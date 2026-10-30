"""Guia Configurações (somente administradores): armazenamento de rede, backup e restauração."""

import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import audit, backup, settings_store, storage
from ..auth import require_role
from ..config import settings
from ..database import SessionLocal, get_db
from ..models import AuditLog, User
from ..timeutil import local_tz

router = APIRouter(prefix="/api/config")
admin_only = require_role("admin")
MAX_UPLOAD = 20 * 1024**3  # 20 GB (backups completos com evidências)


def _error(exc: Exception, status: int = 400):
    return HTTPException(status, str(exc))


@router.get("")
def get_config(_: User = Depends(admin_only)):
    if storage.enabled():
        storage.check()
    return {
        "values": settings_store.public_values(),
        "storage": storage.status(),
        "database": "sqlite" if backup.sqlite_path() else "postgresql",
        "backups": backup.list_backups(),
        "backup_dir": str(backup.backup_dir().resolve()),
    }


class ConfigIn(BaseModel):
    values: dict = {}
    reset: list[str] = []  # campos que voltam ao valor do .env


@router.put("")
def put_config(data: ConfigIn, request: Request, user: User = Depends(admin_only), db: Session = Depends(get_db)):
    unknown = [n for n in [*data.values, *data.reset] if n not in settings_store.FIELDS]
    if unknown:
        raise HTTPException(400, f"configuração desconhecida: {unknown[0]}")
    old_path = settings.storage_nas_path
    try:
        changed = settings_store.save(data.values)
    except ValueError as exc:
        raise _error(exc) from exc
    if data.reset:
        settings_store.clear(data.reset)
        changed += data.reset
    if settings.storage_nas_path != old_path:
        storage.reset_state()
    if changed:
        shown = [n if n != "storage_nas_password" else "senha do NAS" for n in changed]
        audit.record(db, user, "configuracao_alterada", "sistema", None, ", ".join(shown), request)
        db.commit()
    return get_config(user)


class StorageTestIn(BaseModel):
    path: str
    user: str = ""
    password: str | None = None  # vazio = usar a senha salva


@router.post("/storage/test")
def test_storage(data: StorageTestIn, _: User = Depends(admin_only)):
    password = data.password if data.password else settings.storage_nas_password
    return storage.probe(data.path.strip(), data.user.strip(), password or "")


@router.post("/storage/activate")
def storage_activate(request: Request, user: User = Depends(admin_only), db: Session = Depends(get_db)):
    try:
        storage.activate()
    except OSError as exc:
        raise _error(exc) from exc
    audit.record(db, user, "nas_ativado", "sistema", None, settings.storage_nas_path, request)
    db.commit()
    return storage.status()


@router.post("/storage/sync")
def storage_sync(request: Request, user: User = Depends(admin_only), db: Session = Depends(get_db)):
    if not storage.enabled():
        raise HTTPException(400, "armazenamento de rede não configurado")
    result = storage.sync_once()
    if not result["online"]:
        raise HTTPException(503, storage.status()["error"] or "armazenamento de rede inacessível")
    audit.record(db, user, "nas_sincronizado", "sistema", None,
                 f"{result['synced_events']} ocorrências, {result['copied_files']} arquivos", request)
    db.commit()
    return {**result, "status": storage.status()}


# ---------- Uso do sistema e alertas ----------

@router.get("/usage")
def system_usage(_: User = Depends(admin_only)):
    from ..usage import snapshot

    return snapshot()


class AlertTestIn(BaseModel):
    channel: str  # email | whatsapp
    to: str = ""


@router.post("/alerts/test")
def test_alert(data: AlertTestIn, request: Request, user: User = Depends(admin_only), db: Session = Depends(get_db)):
    """Envia uma mensagem de teste com a configuração salva (mostra o erro, se houver)."""
    from datetime import datetime, timezone

    from .. import notifier

    sample = {"id": 0, "message": "Mensagem de teste do VigIA", "camera_name": "Teste", "rule_name": "Teste",
              "severity": "alta", "created_at": datetime.now(timezone.utc)}
    targets = [t.strip() for t in data.to.replace(";", ",").split(",") if t.strip()]
    try:
        if data.channel == "email":
            recipients = targets or settings.email_recipients
            if not settings.smtp_host or not recipients:
                raise HTTPException(400, "preencha o servidor SMTP e ao menos um destinatário e salve")
            notifier.send_mail(recipients, "[VigIA] Mensagem de teste",
                               "Se você recebeu esta mensagem, os alertas por e-mail do VigIA estão funcionando.")
        elif data.channel == "whatsapp":
            recipients = ["".join(c for c in t if c.isdigit()) for t in targets] or settings.whatsapp_recipients
            if not (settings.whatsapp_token and settings.whatsapp_phone_id and recipients):
                raise HTTPException(400, "preencha token, ID do número e destinatários do WhatsApp e salve")
            notifier.send_whatsapp(sample, None, recipients)
        else:
            raise HTTPException(400, "canal inválido")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, f"falha no envio: {exc}") from exc
    audit.record(db, user, "alerta_teste", "sistema", None, f"{data.channel} para {', '.join(recipients)}", request)
    db.commit()
    return {"sent": True, "to": recipients}


