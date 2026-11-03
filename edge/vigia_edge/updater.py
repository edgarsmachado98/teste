"""Atualização remota do Edge (e do detector da planta).

1. A nuvem avisa (botão "Atualizar" ou atualização automática) ou o Edge verifica sozinho.
2. O Edge baixa o pacote e a assinatura e confere com a chave pública do fornecedor (Ed25519):
   pacote alterado ou de outra origem é recusado.
3. Confere o SHA-256 de cada arquivo, extrai numa pasta da versão (sem tocar na versão em uso) e
   encerra com o código 75. O inicializador (planta.py) sobe a versão nova e, se ela não conectar
   na nuvem em alguns minutos, volta sozinho para a anterior."""

import base64
import hashlib
import io
import json
import logging
import os
import zipfile
from pathlib import Path, PurePosixPath

import httpx

from . import __version__

log = logging.getLogger("vigia.edge.update")

EXIT_UPDATED = 75
PUB_FILE = Path(__file__).with_name("fornecedor.pub")


class UpdateError(Exception):
    pass


def parse(v: str) -> tuple:
    try:
        return tuple(int(x) for x in v.split("."))
    except ValueError:
        return (0,)


def vendor_key():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    path = Path(os.getenv("EDGE_FORNECEDOR_PUB") or PUB_FILE)
    if not path.exists():
        raise UpdateError("atualização remota desativada: este Edge não tem a chave pública do fornecedor")
    return Ed25519PublicKey.from_public_bytes(base64.b64decode(path.read_text().strip()))


def verify_and_extract(zip_bytes: bytes, signature_b64: str, versions_dir: Path) -> tuple[str, Path]:
    """Confere assinatura e integridade e extrai em versions_dir/<versão>. Devolve (versão, pasta)."""
    from cryptography.exceptions import InvalidSignature
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
        manifest_bytes = zf.read("manifest.json")
    except (zipfile.BadZipFile, KeyError) as exc:
        raise UpdateError("pacote corrompido") from exc
    try:
        vendor_key().verify(base64.b64decode(signature_b64), manifest_bytes)
    except (InvalidSignature, ValueError) as exc:
        raise UpdateError("assinatura inválida: pacote recusado") from exc
    manifest = json.loads(manifest_bytes)
    version = manifest.get("version", "")
    if manifest.get("app") != "vigia-edge" or parse(version) == (0,):
        raise UpdateError("manifesto inválido")
    names = set(zf.namelist()) - {"manifest.json"}
    if names != set(manifest["files"]):
        raise UpdateError("arquivos do pacote não conferem com o manifesto")
    target = versions_dir / version
    tmp = versions_dir / f".{version}.tmp"
    if tmp.exists():
        import shutil
        shutil.rmtree(tmp)
    for name, digest in manifest["files"].items():
        p = PurePosixPath(name)
        if p.is_absolute() or ".." in p.parts or "\\" in name:
            raise UpdateError(f"caminho inválido no pacote: {name}")
        data = zf.read(name)
        if hashlib.sha256(data).hexdigest() != digest:
            raise UpdateError(f"arquivo alterado: {name}")
        out = tmp / Path(*p.parts)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
    if target.exists():
        import shutil
        shutil.rmtree(target)
    tmp.replace(target)
    return version, target


def state_file(home: Path) -> Path:
    return home / "versao.json"


def read_state(home: Path) -> dict:
    try:
        return json.loads(state_file(home).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_state(home: Path, state: dict) -> None:
    tmp = state_file(home).with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1), encoding="utf-8")
    tmp.replace(state_file(home))


class Updater:
    def __init__(self, cfg, client: httpx.AsyncClient, home: Path):
        self.cfg, self.client, self.home = cfg, client, home
        self.state = "ok"
        self.message = ""

    def status(self) -> dict:
        return {"update": {"state": self.state, "message": self.message}}

    async def check_and_install(self) -> bool:
        """True se instalou uma versão nova (o processo deve encerrar com EXIT_UPDATED)."""
        import asyncio
        try:
            latest = (await self.client.get("/api/edge/update/latest")).json()
            version = latest.get("version")
            if not version or parse(version) <= parse(__version__):
                self.state, self.message = "ok", "versão mais recente"
                return False
            if version in read_state(self.home).get("failed", []):
                self.state, self.message = "erro", f"{version} falhou antes e foi revertida; aguardando nova versão"
                return False
            self.state, self.message = "baixando", version
            zip_resp = await self.client.get(f"/api/edge/update/{version}.zip", timeout=300)
            sig_resp = await self.client.get(f"/api/edge/update/{version}.sig")
            zip_resp.raise_for_status()
            sig_resp.raise_for_status()
            versions = self.home / "versoes"
            versions.mkdir(parents=True, exist_ok=True)
            got, _path = await asyncio.to_thread(verify_and_extract, zip_resp.content, sig_resp.text, versions)
            if got != version:
                raise UpdateError("versão do pacote diferente da anunciada")
            state = read_state(self.home)
            state["pending"] = version
            write_state(self.home, state)
            self.state, self.message = "instalado", f"{version} – reiniciando"
            log.info("versão %s instalada; reiniciando para aplicar", version)
            return True
        except UpdateError as exc:
            self.state, self.message = "erro", str(exc)
            log.error("atualização recusada: %s", exc)
        except (httpx.HTTPError, ValueError) as exc:
            self.state, self.message = "erro", f"falha ao baixar: {exc}"[:200]
            log.warning("falha ao verificar atualização: %s", exc)
        return False
