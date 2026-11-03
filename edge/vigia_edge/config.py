"""Configuração do Edge: credencial (edge.json, criada no cadastro) + variáveis de ambiente."""

import json
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

HOME = Path(os.getenv("EDGE_HOME", Path.cwd() / "edge-data"))
CRED_FILE = HOME / "edge.json"


@dataclass
class EdgeConfig:
    cloud_url: str = ""
    edge_id: int = 0
    key: str = ""
    name: str = ""
    # Chave que o detector local usa para falar com o Edge (gerada no cadastro)
    detector_key: str = field(default_factory=lambda: secrets.token_urlsafe(24))
    retention_days: int = 90
    # Chaves das imagens (AES-256): {id: chave base64}; a ativa cifra o que for gravado agora
    media_keys: dict = field(default_factory=dict)
    active_kid: str = ""
    # Storage do cliente (pasta local, unidade mapeada ou caminho de rede montado)
    media_dir: Path = field(default_factory=lambda: Path(os.getenv("EDGE_MEDIA_DIR", HOME / "midia")))
    # Fila de envio para a nuvem e quadros ao vivo: ficam no disco da própria caixa
    outbox_dir: Path = field(default_factory=lambda: HOME / "fila")
    live_dir: Path = field(default_factory=lambda: HOME / "ao-vivo")
    listen_host: str = os.getenv("EDGE_HOST", "127.0.0.1")
    listen_port: int = int(os.getenv("EDGE_PORT", "8100"))
    # Acesso direto pela rede da fábrica (HTTPS); 0 desliga
    lan_port: int = field(default_factory=lambda: int(os.getenv("EDGE_LAN_PORT", "8443")))
    # certificado próprio da nuvem (ex.: teste com o servidor local em HTTPS), se houver
    verify: str | bool = field(default_factory=lambda: os.getenv("EDGE_CLOUD_CA") or True)

    @property
    def enrolled(self) -> bool:
        return bool(self.cloud_url and self.edge_id and self.key)

    @property
    def auth_headers(self) -> dict:
        return {"X-Edge-Id": str(self.edge_id), "X-Edge-Key": self.key}

    @property
    def client_cert(self) -> Path:
        return HOME / "edge-cliente.crt"

    @property
    def client_key(self) -> Path:
        return HOME / "edge-cliente.key"

    def ssl_context(self):
        """TLS para a nuvem: confia na nuvem (certificado público ou o local de teste) e apresenta o
        certificado deste Edge (mTLS), quando houver."""
        import ssl
        ctx = ssl.create_default_context(cafile=self.verify if isinstance(self.verify, str) else None)
        if self.client_cert.exists() and self.client_key.exists():
            ctx.load_cert_chain(self.client_cert, self.client_key)
        return ctx

    @property
    def ws_url(self) -> str:
        base = self.cloud_url.rstrip("/")
        return ("wss://" + base[8:] if base.startswith("https://") else "ws://" + base[7:]) + "/api/edge/tunnel"


def check_cloud_url(url: str) -> str:
    """Exige HTTPS (o túnel leva imagens de pessoas). HTTP só para testes na própria máquina."""
    url = url.strip().rstrip("/")
    if url.startswith("https://"):
        return url
    host = url.split("://", 1)[-1].split("/")[0].split(":")[0]
    if url.startswith("http://") and (host in ("localhost", "127.0.0.1") or os.getenv("EDGE_ALLOW_INSECURE") == "1"):
        return url
    raise ValueError("use o endereço HTTPS da nuvem (ex.: https://cliente.seudominio.com.br)")


def load() -> EdgeConfig:
    cfg = EdgeConfig()
    if CRED_FILE.exists():
        data = json.loads(CRED_FILE.read_text(encoding="utf-8"))
        for key in ("cloud_url", "edge_id", "key", "name", "detector_key", "retention_days", "media_keys", "active_kid"):
            if key in data:
                setattr(cfg, key, data[key])
        if data.get("media_dir") and not os.getenv("EDGE_MEDIA_DIR"):
            cfg.media_dir = Path(data["media_dir"])
    return cfg


def save(cfg: EdgeConfig) -> None:
    HOME.mkdir(parents=True, exist_ok=True)
    data = {"cloud_url": cfg.cloud_url, "edge_id": cfg.edge_id, "key": cfg.key, "name": cfg.name,
            "detector_key": cfg.detector_key, "retention_days": cfg.retention_days, "media_dir": str(cfg.media_dir),
            "media_keys": cfg.media_keys, "active_kid": cfg.active_kid}
    tmp = CRED_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)  # só o usuário do serviço lê a credencial
    except OSError:
        pass
    tmp.replace(CRED_FILE)
