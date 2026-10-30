from datetime import date
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .config import settings
from .models import ActionItem, Event
from .schemas import ActionOut, EventOut

EVIDENCE_DIR = Path(settings.evidence_dir)

TYPE_LABELS = {
    "ppe_missing": "EPI ausente",
    "restricted_zone": "Zona restrita",
    "fire_smoke": "Fogo / fumaça",
    "max_people": "Excesso de pessoas",
}


def get_or_404(db: Session, model, obj_id: int):
    obj = db.get(model, obj_id)
    if obj is None:
        raise HTTPException(404, "não encontrado")
    return obj


def is_overdue(action: ActionItem) -> bool:
    return action.status == "aberta" and action.due_date is not None and action.due_date < date.today()


def action_out(action: ActionItem) -> dict:
    return ActionOut(
        id=action.id,
        event_id=action.event_id,
        event_message=action.event.message if action.event else None,
        title=action.title,
        description=action.description,
        responsible_id=action.responsible_id,
        responsible_name=action.responsible.name if action.responsible else None,
        due_date=action.due_date,
        status=action.status,
        overdue=is_overdue(action),
        completion_notes=action.completion_notes,
        created_by=action.created_by.name if action.created_by else None,
        created_at=action.created_at,
        completed_at=action.completed_at,
    ).model_dump()


def event_out(event: Event) -> dict:
    return EventOut(
        id=event.id,
        camera_id=event.camera_id,
        camera_name=event.camera.name,
        location=event.camera.location,
        rule_id=event.rule_id,
        rule_name=event.rule.name if event.rule else None,
        type=event.type,
        severity=event.severity,
        message=event.message,
        image_url=f"/api/events/{event.id}/image" if event.image_file else None,
        status=event.status,
        classification=event.classification,
        notes=event.notes,
        reviewed_by=event.reviewed_by.name if event.reviewed_by else None,
        reviewed_at=event.reviewed_at,
        closed_at=event.closed_at,
        open_actions=sum(1 for a in event.actions if a.status == "aberta"),
        created_at=event.created_at,
    ).model_dump()


