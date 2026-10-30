"""Ponto de entrada do detector: sincroniza câmeras/regras com o backend e gerencia as threads."""

import logging
import os
import threading
import time
from pathlib import Path

import httpx

from .client import BackendClient
from .engine import Engine
from .worker import CameraWorker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("vigia.detector")


def load_env_file() -> None:
    """Fora do Docker, lê o .env da raiz do projeto (variáveis já definidas têm prioridade)."""
    for path in (Path.cwd() / ".env", Path.cwd().parent / ".env"):
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
        return


def main() -> None:
    load_env_file()
    backend = os.getenv("BACKEND_URL", "http://localhost:8000")
    api_key = os.getenv("DETECTOR_API_KEY", "troque-esta-chave")
    model_paths = [p.strip() for p in os.getenv("MODEL_PATHS", "yolov8n.pt").split(",") if p.strip()]
    analysis_fps = float(os.getenv("ANALYSIS_FPS", "3"))
    refresh = float(os.getenv("CONFIG_REFRESH", "15"))
    clip_seconds = (float(os.getenv("CLIP_BEFORE", "5")), float(os.getenv("CLIP_AFTER", "5")))
    # HTTPS com certificado próprio da instalação: o detector confia nele explicitamente
    verify = os.getenv("BACKEND_CA") or True
    collector = None
    if os.getenv("DATASET_DIR"):
        from .dataset import Collector
        collector = Collector(os.getenv("DATASET_DIR"), float(os.getenv("DATASET_INTERVAL", "60")))
        log.info("coleta de imagens para treinamento ativa em %s", os.getenv("DATASET_DIR"))

    engine = Engine(model_paths, device=os.getenv("DEVICE") or None, imgsz=int(os.getenv("IMG_SIZE", "640")))
    engine_lock = threading.Lock()
    client = BackendClient(backend, api_key, verify)
    workers: dict[int, CameraWorker] = {}

    while True:
        try:
            cameras = {c["id"]: c for c in client.get_config()}
        except httpx.HTTPError as exc:
            log.warning("não foi possível obter a configuração (%s)", exc)
            time.sleep(refresh)
            continue

        for cam_id in list(workers):
            worker = workers[cam_id]
            camera = cameras.get(cam_id)
            if camera is None or camera["source"] != worker.camera["source"] or not worker.is_alive():
                worker.stop()
                del workers[cam_id]
        for cam_id, camera in cameras.items():
            if cam_id in workers:
                workers[cam_id].update(camera)
            else:
                log.info("iniciando câmera %s (%d regras)", camera["name"], len(camera["rules"]))
                workers[cam_id] = CameraWorker(camera, engine, engine_lock, client, analysis_fps,
                                               clip_seconds=clip_seconds, collector=collector)
                workers[cam_id].start()
        time.sleep(refresh)


if __name__ == "__main__":
    main()
