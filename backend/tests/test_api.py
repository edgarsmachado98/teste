import json
import os
import tempfile
from datetime import date, timedelta

tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{tmp}/test.db"
os.environ["EVIDENCE_DIR"] = f"{tmp}/evidencias"
os.environ["DETECTOR_API_KEY"] = "chave-teste"
os.environ["CAMERA_OFFLINE_AFTER"] = "0"
os.environ["BACKUP_DIR"] = f"{tmp}/backups"
os.environ["BACKUP_KEEP"] = "2"
os.environ["REPORT_FREQUENCY"] = "mensal"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.health import check_offline_cameras  # noqa: E402
from app.main import app  # noqa: E402

DET = {"X-Detector-Key": "chave-teste"}


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def admin(client):
    assert client.get("/api/setup").json() == {"needs_setup": True}
    resp = client.post("/api/setup", json={"name": "Ana Admin", "email": "ana@fabrica.com", "password": "senha-forte-1"})
    assert resp.status_code == 201
    assert client.get("/api/setup").json() == {"needs_setup": False}
    # segunda configuração é bloqueada
    assert client.post("/api/setup", json={"name": "X", "email": "x@x.com", "password": "12345678"}).status_code == 409
    return bearer(resp.json()["token"])


def make_user(client, admin, email, role):
    resp = client.post("/api/users", headers=admin,
                       json={"name": email.split("@")[0], "email": email, "role": role, "password": "senha-123456"})
    assert resp.status_code == 201, resp.text
    login = client.post("/api/auth/login", json={"email": email, "password": "senha-123456"})
    return resp.json()["id"], bearer(login.json()["token"])


def test_auth_and_roles(client, admin):
    assert client.get("/api/cameras").status_code == 401
    assert client.post("/api/auth/login", json={"email": "ana@fabrica.com", "password": "errada"}).status_code == 401

    _, operador = make_user(client, admin, "op@fabrica.com", "operador")
    assert client.get("/api/auth/me", headers=operador).json()["role"] == "operador"
    assert client.get("/api/cameras", headers=operador).status_code == 200
    assert client.post("/api/cameras", headers=operador, json={"name": "x", "source": "0"}).status_code == 403
    assert client.post("/api/users", headers=operador,
                       json={"name": "x", "email": "y@y.com", "password": "12345678"}).status_code == 403
    assert client.get("/api/audit", headers=operador).status_code == 403

    # não é possível remover o último administrador
    me = client.get("/api/auth/me", headers=admin).json()
    resp = client.put(f"/api/users/{me['id']}", headers=admin,
                      json={"name": me["name"], "email": me["email"], "role": "gestor", "active": True})
    assert resp.status_code == 400

    # troca de senha e logout
    assert client.put("/api/auth/password", headers=operador,
                      json={"current_password": "senha-123456", "new_password": "nova-senha-99"}).status_code == 204
    assert client.post("/api/auth/logout", headers=operador).status_code == 204
    assert client.get("/api/auth/me", headers=operador).status_code == 401


