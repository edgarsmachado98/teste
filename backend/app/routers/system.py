"""Administração do sistema: backups e relatório por e-mail."""

import re
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import audit, storage
from ..auth import require_role
from ..backup import backup_dir, list_backups, run_backup, sqlite_path
from ..config import settings
from ..database import get_db
from ..models import User
from ..scheduler import get_state, report_period, send_report
from ..timeutil import local_tz
from .reports import _period

router = APIRouter(prefix="/api")


@router.get("/system/status", dependencies=[Depends(require_role("gestor"))])
def status():
    today = datetime.now(local_tz()).date()
    next_period = report_period(today, settings.report_frequency)
    return {
        "database": "sqlite" if sqlite_path() else "postgresql",
        "backups": list_backups(),
        "backup_last": get_state("backup_last"),
        "backup_hour": settings.backup_hour,
        "backup_keep": settings.backup_keep,
        "backup_copy_dir": settings.backup_copy_dir,
        "email_configured": bool(settings.smtp_host),
        "report_frequency": settings.report_frequency,
        "report_hour": settings.report_hour,
        "report_recipients": settings.report_recipients,
        "report_last": get_state("report_last"),
        "report_last_period": {"start": next_period[0], "end": next_period[1]} if next_period else None,
        "retention_days": settings.retention_days,
        "event_retention_days": settings.event_retention_days,
    }


@router.get("/system/storage", dependencies=[Depends(require_role("gestor"))])
def storage_status():
    if storage.enabled():
        storage.check()
    return storage.status()


@router.post("/system/storage/activate")
def storage_activate(request: Request, user: User = Depends(require_role("admin")), db: Session = Depends(get_db)):
    try:
        storage.activate()
    except OSError as exc:
        raise HTTPException(400, str(exc)) from exc
    audit.record(db, user, "nas_ativado", "sistema", None, settings.storage_nas_path, request)
    db.commit()
    return storage.status()


@router.post("/system/storage/sync")
def storage_sync(request: Request, user: User = Depends(require_role("admin")), db: Session = Depends(get_db)):
    if not storage.enabled():
        raise HTTPException(400, "armazenamento de rede não configurado (STORAGE_NAS_PATH no .env)")
    result = storage.sync_once()
    if not result["online"]:
        raise HTTPException(503, storage.status()["error"] or "armazenamento de rede inacessível")
    audit.record(db, user, "nas_sincronizado", "sistema", None,
                 f"{result['synced_events']} ocorrências, {result['copied_files']} arquivos", request)
    db.commit()
    return {**result, "status": storage.status()}


@router.post("/system/backups", status_code=201)
def backup_now(request: Request, user: User = Depends(require_role("admin")), db: Session = Depends(get_db)):
    try:
        result = run_backup()
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc
    audit.record(db, user, "backup_manual", "sistema", None, result["name"], request)
    db.commit()
    return result


@router.get("/system/backups/{name}")
def download_backup(name: str, request: Request, user: User = Depends(require_role("admin")),
                    db: Session = Depends(get_db)):
    if not re.fullmatch(r"vigia-\d{8}-\d{6}\.db", name) or not (backup_dir() / name).exists():
        raise HTTPException(404, "backup não encontrado")
    audit.record(db, user, "backup_baixado", "sistema", None, name, request)
    db.commit()
    return FileResponse(backup_dir() / name, media_type="application/octet-stream", filename=name)


class ReportEmailIn(BaseModel):
    start: date | None = None
    end: date | None = None
    recipients: list[str] | None = None


@router.post("/system/report-email")
def report_email_now(data: ReportEmailIn, request: Request, user: User = Depends(require_role("gestor")),
                     db: Session = Depends(get_db)):
    start, end = _period(data.start, data.end)
    recipients = [r.strip() for r in (data.recipients or []) if "@" in r] or None
    try:
        size = send_report(start, end, recipients)
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # falha de SMTP
        raise HTTPException(502, f"falha ao enviar o e-mail: {exc}") from exc
    audit.record(db, user, "relatorio_enviado", "relatorio", None,
                 f"{start:%d/%m/%Y} a {end:%d/%m/%Y} para {', '.join(recipients or settings.report_recipients)}", request)
    db.commit()
    return {"sent": True, "size": size}


@router.get("/reports/pdf")
def report_pdf(request: Request, start: date | None = None, end: date | None = None, camera_id: int | None = None,
               user: User = Depends(require_role("tecnico")), db: Session = Depends(get_db)):
    from ..reportpdf import build_report_pdf

    start, end = _period(start, end)
    pdf = build_report_pdf(db, start, end, camera_id)
    audit.record(db, user, "relatorio_gerado", "relatorio", None, f"PDF {start:%d/%m/%Y} a {end:%d/%m/%Y}", request)
    db.commit()
    return Response(pdf, media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="relatorio-vigia-{start:%Y%m%d}-{end:%Y%m%d}.pdf"'})
