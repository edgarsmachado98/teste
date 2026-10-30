import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from sqlalchemy import delete, select

from .auth import user_from_token
from .common import EVIDENCE_DIR
from .config import settings
from .database import SessionLocal
from .health import health_loop
from .migrate import migrate
from .models import Event, Session
from .routers import access, cameras, detector, events, reports
from .ws import hub

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("vigia")

STATIC_DIR = Path(__file__).parent / "static"


def purge_old_data() -> tuple[int, int]:
    """Retenção (LGPD): apaga as imagens após RETENTION_DAYS e os registros de ocorrência
    após EVENT_RETENTION_DAYS. Também remove sessões expiradas."""
    now = datetime.now(timezone.utc)
    image_cutoff = now - timedelta(days=settings.retention_days)
    event_cutoff = now - timedelta(days=max(settings.event_retention_days, settings.retention_days))
    with SessionLocal() as db:
        with_images = db.scalars(
            select(Event).where(Event.created_at < image_cutoff, Event.image_file.is_not(None))
        ).all()
        for event in with_images:
            (EVIDENCE_DIR / event.image_file).unlink(missing_ok=True)
            event.image_file = None
        old = db.scalars(select(Event).where(Event.created_at < event_cutoff)).all()
        for event in old:
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
    tasks = [asyncio.create_task(retention_loop()), asyncio.create_task(health_loop())]
    yield
    for task in tasks:
        task.cancel()


app = FastAPI(title="VigIA – Gestão de Segurança Industrial", lifespan=lifespan)
for module in (access, cameras, events, reports, detector):
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