def test_occurrence_workflow(client, admin):
    tecnico_id, tecnico = make_user(client, admin, "tec@fabrica.com", "tecnico")
    resp_id, responsavel = make_user(client, admin, "manut@fabrica.com", "operador")

    cam = client.post("/api/cameras", headers=tecnico, json={"name": "Prensa 1", "location": "Galpão A",
                                                             "source": "rtsp://u:segredo@10.0.0.1/s"}).json()
    rule = client.post("/api/rules", headers=tecnico, json={
        "camera_id": cam["id"], "name": "Capacete", "type": "ppe_missing", "params": {"required": ["helmet"]}}).json()

    with client.websocket_connect("/ws?token=" + admin["Authorization"][7:]) as ws:
        resp = client.post("/api/detector/events", headers=DET,
                           data={"camera_id": cam["id"], "rule_id": rule["id"], "message": "1 pessoa(s) sem capacete",
                                 "boxes": json.dumps([[0.4, 0.3, 0.6, 0.9]])},
                           files={"snapshot": ("e.jpg", b"\xff\xd8fake", "image/jpeg")})
        assert resp.status_code == 201
        assert ws.receive_json()["kind"] == "event"
    event_id = resp.json()["id"]
    assert client.get(f"/api/events/{event_id}/image", headers=admin).content == b"\xff\xd8fake"

    # plano de ação: criar confirma a ocorrência automaticamente
    action = client.post("/api/actions", headers=tecnico, json={
        "event_id": event_id, "title": "Reforçar DDS sobre capacete", "responsible_id": resp_id,
        "due_date": str(date.today() - timedelta(days=1))}).json()
    assert action["overdue"] is True
    detail = client.get(f"/api/events/{event_id}", headers=admin).json()
    assert detail["status"] == "confirmada" and detail["open_actions"] == 1

    # não encerra com ação aberta
    assert client.patch(f"/api/events/{event_id}", headers=tecnico, json={"status": "encerrada"}).status_code == 400
    # responsável (operador) só conclui a própria ação, e precisa descrever o que fez
    assert client.patch(f"/api/actions/{action['id']}", headers=responsavel,
                        json={"title": "outro"}).status_code == 403
    assert client.patch(f"/api/actions/{action['id']}", headers=responsavel,
                        json={"status": "concluida"}).status_code == 400
    done = client.patch(f"/api/actions/{action['id']}", headers=responsavel,
                        json={"status": "concluida", "completion_notes": "DDS feito com o turno A"})
    assert done.status_code == 200 and done.json()["status"] == "concluida"
    mine = client.get("/api/actions?mine=true", headers=responsavel).json()
    assert [a["id"] for a in mine] == [action["id"]]

    upd = client.patch(f"/api/events/{event_id}", headers=tecnico,
                       json={"classification": "ato_inseguro", "status": "encerrada", "notes": "Tratado"})
    assert upd.status_code == 200 and upd.json()["status"] == "encerrada"
    history = client.get(f"/api/events/{event_id}", headers=admin).json()["history"]
    assert [h["user_name"] for h in history] == ["tec", "manut", "tec"]

    # senha da câmera não vai para a auditoria
    audit = client.get("/api/audit?entity=camera", headers=admin).json()
    assert audit and all("segredo" not in a["details"] for a in audit)

    # falso alarme em outra ocorrência entra na taxa
    resp = client.post("/api/detector/events", headers=DET,
                       data={"camera_id": cam["id"], "rule_id": rule["id"], "message": "falso"})
    client.patch(f"/api/events/{resp.json()['id']}", headers=tecnico, json={"status": "descartada"})

    # estatísticas de conformidade enviadas pelo detector
    client.post("/api/detector/stats", headers=DET,
                json={"camera_id": cam["id"], "items": [{"rule_id": rule["id"], "observed": 100, "violations": 8}]})

    summary = client.get("/api/reports/summary", headers=admin).json()
    assert summary["totals"]["deviations"] == 1 and summary["totals"]["discarded"] == 1
    assert summary["totals"]["false_alarm_rate"] == 0.5
    assert summary["compliance"]["rate"] == 0.92
    assert summary["compliance"]["by_camera"][0]["camera"] == "Prensa 1"
    assert summary["actions"]["completed_in_period"] == 1 and summary["actions"]["on_time_rate"] == 0.0
    assert sum(d["count"] for d in summary["by_day"]) == 1
    assert sum(s["count"] for s in summary["by_shift"]) == 1

    heat = client.get(f"/api/reports/heatmap?camera_id={cam['id']}", headers=admin).json()
    assert heat["points"] == [[0.5, 0.9]]


def test_camera_health(client, admin):
    cam = client.post("/api/cameras", headers=admin, json={"name": "Doca 2", "source": "0"}).json()

    def frame(health):
        return client.post(f"/api/detector/cameras/{cam['id']}/frame", headers=DET, data={"health": health},
                           files={"frame": ("f.jpg", b"frame", "image/jpeg")})

    assert frame("ok").status_code == 204
    assert client.get(f"/api/cameras/{cam['id']}/frame", headers=admin).content == b"frame"
    frame("obstruida")
    cams = {c["id"]: c for c in client.get("/api/cameras", headers=admin).json()}
    assert cams[cam["id"]]["health"] == "obstruida"

    import asyncio
    asyncio.run(check_offline_cameras())  # CAMERA_OFFLINE_AFTER=0 nos testes
    cams = {c["id"]: c for c in client.get("/api/cameras", headers=admin).json()}
    assert cams[cam["id"]]["health"] == "offline"
    log = client.get(f"/api/audit?entity=camera&entity_id={cam['id']}", headers=admin).json()
    assert {"lente obstruída ou desfocada", "sem sinal"} <= {a["details"].split(": ")[1] for a in log
                                                            if a["action"] == "camera_saude"}


