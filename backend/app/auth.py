import secrets

from fastapi import Header, HTTPException, Query, status

from .config import settings


def matches(given: str | None, expected: str) -> bool:
    return bool(given) and secrets.compare_digest(given, expected)


def require_user(
    authorization: str | None = Header(None),
    token: str | None = Query(None),
) -> None:
    """Protege o painel/API. Aceita 'Authorization: Bearer <token>' ou '?token=' (imagens e WebSocket)."""
    if not settings.api_token:
        return
    given = token
    if authorization and authorization.lower().startswith("bearer "):
        given = authorization[7:]
    if not matches(given, settings.api_token):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token inválido")


def require_detector(x_detector_key: str | None = Header(None)) -> None:
    if not matches(x_detector_key, settings.detector_api_key):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "chave do detector inválida")
