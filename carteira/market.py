"""Obtenção de cotações (Yahoo Finance) com cache em SQLite e modo demonstração."""
import datetime as dt
import hashlib
import math
import os
import random
import re

import requests

YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
HEADERS = {"User-Agent": "Mozilla/5.0 (carteira-aportes)"}
B3_PATTERN = re.compile(r"^[A-Z]{4}\d{1,2}F?$")


class MarketDataError(Exception):
    pass


def simbolo_yahoo(ticker):
    """PETR4 -> PETR4.SA ; BTC -> BTC-USD ; demais permanecem iguais."""
    t = ticker.upper().strip()
    if "." in t or "-" in t or t.startswith("^"):
        return t
    if B3_PATTERN.match(t):
        return t + ".SA"
    if t in {"BTC", "ETH", "SOL", "ADA", "XRP"}:
        return t + "-USD"
    return t


def buscar_yahoo(ticker, periodo="2y"):
    resp = requests.get(YAHOO_URL.format(symbol=simbolo_yahoo(ticker)),
                        params={"range": periodo, "interval": "1d"},
                        headers=HEADERS, timeout=10)
    resp.raise_for_status()
    dados = resp.json()["chart"]
    if dados.get("error") or not dados.get("result"):
        raise MarketDataError(f"Ticker não encontrado: {ticker}")
    r = dados["result"][0]
    ts = r.get("timestamp") or []
    closes = r["indicators"]["quote"][0].get("close") or []
    serie = [(dt.datetime.fromtimestamp(t, dt.timezone.utc).date().isoformat(), float(c))
             for t, c in zip(ts, closes) if c is not None]
    if not serie:
        raise MarketDataError(f"Sem cotações para {ticker}")
    return serie


def serie_simulada(ticker, dias=504, fim=None):
    """Série determinística (movimento browniano geométrico) para modo demonstração."""
    semente = int(hashlib.sha256(ticker.upper().encode()).hexdigest()[:8], 16)
    rng = random.Random(semente)
    preco = 10 + (semente % 9000) / 100
    mu = rng.uniform(-0.05, 0.25) / 252
    sigma = rng.uniform(0.15, 0.45) / math.sqrt(252)
    fim = fim or dt.date.today()
    datas = []
    d = fim
    while len(datas) < dias:
        if d.weekday() < 5:
            datas.append(d)
        d -= dt.timedelta(days=1)
    datas.reverse()
    serie = []
    for d in datas:
        preco *= math.exp(mu - sigma ** 2 / 2 + sigma * rng.gauss(0, 1))
        serie.append((d.isoformat(), round(preco, 2)))
    return serie


def modo_demo():
    return os.environ.get("CARTEIRA_DEMO", "").lower() in {"1", "true", "sim"}


class Mercado:
    def __init__(self, conn, fonte=None):
        self.conn = conn
        self.fonte = fonte or buscar_yahoo

    def _cache_valido(self, ticker):
        row = self.conn.execute(
            "SELECT atualizado FROM precos_meta WHERE ticker = ?", (ticker,)).fetchone()
        return row is not None and row["atualizado"] == dt.date.today().isoformat()

    def _salvar(self, ticker, serie, fonte):
        self.conn.execute("DELETE FROM precos WHERE ticker = ?", (ticker,))
        self.conn.executemany(
            "INSERT INTO precos (ticker, data, fechamento, fonte) VALUES (?, ?, ?, ?)",
            [(ticker, d, c, fonte) for d, c in serie])
        self.conn.execute(
            "INSERT OR REPLACE INTO precos_meta (ticker, atualizado, fonte) VALUES (?, ?, ?)",
            (ticker, dt.date.today().isoformat(), fonte))
        self.conn.commit()

    def _do_cache(self, ticker):
        rows = self.conn.execute(
            "SELECT data, fechamento FROM precos WHERE ticker = ? ORDER BY data",
            (ticker,)).fetchall()
        meta = self.conn.execute(
            "SELECT fonte FROM precos_meta WHERE ticker = ?", (ticker,)).fetchone()
        return [(r["data"], r["fechamento"]) for r in rows], (meta["fonte"] if meta else None)

    def historico(self, ticker, forcar=False):
        """Retorna (serie, fonte). Fonte: 'yahoo', 'cache' (desatualizado) ou 'simulado'."""
        ticker = ticker.upper()
        if not forcar and self._cache_valido(ticker):
            serie, fonte = self._do_cache(ticker)
            if serie:
                return serie, fonte
        if modo_demo():
            serie = serie_simulada(ticker)
            self._salvar(ticker, serie, "simulado")
            return serie, "simulado"
        try:
            serie = self.fonte(ticker)
            self._salvar(ticker, serie, "yahoo")
            return serie, "yahoo"
        except Exception as exc:  # rede indisponível, ticker inválido etc.
            serie, fonte = self._do_cache(ticker)
            if serie:
                return serie, "cache"
            raise MarketDataError(
                f"Não foi possível obter cotações de {ticker}: {exc}. "
                "Informe um preço manual ou ative o modo demonstração (CARTEIRA_DEMO=1).") from exc

    def preco_atual(self, ticker, preco_manual=None):
        if preco_manual:
            return float(preco_manual), "manual"
        try:
            serie, fonte = self.historico(ticker)
            return serie[-1][1], fonte
        except MarketDataError:
            return None, None
