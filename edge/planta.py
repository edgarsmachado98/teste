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
    local_ca = ROOT / "certs" / "vigia-ca.crt"
    if local_ca.exists() and not os.getenv("EDGE_CLOUD_CA"):
        os.environ["EDGE_CLOUD_CA"] = str(local_ca)  # cadastro no servidor local em HTTPS
    from vigia_edge.__main__ import enroll
    from vigia_edge.config import load
    if load().enrolled:
        return
    print("\n=== Cadastro deste VigIA Edge ===")
    print("Gere o código em: painel da nuvem → Configurações → VigIA Edge → Gerar código de instalação\n")
    while True:
        cloud = input("Endereço da nuvem (ex.: https://cliente.seudominio.com.br; teste local: http://localhost:8000): ").strip()
        code = input("Código de instalação (ex.: ABCD-1234): ").strip()
        media = input("Pasta do storage do cliente [D:\\vigia ou \\\\nas\\vigia] (Enter = pasta local): ").strip()
        args = type("A", (), {"cloud": cloud, "code": code, "media_dir": media or None})
        if enroll(args) == 0:
            return
        print("Tente novamente.\n")


def use_project_venv() -> None:
    """No computador que já roda o iniciar.bat, reaproveita o .venv (mesmas dependências)."""
    venv_py = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if venv_py.exists() and Path(sys.executable).resolve() != venv_py.resolve():
        sys.exit(subprocess.call([str(venv_py), str(Path(__file__).resolve()), *sys.argv[1:]]))


TRIAL_SECONDS = 180  # tempo para uma versão nova provar que funciona (conectar na nuvem)
EXIT_UPDATED = 75


# ---------- versões (atualização remota) ----------

def plan(state: dict) -> tuple[str | None, bool]:
    """(versão a rodar – None = a desta pasta, está em teste?)"""
    if state.get("pending"):
        return state["pending"], True
    return state.get("current"), False


def promote(state: dict) -> dict:
    return {**state, "previous": state.get("current"), "current": state["pending"], "pending": None}


def rollback(state: dict) -> dict:
    failed = list(dict.fromkeys([*state.get("failed", []), state["pending"]]))[-10:]
    return {**state, "pending": None, "failed": failed}


def launch_cmds(version_dir: Path | None) -> dict:
    """Comandos do Edge e do detector, usando o código da versão instalada (se houver)."""
    def run(module: str, *args) -> list[str]:
        if version_dir is None:
            return [sys.executable, "-m", module, *args]
        code = (f"import sys, runpy; sys.path.insert(0, {str(version_dir)!r}); "
                f"runpy.run_module({module!r}, run_name='__main__', alter_sys=True)")
        return [sys.executable, "-c", code, *args]
    return {"edge": (run("vigia_edge", "run"), HERE), "detector": (run("vigia_detector.main"), ROOT / "detector")}


def install_requirements(version_dir: Path) -> bool:
    """Dependências novas da versão (só quando mudaram)."""
    import hashlib
    for req in sorted(version_dir.glob("requirements-*.txt")):
        marker = version_dir / f".{req.stem}.instalado"
        digest = hashlib.sha256(req.read_bytes()).hexdigest()
        if marker.exists() and marker.read_text() == digest:
            continue
        print(f"Instalando dependências da versão nova ({req.name})...")
        if subprocess.call([sys.executable, "-m", "pip", "install", "-q", "-r", str(req)]) != 0:
            return False
        marker.write_text(digest)
    return True


def tunnel_up(port: int) -> bool:
    import json
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/status", timeout=3) as r:
            return bool(json.loads(r.read()).get("tunnel"))
    except Exception:  # noqa: BLE001
        return False


def main() -> int:
    use_project_venv()
    ensure_packages()
    first_setup()
    from vigia_edge.config import HOME, load
    from vigia_edge.updater import read_state, write_state
    cfg = load()
    # Teste com o servidor neste mesmo computador em HTTPS: confia no certificado gerado pelo vigia.py
    local_ca = ROOT / "certs" / "vigia-ca.crt"
    if cfg.cloud_url.startswith("https://localhost") and local_ca.exists() and not os.getenv("EDGE_CLOUD_CA"):
        os.environ["EDGE_CLOUD_CA"] = str(local_ca)
    env = {**os.environ, "BACKEND_URL": f"http://127.0.0.1:{cfg.listen_port}", "DETECTOR_API_KEY": cfg.detector_key}
    print(f"\nVigIA Edge \"{cfg.name}\" → {cfg.cloud_url}\nImagens em: {cfg.media_dir}\nCtrl+C para encerrar.\n")
    procs: dict[str, subprocess.Popen | None] = {"edge": None, "detector": None}

    def stop_all():
        for p in procs.values():
            if p and p.poll() is None:
                p.terminate()
                try:
                    p.wait(15)
                except subprocess.TimeoutExpired:
                    p.kill()
        procs.update(edge=None, detector=None)

    try:
        while True:
            state = read_state(HOME)
            version, trial = plan(state)
            vdir = HOME / "versoes" / version if version else None
            if vdir is not None and not vdir.exists():
                print(f"Versão {version} não encontrada; usando a desta pasta.")
                write_state(HOME, rollback(state) if trial else {**state, "current": None})
                continue
            if trial and not install_requirements(vdir):
                print(f"Falha ao instalar dependências da versão {version}; voltando para a anterior.")
                write_state(HOME, rollback(state))
                continue
            cmds = launch_cmds(vdir)
            print(f"Iniciando versão {version or 'desta pasta'}{' (em teste)' if trial else ''}...")
            started = time.monotonic()
            restart = False
            while not restart:
                for name, (cmd, cwd) in cmds.items():
                    p = procs[name]
                    if p is not None and p.poll() is not None:
                        code = p.returncode
                        if name == "edge" and code == EXIT_UPDATED:
                            print("Atualização instalada; reiniciando com a versão nova...")
                            restart = True
                            break
                        if trial:
                            print(f"A versão {version} parou (código {code}) durante o teste; voltando para a anterior.")
                            write_state(HOME, rollback(read_state(HOME)))
                            restart = True
                            break
                        print(f"{name} parou (código {code}); reiniciando...")
                    if p is None or p.poll() is not None:
                        procs[name] = subprocess.Popen(cmd, cwd=cwd, env=env)
                        if name == "edge":
                            time.sleep(3)  # o detector só sobe com o Edge pronto
                if restart:
                    break
                if trial:
                    if tunnel_up(cfg.listen_port):
                        write_state(HOME, promote(read_state(HOME)))
                        print(f"Versão {version} conectada à nuvem: atualização concluída.")
                        trial = False
                    elif time.monotonic() - started > TRIAL_SECONDS:
                        print(f"A versão {version} não conectou à nuvem em {TRIAL_SECONDS} s; voltando para a anterior.")
                        write_state(HOME, rollback(read_state(HOME)))
                        restart = True
                        break
                time.sleep(5)
            stop_all()
    except KeyboardInterrupt:
        pass
    finally:
        stop_all()
    return 0


if __name__ == "__main__":
    sys.exit(main())
