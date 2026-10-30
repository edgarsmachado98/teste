from fastapi import Request
from sqlalchemy.orm import Session

from .models import AuditLog, User


def record(
    db: Session,
    user: User | None,
    action: str,
    entity: str = "",
    entity_id: int | None = None,
    details: str = "",
    request: Request | None = None,
) -> None:
    """Adiciona ao log de auditoria (o commit fica com quem chamou)."""
    db.add(
        AuditLog(
            user_id=user.id if user else None,
            user_name=user.name if user else "sistema",
            action=action,
            entity=entity,
            entity_id=entity_id,
            details=details[:2000],
            ip=request.client.host if request and request.client else "",
        )
    )
