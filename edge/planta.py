"""Inicializador da planta: VigIA Edge + detector, reiniciando o que parar.

Primeira vez: pede o endereço da nuvem, o código de instalação (gerado em Configurações → VigIA Edge)
e a pasta do storage do cliente. Depois é só rodar de novo (ou instalar como serviço)."""

import importlib.util
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
os.environ.setdefault("EDGE_HOME", str(HERE / "edge-data"))
sys.path.insert(0, str(HERE))


def ensure_packages() -> None:
    missing = [m for m in ("fastapi", "uvicorn", "httpx", "websockets", "PIL", "multipart", "ultralytics", "cv2")
               if importlib.util.find_spec(m) is None]
    if missing:
        print("Instalando dependências (só na primeira vez)...")
        for req in (HERE / "requirements.txt", ROOT / "detector" / "requirements.txt"):
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "-r", str(req)])


def first_setup() -> None:
    from vigia_edge.__main__ import enroll
    from vigia_edge.config import load
    if load().enrolled:
        return
    print("\n=== Cadastro deste VigIA Edge ===")
    print("Gere o código em: painel da nuvem → Configurações → VigIA Edge → Gerar código de instalação\n")
    while True:
        cloud = input("Endereço da nuvem (ex.: https://cliente.seudominio.com.br): ").strip()
        code = input("Código de instalação (ex.: ABCD-1234): ").strip()
        media = input("Pasta do storage do cliente [D:\\vigia ou \\\\nas\\vigia] (Enter = pasta local): ").strip()
        args = type("A", (), {"cloud": cloud, "code": code, "media_dir": media or None})
        if enroll(args) == 0:
            return
        print("Tente novamente.\n")


def main() -> int:
    ensure_packages()
    first_setup()
    from vigia_edge.config import load
    cfg = load()
    env = {**os.environ, "BACKEND_URL": f"http://127.0.0.1:{cfg.listen_port}", "DETECTOR_API_KEY": cfg.detector_key}
    procs: dict[str, subprocess.Popen | None] = {"edge": None, "detector": None}
    cmds = {"edge": ([sys.executable, "-m", "vigia_edge", "run"], HERE),
            "detector": ([sys.executable, "-m", "vigia_detector.main"], ROOT / "detector")}
    print(f"\nVigIA Edge \"{cfg.name}\" → {cfg.cloud_url}\nImagens em: {cfg.media_dir}\nCtrl+C para encerrar.\n")
    try:
        while True:
            for name, (cmd, cwd) in cmds.items():
                p = procs[name]
                if p is None or p.poll() is not None:
                    if p is not None:
                        print(f"{name} parou (código {p.returncode}); reiniciando...")
                    procs[name] = subprocess.Popen(cmd, cwd=cwd, env=env)
                    if name == "edge":
                        time.sleep(3)  # o detector só sobe com o Edge pronto
            time.sleep(5)
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs.values():
            if p and p.poll() is None:
                p.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())
