"""Identificação assistida da pessoa, medidas educativas/disciplinares, ciência e histórico."""

import base64
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from .. import audit, grading
from ..auth import has_role, require_role
from ..common import camera_name, get_or_404
from ..database import get_db
from ..models import Camera, Event, Measure, Person, TrainingRecord, User
from ..people import mask_cpf, only_digits, people_dir
from ..timeutil import shift_of, to_local
from ..ws import hub
from .people import person_query

router = APIRouter(prefix="/api")
tecnico = require_role("tecnico")

ACK_LABELS = {"pendente": "pendente", "assinada": "assinada", "impressa": "termo impresso", "recusada": "recusou assinar"}


def measure_out(m: Measure) -> dict:
    return {
        "id": m.id, "number": m.number, "event_id": m.event_id, "person_id": m.person_id,
        "person_name": m.person.name if m.person else None, "type": m.type, "label": grading.LABELS[m.type],
        "suggested_type": m.suggested_type, "justification": m.justification, "description": m.description,
        "training_name": m.training_name, "training_date": m.training_date, "status": m.status,
        "approved_by": m.approved_by.name if m.approved_by else None, "approved_at": m.approved_at,
        "ack": m.ack, "ack_label": ACK_LABELS[m.ack], "ack_at": m.ack_at, "has_signature": bool(m.signature_file),
        "statement": m.statement, "witnesses": m.witnesses,
        "created_by": m.created_by.name if m.created_by else None, "created_at": m.created_at,
        "event_message": m.event.message if m.event else None,
        "event_at": m.event.created_at if m.event else None,
        "camera_name": camera_name(m.event) if m.event else None,
    }


def measure_query():
    return select(Measure).options(selectinload(Measure.person), selectinload(Measure.created_by),
                                   selectinload(Measure.approved_by),
                                   selectinload(Measure.event).selectinload(Event.camera))


# ---------- Identificação assistida ----------

@router.get("/events/{event_id}/candidates")
def candidates(event_id: int, q: str = "", _: User = Depends(tecnico), db: Session = Depends(get_db)):
    """Candidatos para a ocorrência: pessoas do setor da câmera, priorizando o turno do horário.
    A escolha é sempre de uma pessoa: o sistema só ordena a lista (sem reconhecimento facial)."""
    event = get_or_404(db, Event, event_id)
    camera = db.get(Camera, event.camera_id)
    shift = shift_of(to_local(event.created_at))
    cfg = grading.load(db)
    since = event.created_at - timedelta(days=cfg["window_days"])
    query = person_query().where(Person.status == "ativo")
    if q.strip():
        term = q.strip()
        digits = only_digits(term)
        conds = [Person.name.ilike(f"%{term}%"), Person.registration.ilike(f"%{term}%"), Person.badge_code == term.upper()]
        if len(digits) >= 3:
            conds.append(Person.cpf.contains(digits))
        query = query.where(or_(*conds))
    elif camera and camera.sector_id:
        query = query.where(Person.sector_id == camera.sector_id)
    else:
        query = query.limit(0)  # câmera sem setor: use a busca
    people = db.scalars(query).all()
    counts = dict(db.execute(select(Event.person_id, func.count()).where(
        Event.person_id.in_([p.id for p in people]), Event.status != "descartada", Event.created_at >= since,
        Event.id != event.id).group_by(Event.person_id)).all()) if people else {}
    rows = []
    for p in people:
        same_shift = bool(p.shift) and p.shift == shift
        rows.append({"id": p.id, "name": p.name, "role": p.role, "shift": p.shift, "sector": p.sector.name if p.sector else None,
                     "registration": p.registration, "badge_code": p.badge_code, "has_photo": bool(p.photo_file),
                     "cpf": mask_cpf(p.cpf), "same_shift": same_shift, "recent": counts.get(p.id, 0)})
    rows.sort(key=lambda r: (not r["same_shift"], r["name"]))
    return {"shift": shift, "sector": camera.sector.name if camera and camera.sector else None,
            "has_sector": bool(camera and camera.sector_id), "current_person_id": event.person_id,
            "candidates": rows[:100], "window_days": cfg["window_days"]}


class IdentifyIn(BaseModel):
    person_id: int | None = None  # None = não foi possível identificar
    method: str = Field("lista", pattern="^(lista|numero|busca)$")


