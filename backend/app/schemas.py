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
    sector_id: int | None = None
    unit_id: int | None = None  # ignorado quando há setor (vale a unidade do setor)


class CameraOut(CameraIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    health: str | None = None
    last_frame_at: datetime | None = None
    connect_error: str | None = None
    connect_error_at: datetime | None = None


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
    sector_id: int | None = None


# ---------- Unidades e setores ----------

PPEItem = Literal["helmet", "vest", "glasses", "gloves", "mask"]


class UnitIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    active: bool = True


class UnitOut(UnitIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class BehaviorIn(BaseModel):
    enabled: bool = False
    severity: Severity = "alta"
    max: int | None = Field(None, ge=0, le=100)


class SectorIn(BaseModel):
    unit_id: int
    name: str = Field(min_length=1, max_length=120)
    required_ppe: list[PPEItem] = []
    delivery_ppe: list[str] = []
    required_exams: list[str] = []
    ppe_severity: Severity = "alta"
    behaviors: dict[Literal["restricted_zone", "max_people", "fire_smoke"], BehaviorIn] = {}
    start_hour: int | None = Field(None, ge=0, le=23)
    end_hour: int | None = Field(None, ge=0, le=24)
    reference: str = Field("", max_length=200)

    @field_validator("delivery_ppe")
    @classmethod
    def clean_delivery(cls, items: list[str]) -> list[str]:
        return [i.strip()[:80] for i in items if i.strip()][:30]

    @field_validator("required_exams")
    @classmethod
    def known_exams(cls, items: list[str]) -> list[str]:
        from .exams import CATALOG
        unknown = [i for i in items if i not in CATALOG]
        if unknown:
            raise ValueError(f"exame desconhecido: {', '.join(unknown)}")
        return list(dict.fromkeys(items))


class SectorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    unit_id: int
    name: str
    required_ppe: list[str]
    delivery_ppe: list[str]
    required_exams: list[str] = []
    ppe_severity: str
    behaviors: dict
    start_hour: int | None
    end_hour: int | None
    reference: str
    version: int
    updated_at: datetime
    updated_by: str
    cameras: int = 0
    rules: int = 0


# ---------- Ocorrências e plano de ação ----------

class EventOut(BaseModel):
    unit_id: int | None = None
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
    thumb_url: str | None = None
    media_at_edge: bool = False
    clip_video_url: str | None = None
    clip_frames: int | None = None
    clip_duration: float | None = None
    status: EventStatus
    classification: Classification | None
    notes: str | None
    reviewed_by: str | None
    reviewed_at: datetime | None
    closed_at: datetime | None
    open_actions: int
    created_at: datetime
    person_id: int | None = None
    person_name: str | None = None
    identification: str | None = None


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


class AttachmentOut(BaseModel):
    id: int
    kind: str
    kind_label: str
    filename: str
    content_type: str
    size: int
    uploaded_by: str | None
    uploaded_by_id: int | None
    created_at: datetime


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
    attachments: list[AttachmentOut] = []


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
    direct: dict | None = None  # links assinados para buscar a mídia direto no Edge (rede da fábrica)
    actions: list[ActionOut]
    history: list[AuditOut]
    measures: list[dict] = []
    identified_by: str | None = None
    identified_at: datetime | None = None


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


# ---------- Pessoas ----------

PersonStatus = Literal["ativo", "afastado", "desligado"]
Employment = Literal["clt", "terceiro", "temporario", "estagiario"]


class PersonIn(BaseModel):
    unit_id: int
    sector_id: int | None = None
    name: str = Field(min_length=3, max_length=160)
    cpf: str = Field(min_length=11, max_length=14)
    registration: str | None = Field(None, max_length=40)
    role: str = Field("", max_length=120)
    shift: str = Field("", max_length=60)
    employment: Employment = "clt"
    company: str = Field("", max_length=160)
    manager: str = Field("", max_length=160)
    badge_code: str | None = Field(None, max_length=40)
    photo_consent: bool = False
    status: PersonStatus = "ativo"

    @field_validator("registration", "badge_code")
    @classmethod
    def empty_to_none(cls, value: str | None) -> str | None:
        value = (value or "").strip()
        return value.upper() if value else None


class PersonOut(BaseModel):
    id: int
    unit_id: int
    unit: str
    sector_id: int | None
    sector: str | None
    name: str
    cpf: str  # mascarado, exceto para gestores e administradores no detalhe
    registration: str | None
    role: str
    shift: str
    employment: str
    company: str
    manager: str
    badge_code: str | None
    has_photo: bool
    photo_consent: bool
    photo_consent_on: date | None
    status: str
    ppe_alert: str | None = None  # ex.: "Máscara vence em 12 dias"
    open_trainings: int = 0
    exam_alert: str | None = None  # ex.: "ASO vencido", "Audiometria vence em 12 dia(s)"


class DeliveryIn(BaseModel):
    item: str = Field(min_length=1, max_length=120)
    ca: str = Field("", max_length=20)
    delivered_on: date
    valid_until: date | None = None


class DeliveryOut(DeliveryIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class TrainingIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    scheduled_on: date | None = None
    valid_until: date | None = None
    status: Literal["agendado", "concluido", "cancelado"] = "agendado"


class TrainingOut(TrainingIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    measure_id: int | None = None


class ExamIn(BaseModel):
    exam: str
    aso_type: Literal["admissional", "periodico", "retorno", "mudanca_risco", "demissional"] | None = None
    performed_on: date
    valid_until: date | None = None  # vazio = calculada pela periodicidade sugerida
    result: Literal["apto", "apto_restricao", "inapto"] | None = None
    restrictions: str = Field("", max_length=300)
    aptitudes: list[str] = []
    provider: str = Field("", max_length=160)

    @field_validator("exam")
    @classmethod
    def known_exam(cls, value: str) -> str:
        from .exams import CATALOG
        if value not in CATALOG:
            raise ValueError("exame desconhecido")
        return value

    @field_validator("aptitudes")
    @classmethod
    def known_aptitudes(cls, items: list[str]) -> list[str]:
        from .exams import APTITUDES
        return [i for i in dict.fromkeys(items) if i in APTITUDES]


class ExamOut(ExamIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    label: str = ""
    status: str = ""
    days: int | None = None


class PersonDetail(PersonOut):
    deliveries: list[DeliveryOut]
    trainings: list[TrainingOut]
    exams: list[ExamOut] = []
    exam_status: list[dict] = []
    required_exams: list[str] = []
    required_ppe: list[str] = []
    delivery_ppe: list[str] = []
