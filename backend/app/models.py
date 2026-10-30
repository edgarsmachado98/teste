from datetime import date, datetime, timezone

from sqlalchemy import JSON, Boolean, Date, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base, UTCDateTime


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# Perfis em ordem crescente de permissão
ROLES = ("operador", "tecnico", "gestor", "admin")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(300))
    role: Mapped[str] = mapped_column(String(20), default="operador")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    # Guardamos só o hash do token: um vazamento do banco não dá acesso ao sistema.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)

    user: Mapped[User] = relationship()


class AuditLog(Base):
    """Registro de quem fez o quê (LGPD e rastreabilidade das ocorrências)."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    user_name: Mapped[str] = mapped_column(String(120), default="sistema")
    action: Mapped[str] = mapped_column(String(60))
    entity: Mapped[str] = mapped_column(String(40), default="")
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    details: Mapped[str] = mapped_column(Text, default="")
    ip: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)


class Camera(Base):
    __tablename__ = "cameras"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    location: Mapped[str] = mapped_column(String(120), default="")
    # URL RTSP/HTTP ou caminho de arquivo de vídeo (para testes)
    source: Mapped[str] = mapped_column(String(500))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    # Saúde: ok | offline | escura | obstruida | congelada (None = ainda sem imagem)
    health: Mapped[str | None] = mapped_column(String(20), nullable=True)
    last_frame_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

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


# Fluxo da ocorrência: nova -> confirmada | descartada -> encerrada
EVENT_STATUSES = ("nova", "confirmada", "descartada", "encerrada")
CLASSIFICATIONS = ("ato_inseguro", "condicao_insegura", "quase_acidente", "acidente")


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id", ondelete="CASCADE"))
    rule_id: Mapped[int | None] = mapped_column(ForeignKey("rules.id", ondelete="SET NULL"), nullable=True)
    type: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(String(500))
    image_file: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Clipe (sequência de quadros JPEG) de alguns segundos antes e depois do desvio
    clip_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    clip_dir: Mapped[str | None] = mapped_column(String(255), nullable=True)
    clip_frames: Mapped[int | None] = mapped_column(Integer, nullable=True)
    clip_duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Quando a foto e o clipe foram copiados para o armazenamento de rede (NAS)
    media_synced_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="nova")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    # Caixas normalizadas das pessoas/objetos em violação (usadas no mapa de calor)
    boxes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    classification: Mapped[str | None] = mapped_column(String(30), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    camera: Mapped[Camera] = relationship()
    rule: Mapped[Rule | None] = relationship()
    reviewed_by: Mapped[User | None] = relationship()
    actions: Mapped[list["ActionItem"]] = relationship(back_populates="event")


ACTION_STATUSES = ("aberta", "concluida", "cancelada")


class ActionItem(Base):
    """Ação do plano de ação (corretiva ou preventiva)."""

    __tablename__ = "actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int | None] = mapped_column(ForeignKey("events.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    responsible_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="aberta")
    completion_notes: Mapped[str] = mapped_column(Text, default="")
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    event: Mapped[Event | None] = relationship(back_populates="actions")
    responsible: Mapped[User | None] = relationship(foreign_keys=[responsible_id])
    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id])


class StorageDeletion(Base):
    """Exclusão pendente no NAS (retenção/LGPD) para quando ele estiver acessível."""

    __tablename__ = "storage_deletions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rel_path: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class SystemState(Base):
    """Pares chave/valor do sistema (ex.: data do último backup e do último relatório enviado)."""

    __tablename__ = "system_state"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


class RuleStat(Base):
    """Observações agregadas por hora: base do índice de conformidade de EPI.

    `observed` = pessoas observadas na zona (somadas por quadro analisado);
    `violations` = quantas dessas estavam sem algum EPI obrigatório."""

    __tablename__ = "rule_stats"
    __table_args__ = (UniqueConstraint("rule_id", "hour"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("rules.id", ondelete="CASCADE"))
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id", ondelete="CASCADE"))
    hour: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    observed: Mapped[int] = mapped_column(Integer, default=0)
    violations: Mapped[int] = mapped_column(Integer, default=0)
