import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import delete, select

from . import storage
from .auth import user_from_token
from .common import EVIDENCE_DIR
from .config import settings
from .database import SessionLocal
from .health import health_loop
from .migrate import migrate
from .models import AuditLog, Event, Session
from .routers import access, cameras, config, detector, events, measures, people, reports, sectors, system
from .sectors import ensure_default_unit
from .settings_store import apply_overrides
from .scheduler import scheduler_loop
from .storage import storage_loop
from .usage import usage_loop
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
        if settings.audit_retention_days > 0:
            db.execute(delete(AuditLog).where(AuditLog.created_at < now - timedelta(days=settings.audit_retention_days)))
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
    apply_overrides()  # configurações salvas pelo painel (guia Configurações)
    with SessionLocal() as db:
        ensure_default_unit(db)
    tasks = [asyncio.create_task(retention_loop()), asyncio.create_task(health_loop()),
             asyncio.create_task(scheduler_loop()), asyncio.create_task(storage_loop()),
             asyncio.create_task(usage_loop())]
    yield
    for task in tasks:
        task.cancel()


app = FastAPI(title="VigIA – Gestão de Segurança Industrial", lifespan=lifespan)

ERROR_LOG = Path(__file__).resolve().parents[2] / "logs" / "erros.log"


@app.exception_handler(Exception)
async def unexpected_error(request: Request, exc: Exception):
    """Erro inesperado: registra o rastro completo em logs/erros.log e devolve à tela
    a rota e a causa, para o suporte identificar o problema sem precisar do console."""
    import traceback
    trace = "".join(traceback.format_exception(exc))
    log.error("Erro em %s %s\n%s", request.method, request.url.path, trace)
    try:
        ERROR_LOG.parent.mkdir(parents=True, exist_ok=True)
        if ERROR_LOG.exists() and ERROR_LOG.stat().st_size > 5 * 1024 * 1024:
            ERROR_LOG.replace(ERROR_LOG.with_suffix(".log.1"))
        with open(ERROR_LOG, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {request.method} {request.url.path}\n{trace}\n")
    except OSError:
        pass  # disco cheio ou sem permissão: o rastro já foi para o console
    return JSONResponse(status_code=500, content={
        "detail": f"Erro interno em {request.url.path}: {type(exc).__name__}: {str(exc)[:300]}"})
for module in (access, cameras, events, reports, detector, system, config, sectors, people, measures):
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
