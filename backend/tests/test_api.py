import os
import tempfile

tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{tmp}/test.db"
os.environ["EVIDENCE_DIR"] = f"{tmp}/evidencias"
os.environ["DETECTOR_API_KEY"] = "chave-teste"
os.environ["API_TOKEN"] = "token-teste"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

AUTH = {"Authorization": "Bearer token-teste"}
DET = {"X-Detector-Key": "chave-teste"}


def test_full_flow():
    with TestClient(app) as client:
        assert client.get("/api/cameras").status_code == 401

        cam = client.post("/api/cameras", json={"name": "Prensa 1", "source": "video.mp4"}, headers=AUTH).json()
        bad = client.post("/api/rules", headers=AUTH, json={
            "camera_id": cam["id"], "name": "x", "type": "ppe_missing", "zone": [[0, 0], [1, 1]]})
        assert bad.status_code == 422

        rule = client.post("/api/rules", headers=AUTH, json={
            "camera_id": cam["id"], "name": "Capacete obrigatório", "type": "ppe_missing",
            "params": {"required": ["helmet"]}, "zone": [[0, 0], [1, 0], [1, 1]]}).json()

        assert client.get("/api/detector/config").status_code == 401
        config = client.get("/api/detector/config", headers=DET).json()
        assert config[0]["rules"][0]["id"] == rule["id"]

        with client.websocket_connect("/ws?token=token-teste") as ws:
            resp = client.post("/api/detector/events", headers=DET,
                               data={"camera_id": cam["id"], "rule_id": rule["id"], "message": "1 pessoa(s) sem capacete"},
                               files={"snapshot": ("e.jpg", b"\xff\xd8fake", "image/jpeg")})
            assert resp.status_code == 201
            pushed = ws.receive_json()
        assert pushed["event"]["message"] == "1 pessoa(s) sem capacete"
        event_id = resp.json()["id"]

        events = client.get("/api/events", headers=AUTH).json()
        assert events[0]["camera_name"] == "Prensa 1" and events[0]["status"] == "nova"
        assert client.get(f"/api/events/{event_id}/image?token=token-teste").content == b"\xff\xd8fake"

        client.patch(f"/api/events/{event_id}", json={"status": "descartada"}, headers=AUTH)
        assert client.get("/api/events?status=nova", headers=AUTH).json() == []
        assert client.get("/api/stats", headers=AUTH).json()["last_24h"] == {"ppe_missing": 1}

        client.post(f"/api/detector/cameras/{cam['id']}/frame", headers=DET,
                    files={"frame": ("f.jpg", b"frame", "image/jpeg")})
        assert client.get(f"/api/cameras/{cam['id']}/frame", headers=AUTH).content == b"frame"

        assert client.get("/").status_code == 200
