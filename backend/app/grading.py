"""Regras de gradação: sugerem a medida conforme o histórico da pessoa. A decisão é sempre
de uma pessoa (técnico, gestor ou RH): nada é aplicado automaticamente."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import SessionLocal
from .models import Event, Person, SystemState

LABELS = {"orientacao": "Orientação registrada", "treinamento": "Encaminhar para treinamento",
          "advertencia": "Advertência escrita", "rh": "Encaminhar ao RH"}

DEFAULT = {
    "window_days": 90,
    "steps": ["orientacao", "treinamento", "advertencia", "rh"],
    # degrau inicial (1 = primeiro) por severidade da regra e por tipo de desvio
    "severity_start": {"critica": 2},
    "type_start": {},
    "require_evidence_for_warning": True,
    "require_witnesses_on_refusal": False,
    "transparency_text": (
        "As áreas operacionais são monitoradas por câmeras para verificar o uso de EPI e o respeito às áreas de "
        "risco. Quando um desvio é registrado, a equipe de segurança pode identificar o colaborador para "
        "orientação, treinamento ou, em reincidência, advertência, conforme o art. 158 da CLT e a NR-6. Não há "
        "reconhecimento facial."),
    "default_trainings": ["Reciclagem NR-6 · uso correto de EPI", "DDS dirigido no posto",
                          "NR-12 · segurança em máquinas e equipamentos"],
}
KEY = "gradacao"


def load(db: Session | None = None) -> dict:
    close = db is None
    db = db or SessionLocal()
    try:
        row = db.get(SystemState, KEY)
        stored = json.loads(row.value) if row and row.value else {}
    finally:
        if close:
            db.close()
    return {**DEFAULT, **stored}


def validate(cfg: dict) -> dict:
    out = {**DEFAULT, **{k: v for k, v in cfg.items() if k in DEFAULT}}
    days = int(out["window_days"])
    if not 7 <= days <= 730:
        raise ValueError("janela entre 7 e 730 dias")
    steps = list(out["steps"])
    if not 1 <= len(steps) <= 6 or any(s not in LABELS for s in steps):
        raise ValueError("escada com 1 a 6 degraus, usando orientacao, treinamento, advertencia ou rh")
    for mapping in ("severity_start", "type_start"):
        out[mapping] = {k: max(1, min(int(v), len(steps))) for k, v in dict(out[mapping]).items()}
    out["window_days"], out["steps"] = days, steps
    out["default_trainings"] = [t.strip()[:160] for t in out["default_trainings"] if t.strip()][:20]
    out["transparency_text"] = str(out["transparency_text"])[:3000]
    return out


def save(db: Session, cfg: dict) -> dict:
    clean = validate(cfg)
    db.merge(SystemState(key=KEY, value=json.dumps(clean, ensure_ascii=False)))
    db.commit()
    return clean


def count_in_window(db: Session, person: Person, event: Event, window_days: int) -> int:
    """Ocorrências do mesmo tipo atribuídas à pessoa na janela (inclui a atual)."""
    since = event.created_at - timedelta(days=window_days)
    rows = db.scalars(select(Event.id).where(
        Event.person_id == person.id, Event.type == event.type, Event.status != "descartada",
        Event.created_at >= since, Event.created_at <= event.created_at, Event.id != event.id)).all()
    return len(rows) + 1


def suggest(db: Session, person: Person, event: Event) -> dict:
    cfg = load(db)
    steps = cfg["steps"]
    count = count_in_window(db, person, event, cfg["window_days"])
    index = min(count, len(steps)) - 1
    start = max(cfg["severity_start"].get(event.severity, 1), cfg["type_start"].get(event.type, 1))
    reasons = [f"{count}ª ocorrência deste tipo em {cfg['window_days']} dias"]
    if start - 1 > index:
        index = start - 1
        reasons.append("desvio grave: começa em degrau acima")
    measure = steps[index]
    next_step = steps[min(index + 1, len(steps) - 1)]
    until = (event.created_at + timedelta(days=cfg["window_days"])).date()
    return {"type": measure, "label": LABELS[measure], "count": count, "step": index + 1,
            "reason": "; ".join(reasons), "window_days": cfg["window_days"],
            "next_type": next_step, "next_label": LABELS[next_step], "reset_on": until}


def next_measure(db: Session, person: Person) -> dict | None:
    """Para o histórico: o que acontece se houver nova ocorrência (pelo tipo mais recente)."""
    last = db.scalar(select(Event).where(Event.person_id == person.id, Event.status != "descartada")
                     .order_by(Event.created_at.desc()))
    if last is None:
        return None
    cfg = load(db)
    if datetime.now(timezone.utc) - last.created_at > timedelta(days=cfg["window_days"]):
        return {"label": LABELS[cfg["steps"][0]], "type": cfg["steps"][0], "until": None, "event_type": last.type}
    fake = Event(type=last.type, severity=last.severity, created_at=datetime.now(timezone.utc))
    fake.id = -1
    s = suggest(db, person, fake)
    until = (last.created_at + timedelta(days=cfg["window_days"])).date()
    return {"label": s["label"], "type": s["type"], "until": until, "event_type": last.type}
