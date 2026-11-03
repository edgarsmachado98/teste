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


PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="


def test_identification_and_measures(client, admin):
    from datetime import datetime, timedelta, timezone

    from app.database import SessionLocal
    from app.models import Event

    unit_id = client.get("/api/units", headers=admin).json()[0]["id"]
    sector = next(s for s in client.get("/api/sectors", headers=admin).json() if s["name"] == "Solda")
    _, tecnico = make_user(client, admin, "tec-medidas@fabrica.com", "tecnico")
    _, gestor = make_user(client, admin, "gestor-medidas@fabrica.com", "gestor")
    _, operador = make_user(client, admin, "op-medidas@fabrica.com", "operador")
    cam = client.post("/api/cameras", headers=admin, json={"name": "Célula 9", "source": "9", "sector_id": sector["id"]}).json()
    rule = next(r for r in client.get(f"/api/rules?camera_id={cam['id']}", headers=admin).json() if r["type"] == "ppe_missing")
    people = client.get(f"/api/people?sector_id={sector['id']}", headers=admin).json()["items"]
    camila = next(p for p in people if p["name"] == "Camila Duarte")

    def new_event(days_ago=0, with_image=True):
        files = {"snapshot": ("e.jpg", b"\xff\xd8img", "image/jpeg")} if with_image else None
        ev = client.post("/api/detector/events", headers=DET, files=files,
                         data={"camera_id": cam["id"], "rule_id": rule["id"], "message": "1 pessoa(s) sem capacete"}).json()
        if days_ago:
            with SessionLocal() as db:
                db.get(Event, ev["id"]).created_at = datetime.now(timezone.utc) - timedelta(days=days_ago)
                db.commit()
        return ev

    ev1 = new_event(days_ago=20)
    # candidatos: pessoas do setor da câmera; busca pelo nº do colete
    assert client.get(f"/api/events/{ev1['id']}/candidates", headers=operador).status_code == 403
    cands = client.get(f"/api/events/{ev1['id']}/candidates", headers=tecnico).json()
    assert cands["has_sector"] and {c["name"] for c in cands["candidates"]} >= {"Camila Duarte", "Bruno Henrique Costa"}
    assert all(c["cpf"].startswith("***") for c in cands["candidates"])
    by_badge = client.get(f"/api/events/{ev1['id']}/candidates?q=0501", headers=tecnico).json()["candidates"]
    assert [c["name"] for c in by_badge] == ["Camila Duarte"]

    # medida antes de identificar: erro claro
    assert client.post("/api/measures", headers=tecnico, json={"event_id": ev1["id"], "type": "orientacao"}).status_code == 400
    ident = client.post(f"/api/events/{ev1['id']}/identify", headers=tecnico, json={"person_id": camila["id"], "method": "numero"})
    assert ident.status_code == 200
    detail = client.get(f"/api/events/{ev1['id']}", headers=tecnico).json()
    assert detail["person_name"] == "Camila Duarte" and detail["status"] == "confirmada"

    # 1ª ocorrência → orientação
    sug = client.get(f"/api/events/{ev1['id']}/suggestion", headers=tecnico).json()
    assert sug["type"] == "orientacao" and sug["count"] == 1
    m1 = client.post("/api/measures", headers=tecnico, json={"event_id": ev1["id"], "type": "orientacao",
                                                            "description": "Conversa no posto",
                                                            "training_name": "ignorado", "training_date": "2026-12-01"}).json()
    assert m1["status"] == "aplicada" and m1["number"].startswith("VIG-")
    assert m1["training_name"] == "" and m1["training_date"] is None  # só medidas de treinamento guardam o curso

    # 2ª → treinamento (cria treinamento agendado); escolher outra exige justificativa
    ev2 = new_event(days_ago=5)
    client.post(f"/api/events/{ev2['id']}/identify", headers=tecnico, json={"person_id": camila["id"]})
    sug = client.get(f"/api/events/{ev2['id']}/suggestion", headers=tecnico).json()
    assert sug["type"] == "treinamento" and sug["count"] == 2 and sug["next_type"] == "advertencia"
    bad = client.post("/api/measures", headers=tecnico, json={"event_id": ev2["id"], "type": "orientacao"})
    assert bad.status_code == 422 and "justifique" in bad.json()["detail"]
    m2 = client.post("/api/measures", headers=tecnico, json={"event_id": ev2["id"], "type": "treinamento",
                                                            "training_name": "Reciclagem NR-6", "training_date": "2026-11-10"}).json()
    person = client.get(f"/api/people/{camila['id']}", headers=admin).json()
    assert any(t["name"] == "Reciclagem NR-6" and t["status"] == "agendado" and t["measure_id"] == m2["id"]
               for t in person["trainings"])

    # ciência: assinatura no celular, com a versão do colaborador
    ack = client.post(f"/api/measures/{m2['id']}/ack", headers=tecnico, json={
        "ack": "assinada", "signature": PNG, "statement": "Tirei o capacete para ajustar o protetor auricular"})
    assert ack.status_code == 200 and ack.json()["ack"] == "assinada" and ack.json()["has_signature"]
    assert client.get(f"/api/measures/{m2['id']}/signature", headers=tecnico).content.startswith(b"\x89PNG")
    assert client.post(f"/api/measures/{m1['id']}/ack", headers=tecnico, json={"ack": "assinada"}).status_code == 422

    # 3ª → advertência: criada por técnico fica aguardando aprovação do gestor; sem evidência é recusada
    ev3 = new_event(with_image=False)
    client.post(f"/api/events/{ev3['id']}/identify", headers=tecnico, json={"person_id": camila["id"]})
    assert client.get(f"/api/events/{ev3['id']}/suggestion", headers=tecnico).json()["type"] == "advertencia"
    noev = client.post("/api/measures", headers=tecnico, json={"event_id": ev3["id"], "type": "advertencia"})
    assert noev.status_code == 400 and "evidência" in noev.json()["detail"]
    ev4 = new_event()
    client.post(f"/api/events/{ev4['id']}/identify", headers=tecnico, json={"person_id": camila["id"]})
    m4 = client.post("/api/measures", headers=tecnico, json={"event_id": ev4["id"], "type": "rh",
                                                            "justification": "quarta ocorrência no período"}).json()
    assert m4["type"] == "rh"
    ev5 = new_event()
    client.post(f"/api/events/{ev5['id']}/identify", headers=tecnico, json={"person_id": camila["id"]})
    m5 = client.post("/api/measures", headers=tecnico, json={"event_id": ev5["id"], "type": "advertencia",
                                                            "justification": "advertência conforme regulamento"}).json()
    assert m5["status"] == "pendente_aprovacao"
    assert client.post(f"/api/measures/{m5['id']}/ack", headers=tecnico, json={"ack": "impressa"}).status_code == 400
    assert client.post(f"/api/measures/{m5['id']}/decision", headers=tecnico, json={"approve": True}).status_code == 403
    dec = client.post(f"/api/measures/{m5['id']}/decision", headers=gestor, json={"approve": True}).json()
    assert dec["status"] == "aplicada" and dec["approved_by"]
    pending = client.get("/api/measures?status=pendente_aprovacao", headers=gestor).json()
    assert all(m["id"] != m5["id"] for m in pending)

    # recusa com testemunhas obrigatórias (configurável) e exceção por gravidade
    grading = client.get("/api/grading", headers=tecnico).json()
    assert client.put("/api/grading", headers=tecnico, json=grading).status_code == 403
    assert client.put("/api/grading", headers=admin, json={**grading, "window_days": 2}).status_code == 400
    cfg = client.put("/api/grading", headers=admin, json={**grading, "require_witnesses_on_refusal": True,
                                                         "type_start": {"restricted_zone": 2}}).json()
    assert cfg["type_start"] == {"restricted_zone": 2}
    assert client.post(f"/api/measures/{m5['id']}/ack", headers=tecnico, json={"ack": "recusada"}).status_code == 422
    assert client.post(f"/api/measures/{m5['id']}/ack", headers=tecnico,
                       json={"ack": "recusada", "witnesses": "Elaine Prado e João Vieira"}).status_code == 200

    # não identificado
    ev6 = new_event()
    client.post(f"/api/events/{ev6['id']}/identify", headers=tecnico, json={"person_id": None})
    assert client.get(f"/api/events/{ev6['id']}", headers=tecnico).json()["identification"] == "nao_identificado"

    # histórico: linha do tempo, resumo e próximo passo; consulta auditada
    hist = client.get(f"/api/people/{camila['id']}/history", headers=tecnico).json()
    assert hist["summary"]["events_window"] == 5 and hist["summary"]["warnings"] == 1
    assert hist["summary"]["orientations"] == 1 and hist["summary"]["trainings"] == 1
    assert hist["next"]["type"] == "rh"
    kinds = {t["kind"] for t in hist["timeline"]}
    assert kinds == {"ocorrencia", "medida", "treinamento"}
    assert client.get(f"/api/people/{camila['id']}/history", headers=operador).status_code == 403
    log = client.get(f"/api/audit?entity=pessoa&entity_id={camila['id']}", headers=admin).json()
    assert any(a["action"] == "historico_consultado" for a in log)
    assert client.get(f"/api/events/{ev2['id']}", headers=tecnico).json()["measures"][0]["number"] == m2["number"]


