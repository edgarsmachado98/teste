import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from . import auth, notifier
from .config import settings
from .database import Base, SessionLocal, engine, get_db
from .models import Camera, Event, Rule
from .schemas import (
    CameraIn,
    CameraOut,
    DetectorCamera,
    EventOut,
    EventStatusIn,
    RuleIn,
    RuleOut,
)
from .ws import hub

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("vigia")

EVIDENCE_DIR = Path(settings.evidence_dir)
STATIC_DIR = Path(__file__).parent / "static"


def purge_old_events() -> int:
    """Remove eventos e imagens além do prazo de retenção (LGPD)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.retention_days)
    with SessionLocal() as db:
        old = db.scalars(select(Event).where(Event.created_at < cutoff)).all()
        for event in old:
            if event.image_file:
                (EVIDENCE_DIR / event.image_file).unlink(missing_ok=True)
            db.delete(event)
        db.commit()
    if old:
        log.info("retenção: %d eventos removidos", len(old))
    return len(old)


async def retention_loop() -> None:
    while True:
        await asyncio.to_thread(purge_old_events)
        await asyncio.sleep(3600)


@asynccontextmanager
async def lifespan(app: FastAPI):
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)
    task = asyncio.create_task(retention_loop())
    yield
    task.cancel()


app = FastAPI(title="VigIA – Monitoramento Industrial", lifespan=lifespan)
user = [Depends(auth.require_user)]


def event_to_dict(event: Event) -> dict:
    return EventOut(
        id=event.id,
        camera_id=event.camera_id,
        camera_name=event.camera.name,
        rule_id=event.rule_id,
        rule_name=event.rule.name if event.rule else None,
        type=event.type,
        severity=event.severity,
        message=event.message,
        image_url=f"/api/events/{event.id}/image" if event.image_file else None,
        status=event.status,
        created_at=event.created_at,
    ).model_dump()


def get_or_404(db: Session, model, obj_id: int):
    obj = db.get(model, obj_id)
    if obj is None:
        raise HTTPException(404, "não encontrado")
    return obj


# ---------- Câmeras ----------

@app.get("/api/cameras", response_model=list[CameraOut], dependencies=user)
def list_cameras(db: Session = Depends(get_db)):
    return db.scalars(select(Camera).order_by(Camera.name)).all()


@app.post("/api/cameras", response_model=CameraOut, status_code=201, dependencies=user)
def create_camera(data: CameraIn, db: Session = Depends(get_db)):
    camera = Camera(**data.model_dump())
    db.add(camera)
    db.commit()
    return camera


@app.put("/api/cameras/{camera_id}", response_model=CameraOut, dependencies=user)
def update_camera(camera_id: int, data: CameraIn, db: Session = Depends(get_db)):
    camera = get_or_404(db, Camera, camera_id)
    for key, value in data.model_dump().items():
        setattr(camera, key, value)
    db.commit()
    return camera


@app.delete("/api/cameras/{camera_id}", status_code=204, dependencies=user)
def delete_camera(camera_id: int, db: Session = Depends(get_db)):
    db.delete(get_or_404(db, Camera, camera_id))
    db.commit()


# ---------- Regras ----------

@app.get("/api/rules", response_model=list[RuleOut], dependencies=user)
def list_rules(camera_id: int | None = None, db: Session = Depends(get_db)):
    query = select(Rule).order_by(Rule.camera_id, Rule.name)
    if camera_id is not None:
        query = query.where(Rule.camera_id == camera_id)
    return db.scalars(query).all()


@app.post("/api/rules", response_model=RuleOut, status_code=201, dependencies=user)
def create_rule(data: RuleIn, db: Session = Depends(get_db)):
    get_or_404(db, Camera, data.camera_id)
    rule = Rule(**data.model_dump())
    db.add(rule)
    db.commit()
    return rule


@app.put("/api/rules/{rule_id}", response_model=RuleOut, dependencies=user)
def update_rule(rule_id: int, data: RuleIn, db: Session = Depends(get_db)):
    rule = get_or_404(db, Rule, rule_id)
    get_or_404(db, Camera, data.camera_id)
    for key, value in data.model_dump().items():
        setattr(rule, key, value)
    db.commit()
    return rule


@app.delete("/api/rules/{rule_id}", status_code=204, dependencies=user)
def delete_rule(rule_id: int, db: Session = Depends(get_db)):
    db.delete(get_or_404(db, Rule, rule_id))
    db.commit()


# ---------- Eventos ----------

@app.get("/api/events", response_model=list[EventOut], dependencies=user)
def list_events(
    camera_id: int | None = None,
    status: str | None = None,
    limit: int = Query(100, le=500),
    db: Session = Depends(get_db),
):
    query = (
        select(Event)
        .options(selectinload(Event.camera), selectinload(Event.rule))
        .order_by(Event.created_at.desc())
        .limit(limit)
    )
    if camera_id is not None:
        query = query.where(Event.camera_id == camera_id)
    if status:
        query = query.where(Event.status == status)
    return [event_to_dict(e) for e in db.scalars(query).all()]


@app.patch("/api/events/{event_id}", response_model=EventOut, dependencies=user)
def update_event_status(event_id: int, data: EventStatusIn, db: Session = Depends(get_db)):
    event = get_or_404(db, Event, event_id)
    event.status = data.status
    db.commit()
    return event_to_dict(event)


@app.get("/api/events/{event_id}/image", dependencies=user)
def event_image(event_id: int, db: Session = Depends(get_db)):
    event = get_or_404(db, Event, event_id)
    if not event.image_file:
        raise HTTPException(404, "evento sem imagem")
    return FileResponse(EVIDENCE_DIR / event.image_file, media_type="image/jpeg")


@app.get("/api/stats", dependencies=user)
def stats(db: Session = Depends(get_db)):
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    by_type = db.execute(
        select(Event.type, func.count()).where(Event.created_at >= since).group_by(Event.type)
    ).all()
    pending = db.scalar(select(func.count()).select_from(Event).where(Event.status == "nova"))
    return {
        "last_24h": {t: c for t, c in by_type},
        "pending": pending,
        "cameras": db.scalar(select(func.count()).select_from(Camera)),
    }


# ---------- Integração com o detector ----------

@app.get("/api/detector/config", response_model=list[DetectorCamera], dependencies=[Depends(auth.require_detector)])
def detector_config(db: Session = Depends(get_db)):
    cameras = db.scalars(select(Camera).where(Camera.enabled).options(selectinload(Camera.rules))).all()
    return [
        DetectorCamera(
            id=c.id,
            name=c.name,
            source=c.source,
            rules=[RuleOut.model_validate(r) for r in c.rules if r.enabled],
        )
        for c in cameras
    ]


@app.post("/api/detector/events", status_code=201, dependencies=[Depends(auth.require_detector)])
async def receive_event(
    background: BackgroundTasks,
    camera_id: int = Form(...),
    rule_id: int = Form(...),
    message: str = Form(..., max_length=500),
    snapshot: UploadFile | None = File(None),
    db: Session = Depends(get_db),
):
    camera = get_or_404(db, Camera, camera_id)
    rule = get_or_404(db, Rule, rule_id)
    if rule.camera_id != camera.id:
        raise HTTPException(400, "regra não pertence à câmera")

    image_file = None
    if snapshot is not None:
        now = datetime.now(timezone.utc)
        image_file = f"{now:%Y/%m/%d}/{uuid.uuid4().hex}.jpg"
        path = EVIDENCE_DIR / image_file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(await snapshot.read())

    event = Event(
        camera_id=camera.id,
        rule_id=rule.id,
        type=rule.type,
        severity=rule.severity,
        message=message,
        image_file=image_file,
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    payload = event_to_dict(event)
    await hub.broadcast({"kind": "event", "event": payload})
    background.add_task(notifier.notify, payload, EVIDENCE_DIR / image_file if image_file else None)
    return payload


@app.post("/api/detector/cameras/{camera_id}/frame", status_code=204, dependencies=[Depends(auth.require_detector)])
async def receive_frame(camera_id: int, frame: UploadFile = File(...), db: Session = Depends(get_db)):
    """Último quadro da câmera: usado na visualização ao vivo e para desenhar zonas."""
    get_or_404(db, Camera, camera_id)
    path = EVIDENCE_DIR / "ao-vivo" / f"{camera_id}.jpg"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(await frame.read())
    tmp.replace(path)


@app.get("/api/cameras/{camera_id}/frame", dependencies=user)
def camera_frame(camera_id: int):
    path = EVIDENCE_DIR / "ao-vivo" / f"{camera_id}.jpg"
    if not path.exists():
        raise HTTPException(404, "sem imagem ainda – verifique se o detector está rodando")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


# ---------- Tempo real e painel ----------

@app.websocket("/ws")
async def websocket_alerts(ws: WebSocket, token: str | None = None):
    if settings.api_token and not auth.matches(token, settings.api_token):
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