def test_static_pages(client):
    assert client.get("/").status_code == 200


def test_retention_keeps_records_but_drops_images(client, admin):
    from datetime import datetime, timedelta, timezone

    from app.common import EVIDENCE_DIR
    from app.database import SessionLocal
    from app.main import purge_old_data
    from app.models import Event

    cam = client.post("/api/cameras", headers=admin, json={"name": "Antiga", "source": "0"}).json()
    rule = client.post("/api/rules", headers=admin, json={"camera_id": cam["id"], "name": "Z", "type": "restricted_zone"}).json()
    ev = client.post("/api/detector/events", headers=DET, data={"camera_id": cam["id"], "rule_id": rule["id"], "message": "velho"},
                     files={"snapshot": ("e.jpg", b"img", "image/jpeg")}).json()
    with SessionLocal() as db:
        event = db.get(Event, ev["id"])
        image = EVIDENCE_DIR / event.image_file
        event.created_at = datetime.now(timezone.utc) - timedelta(days=40)
        db.commit()
    assert image.exists()
    purge_old_data()
    with SessionLocal() as db:
        event = db.get(Event, ev["id"])
        assert event is not None and event.image_file is None
    assert not image.exists()


def test_clip_upload_and_retention(client, admin):
    from datetime import datetime, timedelta, timezone

    from app.common import EVIDENCE_DIR
    from app.database import SessionLocal
    from app.main import purge_old_data
    from app.models import Event

    cam = client.post("/api/cameras", headers=admin, json={"name": "Clipe", "source": "0"}).json()
    rule = client.post("/api/rules", headers=admin, json={"camera_id": cam["id"], "name": "Z", "type": "restricted_zone"}).json()
    ev = client.post("/api/detector/events", headers=DET, data={
        "camera_id": cam["id"], "rule_id": rule["id"], "message": "com clipe", "clip_id": "abc123"}).json()
    assert ev["clip_frames"] is None
    # clipe de ocorrência desconhecida é recusado
    files = [("frames", (f"{i}.jpg", f"q{i}".encode(), "image/jpeg")) for i in range(3)]
    assert client.post("/api/detector/clips/nao-existe", headers=DET, data={"duration": "1"}, files=files).status_code == 404
    assert client.post("/api/detector/clips/abc123", headers=DET, data={"duration": "1.5"}, files=files).status_code == 204

    detail = client.get(f"/api/events/{ev['id']}", headers=admin).json()
    assert detail["clip_frames"] == 3 and detail["clip_duration"] == 1.5
    assert client.get(f"/api/events/{ev['id']}/clip/2", headers=admin).content == b"q2"
    assert client.get(f"/api/events/{ev['id']}/clip/3", headers=admin).status_code == 404
    assert client.get(f"/api/events/{ev['id']}/clip/0").status_code == 401

    with SessionLocal() as db:
        event = db.get(Event, ev["id"])
        folder = EVIDENCE_DIR / event.clip_dir
        event.created_at = datetime.now(timezone.utc) - timedelta(days=40)
        db.commit()
    purge_old_data()
    assert not folder.exists()
    assert client.get(f"/api/events/{ev['id']}", headers=admin).json()["clip_frames"] is None


