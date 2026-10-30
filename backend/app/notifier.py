"""Envio de alertas por e-mail e WhatsApp. Executado em segundo plano após cada evento."""

import logging
import smtplib
from email.message import EmailMessage
from pathlib import Path

import httpx

from .config import settings

log = logging.getLogger("vigia.notifier")

WHATSAPP_API = "https://graph.facebook.com/v21.0"


def build_text(event: dict) -> str:
    return (
        f"🚨 VigIA – {event['message']}\n"
        f"Câmera: {event['camera_name']}\n"
        f"Regra: {event['rule_name'] or '-'}\n"
        f"Severidade: {event['severity']}\n"
        f"Quando: {event['created_at']:%d/%m/%Y %H:%M:%S} (UTC)\n"
        f"Painel: {settings.public_url}/#evento-{event['id']}"
    )


def send_email(event: dict, image_path: Path | None) -> None:
    recipients = settings.email_recipients
    if not (settings.smtp_host and recipients):
        return
    msg = EmailMessage()
    msg["Subject"] = f"[VigIA] {event['severity'].upper()} – {event['message']} ({event['camera_name']})"
    msg["From"] = settings.smtp_from or settings.smtp_user
    msg["To"] = ", ".join(recipients)
    msg.set_content(build_text(event))
    if image_path and image_path.exists():
        msg.add_attachment(image_path.read_bytes(), maintype="image", subtype="jpeg", filename=image_path.name)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
        if settings.smtp_tls:
            smtp.starttls()
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(msg)
    log.info("e-mail enviado para %s (evento %s)", recipients, event["id"])


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
                                    {"type": "text", "text": f"{event['created_at']:%d/%m/%Y %H:%M}"},
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


def notify(event: dict, image_path: Path | None) -> None:
    for sender in (send_email, send_whatsapp):
        try:
            sender(event, image_path)
        except Exception:
            log.exception("falha ao enviar alerta via %s", sender.__name__)
