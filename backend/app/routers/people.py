"""Cadastro de pessoas (colaboradores e terceiros), fotos de identificação, EPIs e treinamentos."""

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from .. import audit
from ..auth import has_role, require_role
from ..common import get_or_404
from ..database import get_db
from ..models import Person, PPEDelivery, Sector, TrainingRecord, Unit, User
from ..people import (EMPLOYMENT_ALIASES, TEMPLATE_CSV, delete_photo, format_cpf, mask_cpf, only_digits, parse_csv,
                      people_dir, save_photo, valid_cpf)
from ..schemas import DeliveryIn, DeliveryOut, PersonDetail, PersonIn, PersonOut, TrainingIn, TrainingOut
from ..sectors import PPE_LABELS

router = APIRouter(prefix="/api/people")
viewer = require_role("tecnico")   # SESMT consulta
editor = require_role("gestor")    # RH/gestão edita


def ppe_alert(person: Person, today: date | None = None) -> str | None:
    today = today or date.today()
    soon = [d for d in person.deliveries if d.valid_until and d.valid_until <= today + timedelta(days=30)]
    if not soon:
        return None
    first = min(soon, key=lambda d: d.valid_until)
    days = (first.valid_until - today).days
    return f"{first.item} vencido" if days < 0 else f"{first.item} vence em {days} dia(s)"


def person_out(person: Person, full_cpf: bool = False) -> dict:
    return PersonOut(
        id=person.id, unit_id=person.unit_id, unit=person.unit.name, sector_id=person.sector_id,
        sector=person.sector.name if person.sector else None, name=person.name,
        cpf=format_cpf(person.cpf) if full_cpf else mask_cpf(person.cpf), registration=person.registration,
        role=person.role, shift=person.shift, employment=person.employment, company=person.company,
        manager=person.manager, badge_code=person.badge_code, has_photo=bool(person.photo_file),
        photo_consent=person.photo_consent, photo_consent_on=person.photo_consent_on, status=person.status,
        ppe_alert=ppe_alert(person), open_trainings=sum(1 for t in person.trainings if t.status == "agendado"),
    ).model_dump()


def person_query():
    return select(Person).options(selectinload(Person.unit), selectinload(Person.sector),
                                  selectinload(Person.deliveries), selectinload(Person.trainings))


@router.get("")
def list_people(q: str = "", unit_id: int | None = None, sector_id: int | None = None, status: str = "ativo,afastado",
                limit: int = Query(50, le=500), offset: int = 0, _: User = Depends(viewer), db: Session = Depends(get_db)):
    query = person_query()
    if q.strip():
        term = q.strip()
        digits = only_digits(term)
        conds = [Person.name.ilike(f"%{term}%"), Person.registration.ilike(f"%{term}%"), Person.badge_code == term.upper()]
        if len(digits) >= 3:
            conds.append(Person.cpf.contains(digits))
        query = query.where(or_(*conds))
    if unit_id is not None:
        query = query.where(Person.unit_id == unit_id)
    if sector_id is not None:
        query = query.where(Person.sector_id == sector_id)
    if status:
        query = query.where(Person.status.in_(status.split(",")))
    total = db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
    people = db.scalars(query.order_by(Person.name).limit(limit).offset(offset)).all()
    return {"total": total, "items": [person_out(p) for p in people]}


@router.get("/summary", dependencies=[Depends(viewer)])
def people_summary(unit_id: int | None = None, db: Session = Depends(get_db)):
    query = person_query().where(Person.status != "desligado")
    if unit_id is not None:
        query = query.where(Person.unit_id == unit_id)
    people = db.scalars(query).all()
    by_sector: dict[str, int] = {}
    for p in people:
        key = p.sector.name if p.sector else "Sem setor"
        by_sector[key] = by_sector.get(key, 0) + 1
    today = date.today()
    return {
        "active": sum(1 for p in people if p.status == "ativo"),
        "third_party": sum(1 for p in people if p.employment == "terceiro"),
        "by_sector": sorted(({"sector": k, "count": v} for k, v in by_sector.items()), key=lambda x: -x["count"]),
        "ppe_expiring": sum(1 for p in people for d in p.deliveries
                            if d.valid_until and today <= d.valid_until <= today + timedelta(days=30)),
        "ppe_expired": sum(1 for p in people for d in p.deliveries if d.valid_until and d.valid_until < today),
        "without_photo": sum(1 for p in people if not p.photo_file),
        "trainings_scheduled": sum(1 for p in people for t in p.trainings if t.status == "agendado"),
    }


