import pytest

from carteira.market import serie_simulada
from tests.conftest import cliente_logado


def fonte_falsa(ticker):
    if ticker == "FALHA3":
        raise RuntimeError("sem rede")
    return serie_simulada(ticker, dias=300)


@pytest.fixture
def client(novo_app):
    return cliente_logado(novo_app(fonte_falsa))


def test_fluxo_completo(client):
    assert client.post("/api/ativos", json={"ticker": "itub4", "classe": "acao", "meta_pct": 50}).status_code == 201
    assert client.post("/api/ativos", json={"ticker": "KNRI11", "classe": "fii", "meta_pct": 50}).status_code == 201
    r = client.post("/api/aportes", json={"data": "2025-01-10", "ticker": "ITUB4", "quantidade": 10, "preco": 30})
    assert r.status_code == 201

    c = client.get("/api/carteira").get_json()
    itub = next(a for a in c["ativos"] if a["ticker"] == "ITUB4")
    assert itub["quantidade"] == 10 and itub["fonte_preco"] == "yahoo"

    s = client.post("/api/sugestao", json={"valor": 5000}).get_json()
    assert s["valor_utilizado"] <= 5000
    assert {x["ticker"] for x in s["sugestoes"]} <= {"ITUB4", "KNRI11"}

    m = client.get("/api/mercado/ITUB4?dias=100").get_json()
    assert len(m["datas"]) == 100 and m["sinais"]

    cmp_ = client.get("/api/comparar?tickers=ITUB4,KNRI11").get_json()
    assert cmp_["correlacao"][0][0] == pytest.approx(1)


def test_venda_sem_posicao_rejeitada(client):
    r = client.post("/api/aportes", json={"data": "2025-01-10", "ticker": "X", "tipo": "venda",
                                          "quantidade": 1, "preco": 1})
    assert r.status_code == 400


def test_preco_manual_e_falha_de_rede(client):
    client.post("/api/ativos", json={"ticker": "FALHA3", "meta_pct": 100, "preco_manual": 12.5})
    client.post("/api/aportes", json={"data": "2025-01-10", "ticker": "FALHA3", "quantidade": 2, "preco": 10})
    a = client.get("/api/carteira").get_json()["ativos"][0]
    assert a["preco_atual"] == 12.5 and a["fonte_preco"] == "manual"
    assert client.get("/api/mercado/FALHA3").status_code == 502


def test_nao_remove_ativo_com_aportes(client):
    client.post("/api/aportes", json={"data": "2025-01-10", "ticker": "ABCD3", "quantidade": 1, "preco": 1})
    assert client.delete("/api/ativos/ABCD3").status_code == 409
