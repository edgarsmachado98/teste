"""Padrões por setor, cadastro de pessoas e identificação/medidas.

Usa o mesmo app e banco de test_api (os módulos de teste compartilham o processo)."""

from tests.test_api import DET, bearer, make_user  # noqa: F401  (configura o ambiente de teste)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def admin(client):
    st = client.get("/api/setup").json()
    if st["needs_setup"]:
        token = client.post("/api/setup", json={"name": "Ana Admin", "email": "ana@fabrica.com",
                                                "password": "senha-forte-1"}).json()["token"]
    else:
        token = client.post("/api/auth/login", json={"email": "ana@fabrica.com", "password": "senha-forte-1"}).json()["token"]
    return bearer(token)


def sector_payload(unit_id, **kw):
    base = {"unit_id": unit_id, "name": "Solda", "required_ppe": ["helmet", "mask"],
            "delivery_ppe": ["Botina", " "], "ppe_severity": "alta",
            "behaviors": {"restricted_zone": {"enabled": True, "severity": "critica"},
                          "max_people": {"enabled": True, "max": 2, "severity": "alta"},
                          "fire_smoke": {"enabled": False}}}
    return {**base, **kw}


def test_sector_standards_generate_rules(client, admin):
    units = client.get("/api/units", headers=admin).json()
    assert units, "unidade padrão criada na inicialização"
    unit_id = units[0]["id"]
    templates = client.get("/api/sectors/templates", headers=admin).json()
    assert {t["id"] for t in templates} >= {"soldagem", "prensas", "docas"}

    resp = client.post("/api/sectors", headers=admin, json=sector_payload(unit_id))
    assert resp.status_code == 201, resp.text
    sector = resp.json()["sector"]
    assert sector["delivery_ppe"] == ["Botina"] and sector["version"] == 1
    assert client.post("/api/sectors", headers=admin, json=sector_payload(unit_id)).status_code == 409

    # câmeras no setor recebem as regras automaticamente
    c1 = client.post("/api/cameras", headers=admin, json={"name": "Célula 3", "source": "0", "sector_id": sector["id"]}).json()
    c2 = client.post("/api/cameras", headers=admin, json={"name": "Célula 4", "source": "1", "sector_id": sector["id"]}).json()
    rules = [r for r in client.get("/api/rules", headers=admin).json() if r["sector_id"] == sector["id"]]
    assert len(rules) == 6  # 3 tipos × 2 câmeras
    zone_rules = [r for r in rules if r["type"] == "restricted_zone"]
    assert all(not r["enabled"] for r in zone_rules)  # sem zona desenhada: desativada
    ppe = next(r for r in rules if r["type"] == "ppe_missing" and r["camera_id"] == c1["id"])
    assert ppe["params"] == {"required": ["helmet", "mask"]}

    # o técnico desenha a zona e ajusta a duração; a regra manual não é tocada
    zr = next(r for r in zone_rules if r["camera_id"] == c1["id"])
    client.put(f"/api/rules/{zr['id']}", headers=admin, json={**zr, "zone": [[0, 0], [0.5, 0], [0.5, 1]],
                                                             "enabled": True, "min_duration": 5})
    manual = client.post("/api/rules", headers=admin, json={"camera_id": c1["id"], "name": "Manual", "type": "fire_smoke"}).json()

    # prévia não grava nada
    new = sector_payload(unit_id, required_ppe=["helmet", "mask", "gloves"],
                         behaviors={"restricted_zone": {"enabled": True, "severity": "critica"},
                                    "max_people": {"enabled": False}, "fire_smoke": {"enabled": True, "severity": "critica"}})
    prev = client.post(f"/api/sectors/{sector['id']}/preview", headers=admin, json=new).json()
    assert len(prev["created"]) == 2 and len(prev["removed"]) == 2 and prev["pending_zone"] == ["Célula 4"]
    assert len([r for r in client.get("/api/rules", headers=admin).json() if r["sector_id"] == sector["id"]]) == 6

    # salvar aplica: nova versão, zona e duração preservadas
    saved = client.put(f"/api/sectors/{sector['id']}", headers=admin, json=new).json()
    assert saved["sector"]["version"] == 2 and len(saved["applied"]["created"]) == 2
    rules = {(r["camera_id"], r["type"]): r for r in client.get("/api/rules", headers=admin).json()
             if r["sector_id"] == sector["id"]}
    assert (c1["id"], "max_people") not in rules and (c1["id"], "fire_smoke") in rules
    kept = rules[(c1["id"], "restricted_zone")]
    assert kept["zone"] and kept["enabled"] and kept["min_duration"] == 5
    assert rules[(c1["id"], "ppe_missing")]["params"]["required"] == ["helmet", "mask", "gloves"]
    assert any(r["id"] == manual["id"] for r in client.get("/api/rules", headers=admin).json())

    # câmera sai do setor: regras geradas removidas
    client.put(f"/api/cameras/{c2['id']}", headers=admin, json={**c2, "sector_id": None})
    assert not [r for r in client.get(f"/api/rules?camera_id={c2['id']}", headers=admin).json()]
    listed = next(s for s in client.get("/api/sectors", headers=admin).json() if s["id"] == sector["id"])
    assert listed["cameras"] == 1 and listed["rules"] == 3

    # permissões
    _, operador = make_user(client, admin, "op-setor@fabrica.com", "operador")
    assert client.put(f"/api/sectors/{sector['id']}", headers=operador, json=new).status_code == 403
