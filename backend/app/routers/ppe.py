"""Guia EPI: catálogo (com CA), estoque por unidade com mínimo, entregas de EPI e uniforme com ficha assinada,
vencimentos de CA, plano de substituição por setor e relatórios (CSV)."""

from __future__ import annotations

import base64
import csv
import io
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import audit, ppe
from ..auth import require_role
from ..common import get_or_404
from ..database import get_db
from ..models import (DELIVERY_REASONS, MOVE_TYPES, SIGN_METHODS, Person, PPEDelivery, PPEItem, PPEMovement,
                      PPEReceipt, PPEStock, Unit, User)
from ..people import format_cpf, mask_cpf, only_digits, people_dir
from ..timeutil import to_local

router = APIRouter(prefix="/api/ppe")
viewer = require_role("tecnico")
editor = require_role("tecnico")  # SESMT / almoxarifado

FILES = "epi"  # subpasta (em people_dir) de assinaturas e fotos das entregas


def files_dir():
    return people_dir()


# ---------- Esquemas ----------

class ItemIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    category: Literal["epi", "uniforme"] = "epi"
    ppe_type: str = Field("", max_length=30)
    ca: str = Field("", max_length=20)
    ca_valid_until: date | None = None
    manufacturer: str = Field("", max_length=120)
    sizes: list[str] = []
    replacement_days: int | None = Field(None, ge=1, le=3650)
    unit_label: str = Field("un", max_length=10)
    unit_cost: float | None = Field(None, ge=0)
    active: bool = True

    @field_validator("sizes")
    @classmethod
    def clean_sizes(cls, items: list[str]) -> list[str]:
        out = []
        for s in items:
            s = s.strip().upper()[:20]
            if s and s not in out:
                out.append(s)
        return out[:30]

    @field_validator("ca")
    @classmethod
    def clean_ca(cls, v: str) -> str:
        return only_digits(v) or v.strip()


class MoveIn(BaseModel):
    unit_id: int
    item_id: int
    size: str = Field("", max_length=20)
    type: Literal["entrada", "ajuste", "devolucao"]
    quantity: int = Field(ge=0, le=100000)  # entrada/devolução: quantidade; ajuste: saldo contado
    note: str = Field("", max_length=300)


class MinIn(BaseModel):
    unit_id: int
    item_id: int
    size: str = Field("", max_length=20)
    min_quantity: int = Field(ge=0, le=100000)
    location: str = Field("", max_length=80)


class LineIn(BaseModel):
    item_id: int
    size: str = Field("", max_length=20)
    quantity: int = Field(1, ge=1, le=100)
    reason: Literal["primeira", "troca", "desgaste", "perda", "tamanho", "outro"] = "primeira"
    valid_until: date | None = None
    from_stock: bool = True


class ReceiptIn(BaseModel):
    person_id: int
    delivered_on: date
    items: list[LineIn] = Field(min_length=1, max_length=30)
    notes: str = Field("", max_length=500)


class SignIn(BaseModel):
    method: Literal["tela", "impressa"]
    signature: str | None = None  # data URL PNG (assinatura na tela)
    photo: str | None = None  # data URL JPEG (foto do momento da entrega, opcional)
    cpf_check: str = Field("", max_length=14)  # 3 primeiros dígitos do CPF, digitados pelo colaborador
    aware: bool = False  # declarou ter recebido, sido orientado e estar ciente das obrigações


class SizesIn(BaseModel):
    sizes: dict[str, str] = {}

    @field_validator("sizes")
    @classmethod
    def clean(cls, v: dict[str, str]) -> dict[str, str]:
        return {k.strip()[:20]: str(s).strip().upper()[:10] for k, s in list(v.items())[:12] if k.strip() and str(s).strip()}


# ---------- Saída ----------

def item_out(i: PPEItem) -> dict:
    status, days = ppe.ca_status(i)
    return {"id": i.id, "name": i.name, "category": i.category, "ppe_type": i.ppe_type, "ca": i.ca,
            "ca_valid_until": i.ca_valid_until, "ca_status": status, "ca_days": days, "manufacturer": i.manufacturer,
            "sizes": i.sizes or [], "replacement_days": i.replacement_days, "unit_label": i.unit_label,
            "unit_cost": i.unit_cost, "active": i.active}