@router.get("/import/template")
def import_template(_: User = Depends(editor)):
    return Response(TEMPLATE_CSV.encode("utf-8-sig"), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="modelo-pessoas-vigia.csv"'})


def _check_unique(db: Session, data: PersonIn, cpf: str, person_id: int | None) -> None:
    def taken(column, value):
        return value and db.scalar(select(Person.id).where(column == value, Person.id != (person_id or 0)))
    if taken(Person.cpf, cpf):
        raise HTTPException(409, "já existe uma pessoa cadastrada com este CPF")
    if taken(Person.registration, data.registration):
        raise HTTPException(409, "já existe uma pessoa com esta matrícula")
    if taken(Person.badge_code, data.badge_code):
        raise HTTPException(409, "este número de colete/crachá já está em uso")


def _apply(db: Session, person: Person, data: PersonIn) -> list[str]:
    cpf = only_digits(data.cpf)
    if not valid_cpf(cpf):
        raise HTTPException(422, "CPF inválido")
    get_or_404(db, Unit, data.unit_id)
    if data.sector_id is not None:
        sector = get_or_404(db, Sector, data.sector_id)
        if sector.unit_id != data.unit_id:
            raise HTTPException(422, "o setor escolhido é de outra unidade")
    _check_unique(db, data, cpf, person.id)
    values = {**data.model_dump(), "cpf": cpf, "name": " ".join(data.name.split())}
    changed = [k for k, v in values.items() if getattr(person, k, None) != v]
    if values["photo_consent"] and not person.photo_consent:
        person.photo_consent_on = date.today()
    for key, value in values.items():
        setattr(person, key, value)
    person.updated_at = datetime.now(timezone.utc)
    if person.status == "desligado" and person.photo_file:
        # a foto só serve para identificar quem está trabalhando (LGPD: minimização)
        delete_photo(person.photo_file)
        person.photo_file = None
        changed.append("foto apagada no desligamento")
    return changed


@router.get("/{person_id}", response_model=PersonDetail)
def get_person(person_id: int, request: Request, user: User = Depends(viewer), db: Session = Depends(get_db)):
    person = db.scalar(person_query().where(Person.id == person_id))
    if person is None:
        raise HTTPException(404, "não encontrado")
    full = has_role(user, "gestor")
    if full:
        audit.record(db, user, "pessoa_consultada", "pessoa", person.id, person.name, request)
        db.commit()
    return {**person_out(person, full_cpf=full),
            "deliveries": [DeliveryOut.model_validate(d) for d in person.deliveries],
            "trainings": [TrainingOut.model_validate(t) for t in person.trainings],
            "required_ppe": [PPE_LABELS.get(p, p) for p in (person.sector.required_ppe if person.sector else [])],
            "delivery_ppe": list(person.sector.delivery_ppe) if person.sector else []}


@router.post("", status_code=201)
def create_person(data: PersonIn, request: Request, user: User = Depends(editor), db: Session = Depends(get_db)):
    person = Person()
    _apply(db, person, data)
    db.add(person)
    db.flush()
    audit.record(db, user, "pessoa_cadastrada", "pessoa", person.id, person.name, request)
    db.commit()
    return person_out(db.scalar(person_query().where(Person.id == person.id)), full_cpf=True)


@router.put("/{person_id}")
def update_person(person_id: int, data: PersonIn, request: Request, user: User = Depends(editor),
                  db: Session = Depends(get_db)):
    person = get_or_404(db, Person, person_id)
    changed = _apply(db, person, data)
    if changed:
        shown = ["CPF" if c == "cpf" else c for c in changed]
        audit.record(db, user, "pessoa_alterada", "pessoa", person.id, f"{person.name}: {', '.join(shown)}", request)
    db.commit()
    return person_out(db.scalar(person_query().where(Person.id == person.id)), full_cpf=True)


# ---------- Foto ----------

@router.post("/{person_id}/photo")
async def upload_photo(person_id: int, request: Request, photo: UploadFile = File(...), user: User = Depends(editor),
                       db: Session = Depends(get_db)):
    person = get_or_404(db, Person, person_id)
    if not person.photo_consent:
        raise HTTPException(400, "registre a ciência do colaborador sobre o uso da foto antes de enviá-la")
    try:
        name = save_photo(person.id, await photo.read())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    delete_photo(person.photo_file)
    person.photo_file = name
    audit.record(db, user, "foto_atualizada", "pessoa", person.id, person.name, request)
    db.commit()
    return {"has_photo": True}


@router.get("/{person_id}/photo", dependencies=[Depends(viewer)])
def get_photo(person_id: int, db: Session = Depends(get_db)):
    person = get_or_404(db, Person, person_id)
    if not person.photo_file or not (people_dir() / person.photo_file).exists():
        raise HTTPException(404, "sem foto")
    media = "image/png" if person.photo_file.endswith(".png") else "image/jpeg"
    return FileResponse(people_dir() / person.photo_file, media_type=media, headers={"Cache-Control": "private, max-age=300"})


@router.delete("/{person_id}/photo", status_code=204)
def remove_photo(person_id: int, request: Request, user: User = Depends(editor), db: Session = Depends(get_db)):
    person = get_or_404(db, Person, person_id)
    delete_photo(person.photo_file)
    person.photo_file = None
    audit.record(db, user, "foto_removida", "pessoa", person.id, person.name, request)
    db.commit()


# ---------- EPIs entregues e treinamentos ----------

@router.post("/{person_id}/deliveries", response_model=DeliveryOut, status_code=201)
def add_delivery(person_id: int, data: DeliveryIn, request: Request, user: User = Depends(viewer),
                 db: Session = Depends(get_db)):
    person = get_or_404(db, Person, person_id)
    if data.valid_until and data.valid_until < data.delivered_on:
        raise HTTPException(422, "a validade é anterior à entrega")
    delivery = PPEDelivery(person_id=person.id, **data.model_dump())
    db.add(delivery)
    db.flush()
    audit.record(db, user, "epi_entregue", "pessoa", person.id, f"{data.item} (CA {data.ca or '-'})", request)
    db.commit()
    return delivery


@router.delete("/{person_id}/deliveries/{delivery_id}", status_code=204)
def delete_delivery(person_id: int, delivery_id: int, request: Request, user: User = Depends(viewer),
                    db: Session = Depends(get_db)):
    delivery = get_or_404(db, PPEDelivery, delivery_id)
    if delivery.person_id != person_id:
        raise HTTPException(404, "não encontrado")
    audit.record(db, user, "epi_entrega_excluida", "pessoa", person_id, delivery.item, request)
    db.delete(delivery)
    db.commit()


@router.post("/{person_id}/trainings", response_model=TrainingOut, status_code=201)
def add_training(person_id: int, data: TrainingIn, request: Request, user: User = Depends(viewer),
                 db: Session = Depends(get_db)):
    get_or_404(db, Person, person_id)
    training = TrainingRecord(person_id=person_id, **data.model_dump())
    db.add(training)
    db.flush()
    audit.record(db, user, "treinamento_registrado", "pessoa", person_id, f"{data.name} ({data.status})", request)
    db.commit()
    return training


@router.patch("/{person_id}/trainings/{training_id}", response_model=TrainingOut)
def update_training(person_id: int, training_id: int, data: TrainingIn, request: Request, user: User = Depends(viewer),
                    db: Session = Depends(get_db)):
    training = get_or_404(db, TrainingRecord, training_id)
    if training.person_id != person_id:
        raise HTTPException(404, "não encontrado")
    for key, value in data.model_dump().items():
        setattr(training, key, value)
    audit.record(db, user, "treinamento_atualizado", "pessoa", person_id, f"{data.name}: {data.status}", request)
    db.commit()
    return training


# ---------- Importação ----------

@router.post("/import")
async def import_people(request: Request, file: UploadFile = File(...), user: User = Depends(editor),
                        db: Session = Depends(get_db)):
    """Cria ou atualiza pessoas a partir de CSV (chave: CPF). Linhas com erro são ignoradas e listadas."""
    try:
        rows = parse_csv(await file.read())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    units = {u.name.lower(): u for u in db.scalars(select(Unit))}
    default_unit = next(iter(units.values()), None)
    sectors = {(s.unit_id, s.name.lower()): s for s in db.scalars(select(Sector))}
    created = updated = 0
    errors = []
    for row in rows:
        line = row.pop("_line")
        try:
            unit = units.get(row.get("unit", "").lower()) if row.get("unit") else default_unit
            if unit is None:
                raise ValueError(f"unidade '{row.get('unit')}' não cadastrada")
            sector = None
            if row.get("sector"):
                sector = sectors.get((unit.id, row["sector"].lower()))
                if sector is None:
                    raise ValueError(f"setor '{row['sector']}' não existe na unidade {unit.name}")
            employment = EMPLOYMENT_ALIASES.get((row.get("employment") or "clt").lower())
            if employment is None:
                raise ValueError(f"vínculo '{row.get('employment')}' inválido")
            cpf = only_digits(row.get("cpf", ""))
            person = db.scalar(select(Person).where(Person.cpf == cpf)) or Person()
            is_new = person.id is None
            data = PersonIn(unit_id=unit.id, sector_id=sector.id if sector else None, name=row.get("name", ""),
                            cpf=row.get("cpf", ""), registration=row.get("registration") or None,
                            role=row.get("role", ""), shift=row.get("shift", ""), employment=employment,
                            company=row.get("company", ""), manager=row.get("manager", ""),
                            badge_code=row.get("badge_code") or None,
                            photo_consent=bool(person.photo_consent), status=person.status or "ativo")
            with db.begin_nested():
                _apply(db, person, data)
                if is_new:
                    db.add(person)
                db.flush()
            created += is_new
            updated += not is_new
        except HTTPException as exc:
            errors.append({"line": line, "message": exc.detail})
        except Exception as exc:  # validação do esquema e demais erros da linha
            message = str(exc).split("\n")[0] if not hasattr(exc, "errors") else "; ".join(
                f"{e['loc'][-1]}: {e['msg']}" for e in exc.errors())
            errors.append({"line": line, "message": message})
    audit.record(db, user, "pessoas_importadas", "pessoa", None,
                 f"{file.filename}: {created} novas, {updated} atualizadas, {len(errors)} com erro", request)
    db.commit()
    return {"created": created, "updated": updated, "errors": errors[:200], "total_errors": len(errors)}
