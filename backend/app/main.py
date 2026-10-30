import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from sqlalchemy import delete, select

from . import storage
from .auth import user_from_token
from .common import EVIDENCE_DIR
from .config import settings
from .database import SessionLocal
from .health import health_loop
from .migrate import migrate
from .models import Event, Session
from .routers import access, cameras, detector, events, reports, system
from .scheduler import scheduler_loop
from .storage import storage_loop
from .ws import hub

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("vigia")

STATIC_DIR = Path(__file__).parent / "static"


def remove_media(event: Event, db=None) -> None:
    """Apaga a foto e o clipe da ocorrência (dados pessoais), no disco local e no NAS,
    mantendo o registro."""
    storage.remove(event.image_file, db)
    storage.remove(event.clip_dir, db)
    event.image_file = None
    event.clip_dir = event.clip_frames = event.clip_duration = None


def purge_old_data() -> tuple[int, int]:
    """Retenção (LGPD): apaga as imagens após RETENTION_DAYS e os registros de ocorrência
    após EVENT_RETENTION_DAYS. Também remove sessões expiradas."""
    now = datetime.now(timezone.utc)
    image_cutoff = now - timedelta(days=settings.retention_days)
    event_cutoff = now - timedelta(days=max(settings.event_retention_days, settings.retention_days))
    with SessionLocal() as db:
        with_images = db.scalars(select(Event).where(
            Event.created_at < image_cutoff, (Event.image_file.is_not(None)) | (Event.clip_dir.is_not(None))
        )).all()
        for event in with_images:
            remove_media(event, db)
        old = db.scalars(select(Event).where(Event.created_at < event_cutoff)).all()
        for event in old:
            remove_media(event, db)
            db.delete(event)
        db.execute(delete(Session).where(Session.expires_at < now))
        db.commit()
    if with_images or old:
        log.info("retenção: %d imagens e %d ocorrências removidas", len(with_images), len(old))
    return len(with_images), len(old)


async def retention_loop() -> None:
    while True:
        await asyncio.to_thread(purge_old_data)
        await asyncio.sleep(3600)


@asynccontextmanager
async def lifespan(app: FastAPI):
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    migrate()
    tasks = [asyncio.create_task(retention_loop()), asyncio.create_task(health_loop()),
             asyncio.create_task(scheduler_loop()), asyncio.create_task(storage_loop())]
    yield
    for task in tasks:
        task.cancel()


app = FastAPI(title="VigIA – Gestão de Segurança Industrial", lifespan=lifespan)
for module in (access, cameras, events, reports, detector, system):
    app.include_router(module.router)


@app.websocket("/ws")
async def websocket_alerts(ws: WebSocket, token: str | None = None):
    with SessionLocal() as db:
        authorized = user_from_token(db, token) is not None
    if not authorized:
        await ws.close(code=4401)
        return
    await hub.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        await hub.disconnect(ws)


@app.get("/api/health")
def health():
    return {"status": "ok"}


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