def delivery_out(d: PPEDelivery) -> dict:
    today = date.today()
    return {"id": d.id, "person_id": d.person_id, "item_id": d.item_id, "item": d.item, "ca": d.ca,
            "category": d.category or "epi", "size": d.size or "", "quantity": d.quantity or 1,
            "reason": d.reason or "", "reason_label": DELIVERY_REASONS.get(d.reason or "", ""),
            "delivered_on": d.delivered_on, "valid_until": d.valid_until, "replaced_on": d.replaced_on,
            "overdue": bool(d.valid_until and d.valid_until < today and not d.replaced_on),
            "receipt_id": d.receipt_id, "receipt_number": d.receipt.number if d.receipt else None,
            "signed": bool(d.receipt and d.receipt.signed_at)}


def receipt_out(r: PPEReceipt, verify: bool = False) -> dict:
    p = r.person
    out = {"id": r.id, "number": r.number, "person_id": r.person_id, "person": p.name if p else None,
           "registration": p.registration if p else None, "role": p.role if p else "",
           "sector": p.sector.name if p and p.sector else None, "unit_id": r.unit_id,
           "delivered_on": r.delivered_on, "method": r.method, "method_label": SIGN_METHODS.get(r.method, "pendente"),
           "signed": r.signed_at is not None, "signed_at": r.signed_at, "identity_check": r.identity_check,
           "has_signature": bool(r.signature_file), "has_photo": bool(r.photo_file), "content_hash": r.content_hash,
           "ip": r.ip, "notes": r.notes, "created_by": r.created_by.name if r.created_by else None,
           "created_at": r.created_at, "items": [delivery_out(d) for d in r.deliveries]}
    if verify and r.signed_at:
        out["intact"] = ppe.content_hash(r, files_dir()) == r.content_hash
    return out


def stock_out(row: PPEStock) -> dict:
    return {"id": row.id, "unit_id": row.unit_id, "unit": row.unit.name if row.unit else "", "item_id": row.item_id,
            "item": row.item.name, "category": row.item.category, "size": row.size, "quantity": row.quantity,
            "min_quantity": row.min_quantity, "location": row.location, "low": ppe.is_low(row),
            "unit_label": row.item.unit_label, "ca_status": ppe.ca_status(row.item)[0]}


def _units(db: Session, unit_id: int | None) -> list[Unit]:
    q = select(Unit).where(Unit.active.is_(True)).order_by(Unit.name)
    if unit_id:
        q = q.where(Unit.id == unit_id)
    return db.scalars(q).all()


# ---------- Catálogo ----------

@router.get("/items", dependencies=[Depends(viewer)])
def list_items(category: str | None = None, all: bool = False, db: Session = Depends(get_db)):
    q = select(PPEItem).order_by(PPEItem.category, PPEItem.name)
    if category:
        q = q.where(PPEItem.category == category)
    if not all:
        q = q.where(PPEItem.active.is_(True))
    return [item_out(i) for i in db.scalars(q)]


@router.post("/items", status_code=201)
def create_item(data: ItemIn, request: Request, user: User = Depends(editor), db: Session = Depends(get_db)):
    item = PPEItem(**data.model_dump())
    db.add(item)
    db.flush()
    audit.record(db, user, "epi_catalogo_incluido", "epi", item.id, f"{item.name} (CA {item.ca or '-'})", request)
    db.commit()
    return item_out(item)


@router.put("/items/{item_id}")
def update_item(item_id: int, data: ItemIn, request: Request, user: User = Depends(editor), db: Session = Depends(get_db)):
    item = get_or_404(db, PPEItem, item_id)
    changed = [k for k, v in data.model_dump().items() if getattr(item, k) != v]
    for k, v in data.model_dump().items():
        setattr(item, k, v)
    if changed:
        audit.record(db, user, "epi_catalogo_alterado", "epi", item.id, f"{item.name}: {', '.join(changed)}", request)
    db.commit()
    return item_out(item)


