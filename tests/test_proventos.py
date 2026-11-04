import pytest

from app import create_app
from carteira import portfolio, providers
from carteira.market import serie_simulada


def ap(data, ticker, qtd, tipo="compra"):
    return {"data": data, "ticker": ticker, "quantidade": qtd, "preco": 10, "tipo": tipo, "taxas": 0}


APORTES = [ap("2025-01-10", "ITUB4", 100), ap("2025-03-10", "ITUB4", 50), ap("2025-05-10", "ITUB4", 30, "venda")]


def test_quantidade_na_data():
    assert portfolio.quantidade_na_data(APORTES, "ITUB4", "2025-01-09") == 0
    assert portfolio.quantidade_na_data(APORTES, "ITUB4", "2025-01-10") == 100
    assert portfolio.quantidade_na_data(APORTES, "ITUB4", "2025-04-01") == 150
    assert portfolio.quantidade_na_data(APORTES, "ITUB4", "2025-06-01") == 120


def test_estimar_proventos():
    fonte = {"ITUB4": [
        {"data_com": "2025-01-05", "data_pagamento": "2025-02-01", "valor": 1.0, "tipo": "dividendo"},  # antes da compra
        {"data_com": "2025-04-01", "data_pagamento": "2025-05-01", "valor": 1.0, "tipo": "jcp"},
        {"data_com": "2025-06-01", "data_pagamento": None, "valor": 0.5, "tipo": "dividendo"},
        {"data_com": "2025-07-01", "data_pagamento": "2025-08-01", "valor": 0.5, "tipo": "dividendo"},
        {"data_com": "2025-12-01", "data_pagamento": "2026-01-01", "valor": 9, "tipo": "dividendo"},  # data com futura
    ]}
    registrados = [{"ticker": "ITUB4", "data_com": "2025-07-01", "data_pagamento": "2025-08-01", "tipo": "dividendo"}]
    itens = {i["data_com"]: i for i in portfolio.estimar_proventos(APORTES, fonte, registrados, "2025-06-15")}
    assert set(itens) == {"2025-04-01", "2025-06-01"}  # 07-01 e 12-01 têm data com futura
    jcp = itens["2025-04-01"]
    assert jcp["quantidade"] == 150 and jcp["valor_total"] == pytest.approx(150 * 0.85)
    assert jcp["status"] == "recebido"
    div = itens["2025-06-01"]
    assert div["pagamento_estimado"] and div["data_pagamento"] == "2025-07-01"
    assert div["status"] == "a_receber" and div["valor_total"] == 60

    todos = portfolio.estimar_proventos(APORTES, fonte, registrados, "2025-09-01")
    assert next(i for i in todos if i["data_com"] == "2025-07-01")["ja_registrado"]


def test_resumo_proventos():
    resumo = {"ativos": [{"ticker": "A", "custo": 1000, "valor": 2000}], "total_custo": 1000, "total_valor": 2000}
    provs = [
        {"ticker": "A", "tipo": "dividendo", "data_pagamento": "2025-12-10", "valor_total": 30},
        {"ticker": "A", "tipo": "jcp", "data_pagamento": "2025-03-10", "valor_total": 20},
        {"ticker": "A", "tipo": "dividendo", "data_pagamento": "2024-01-10", "valor_total": 100},  # > 12 meses
        {"ticker": "A", "tipo": "dividendo", "data_pagamento": "2026-02-10", "valor_total": 7},   # futuro
    ]
    r = portfolio.resumo_proventos(provs, resumo, "2026-01-01")
    assert r["total"] == 150 and r["ult_12m"] == 50 and r["a_receber"] == 7
    assert r["yoc_pct"] == pytest.approx(5) and r["dy_pct"] == pytest.approx(2.5)
    assert r["por_mes"][-1]["mes"] == "2026-01" and len(r["por_mes"]) == 24
    assert next(m for m in r["por_mes"] if m["mes"] == "2025-12")["dividendo"] == 30


