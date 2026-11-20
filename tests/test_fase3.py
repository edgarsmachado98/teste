import pytest

from carteira import evolucao, portfolio, providers
from carteira.market import serie_simulada
from tests.conftest import cliente_logado


def ap(data, ticker, qtd, preco, tipo="compra", id_=None):
    return {"id": id_, "data": data, "ticker": ticker, "quantidade": qtd, "preco": preco, "tipo": tipo, "taxas": 0}


def ev(data, ticker, tipo, fator, id_=1):
    return {"id": id_, "data": data, "ticker": ticker, "tipo": tipo, "fator": fator}


def test_eventos_ajustam_quantidade_e_preco_medio():
    ops = portfolio.com_eventos([ap("2025-01-02", "X", 100, 10, id_=1)],
                                [ev("2025-03-01", "X", "desdobramento", 2), ev("2025-06-01", "X", "grupamento", 0.1, 2)])
    p = portfolio.calcular_posicoes(ops)["X"]
    assert p["quantidade"] == pytest.approx(20) and p["custo"] == 1000 and p["preco_medio"] == pytest.approx(50)
    assert portfolio.quantidade_na_data(ops, "X", "2025-04-01") == pytest.approx(200)
    # venda depois do desdobramento usa a quantidade nova
    ops2 = portfolio.com_eventos([ap("2025-01-02", "X", 100, 10, id_=1), ap("2025-04-01", "X", 150, 6, "venda", 2)],
                                 [ev("2025-03-01", "X", "desdobramento", 2)])
    p2 = portfolio.calcular_posicoes(ops2)["X"]
    assert p2["quantidade"] == 50 and p2["realizado"] == pytest.approx(150 * (6 - 5))


def test_evento_no_mesmo_dia_vale_depois_da_compra():
    ops = portfolio.com_eventos([ap("2025-03-01", "X", 10, 10, id_=1)], [ev("2025-03-01", "X", "bonificacao", 1.1)])
    assert portfolio.calcular_posicoes(ops)["X"]["quantidade"] == pytest.approx(11)


def test_evolucao_usa_quantidade_ajustada_com_cotacoes_ajustadas():
    # Cotações históricas vêm ajustadas pelo desdobramento (janeiro: 100 real = 50 ajustado)
    ops = portfolio.com_eventos([ap("2025-01-01", "X", 10, 100, id_=1)], [ev("2025-02-15", "X", "desdobramento", 2)])
    serie = [("2025-01-31", 50.0), ("2025-02-28", 55.0)]
    r = evolucao.calcular_evolucao(ops, [], {"X": serie}, {"X": 55.0}, "2025-02-28")
    jan, fev = r["meses"]
    assert jan["patrimonio"] == pytest.approx(1000) and jan["rent_mes"] == pytest.approx(0)
    assert fev["patrimonio"] == pytest.approx(1100) and fev["rent_mes"] == pytest.approx(10)
    assert fev["investido"] == 1000  # evento não é aporte


def test_fator_evento():
    assert providers.fator_evento("desdobramento", 2) == 2 and providers.fator_evento("desdobramento", 0.5) == 2
    assert providers.fator_evento("grupamento", 10) == pytest.approx(0.1)
    assert providers.fator_evento("bonificacao", 10) == pytest.approx(1.1)
    assert providers.fator_evento("bonificacao", 0.1) == pytest.approx(1.1)
    assert providers.fator_evento("bonificacao", 1.05) == pytest.approx(1.05)
    assert providers.tipo_evento("DESDOBRAMENTO") == "desdobramento" and providers.tipo_evento("BONIFICACAO") == "bonificacao"


def test_brapi_eventos(monkeypatch):
    class Resp:
        status_code, text = 200, ""

        def json(self):
            return {"results": [{"dividendsData": {"cashDividends": [], "stockDividends": [
                {"label": "DESDOBRAMENTO", "factor": 2, "lastDatePrior": "2025-03-14T00:00:00.000Z"},
                {"label": "BONIFICACAO", "factor": 10, "lastDatePrior": "2025-06-14T00:00:00.000Z"},
                {"label": "SUBSCRICAO", "factor": 0.2, "lastDatePrior": "2025-07-01T00:00:00.000Z"}]}}]}

        def raise_for_status(self):
            pass

    monkeypatch.setattr(providers.requests, "get", lambda *a, **k: Resp())
    itens = providers.Brapi(token="t").eventos("ITUB4")
    assert [(e["data_com"], e["tipo"], round(e["fator"], 2)) for e in itens] == [
        ("2025-03-14", "desdobramento", 2), ("2025-06-14", "bonificacao", 1.1)]


FONTE = {"X": [
    {"data_com": "2025-03-10", "data_pagamento": "2025-03-20", "valor": 0.5, "tipo": "dividendo"},
    {"data_com": "2025-09-10", "data_pagamento": "2025-09-25", "valor": 0.5, "tipo": "jcp"},
    {"data_com": "2026-01-05", "data_pagamento": "2026-02-10", "valor": 0.2, "tipo": "dividendo"},
    {"data_com": "2026-03-10", "data_pagamento": "2026-03-20", "valor": 0.6, "tipo": "dividendo"},
]}