# ---------- Backup ----------

class BackupIn(BaseModel):
    include_evidence: bool = False


@router.post("/backups", status_code=201)
def create_backup(data: BackupIn, request: Request, user: User = Depends(admin_only), db: Session = Depends(get_db)):
    try:
        result = backup.run_backup(include_evidence=data.include_evidence)
    except backup.BackupError as exc:
        raise _error(exc) from exc
    audit.record(db, user, "backup_manual", "sistema", None,
                 f"{result['name']}{' (com evidências)' if data.include_evidence else ''}", request)
    db.commit()
    return result


@router.get("/backups/{name}")
def download_backup(name: str, request: Request, user: User = Depends(admin_only), db: Session = Depends(get_db)):
    try:
        path = backup.backup_path(name)
    except backup.BackupError as exc:
        raise _error(exc, 404) from exc
    audit.record(db, user, "backup_baixado", "sistema", None, name, request)
    db.commit()
    return FileResponse(path, media_type="application/octet-stream", filename=name)


@router.delete("/backups/{name}", status_code=204)
def remove_backup(name: str, request: Request, user: User = Depends(admin_only), db: Session = Depends(get_db)):
    try:
        backup.delete_backup(name)
    except backup.BackupError as exc:
        raise _error(exc, 404) from exc
    audit.record(db, user, "backup_excluido", "sistema", None, name, request)
    db.commit()


# ---------- Restauração ----------

class RestoreIn(BaseModel):
    name: str
    confirm: str


def _do_restore(path: Path, user: User, request: Request, db: Session) -> dict:
    user_name = user.name
    ip = request.client.host if request.client else ""
    db.close()  # libera a conexão desta requisição antes de substituir o banco
    try:
        result = backup.restore(path)
    except backup.BackupError as exc:
        raise _error(exc) from exc
    # registra no banco restaurado (o usuário pode não existir nele)
    with SessionLocal() as new_db:
        new_db.add(AuditLog(user_name=user_name, action="sistema_restaurado", entity="sistema", ip=ip,
                            details=f"a partir de {result['restored_from']}; backup de segurança "
                                    f"{result['safety_backup']}"))
        new_db.commit()
    storage.reset_state()
    return result


def _check_confirm(text: str) -> None:
    if text.strip().upper() != "RESTAURAR":
        raise HTTPException(400, 'digite RESTAURAR para confirmar')


@router.post("/restore")
def restore_from_list(data: RestoreIn, request: Request, user: User = Depends(admin_only),
                      db: Session = Depends(get_db)):
    _check_confirm(data.confirm)
    try:
        path = backup.backup_path(data.name)
    except backup.BackupError as exc:
        raise _error(exc, 404) from exc
    return _do_restore(path, user, request, db)


@router.post("/restore/upload")
async def restore_from_upload(request: Request, file: UploadFile = File(...), confirm: str = "",
                              user: User = Depends(admin_only), db: Session = Depends(get_db)):
    _check_confirm(confirm)
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in (".zip", ".db"):
        raise HTTPException(400, "envie um arquivo de backup do VigIA (.zip ou .db)")
    folder = backup.backup_dir()
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"vigia-{datetime.now(local_tz()):%Y%m%d-%H%M%S}-importado{suffix}"
    if target.exists():
        target = target.with_name(f"{target.stem}-{uuid.uuid4().hex[:4]}{suffix}")
    size = 0
    with open(target, "wb") as out:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD:
                out.close()
                target.unlink(missing_ok=True)
                raise HTTPException(413, "arquivo grande demais")
            out.write(chunk)
    try:
        return _do_restore(target, user, request, db)
    except HTTPException:
        target.unlink(missing_ok=True)  # arquivo inválido não fica na lista
        raise

