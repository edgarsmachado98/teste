#!/usr/bin/env python3
"""Inicia o VigIA com um único comando:  python vigia.py

Na primeira vez cria o ambiente (.venv), instala as dependências e gera o .env com uma
chave aleatória para o detector. Depois sobe o servidor e o detector juntos e abre o painel.

Outros modos:
  python vigia.py --servico              roda sem janela/navegador, com log em logs/ e reinício automático
  python vigia.py --instalar-servico     Windows: inicia o VigIA junto com o computador (como administrador)
  python vigia.py --remover-servico      Windows: remove a inicialização automática
  python vigia.py --gerar-certificado    cria o certificado HTTPS da instalação (pasta certs/)
"""

import argparse
import hashlib
import ipaddress
import os
import secrets
import signal
import socket
import ssl
import subprocess
import sys
import time
import urllib.request
import venv
import webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
REQUIREMENTS = [ROOT / "backend" / "requirements.txt", ROOT / "detector" / "requirements.txt"]
CERT_DIR = ROOT / "certs"
LOG_DIR = ROOT / "logs"
TASK_NAME = "VigIA"


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def in_venv() -> bool:
    return Path(sys.prefix).resolve() == VENV.resolve()


def ensure_venv() -> Path:
    python = venv_python()
    if not python.exists():
        print("Criando o ambiente Python (.venv)...")
        venv.create(VENV, with_pip=True)

    digest = hashlib.sha256(b"".join(p.read_bytes() for p in REQUIREMENTS)).hexdigest()
    marker = VENV / ".requisitos-instalados"
    if not marker.exists() or marker.read_text() != digest:
        print("Instalando as dependências. Na primeira vez isso leva alguns minutos...")
        args = [str(python), "-m", "pip", "install", "--disable-pip-version-check"]
        for req in REQUIREMENTS:
            args += ["-r", str(req)]
        subprocess.check_call(args)
        marker.write_text(digest)
    return python


def ensure_env() -> dict[str, str]:
    env_file = ROOT / ".env"
    if not env_file.exists():
        text = (ROOT / ".env.example").read_text(encoding="utf-8")
        text = text.replace("DETECTOR_API_KEY=troque-esta-chave", f"DETECTOR_API_KEY={secrets.token_urlsafe(24)}")
        env_file.write_text(text, encoding="utf-8")
        print("Arquivo .env criado. Edite-o para configurar e-mail e WhatsApp.")

    values = {}
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


# ---------- HTTPS ----------

def tls_files(config: dict) -> tuple[Path, Path, Path | None] | None:
    """(certificado, chave, CA) se houver HTTPS configurado."""
    if config.get("SSL_CERTFILE") and config.get("SSL_KEYFILE"):
        ca = config.get("SSL_CAFILE")
        return Path(config["SSL_CERTFILE"]), Path(config["SSL_KEYFILE"]), Path(ca) if ca else None
    cert, key, ca = CERT_DIR / "vigia.crt", CERT_DIR / "vigia.key", CERT_DIR / "vigia-ca.crt"
    if cert.exists() and key.exists():
        return cert, key, ca if ca.exists() else None
    return None