def test_backup_and_rotation(client, admin):
    import json
    import time
    import zipfile

    from app.backup import backup_dir

    _, gestor = make_user(client, admin, "gestor-bk@fabrica.com", "gestor")
    assert client.post("/api/config/backups", headers=gestor, json={}).status_code == 403
    assert client.get("/api/config", headers=gestor).status_code == 403
    names = []
    for _ in range(3):
        resp = client.post("/api/config/backups", headers=admin, json={})
        assert resp.status_code == 201
        names.append(resp.json()["name"])
        time.sleep(1.1)
    files = sorted(p.name for p in backup_dir().glob("vigia-*.zip"))
    assert files == sorted(names[1:])  # BACKUP_KEEP=2
    with zipfile.ZipFile(backup_dir() / names[-1]) as zf:
        manifest = json.loads(zf.read("manifest.json"))
        assert set(zf.namelist()) == {"vigia.db", "manifest.json"}
    assert manifest["counts"]["users"] >= 1 and manifest["evidence_files"] == 0
    assert client.get(f"/api/config/backups/{names[-1]}", headers=admin).status_code == 200
    assert client.get("/api/config/backups/..%2Fvigia.db", headers=admin).status_code == 404
    assert len(client.get("/api/config", headers=admin).json()["backups"]) == 2
    assert client.delete(f"/api/config/backups/{names[-1]}", headers=admin).status_code == 204
    assert len(client.get("/api/config", headers=admin).json()["backups"]) == 1


def test_report_pdf_and_email(client, admin, monkeypatch):
    from app import notifier

    resp = client.get("/api/reports/pdf", headers=admin)
    assert resp.status_code == 200 and resp.content.startswith(b"%PDF")
    assert len(resp.content) > 3000

    # sem SMTP configurado: erro claro
    assert client.post("/api/system/report-email", headers=admin, json={}).status_code == 400

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
    monkeypatch.setattr(notifier.settings, "alert_emails", "sesmt@fabrica.com")
    resp = client.post("/api/system/report-email", headers=admin, json={"start": "2026-01-01", "end": "2026-01-31"})
    assert resp.status_code == 200, resp.text
    msg = sent[0]
    assert msg["To"] == "sesmt@fabrica.com" and "01/01/2026 a 31/01/2026" in msg["Subject"]
    pdfs = [p for p in msg.iter_attachments() if p.get_content_type() == "application/pdf"]
    assert pdfs and pdfs[0].get_content().startswith(b"%PDF")


def test_scheduler_runs_each_job_once(monkeypatch):
    from datetime import date, datetime

    from app import scheduler
    from app.timeutil import local_tz

    assert scheduler.report_period(date(2026, 3, 1), "mensal") == (date(2026, 2, 1), date(2026, 2, 28))
    assert scheduler.report_period(date(2026, 3, 4), "semanal") == (date(2026, 2, 23), date(2026, 3, 1))
    assert scheduler.report_period(date(2026, 3, 4), "desligado") is None

    calls = []
    monkeypatch.setattr(scheduler, "run_backup", lambda: calls.append("backup"))
    monkeypatch.setattr(scheduler, "send_report", lambda s, e: calls.append(("report", s, e)))
    monkeypatch.setattr(scheduler.settings, "smtp_host", "smtp.teste")
    monkeypatch.setattr(scheduler.settings, "alert_emails", "x@y.com")
    early = datetime(2026, 4, 1, 1, 0, tzinfo=local_tz())
    assert scheduler.run_due_jobs(early) == []  # antes do horário do backup e do relatório
    now = datetime(2026, 4, 1, 8, 0, tzinfo=local_tz())
    assert scheduler.run_due_jobs(now) == ["backup", "report"]
    assert scheduler.run_due_jobs(now) == []  # não repete
    assert calls == ["backup", ("report", date(2026, 3, 1), date(2026, 3, 31))]


