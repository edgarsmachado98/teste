import json
import os
import tempfile
from datetime import date, timedelta

tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{tmp}/test.db"
os.environ["EVIDENCE_DIR"] = f"{tmp}/evidencias"
os.environ["DETECTOR_API_KEY"] = "chave-teste"
os.environ["CAMERA_OFFLINE_AFTER"] = "0"

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