@router.post("/events/{event_id}/identify")
async def identify(event_id: int, data: IdentifyIn, request: Request, user: User = Depends(tecnico),
                   db: Session = Depends(get_db)):
    event = get_or_404(db, Event, event_id)
    if event.status == "descartada":
        raise HTTPException(400, "ocorrência marcada como falso alarme")
    now = datetime.now(timezone.utc)
    if data.person_id is None:
        event.person_id, event.identification = None, "nao_identificado"
        detail = "pessoa não identificada"
    else:
        person = get_or_404(db, Person, data.person_id)
        event.person_id, event.identification = person.id, data.method
        detail = f"pessoa identificada: {person.name} (por {data.method})"
    event.identified_by_id, event.identified_at = user.id, now
    if event.status == "nova":
        event.status, event.reviewed_by_id, event.reviewed_at = "confirmada", user.id, now
        detail += "; status: nova → confirmada"
    audit.record(db, user, "pessoa_identificada", "ocorrencia", event.id, detail, request)
    db.commit()
    await hub.broadcast({"kind": "event_updated", "id": event.id})
    return {"person_id": event.person_id, "identification": event.identification}


@router.get("/events/{event_id}/suggestion")
def suggestion(event_id: int, _: User = Depends(tecnico), db: Session = Depends(get_db)):
    event = get_or_404(db, Event, event_id)
    if not event.person_id:
        raise HTTPException(400, "identifique a pessoa antes de definir a medida")
    person = db.scalar(person_query().where(Person.id == event.person_id))
    cfg = grading.load(db)
    return {**grading.suggest(db, person, event), "trainings": cfg["default_trainings"],
            "has_evidence": bool(event.image_file or event.clip_dir),
            "require_evidence_for_warning": cfg["require_evidence_for_warning"],
            "require_witnesses_on_refusal": cfg["require_witnesses_on_refusal"],
            "person": {"id": person.id, "name": person.name, "role": person.role, "sector": person.sector.name if person.sector else None,
                       "shift": person.shift, "manager": person.manager, "has_photo": bool(person.photo_file)}}


# ---------- Medidas ----------

class MeasureIn(BaseModel):
    event_id: int
    type: str = Field(pattern="^(orientacao|treinamento|advertencia|rh)$")
    description: str = Field("", max_length=4000)
    training_name: str = Field("", max_length=160)
    training_date: date | None = None
    justification: str = Field("", max_length=2000)


def _next_number(db: Session) -> str:
    year = date.today().year
    prefix = f"VIG-{year}-"
    last = db.scalar(select(Measure.number).where(Measure.number.like(f"{prefix}%")).order_by(Measure.number.desc()))
    seq = int(last.rsplit("-", 1)[1]) + 1 if last else 1
    return f"{prefix}{seq:04d}"


@router.post("/measures", status_code=201)
async def create_measure(data: MeasureIn, request: Request, user: User = Depends(tecnico), db: Session = Depends(get_db)):
    event = get_or_404(db, Event, data.event_id)
    if not event.person_id:
        raise HTTPException(400, "identifique a pessoa antes de aplicar a medida")
    person = db.scalar(person_query().where(Person.id == event.person_id))
    cfg = grading.load(db)
    sug = grading.suggest(db, person, event)
    if data.type != sug["type"] and len(data.justification.strip()) < 10:
        raise HTTPException(422, f"a medida sugerida é '{sug['label']}': justifique a escolha diferente (mín. 10 caracteres)")
    if data.type == "advertencia" and cfg["require_evidence_for_warning"] and not (event.image_file or event.clip_dir):
        raise HTTPException(400, "advertência exige evidência (foto ou clipe) na ocorrência")
    if data.type == "treinamento" and not data.training_name.strip():
        raise HTTPException(422, "informe o treinamento")
    approved = data.type != "advertencia" or has_role(user, "gestor")
    now = datetime.now(timezone.utc)
    measure = Measure(number=_next_number(db), event_id=event.id, person_id=person.id, type=data.type,
                      suggested_type=sug["type"], justification=data.justification.strip(),
                      description=data.description.strip(),
                      training_name=data.training_name.strip() if data.type == "treinamento" else "",
                      training_date=data.training_date if data.type == "treinamento" else None, status="aplicada" if approved else "pendente_aprovacao",
                      approved_by_id=user.id if approved and data.type == "advertencia" else None,
                      approved_at=now if approved and data.type == "advertencia" else None, created_by_id=user.id)
    db.add(measure)
    db.flush()
    if data.type == "treinamento":
        db.add(TrainingRecord(person_id=person.id, name=measure.training_name, scheduled_on=measure.training_date,
                              status="agendado", measure_id=measure.id))
    detail = f"medida {measure.number}: {grading.LABELS[data.type]} para {person.name}"
    if data.type != sug["type"]:
        detail += f" (sugerida: {sug['label']})"
    if not approved:
        detail += " – aguardando aprovação"
    audit.record(db, user, "medida_registrada", "ocorrencia", event.id, detail, request)
    audit.record(db, user, "medida_registrada", "pessoa", person.id, detail, request)
    db.commit()
    await hub.broadcast({"kind": "event_updated", "id": event.id})
    return measure_out(db.scalar(measure_query().where(Measure.id == measure.id)))