def generate_certificate(extra_names: list[str]) -> None:
    """Cria uma autoridade certificadora (CA) local e um certificado de servidor assinado por ela.

    Instalando certs/vigia-ca.crt nos computadores da empresa, o navegador passa a confiar no
    painel sem avisos. O detector usa a mesma CA para validar a conexão."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    CERT_DIR.mkdir(exist_ok=True)
    now = datetime.now(timezone.utc)
    ca_key_path, ca_path = CERT_DIR / "vigia-ca.key", CERT_DIR / "vigia-ca.crt"

    if ca_path.exists() and ca_key_path.exists():
        ca_key = serialization.load_pem_private_key(ca_key_path.read_bytes(), None)
        ca_cert = x509.load_pem_x509_certificate(ca_path.read_bytes())
    else:
        ca_key = ec.generate_private_key(ec.SECP256R1())
        ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"VigIA CA local ({socket.gethostname()})")])
        ca_cert = (
            x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name).public_key(ca_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True,
                                         content_commitment=False, key_encipherment=False, data_encipherment=False,
                                         key_agreement=False, encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256())
        )
        ca_key_path.write_bytes(ca_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                      serialization.NoEncryption()))
        ca_path.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))

    hostname = socket.gethostname()
    names = {"localhost", hostname, *extra_names}
    ips = {"127.0.0.1"}
    try:
        ips.update(socket.gethostbyname_ex(hostname)[2])
    except OSError:
        pass
    alt = [x509.DNSName(n) for n in sorted(names) if n] + [x509.IPAddress(ipaddress.ip_address(i)) for i in sorted(ips)]

    key = ec.generate_private_key(ec.SECP256R1())
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)]))
        .issuer_name(ca_cert.subject).public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=825))
        .add_extension(x509.SubjectAlternativeName(alt), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.KeyUsage(digital_signature=True, key_encipherment=False, content_commitment=False,
                                     data_encipherment=False, key_agreement=False, key_cert_sign=False,
                                     crl_sign=False, encipher_only=False, decipher_only=False), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    (CERT_DIR / "vigia.key").write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                           serialization.NoEncryption()))
    (CERT_DIR / "vigia.crt").write_bytes(cert.public_bytes(serialization.Encoding.PEM))

    print("Certificado HTTPS criado em certs/ para:", ", ".join(sorted(names) + sorted(ips)))
    print("\nPróximos passos:")
    print(f"  1. Ajuste PUBLIC_URL no .env para https://{hostname}:<porta> (links dos e-mails).")
    print("  2. Para o navegador não mostrar aviso, instale certs/vigia-ca.crt nos computadores que acessam")
    print("     o painel (Windows: duplo clique > Instalar certificado > Máquina local >")
    print("     'Autoridades de Certificação Raiz Confiáveis').")
    print("  3. Guarde certs/vigia-ca.key em local seguro: com ela é possível emitir certificados confiáveis.")
    print("  4. Reinicie o VigIA.")


# ---------- Execução ----------

def ssl_context(ca: Path | None) -> ssl.SSLContext:
    ctx = ssl.create_default_context(cafile=str(ca)) if ca else ssl.create_default_context()
    return ctx


def wait_until_up(url: str, process: subprocess.Popen, ca: Path | None = None, timeout: float = 60) -> bool:
    deadline = time.time() + timeout
    context = ssl_context(ca) if url.startswith("https") else None
    while time.time() < deadline:
        if process.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(url, timeout=2, context=context):
                return True
        except OSError:
            time.sleep(0.5)
    return False


def stop(*processes) -> None:
    for p in processes:
        if p and p.poll() is None:
            p.terminate()
    for p in processes:
        if p:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()


_JOB = None


def bind_to_parent(proc: subprocess.Popen) -> None:
    """Windows: se o VigIA for encerrado à força (ex.: pelo Agendador), os processos filhos
    também terminam, em vez de ficarem órfãos ocupando a porta e a câmera."""
    global _JOB
    if os.name != "nt":
        return
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        if _JOB is None:
            class Basic(ctypes.Structure):
                _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                            ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                            ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                            ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                            ("SchedulingClass", wintypes.DWORD)]

            class IoCounters(ctypes.Structure):
                _fields_ = [(n, ctypes.c_uint64) for n in ("r", "w", "o", "rb", "wb", "ob")]

            class Extended(ctypes.Structure):
                _fields_ = [("Basic", Basic), ("Io", IoCounters), ("ProcessMemoryLimit", ctypes.c_size_t),
                            ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                            ("PeakJobMemoryUsed", ctypes.c_size_t)]

            kernel32.CreateJobObjectW.restype = wintypes.HANDLE
            job = kernel32.CreateJobObjectW(None, None)
            info = Extended()
            info.Basic.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            kernel32.SetInformationJobObject(wintypes.HANDLE(job), 9, ctypes.byref(info), ctypes.sizeof(info))
            _JOB = job
        kernel32.AssignProcessToJobObject(wintypes.HANDLE(_JOB), wintypes.HANDLE(int(proc._handle)))
    except Exception:
        pass  # sem isso o sistema funciona; só não limpa filhos em encerramento forçado


class Stack:
    """Servidor + detector, com a configuração de rede (HTTP/HTTPS)."""

    def __init__(self, config: dict, output=None):
        self.config = config
        self.output = output
        self.host = os.getenv("HOST") or config.get("HOST") or "127.0.0.1"
        self.port = os.getenv("PORT") or config.get("PORT") or "8000"
        self.tls = tls_files(config)
        scheme = "https" if self.tls else "http"
        self.local_url = f"{scheme}://localhost:{self.port}"
        self.env = {**os.environ, **config, "BACKEND_URL": self.local_url,
                    "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
        if self.tls and self.tls[2]:
            self.env["BACKEND_CA"] = str(self.tls[2])
        self.backend = self.detector = None

    def _popen(self, args, cwd):
        kwargs = {"cwd": cwd, "env": self.env}
        if self.output:
            kwargs.update(stdout=self.output, stderr=subprocess.STDOUT)
        proc = subprocess.Popen(args, **kwargs)
        bind_to_parent(proc)
        return proc

    def start_backend(self) -> bool:
        args = [sys.executable, "-m", "uvicorn", "app.main:app", "--host", self.host, "--port", self.port,
                "--log-level", "warning"]
        if self.tls:
            args += ["--ssl-certfile", str(self.tls[0]), "--ssl-keyfile", str(self.tls[1])]
        self.backend = self._popen(args, ROOT / "backend")
        ca = self.tls[2] if self.tls else None
        return wait_until_up(f"{self.local_url}/api/health", self.backend, ca)

    def start_detector(self) -> None:
        self.detector = self._popen([sys.executable, "-m", "vigia_detector.main"], ROOT / "detector")

    def stop(self) -> None:
        stop(self.detector, self.backend)


def run_interactive() -> int:
    stack = Stack(ensure_env())
    print("Iniciando o servidor...")
    if not stack.start_backend():
        print(f"\nO servidor não iniciou. A porta {stack.port} pode estar em uso: feche outro VigIA aberto")
        print("(ou pare o serviço com 'python vigia.py --remover-servico') ou defina outra porta no .env (PORT=8001).")
        stack.stop()
        return 1
    print("Iniciando o detector de IA...")
    stack.start_detector()

    url = f"{stack.local_url}/"
    print("\n" + "=" * 60)
    print(f"  VigIA rodando em {url}")
    print("  No primeiro acesso, crie o usuário administrador na tela.")
    print("  Para encerrar, pressione Ctrl+C nesta janela.")
    print("=" * 60 + "\n")
    webbrowser.open(url)

    try:
        while stack.backend.poll() is None:
            if stack.detector.poll() is not None:
                print("\nO detector parou (veja o erro acima). O painel continua funcionando;")
                print("corrija o problema e reinicie o VigIA.\n")
                stack.backend.wait()
                break
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nEncerrando o VigIA...")
    finally:
        stack.stop()
    return 0


def run_service() -> int:
    """Modo serviço: sem navegador, log em arquivo e reinício automático dos componentes."""
    LOG_DIR.mkdir(exist_ok=True)
    log_path = LOG_DIR / "vigia.log"
    if log_path.exists() and log_path.stat().st_size > 20 * 1024 * 1024:
        log_path.replace(LOG_DIR / "vigia.log.1")
    log = open(log_path, "a", encoding="utf-8", buffering=1)

    def say(msg):
        log.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} [vigia] {msg}\n")

    def on_terminate(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, on_terminate)
    stack = Stack(ensure_env(), output=log)
    say(f"iniciando em modo serviço ({stack.local_url})")
    backoff = 5
    detector_retry_at = 0.0
    try:
        while True:
            if stack.backend is None or stack.backend.poll() is not None:
                if stack.backend is not None:
                    say(f"servidor parou (código {stack.backend.returncode}); reiniciando")
                stop(stack.detector)
                stack.detector = None
                if not stack.start_backend():
                    say(f"servidor não iniciou; nova tentativa em {backoff}s")
                    stop(stack.backend)
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 300)
                    continue
                say("servidor ativo")
                backoff = 5
            if stack.detector is not None and stack.detector.poll() is not None:
                say(f"detector parou (código {stack.detector.returncode}); reiniciando em 15s")
                stack.detector = None
                detector_retry_at = time.monotonic() + 15
            if stack.detector is None and time.monotonic() >= detector_retry_at:
                stack.start_detector()
                say("detector ativo")
            time.sleep(2)
    except KeyboardInterrupt:
        pass
    finally:
        say("encerrando")
        stack.stop()
    return 0


# ---------- Inicialização automática ----------

def task_xml(python: Path) -> str:
    def esc(s):
        return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>VigIA - monitoramento de segurança (servidor e detector)</Description></RegistrationInfo>
  <Triggers><BootTrigger><Enabled>true</Enabled><Delay>PT30S</Delay></BootTrigger></Triggers>
  <Principals><Principal id="Author"><UserId>S-1-5-18</UserId><RunLevel>HighestAvailable</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <RestartOnFailure><Interval>PT1M</Interval><Count>999</Count></RestartOnFailure>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{esc(python)}</Command>
      <Arguments>"{esc(ROOT / 'vigia.py')}" --servico</Arguments>
      <WorkingDirectory>{esc(ROOT)}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def install_service() -> int:
    python = ensure_venv()
    ensure_env()
    if os.name != "nt":
        unit = f"""[Unit]
