"""Saúde das câmeras: o cliente precisa confiar que o sistema está realmente olhando."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from fastapi import BackgroundTasks
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import audit, notifier
from .config import settings
from .database import SessionLocal
from .models import Camera
from .timeutil import as_utc
from .ws import hub

log = logging.getLogger("vigia.health")

HEALTH_LABELS = {
    "ok": "normal",
    "offline": "sem sinal",
    "escura": "imagem escura",
    "obstruida": "lente obstruída ou desfocada",
    "congelada": "imagem congelada",
}


async def set_camera_health(db: Session, camera: Camera, health: str, background: BackgroundTasks | None = None):
    previous = camera.health
    if previous == health:
        return
    camera.health = health
    if previous is None and health == "ok":
        return  # primeira imagem da câmera: nada a alertar
    label = HEALTH_LABELS[health]
    audit.record(db, None, "camera_saude", "camera", camera.id, f"{camera.name}: {label}")
    payload = {"kind": "camera_health", "camera_id": camera.id, "camera_name": camera.name,
               "health": health, "label": label}
    await hub.broadcast(payload)
    if background is not None:
        background.add_task(notifier.notify_camera_health, payload)
    else:
        await asyncio.to_thread(notifier.notify_camera_health, payload)
    log.warning("câmera %s: %s", camera.name, label)


async def check_offline_cameras() -> None:
    limit = datetime.now(timezone.utc) - timedelta(seconds=settings.camera_offline_after)
    with SessionLocal() as db:
        cameras = db.scalars(select(Camera).where(Camera.enabled, Camera.last_frame_at.is_not(None))).all()
        for camera in cameras:
            if as_utc(camera.last_frame_at) < limit and camera.health != "offline":
                await set_camera_health(db, camera, "offline")
        db.commit()


async def health_loop() -> None:
    while True:
        try:
            await check_offline_cameras()
        except Exception:
            log.exception("falha ao verificar câmeras")
        await asyncio.sleep(20)
