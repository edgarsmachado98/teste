"""Guia DDS: temas, plano (programação) e registro de realização com presença."""

from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, dds
from ..auth import current_user, require_role
from ..common import get_or_404
from ..database import get_db
from ..models import DDSAttendance, DDSSession, DDSTheme, Person, Sector, Unit, User

router = APIRouter(prefix="/api/dds")
editor = require_role("tecnico")

MAX_PLAN_DAYS = 92


# ---------- Esquemas ----------

class ThemeIn(BaseModel):
    category: str = Field(min_length=1, max_length=60)
    title: str = Field(min_length=3, max_length=200)
    reference: str = Field("", max_length=120)
    points: list[str] = []
    question: str = Field("", max_length=300)
    minutes: int = Field(10, ge=5, le=60)

    @field_validator("points")
    @classmethod
    def clean_points(cls, items: list[str]) -> list[str]:
        return [p.strip()[:300] for p in items if p.strip()][:10]


class SessionIn(BaseModel):
    unit_id: int
    sector_id: int | None = None
    shift: str = Field("", max_length=60)
    day: date
    theme_id: int
    facilitator: str = Field("", max_length=120)
    notes: str = Field("", max_length=2000)
    status: Literal["planejado", "cancelado"] = "planejado"


class RecordIn(BaseModel):
    person_ids: list[int] = []
    extra_participants: int = Field(0, ge=0, le=500)
    facilitator: str = Field(min_length=2, max_length=120)
    notes: str = Field("", max_length=2000)


class PlanIn(BaseModel):
    unit_id: int
    sector_id: int | None = None
    shift: str = Field("", max_length=60)
    start: date
    end: date
    weekdays: list[int] = [0, 1, 2, 3, 4]
    facilitator: str = Field("", max_length=120)
    dry_run: bool = True


# ---------- Saída ----------

def theme_out(t: DDSTheme, last_used: date | None = None, uses: int = 0) -> dict:
    return {"id": t.id, "code": t.code, "category": t.category, "title": t.title, "reference": t.reference,
            "points": t.points or [], "question": t.question, "minutes": t.minutes, "builtin": t.builtin,
            "triggers": t.triggers or [], "last_used": last_used, "uses": uses}


def session_out(s: DDSSession) -> dict:
    today = date.today()
    return {
        "id": s.id, "unit_id": s.unit_id, "unit": s.unit.name if s.unit else None, "sector_id": s.sector_id,
        "sector": s.sector.name if s.sector else None, "shift": s.shift, "day": s.day, "theme_id": s.theme_id,
        "title": s.title, "category": s.theme.category if s.theme else None,
        "reference": s.theme.reference if s.theme else "", "points": s.theme.points if s.theme else [],
        "question": s.theme.question if s.theme else "", "minutes": s.theme.minutes if s.theme else 10,
        "facilitator": s.facilitator, "status": s.status, "reason": s.reason, "notes": s.notes,
        "late": s.status == "planejado" and s.day < today,
        "participants": len(s.attendance) + s.extra_participants, "extra_participants": s.extra_participants,
        "person_ids": [a.person_id for a in s.attendance], "held_at": s.held_at,
    }


# ---------- Temas ----------

@router.get("/themes", dependencies=[Depends(current_user)])
def list_themes(unit_id: int | None = None, db: Session = Depends(get_db)):
    from sqlalchemy import func
    q = select(DDSSession.theme_id, func.max(DDSSession.day), func.count()).where(
        DDSSession.status == "realizado").group_by(DDSSession.theme_id)
    if unit_id is not None:
        q = q.where(DDSSession.unit_id == unit_id)
    usage = {tid: (last, n) for tid, last, n in db.execute(q).all()}
    themes = db.scalars(select(DDSTheme).where(DDSTheme.active.is_(True)).order_by(DDSTheme.category, DDSTheme.title))
    return {"categories": dds.CATEGORIES,
            "themes": [theme_out(t, *usage.get(t.id, (None, 0))) for t in themes]}


@router.post("/themes", status_code=201)
def create_theme(data: ThemeIn, request: Request, user: User = Depends(editor), db: Session = Depends(get_db)):
    theme = DDSTheme(**data.model_dump(), builtin=False)
    db.add(theme)
    db.flush()
    audit.record(db, user, "dds_tema_criado", "dds", theme.id, theme.title, request)
    db.commit()
    return theme_out(theme)


