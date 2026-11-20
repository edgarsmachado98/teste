import datetime as dt

import pytest

from carteira import db, market, providers
from carteira.market import Mercado
from tests.conftest import cliente_logado


def test_em_pregao():
    seg = dt.datetime(2026, 11, 9, 11, 0)  # segunda-feira
    assert market.em_pregao(seg)
    assert not market.em_pregao(seg.replace(hour=9))
    assert market.em_pregao(seg.replace(hour=18, minute=5)) and not market.em_pregao(seg.replace(hour=19))
    assert not market.em_pregao(dt.datetime(2026, 11, 7, 11, 0))   # sábado
    assert not market.em_pregao(dt.datetime(2026, 11, 20, 11, 0))  # feriado (Consciência Negra)


class Relogio:
    def __init__(self, hora, minuto=0):
        self.agora = dt.datetime.combine(dt.date.today(), dt.time(hora, minuto))

    def __call__(self):
        return self.agora


@pytest.fixture
def mercado(tmp_path, monkeypatch):
    relogio = Relogio(10, 50)
    monkeypatch.setattr(market, "agora_brasilia", relogio)
    monkeypatch.setattr(market, "em_pregao", lambda m=None: dt.time(10) <= (m or relogio()).time() <= dt.time(18, 10))
    chamadas = []

    def fonte(t):
        chamadas.append(relogio().time())
        return [("2026-01-02", 10.0), (dt.date.today().isoformat(), 11.0)]

    return Mercado(db.connect(str(tmp_path / "x.db")), fonte), relogio, chamadas


def test_cache_no_pregao_vale_15_minutos(mercado):
    m, relogio, chamadas = mercado
    m.historico("PETR4")
    relogio.agora += dt.timedelta(minutes=10)
    m.historico("PETR4")
    assert len(chamadas) == 1  # 10 minutos: ainda vale
    relogio.agora += dt.timedelta(minutes=10)
    m.historico("PETR4")
    assert len(chamadas) == 2  # 20 minutos: busca de novo


def test_depois_do_fechamento_busca_o_fechamento_uma_vez(mercado):
    m, relogio, chamadas = mercado
    m.historico("PETR4")                                  # 10h50, no pregão
    relogio.agora = relogio.agora.replace(hour=19)
    m.historico("PETR4")                                  # 19h: a cotação era do meio do pregão -> busca
    relogio.agora = relogio.agora.replace(hour=21)
    m.historico("PETR4")                                  # 21h: já tem o fechamento -> cache
    assert len(chamadas) == 2
    assert m.atualizado_em(["PETR4"]).startswith(dt.date.today().isoformat() + "T19")


def test_brapi_acrescenta_cotacao_do_momento(monkeypatch):
    hoje = dt.date.today()

    class Resp:
        status_code, text = 200, ""

        def json(self):
            return {"results": [{"regularMarketPrice": 39.5, "regularMarketTime": hoje.isoformat() + "T14:31:00.000Z",
                                 "historicalDataPrice": [{"date": 1735776000, "close": 38.0}]}]}

        def raise_for_status(self):
            pass

    monkeypatch.setattr(providers.requests, "get", lambda *a, **k: Resp())
    serie = providers.Brapi(token="t").historico("PETR4")
    assert serie[-1] == (hoje.isoformat(), 39.5) and serie[0][1] == 38.0


def test_api_atualizar_cotacoes(novo_app):
    chamadas = []

    def fonte(t):
        chamadas.append(t)
        return [("2026-01-02", 10.0), (dt.date.today().isoformat(), 11.0)]

    c = cliente_logado(novo_app(fonte))
    c.post("/api/aportes", json={"data": "2026-01-05", "ticker": "PETR4", "quantidade": 10, "preco": 10})
    c.post("/api/ativos", json={"ticker": "CDB X", "classe": "renda_fixa", "preco_manual": 1000})
    c.post("/api/acompanhamento", json={"ticker": "TAEE11"})
    antes = len(chamadas)
    r = c.post("/api/cotacoes/atualizar").get_json()
    assert r["atualizados"] == 2 and set(chamadas[antes:]) == {"PETR4", "TAEE11"}  # CDB manual fica de fora
    cart = c.get("/api/carteira").get_json()
    assert cart["cotacoes_em"] and "em_pregao" in cart
