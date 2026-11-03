import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import notifier
from ..auth import require_detector
from ..common import EVIDENCE_DIR, event_out, get_or_404
from ..database import get_db
from ..health import set_camera_health
from ..models import Camera, Event, Rule, RuleStat
from ..schemas import DetectorCamera, RuleOut, StatsIn
from ..ws import hub

router = APIRouter(prefix="/api/detector", dependencies=[Depends(require_detector)])


@router.get("/config", response_model=list[DetectorCamera])
def detector_config(db: Session = Depends(get_db)):
    """Detector desta instalação. Câmeras de unidades atendidas por um VigIA Edge ficam com o Edge
    (evita a mesma câmera ser analisada duas vezes quando se testa nuvem e Edge no mesmo computador)."""
    from ..models import Edge
    edge_units = select(Edge.unit_id).where(Edge.revoked_at.is_(None))
    cameras = db.scalars(select(Camera).where(Camera.enabled, Camera.unit_id.not_in(edge_units))
                         .options(selectinload(Camera.rules))).all()
    return [
        DetectorCamera(id=c.id, name=c.name, source=c.source,
                       rules=[RuleOut.model_validate(r) for r in c.rules if r.enabled])
        for c in cameras
    ]


def _parse_boxes(raw: str | None) -> list | None:
    if not raw:
        return None
    try:
        boxes = json.loads(raw)
    except ValueError:
        return None
    valid = [b for b in boxes if isinstance(b, list) and len(b) == 4 and all(isinstance(v, (int, float)) for v in b)]
    return valid[:50] or None


@router.post("/events", status_code=201)
async def receive_event(
    background: BackgroundTasks,
    camera_id: int = Form(...),
    rule_id: int = Form(...),
    message: str = Form(..., max_length=500),
    boxes: str | None = Form(None),
    clip_id: str | None = Form(None, max_length=40),
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

    return await register_event(db, background, camera, rule, message, _parse_boxes(boxes), clip_id, image_file)


async def register_event(db: Session, background: BackgroundTasks, camera: Camera, rule: Rule, message: str,
                         boxes: list | None, clip_id: str | None, image_file: str | None, **extra) -> dict:
    """Grava a ocorrência, avisa as telas em tempo real e dispara as notificações.
    extra: campos do Edge (media_edge_id, thumb_file, edge_ref, created_at)."""
    event = Event(camera_id=camera.id, rule_id=rule.id, type=rule.type, severity=rule.severity,
                  message=message, image_file=image_file, boxes=boxes, clip_id=clip_id, **extra)
    db.add(event)
    db.commit()
    event = db.scalar(select(Event).where(Event.id == event.id).options(selectinload(Event.actions)))

    payload = event_out(event)
    await hub.broadcast({"kind": "event", "event": payload})
    # imagem do e-mail/WhatsApp: a local, ou a miniatura quando a imagem está no Edge
    attach = event.thumb_file if event.media_edge_id else image_file
    background.add_task(notifier.notify, payload, EVIDENCE_DIR / attach if attach else None)
    return payload


@router.post("/clips/{clip_id}", status_code=204)
async def receive_clip(clip_id: str, frames: list[UploadFile] = File(...), duration: float = Form(...),
                       db: Session = Depends(get_db)):
    """Quadros do clipe de uma ocorrência (chegam alguns segundos depois do evento)."""
    event = db.scalar(select(Event).where(Event.clip_id == clip_id))
    if event is None:
        raise HTTPException(404, "ocorrência do clipe não encontrada")
    if len(frames) > 300:
        raise HTTPException(400, "clipe longo demais")
    folder = f"clipes/{event.created_at:%Y/%m/%d}/{event.id}"
    path = EVIDENCE_DIR / folder
    path.mkdir(parents=True, exist_ok=True)
    for i, frame in enumerate(frames):
        (path / f"{i:04d}.jpg").write_bytes(await frame.read())
    event.clip_dir, event.clip_frames, event.clip_duration = folder, len(frames), max(duration, 0.1)
    event.media_synced_at = None  # o clipe chegou depois: enviar também ao NAS
    db.commit()
    await hub.broadcast({"kind": "event_updated", "id": event.id})


@router.post("/cameras/{camera_id}/frame", status_code=204)
async def receive_frame(camera_id: int, background: BackgroundTasks, frame: UploadFile = File(...),
                        health: str = Form("ok"), db: Session = Depends(get_db)):
    """Último quadro da câmera (ao vivo e desenho de zonas) + estado de saúde da imagem."""
    camera = get_or_404(db, Camera, camera_id)
    path = EVIDENCE_DIR / "ao-vivo" / f"{camera_id}.jpg"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(await frame.read())
    tmp.replace(path)
    camera.last_frame_at = datetime.now(timezone.utc)
    camera.connect_error = None
    await set_camera_health(db, camera, health if health in ("ok", "escura", "obstruida", "congelada") else "ok",
                            background)
    db.commit()


class CameraStatusIn(BaseModel):
    error: str | None = Field(None, max_length=300)


@router.post("/cameras/{camera_id}/status", status_code=204)
async def receive_camera_status(camera_id: int, data: CameraStatusIn, db: Session = Depends(get_db)):
    """Por que o detector não consegue abrir a câmera (None = conectou)."""
    await apply_camera_status(db, get_or_404(db, Camera, camera_id), data.error)


async def apply_camera_status(db: Session, camera: Camera, error: str | None) -> None:
    changed = (camera.connect_error or None) != (error or None)
    camera.connect_error = error or None
    camera.connect_error_at = datetime.now(timezone.utc) if error else None
    db.commit()
    if changed:
        await hub.broadcast({"kind": "camera_status", "camera_id": camera.id, "error": camera.connect_error})


@router.post("/stats", status_code=204)
def receive_stats(data: StatsIn, db: Session = Depends(get_db)):
    """Contagens de pessoas observadas x em violação, agregadas por hora (índice de conformidade)."""
    record_stats(db, data)


def record_stats(db: Session, data: StatsIn, at: datetime | None = None) -> None:
    """at: momento da observação (o Edge reenvia depois de uma queda de internet)."""
    hour = (at or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    valid_rules = set(db.scalars(select(Rule.id).where(Rule.camera_id == data.camera_id)))
    for item in data.items:
        if item.rule_id not in valid_rules:
            continue
        stat = db.scalar(select(RuleStat).where(RuleStat.rule_id == item.rule_id, RuleStat.hour == hour))
        if stat is None:
            stat = RuleStat(rule_id=item.rule_id, camera_id=data.camera_id, hour=hour, observed=0, violations=0)
            db.add(stat)
        stat.observed += item.observed
        stat.violations += min(item.violations, item.observed)
    db.commit()