def test_network_storage(client, admin, monkeypatch, tmp_path):
    from datetime import datetime, timedelta, timezone

    from app import storage
    from app.common import EVIDENCE_DIR
    from app.database import SessionLocal
    from app.main import purge_old_data
    from app.models import Event

    nas = tmp_path / "nas"
    nas.mkdir()
    monkeypatch.setattr(storage.settings, "storage_nas_path", str(nas))
    monkeypatch.setattr(storage.settings, "storage_mode", "principal")
    monkeypatch.setattr(storage.settings, "storage_local_days", 7)

    _, tecnico = make_user(client, admin, "tec-nas@fabrica.com", "tecnico")
    assert client.get("/api/config", headers=tecnico).status_code == 403
    st = client.get("/api/config", headers=admin).json()["storage"]
    assert st["enabled"] and not st["online"] and "ativado" in st["error"]
    assert not storage.sync_once()["online"]          # sem marcador: não grava nada na pasta
    assert list(nas.iterdir()) == []

    assert client.post("/api/config/storage/activate", headers=admin).json()["online"] is True

    cam = client.post("/api/cameras", headers=admin, json={"name": "NAS cam", "source": "0"}).json()
    rule = client.post("/api/rules", headers=admin, json={"camera_id": cam["id"], "name": "Z", "type": "restricted_zone"}).json()
    ev = client.post("/api/detector/events", headers=DET, files={"snapshot": ("e.jpg", b"foto", "image/jpeg")},
                     data={"camera_id": cam["id"], "rule_id": rule["id"], "message": "nas", "clip_id": "clip-nas"}).json()

    # o clipe ainda não chegou: aguarda (as ocorrências dos testes anteriores são enviadas)
    storage.sync_once()
    with SessionLocal() as db:
        assert db.get(Event, ev["id"]).media_synced_at is None
    files = [("frames", (f"{i}.jpg", f"q{i}".encode(), "image/jpeg")) for i in range(2)]
    client.post("/api/detector/clips/clip-nas", headers=DET, data={"duration": "1"}, files=files)
    result = client.post("/api/config/storage/sync", headers=admin).json()
    assert result["synced_events"] >= 1 and result["copied_files"] >= 3

    with SessionLocal() as db:
        event = db.get(Event, ev["id"])
        image_rel, clip_rel = event.image_file, event.clip_dir
        assert event.media_synced_at is not None
        assert (nas / "evidencias" / image_rel).read_bytes() == b"foto"
        # modo principal: ocorrência com mais de 7 dias sai do disco local
        event.created_at = datetime.now(timezone.utc) - timedelta(days=10)
        db.commit()
    assert storage.sync_once()["freed_events"] >= 1
    assert not (EVIDENCE_DIR / image_rel).exists() and not (EVIDENCE_DIR / clip_rel).exists()
    # ...e o painel continua mostrando, agora a partir do NAS
    assert client.get(f"/api/events/{ev['id']}/image", headers=admin).content == b"foto"
    assert client.get(f"/api/events/{ev['id']}/clip/1", headers=admin).content == b"q1"

    # NAS cai: imagem indisponível (503) e a retenção deixa a exclusão pendente
    offline = tmp_path / "nas-desligado"
    nas.rename(offline)
    assert not storage.check()
    assert client.get(f"/api/events/{ev['id']}/image", headers=admin).status_code == 503
    with SessionLocal() as db:
        db.get(Event, ev["id"]).created_at = datetime.now(timezone.utc) - timedelta(days=40)
        db.commit()
    purge_old_data()
    assert storage.status()["pending_deletions"] == 2
    assert (offline / "evidencias" / image_rel).exists()

    # NAS volta: exclusões pendentes são feitas (LGPD)
    offline.rename(nas)
    assert storage.sync_once()["deleted"] == 2
    assert not (nas / "evidencias" / image_rel).exists() and not (nas / "evidencias" / clip_rel).exists()

    # backup também vai para o NAS
    backup = client.post("/api/config/backups", headers=admin, json={}).json()
    assert (nas / "backups" / backup["name"]).exists()



def test_config_settings_and_nas_probe(client, admin, tmp_path):
    from app import settings_store
    from app.config import settings
    from app.database import SessionLocal
    from app.models import SystemState

    nas = tmp_path / "nas2"
    nas.mkdir()
    probe = client.post("/api/config/storage/test", headers=admin,
                        json={"path": str(nas), "user": "vigia", "password": "x"}).json()
    assert probe["ok"] and probe["writable"] and not probe["activated"]
    bad = client.post("/api/config/storage/test", headers=admin, json={"path": str(tmp_path / "nao-existe")}).json()
    assert not bad["ok"] and "não encontrada" in bad["message"]

    resp = client.put("/api/config", headers=admin, json={"values": {
        "storage_nas_path": str(nas), "storage_nas_user": "vigia", "storage_nas_password": "s3nh@-do-nas",
        "storage_mode": "principal", "backup_hour": 3}})
    assert resp.status_code == 200, resp.text
    values = resp.json()["values"]
    assert values["storage_nas_password"] == {"set": True, "source": "painel"}  # senha nunca volta para a tela
    assert values["storage_mode"]["value"] == "principal" and settings.backup_hour == 3
    assert settings.storage_nas_password == "s3nh@-do-nas"
    with SessionLocal() as db:
        stored = db.get(SystemState, "cfg:storage_nas_password").value
    assert stored.startswith("enc:") and "s3nh@" not in stored  # criptografada no banco

    # senha vazia mantém a atual; valores inválidos são recusados
    client.put("/api/config", headers=admin, json={"values": {"storage_nas_password": ""}})
    assert settings.storage_nas_password == "s3nh@-do-nas"
    assert client.put("/api/config", headers=admin, json={"values": {"backup_hour": 30}}).status_code == 400
    assert client.put("/api/config", headers=admin, json={"values": {"storage_mode": "x"}}).status_code == 400
    assert client.put("/api/config", headers=admin, json={"values": {"database_url": "x"}}).status_code == 400

    # voltar ao .env
    client.put("/api/config", headers=admin, json={"reset": list(settings_store.FIELDS)})
    assert settings.storage_nas_path == "" and settings.backup_hour == 2
    audit = client.get("/api/audit?entity=sistema", headers=admin).json()
    assert any("senha do NAS" in a["details"] for a in audit)
    assert all("s3nh@" not in a["details"] for a in audit)


