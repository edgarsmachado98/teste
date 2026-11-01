"""Unidades, setores e padrões de segurança por setor."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..auth import current_user, require_role
from ..common import get_or_404
from ..database import get_db
from ..models import Camera, Rule, Sector, Unit, User
from ..schemas import SectorIn, SectorOut, UnitIn, UnitOut
from ..sectors import TEMPLATES, apply_sector

router = APIRouter(prefix="/api")


# ---------- Unidades ----------

@router.get("/units", response_model=list[UnitOut], dependencies=[Depends(current_user)])
def list_units(db: Session = Depends(get_db)):
    return db.scalars(select(Unit).order_by(Unit.name)).all()


@router.post("/units", response_model=UnitOut, status_code=201)
def create_unit(data: UnitIn, request: Request, user: User = Depends(require_role("admin")),
                db: Session = Depends(get_db)):
    if db.scalar(select(Unit).where(Unit.name == data.name)):
        raise HTTPException(409, "já existe uma unidade com este nome")
    unit = Unit(**data.model_dump())
    db.add(unit)
    db.flush()
    audit.record(db, user, "unidade_criada", "unidade", unit.id, unit.name, request)
    db.commit()
    return unit


@router.put("/units/{unit_id}", response_model=UnitOut)
def update_unit(unit_id: int, data: UnitIn, request: Request, user: User = Depends(require_role("admin")),
                db: Session = Depends(get_db)):
    unit = get_or_404(db, Unit, unit_id)
    unit.name, unit.active = data.name, data.active
    audit.record(db, user, "unidade_alterada", "unidade", unit.id, unit.name, request)
    db.commit()
    return unit


# ---------- Setores ----------

def _out(db: Session, sector: Sector) -> dict:
    cameras = db.scalar(select(func.count()).select_from(Camera).where(Camera.sector_id == sector.id))
    rules = db.scalar(select(func.count()).select_from(Rule).where(Rule.sector_id == sector.id))
    return {**SectorOut.model_validate(sector).model_dump(), "cameras": cameras, "rules": rules}


def _payload(data: SectorIn) -> dict:
    values = data.model_dump()
    values["behaviors"] = {k: v for k, v in values["behaviors"].items()}
    return values


@router.get("/sectors", response_model=list[SectorOut], dependencies=[Depends(current_user)])
def list_sectors(unit_id: int | None = None, db: Session = Depends(get_db)):
    query = select(Sector).order_by(Sector.name)
    if unit_id is not None:
        query = query.where(Sector.unit_id == unit_id)
    return [_out(db, s) for s in db.scalars(query)]


@router.get("/sectors/templates", dependencies=[Depends(current_user)])
def sector_templates():
    return [{"id": key, **tpl} for key, tpl in TEMPLATES.items()]


@router.get("/sectors/{sector_id}", response_model=SectorOut, dependencies=[Depends(current_user)])
def get_sector(sector_id: int, db: Session = Depends(get_db)):
    return _out(db, get_or_404(db, Sector, sector_id))


@router.post("/sectors/preview", dependencies=[Depends(require_role("tecnico"))])
def preview_new_sector(data: SectorIn, db: Session = Depends(get_db)):
    """Prévia de um setor ainda não salvo (sem câmeras, mostra só as regras do padrão)."""
    return apply_sector(db, Sector(id=-1, **_payload(data)), dry_run=True).as_dict()


@router.post("/sectors/{sector_id}/preview", dependencies=[Depends(require_role("tecnico"))])
def preview_sector(sector_id: int, data: SectorIn, db: Session = Depends(get_db)):
    """O que mudaria nas câmeras se o padrão fosse salvo com estes valores (nada é gravado)."""
    get_or_404(db, Sector, sector_id)
    transient = Sector(id=sector_id, **_payload(data))
    result = apply_sector(db, transient, dry_run=True).as_dict()
    db.expunge(transient) if transient in db else None
    db.rollback()
    return result


def _save(db: Session, sector: Sector, data: SectorIn, user: User) -> None:
    get_or_404(db, Unit, data.unit_id)
    other = db.scalar(select(Sector).where(Sector.unit_id == data.unit_id, Sector.name == data.name,
                                           Sector.id != (sector.id or 0)))
    if other:
        raise HTTPException(409, "já existe um setor com este nome nesta unidade")
    if (data.start_hour is None) != (data.end_hour is None):
        raise HTTPException(422, "informe as duas horas do horário ou nenhuma")
    for key, value in _payload(data).items():
        setattr(sector, key, value)
    sector.updated_at = datetime.now(timezone.utc)
    sector.updated_by = user.name


@router.post("/sectors", status_code=201)
def create_sector(data: SectorIn, request: Request, user: User = Depends(require_role("tecnico")),
                  db: Session = Depends(get_db)):
    sector = Sector(version=1)
    _save(db, sector, data, user)
    db.add(sector)
    db.flush()
    audit.record(db, user, "setor_criado", "setor", sector.id, sector.name, request)
    db.commit()
    return {"sector": _out(db, sector), "applied": apply_sector(db, sector, dry_run=True).as_dict()}


@router.put("/sectors/{sector_id}")
def update_sector(sector_id: int, data: SectorIn, request: Request, user: User = Depends(require_role("tecnico")),
                  db: Session = Depends(get_db)):
    """Salva o padrão (nova versão) e aplica às câmeras do setor."""
    sector = get_or_404(db, Sector, sector_id)
    _save(db, sector, data, user)
    sector.version += 1
    result = apply_sector(db, sector)
    audit.record(db, user, "padrao_setor_aplicado", "setor", sector.id,
                 f"{sector.name} v{sector.version}: {len(result.created)} regras criadas, {len(result.updated)} "
                 f"atualizadas, {len(result.removed)} removidas", request)
    db.commit()
    return {"sector": _out(db, sector), "applied": result.as_dict()}


@router.delete("/sectors/{sector_id}", status_code=204)
def delete_sector(sector_id: int, request: Request, user: User = Depends(require_role("gestor")),
                  db: Session = Depends(get_db)):
    sector = get_or_404(db, Sector, sector_id)
    for rule in db.scalars(select(Rule).where(Rule.sector_id == sector.id)):
        db.delete(rule)
    for camera in db.scalars(select(Camera).where(Camera.sector_id == sector.id)):
        camera.sector_id = None
    audit.record(db, user, "setor_excluido", "setor", sector.id, sector.name, request)
    db.delete(sector)
    db.commit()
