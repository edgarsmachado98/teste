"""Indicadores de segurança para o painel e para o relatório mensal."""

from collections import Counter, defaultdict
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import audit
from ..auth import current_user, require_role
from ..common import TYPE_LABELS, is_overdue
from ..database import get_db
from ..models import ActionItem, Camera, Event, RuleStat, User
from ..timeutil import as_utc, shift_names, shift_of, to_local
from .events import local_range

router = APIRouter(prefix="/api/reports")


def _period(start: date | None, end: date | None) -> tuple[date, date]:
    end = end or date.today()
    start = start or end - timedelta(days=29)
    if start > end:
        raise HTTPException(400, "a data inicial é posterior à final")
    if (end - start).days > 366:
        raise HTTPException(400, "período máximo: 1 ano")
    return start, end


def _events(db: Session, start: date, end: date, camera_id: int | None) -> list[Event]:
    lo, hi = local_range(start, end)
    query = select(Event).options(selectinload(Event.camera)).where(Event.created_at >= lo, Event.created_at < hi)
    if camera_id is not None:
        query = query.where(Event.camera_id == camera_id)
    return list(db.scalars(query))


def _stats(db: Session, start: date, end: date, camera_id: int | None) -> list[RuleStat]:
    lo, hi = local_range(start, end)
    query = select(RuleStat).where(RuleStat.hour >= lo, RuleStat.hour < hi)
    if camera_id is not None:
        query = query.where(RuleStat.camera_id == camera_id)
    return list(db.scalars(query))


def _rate(observed: int, violations: int) -> float | None:
    return round(1 - violations / observed, 4) if observed else None