@router.put("/themes/{theme_id}")
def update_theme(theme_id: int, data: ThemeIn, request: Request, user: User = Depends(editor),
                 db: Session = Depends(get_db)):
    theme = get_or_404(db, DDSTheme, theme_id)
    if theme.builtin:
        raise HTTPException(400, "temas de referência não são editados: crie um tema próprio a partir dele")
    for k, v in data.model_dump().items():
        setattr(theme, k, v)
    audit.record(db, user, "dds_tema_alterado", "dds", theme.id, theme.title, request)
    db.commit()
    return theme_out(theme)


@router.delete("/themes/{theme_id}", status_code=204)
def delete_theme(theme_id: int, request: Request, user: User = Depends(editor), db: Session = Depends(get_db)):
    theme = get_or_404(db, DDSTheme, theme_id)
    if theme.builtin:
        raise HTTPException(400, "temas de referência não podem ser excluídos")
    theme.active = False  # o histórico dos DDS realizados continua com o título
    audit.record(db, user, "dds_tema_excluido", "dds", theme.id, theme.title, request)
    db.commit()


@router.get("/suggestions", dependencies=[Depends(current_user)])
def suggestions(unit_id: int | None = None, sector_id: int | None = None, days: int = 30,
                db: Session = Depends(get_db)):
    return dds.suggestions(db, unit_id, sector_id, max(7, min(days, 180)))


# ---------- Plano ----------

def _check_place(db: Session, unit_id: int, sector_id: int | None) -> None:
    get_or_404(db, Unit, unit_id)
    if sector_id is not None and get_or_404(db, Sector, sector_id).unit_id != unit_id:
        raise HTTPException(422, "o setor escolhido é de outra unidade")


@router.get("/sessions", dependencies=[Depends(current_user)])
def list_sessions(start: date | None = None, end: date | None = None, unit_id: int | None = None,
                  sector_id: int | None = None, status: str | None = None, db: Session = Depends(get_db)):
    start = start or date.today().replace(day=1)
    end = end or (start + timedelta(days=40)).replace(day=1) - timedelta(days=1)
    q = select(DDSSession).where(DDSSession.day >= start, DDSSession.day <= end).order_by(DDSSession.day, DDSSession.shift)
    if unit_id is not None:
        q = q.where(DDSSession.unit_id == unit_id)
    if sector_id is not None:
        q = q.where(DDSSession.sector_id == sector_id)
    if status:
        q = q.where(DDSSession.status.in_(status.split(",")))
    sessions = db.scalars(q).all()
    done = [s for s in sessions if s.status == "realizado"]
    due = [s for s in sessions if s.status != "cancelado" and s.day <= date.today()]
    return {
        "start": start, "end": end, "sessions": [session_out(s) for s in sessions],
        "summary": {
            "planned": sum(1 for s in sessions if s.status != "cancelado"),
            "done": len(done),
            "late": sum(1 for s in sessions if s.status == "planejado" and s.day < date.today()),
            "canceled": sum(1 for s in sessions if s.status == "cancelado"),
            "adherence": round(len(done) / len(due), 4) if due else None,  # realizados ÷ previstos até hoje
            "participants": sum(len(s.attendance) + s.extra_participants for s in done),
        },
    }


@router.post("/sessions", status_code=201)
def create_session(data: SessionIn, request: Request, user: User = Depends(editor), db: Session = Depends(get_db)):
    _check_place(db, data.unit_id, data.sector_id)
    theme = get_or_404(db, DDSTheme, data.theme_id)
    s = DDSSession(**data.model_dump(), title=theme.title, created_by_id=user.id, reason="escolhido manualmente")
    db.add(s)
    db.flush()
    audit.record(db, user, "dds_programado", "dds", s.id, f"{s.day:%d/%m/%Y}: {s.title}", request)
    db.commit()
    db.refresh(s)
    return session_out(s)


