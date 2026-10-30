"""Configuração inicial, login, usuários e auditoria."""


from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from .. import audit
from ..auth import create_session, current_user, extract_token, require_role
from ..common import get_or_404
from ..database import get_db
from ..models import AuditLog, Session, User
from ..schemas import AuditOut, LoginIn, PasswordIn, SessionOut, SetupIn, UserIn, UserOut
from ..security import hash_password, token_hash, verify_password

router = APIRouter(prefix="/api")


@router.get("/setup")
def setup_status(db: DbSession = Depends(get_db)):
    return {"needs_setup": db.scalar(select(func.count()).select_from(User)) == 0}


@router.post("/setup", response_model=SessionOut, status_code=201)
def setup(data: SetupIn, request: Request, db: DbSession = Depends(get_db)):
    """Cria o primeiro administrador. Só funciona enquanto não houver usuários."""
    if db.scalar(select(func.count()).select_from(User)):
        raise HTTPException(409, "o sistema já foi configurado")
    user = User(name=data.name, email=data.email.lower(), password_hash=hash_password(data.password), role="admin")
    db.add(user)
    db.flush()
    audit.record(db, user, "configuracao_inicial", "usuario", user.id, request=request)
    return {"token": create_session(db, user), "user": user}


@router.post("/auth/login", response_model=SessionOut)
def login(data: LoginIn, request: Request, db: DbSession = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == data.email.strip().lower()))
    if user is None or not user.active or not verify_password(data.password, user.password_hash):
        audit.record(db, None, "login_falhou", "usuario", None, data.email[:200], request)
        db.commit()
        raise HTTPException(401, "e-mail ou senha incorretos")
    audit.record(db, user, "login", "usuario", user.id, request=request)
    return {"token": create_session(db, user), "user": user}


@router.post("/auth/logout", status_code=204)
def logout(request: Request, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    token = extract_token(request.headers.get("authorization"), request.query_params.get("token"))
    session = db.scalar(select(Session).where(Session.token_hash == token_hash(token or "")))
    if session:
        db.delete(session)
    audit.record(db, user, "logout", "usuario", user.id, request=request)
    db.commit()


@router.get("/auth/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user


@router.put("/auth/password", status_code=204)
def change_password(data: PasswordIn, request: Request, user: User = Depends(current_user),
                    db: DbSession = Depends(get_db)):
    if not verify_password(data.current_password, user.password_hash):
        raise HTTPException(400, "senha atual incorreta")
    user.password_hash = hash_password(data.new_password)
    audit.record(db, user, "senha_alterada", "usuario", user.id, request=request)
    db.commit()


# ---------- Usuários (administrador) ----------

@router.get("/users", response_model=list[UserOut], dependencies=[Depends(current_user)])
def list_users(db: DbSession = Depends(get_db)):
    # Todos os perfis podem listar (para escolher responsáveis por ações).
    return db.scalars(select(User).order_by(User.name)).all()


def _admins_left(db: DbSession, excluding: int) -> int:
    return db.scalar(
        select(func.count()).select_from(User).where(User.role == "admin", User.active, User.id != excluding)
    )


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(data: UserIn, request: Request, admin: User = Depends(require_role("admin")),
                db: DbSession = Depends(get_db)):
    if not data.password:
        raise HTTPException(422, "defina uma senha com pelo menos 8 caracteres")
    if db.scalar(select(User).where(User.email == data.email.lower())):
        raise HTTPException(409, "já existe um usuário com este e-mail")
    user = User(name=data.name, email=data.email.lower(), role=data.role, active=data.active,
                password_hash=hash_password(data.password))
    db.add(user)
    db.flush()
    audit.record(db, admin, "usuario_criado", "usuario", user.id, f"{user.email} ({user.role})", request)
    db.commit()
    return user


@router.put("/users/{user_id}", response_model=UserOut)
def update_user(user_id: int, data: UserIn, request: Request, admin: User = Depends(require_role("admin")),
                db: DbSession = Depends(get_db)):
    user = get_or_404(db, User, user_id)
    demoting = user.role == "admin" and (data.role != "admin" or not data.active)
    if demoting and _admins_left(db, user.id) == 0:
        raise HTTPException(400, "o sistema precisa de pelo menos um administrador ativo")
    other = db.scalar(select(User).where(User.email == data.email.lower(), User.id != user.id))
    if other:
        raise HTTPException(409, "já existe um usuário com este e-mail")
    changes = [f"{f}: {getattr(user, f)} → {getattr(data, f)}" for f in ("name", "email", "role", "active")
               if getattr(user, f) != getattr(data, f)]
    user.name, user.email, user.role, user.active = data.name, data.email.lower(), data.role, data.active
    if data.password:
        user.password_hash = hash_password(data.password)
        changes.append("senha redefinida")
    if not user.active:
        for session in db.scalars(select(Session).where(Session.user_id == user.id)):
            db.delete(session)
    audit.record(db, admin, "usuario_alterado", "usuario", user.id, "; ".join(changes), request)
    db.commit()
    return user


# ---------- Auditoria ----------

@router.get("/audit", response_model=list[AuditOut], dependencies=[Depends(require_role("admin"))])
def list_audit(entity: str | None = None, entity_id: int | None = None, user_name: str | None = None,
               limit: int = 200, db: DbSession = Depends(get_db)):
    query = select(AuditLog).order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(min(limit, 1000))
    if entity:
        query = query.where(AuditLog.entity == entity)
    if entity_id is not None:
        query = query.where(AuditLog.entity_id == entity_id)
    if user_name:
        query = query.where(AuditLog.user_name.ilike(f"%{user_name}%"))
    return db.scalars(query).all()