def test_agenda_e_projecao():
    ops = [ap("2025-01-01", "X", 100, 10, id_=1)]
    agenda = portfolio.agenda_proventos(ops, FONTE, [], "2026-01-15")
    assert [(a["data_pagamento"], a["status"], a["valor_total"]) for a in agenda] == [
        ("2026-02-10", "a_receber", 20.0), ("2026-03-20", "anunciado", 60.0)]
    proj = portfolio.projecao_renda(ops, FONTE, [], "2026-01-15")
    meses = {m["mes"]: m for m in proj["meses"]}
    assert len(proj["meses"]) == 12 and proj["meses"][0]["mes"] == "2026-01"
    assert meses["2026-02"]["confirmado"] == 20 and meses["2026-03"]["confirmado"] == 60
    assert meses["2026-03"]["projetado"] == 0  # já anunciado: não projeta o de março passado
    assert meses["2026-09"]["projetado"] == pytest.approx(100 * 0.5 * 0.85)  # JCP líquido
    assert proj["total_12m"] == pytest.approx(20 + 60 + 42.5)


def test_projecao_com_proventos_registrados_sem_fonte():
    ops = [ap("2025-01-01", "Y", 10, 100, id_=1), ap("2025-08-01", "Y", 10, 100, id_=2)]
    registrados = [{"ticker": "Y", "tipo": "rendimento", "data_com": "2025-06-30", "data_pagamento": "2025-07-14",
                    "valor_total": 10.0, "quantidade": None}]
    proj = portfolio.projecao_renda(ops, {}, registrados, "2026-01-15")
    assert {m["mes"]: m["projetado"] for m in proj["meses"]}["2026-07"] == pytest.approx(20)  # hoje tem o dobro


def test_numero_magico():
    linhas = [{"ticker": "F", "classe": "fii", "quantidade": 50, "preco_atual": 100.0}]
    fonte = {"F": [{"data_com": f"2025-{m:02d}-01", "valor": 1.0, "tipo": "rendimento"} for m in range(2, 14) if m <= 12]}
    r = portfolio.numero_magico(linhas, fonte, [], [], "2026-01-15")[0]
    assert r["rendimento_mensal_cota"] == pytest.approx(11 / 12)
    assert r["cotas_necessarias"] == 110 and r["faltam"] == 60


class FonteFake:
    nome = "brapi"

    def historico(self, t):
        return serie_simulada(t, dias=300)

    def proventos(self, t):
        return FONTE["X"]

    def eventos(self, t):
        return [{"data_com": "2025-03-14", "tipo": "desdobramento", "fator": 2.0, "descricao": "DESDOBRAMENTO"}]


def test_api_eventos_e_agenda(novo_app):
    c = cliente_logado(novo_app([FonteFake()]))
    c.post("/api/aportes", json={"data": "2025-01-02", "ticker": "ABCD3", "quantidade": 100, "preco": 10})
    sug = c.get("/api/eventos/sugeridos").get_json()["itens"]
    assert len(sug) == 1 and sug[0]["quantidade_antes"] == 100 and sug[0]["quantidade_depois"] == 200
    e = sug[0]
    assert c.post("/api/eventos", json={"ticker": e["ticker"], "data": e["data"], "tipo": e["tipo"], "fator": e["fator"]}).status_code == 201
    assert c.post("/api/eventos", json={"ticker": e["ticker"], "data": e["data"], "tipo": e["tipo"], "fator": 2}).status_code == 409
    assert c.get("/api/eventos/sugeridos").get_json()["itens"] == []
    pos = c.get("/api/carteira").get_json()["ativos"][0]
    assert pos["quantidade"] == 200 and pos["preco_medio"] == pytest.approx(5)
    # venda de 150 só é possível depois do desdobramento
    assert c.post("/api/aportes", json={"data": "2025-04-01", "ticker": "ABCD3", "tipo": "venda", "quantidade": 150, "preco": 6}).status_code == 201

    cid = c.get("/api/eu").get_json()["carteiras"][0]["id"]
    assert c.put(f"/api/carteiras/{cid}/meta-renda", json={"valor": 500}).status_code == 200
    ag = c.get("/api/proventos/agenda").get_json()
    assert ag["meta_mensal"] == 500 and len(ag["meses"]) == 12

    eid = c.get("/api/eventos").get_json()["itens"][0]["id"]
    assert c.delete(f"/api/eventos/{eid}").status_code == 409  # a venda de 150 depende do desdobramento
    vid = next(a["id"] for a in c.get("/api/aportes").get_json() if a["tipo"] == "venda")
    c.delete(f"/api/aportes/{vid}")
    assert c.delete(f"/api/eventos/{eid}").status_code == 200