@router.delete("/items/{item_id}", status_code=204)
def delete_item(item_id: int, request: Request, user: User = Depends(editor), db: Session = Depends(get_db)):
    item = get_or_404(db, PPEItem, item_id)
    used = db.scalar(select(PPEDelivery.id).where(PPEDelivery.item_id == item_id).limit(1)) or \
        db.scalar(select(PPEMovement.id).where(PPEMovement.item_id == item_id).limit(1))
    if used:  # histórico de entregas é registro legal: só desativa
        item.active = False
        audit.record(db, user, "epi_catalogo_desativado", "epi", item.id, item.name, request)
    else:
        audit.record(db, user, "epi_catalogo_excluido", "epi", item.id, item.name, request)
        db.delete(item)
    db.commit()


# ---------- Estoque ----------

@router.get("/stock", dependencies=[Depends(viewer)])
def list_stock(unit_id: int | None = None, category: str | None = None, db: Session = Depends(get_db)):
    """Saldo por unidade × item × tamanho. Itens ativos sem saldo lançado aparecem com 0 (para definir o mínimo)."""
    items = db.scalars(select(PPEItem).where(PPEItem.active.is_(True)).order_by(PPEItem.category, PPEItem.name)).all()
    if category:
        items = [i for i in items if i.category == category]
    units = _units(db, unit_id)
    rows = {(r.unit_id, r.item_id, r.size): r for r in db.scalars(select(PPEStock))}
    out = []
    for u in units:
        for i in items:
            sizes = list(i.sizes or []) or [""]
            extra = [s for (uid, iid, s) in rows if uid == u.id and iid == i.id and s not in sizes]
            for size in sizes + extra:
                r = rows.get((u.id, i.id, size))
                if r is not None:
                    out.append(stock_out(r))
                else:
                    out.append({"id": None, "unit_id": u.id, "unit": u.name, "item_id": i.id, "item": i.name,
                                "category": i.category, "size": size, "quantity": 0, "min_quantity": 0, "location": "",
                                "low": False, "unit_label": i.unit_label, "ca_status": ppe.ca_status(i)[0]})
    return {"rows": out, "low": sum(1 for r in out if r["low"]),
            "zero": sum(1 for r in out if r["quantity"] <= 0 and r["min_quantity"] > 0)}


@router.post("/stock/move")
def stock_move(data: MoveIn, request: Request, user: User = Depends(editor), db: Session = Depends(get_db)):
    get_or_404(db, Unit, data.unit_id)
    item = get_or_404(db, PPEItem, data.item_id)
    size = data.size.strip().upper()
    if data.type == "ajuste":
        current = ppe.stock_row(db, data.unit_id, item.id, size)
        delta = data.quantity - current.quantity
    else:
        if data.quantity <= 0:
            raise HTTPException(422, "informe a quantidade")
        delta = data.quantity
    try:
        row = ppe.move(db, unit_id=data.unit_id, item_id=item.id, size=size, type_=data.type, quantity=delta,
                       note=data.note, user_name=user.name)
    except ppe.StockError as exc:
        raise HTTPException(409, str(exc)) from exc
    audit.record(db, user, f"epi_estoque_{data.type}", "epi", item.id,
                 f"{item.name}{f' {size}' if size else ''}: {delta:+d} → saldo {row.quantity}"
                 f"{f' ({data.note})' if data.note else ''}", request)
    db.commit()
    return stock_out(row)


@router.put("/stock/min")
def stock_min(data: MinIn, request: Request, user: User = Depends(editor), db: Session = Depends(get_db)):
    get_or_404(db, Unit, data.unit_id)
    item = get_or_404(db, PPEItem, data.item_id)
    row = ppe.stock_row(db, data.unit_id, item.id, data.size.strip().upper())
    row.min_quantity, row.location = data.min_quantity, data.location.strip()
    audit.record(db, user, "epi_estoque_minimo", "epi", item.id,
                 f"{item.name}{f' {row.size}' if row.size else ''}: mínimo {row.min_quantity}", request)
    db.commit()
    return stock_out(row)


