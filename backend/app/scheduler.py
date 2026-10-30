"""Tarefas agendadas: backup diário e relatório periódico por e-mail.

Cada tarefa grava em system_state quando rodou pela última vez, para não repetir após
reinícios e para rodar assim que possível se o computador estava desligado no horário."""

import asyncio
import logging
from datetime import date, datetime, timedelta

from .backup import run_backup, sqlite_path
from .config import settings
from .database import SessionLocal
from .models import SystemState
from .notifier import send_mail
from .timeutil import local_tz

log = logging.getLogger("vigia.scheduler")


def get_state(key: str) -> str:
    with SessionLocal() as db:
        row = db.get(SystemState, key)
        return row.value if row else ""


def set_state(key: str, value: str) -> None:
    with SessionLocal() as db:
        row = db.get(SystemState, key) or SystemState(key=key)
        row.value = value
        db.merge(row)
        db.commit()


def report_period(today: date, frequency: str) -> tuple[date, date] | None:
    """Período do relatório que deve ter sido enviado até hoje: mês ou semana anteriores."""
    if frequency == "mensal":
        end = today.replace(day=1) - timedelta(days=1)
        return end.replace(day=1), end
    if frequency == "semanal":
        end = today - timedelta(days=today.weekday() + 1)  # domingo passado
        return end - timedelta(days=6), end
    return None


def send_report(start: date, end: date, recipients: list[str] | None = None) -> int:
    from .reportpdf import build_report_pdf

    recipients = recipients or settings.report_recipients
    if not settings.smtp_host or not recipients:
        raise RuntimeError("Configure SMTP_HOST e REPORT_EMAILS (ou ALERT_EMAILS) no .env para enviar relatórios.")
    with SessionLocal() as db:
        pdf = build_report_pdf(db, start, end)
    period = f"{start:%d/%m/%Y} a {end:%d/%m/%Y}"
    body = (f"Segue o relatório de segurança e comportamento do período {period}.\n\n"
            f"Para ver fotos, clipes e o detalhe de cada ocorrência, acesse {settings.public_url}/#indicadores\n\n"
            "Mensagem automática do VigIA.")
    company = f" – {settings.company_name}" if settings.company_name else ""
    send_mail(recipients, f"[VigIA] Relatório de segurança{company} – {period}", body,
              attachment=(f"relatorio-vigia-{start:%Y%m%d}-{end:%Y%m%d}.pdf", pdf, "application/pdf"))
    log.info("relatório %s enviado para %s", period, recipients)
    return len(pdf)


def archive_report(start: date, end: date) -> str:
    """Guarda o PDF do período na pasta relatorios/ do NAS (histórico para auditorias)."""
    from . import storage
    from .reportpdf import build_report_pdf

    if not storage.enabled():
        return ""
    with SessionLocal() as db:
        pdf = build_report_pdf(db, start, end)
    return storage.write_to_nas(f"relatorio-vigia-{start:%Y%m%d}-{end:%Y%m%d}.pdf", pdf, "relatorios")


def due_jobs(now: datetime) -> list[str]:
    jobs = []
    if sqlite_path() and now.hour >= settings.backup_hour and get_state("backup_last") != f"{now:%Y-%m-%d}":
        jobs.append("backup")
    period = report_period(now.date(), settings.report_frequency)
    if period and now.hour >= settings.report_hour and get_state("report_last") != f"{period[0]}:{period[1]}":
        jobs.append("report")
    return jobs


def run_due_jobs(now: datetime | None = None) -> list[str]:
    now = now or datetime.now(local_tz())
    done = []
    for job in due_jobs(now):
        try:
            if job == "backup":
                run_backup()  # .zip só com o banco; com evidências apenas sob demanda
                set_state("backup_last", f"{now:%Y-%m-%d}")
            elif job == "report":
                start, end = report_period(now.date(), settings.report_frequency)
                try:
                    archive_report(start, end)
                except OSError as exc:
                    log.error("relatório não arquivado no NAS: %s", exc)
                if settings.smtp_host and settings.report_recipients:
                    send_report(start, end)
                else:
                    log.info("relatório automático não enviado: e-mail não configurado")
                set_state("report_last", f"{start}:{end}")
            done.append(job)
        except Exception:
            log.exception("falha na tarefa agendada %s", job)
    return done


async def scheduler_loop() -> None:
    while True:
        await asyncio.to_thread(run_due_jobs)
        await asyncio.sleep(300)
