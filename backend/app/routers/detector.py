import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
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
    cameras = db.scalars(select(Camera).where(Camera.enabled).options(selectinload(Camera.rules))).all()
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

    event = Event(camera_id=camera.id, rule_id=rule.id, type=rule.type, severity=rule.severity,
                  message=message, image_file=image_file, boxes=_parse_boxes(boxes))
    db.add(event)
    db.commit()
    event = db.scalar(select(Event).where(Event.id == event.id).options(selectinload(Event.actions)))

    payload = event_out(event)
    await hub.broadcast({"kind": "event", "event": payload})
    background.add_task(notifier.notify, payload, EVIDENCE_DIR / image_file if image_file else None)
    return payload


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
    await set_camera_health(db, camera, health if health in ("ok", "escura", "obstruida", "congelada") else "ok",
                            background)
    db.commit()


@router.post("/stats", status_code=204)
def receive_stats(data: StatsIn, db: Session = Depends(get_db)):
    """Contagens de pessoas observadas x em violação, agregadas por hora (índice de conformidade)."""
    hour = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
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
