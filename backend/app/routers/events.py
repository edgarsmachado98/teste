"""Ocorrências (fluxo de tratamento) e plano de ação."""

from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import audit, notifier
from ..auth import current_user, has_role, require_role
from ..common import EVIDENCE_DIR, action_out, event_out, get_or_404
from ..database import get_db
from ..models import ActionItem, AuditLog, Event, User
from ..schemas import ActionIn, ActionOut, ActionUpdate, AuditOut, EventDetail, EventOut, EventUpdate
from ..timeutil import local_tz
from ..ws import hub

router = APIRouter(prefix="/api")

STATUS_LABELS = {"nova": "nova", "confirmada": "confirmada", "descartada": "falso alarme", "encerrada": "encerrada"}
CLASS_LABELS = {
    "ato_inseguro": "ato inseguro",
    "condicao_insegura": "condição insegura",
    "quase_acidente": "quase acidente",
    "acidente": "acidente",
}


def local_range(start: date | None, end: date | None) -> tuple[datetime | None, datetime | None]:
    """Converte datas locais (inclusive) em instantes UTC."""
    tz = local_tz()
    lo = datetime.combine(start, time.min, tz).astimezone(timezone.utc) if start else None
    hi = datetime.combine(end + timedelta(days=1), time.min, tz).astimezone(timezone.utc) if end else None
    return lo, hi


def event_query():
    return select(Event).options(
        selectinload(Event.camera), selectinload(Event.rule), selectinload(Event.reviewed_by),
        selectinload(Event.actions),
    )


@router.get("/events", response_model=list[EventOut], dependencies=[Depends(current_user)])
def list_events(
    status: str | None = None,
    camera_id: int | None = None,
    type: str | None = None,
    classification: str | None = None,
    start: date | None = None,
    end: date | None = None,
    limit: int = Query(100, le=500),
    offset: int = 0,
    db: Session = Depends(get_db),
):
    query = event_query().order_by(Event.created_at.desc()).limit(limit).offset(offset)
    if status:
        query = query.where(Event.status.in_(status.split(",")))
    if camera_id is not None:
        query = query.where(Event.camera_id == camera_id)
    if type:
        query = query.where(Event.type == type)
    if classification:
        query = query.where(Event.classification == classification)
    lo, hi = local_range(start, end)
    if lo:
        query = query.where(Event.created_at >= lo)
    if hi:
        query = query.where(Event.created_at < hi)
    return [event_out(e) for e in db.scalars(query).all()]


@router.get("/events/{event_id}", response_model=EventDetail, dependencies=[Depends(current_user)])
def event_detail(event_id: int, db: Session = Depends(get_db)):
    event = db.scalar(event_query().where(Event.id == event_id))
    if event is None:
        raise HTTPException(404, "não encontrado")
    history = db.scalars(
        select(AuditLog).where(AuditLog.entity == "ocorrencia", AuditLog.entity_id == event_id)
        .order_by(AuditLog.created_at, AuditLog.id)
    ).all()
    return {
        **event_out(event),
        "actions": [action_out(a) for a in sorted(event.actions, key=lambda a: a.id)],
        "history": [AuditOut.model_validate(h) for h in history],
    }


@router.patch("/events/{event_id}", response_model=EventOut)
async def update_event(event_id: int, data: EventUpdate, request: Request,
                       user: User = Depends(current_user), db: Session = Depends(get_db)):
    event = db.scalar(event_query().where(Event.id == event_id))
    if event is None:
        raise HTTPException(404, "não encontrado")
    now = datetime.now(timezone.utc)
    changes = []

    if data.status and data.status != event.status:
        new, old = data.status, event.status
        if new == "encerrada":
            if not has_role(user, "tecnico"):
                raise HTTPException(403, "apenas técnicos, gestores e administradores encerram ocorrências")
            if old != "confirmada":
                raise HTTPException(400, "só é possível encerrar ocorrências confirmadas")
            if any(a.status == "aberta" for a in event.actions):
                raise HTTPException(400, "conclua ou cancele as ações abertas antes de encerrar")
            event.closed_at = now
        elif old in ("encerrada", "descartada") or new == "nova":
            if not has_role(user, "tecnico"):
                raise HTTPException(403, "apenas técnicos, gestores e administradores reabrem ocorrências")
            event.closed_at = None
        if old == "nova":
            event.reviewed_by_id, event.reviewed_at = user.id, now
        event.status = new
        changes.append(f"status: {STATUS_LABELS[old]} → {STATUS_LABELS[new]}")

    if data.classification is not None and data.classification != event.classification:
        event.classification = data.classification
        changes.append(f"classificação: {CLASS_LABELS[data.classification]}")
    if data.notes is not None and data.notes != (event.notes or ""):
        event.notes = data.notes
        changes.append("observações atualizadas")

    if changes:
        audit.record(db, user, "ocorrencia_atualizada", "ocorrencia", event.id, "; ".join(changes), request)
        db.commit()
        await hub.broadcast({"kind": "event_updated", "id": event.id})
    return event_out(event)


