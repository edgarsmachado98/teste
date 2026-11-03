"""O Edge apresenta o certificado dele numa conexão TLS que exige certificado de cliente (como o Caddy faz)."""

import socket
import ssl
import threading
from datetime import datetime, timedelta, timezone

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID


def _cert(subject, issuer, pub, signer, ca=False, san=None):
    now = datetime.now(timezone.utc)
    b = (x509.CertificateBuilder().subject_name(subject).issuer_name(issuer).public_key(pub)
         .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=1))
         .not_valid_after(now + timedelta(days=1)).add_extension(x509.BasicConstraints(ca=ca, path_length=None), True)
         .add_extension(x509.SubjectKeyIdentifier.from_public_key(pub), False)
         .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(signer.public_key()), False))
    if ca:
        b = b.add_extension(x509.KeyUsage(digital_signature=False, content_commitment=False, key_encipherment=False,
                                          data_encipherment=False, key_agreement=False, key_cert_sign=True,
                                          crl_sign=True, encipher_only=False, decipher_only=False), True)
    if san:
        b = b.add_extension(x509.SubjectAlternativeName([x509.DNSName(san)]), False)
    return b.sign(signer, hashes.SHA256())


def test_edge_presents_client_certificate(tmp_path, monkeypatch):
    monkeypatch.setenv("EDGE_HOME", str(tmp_path))
    import importlib

    import vigia_edge.config as config
    importlib.reload(config)
    from vigia_edge.__main__ import new_client_key
    pem = lambda c: c.public_bytes(serialization.Encoding.PEM)  # noqa: E731
    keypem = lambda k: k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,  # noqa: E731
                                       serialization.NoEncryption())
    # CA da instância e certificado do servidor
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "CA teste")])
    ca = _cert(ca_name, ca_name, ca_key.public_key(), ca_key, ca=True)
    srv_key = ec.generate_private_key(ec.SECP256R1())
    srv = _cert(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")]), ca_name, srv_key.public_key(), ca_key,
                san="localhost")
    (tmp_path / "ca.crt").write_bytes(pem(ca))
    (tmp_path / "srv.crt").write_bytes(pem(srv))
    (tmp_path / "srv.key").write_bytes(keypem(srv_key))
    # Edge: gera chave + CSR; a "nuvem" assina
    csr_pem, edge_key_pem = new_client_key()
    csr = x509.load_pem_x509_csr(csr_pem.encode())
    edge_cert = _cert(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "edge-1")]), ca_name, csr.public_key(), ca_key)
    cfg = config.EdgeConfig(cloud_url="https://localhost", verify=str(tmp_path / "ca.crt"))
    cfg.client_key.write_bytes(edge_key_pem)
    cfg.client_cert.write_bytes(pem(edge_cert))

    server_ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH, cafile=str(tmp_path / "ca.crt"))
    server_ctx.load_cert_chain(tmp_path / "srv.crt", tmp_path / "srv.key")
    server_ctx.verify_mode = ssl.CERT_REQUIRED  # exige certificado do cliente
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(2)
    port = sock.getsockname()[1]
    seen = []

    def serve():
        for _ in range(2):
            conn, _ = sock.accept()
            try:
                with server_ctx.wrap_socket(conn, server_side=True) as tls:
                    seen.append(tls.getpeercert()["subject"])
                    tls.sendall(b"ok")
            except ssl.SSLError as exc:
                seen.append(f"recusado: {exc.reason}")
    threading.Thread(target=serve, daemon=True).start()

    with socket.create_connection(("127.0.0.1", port)) as raw:
        with cfg.ssl_context().wrap_socket(raw, server_hostname="localhost") as tls:
            assert tls.recv(2) == b"ok"
    assert "edge-1" in str(seen[0])
    # sem certificado de cliente a conexão é recusada
    cfg.client_cert.unlink()
    with socket.create_connection(("127.0.0.1", port)) as raw:
        try:
            with cfg.ssl_context().wrap_socket(raw, server_hostname="localhost") as tls:
                tls.recv(2)
        except (ssl.SSLError, ConnectionResetError, OSError):
            pass
    threading.Event().wait(0.3)
    assert "recusado" in str(seen[1])