@router.get("/movements", dependencies=[Depends(viewer)])
def list_movements(unit_id: int | None = None, item_id: int | None = None, start: date | None = None,
                   end: date | None = None, limit: int = 300, db: Session = Depends(get_db)):
    q = select(PPEMovement).order_by(PPEMovement.created_at.desc(), PPEMovement.id.desc()).limit(min(limit, 2000))
    if unit_id:
        q = q.where(PPEMovement.unit_id == unit_id)
    if item_id:
        q = q.where(PPEMovement.item_id == item_id)
    if start:
        q = q.where(PPEMovement.created_at >= datetime.combine(start, datetime.min.time(), timezone.utc))
    if end:
        q = q.where(PPEMovement.created_at < datetime.combine(end + timedelta(days=1), datetime.min.time(), timezone.utc))
    names = {u.id: u.name for u in db.scalars(select(Unit))}
    people = {}
    rows = db.scalars(q).all()
    ids = {m.person_id for m in rows if m.person_id}
    if ids:
        people = {p.id: p.name for p in db.scalars(select(Person).where(Person.id.in_(ids)))}
    return [{"id": m.id, "unit": names.get(m.unit_id, ""), "item": m.item.name if m.item else "", "size": m.size,
             "type": m.type, "type_label": MOVE_TYPES.get(m.type, m.type), "quantity": m.quantity, "balance": m.balance,
             "note": m.note, "person": people.get(m.person_id), "receipt_id": m.receipt_id, "user": m.user_name,
             "created_at": m.created_at} for m in rows]


# ---------- Entregas (comprovante) ----------

def receipt_query():
    return select(PPEReceipt).options(selectinload(PPEReceipt.person).selectinload(Person.sector),
                                      selectinload(PPEReceipt.deliveries).selectinload(PPEDelivery.receipt))


@router.post("/receipts", status_code=201)
def create_receipt(data: ReceiptIn, request: Request, user: User = Depends(editor), db: Session = Depends(get_db)):
    person = get_or_404(db, Person, data.person_id)
    if person.status == "desligado":
        raise HTTPException(400, "colaborador desligado")
    if data.delivered_on > date.today():
        raise HTTPException(422, "a data de entrega não pode ser futura")
    receipt = PPEReceipt(number=ppe.next_number(db, data.delivered_on), person_id=person.id, unit_id=person.unit_id,
                         delivered_on=data.delivered_on, notes=data.notes.strip(), created_by_id=user.id)
    db.add(receipt)
    db.flush()
    warnings, names = [], []
    for line in data.items:
        item = get_or_404(db, PPEItem, line.item_id)
        if not item.active:
            raise HTTPException(400, f"{item.name} está desativado no catálogo")
        size = line.size.strip().upper()
        if item.sizes and size not in item.sizes:
            raise HTTPException(422, f"escolha o tamanho de {item.name} ({', '.join(item.sizes)})")
        status, _ = ppe.ca_status(item, data.delivered_on)
        if status == "vencido":
            warnings.append(f"CA {item.ca} de {item.name} vencido em {item.ca_valid_until:%d/%m/%Y}: confira se o lote "
                            "foi fabricado dentro da validade do CA")
        elif status == "sem_ca":
            warnings.append(f"{item.name} sem CA no catálogo (NR-6 exige CA para EPI)")
        valid = line.valid_until or (data.delivered_on + timedelta(days=item.replacement_days)
                                     if item.replacement_days else None)
        if valid and valid < data.delivered_on:
            raise HTTPException(422, "a troca prevista é anterior à entrega")
        # a peça anterior do mesmo item deixa de contar nos vencimentos
        for old in person.deliveries:
            if old.item_id == item.id and old.replaced_on is None and old.delivered_on <= data.delivered_on:
                old.replaced_on = data.delivered_on
        db.add(PPEDelivery(person_id=person.id, item=item.name, ca=item.ca if item.category == "epi" else "",
                           delivered_on=data.delivered_on, valid_until=valid, item_id=item.id, category=item.category,
                           size=size, quantity=line.quantity, reason=line.reason, unit_id=person.unit_id,
                           receipt_id=receipt.id, from_stock=line.from_stock))
        if line.from_stock:
            try:
                row = ppe.move(db, unit_id=person.unit_id, item_id=item.id, size=size, type_="saida",
                               quantity=-line.quantity, note=receipt.number, user_name=user.name,
                               person_id=person.id, receipt_id=receipt.id)
            except ppe.StockError as exc:
                db.rollback()
                raise HTTPException(409, f"{exc}. Lance a entrada no Estoque ou desmarque \"baixar do estoque\".") from exc
            if ppe.is_low(row):
                warnings.append(f"estoque de {item.name}{f' {size}' if size else ''} no mínimo ou abaixo: "
                                f"{row.quantity} (mínimo {row.min_quantity})")
        names.append(f"{line.quantity}× {item.name}{f' {size}' if size else ''}")
    audit.record(db, user, "epi_entregue", "pessoa", person.id, f"{receipt.number}: {', '.join(names)}", request)
    db.commit()
    receipt = db.scalar(receipt_query().where(PPEReceipt.id == receipt.id))
    return {**receipt_out(receipt), "warnings": warnings}


