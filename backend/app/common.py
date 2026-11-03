from datetime import date
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .config import settings
from .models import ATTACHMENT_KINDS, ActionItem, Attachment, Event
from .schemas import ActionOut, AttachmentOut, EventOut

EVIDENCE_DIR = Path(settings.evidence_dir)

CLASS_LABELS_PT = {
    "ato_inseguro": "Ato inseguro",
    "condicao_insegura": "Condição insegura",
    "quase_acidente": "Quase acidente",
    "acidente": "Acidente",
    "nao_classificada": "Não classificada",
}

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
        attachments=[attachment_out(a) for a in action.attachments],
    ).model_dump()


def attachment_out(a: Attachment) -> AttachmentOut:
    return AttachmentOut(id=a.id, kind=a.kind, kind_label=ATTACHMENT_KINDS.get(a.kind, a.kind), filename=a.filename,
                         content_type=a.content_type, size=a.size,
                         uploaded_by=a.uploaded_by.name if a.uploaded_by else None, uploaded_by_id=a.uploaded_by_id,
                         created_at=a.created_at)


def unit_cameras(unit_id: int):
    """Subconsulta com as câmeras de uma unidade (filtro do seletor de unidade do cabeçalho)."""
    from sqlalchemy import select

    from .models import Camera
    return select(Camera.id).where(Camera.unit_id == unit_id)


def camera_name(event: Event) -> str:
    """Nome da câmera da ocorrência. Ocorrências antigas podem ter perdido a câmera
    (excluída antes da proteção do histórico); o registro continua válido."""
    return event.camera.name if event.camera else f"Câmera excluída (#{event.camera_id})"


def camera_location(event: Event) -> str:
    return (event.camera.location if event.camera else "") or ""


def event_out(event: Event) -> dict:
    return EventOut(
        id=event.id,
        camera_id=event.camera_id,
        camera_name=camera_name(event),
        unit_id=event.camera.unit_id if event.camera else None,
        location=camera_location(event),
        rule_id=event.rule_id,
        rule_name=event.rule.name if event.rule else None,
        type=event.type,
        severity=event.severity,
        message=event.message,
        image_url=f"/api/events/{event.id}/image" if event.image_file else None,
        thumb_url=f"/api/events/{event.id}/thumb" if (event.thumb_file or event.image_file) else None,
        media_at_edge=bool(event.media_edge_id),
        clip_video_url=f"/api/events/{event.id}/clip.webm" if event.clip_dir and event.clip_format == "webm" else None,
        clip_frames=event.clip_frames if event.clip_dir else None,
        clip_duration=event.clip_duration if event.clip_dir else None,
        status=event.status,
        classification=event.classification,
        notes=event.notes,
        reviewed_by=event.reviewed_by.name if event.reviewed_by else None,
        reviewed_at=event.reviewed_at,
        closed_at=event.closed_at,
        open_actions=sum(1 for a in event.actions if a.status == "aberta"),
        created_at=event.created_at,
        person_id=event.person_id,
        person_name=event.person.name if event.person_id and event.person else None,
        identification=event.identification,
    ).model_dump()


