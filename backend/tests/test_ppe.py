"""Guia EPI: catálogo, estoque com mínimo, entrega com ficha assinada, uniformes, CA e plano de substituição."""

from tests.test_api import bearer, make_user  # noqa: F401  (configura o ambiente de teste)

import base64  # noqa: E402
from datetime import date, timedelta  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

PNG = "data:image/png;base64," + base64.b64encode(
    bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d4944415478da63f8ff"
                  "ff3f0005fe02fea7d6a5e20000000049454e44ae426082")).decode()


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


def test_ppe_module(client, admin):
    today = date.today()
    unit = client.post("/api/units", headers=admin, json={"name": "Planta EPI"}).json()["id"]
    sector = client.post("/api/sectors", headers=admin, json={
        "unit_id": unit, "name": "Caldeiraria", "required_ppe": ["helmet", "glasses"], "delivery_ppe": ["Botina"],
        "ppe_severity": "alta", "behaviors": {}}).json()["sector"]
    person = client.post("/api/people", headers=admin, json={
        "unit_id": unit, "sector_id": sector["id"], "name": "Carla Souza", "cpf": "286.145.923-96",
        "registration": "EPI01", "role": "Caldeireira", "shift": "Turno A"}).json()

    # catálogo
    helmet = client.post("/api/ppe/items", headers=admin, json={
        "name": "Capacete aba frontal", "ppe_type": "helmet", "ca": "CA 31.469", "ca_valid_until": str(today + timedelta(days=20)),
        "replacement_days": 365}).json()
    assert helmet["ca"] == "31469" and helmet["ca_status"] == "vence"
    glasses = client.post("/api/ppe/items", headers=admin, json={
        "name": "Óculos de proteção incolor", "ppe_type": "glasses", "ca": "11268",
        "ca_valid_until": str(today - timedelta(days=5)), "replacement_days": 10}).json()
    shirt = client.post("/api/ppe/items", headers=admin, json={
        "name": "Camisa manga longa", "category": "uniforme", "sizes": ["p", "M", "g", "M"], "replacement_days": 180}).json()
    assert shirt["sizes"] == ["P", "M", "G"] and shirt["ca_status"] == "nao_se_aplica"

    # estoque: entrada, mínimo, ajuste por contagem
    r = client.post("/api/ppe/stock/move", headers=admin, json={"unit_id": unit, "item_id": helmet["id"], "type": "entrada",
                                                               "quantity": 3, "note": "NF 123"})
    assert r.status_code == 200 and r.json()["quantity"] == 3
    client.put("/api/ppe/stock/min", headers=admin, json={"unit_id": unit, "item_id": helmet["id"], "min_quantity": 2})
    client.post("/api/ppe/stock/move", headers=admin, json={"unit_id": unit, "item_id": shirt["id"], "size": "M",
                                                           "type": "entrada", "quantity": 4})
    adj = client.post("/api/ppe/stock/move", headers=admin, json={"unit_id": unit, "item_id": shirt["id"], "size": "m",
                                                                 "type": "ajuste", "quantity": 5, "note": "inventário"}).json()
    assert adj["quantity"] == 5
    stock = client.get("/api/ppe/stock", headers=admin, params={"unit_id": unit}).json()
    sizes = {(row["item"], row["size"]): row for row in stock["rows"]}
    assert ("Camisa manga longa", "G") in sizes and sizes[("Camisa manga longa", "G")]["quantity"] == 0

    # entrega com baixa no estoque; sem saldo é recusada
    body = {"person_id": person["id"], "delivered_on": str(today),
            "items": [{"item_id": helmet["id"]}, {"item_id": shirt["id"], "size": "M", "quantity": 2, "reason": "primeira"}]}
    rec = client.post("/api/ppe/receipts", headers=admin, json=body)
    assert rec.status_code == 201, rec.text
    rec = rec.json()
    assert rec["number"].startswith(f"EPI-{today.year}-") and not rec["signed"]
    assert any("mínimo" in w for w in rec["warnings"])  # capacete: saldo 2, mínimo 2
    helmet_line = next(i for i in rec["items"] if i["item_id"] == helmet["id"])
    assert helmet_line["valid_until"] == str(today + timedelta(days=365)) and helmet_line["ca"] == "31469"
    bad = client.post("/api/ppe/receipts", headers=admin, json={
        "person_id": person["id"], "delivered_on": str(today), "items": [{"item_id": glasses["id"]}]})
    assert bad.status_code == 409 and "estoque insuficiente" in bad.json()["detail"]
    assert client.post("/api/ppe/receipts", headers=admin, json={
        "person_id": person["id"], "delivered_on": str(today), "items": [{"item_id": shirt["id"]}]}).status_code == 422

    # entrega sem baixa (registro de entrega antiga): o CA ainda valia na data da entrega
    old = client.post("/api/ppe/receipts", headers=admin, json={
        "person_id": person["id"], "delivered_on": str(today - timedelta(days=30)),
        "items": [{"item_id": glasses["id"], "from_stock": False}]}).json()
    assert old["warnings"] == []

    # assinatura: CPF confere, declaração obrigatória, hash e integridade
    sign = {"method": "tela", "signature": PNG, "cpf_check": "111", "aware": True}
    assert client.post(f"/api/ppe/receipts/{rec['id']}/sign", headers=admin, json=sign).status_code == 422
    assert client.post(f"/api/ppe/receipts/{rec['id']}/sign", headers=admin,
                       json={**sign, "cpf_check": "286", "aware": False}).status_code == 422
    signed = client.post(f"/api/ppe/receipts/{rec['id']}/sign", headers=admin, json={**sign, "cpf_check": "286"})
    assert signed.status_code == 200, signed.text
    signed = signed.json()
    assert signed["signed"] and len(signed["content_hash"]) == 64 and signed["intact"] is True
    assert client.get(f"/api/ppe/receipts/{rec['id']}/signature", headers=admin).status_code == 200
    assert client.post(f"/api/ppe/receipts/{rec['id']}/sign", headers=admin, json=sign).status_code == 409
    assert client.delete(f"/api/ppe/receipts/{rec['id']}", headers=admin).status_code == 409

    # alteração no banco depois de assinado é detectada
    from app.database import SessionLocal
    from app.models import PPEDelivery
    with SessionLocal() as db:
        d = db.get(PPEDelivery, helmet_line["id"])
        d.quantity = 5
        db.commit()
    assert client.get(f"/api/ppe/receipts/{rec['id']}", headers=admin).json()["intact"] is False
    with SessionLocal() as db:
        db.get(PPEDelivery, helmet_line["id"]).quantity = 1
        db.commit()

    # estorno (não assinado) devolve ao estoque
    extra = client.post("/api/ppe/receipts", headers=admin, json={
        "person_id": person["id"], "delivered_on": str(today), "items": [{"item_id": helmet["id"], "reason": "perda"}]}).json()
    assert client.delete(f"/api/ppe/receipts/{extra['id']}", headers=admin).status_code == 204
    helmet_row = next(r for r in client.get("/api/ppe/stock", headers=admin, params={"unit_id": unit}).json()["rows"]
                      if r["item_id"] == helmet["id"])
    assert helmet_row["quantity"] == 2 and helmet_row["low"]
    moves = client.get("/api/ppe/movements", headers=admin, params={"unit_id": unit}).json()
    assert {m["type"] for m in moves} >= {"entrada", "saida", "ajuste", "estorno"}

    # ficha, uniformes, CA, plano e resumo
    f = client.get(f"/api/ppe/fichas/{person['id']}", headers=admin).json()
    assert f["person"]["cpf"] == "286.145.923-96" and len(f["receipts"]) == 2
    client.put(f"/api/ppe/people/{person['id']}/sizes", headers=admin, json={"sizes": {"camisa": "m", "calcado": "38"}})
    uni = next(u for u in client.get("/api/ppe/uniforms", headers=admin, params={"unit_id": unit}).json() if u["id"] == person["id"])
    assert uni["total"] == 2 and uni["sizes"] == {"camisa": "M", "calcado": "38"}
    ca = client.get("/api/ppe/ca-report", headers=admin, params={"unit_id": unit}).json()
    assert ca["rows"][0]["name"].startswith("Óculos") and ca["counts"]["vencido"] >= 1 and ca["counts"]["vence"] >= 1
    plan = client.get("/api/ppe/replacement-plan", headers=admin, params={"unit_id": unit, "days": 30}).json()
    sec = next(s for s in plan["sectors"] if s["sector"] == "Caldeiraria")
    carla = sec["people"][0]
    assert [d["item"] for d in carla["due"]] == ["Óculos de proteção incolor"] and carla["due"][0]["overdue"]
    assert [m["requirement"] for m in carla["missing"]] == ["Botina"]  # capacete e óculos entregues
    need = next(n for n in plan["needs"] if n["item"].startswith("Óculos"))
    assert need["quantity"] == 1 and need["shortage"] == 1
    s = client.get("/api/ppe/summary", headers=admin, params={"unit_id": unit}).json()
    assert s["stock_low"] == 1 and s["unsigned"] == 1 and s["replacements_overdue"] == 1 and s["missing"] == 1

    # trocar o óculos encerra a pendência da peça anterior
    client.post("/api/ppe/stock/move", headers=admin, json={"unit_id": unit, "item_id": glasses["id"], "type": "entrada",
                                                           "quantity": 1})
    swap = client.post("/api/ppe/receipts", headers=admin, json={
        "person_id": person["id"], "delivered_on": str(today), "items": [{"item_id": glasses["id"], "reason": "troca"}]}).json()
    assert any("vencido" in w for w in swap["warnings"])  # CA vencido hoje: avisa
    plan = client.get("/api/ppe/replacement-plan", headers=admin, params={"unit_id": unit, "days": 5}).json()
    assert not any(p["due"] for s in plan["sectors"] for p in s["people"])
    detail = client.get(f"/api/people/{person['id']}", headers=admin).json()
    assert "vence em 10" in detail["ppe_alert"] and any(d["replaced_on"] for d in detail["deliveries"])

    # relatórios CSV e permissões
    csv = client.get("/api/ppe/deliveries.csv", headers=admin, params={"unit_id": unit,
                                                                       "start": str(today - timedelta(days=40))})
    assert csv.status_code == 200 and "Capacete aba frontal" in csv.text and "Assinatura na tela" in csv.text
    assert "ABAIXO DO MÍNIMO" in client.get("/api/ppe/stock.csv", headers=admin, params={"unit_id": unit}).text
    _, operador = make_user(client, admin, "op-epi@fabrica.com", "operador")
    assert client.get("/api/ppe/stock", headers=operador).status_code == 403
    # item com histórico não é apagado, só desativado
    client.delete(f"/api/ppe/items/{helmet['id']}", headers=admin)
    assert all(i["id"] != helmet["id"] for i in client.get("/api/ppe/items", headers=admin).json())
    assert any(i["id"] == helmet["id"] and not i["active"]
               for i in client.get("/api/ppe/items", headers=admin, params={"all": True}).json())
