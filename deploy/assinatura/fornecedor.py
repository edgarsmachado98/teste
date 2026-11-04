"""Ferramenta do fornecedor: chaves de assinatura e pacotes de atualização do VigIA Edge.

  python fornecedor.py gerar-chaves                 # uma vez; guarde fornecedor.key em local seguro
  python fornecedor.py empacotar --versao 1.1.0     # gera pacotes/vigia-edge-1.1.0.zip + .sig

Os Edges só instalam pacotes assinados com a chave privada do fornecedor (Ed25519). A chave pública vai
dentro do Edge (vigia_edge/fornecedor.pub). Nem a nuvem nem quem invadir a nuvem consegue fabricar uma
atualização: sem a chave privada, o Edge recusa o pacote."""

import argparse
import base64
import hashlib
import io
import json
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
KEY_FILE = HERE / "fornecedor.key"
PUB_FILE = ROOT / "edge" / "vigia_edge" / "fornecedor.pub"
SOURCES = {"vigia_edge": ROOT / "edge" / "vigia_edge", "vigia_detector": ROOT / "detector" / "vigia_detector"}
REQUIREMENTS = {"requirements-edge.txt": ROOT / "edge" / "requirements.txt",
                "requirements-detector.txt": ROOT / "detector" / "requirements.txt"}
# requirements-ultralytics.txt não entra no pacote: a planta só instala a Ultralytics se usar modelos .pt


def generate_keys(key_file: Path = KEY_FILE, pub_file: Path = PUB_FILE) -> None:
    if key_file.exists():
        sys.exit(f"{key_file} já existe – não sobrescrevo (os Edges instalados confiam nela).")
    key = Ed25519PrivateKey.generate()
    key_file.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
    key_file.chmod(0o600)
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    pub_file.write_text(base64.b64encode(raw).decode() + "\n", encoding="utf-8")
    print(f"✔ Chave privada: {key_file}  (FAÇA BACKUP e não coloque no git nem no servidor)")
    print(f"✔ Chave pública: {pub_file}  (vai junto do Edge – faça commit)")


def build_package(version: str, key_file: Path = KEY_FILE, out_dir: Path = HERE / "pacotes",
                  sources: dict | None = None, requirements: dict | None = None) -> tuple[Path, Path]:
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("versão no formato 1.2.3")
    key = serialization.load_pem_private_key(key_file.read_bytes(), None)
    files: dict[str, bytes] = {}
    for pkg, src in (sources or SOURCES).items():
        for path in sorted(src.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                data = path.read_bytes()
                rel = f"{pkg}/{path.relative_to(src).as_posix()}"
                if rel == "vigia_edge/__init__.py":  # a versão do pacote é a versão do Edge
                    data = re.sub(rb'__version__ = "[^"]*"', f'__version__ = "{version}"'.encode(), data)
                files[rel] = data
    for name, src in (requirements or REQUIREMENTS).items():
        files[name] = src.read_bytes()
    manifest = {"app": "vigia-edge", "version": version, "created_at": datetime.now(timezone.utc).isoformat(),
                "files": {k: hashlib.sha256(v).hexdigest() for k, v in files.items()}}
    manifest_bytes = json.dumps(manifest, indent=1, sort_keys=True).encode()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", manifest_bytes)
        for name, data in files.items():
            zf.writestr(name, data)
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / f"vigia-edge-{version}.zip"
    sig_path = out_dir / f"vigia-edge-{version}.sig"
    zip_path.write_bytes(buf.getvalue())
    # assina o manifesto (que traz o SHA-256 de cada arquivo)
    sig_path.write_text(base64.b64encode(key.sign(manifest_bytes)).decode(), encoding="utf-8")
    return zip_path, sig_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Ferramenta do fornecedor – VigIA Edge")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("gerar-chaves")
    p = sub.add_parser("empacotar")
    p.add_argument("--versao", required=True)
    p.add_argument("--chave", default=str(KEY_FILE))
    p.add_argument("--saida", default=str(HERE / "pacotes"))
    args = parser.parse_args()
    if args.cmd == "gerar-chaves":
        generate_keys()
    else:
        z, s = build_package(args.versao, Path(args.chave), Path(args.saida))
        print(f"✔ {z}\n✔ {s}\nPublique nos clientes: deploy/nuvem/clientes.sh publicar-edge {z}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
