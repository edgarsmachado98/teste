#!/usr/bin/env python3
"""Inicia o VigIA com um único comando:  python vigia.py

Na primeira vez cria o ambiente (.venv), instala as dependências e gera o .env com
tokens aleatórios. Depois sobe o servidor e o detector juntos e abre o painel no navegador.
Ctrl+C encerra tudo."""

import hashlib
import os
import secrets
import subprocess
import sys
import time
import urllib.request
import venv
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
REQUIREMENTS = [ROOT / "backend" / "requirements.txt", ROOT / "detector" / "requirements.txt"]


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


def wait_until_up(url: str, process: subprocess.Popen, timeout: float = 60) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if process.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(url, timeout=2):
                return True
        except OSError:
            time.sleep(0.5)
    return False


def stop(*processes: subprocess.Popen) -> None:
    for p in processes:
        if p and p.poll() is None:
            p.terminate()
    for p in processes:
        if p:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()


def run() -> int:
    config = ensure_env()
    host = os.getenv("HOST") or config.get("HOST") or "127.0.0.1"
    port = os.getenv("PORT") or config.get("PORT") or "8000"
    env = {
        **os.environ,
        **config,
        "BACKEND_URL": f"http://127.0.0.1:{port}",
        "PYTHONUNBUFFERED": "1",
        "PYTHONIOENCODING": "utf-8",
    }

    print("Iniciando o servidor...")
    backend = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", host, "--port", port, "--log-level", "warning"],
        cwd=ROOT / "backend",
        env=env,
    )
    if not wait_until_up(f"http://127.0.0.1:{port}/api/health", backend):
        print(f"\nO servidor não iniciou. A porta {port} pode estar em uso: feche outro VigIA aberto ou")
        print("defina outra porta no .env (ex.: PORT=8001).")
        stop(backend)
        return 1

    print("Iniciando o detector de IA...")
    detector = subprocess.Popen([sys.executable, "-m", "vigia_detector.main"], cwd=ROOT / "detector", env=env)

    url = f"http://localhost:{port}/"
    print("\n" + "=" * 60)
    print(f"  VigIA rodando em {url}")
    print("  No primeiro acesso, crie o usuário administrador na tela.")
    print("  Para encerrar, pressione Ctrl+C nesta janela.")
    print("=" * 60 + "\n")
    webbrowser.open(url)

    try:
        while backend.poll() is None:
            if detector.poll() is not None:
                print("\nO detector parou (veja o erro acima). O painel continua funcionando;")
                print("corrija o problema e reinicie o VigIA.\n")
                backend.wait()
                break
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nEncerrando o VigIA...")
    finally:
        stop(detector, backend)
    return 0


if __name__ == "__main__":
    if not in_venv():
        python = ensure_venv()
        try:
            sys.exit(subprocess.call([str(python), str(Path(__file__).resolve())]))
        except KeyboardInterrupt:
            sys.exit(0)
    sys.exit(run())
