from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Camera(Base):
    __tablename__ = "cameras"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    location: Mapped[str] = mapped_column(String(120), default="")
    # URL RTSP/HTTP ou caminho de arquivo de vídeo (para testes)
    source: Mapped[str] = mapped_column(String(500))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    rules: Mapped[list["Rule"]] = relationship(back_populates="camera", cascade="all, delete-orphan")


class Rule(Base):
    __tablename__ = "rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120))
    # ppe_missing | restricted_zone | fire_smoke | max_people
    type: Mapped[str] = mapped_column(String(40))
    # Polígono com coordenadas normalizadas (0..1). Vazio = imagem inteira.
    zone: Mapped[list] = mapped_column(JSON, default=list)
    # Parâmetros específicos do tipo, ex.: {"required": ["helmet", "vest"]}
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    min_confidence: Mapped[float] = mapped_column(Float, default=0.5)
    min_duration: Mapped[float] = mapped_column(Float, default=2.0)  # segundos
    cooldown: Mapped[float] = mapped_column(Float, default=300.0)  # segundos
    start_hour: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_hour: Mapped[int | None] = mapped_column(Integer, nullable=True)
    severity: Mapped[str] = mapped_column(String(20), default="alta")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    camera: Mapped[Camera] = relationship(back_populates="rules")


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id", ondelete="CASCADE"))
    rule_id: Mapped[int | None] = mapped_column(ForeignKey("rules.id", ondelete="SET NULL"), nullable=True)
    type: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(String(500))
    image_file: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # nova | confirmada | descartada
    status: Mapped[str] = mapped_column(String(20), default="nova")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    camera: Mapped[Camera] = relationship()
    rule: Mapped[Rule | None] = relationship()