def test_events_csv_export(client, admin):
    import csv
    import io

    resp = client.get("/api/reports/events.csv", headers=admin)
    assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(resp.content.decode("utf-8-sig")), delimiter=";"))
    assert rows[0][:3] == ["Nº", "Data", "Hora"] and len(rows) > 1
    assert any(r[12] == "Camila Duarte" for r in rows[1:])  # pessoa identificada
    _, operador = make_user(client, admin, "op-csv@fabrica.com", "operador")
    assert client.get("/api/reports/events.csv", headers=operador).status_code == 403
    log = client.get("/api/audit?entity=relatorio", headers=admin).json()
    assert any(a["action"] == "ocorrencias_exportadas" for a in log)


def test_occupational_exams(client, admin):
    from datetime import date, timedelta
    from app.exams import add_months
    unit = client.get("/api/units", headers=admin).json()[0]["id"]
    sector = client.post("/api/sectors", headers=admin, json=sector_payload(
        unit, name="Caldeiraria", required_exams=["aso", "audiometria", "espirometria"])).json()["sector"]
    assert sector["required_exams"] == ["aso", "audiometria", "espirometria"]
    assert client.post("/api/sectors", headers=admin, json=sector_payload(
        unit, name="X", required_exams=["raio_x_do_pe"])).status_code == 422
    person = client.post("/api/people", headers=admin, json=person_payload(
        unit, name="Diego Exames", cpf="390.533.447-05", registration="EX-1", badge_code="EX1",
        sector_id=sector["id"])).json()
    pid = person["id"]
    detail = client.get(f"/api/people/{pid}", headers=admin).json()
    status = {i["exam"]: i["status"] for i in detail["exam_status"]}
    assert status == {"aso": "pendente", "audiometria": "pendente", "espirometria": "pendente"}
    url = f"/api/people/{pid}/exams"
    today = date.today()
    # ASO precisa de tipo e resultado; restrição exige descrição
    assert client.post(url, headers=admin, json={"exam": "aso", "performed_on": str(today)}).status_code == 422
    assert client.post(url, headers=admin, json={"exam": "aso", "aso_type": "periodico", "result": "apto_restricao",
                                                  "performed_on": str(today)}).status_code == 422
    assert client.post(url, headers=admin, json={"exam": "aso", "aso_type": "periodico", "result": "apto",
                                                  "performed_on": str(today + timedelta(days=3))}).status_code == 422
    aso = client.post(url, headers=admin, json={
        "exam": "aso", "aso_type": "periodico", "result": "apto", "performed_on": str(today),
        "aptitudes": ["altura", "inexistente"], "provider": "Clínica Vida"}).json()
    assert aso["valid_until"] == str(add_months(today, 12))  # validade sugerida pelo catálogo
    assert aso["aptitudes"] == ["altura"] and aso["status"] == "em_dia"
    # audiometria vencida e espirometria a vencer em 10 dias (validade informada)
    old = today - timedelta(days=400)
    client.post(url, headers=admin, json={"exam": "audiometria", "performed_on": str(old), "aso_type": "admissional",
                                          "result": "inapto", "aptitudes": ["altura"]})
    esp = client.post(url, headers=admin, json={"exam": "espirometria", "performed_on": str(today - timedelta(days=700)),
                                                "valid_until": str(today + timedelta(days=10))}).json()
    assert esp["status"] == "vence" and esp["days"] == 10
    detail = client.get(f"/api/people/{pid}", headers=admin).json()
    audio = next(e for e in detail["exams"] if e["exam"] == "audiometria")
    assert audio["aso_type"] is None and audio["result"] is None and audio["aptitudes"] == []  # campos só do ASO
    status = {i["exam"]: i["status"] for i in detail["exam_status"]}
    assert status == {"aso": "em_dia", "audiometria": "vencido", "espirometria": "vence"}
    listed = client.get("/api/people", headers=admin, params={"q": "Diego Exames"}).json()["items"][0]
    assert listed["exam_alert"] == "Audiometria tonal vencido"
    summary = client.get("/api/people/summary", headers=admin).json()
    assert summary["exams_expired"] >= 1 and summary["exams_expiring"] >= 1
    # ASO inapto ganha destaque; demissional encerra sem próxima validade
    client.put(f"{url}/{aso['id']}", headers=admin, json={**{k: aso[k] for k in ("exam", "aso_type", "performed_on",
               "provider", "aptitudes")}, "result": "inapto", "valid_until": aso["valid_until"]})
    listed = client.get("/api/people", headers=admin, params={"q": "Diego Exames"}).json()["items"][0]
    assert listed["exam_alert"] == "ASO: inapto"
    dem = client.post(url, headers=admin, json={"exam": "aso", "aso_type": "demissional", "result": "apto",
                                                "performed_on": str(today)}).json()
    assert dem["valid_until"] is None
    # tudo auditado; exclusão
    assert client.delete(f"{url}/{dem['id']}", headers=admin).status_code == 204
    actions = [a["action"] for a in client.get("/api/audit", headers=admin).json()]
    assert {"exame_registrado", "exame_alterado", "exame_excluido"} <= set(actions)
    catalog = client.get("/api/people/exams/catalog", headers=admin).json()
    assert {"aso", "audiometria", "toxicologico"} <= {e["id"] for e in catalog["exams"]}
    assert "demissional" in catalog["aso_types"] and "altura" in catalog["aptitudes"]


