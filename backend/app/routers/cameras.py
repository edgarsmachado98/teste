from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..auth import current_user, require_role
from ..common import EVIDENCE_DIR, get_or_404
from ..database import get_db
from ..models import Camera, Rule, User
from ..schemas import CameraIn, CameraOut, RuleIn, RuleOut

router = APIRouter(prefix="/api")
viewer = [Depends(current_user)]


def _mask(source: str) -> str:
    """Esconde a senha das URLs RTSP no log de auditoria."""
    if "://" in source and "@" in source:
        scheme, rest = source.split("://", 1)
        return f"{scheme}://***@{rest.split('@', 1)[1]}"
    return source


@router.get("/cameras", response_model=list[CameraOut], dependencies=viewer)
def list_cameras(db: Session = Depends(get_db)):
    return db.scalars(select(Camera).order_by(Camera.name)).all()


@router.post("/cameras", response_model=CameraOut, status_code=201)
def create_camera(data: CameraIn, request: Request, user: User = Depends(require_role("tecnico")),
                  db: Session = Depends(get_db)):
    camera = Camera(**data.model_dump())
    db.add(camera)
    db.flush()
    audit.record(db, user, "camera_criada", "camera", camera.id, f"{camera.name} – {_mask(camera.source)}", request)
    db.commit()
    return camera


@router.put("/cameras/{camera_id}", response_model=CameraOut)
def update_camera(camera_id: int, data: CameraIn, request: Request, user: User = Depends(require_role("tecnico")),
                  db: Session = Depends(get_db)):
    camera = get_or_404(db, Camera, camera_id)
    for key, value in data.model_dump().items():
        setattr(camera, key, value)
    audit.record(db, user, "camera_alterada", "camera", camera.id, camera.name, request)
    db.commit()
    return camera


@router.delete("/cameras/{camera_id}", status_code=204)
def delete_camera(camera_id: int, request: Request, user: User = Depends(require_role("gestor")),
                  db: Session = Depends(get_db)):
    camera = get_or_404(db, Camera, camera_id)
    audit.record(db, user, "camera_excluida", "camera", camera.id, camera.name, request)
    db.delete(camera)
    db.commit()


@router.get("/cameras/{camera_id}/frame", dependencies=viewer)
def camera_frame(camera_id: int):
    path = EVIDENCE_DIR / "ao-vivo" / f"{camera_id}.jpg"
    if not path.exists():
        raise HTTPException(404, "sem imagem ainda – verifique se o detector está rodando")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


# ---------- Regras ----------

@router.get("/rules", response_model=list[RuleOut], dependencies=viewer)
def list_rules(camera_id: int | None = None, db: Session = Depends(get_db)):
    query = select(Rule).order_by(Rule.camera_id, Rule.name)
    if camera_id is not None:
        query = query.where(Rule.camera_id == camera_id)
    return db.scalars(query).all()


@router.post("/rules", response_model=RuleOut, status_code=201)
def create_rule(data: RuleIn, request: Request, user: User = Depends(require_role("tecnico")),
                db: Session = Depends(get_db)):
    get_or_404(db, Camera, data.camera_id)
    rule = Rule(**data.model_dump())
    db.add(rule)
    db.flush()
    audit.record(db, user, "regra_criada", "regra", rule.id, f"{rule.name} ({rule.type})", request)
    db.commit()
    return rule


@router.put("/rules/{rule_id}", response_model=RuleOut)
def update_rule(rule_id: int, data: RuleIn, request: Request, user: User = Depends(require_role("tecnico")),
                db: Session = Depends(get_db)):
    rule = get_or_404(db, Rule, rule_id)
    get_or_404(db, Camera, data.camera_id)
    for key, value in data.model_dump().items():
        setattr(rule, key, value)
    audit.record(db, user, "regra_alterada", "regra", rule.id, rule.name, request)
    db.commit()
    return rule


@router.delete("/rules/{rule_id}", status_code=204)
def delete_rule(rule_id: int, request: Request, user: User = Depends(require_role("tecnico")),
                db: Session = Depends(get_db)):
    rule = get_or_404(db, Rule, rule_id)
    audit.record(db, user, "regra_excluida", "regra", rule.id, rule.name, request)
    db.delete(rule)
    db.commit()
