import pytest

from carteira import db, providers
from carteira.market import Mercado, MarketDataError


class Resp:
    def __init__(self, dados, status=200):
        self.dados, self.status_code, self.text = dados, status, str(dados)

    def json(self):
        return self.dados

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_brapi_le_historico_e_envia_token(monkeypatch):
    chamadas = []

    def fake_get(url, headers=None, params=None, timeout=None):
        chamadas.append((url, headers, params))
        if params["range"] == "2y":
            return Resp({"error": True}, 403)  # plano não libera 2 anos
        return Resp({"results": [{"symbol": "WEGE3", "historicalDataPrice": [
            {"date": 1735776000, "close": 50.0, "adjustedClose": 49.5},
            {"date": 1735862400, "close": 51.0, "adjustedClose": None},
        ]}]})

    monkeypatch.setattr(providers.requests, "get", fake_get)
    serie = providers.Brapi(token="abc").historico("wege3")
    assert serie == [("2025-01-02", 49.5), ("2025-01-03", 51.0)]
    assert chamadas[0][1]["Authorization"] == "Bearer abc"
    assert [c[2]["range"] for c in chamadas] == ["2y", "1y"]


def test_brapi_sem_token_so_sandbox():
    with pytest.raises(providers.FonteIndisponivel):
        providers.Brapi(token="").historico("WEGE3")
    with pytest.raises(providers.FonteIndisponivel):
        providers.Brapi(token="x").historico("AAPL")


def test_dadosdemercado(monkeypatch):
    monkeypatch.setattr(providers.requests, "get", lambda url, **k: Resp(
        [{"date": "2025-01-03", "close": 10.0}, {"date": "2025-01-02", "close": 9.0}]))
    assert providers.DadosDeMercado(token="t").historico("PETR4") == [("2025-01-02", 9.0), ("2025-01-03", 10.0)]
    with pytest.raises(providers.FonteIndisponivel):
        providers.DadosDeMercado(token="").historico("PETR4")


def test_hgbrasil(monkeypatch):
    monkeypatch.setattr(providers.requests, "get", lambda url, **k: Resp(
        {"results": {"PETR4": {"symbol": "PETR4", "price": 38.2, "updated_at": "2025-01-03 17:00:00"}}}))
    assert providers.HGBrasil(key="k").historico("petr4") == [("2025-01-03", 38.2)]


def test_yahoo_simbolos():
    assert providers.Yahoo.simbolo("petr4") == "PETR4.SA"
    assert providers.Yahoo.simbolo("BTC") == "BTC-USD"
    assert providers.Yahoo.simbolo("AAPL") == "AAPL"


class FonteFake:
    def __init__(self, nome, serie=None, erro=None):
        self.nome, self.serie, self.erro, self.chamadas = nome, serie, erro, 0

    def historico(self, ticker):
        self.chamadas += 1
        if self.erro:
            raise self.erro
        return self.serie


def test_mercado_usa_proxima_fonte_quando_uma_falha(tmp_path):
    a = FonteFake("brapi", erro=RuntimeError("timeout"))
    b = FonteFake("yahoo", serie=[("2025-01-02", 1.0), ("2025-01-03", 2.0)])
    m = Mercado(db.connect(str(tmp_path / "x.db")), [a, b])
    assert m.historico("ABCD3") == (b.serie, "yahoo")
    # Segunda chamada no mesmo dia vem do cache, sem consultar as fontes.
    m.historico("ABCD3")
    assert a.chamadas == 1 and b.chamadas == 1


def test_mercado_cotacao_atual_complementa_cache(tmp_path):
    conn = db.connect(str(tmp_path / "x.db"))
    Mercado(conn, [FonteFake("yahoo", serie=[("2025-01-02", 1.0), ("2025-01-03", 2.0)])]).historico("ABCD3")
    hg = FonteFake("hgbrasil", serie=[("2025-01-06", 3.0)])
    serie, fonte = Mercado(conn, [hg]).historico("ABCD3", forcar=True)
    assert fonte == "hgbrasil" and serie[-1] == ("2025-01-06", 3.0) and len(serie) == 3


def test_mercado_erro_detalha_fontes(tmp_path):
    m = Mercado(db.connect(str(tmp_path / "x.db")),
                [FonteFake("brapi", erro=providers.FonteIndisponivel("sem token"))])
    with pytest.raises(MarketDataError, match="brapi: sem token"):
        m.historico("ABCD3")