def test_restore(client, admin, tmp_path):
    import io
    import zipfile

    from app.backup import backup_dir
    from app.common import EVIDENCE_DIR

    cam = client.post("/api/cameras", headers=admin, json={"name": "Antes do backup", "source": "0"}).json()
    rule = client.post("/api/rules", headers=admin, json={"camera_id": cam["id"], "name": "Z", "type": "restricted_zone"}).json()
    ev = client.post("/api/detector/events", headers=DET, files={"snapshot": ("e.jpg", b"evidencia-original", "image/jpeg")},
                     data={"camera_id": cam["id"], "rule_id": rule["id"], "message": "antes"}).json()
    full = client.post("/api/config/backups", headers=admin, json={"include_evidence": True}).json()
    assert full["evidence_files"] >= 1 and full["kind"] == "completo"

    # mudanças depois do backup
    client.post("/api/cameras", headers=admin, json={"name": "Depois do backup", "source": "0"})
    image = client.get(f"/api/events/{ev['id']}", headers=admin).json()
    from app.database import SessionLocal
    from app.models import Event
    with SessionLocal() as db:
        image_file = EVIDENCE_DIR / db.get(Event, ev["id"]).image_file
    image_file.unlink()
    assert image["id"] == ev["id"]

    # confirmação obrigatória
    assert client.post("/api/config/restore", headers=admin, json={"name": full["name"], "confirm": "sim"}).status_code == 400
    result = client.post("/api/config/restore", headers=admin, json={"name": full["name"], "confirm": "RESTAURAR"}).json()
    assert result["evidence_files"] >= 1 and "antes-restauracao" in result["safety_backup"]

    # sessão do admin existia no backup, então continua válida; dados voltaram
    names = [c["name"] for c in client.get("/api/cameras", headers=admin).json()]
    assert "Antes do backup" in names and "Depois do backup" not in names
    assert client.get(f"/api/events/{ev['id']}/image", headers=admin).content == b"evidencia-original"
    assert any(a["action"] == "sistema_restaurado" for a in client.get("/api/audit?entity=sistema", headers=admin).json())

    # desfazer: restaurar o backup de segurança traz a câmera de volta
    client.post("/api/config/restore", headers=admin, json={"name": result["safety_backup"], "confirm": "RESTAURAR"})
    assert "Depois do backup" in [c["name"] for c in client.get("/api/cameras", headers=admin).json()]

    # envio de arquivo: válido
    data = (backup_dir() / full["name"]).read_bytes()
    up = client.post("/api/config/restore/upload?confirm=RESTAURAR", headers=admin,
                     files={"file": ("meu-backup.zip", data, "application/zip")})
    assert up.status_code == 200, up.text
    assert "Depois do backup" not in [c["name"] for c in client.get("/api/cameras", headers=admin).json()]

    # arquivos inválidos são recusados e não ficam na lista
    before = len(list(backup_dir().iterdir()))
    bad = client.post("/api/config/restore/upload?confirm=RESTAURAR", headers=admin,
                      files={"file": ("x.zip", b"isto nao e zip", "application/zip")})
    assert bad.status_code == 400 and "inválido" in bad.json()["detail"]
    evil = io.BytesIO()
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("vigia.db", data[:10])
        zf.writestr("../../fora.txt", "x")
    bad = client.post("/api/config/restore/upload?confirm=RESTAURAR", headers=admin,
                      files={"file": ("evil.zip", evil.getvalue(), "application/zip")})
    assert bad.status_code == 400 and "não permitidos" in bad.json()["detail"]
    notdb = io.BytesIO()
    with zipfile.ZipFile(notdb, "w") as zf:
        zf.writestr("vigia.db", b"nao sou um banco")
    bad = client.post("/api/config/restore/upload?confirm=RESTAURAR", headers=admin,
                      files={"file": ("n.zip", notdb.getvalue(), "application/zip")})
    assert bad.status_code == 400
    assert len(list(backup_dir().iterdir())) == before
    assert client.get("/api/auth/me", headers=admin).status_code == 200  # sistema segue funcionando