@router.get("/measures")
def list_measures(status: str | None = None, person_id: int | None = None, user: User = Depends(tecnico),
                  db: Session = Depends(get_db)):
    query = measure_query().order_by(Measure.created_at.desc()).limit(300)
    if status:
        query = query.where(Measure.status.in_(status.split(",")))
    if person_id is not None:
        query = query.where(Measure.person_id == person_id)
    return [measure_out(m) for m in db.scalars(query)]


@router.get("/measures/{measure_id}")
def get_measure(measure_id: int, _: User = Depends(tecnico), db: Session = Depends(get_db)):
    m = db.scalar(measure_query().where(Measure.id == measure_id))
    if m is None:
        raise HTTPException(404, "não encontrada")
    out = measure_out(m)
    out["person"] = {"name": m.person.name, "registration": m.person.registration, "role": m.person.role,
                     "sector": m.person.sector.name if m.person.sector else None, "unit": m.person.unit.name}
    return out


class DecisionIn(BaseModel):
    approve: bool
    note: str = Field("", max_length=1000)


@router.post("/measures/{measure_id}/decision")
async def decide(measure_id: int, data: DecisionIn, request: Request, user: User = Depends(require_role("gestor")),
                 db: Session = Depends(get_db)):
    m = db.scalar(measure_query().where(Measure.id == measure_id))
    if m is None or m.status != "pendente_aprovacao":
        raise HTTPException(400, "medida não está aguardando aprovação")
    m.status = "aplicada" if data.approve else "cancelada"
    m.approved_by_id, m.approved_at = user.id, datetime.now(timezone.utc)
    detail = f"medida {m.number} {'aprovada' if data.approve else 'recusada'}" + (f": {data.note}" if data.note else "")
    audit.record(db, user, "medida_decidida", "pessoa", m.person_id, detail, request)
    if m.event_id:
        audit.record(db, user, "medida_decidida", "ocorrencia", m.event_id, detail, request)
    db.commit()
    db.refresh(m)
    if m.event_id:
        await hub.broadcast({"kind": "event_updated", "id": m.event_id})
    return measure_out(m)


class AckIn(BaseModel):
    ack: str = Field(pattern="^(assinada|impressa|recusada)$")
    signature: str | None = None  # data URL PNG
    statement: str = Field("", max_length=4000)
    witnesses: str = Field("", max_length=1000)


@router.post("/measures/{measure_id}/ack")
async def acknowledge(measure_id: int, data: AckIn, request: Request, user: User = Depends(tecnico),
                      db: Session = Depends(get_db)):
    m = db.scalar(measure_query().where(Measure.id == measure_id))
    if m is None:
        raise HTTPException(404, "não encontrada")
    if m.status != "aplicada":
        raise HTTPException(400, "a ciência é colhida depois que a medida está aplicada (aprovada)")
    cfg = grading.load(db)
    if data.ack == "assinada":
        prefix = "data:image/png;base64,"
        if not data.signature or not data.signature.startswith(prefix):
            raise HTTPException(422, "assinatura ausente")
        raw = base64.b64decode(data.signature[len(prefix):], validate=True)
        if not raw.startswith(b"\x89PNG") or len(raw) > 1024 * 1024:
            raise HTTPException(422, "assinatura inválida")
        folder = people_dir() / "assinaturas"
        folder.mkdir(parents=True, exist_ok=True)
        name = f"assinaturas/{m.number}-{uuid.uuid4().hex[:8]}.png"
        (people_dir() / name).write_bytes(raw)
        m.signature_file = name
    if data.ack == "recusada" and cfg["require_witnesses_on_refusal"] and len(data.witnesses.strip()) < 5:
        raise HTTPException(422, "informe as duas testemunhas da recusa")
    m.ack, m.ack_at = data.ack, datetime.now(timezone.utc)
    m.statement, m.witnesses = data.statement.strip(), data.witnesses.strip()
    detail = f"medida {m.number}: ciência {ACK_LABELS[data.ack]}" + (" · colaborador registrou sua versão" if m.statement else "")
    audit.record(db, user, "ciencia_registrada", "pessoa", m.person_id, detail, request)
    if m.event_id:
        audit.record(db, user, "ciencia_registrada", "ocorrencia", m.event_id, detail, request)
    db.commit()
    if m.event_id:
        await hub.broadcast({"kind": "event_updated", "id": m.event_id})
    return measure_out(m)


