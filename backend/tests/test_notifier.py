from datetime import datetime, timezone

from app import notifier

EVENT = {"id": 7, "message": "1 pessoa(s) sem capacete", "camera_name": "Prensa 1", "rule_name": "Capacete",
         "severity": "alta", "created_at": datetime(2026, 1, 1, 12, 30, tzinfo=timezone.utc)}


def test_email_is_sent_with_attachment(monkeypatch, tmp_path):
    sent = []

    class FakeSMTP:
        def __init__(self, *a, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def starttls(self): pass
        def login(self, *a): pass
        def send_message(self, msg): sent.append(msg)

    monkeypatch.setattr(notifier.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(notifier.settings, "smtp_host", "smtp.teste")
    monkeypatch.setattr(notifier.settings, "alert_emails", "a@x.com, b@x.com")
    img = tmp_path / "e.jpg"
    img.write_bytes(b"\xff\xd8")

    notifier.notify(EVENT, img)

    assert len(sent) == 1
    msg = sent[0]
    assert msg["To"] == "a@x.com, b@x.com"
    assert "sem capacete" in msg["Subject"] and "Prensa 1" in msg["Subject"]
    assert [p.get_filename() for p in msg.iter_attachments()] == ["e.jpg"]


def test_nothing_sent_when_not_configured(monkeypatch):
    monkeypatch.setattr(notifier.settings, "smtp_host", "")
    monkeypatch.setattr(notifier.settings, "whatsapp_token", "")
    notifier.notify(EVENT, None)  # não deve levantar erro
