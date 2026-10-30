"""Configurações editáveis pelo painel (guia Configurações, só administradores).

Os valores salvos no banco têm prioridade sobre o .env e são aplicados ao objeto `settings`
na inicialização e a cada alteração. Segredos (senha do NAS) são criptografados com uma
chave que NÃO vai no backup: ao restaurar em outro computador, basta digitar a senha de novo."""

from __future__ import annotations

import base64
import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from .config import settings
from .database import SessionLocal
from .models import SystemState

log = logging.getLogger("vigia.config")

PREFIX = "cfg:"


@dataclass(frozen=True)
class Field:
    kind: str  # text | int | choice | secret | bool | emails | phones
    minimum: int | None = None
    maximum: int | None = None
    choices: tuple[str, ...] = ()
    max_length: int = 500


SEVERITIES = ("baixa", "media", "alta", "critica")

FIELDS: dict[str, Field] = {
    # Retenção
    "retention_days": Field("int", 1, 3650),
    "event_retention_days": Field("int", 1, 7300),
    "audit_retention_days": Field("int", 0, 7300),
    "session_hours": Field("int", 1, 720),
    # Uso do sistema
    "usage_alert_cpu": Field("int", 10, 100),
    "usage_alert_memory": Field("int", 10, 100),
    "usage_alert_disk": Field("int", 10, 100),
    "usage_alert_minutes": Field("int", 1, 1440),
    # Alertas
    "alert_emails": Field("emails", max_length=2000),
    "alert_min_severity_email": Field("choice", choices=SEVERITIES),
    "alert_min_severity_whatsapp": Field("choice", choices=SEVERITIES),
    "camera_offline_after": Field("int", 10, 86400),
    "smtp_host": Field("text", max_length=200),
    "smtp_port": Field("int", 1, 65535),
    "smtp_user": Field("text", max_length=200),
    "smtp_password": Field("secret", max_length=500),
    "smtp_from": Field("text", max_length=200),
    "smtp_tls": Field("bool"),
    "whatsapp_token": Field("secret", max_length=1000),
    "whatsapp_phone_id": Field("text", max_length=60),
    "whatsapp_to": Field("phones", max_length=1000),
    "whatsapp_template": Field("text", max_length=200),
    "whatsapp_template_lang": Field("text", max_length=20),
    "report_emails": Field("emails", max_length=2000),
    "public_url": Field("text", max_length=300),
    # Armazenamento de rede
    "storage_nas_path": Field("text"),
    "storage_nas_user": Field("text", max_length=200),
    "storage_nas_password": Field("secret", max_length=200),
    "storage_mode": Field("choice", choices=("espelho", "principal")),
    "storage_local_days": Field("int", 1, 3650),
    "storage_sync_interval": Field("int", 10, 3600),
    "storage_offline_alert_minutes": Field("int", 1, 1440),
    "storage_backup_keep": Field("int", 1, 1000),
    # Backup
    "backup_hour": Field("int", 0, 23),
    "backup_keep": Field("int", 1, 365),
    "backup_copy_dir": Field("text"),
}

# Valores vindos do .env/ambiente, para "voltar ao padrão"
ENV_DEFAULTS = {name: getattr(settings, name) for name in FIELDS}
FROM_ENV = {name for name in FIELDS if name in settings.model_fields_set}


def _fernet() -> Fernet:
    secret = settings.secret_key
    if not secret:
        key_file = Path(settings.secret_key_file)
        if not key_file.exists():
            key_file.parent.mkdir(parents=True, exist_ok=True)
            key_file.write_text(base64.urlsafe_b64encode(hashlib.sha256(Fernet.generate_key()).digest()).decode())
        secret = key_file.read_text().strip()
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()))


def encrypt(value: str) -> str:
    return "enc:" + _fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str | None:
    if not value.startswith("enc:"):
        return value
    try:
        return _fernet().decrypt(value[4:].encode()).decode()
    except InvalidToken:
        return None  # chave diferente (ex.: backup restaurado em outro computador)