def test_parameters_usage_and_alerts(client, admin, monkeypatch):
    from datetime import datetime, timedelta, timezone

    from app import notifier, usage
    from app.config import settings
    from app.database import SessionLocal
    from app.main import purge_old_data
    from app.models import AuditLog

    # parâmetros de retenção e alerta pela tela
    resp = client.put("/api/config", headers=admin, json={"values": {
        "audit_retention_days": 30, "alert_emails": "sesmt@fab.com; gerente@fab.com",
        "alert_min_severity_whatsapp": "critica", "whatsapp_to": "+55 (11) 99999-8888", "smtp_tls": "false",
        "usage_alert_disk": 80}})
    assert resp.status_code == 200, resp.text
    assert settings.alert_emails == "sesmt@fab.com, gerente@fab.com"
    assert settings.whatsapp_to == "5511999998888" and settings.smtp_tls is False
    assert client.put("/api/config", headers=admin, json={"values": {"alert_emails": "invalido"}}).status_code == 400
    assert client.put("/api/config", headers=admin, json={"values": {"whatsapp_to": "123"}}).status_code == 400

    # retenção da auditoria
    with SessionLocal() as db:
        db.add(AuditLog(user_name="antigo", action="login", created_at=datetime.now(timezone.utc) - timedelta(days=40)))
        db.commit()
    purge_old_data()
    assert not [a for a in client.get("/api/audit?user_name=antigo", headers=admin).json()]

    # severidade mínima por canal
    sent = []
    monkeypatch.setattr(notifier, "send_email", lambda e, i: sent.append(("email", e["severity"])))
    monkeypatch.setattr(notifier, "send_whatsapp", lambda e, i, r=None: sent.append(("whatsapp", e["severity"])))
    notifier.notify({"severity": "alta"}, None)
    notifier.notify({"severity": "critica"}, None)
    assert sent == [("email", "alta"), ("email", "critica"), ("whatsapp", "critica")]

    # uso do sistema
    data = client.get("/api/config/usage", headers=admin).json()
    assert 0 < data["disk_percent"] <= 100 and data["limits"]["disk"] == 80
    assert data["cpu_percent"] is not None and data["memory_percent"] is not None

    # alerta só após o tempo contínuo e volta com histerese
    monkeypatch.setattr(settings, "usage_alert_minutes", 5)
    assert usage.evaluate({"disk_percent": 85}, 0) == []
    assert usage.evaluate({"disk_percent": 85}, 299) == []
    assert usage.evaluate({"disk_percent": 86}, 301) == [("disk", True, 86)]
    assert usage.evaluate({"disk_percent": 86}, 400) == []          # não repete
    assert usage.evaluate({"disk_percent": 78}, 401) == []          # dentro da histerese
    assert usage.evaluate({"disk_percent": 70}, 402) == [("disk", False, 70)]

    # mensagem de teste: sem SMTP, erro claro
    monkeypatch.setattr(settings, "smtp_host", "")
    resp = client.post("/api/config/alerts/test", headers=admin, json={"channel": "email"})
    assert resp.status_code == 400 and "SMTP" in resp.json()["detail"]
    client.put("/api/config", headers=admin, json={"reset": ["audit_retention_days", "alert_emails",
               "alert_min_severity_whatsapp", "whatsapp_to", "smtp_tls", "usage_alert_disk"]})