def test_dividend_yield_e_por_ano():
    itens = [{"data_com": "2025-03-01", "valor": 1}, {"data_com": "2025-09-01", "valor": 2},
             {"data_com": "2024-03-01", "valor": 5}]
    assert portfolio.dividend_yield(itens, 30, "2026-01-01") == pytest.approx(0.1)
    assert portfolio.proventos_por_ano(itens) == [{"ano": "2024", "valor": 5}, {"ano": "2025", "valor": 3}]


def test_brapi_proventos_e_fundamentos(monkeypatch):
    class Resp:
        status_code, text = 200, ""

        def __init__(self, d):
            self.d = d

        def json(self):
            return self.d

        def raise_for_status(self):
            pass

    def fake_get(url, headers=None, params=None, timeout=None):
        if params.get("dividends"):
            return Resp({"results": [{"dividendsData": {"cashDividends": [
                {"rate": 0.5, "label": "JRS CAP PROPRIO", "lastDatePrior": "2025-03-01T00:00:00.000Z",
                 "paymentDate": "2025-04-01T00:00:00.000Z"},
                {"rate": 0.3, "label": "DIVIDENDO", "lastDatePrior": "2025-06-01T00:00:00.000Z", "paymentDate": None},
            ]}}]})
        return Resp({"results": [{"longName": "Itaú", "priceEarnings": 8.5, "earningsPerShare": 4.1,
                                  "defaultKeyStatistics": {"priceToBook": {"raw": 1.9}},
                                  "financialData": {"returnOnEquity": 0.21, "debtToEquity": 150}}]})

    monkeypatch.setattr(providers.requests, "get", fake_get)
    b = providers.Brapi(token="t")
    assert b.proventos("ITUB4") == [
        {"data_com": "2025-03-01", "data_pagamento": "2025-04-01", "valor": 0.5, "tipo": "jcp"},
        {"data_com": "2025-06-01", "data_pagamento": None, "valor": 0.3, "tipo": "dividendo"},
    ]
    f = b.fundamentos("ITUB4")
    assert f["pl"] == 8.5 and f["pvp"] == 1.9 and f["roe"] == 0.21 and f["divida_pl"] == 1.5


class FonteFake:
    nome = "brapi"

    def historico(self, t):
        return serie_simulada(t, dias=300)

    def proventos(self, t):
        return [{"data_com": "2025-02-03", "data_pagamento": "2025-02-20", "valor": 0.8, "tipo": "rendimento"}]

    def fundamentos(self, t):
        return {"pl": 10.0, "pvp": 0.95}


@pytest.fixture
def client(tmp_path):
    return create_app(str(tmp_path / "t.db"), [FonteFake()]).test_client()


def test_api_fluxo_proventos(client):
    client.post("/api/aportes", json={"data": "2025-01-10", "ticker": "KNRI11", "classe": "fii",
                                      "quantidade": 10, "preco": 150})
    est = client.get("/api/proventos/estimar").get_json()
    assert est["fontes"] == {"KNRI11": "brapi"}
    item = est["itens"][0]
    assert item["valor_total"] == 8 and not item["ja_registrado"]

    assert client.post("/api/proventos/importar", json={"itens": [item]}).status_code == 201
    assert client.get("/api/proventos/estimar").get_json()["itens"][0]["ja_registrado"]

    r = client.get("/api/proventos").get_json()
    assert r["resumo"]["total"] == 8 and r["itens"][0]["obs"] == "importado"

    assert client.post("/api/proventos", json={"ticker": "KNRI11", "tipo": "x", "data_pagamento": "2025-01-01",
                                               "valor_total": 1}).status_code == 400
    assert client.post("/api/proventos", json={"ticker": "KNRI11", "data_pagamento": "2025-03-01",
                                               "quantidade": 10, "valor_unitario": 0.5}).status_code == 201
    assert client.get("/api/carteira").get_json()["proventos"]["total"] == 13

    pid = client.get("/api/proventos").get_json()["itens"][0]["id"]
    assert client.delete(f"/api/proventos/{pid}").status_code == 200


def test_api_fundamentos(client):
    f = client.get("/api/fundamentos/KNRI11").get_json()
    assert f["indicadores"]["pvp"] == 0.95 and f["fonte_indicadores"] == "brapi"
    assert f["proventos_por_ano"] == [{"ano": "2025", "valor": 0.8}]
