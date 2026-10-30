import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, Header, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from .config import settings
from .database import get_db
from .models import ROLES, Session, User
from .security import new_token, token_hash
from .timeutil import as_utc


def matches(given: str | None, expected: str) -> bool:
    return bool(given) and secrets.compare_digest(given, expected)


def create_session(db: DbSession, user: User) -> str:
    token = new_token()
    now = datetime.now(timezone.utc)
    db.add(Session(user_id=user.id, token_hash=token_hash(token), expires_at=now + timedelta(hours=settings.session_hours)))
    user.last_login_at = now
    db.commit()
    return token


def user_from_token(db: DbSession, token: str | None) -> User | None:
    if not token:
        return None
    session = db.scalar(select(Session).where(Session.token_hash == token_hash(token)))
    if session is None or as_utc(session.expires_at) < datetime.now(timezone.utc):
        return None
    return session.user if session.user.active else None


def extract_token(authorization: str | None, token: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:]
    return token


def current_user(
    request: Request,
    authorization: str | None = Header(None),
    token: str | None = Query(None),
    db: DbSession = Depends(get_db),
) -> User:
    """Aceita 'Authorization: Bearer <token>' ou '?token=' (imagens e WebSocket)."""
    user = user_from_token(db, extract_token(authorization, token))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "faça login para continuar")
    request.state.user = user
    return user


def require_role(minimum: str):
    level = ROLES.index(minimum)

    def checker(user: User = Depends(current_user)) -> User:
        if ROLES.index(user.role) < level:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"permissão insuficiente (requer perfil {minimum})")
        return user

    return checker


def has_role(user: User, minimum: str) -> bool:
    return ROLES.index(user.role) >= ROLES.index(minimum)


def require_detector(x_detector_key: str | None = Header(None)) -> None:
    if not matches(x_detector_key, settings.detector_api_key):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "chave do detector inválida")
