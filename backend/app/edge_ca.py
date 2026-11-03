"""Autoridade certificadora (CA) da instância para o mTLS dos VigIA Edge.

No cadastro, o Edge gera a própria chave privada (que nunca sai da máquina dele) e manda um pedido de
certificado (CSR). A CA desta instância assina e guarda a impressão digital. O proxy HTTPS (Caddy) confere
o certificado na conexão e repassa a impressão digital no cabeçalho X-Client-Cert-Sha256; com
EDGE_REQUIRE_MTLS ativo, o servidor só aceita o Edge que apresentar o certificado dele.
Cada cliente tem a sua CA: um certificado de um cliente não abre a instância de outro."""

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from .config import settings

CERT_YEARS = 3


def ca_paths() -> tuple[Path, Path]:
    folder = Path(settings.secret_key_file).parent
    return folder / "edge-ca.crt", folder / "edge-ca.key"


def ensure_ca() -> tuple[x509.Certificate, ec.EllipticCurvePrivateKey]:
    crt_path, key_path = ca_paths()
    if crt_path.exists() and key_path.exists():
        return (x509.load_pem_x509_certificate(crt_path.read_bytes()),
                serialization.load_pem_private_key(key_path.read_bytes(), None))
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, "VigIA"),
                      x509.NameAttribute(NameOID.COMMON_NAME, f"VigIA Edge CA – {settings.company_name or 'instância'}")])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=5))
            .not_valid_after(now + timedelta(days=365 * 20))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .add_extension(x509.KeyUsage(digital_signature=False, content_commitment=False, key_encipherment=False,
                                         data_encipherment=False, key_agreement=False, key_cert_sign=True,
                                         crl_sign=True, encipher_only=False, decipher_only=False), critical=True)
            .sign(key, hashes.SHA256()))
    crt_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
    try:
        key_path.chmod(0o600)
    except OSError:
        pass
    crt_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return cert, key


def fingerprint(cert: x509.Certificate) -> str:
    return hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()


def sign_csr(csr_pem: str, edge_id: int, edge_name: str) -> tuple[str, str, str]:
    """Assina o pedido do Edge. Devolve (certificado PEM, CA PEM, impressão digital SHA-256)."""
    csr = x509.load_pem_x509_csr(csr_pem.encode())
    if not csr.is_signature_valid:
        raise ValueError("pedido de certificado inválido")
    if not isinstance(csr.public_key(), ec.EllipticCurvePublicKey):
        raise ValueError("use chave de curva elíptica (P-256)")
    ca_cert, ca_key = ensure_ca()
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, "VigIA Edge"),
                                     x509.NameAttribute(NameOID.COMMON_NAME, f"edge-{edge_id}"),
                                     x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, edge_name[:60])]))
            .issuer_name(ca_cert.subject).public_key(csr.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=365 * CERT_YEARS))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]), critical=False)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(csr.public_key()), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256()))
    return (cert.public_bytes(serialization.Encoding.PEM).decode(),
            ca_cert.public_bytes(serialization.Encoding.PEM).decode(), fingerprint(cert))


def normalize(value: str | None) -> str:
    return (value or "").replace(":", "").replace(" ", "").strip().lower()