@router.put("/sessions/{session_id}")
def update_session(session_id: int, data: SessionIn, request: Request, user: User = Depends(editor),
                   db: Session = Depends(get_db)):
    s = get_or_404(db, DDSSession, session_id)
    if s.status == "realizado":
        raise HTTPException(400, "DDS já realizado: o registro não é alterado")
    _check_place(db, data.unit_id, data.sector_id)
    theme = get_or_404(db, DDSTheme, data.theme_id)
    if theme.id != s.theme_id:
        s.title, s.reason = theme.title, "alterado manualmente"
    for k, v in data.model_dump().items():
        setattr(s, k, v)
    audit.record(db, user, "dds_alterado", "dds", s.id, f"{s.day:%d/%m/%Y}: {s.title} ({s.status})", request)
    db.commit()
    return session_out(s)


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(session_id: int, request: Request, user: User = Depends(editor), db: Session = Depends(get_db)):
    s = get_or_404(db, DDSSession, session_id)
    if s.status == "realizado":
        raise HTTPException(400, "DDS realizado é registro de segurança e não pode ser excluído")
    audit.record(db, user, "dds_excluido", "dds", s.id, f"{s.day:%d/%m/%Y}: {s.title}", request)
    db.delete(s)
    db.commit()


@router.post("/sessions/{session_id}/record")
def record_session(session_id: int, data: RecordIn, request: Request, user: User = Depends(editor),
                   db: Session = Depends(get_db)):
    """Registra a realização: quem conduziu, presentes (do cadastro) e participantes sem cadastro."""
    s = get_or_404(db, DDSSession, session_id)
    if s.status == "cancelado":
        raise HTTPException(400, "DDS cancelado: reabra antes de registrar")
    if s.day > date.today():
        raise HTTPException(400, "não é possível registrar um DDS com data futura")
    ids = list(dict.fromkeys(data.person_ids))
    if ids:
        found = set(db.scalars(select(Person.id).where(Person.id.in_(ids))))
        if found != set(ids):
            raise HTTPException(422, "pessoa não encontrada no cadastro")
    if not ids and not data.extra_participants:
        raise HTTPException(422, "informe os participantes")
    s.attendance = [DDSAttendance(person_id=pid) for pid in ids]
    s.extra_participants = data.extra_participants
    s.facilitator, s.notes = data.facilitator, data.notes
    first = s.status != "realizado"
    s.status = "realizado"
    s.held_at = s.held_at or datetime.now(timezone.utc)
    s.recorded_by_id = user.id
    audit.record(db, user, "dds_realizado" if first else "dds_presenca_alterada", "dds", s.id,
                 f"{s.day:%d/%m/%Y}: {s.title} – {len(ids) + data.extra_participants} participante(s)", request)
    db.commit()
    db.refresh(s)
    return session_out(s)


@router.post("/plan")
def plan(data: PlanIn, request: Request, user: User = Depends(editor), db: Session = Depends(get_db)):
    """Gera a programação do período. dry_run=true devolve a prévia sem gravar."""
    _check_place(db, data.unit_id, data.sector_id)
    if data.end < data.start:
        raise HTTPException(422, "o fim do período é anterior ao início")
    if (data.end - data.start).days > MAX_PLAN_DAYS:
        raise HTTPException(422, f"gere no máximo {MAX_PLAN_DAYS} dias por vez")
    weekdays = sorted({d for d in data.weekdays if 0 <= d <= 6})
    if not weekdays:
        raise HTTPException(422, "escolha ao menos um dia da semana")
    dds.ensure_themes(db)
    items = dds.generate_plan(db, data.unit_id, data.sector_id, data.shift, data.start, data.end, weekdays,
                              data.facilitator)
    if data.dry_run:
        return {"created": 0, "items": items}
    for it in items:
        db.add(DDSSession(unit_id=data.unit_id, sector_id=data.sector_id, shift=data.shift, day=it["date"],
                          theme_id=it["theme_id"], title=it["title"], facilitator=data.facilitator,
                          reason=it["reason"], created_by_id=user.id))
    audit.record(db, user, "dds_plano_gerado", "dds", None,
                 f"{len(items)} DDS de {data.start:%d/%m/%Y} a {data.end:%d/%m/%Y}", request)
    db.commit()
    return {"created": len(items), "items": items}


@router.get("/people/{person_id}", dependencies=[Depends(editor)])
def person_dds(person_id: int, db: Session = Depends(get_db)):
    """DDS de que a pessoa participou (para o histórico do colaborador)."""
    rows = db.scalars(select(DDSSession).join(DDSAttendance).where(DDSAttendance.person_id == person_id)
                      .order_by(DDSSession.day.desc()).limit(100)).all()
    return [{"id": s.id, "day": s.day, "title": s.title, "facilitator": s.facilitator} for s in rows]
