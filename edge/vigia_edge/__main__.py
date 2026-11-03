"""VigIA Edge – linha de comando.

  python -m vigia_edge enroll --cloud https://cliente.seudominio.com.br --code ABCD-1234 [--media-dir D:\\vigia]
  python -m vigia_edge run
  python -m vigia_edge status
"""

import argparse
import json
import logging
import sys
from pathlib import Path

import httpx

from . import __version__
from .config import CRED_FILE, check_cloud_url, load, save


def new_client_key() -> tuple[str, bytes]:
    """Chave privada do Edge (P-256) + pedido de certificado para a nuvem assinar."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    key = ec.generate_private_key(ec.SECP256R1())
    csr = (x509.CertificateSigningRequestBuilder()
           .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "vigia-edge")]))
           .sign(key, hashes.SHA256()))
    return (csr.public_bytes(serialization.Encoding.PEM).decode(),
            key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))


def enroll(args) -> int:
    cfg = load()
    try:
        cfg.cloud_url = check_cloud_url(args.cloud)
    except ValueError as exc:
        print(f"Erro: {exc}")
        return 2
    if args.media_dir:
        cfg.media_dir = Path(args.media_dir)
    csr_pem, key_pem = new_client_key()
    try:
        resp = httpx.post(f"{cfg.cloud_url}/api/edge/enroll",
                          json={"code": args.code, "version": __version__, "csr": csr_pem},
                          timeout=20, verify=cfg.verify)
    except httpx.HTTPError as exc:
        print(f"Erro: não foi possível falar com a nuvem ({exc}). Verifique o endereço e se a saída 443 está liberada.")
        return 1
    if resp.status_code != 200:
        print(f"Erro: {resp.json().get('detail', resp.text)}")
        return 1
    data = resp.json()
    cfg.edge_id, cfg.key, cfg.name = data["edge_id"], data["key"], data["name"]
    if data.get("client_cert"):  # mTLS: a chave privada foi gerada aqui e nunca saiu desta máquina
        cfg.client_key.parent.mkdir(parents=True, exist_ok=True)
        cfg.client_key.write_bytes(key_pem)
        try:
            cfg.client_key.chmod(0o600)
        except OSError:
            pass
        cfg.client_cert.write_text(data["client_cert"], encoding="utf-8")
    cfg.retention_days = data.get("retention_days", cfg.retention_days)
    if data.get("media_keys"):
        cfg.media_keys = {k["kid"]: k["key"] for k in data["media_keys"]}
        cfg.active_kid = data["active_kid"]
    save(cfg)
    print(f"\n✔ Edge \"{cfg.name}\" cadastrado (nº {cfg.edge_id}). Credencial salva em {CRED_FILE}")
    print(f"  Imagens serão guardadas em: {cfg.media_dir}"
          + (" (criptografadas, AES-256)" if cfg.active_kid else ""))
    print("\nConfigure o detector desta máquina com:")
    print(f"  BACKEND_URL=http://127.0.0.1:{cfg.listen_port}")
    print(f"  DETECTOR_API_KEY={cfg.detector_key}\n")
    return 0


def run(_args) -> int:
    import uvicorn

    from .app import create_app
    cfg = load()
    if not cfg.enrolled:
        print("Edge ainda não cadastrado. Rode: python -m vigia_edge enroll --cloud <endereço> --code <código>")
        return 2
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    uvicorn.run(create_app(cfg), host=cfg.listen_host, port=cfg.listen_port, log_level="warning")
    return 0


def status(_args) -> int:
    cfg = load()
    try:
        print(json.dumps(httpx.get(f"http://127.0.0.1:{cfg.listen_port}/status", timeout=5).json(), indent=2,
                         ensure_ascii=False))
    except httpx.HTTPError:
        print("O VigIA Edge não está rodando nesta máquina.")
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="vigia_edge", description="VigIA Edge")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("enroll", help="cadastra este Edge na nuvem com o código gerado em Configurações")
    p.add_argument("--cloud", required=True, help="endereço HTTPS da nuvem do cliente")
    p.add_argument("--code", required=True, help="código de instalação (vale 24 h, uso único)")
    p.add_argument("--media-dir", help="pasta do storage do cliente (ex.: D:\\vigia ou \\\\nas\\vigia)")
    p.set_defaults(fn=enroll)
    sub.add_parser("run", help="inicia o Edge").set_defaults(fn=run)
    sub.add_parser("status", help="mostra a saúde do Edge em execução").set_defaults(fn=status)
    args = parser.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