def test_unit_filter(client, admin):
    """Seletor de unidade do cabeçalho: câmeras, ocorrências, ações, indicadores e CSV por unidade."""
    from tests.test_api import DET
    plant_a = client.post("/api/units", headers=admin, json={"name": "Planta Joinville"}).json()["id"]
    plant_b = client.post("/api/units", headers=admin, json={"name": "Planta Curitiba"}).json()["id"]
    sec_b = client.post("/api/sectors", headers=admin, json=sector_payload(plant_b, name="Expedição B")).json()["sector"]
    cam_a = client.post("/api/cameras", headers=admin, json={"name": "Doca A", "source": "0", "unit_id": plant_a}).json()
    cam_b = client.post("/api/cameras", headers=admin, json={"name": "Doca B", "source": "0", "sector_id": sec_b["id"],
                                                            "unit_id": plant_a}).json()
    assert cam_a["unit_id"] == plant_a
    assert cam_b["unit_id"] == plant_b  # com setor, vale a unidade do setor (ignora a escolhida)
    rule = client.post("/api/rules", headers=admin, json={"camera_id": cam_a["id"], "name": "Zona", "type": "restricted_zone"}).json()
    ev_a = client.post("/api/detector/events", headers=DET, data={"camera_id": cam_a["id"], "rule_id": rule["id"],
                                                                 "message": "pessoa na doca A"}).json()
    b_rule = client.get("/api/rules", headers=admin, params={"camera_id": cam_b["id"]}).json()[0]
    ev_b = client.post("/api/detector/events", headers=DET, data={"camera_id": cam_b["id"], "rule_id": b_rule["id"],
                                                                 "message": "pessoa na doca B"}).json()
    ids = lambda r: {x["id"] for x in r.json()}  # noqa: E731
    assert {cam_a["id"]} == ids(client.get("/api/cameras", headers=admin, params={"unit_id": plant_a}))
    only_a = client.get("/api/events", headers=admin, params={"unit_id": plant_a}).json()
    assert [e["id"] for e in only_a] == [ev_a["id"]] and only_a[0]["unit_id"] == plant_a
    assert ev_b["id"] in ids(client.get("/api/events", headers=admin, params={"unit_id": plant_b}))
    assert all(r["camera_id"] == cam_a["id"] for r in client.get("/api/rules", headers=admin, params={"unit_id": plant_a}).json())
    # ação da ocorrência B some na unidade A; ação avulsa aparece em todas
    act_b = client.post("/api/actions", headers=admin, json={"title": "Sinalizar doca B", "event_id": ev_b["id"]}).json()
    loose = client.post("/api/actions", headers=admin, json={"title": "Revisar plano de emergência"}).json()
    in_a = ids(client.get("/api/actions", headers=admin, params={"unit_id": plant_a}))
    assert loose["id"] in in_a and act_b["id"] not in in_a
    # indicadores e CSV
    s_a = client.get("/api/reports/summary", headers=admin, params={"unit_id": plant_a}).json()
    s_all = client.get("/api/reports/summary", headers=admin).json()
    assert s_a["totals"]["events"] == 1 and s_all["totals"]["events"] > 1
    csv_a = client.get("/api/reports/events.csv", headers=admin, params={"unit_id": plant_a}).text
    assert "pessoa na doca A" in csv_a and "pessoa na doca B" not in csv_a
    assert client.get("/api/reports/pdf", headers=admin, params={"unit_id": plant_a}).status_code == 200
    # setor muda de unidade: a câmera acompanha
    client.put(f"/api/sectors/{sec_b['id']}", headers=admin, json=sector_payload(plant_a, name="Expedição B"))
    assert cam_b["id"] in ids(client.get("/api/cameras", headers=admin, params={"unit_id": plant_a}))
    meta = client.get("/api/meta", headers=admin).json()
    assert {"Planta Joinville", "Planta Curitiba"} <= {u["name"] for u in meta["units"]}


