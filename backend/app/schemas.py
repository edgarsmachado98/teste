from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

RuleType = Literal["ppe_missing", "restricted_zone", "fire_smoke", "max_people"]
Severity = Literal["baixa", "media", "alta", "critica"]
EventStatus = Literal["nova", "confirmada", "descartada", "encerrada"]
Classification = Literal["ato_inseguro", "condicao_insegura", "quase_acidente", "acidente"]
Role = Literal["operador", "tecnico", "gestor", "admin"]
ActionStatus = Literal["aberta", "concluida", "cancelada"]


# ---------- Usuários e acesso ----------

class LoginIn(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    email: str
    role: Role
    active: bool
    last_login_at: datetime | None = None


class UserIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=200, pattern=r"^[^@\s]+@[^@\s]+$")
    role: Role = "operador"
    active: bool = True
    # Obrigatória na criação; na edição, vazia mantém a atual.
    password: str | None = Field(None, min_length=8, max_length=200)


class SetupIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=200, pattern=r"^[^@\s]+@[^@\s]+$")
    password: str = Field(min_length=8, max_length=200)


class PasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=200)


class SessionOut(BaseModel):
    token: str
    user: UserOut


# ---------- Câmeras e regras ----------

class CameraIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    location: str = ""
    source: str = Field(min_length=1, max_length=500)
    enabled: bool = True


class CameraOut(CameraIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    health: str | None = None
    last_frame_at: datetime | None = None


class RuleIn(BaseModel):
    camera_id: int
    name: str = Field(min_length=1, max_length=120)
    type: RuleType
    zone: list[list[float]] = []
    params: dict = {}
    min_confidence: float = Field(0.5, ge=0, le=1)
    min_duration: float = Field(2.0, ge=0)
    cooldown: float = Field(300.0, ge=0)
    start_hour: int | None = Field(None, ge=0, le=23)
    end_hour: int | None = Field(None, ge=0, le=24)
    severity: Severity = "alta"
    enabled: bool = True

    @field_validator("zone")
    @classmethod
    def check_zone(cls, zone: list[list[float]]) -> list[list[float]]:
        if zone and len(zone) < 3:
            raise ValueError("a zona precisa de pelo menos 3 pontos")
        for point in zone:
            if len(point) != 2 or not all(0 <= v <= 1 for v in point):
                raise ValueError("pontos da zona devem ser [x, y] normalizados entre 0 e 1")
        return zone


class RuleOut(RuleIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


# ---------- Ocorrências e plano de ação ----------

class EventOut(BaseModel):
    id: int
    camera_id: int
    camera_name: str
    location: str
    rule_id: int | None
    rule_name: str | None
    type: str
    severity: str
    message: str
    image_url: str | None
    status: EventStatus
    classification: Classification | None
    notes: str | None
    reviewed_by: str | None
    reviewed_at: datetime | None
    closed_at: datetime | None
    open_actions: int
    created_at: datetime


class EventUpdate(BaseModel):
    status: EventStatus | None = None
    classification: Classification | None = None
    notes: str | None = Field(None, max_length=4000)


class ActionIn(BaseModel):
    event_id: int | None = None
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    responsible_id: int | None = None
    due_date: date | None = None


class ActionUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = None
    responsible_id: int | None = None
    due_date: date | None = None
    status: ActionStatus | None = None
    completion_notes: str | None = None


class ActionOut(BaseModel):
    id: int
    event_id: int | None
    event_message: str | None
    title: str
    description: str
    responsible_id: int | None
    responsible_name: str | None
    due_date: date | None
    status: ActionStatus
    overdue: bool
    completion_notes: str
    created_by: str | None
    created_at: datetime
    completed_at: datetime | None


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_name: str
    action: str
    entity: str
    entity_id: int | None
    details: str
    ip: str
    created_at: datetime


class EventDetail(EventOut):
    actions: list[ActionOut]
    history: list[AuditOut]


# ---------- Detector ----------

class DetectorCamera(BaseModel):
    id: int
    name: str
    source: str
    rules: list[RuleOut]


class StatItem(BaseModel):
    rule_id: int
    observed: int = Field(ge=0)
    violations: int = Field(ge=0)


class StatsIn(BaseModel):
    camera_id: int
    items: list[StatItem]
