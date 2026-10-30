from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

RuleType = Literal["ppe_missing", "restricted_zone", "fire_smoke", "max_people"]
Severity = Literal["baixa", "media", "alta", "critica"]
EventStatus = Literal["nova", "confirmada", "descartada"]


class CameraIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    location: str = ""
    source: str = Field(min_length=1, max_length=500)
    enabled: bool = True


class CameraOut(CameraIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime


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


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    camera_id: int
    camera_name: str
    rule_id: int | None
    rule_name: str | None
    type: str
    severity: str
    message: str
    image_url: str | None
    status: EventStatus
    created_at: datetime


class EventStatusIn(BaseModel):
    status: EventStatus


class DetectorCamera(BaseModel):
    id: int
    name: str
    source: str
    rules: list[RuleOut]