def _save_image(data_url: str, prefixes: tuple[str, ...], magic: tuple[bytes, ...], name: str, limit: int) -> str:
    prefix = next((p for p in prefixes if data_url.startswith(p)), None)
    if prefix is None:
        raise HTTPException(422, "imagem inválida")
    try:
        raw = base64.b64decode(data_url[len(prefix):], validate=True)
    except ValueError as exc:
        raise HTTPException(422, "imagem inválida") from exc
    if not raw.startswith(magic) or len(raw) > limit:
        raise HTTPException(422, "imagem inválida ou grande demais")
    ext = ".png" if raw.startswith(b"\x89PNG") else ".jpg"
    (files_dir() / FILES).mkdir(parents=True, exist_ok=True)
    rel = f"{FILES}/{name}-{uuid.uuid4().hex[:10]}{ext}"
    (files_dir() / rel).write_bytes(raw)
    return rel


@router.post("/receipts/{receipt_id}/sign")
def sign_receipt(receipt_id: int, data: SignIn, request: Request, user: User = Depends(editor),
                 db: Session = Depends(get_db)):
    r = db.scalar(receipt_query().where(PPEReceipt.id == receipt_id))
    if r is None:
        raise HTTPException(404, "não encontrado")
    if r.signed_at:
        raise HTTPException(409, "comprovante já assinado – registre uma nova entrega para corrigir")
    if data.method == "tela":
        if not data.aware:
            raise HTTPException(422, "o colaborador precisa confirmar a declaração de recebimento")
        if not data.signature:
            raise HTTPException(422, "assinatura ausente")
        digits = only_digits(data.cpf_check)
        if len(digits) < 3 or not r.person.cpf.startswith(digits[:3]):
            raise HTTPException(422, "os dígitos do CPF não conferem com o cadastro do colaborador")
        r.signature_file = _save_image(data.signature, ("data:image/png;base64,",), (b"\x89PNG",), r.number, 1024 * 1024)
        r.identity_check = "CPF conferido (3 primeiros dígitos)"
    if data.photo:
        r.photo_file = _save_image(data.photo, ("data:image/jpeg;base64,", "data:image/png;base64,"),
                                   (b"\xff\xd8\xff", b"\x89PNG"), f"{r.number}-foto", 3 * 1024 * 1024)
    r.method = data.method
    r.signed_at = datetime.now(timezone.utc)
    r.ip = (request.client.host if request.client else "")[:64]
    r.user_agent = request.headers.get("user-agent", "")[:200]
    db.flush()
    r.content_hash = ppe.content_hash(r, files_dir())
    audit.record(db, user, "epi_ficha_assinada", "pessoa", r.person_id,
                 f"{r.number}: {SIGN_METHODS[data.method]} · hash {r.content_hash[:16]}", request)
    db.commit()
    return receipt_out(r, verify=True)


