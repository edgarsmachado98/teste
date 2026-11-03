"""Acesso direto pela rede da fábrica.

Quem está dentro da planta abre a imagem e o clipe direto do Edge (rápido e sem gastar a internet do
cliente). Para o navegador aceitar (a página do VigIA é HTTPS), o Edge serve em HTTPS com um certificado
emitido pela CA do cliente para os IPs da rede local; a TI instala essa CA nos computadores da empresa
(uma vez, por política de grupo). Cada link vale poucos minutos e é assinado pela nuvem: ninguém na rede
consegue listar ou baixar imagens sem ter aberto a ocorrência no painel.
Se o computador não confiar na CA ou não alcançar o Edge, a tela usa o túnel automaticamente."""

import asyncio
import contextlib
import hashlib
import hmac
import ipaddress
import json
import logging
import socket
import time
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, Response

log = logging.getLogger("vigia.edge.lan")

CHECK_EVERY = 6 * 3600
MEDIA_TYPES = {".jpg": "image/jpeg", ".webm": "video/webm"}


def lan_ips() -> list[str]:
    """IPv4 privados desta máquina (os que os computadores da fábrica alcançam)."""
    found = []
    try:
        import psutil
        for addrs in psutil.net_if_addrs().values():
            for a in addrs:
                if a.family == socket.AF_INET:
                    found.append(a.address)
    except Exception:  # noqa: BLE001
        pass
    with contextlib.suppress(OSError):  # IP da rota padrão (sem enviar nada)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        found.append(s.getsockname()[0])
        s.close()
    ips = []
    for ip in found:
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if addr.is_private and not addr.is_loopback and not addr.is_link_local and ip not in ips:
            ips.append(ip)
    return ips[:8]


def sign(key: bytes, edge_id: int, rel: str, exp: int) -> str:
    return hmac.new(key, f"{edge_id}|{rel}|{exp}".encode(), hashlib.sha256).hexdigest()


def create_lan_app(cfg, store, lan_key: bytes) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/ping")
    def ping():
        # a tela testa se este computador alcança o Edge e confia no certificado
        return JSONResponse({"ok": True, "edge": cfg.edge_id}, headers={"Access-Control-Allow-Origin": "*",
                                                                         "Cache-Control": "no-store"})

    @app.get("/m/{rel:path}")
    def media(rel: str, e: int, s: str):
        if e < time.time() or e > time.time() + 3600:
            raise HTTPException(403, "link vencido – abra a ocorrência de novo")
        if not hmac.compare_digest(s, sign(lan_key, cfg.edge_id, rel, e)):
            raise HTTPException(403, "link inválido")
        data = store.read(rel)
        if data is None:
            raise HTTPException(404, "arquivo não encontrado")
        ext = rel[rel.rfind("."):].lower()
        return Response(data, media_type=MEDIA_TYPES.get(ext, "application/octet-stream"),
                        headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"})

    return app


class _QuietServer:
    """uvicorn dentro do mesmo processo do Edge, sem capturar os sinais do processo principal."""

    def __init__(self, app, port, certfile, keyfile):
        import uvicorn

        class Server(uvicorn.Server):
            def capture_signals(self):  # noqa: D401
                return contextlib.nullcontext()

        self.server = Server(uvicorn.Config(app, host="0.0.0.0", port=port, ssl_certfile=str(certfile),
                                            ssl_keyfile=str(keyfile), log_level="warning"))
        self.task = asyncio.create_task(self.server.serve())

    async def stop(self):
        self.server.should_exit = True
        with contextlib.suppress(Exception):
            await asyncio.wait_for(self.task, 10)


class LanAccess:
    def __init__(self, cfg, store, client: httpx.AsyncClient):
        self.cfg, self.store, self.client = cfg, store, client
        self.server: _QuietServer | None = None
        self.ips: list[str] = []
        self.error = ""

    @property
    def files(self):
        h = self.cfg.client_cert.parent
        return h / "lan.crt", h / "lan.key", h / "lan.json"

    def status(self) -> dict:
        return {"lan": {"ips": self.ips, "port": self.cfg.lan_port, "ready": self.server is not None,
                        "error": self.error}}

    def _cert_ok(self, ips: list[str]) -> bool:
        crt, key, meta = self.files
        if not (crt.exists() and key.exists() and meta.exists()):
            return False
        from cryptography import x509
        cert = x509.load_pem_x509_certificate(crt.read_bytes())
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        have = {str(i) for i in san.get_values_for_type(x509.IPAddress)}
        return set(ips) <= have and cert.not_valid_after_utc > datetime.now(timezone.utc) + timedelta(days=30)

    async def _issue(self, ips: list[str]) -> None:
        """Pede à nuvem o certificado de servidor para os IPs da rede local (chave gerada aqui)."""
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID
        crt, keyf, meta = self.files
        key = ec.generate_private_key(ec.SECP256R1())
        csr = (x509.CertificateSigningRequestBuilder()
               .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "vigia-edge-lan")]))
               .sign(key, hashes.SHA256()))
        resp = await self.client.post("/api/edge/lan", json={
            "csr": csr.public_bytes(serialization.Encoding.PEM).decode(), "ips": ips, "hostname": socket.gethostname()})
        resp.raise_for_status()
        data = resp.json()
        keyf.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
        with contextlib.suppress(OSError):
            keyf.chmod(0o600)
        crt.write_text(data["cert"], encoding="utf-8")
        meta.write_text(json.dumps({"lan_key": data["lan_key"]}), encoding="utf-8")
        with contextlib.suppress(OSError):
            meta.chmod(0o600)

    async def run(self) -> None:
        while True:
            try:
                ips = await asyncio.to_thread(lan_ips)
                changed = ips != self.ips
                self.ips = ips
                if ips and not self._cert_ok(ips):
                    await self._issue(ips)
                    changed = True
                crt, keyf, meta = self.files
                if ips and crt.exists() and (changed or self.server is None):
                    if self.server:
                        await self.server.stop()
                    lan_key = bytes.fromhex(json.loads(meta.read_text())["lan_key"])
                    self.server = _QuietServer(create_lan_app(self.cfg, self.store, lan_key), self.cfg.lan_port,
                                               crt, keyf)
                    log.info("acesso direto na rede local: https://%s:%s", ips[0], self.cfg.lan_port)
                self.error = ""
            except (httpx.HTTPError, OSError, ValueError, KeyError) as exc:
                self.error = str(exc)[:200]
                log.warning("acesso direto na rede local indisponível: %s", exc)
                await asyncio.sleep(300)
                continue
            await asyncio.sleep(CHECK_EVERY)