def build_summary(db: Session, start: date, end: date, camera_id: int | None) -> dict:
    events = _events(db, start, end, camera_id)
    deviations = [e for e in events if e.status != "descartada"]
    status = Counter(e.status for e in events)
    reviewed = [e for e in events if e.reviewed_at is not None]
    triage = [(as_utc(e.reviewed_at) - as_utc(e.created_at)).total_seconds() / 60 for e in reviewed]
    decided = status["confirmada"] + status["descartada"] + status["encerrada"]

    days = [(start + timedelta(days=i)) for i in range((end - start).days + 1)]
    by_day = Counter(to_local(e.created_at).date() for e in deviations)
    by_hour = Counter(to_local(e.created_at).hour for e in deviations)
    by_shift = Counter(shift_of(to_local(e.created_at)) for e in deviations)
    shifts = shift_names() + (["Fora de turno"] if by_shift.get("Fora de turno") else [])

    cameras = defaultdict(lambda: {"count": 0})
    for e in deviations:
        c = cameras[e.camera_id]
        c.update(camera_id=e.camera_id, camera=e.camera.name, location=e.camera.location or "–")
        c["count"] += 1
    locations = Counter(e.camera.location or "Sem local" for e in deviations)

    # Conformidade de EPI (observações do detector)
    stats = _stats(db, start, end, camera_id)
    cam_names = {c.id: (c.name, c.location) for c in db.scalars(select(Camera))}
    comp_cam: dict[int, list[int]] = defaultdict(lambda: [0, 0])
    comp_day: dict[date, list[int]] = defaultdict(lambda: [0, 0])
    comp_shift: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for s in stats:
        local = to_local(s.hour)
        for bucket in (comp_cam[s.camera_id], comp_day[local.date()], comp_shift[shift_of(local)]):
            bucket[0] += s.observed
            bucket[1] += s.violations
    observed = sum(s.observed for s in stats)
    violations = sum(s.violations for s in stats)

    # Período anterior, de mesmo tamanho, para comparação
    length = (end - start).days + 1
    prev_start, prev_end = start - timedelta(days=length), start - timedelta(days=1)
    prev_events = [e for e in _events(db, prev_start, prev_end, camera_id) if e.status != "descartada"]
    prev_stats = _stats(db, prev_start, prev_end, camera_id)

    lo, hi = local_range(start, end)
    actions_q = select(ActionItem).options(selectinload(ActionItem.event))
    all_actions = list(db.scalars(actions_q))
    if camera_id is not None:
        all_actions = [a for a in all_actions if a.event and a.event.camera_id == camera_id]
    in_period = [a for a in all_actions if lo <= as_utc(a.created_at) < hi]
    done_in_period = [a for a in all_actions if a.completed_at and lo <= as_utc(a.completed_at) < hi]
    on_time = [a for a in done_in_period if a.due_date is None or to_local(a.completed_at).date() <= a.due_date]

    return {
        "period": {"start": start, "end": end, "previous_start": prev_start, "previous_end": prev_end},
        "totals": {
            "events": len(events),
            "deviations": len(deviations),
            "previous_deviations": len(prev_events),
            "pending": status["nova"],
            "confirmed": status["confirmada"],
            "discarded": status["descartada"],
            "closed": status["encerrada"],
            "false_alarm_rate": round(status["descartada"] / decided, 4) if decided else None,
            "mean_triage_minutes": round(sum(triage) / len(triage), 1) if triage else None,
        },
        "by_type": [{"type": t, "label": TYPE_LABELS.get(t, t), "count": n}
                    for t, n in Counter(e.type for e in deviations).most_common()],
        "by_severity": dict(Counter(e.severity for e in deviations)),
        "by_classification": dict(Counter(e.classification or "nao_classificada" for e in deviations)),
        "by_camera": sorted(cameras.values(), key=lambda c: -c["count"]),
        "by_location": [{"location": loc, "count": n} for loc, n in locations.most_common()],
        "by_shift": [{"shift": s, "count": by_shift.get(s, 0)} for s in shifts],
        "by_day": [{"date": d, "count": by_day.get(d, 0)} for d in days],
        "by_hour": [by_hour.get(h, 0) for h in range(24)],
        "compliance": {
            "observed": observed,
            "violations": violations,
            "rate": _rate(observed, violations),
            "previous_rate": _rate(sum(s.observed for s in prev_stats), sum(s.violations for s in prev_stats)),
            "by_camera": sorted(
                [{"camera_id": cid, "camera": cam_names.get(cid, ("?", ""))[0],
                  "location": cam_names.get(cid, ("", ""))[1] or "–",
                  "observed": o, "violations": v, "rate": _rate(o, v)} for cid, (o, v) in comp_cam.items()],
                key=lambda c: c["rate"] if c["rate"] is not None else 2,
            ),
            "by_day": [{"date": d, "rate": _rate(*comp_day[d]) if d in comp_day else None} for d in days],
            "by_shift": [{"shift": s, "observed": comp_shift[s][0], "rate": _rate(*comp_shift[s])}
                         for s in shift_names() if s in comp_shift],
        },
        "actions": {
            "open": sum(1 for a in all_actions if a.status == "aberta"),
            "overdue": sum(1 for a in all_actions if is_overdue(a)),
            "created_in_period": len(in_period),
            "completed_in_period": len(done_in_period),
            "on_time_rate": round(len(on_time) / len(done_in_period), 4) if done_in_period else None,
        },
    }


@router.get("/summary", dependencies=[Depends(current_user)])
def summary(start: date | None = None, end: date | None = None, camera_id: int | None = None,
            db: Session = Depends(get_db)):
    start, end = _period(start, end)
    return build_summary(db, start, end, camera_id)


@router.get("/heatmap", dependencies=[Depends(current_user)])
def heatmap(camera_id: int, start: date | None = None, end: date | None = None, db: Session = Depends(get_db)):
    """Pontos (normalizados) onde ocorreram os desvios: pés das pessoas ou centro do fogo/fumaça."""
    start, end = _period(start, end)
    points = []
    for e in _events(db, start, end, camera_id):
        if e.status == "descartada" or not e.boxes:
            continue
        for x1, y1, x2, y2 in e.boxes:
            points.append([round((x1 + x2) / 2, 4), round(y2 if e.type != "fire_smoke" else (y1 + y2) / 2, 4)])
    return {"camera_id": camera_id, "points": points}


@router.post("/export-log", status_code=204)
def log_export(request: Request, start: date | None = None, end: date | None = None,
               user: User = Depends(require_role("tecnico")), db: Session = Depends(get_db)):
    """Registra na auditoria a geração do relatório (que é montado no navegador)."""
    start, end = _period(start, end)
    audit.record(db, user, "relatorio_gerado", "relatorio", None, f"{start:%d/%m/%Y} a {end:%d/%m/%Y}", request)
    db.commit()