@router.delete("/receipts/{receipt_id}", status_code=204)
def cancel_receipt(receipt_id: int, request: Request, user: User = Depends(editor), db: Session = Depends(get_db)):
    """Estorno de entrega lançada por engano: só antes de assinar (depois é registro legal)."""
    r = db.scalar(receipt_query().where(PPEReceipt.id == receipt_id))
    if r is None:
        raise HTTPException(404, "não encontrado")
    if r.signed_at:
        raise HTTPException(409, "comprovante assinado não pode ser excluído")
    for d in list(r.deliveries):
        if d.from_stock and d.item_id:
            ppe.move(db, unit_id=d.unit_id or r.unit_id, item_id=d.item_id, size=d.size or "", type_="estorno",
                     quantity=d.quantity or 1, note=f"estorno {r.number}", user_name=user.name, person_id=r.person_id,
                     allow_negative=True)
        # a peça anterior volta a valer
        for old in r.person.deliveries:
            if old.item_id == d.item_id and old.id != d.id and old.replaced_on == d.delivered_on:
                old.replaced_on = None
        db.delete(d)
    audit.record(db, user, "epi_entrega_estornada", "pessoa", r.person_id, r.number, request)
    db.delete(r)
    db.commit()


@router.get("/receipts", dependencies=[Depends(viewer)])
def list_receipts(unit_id: int | None = None, person_id: int | None = None, start: date | None = None,
                  end: date | None = None, category: str | None = None, pending: bool = False,
                  db: Session = Depends(get_db)):
    q = receipt_query().order_by(PPEReceipt.delivered_on.desc(), PPEReceipt.id.desc()).limit(500)
    if unit_id:
        q = q.where(PPEReceipt.unit_id == unit_id)
    if person_id:
        q = q.where(PPEReceipt.person_id == person_id)
    if start:
        q = q.where(PPEReceipt.delivered_on >= start)
    if end:
        q = q.where(PPEReceipt.delivered_on <= end)
    if pending:
        q = q.where(PPEReceipt.signed_at.is_(None))
    out = [receipt_out(r) for r in db.scalars(q)]
    if category:
        out = [r for r in out if any(i["category"] == category for i in r["items"])]
    return out


@router.get("/receipts/{receipt_id}", dependencies=[Depends(viewer)])
def get_receipt(receipt_id: int, db: Session = Depends(get_db)):
    r = db.scalar(receipt_query().where(PPEReceipt.id == receipt_id))
    if r is None:
        raise HTTPException(404, "não encontrado")
    return receipt_out(r, verify=True)


@router.get("/receipts/{receipt_id}/{kind}", dependencies=[Depends(viewer)])
def receipt_file(receipt_id: int, kind: Literal["signature", "photo"], db: Session = Depends(get_db)):
    r = get_or_404(db, PPEReceipt, receipt_id)
    rel = r.signature_file if kind == "signature" else r.photo_file
    if not rel or not (files_dir() / rel).exists():
        raise HTTPException(404, "sem arquivo")
    return FileResponse(files_dir() / rel, media_type="image/png" if rel.endswith(".png") else "image/jpeg",
                        headers={"Cache-Control": "private, max-age=300"})


# ---------- Ficha de EPI e tamanhos ----------

@router.get("/fichas/{person_id}")
def ficha(person_id: int, request: Request, user: User = Depends(viewer), db: Session = Depends(get_db)):
    person = get_or_404(db, Person, person_id)
    receipts = db.scalars(receipt_query().where(PPEReceipt.person_id == person_id)
                          .order_by(PPEReceipt.delivered_on, PPEReceipt.id)).all()
    loose = [delivery_out(d) for d in sorted(person.deliveries, key=lambda d: (d.delivered_on, d.id)) if not d.receipt_id]
    audit.record(db, user, "epi_ficha_consultada", "pessoa", person.id, person.name, request)
    db.commit()
    return {"person": {"id": person.id, "name": person.name, "cpf": format_cpf(person.cpf), "cpf_masked": mask_cpf(person.cpf),
                       "registration": person.registration, "role": person.role, "shift": person.shift,
                       "sector": person.sector.name if person.sector else None, "unit": person.unit.name,
                       "company": person.company, "employment": person.employment, "status": person.status,
                       "sizes": person.sizes or {}, "has_photo": bool(person.photo_file)},
            "receipts": [receipt_out(r, verify=True) for r in receipts], "manual": loose,
            "requirements": [name for _, name in ppe.requirements(person.sector)]}


