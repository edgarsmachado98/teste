"""Envio de alertas por e-mail e WhatsApp. Executado em segundo plano após cada evento."""

import logging
import smtplib
from email.message import EmailMessage
from pathlib import Path

import httpx

from .config import settings
from .timeutil import to_local

log = logging.getLogger("vigia.notifier")

WHATSAPP_API = "https://graph.facebook.com/v21.0"


def build_text(event: dict) -> str:
    return (
        f"🚨 VigIA – {event['message']}\n"
        f"Câmera: {event['camera_name']}\n"
        f"Regra: {event['rule_name'] or '-'}\n"
        f"Severidade: {event['severity']}\n"
        f"Quando: {to_local(event['created_at']):%d/%m/%Y %H:%M:%S}\n"
        f"Painel: {settings.public_url}/#ocorrencia-{event['id']}"
    )


def send_mail(recipients: list[str], subject: str, body: str, image_path: Path | None = None,
              attachment: tuple[str, bytes, str] | None = None) -> None:
    if not (settings.smtp_host and recipients):
        return
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from or settings.smtp_user
    msg["To"] = ", ".join(recipients)
    msg.set_content(body)
    if image_path and image_path.exists():
        msg.add_attachment(image_path.read_bytes(), maintype="image", subtype="jpeg", filename=image_path.name)
    if attachment:
        filename, data, mime = attachment
        maintype, subtype = mime.split("/")
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
        if settings.smtp_tls:
            smtp.starttls()
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(msg)
    log.info("e-mail enviado para %s: %s", recipients, subject)


def send_email(event: dict, image_path: Path | None) -> None:
    subject = f"[VigIA] {event['severity'].upper()} – {event['message']} ({event['camera_name']})"
    send_mail(settings.email_recipients, subject, build_text(event), image_path)


def send_whatsapp_text(text: str) -> None:
    recipients = settings.whatsapp_recipients
    if not (settings.whatsapp_token and settings.whatsapp_phone_id and recipients) or settings.whatsapp_template:
        return
    headers = {"Authorization": f"Bearer {settings.whatsapp_token}"}
    with httpx.Client(timeout=20, headers=headers) as client:
        for to in recipients:
            client.post(
                f"{WHATSAPP_API}/{settings.whatsapp_phone_id}/messages",
                json={"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": text}},
            ).raise_for_status()


def send_whatsapp(event: dict, image_path: Path | None) -> None:
    recipients = settings.whatsapp_recipients
    if not (settings.whatsapp_token and settings.whatsapp_phone_id and recipients):
        return
    headers = {"Authorization": f"Bearer {settings.whatsapp_token}"}
    base = f"{WHATSAPP_API}/{settings.whatsapp_phone_id}"
    with httpx.Client(timeout=20, headers=headers) as client:
        media_id = None
        if image_path and image_path.exists() and not settings.whatsapp_template:
            resp = client.post(
                f"{base}/media",
                data={"messaging_product": "whatsapp", "type": "image/jpeg"},
                files={"file": (image_path.name, image_path.read_bytes(), "image/jpeg")},
            )
            resp.raise_for_status()
            media_id = resp.json()["id"]

        for to in recipients:
            if settings.whatsapp_template:
                # Template aprovado na Meta com 3 variáveis: mensagem, câmera, data/hora
                payload = {
                    "messaging_product": "whatsapp",
                    "to": to,
                    "type": "template",
                    "template": {
                        "name": settings.whatsapp_template,
                        "language": {"code": settings.whatsapp_template_lang},
                        "components": [
                            {
                                "type": "body",
                                "parameters": [
                                    {"type": "text", "text": event["message"]},
                                    {"type": "text", "text": event["camera_name"]},
                                    {"type": "text", "text": f"{to_local(event['created_at']):%d/%m/%Y %H:%M}"},
                                ],
                            },
                        ],
                    },
                }
            elif media_id:
                payload = {
                    "messaging_product": "whatsapp",
                    "to": to,
                    "type": "image",
                    "image": {"id": media_id, "caption": build_text(event)},
                }
            else:
                payload = {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": build_text(event)}}
            client.post(f"{base}/messages", json=payload).raise_for_status()
    log.info("WhatsApp enviado para %s (evento %s)", recipients, event["id"])


def _safely(func, *args) -> None:
    try:
        func(*args)
    except Exception:
        log.exception("falha ao enviar notificação via %s", func.__name__)


def notify(event: dict, image_path: Path | None) -> None:
    for sender in (send_email, send_whatsapp):
        _safely(sender, event, image_path)


def notify_action_assigned(action: dict, email: str) -> None:
    due = f"{action['due_date']:%d/%m/%Y}" if action["due_date"] else "sem prazo"
    body = (
        f"Uma ação do plano de ação foi atribuída a você.\n\n"
        f"Ação: {action['title']}\n"
        f"Prazo: {due}\n"
        f"Ocorrência: {action['event_message'] or '-'}\n"
        f"Atribuída por: {action['created_by'] or '-'}\n\n"
        f"{action['description']}\n\n"
        f"Acesse: {settings.public_url}/#acoes"
    )
    _safely(send_mail, [email], f"[VigIA] Nova ação atribuída: {action['title']}", body)


def notify_camera_health(info: dict) -> None:
    ok = info["health"] == "ok"
    text = (f"{'✅' if ok else '⚠️'} VigIA – câmera {info['camera_name']}: {info['label']}.\n"
            + ("" if ok else "O monitoramento desta área está comprometido até a imagem ser restabelecida."))
    _safely(send_mail, settings.email_recipients, f"[VigIA] Câmera {info['camera_name']}: {info['label']}", text)
    _safely(send_whatsapp_text, text)
