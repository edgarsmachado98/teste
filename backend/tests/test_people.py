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


VALID_CPFS = ["123.456.789-09", "529.982.247-25", "111.444.777-35", "390.533.447-05"]


def person_payload(unit_id, **kw):
    return {"unit_id": unit_id, "name": "Bruno Henrique Costa", "cpf": VALID_CPFS[0], "registration": "005177",
            "role": "Soldador MIG", "shift": "Turno B", "badge_code": "0417", **kw}


def test_people_registry(client, admin, tmp_path):
    from app.models import Person
    from app.database import SessionLocal
    from app.people import people_dir

    unit_id = client.get("/api/units", headers=admin).json()[0]["id"]
    sector = next(s for s in client.get("/api/sectors", headers=admin).json() if s["name"] == "Solda")
    _, tecnico = make_user(client, admin, "tec-pessoas@fabrica.com", "tecnico")

    # validações
    assert client.post("/api/people", headers=admin, json=person_payload(unit_id, cpf="123.456.789-00")).status_code == 422
    assert client.post("/api/people", headers=tecnico, json=person_payload(unit_id)).status_code == 403
    resp = client.post("/api/people", headers=admin, json=person_payload(unit_id, sector_id=sector["id"]))
    assert resp.status_code == 201, resp.text
    person = resp.json()
    assert person["cpf"] == "123.456.789-09" and person["sector"] == "Solda"
    dup = client.post("/api/people", headers=admin, json=person_payload(unit_id, registration="X1", badge_code="X1"))
    assert dup.status_code == 409 and "CPF" in dup.json()["detail"]
    dup = client.post("/api/people", headers=admin, json=person_payload(unit_id, cpf=VALID_CPFS[1], registration="X2"))
    assert dup.status_code == 409 and "colete" in dup.json()["detail"]

    # técnico vê CPF mascarado; gestor/admin vê completo (e fica na auditoria)
    listed = client.get("/api/people?q=bruno", headers=tecnico).json()
    assert listed["total"] == 1 and listed["items"][0]["cpf"] == "***.456.789-**"
    assert client.get(f"/api/people/{person['id']}", headers=tecnico).json()["cpf"] == "***.456.789-**"
    detail = client.get(f"/api/people/{person['id']}", headers=admin).json()
    assert detail["cpf"] == "123.456.789-09" and detail["required_ppe"] == ["capacete", "máscara", "luvas"]
    assert client.get("/api/people?q=0417", headers=tecnico).json()["total"] == 1   # pelo número do colete
    assert client.get("/api/people?q=456789", headers=tecnico).json()["total"] == 1  # por parte do CPF

    # foto exige ciência registrada, aceita só imagem
    jpg = b"\xff\xd8\xff\xe0" + b"0" * 100
    assert client.post(f"/api/people/{person['id']}/photo", headers=admin,
                       files={"photo": ("f.jpg", jpg, "image/jpeg")}).status_code == 400
    client.put(f"/api/people/{person['id']}", headers=admin, json=person_payload(unit_id, sector_id=sector["id"], photo_consent=True))
    assert client.post(f"/api/people/{person['id']}/photo", headers=admin,
                       files={"photo": ("f.txt", b"texto", "text/plain")}).status_code == 400
    assert client.post(f"/api/people/{person['id']}/photo", headers=admin,
                       files={"photo": ("f.jpg", jpg, "image/jpeg")}).status_code == 200
    assert client.get(f"/api/people/{person['id']}/photo", headers=tecnico).content == jpg
    detail = client.get(f"/api/people/{person['id']}", headers=admin).json()
    assert detail["has_photo"] and detail["photo_consent_on"]

    # EPI entregue com validade próxima gera alerta
    from datetime import date, timedelta
    client.post(f"/api/people/{person['id']}/deliveries", headers=tecnico, json={
        "item": "Máscara de solda", "ca": "38422", "delivered_on": str(date.today() - timedelta(days=300)),
        "valid_until": str(date.today() + timedelta(days=12))})
    item = client.get("/api/people?q=bruno", headers=tecnico).json()["items"][0]
    assert item["ppe_alert"] == "Máscara de solda vence em 12 dia(s)"
    assert client.get("/api/people/summary", headers=tecnico).json()["ppe_expiring"] == 1

    # desligamento apaga a foto (minimização)
    with SessionLocal() as db:
        photo = db.get(Person, person["id"]).photo_file
    client.put(f"/api/people/{person['id']}", headers=admin, json=person_payload(unit_id, status="desligado", photo_consent=True))
    assert not (people_dir() / photo).exists()
    assert client.get("/api/people?q=bruno", headers=tecnico).json()["total"] == 0  # padrão: ativos e afastados
    client.put(f"/api/people/{person['id']}", headers=admin, json=person_payload(unit_id, sector_id=sector["id"], photo_consent=True))

    # importação de planilha (cp1252, ponto e vírgula), com erros por linha
    csv_text = ("Nome;CPF;Matrícula;Setor;Função;Turno;Vínculo;Colete\n"
                f"Camila Duarte;{VALID_CPFS[2]};003390;Solda;Conferente;Turno C;CLT;0501\n"
                f"Bruno Henrique Costa;{VALID_CPFS[0]};005177;Solda;Soldador TIG;Turno B;CLT;0417\n"
                "Sem CPF Válido;123.456.789-00;9;Solda;X;Turno A;CLT;\n"
                f"Fábio Martins;{VALID_CPFS[3]};T-0187;Inexistente;Eletricista;Turno A;terceirizado;\n")
    res = client.post("/api/people/import", headers=admin,
                      files={"file": ("rh.csv", csv_text.encode("cp1252"), "text/csv")}).json()
    assert res["created"] == 1 and res["updated"] == 1, res
    assert [e["line"] for e in res["errors"]] == [4, 5]
    assert "CPF inválido" in res["errors"][0]["message"] and "Inexistente" in res["errors"][1]["message"]
    bruno = client.get(f"/api/people/{person['id']}", headers=admin).json()
    assert bruno["role"] == "Soldador TIG"
    assert client.get("/api/people/import/template", headers=admin).text.startswith("﻿nome;cpf")