@router.put("/people/{person_id}/sizes")
def set_sizes(person_id: int, data: SizesIn, request: Request, user: User = Depends(editor), db: Session = Depends(get_db)):
    person = get_or_404(db, Person, person_id)
    person.sizes = data.sizes
    audit.record(db, user, "tamanhos_alterados", "pessoa", person.id,
                 ", ".join(f"{k} {v}" for k, v in data.sizes.items()) or "sem tamanhos", request)
    db.commit()
    return {"sizes": person.sizes}


# ---------- Uniformes ----------

@router.get("/uniforms", dependencies=[Depends(viewer)])
def uniforms(unit_id: int | None = None, sector_id: int | None = None, db: Session = Depends(get_db)):
    """Quem está com quais peças de uniforme, tamanhos e próxima troca."""
    q = select(Person).where(Person.status == "ativo").order_by(Person.name)
    if unit_id:
        q = q.where(Person.unit_id == unit_id)
    if sector_id:
        q = q.where(Person.sector_id == sector_id)
    today = date.today()
    out = []
    for p in db.scalars(q):
        pieces = [d for d in ppe.in_use(p.deliveries) if (d.category or "epi") == "uniforme"]
        nxt = min((d.valid_until for d in pieces if d.valid_until), default=None)
        out.append({"id": p.id, "name": p.name, "sector": p.sector.name if p.sector else None, "role": p.role,
                    "shift": p.shift, "sizes": p.sizes or {}, "pieces": [delivery_out(d) for d in pieces],
                    "total": sum(d.quantity or 1 for d in pieces), "next_change": nxt,
                    "overdue": bool(nxt and nxt < today)})
    return out


# ---------- Relatórios ----------

@router.get("/ca-report", dependencies=[Depends(viewer)])
def ca_report(days: int = 60, unit_id: int | None = None, db: Session = Depends(get_db)):
    """Vencimentos de CA: EPIs do catálogo com CA vencido, vencendo, sem validade ou sem CA."""
    today = date.today()
    items = db.scalars(select(PPEItem).where(PPEItem.active.is_(True), PPEItem.category == "epi")
                       .order_by(PPEItem.ca_valid_until.is_(None), PPEItem.ca_valid_until, PPEItem.name)).all()
    stock_q = select(PPEStock)
    if unit_id:
        stock_q = stock_q.where(PPEStock.unit_id == unit_id)
    stock: dict[int, int] = {}
    for row in db.scalars(stock_q):
        stock[row.item_id] = stock.get(row.item_id, 0) + row.quantity
    use_q = select(PPEDelivery).where(PPEDelivery.replaced_on.is_(None), PPEDelivery.item_id.is_not(None))
    if unit_id:
        use_q = use_q.join(Person, Person.id == PPEDelivery.person_id).where(Person.unit_id == unit_id)
    using: dict[int, int] = {}
    for d in db.scalars(use_q):
        using[d.item_id] = using.get(d.item_id, 0) + (d.quantity or 1)
    rows = []
    for i in items:
        status, left = ppe.ca_status(i, today, days)
        rows.append({**item_out(i), "ca_status": status, "ca_days": left, "stock": stock.get(i.id, 0),
                     "in_use": using.get(i.id, 0)})
    order = {"vencido": 0, "vence": 1, "sem_ca": 2, "sem_validade": 3, "ok": 4}
    rows.sort(key=lambda r: (order.get(r["ca_status"], 5), r["ca_valid_until"] or date.max))
    counts = {k: sum(1 for r in rows if r["ca_status"] == k) for k in order}
    return {"days": days, "rows": rows, "counts": counts}


@router.get("/replacement-plan", dependencies=[Depends(viewer)])
def replacement_plan(unit_id: int | None = None, sector_id: int | None = None, days: int = 30,
                     db: Session = Depends(get_db)):
    plan = ppe.replacement_plan(db, unit_id, sector_id, max(0, min(days, 365)))
    names = {u.id: u.name for u in db.scalars(select(Unit))}
    for n in plan["needs"]:
        n["unit"] = names.get(n["unit_id"], "")
    return plan


