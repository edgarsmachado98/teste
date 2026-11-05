"""EPI e uniformes: estoque por unidade, entregas com comprovante assinado, vencimento de CA e plano de troca.

Base legal: NR-6 (6.6.1 – fornecer EPI com CA, orientar, substituir quando danificado e registrar o
fornecimento, podendo ser em sistema eletrônico) e Lei 14.063/2020 (assinatura eletrônica)."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Person, PPEDelivery, PPEItem, PPEMovement, PPEReceipt, PPEStock, Sector
from .sectors import PPE_LABELS


class StockError(ValueError):
    pass


def norm(text: str) -> str:
    """minúsculas e sem acento, para comparar "Óculos de proteção" com "oculos"."""
    t = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return " ".join(t.split())


# ---------- Estoque ----------

def stock_row(db: Session, unit_id: int, item_id: int, size: str, create: bool = True) -> PPEStock | None:
    row = db.scalar(select(PPEStock).where(PPEStock.unit_id == unit_id, PPEStock.item_id == item_id,
                                          PPEStock.size == (size or "")))
    if row is None and create:
        row = PPEStock(unit_id=unit_id, item_id=item_id, size=size or "", quantity=0, min_quantity=0)
        db.add(row)
        db.flush()
    return row


def move(db: Session, *, unit_id: int, item_id: int, size: str, type_: str, quantity: int, note: str = "",
         user_name: str = "", person_id: int | None = None, receipt_id: int | None = None,
         allow_negative: bool = False) -> PPEStock:
    """Lança um movimento (quantity com sinal) e atualiza o saldo. Saída sem saldo é recusada."""
    row = stock_row(db, unit_id, item_id, size)
    if row.quantity + quantity < 0 and not allow_negative:
        item = db.get(PPEItem, item_id)
        label = f"{item.name if item else 'item'}{f' tam. {size}' if size else ''}"
        raise StockError(f"estoque insuficiente de {label}: saldo {row.quantity}, pedido {-quantity}")
    row.quantity += quantity
    db.add(PPEMovement(unit_id=unit_id, item_id=item_id, size=size or "", type=type_, quantity=quantity,
                       balance=row.quantity, note=note[:300], user_name=user_name, person_id=person_id,
                       receipt_id=receipt_id))
    return row


def is_low(row: PPEStock) -> bool:
    return row.min_quantity > 0 and row.quantity <= row.min_quantity


# ---------- CA ----------

def ca_status(item: PPEItem, today: date | None = None, warn_days: int = 60) -> tuple[str, int | None]:
    """('sem_ca' | 'sem_validade' | 'vencido' | 'vence' | 'ok', dias até vencer)."""
    today = today or date.today()
    if item.category != "epi":
        return "nao_se_aplica", None
    if not item.ca:
        return "sem_ca", None
    if not item.ca_valid_until:
        return "sem_validade", None
    days = (item.ca_valid_until - today).days
    if days < 0:
        return "vencido", days
    return ("vence" if days <= warn_days else "ok"), days


# ---------- Comprovante ----------

def next_number(db: Session, today: date | None = None) -> str:
    year = (today or date.today()).year
    prefix = f"EPI-{year}-"
    last = db.scalar(select(func.max(PPEReceipt.number)).where(PPEReceipt.number.like(f"{prefix}%")))
    n = int(last.rsplit("-", 1)[1]) + 1 if last else 1
    return f"{prefix}{n:04d}"


def _file_hash(path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return "arquivo-ausente"


def content_hash(receipt: PPEReceipt, files_dir) -> str:
    """Hash do que foi assinado: pessoa, itens, data, método, momento e arquivos (assinatura e foto)."""
    p = receipt.person
    doc = {
        "number": receipt.number, "person": {"id": p.id, "name": p.name, "cpf": p.cpf},
        "delivered_on": receipt.delivered_on.isoformat(), "method": receipt.method,
        "signed_at": receipt.signed_at.astimezone(timezone.utc).isoformat() if receipt.signed_at else None,
        "items": [{"item": d.item, "ca": d.ca, "size": d.size or "", "quantity": d.quantity or 1,
                   "reason": d.reason or "", "valid_until": d.valid_until.isoformat() if d.valid_until else None}
                  for d in sorted(receipt.deliveries, key=lambda d: d.id)],
        "signature": _file_hash(files_dir / receipt.signature_file) if receipt.signature_file else None,
        "photo": _file_hash(files_dir / receipt.photo_file) if receipt.photo_file else None,
        "identity_check": receipt.identity_check,
    }
    return hashlib.sha256(json.dumps(doc, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


# ---------- Em uso, vencimentos e plano de substituição ----------

def in_use(deliveries) -> list[PPEDelivery]:
    return [d for d in deliveries if d.replaced_on is None]


def requirements(sector: Sector | None) -> list[tuple[str, str]]:
    """(código, nome) do que o setor exige: EPI verificado pela câmera + EPI só com controle de entrega."""
    if sector is None:
        return []
    out = [(code, PPE_LABELS.get(code, code).capitalize()) for code in (sector.required_ppe or [])]
    out += [("", name) for name in (sector.delivery_ppe or [])]
    return out


def matches(req: tuple[str, str], name: str, ppe_type: str = "") -> bool:
    code, label = req
    if code and ppe_type == code:
        return True
    a, b = norm(label), norm(name)
    return bool(a) and (a in b or b in a)


def replacement_plan(db: Session, unit_id: int | None, sector_id: int | None, days: int = 30,
                     today: date | None = None) -> dict:
    today = today or date.today()
    limit = today + timedelta(days=days)
    q = select(Person).where(Person.status == "ativo")
    if unit_id:
        q = q.where(Person.unit_id == unit_id)
    if sector_id:
        q = q.where(Person.sector_id == sector_id)
    people = db.scalars(q.order_by(Person.name)).all()
    items = db.scalars(select(PPEItem).where(PPEItem.active.is_(True))).all()
    by_id = {i.id: i for i in items}

    sectors: dict[int | None, dict] = {}
    needs: dict[tuple, dict] = {}

    def need(unit: int, item: PPEItem | None, name: str, size: str):
        key = (unit, item.id if item else name, size or "")
        n = needs.setdefault(key, {"unit_id": unit, "item_id": item.id if item else None,
                                   "item": item.name if item else name, "size": size or "", "quantity": 0})
        n["quantity"] += 1

    for p in people:
        sec = sectors.setdefault(p.sector_id, {"sector_id": p.sector_id, "sector": p.sector.name if p.sector else "Sem setor",
                                              "unit": p.unit.name if p.unit else "", "people": [],
                                              "due": 0, "overdue": 0, "missing": 0})
        using = in_use(p.deliveries)
        due, missing = [], []
        for d in using:
            if d.valid_until and d.valid_until <= limit:
                overdue = d.valid_until < today
                due.append({"delivery_id": d.id, "item_id": d.item_id, "item": d.item, "size": d.size or "",
                            "category": d.category or "epi", "valid_until": d.valid_until,
                            "days": (d.valid_until - today).days, "overdue": overdue})
                sec["overdue" if overdue else "due"] += 1
                need(p.unit_id, by_id.get(d.item_id), d.item, d.size or "")
        for req in requirements(p.sector):
            have = any(matches(req, d.item, by_id[d.item_id].ppe_type if d.item_id in by_id else "") for d in using)
            if not have:
                candidate = next((i for i in items if i.category == "epi" and matches(req, i.name, i.ppe_type)), None)
                missing.append({"requirement": req[1], "item_id": candidate.id if candidate else None,
                                "item": candidate.name if candidate else None})
                sec["missing"] += 1
                need(p.unit_id, candidate, req[1], "")
        if due or missing:
            sec["people"].append({"id": p.id, "name": p.name, "role": p.role, "shift": p.shift,
                                  "sizes": p.sizes or {}, "due": sorted(due, key=lambda x: x["valid_until"]),
                                  "missing": missing})

    stock = {}
    if needs:
        for row in db.scalars(select(PPEStock)).all():
            stock[(row.unit_id, row.item_id, row.size)] = row.quantity
    need_list = []
    for (unit, _, size), n in needs.items():
        if n["item_id"]:
            available = stock.get((unit, n["item_id"], size), 0) if size else sum(
                q for (u, i, _s), q in stock.items() if u == unit and i == n["item_id"])
        else:
            available = 0
        need_list.append({**n, "stock": available, "shortage": max(0, n["quantity"] - available)})
    return {"days": days, "until": limit,
            "sectors": sorted((s for s in sectors.values() if s["people"]), key=lambda s: s["sector"]),
            "needs": sorted(need_list, key=lambda n: (-n["shortage"], n["item"]))}