def test_dds(client, admin):
    from datetime import date, timedelta
    from tests.test_api import DET
    themes = client.get("/api/dds/themes", headers=admin).json()
    assert len(themes["themes"]) >= 30 and "EPI" in themes["categories"]
    unit = client.post("/api/units", headers=admin, json={"name": "Planta DDS"}).json()["id"]
    sector = client.post("/api/sectors", headers=admin, json=sector_payload(unit, name="Pintura")).json()["sector"]
    cam = client.post("/api/cameras", headers=admin, json={"name": "Cabine", "source": "0", "sector_id": sector["id"]}).json()
    rule = client.get("/api/rules", headers=admin, params={"camera_id": cam["id"]}).json()[0]
    for _ in range(3):
        client.post("/api/detector/events", headers=DET, data={"camera_id": cam["id"], "rule_id": rule["id"],
                                                              "message": "1 pessoa(s) sem máscara"})
    sug = client.get("/api/dds/suggestions", headers=admin, params={"sector_id": sector["id"]}).json()
    assert sug[0]["title"].startswith("Proteção respiratória") and "falta de máscara" in sug[0]["reason"]
    # plano: prévia, gravação e não duplica ao gerar de novo
    monday = date.today() - timedelta(days=date.today().weekday())
    body = {"unit_id": unit, "sector_id": sector["id"], "shift": "Turno A", "start": str(monday),
            "end": str(monday + timedelta(days=13)), "weekdays": [0, 2, 4], "facilitator": "Líder Paulo"}
    preview = client.post("/api/dds/plan", headers=admin, json=body).json()
    assert preview["created"] == 0 and len(preview["items"]) == 6
    assert preview["items"][0]["title"].startswith("Proteção respiratória")
    assert len({i["theme_id"] for i in preview["items"]}) == 6  # não repete tema no plano
    created = client.post("/api/dds/plan", headers=admin, json={**body, "dry_run": False}).json()
    assert created["created"] == 6
    assert client.post("/api/dds/plan", headers=admin, json={**body, "dry_run": False}).json()["created"] == 0
    listed = client.get("/api/dds/sessions", headers=admin, params={
        "start": body["start"], "end": body["end"], "unit_id": unit}).json()
    first = listed["sessions"][0]
    assert first["points"] and first["question"] and first["reason"].startswith("3 ocorrência")
    # registro de realização com presença
    person = client.post("/api/people", headers=admin, json=person_payload(
        unit, name="Rita Pintora", cpf="935.411.347-80", registration="DDS-1", badge_code="DDS1",
        sector_id=sector["id"])).json()
    assert client.post(f"/api/dds/sessions/{first['id']}/record", headers=admin,
                       json={"facilitator": "Líder Paulo"}).status_code == 422  # sem participantes
    done = client.post(f"/api/dds/sessions/{first['id']}/record", headers=admin, json={
        "person_ids": [person["id"]], "extra_participants": 2, "facilitator": "Líder Paulo"}).json()
    assert done["status"] == "realizado" and done["participants"] == 3
    assert client.delete(f"/api/dds/sessions/{first['id']}", headers=admin).status_code == 400
    future = next(s for s in listed["sessions"] if date.fromisoformat(s["day"]) > date.today()) \
        if any(date.fromisoformat(s["day"]) > date.today() for s in listed["sessions"]) else None
    if future:
        assert client.post(f"/api/dds/sessions/{future['id']}/record", headers=admin, json={
            "person_ids": [person["id"]], "facilitator": "X Y"}).status_code == 400
    summary = client.get("/api/dds/sessions", headers=admin, params={
        "start": body["start"], "end": body["end"], "unit_id": unit}).json()["summary"]
    assert summary["done"] == 1 and summary["participants"] == 3
    assert client.get(f"/api/dds/people/{person['id']}", headers=admin).json()[0]["title"] == done["title"]
    # tema próprio
    mine = client.post("/api/dds/themes", headers=admin, json={
        "category": "Comportamento seguro", "title": "Uso do crachá na portaria", "points": ["Sempre visível", " "]}).json()
    assert mine["points"] == ["Sempre visível"] and not mine["builtin"]
    builtin = next(t for t in themes["themes"] if t["builtin"])
    assert client.put(f"/api/dds/themes/{builtin['id']}", headers=admin, json={
        "category": "EPI", "title": "Mudado"}).status_code == 400
    assert client.delete(f"/api/dds/themes/{mine['id']}", headers=admin).status_code == 204
    actions = {a["action"] for a in client.get("/api/audit", headers=admin).json()}
    assert {"dds_plano_gerado", "dds_realizado", "dds_tema_criado"} <= actions