@router.get("/measures/{measure_id}/signature", dependencies=[Depends(tecnico)])
def signature(measure_id: int, db: Session = Depends(get_db)):
    m = get_or_404(db, Measure, measure_id)
    if not m.signature_file:
        raise HTTPException(404, "sem assinatura")
    return FileResponse(people_dir() / m.signature_file, media_type="image/png")


# ---------- Histórico da pessoa e regras de gradação ----------

@router.get("/people/{person_id}/history")
def person_history(person_id: int, request: Request, user: User = Depends(tecnico), db: Session = Depends(get_db)):
    person = db.scalar(person_query().where(Person.id == person_id))
    if person is None:
        raise HTTPException(404, "não encontrado")
    events = db.scalars(select(Event).options(selectinload(Event.camera), selectinload(Event.identified_by))
                        .where(Event.person_id == person.id).order_by(Event.created_at.desc())).all()
    measures = db.scalars(measure_query().where(Measure.person_id == person.id).order_by(Measure.created_at.desc())).all()
    year_ago = datetime.now(timezone.utc) - timedelta(days=365)
    cfg = grading.load(db)
    window = datetime.now(timezone.utc) - timedelta(days=cfg["window_days"])
    timeline = []
    for e in events:
        timeline.append({"kind": "ocorrencia", "at": e.created_at, "event_id": e.id, "title": e.message,
                         "detail": f"{camera_name(e)} · identificada por {e.identified_by.name if e.identified_by else '–'}",
                         "status": e.status})
    for m in measures:
        timeline.append({"kind": "medida", "at": m.created_at, "event_id": m.event_id, "measure_id": m.id,
                         "title": grading.LABELS[m.type], "detail": f"{m.number} · ciência {ACK_LABELS[m.ack]}",
                         "status": m.status})
    for t in person.trainings:
        at = datetime.combine(t.scheduled_on, datetime.min.time(), timezone.utc) if t.scheduled_on else t.created_at
        timeline.append({"kind": "treinamento", "at": at, "title": t.name, "detail": t.status, "status": t.status})
    timeline.sort(key=lambda x: x["at"], reverse=True)
    applied = [m for m in measures if m.status == "aplicada" and m.created_at >= year_ago]
    audit.record(db, user, "historico_consultado", "pessoa", person.id, person.name, request)
    db.commit()
    return {
        "person": {"id": person.id, "name": person.name, "role": person.role, "registration": person.registration,
                   "sector": person.sector.name if person.sector else None, "shift": person.shift,
                   "has_photo": bool(person.photo_file), "status": person.status},
        "summary": {
            "events_12m": sum(1 for e in events if e.created_at >= year_ago and e.status != "descartada"),
            "events_window": sum(1 for e in events if e.created_at >= window and e.status != "descartada"),
            "window_days": cfg["window_days"],
            "orientations": sum(1 for m in applied if m.type == "orientacao"),
            "trainings": sum(1 for m in applied if m.type == "treinamento"),
            "warnings": sum(1 for m in applied if m.type == "advertencia"),
            "pending": sum(1 for m in measures if m.status == "pendente_aprovacao"),
        },
        "next": grading.next_measure(db, person),
        "timeline": timeline,
    }


@router.get("/grading", dependencies=[Depends(tecnico)])
def get_grading(db: Session = Depends(get_db)):
    return {**grading.load(db), "labels": grading.LABELS}


@router.put("/grading")
def put_grading(data: dict, request: Request, user: User = Depends(require_role("admin")), db: Session = Depends(get_db)):
    try:
        cfg = grading.save(db, data)
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, str(exc)) from exc
    audit.record(db, user, "gradacao_alterada", "sistema", None,
                 f"janela {cfg['window_days']} dias; escada: {' → '.join(cfg['steps'])}", request)
    db.commit()
    return {**cfg, "labels": grading.LABELS}