@router.get("/summary", dependencies=[Depends(viewer)])
def summary(unit_id: int | None = None, db: Session = Depends(get_db)):
    stock = list_stock(unit_id=unit_id, db=db)
    ca = ca_report(days=60, unit_id=unit_id, db=db)["counts"]
    plan = ppe.replacement_plan(db, unit_id, None, 30)
    pending = select(PPEReceipt.id).where(PPEReceipt.signed_at.is_(None))
    if unit_id:
        pending = pending.where(PPEReceipt.unit_id == unit_id)
    return {"stock_low": stock["low"], "stock_zero": stock["zero"], "ca_expired": ca["vencido"], "ca_expiring": ca["vence"],
            "ca_missing": ca["sem_ca"], "replacements_due": sum(s["due"] for s in plan["sectors"]),
            "replacements_overdue": sum(s["overdue"] for s in plan["sectors"]),
            "missing": sum(s["missing"] for s in plan["sectors"]),
            "unsigned": len(db.scalars(pending).all())}


def _csv(name: str, header: list[str], rows: list[list]) -> Response:
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";")
    writer.writerow(header)
    writer.writerows(rows)
    return Response(out.getvalue().encode("utf-8-sig"), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/deliveries.csv", dependencies=[Depends(viewer)])
def deliveries_csv(start: date | None = None, end: date | None = None, unit_id: int | None = None,
                   category: str | None = None, db: Session = Depends(get_db)):
    end = end or date.today()
    start = start or end.replace(day=1)
    q = select(PPEDelivery).options(selectinload(PPEDelivery.receipt)).where(
        PPEDelivery.delivered_on >= start, PPEDelivery.delivered_on <= end).order_by(PPEDelivery.delivered_on, PPEDelivery.id)
    if category:
        q = q.where(PPEDelivery.category == category)
    rows = db.scalars(q).all()
    people = {p.id: p for p in db.scalars(select(Person).where(Person.id.in_({d.person_id for d in rows})))} if rows else {}
    data = []
    for d in rows:
        p = people.get(d.person_id)
        if unit_id and p and p.unit_id != unit_id:
            continue
        r = d.receipt
        data.append([f"{d.delivered_on:%d/%m/%Y}", r.number if r else "", p.name if p else "", p.registration if p else "",
                     p.sector.name if p and p.sector else "", "Uniforme" if d.category == "uniforme" else "EPI", d.item,
                     d.ca, d.size or "", d.quantity or 1, DELIVERY_REASONS.get(d.reason or "", ""),
                     f"{d.valid_until:%d/%m/%Y}" if d.valid_until else "",
                     SIGN_METHODS.get(r.method, "pendente") if r and r.signed_at else ("pendente" if r else "registro manual"),
                     f"{to_local(r.signed_at):%d/%m/%Y %H:%M}" if r and r.signed_at else ""])
    return _csv(f"entregas-epi-{start:%Y%m%d}-{end:%Y%m%d}.csv",
                ["Data", "Comprovante", "Colaborador", "Matrícula", "Setor", "Tipo", "Item", "CA", "Tamanho", "Qtd.",
                 "Motivo", "Troca prevista", "Assinatura", "Assinado em"], data)


@router.get("/stock.csv", dependencies=[Depends(viewer)])
def stock_csv(unit_id: int | None = None, db: Session = Depends(get_db)):
    rows = list_stock(unit_id=unit_id, db=db)["rows"]
    return _csv(f"estoque-epi-{date.today():%Y%m%d}.csv",
                ["Unidade", "Tipo", "Item", "Tamanho", "Saldo", "Mínimo", "Situação", "Local"],
                [[r["unit"], "Uniforme" if r["category"] == "uniforme" else "EPI", r["item"], r["size"], r["quantity"],
                  r["min_quantity"], "ABAIXO DO MÍNIMO" if r["low"] else "ok", r["location"]] for r in rows])
