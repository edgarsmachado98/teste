"""Datas: o banco guarda em UTC; indicadores e mensagens usam o fuso e os turnos da planta."""

from datetime import datetime, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

from .config import settings


@lru_cache
def local_tz() -> ZoneInfo:
    return ZoneInfo(settings.timezone)


def as_utc(dt: datetime) -> datetime:
    # SQLite devolve datas sem fuso; tudo que gravamos está em UTC.
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def to_local(dt: datetime) -> datetime:
    return as_utc(dt).astimezone(local_tz())


@lru_cache
def parse_shifts(spec: str) -> list[tuple[str, int, int]]:
    shifts = []
    for part in spec.split(","):
        if "=" not in part:
            continue
        name, hours = part.split("=", 1)
        start, end = hours.split("-")
        shifts.append((name.strip(), int(start), int(end)))
    return shifts


def shift_of(local_dt: datetime) -> str:
    hour = local_dt.hour
    for name, start, end in parse_shifts(settings.shifts):
        if (start <= hour < end) if start < end else (hour >= start or hour < end):
            return name
    return "Fora de turno"


def shift_names() -> list[str]:
    return [name for name, _, _ in parse_shifts(settings.shifts)]