@router.get("/events/{event_id}/image", dependencies=[Depends(current_user)])
def event_image(event_id: int, db: Session = Depends(get_db)):
    event = get_or_404(db, Event, event_id)
    if not event.image_file:
        raise HTTPException(404, "evento sem imagem")
    return FileResponse(EVIDENCE_DIR / event.image_file, media_type="image/jpeg")


# ---------- Plano de ação ----------

def action_query():
    return select(ActionItem).options(
        selectinload(ActionItem.event), selectinload(ActionItem.responsible), selectinload(ActionItem.created_by)
    )


@router.get("/actions", response_model=list[ActionOut])
def list_actions(
    status: str | None = None,
    responsible_id: int | None = None,
    mine: bool = False,
    overdue: bool = False,
    event_id: int | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    query = action_query().order_by(ActionItem.due_date.is_(None), ActionItem.due_date, ActionItem.id)
    if status:
        query = query.where(ActionItem.status.in_(status.split(",")))
    if mine:
        query = query.where(ActionItem.responsible_id == user.id)
    elif responsible_id is not None:
        query = query.where(ActionItem.responsible_id == responsible_id)
    if overdue:
        query = query.where(ActionItem.status == "aberta", ActionItem.due_date < date.today())
    if event_id is not None:
        query = query.where(ActionItem.event_id == event_id)
    return [action_out(a) for a in db.scalars(query).all()]


def _check_responsible(db: Session, responsible_id: int | None) -> User | None:
    if responsible_id is None:
        return None
    responsible = db.get(User, responsible_id)
    if responsible is None or not responsible.active:
        raise HTTPException(400, "responsável inválido ou inativo")
    return responsible


@router.post("/actions", response_model=ActionOut, status_code=201)
async def create_action(data: ActionIn, request: Request, background: BackgroundTasks,
                        user: User = Depends(require_role("tecnico")), db: Session = Depends(get_db)):
    event = get_or_404(db, Event, data.event_id) if data.event_id else None
    if event and event.status in ("descartada", "encerrada"):
        raise HTTPException(400, "reabra a ocorrência antes de incluir ações")
    responsible = _check_responsible(db, data.responsible_id)
    action = ActionItem(**data.model_dump(), created_by_id=user.id)
    db.add(action)
    db.flush()
    detail = f"ação #{action.id}: {action.title}" + (f" – responsável {responsible.name}" if responsible else "")
    audit.record(db, user, "acao_criada", "acao", action.id, action.title, request)
    if event:
        if event.status == "nova":
            event.status, event.reviewed_by_id, event.reviewed_at = "confirmada", user.id, datetime.now(timezone.utc)
        audit.record(db, user, "acao_criada", "ocorrencia", event.id, detail, request)
    db.commit()
    action = db.scalar(action_query().where(ActionItem.id == action.id))
    if responsible and responsible.id != user.id:
        background.add_task(notifier.notify_action_assigned, action_out(action), responsible.email)
    if event:
        await hub.broadcast({"kind": "event_updated", "id": event.id})
    return action_out(action)


@router.patch("/actions/{action_id}", response_model=ActionOut)
async def update_action(action_id: int, data: ActionUpdate, request: Request, background: BackgroundTasks,
                        user: User = Depends(current_user), db: Session = Depends(get_db)):
    action = db.scalar(action_query().where(ActionItem.id == action_id))
    if action is None:
        raise HTTPException(404, "não encontrado")
    fields = data.model_dump(exclude_unset=True)
    is_manager = has_role(user, "tecnico")
    if not is_manager:
        # O responsável (qualquer perfil) pode concluir a própria ação.
        if action.responsible_id != user.id or set(fields) - {"status", "completion_notes"}:
            raise HTTPException(403, "você só pode concluir ações atribuídas a você")
        if fields.get("status") not in (None, "concluida"):
            raise HTTPException(403, "você só pode concluir ações atribuídas a você")

    changes = []
    old_responsible = action.responsible_id
    if "responsible_id" in fields:
        _check_responsible(db, fields["responsible_id"])
    new_status = fields.get("status")
    if new_status == "concluida" and not (fields.get("completion_notes") or action.completion_notes).strip():
        raise HTTPException(400, "descreva o que foi feito para concluir a ação")
    for key, value in fields.items():
        if getattr(action, key) != value:
            changes.append(key)
            setattr(action, key, value)
    if new_status and "status" in changes:
        action.completed_at = datetime.now(timezone.utc) if new_status == "concluida" else None

    if changes:
        labels = {"status": f"status: {action.status}", "responsible_id": "responsável alterado",
                  "due_date": f"prazo: {action.due_date:%d/%m/%Y}" if action.due_date else "prazo removido"}
        detail = f"ação #{action.id}: " + ", ".join(labels.get(c, c) for c in changes)
        audit.record(db, user, "acao_atualizada", "acao", action.id, detail, request)
        if action.event_id:
            audit.record(db, user, "acao_atualizada", "ocorrencia", action.event_id, detail, request)
        db.commit()
        db.refresh(action)
        if action.responsible and action.responsible_id != old_responsible and action.responsible_id != user.id:
            background.add_task(notifier.notify_action_assigned, action_out(action), action.responsible.email)
        if action.event_id:
            await hub.broadcast({"kind": "event_updated", "id": action.event_id})
    return action_out(action)