Description=VigIA - monitoramento de segurança
After=network-online.target

[Service]
WorkingDirectory={ROOT}
ExecStart={python} {ROOT / 'vigia.py'} --servico
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
"""
        (ROOT / "vigia.service").write_text(unit)
        print("Arquivo vigia.service criado. Para instalar (Linux com systemd), execute como root:")
        print(f"  cp {ROOT / 'vigia.service'} /etc/systemd/system/ && systemctl enable --now vigia")
        return 0

    xml_path = ROOT / "vigia-tarefa.xml"
    xml_path.write_text(task_xml(python), encoding="utf-16")
    result = subprocess.run(["schtasks", "/Create", "/TN", TASK_NAME, "/XML", str(xml_path), "/F"],
                            capture_output=True, text=True)
    xml_path.unlink(missing_ok=True)
    if result.returncode != 0:
        print(result.stdout + result.stderr)
        print("Não foi possível criar a tarefa. Execute como administrador (clique direito > Executar como administrador).")
        return 1
    subprocess.run(["schtasks", "/Run", "/TN", TASK_NAME], capture_output=True)
    print("VigIA instalado para iniciar junto com o Windows (mesmo sem ninguém logado) e já iniciado.")
    print(f"Log: {LOG_DIR / 'vigia.log'}")
    print("Observação: o serviço roda como SYSTEM; prefira câmeras IP (RTSP). Webcams USB podem não ser acessíveis.")
    return 0


def remove_service() -> int:
    if os.name != "nt":
        print("Linux: systemctl disable --now vigia && rm /etc/systemd/system/vigia.service")
        return 0
    subprocess.run(["schtasks", "/End", "/TN", TASK_NAME], capture_output=True)
    result = subprocess.run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"], capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stdout + result.stderr)
        print("Não foi possível remover. Execute como administrador.")
        return 1
    print("Inicialização automática removida e VigIA parado.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="VigIA – gestão de segurança industrial")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--servico", action="store_true", help="roda em segundo plano (usado pela inicialização automática)")
    group.add_argument("--instalar-servico", action="store_true", help="inicia o VigIA junto com o computador")
    group.add_argument("--remover-servico", action="store_true", help="remove a inicialização automática")
    group.add_argument("--gerar-certificado", action="store_true", help="cria o certificado HTTPS em certs/")
    parser.add_argument("--nome", action="append", default=[], help="nome extra no certificado (ex.: vigia.empresa.local)")
    args = parser.parse_args()

    if args.instalar_servico:
        return install_service()
    if args.remover_servico:
        return remove_service()

    if not in_venv():
        python = ensure_venv()
        try:
            return subprocess.call([str(python), str(Path(__file__).resolve()), *sys.argv[1:]])
        except KeyboardInterrupt:
            return 0
    if args.gerar_certificado:
        generate_certificate(args.nome)
        return 0
    return run_service() if args.servico else run_interactive()


if __name__ == "__main__":
    sys.exit(main())