def validate(name: str, value):
    field = FIELDS.get(name)
    if field is None:
        raise ValueError(f"configuração desconhecida: {name}")
    if field.kind == "bool":
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "sim", "on")
        return bool(value)
    if field.kind == "int":
        try:
            value = int(value)
        except (TypeError, ValueError):
            raise ValueError(f"{name}: informe um número inteiro") from None
        if not field.minimum <= value <= field.maximum:
            raise ValueError(f"{name}: valor entre {field.minimum} e {field.maximum}")
        return value
    value = "" if value is None else str(value).strip()
    if len(value) > field.max_length:
        raise ValueError(f"{name}: texto longo demais")
    if field.kind == "choice" and value not in field.choices:
        raise ValueError(f"{name}: use {' ou '.join(field.choices)}")
    if field.kind == "emails":
        items = [e.strip() for e in value.replace(";", ",").split(",") if e.strip()]
        invalid = [e for e in items if "@" not in e or " " in e or e.startswith("@") or e.endswith("@")]
        if invalid:
            raise ValueError(f"e-mail inválido: {invalid[0]}")
        return ", ".join(items)
    if field.kind == "phones":
        items = ["".join(ch for ch in p if ch.isdigit()) for p in value.replace(";", ",").split(",") if p.strip()]
        invalid = [p for p in items if not 10 <= len(p) <= 15]
        if invalid:
            raise ValueError("WhatsApp: informe os números com DDI e DDD, ex.: 5511999999999")
        return ",".join(items)
    if name == "public_url" and value and not value.startswith(("http://", "https://")):
        raise ValueError("endereço do painel deve começar com http:// ou https://")
    return value


def _stored() -> dict[str, str]:
    with SessionLocal() as db:
        rows = db.query(SystemState).filter(SystemState.key.like(f"{PREFIX}%")).all()
        return {row.key[len(PREFIX):]: row.value for row in rows}


def apply_overrides() -> list[str]:
    """Aplica ao `settings` os valores salvos pelo painel. Devolve avisos (ex.: segredo ilegível)."""
    warnings = []
    stored = _stored()
    for name, default in ENV_DEFAULTS.items():
        if name not in stored:
            setattr(settings, name, default)
            continue
        raw = stored[name]
        if FIELDS[name].kind == "secret":
            value = decrypt(raw)
            if value is None:
                warnings.append(f"{name}: não foi possível ler o valor salvo; digite-o novamente")
                value = ""
        elif FIELDS[name].kind == "int":
            value = int(raw)
        elif FIELDS[name].kind == "bool":
            value = raw == "True"
        else:
            value = raw
        setattr(settings, name, value)
    for w in warnings:
        log.warning(w)
    return warnings


def save(values: dict) -> list[str]:
    """Valida tudo antes de gravar. Segredo vazio/None = manter o atual. Devolve os campos alterados."""
    clean = {}
    for name, value in values.items():
        field = FIELDS.get(name)
        if field and field.kind == "secret" and value in (None, ""):
            continue
        clean[name] = validate(name, value)
    changed = [n for n, v in clean.items() if getattr(settings, n) != v]
    already = set(_stored())
    with SessionLocal() as db:
        # grava só o que mudou (ou já era definido no painel): o resto continua vindo do .env
        for name, value in clean.items():
            if name not in changed and name not in already:
                continue
            stored = encrypt(value) if FIELDS[name].kind == "secret" and value else str(value)
            db.merge(SystemState(key=PREFIX + name, value=stored))
        db.commit()
    apply_overrides()
    return changed


def clear(names: list[str]) -> None:
    """Volta os campos ao valor do .env."""
    with SessionLocal() as db:
        for name in names:
            row = db.get(SystemState, PREFIX + name)
            if row:
                db.delete(row)
        db.commit()
    apply_overrides()


def public_values() -> dict:
    """Valores para a tela, sem expor segredos."""
    stored = _stored()
    out = {}
    for name, field in FIELDS.items():
        source = "painel" if name in stored else ("env" if name in FROM_ENV else "padrao")
        if field.kind == "secret":
            out[name] = {"set": bool(getattr(settings, name)), "source": source}
        else:
            out[name] = {"value": getattr(settings, name), "source": source}
    return out
