"""Obtenção de cotações com várias fontes, cache em SQLite e modo demonstração."""
import datetime as dt
import hashlib
import math
import os
import random
from carteira.providers import FonteIndisponivel, Yahoo, fontes_configuradas


class MarketDataError(Exception):
    pass


simbolo_yahoo = Yahoo.simbolo


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


class _FonteFuncao:
    """Adapta uma função ticker -> série para a interface de fonte (usado nos testes)."""
    nome = "personalizada"

    def __init__(self, func, nome=None):
        self.func, self.nome = func, nome or self.nome

    def historico(self, ticker):
        return self.func(ticker)


class Mercado:
    def __init__(self, conn, fontes=None):
        self.conn = conn
        if fontes is None:
            fontes = fontes_configuradas()
        elif callable(fontes):
            fontes = [_FonteFuncao(fontes, "yahoo")]
        self.fontes = list(fontes)

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
        """Retorna (serie, fonte).

        Fonte: nome do provedor que respondeu (brapi, dadosdemercado, yahoo, hgbrasil),
        'cache' (último histórico salvo, desatualizado) ou 'simulado' (modo demonstração).
        """
        ticker = ticker.upper()
        if not forcar and self._cache_valido(ticker):
            serie, fonte = self._do_cache(ticker)
            if serie:
                return serie, fonte
        if modo_demo():
            serie = serie_simulada(ticker)
            self._salvar(ticker, serie, "simulado")
            return serie, "simulado"
        erros = []
        for fonte in self.fontes:
            try:
                serie = fonte.historico(ticker)
            except FonteIndisponivel as exc:
                erros.append(f"{fonte.nome}: {exc}")
                continue
            except Exception as exc:  # rede indisponível, HTTP 5xx, JSON inesperado...
                erros.append(f"{fonte.nome}: {exc.__class__.__name__}: {exc}")
                continue
            if not serie:
                erros.append(f"{fonte.nome}: sem dados")
                continue
            if len(serie) == 1:
                # Fonte só de cotação atual: acrescenta ao histórico que já temos.
                antigo, _ = self._do_cache(ticker)
                serie = sorted(dict(antigo + serie).items())
            self._salvar(ticker, serie, fonte.nome)
            return serie, fonte.nome
        serie, _ = self._do_cache(ticker)
        if serie:
            return serie, "cache"
        detalhes = "; ".join(erros) or "nenhuma fonte configurada"
        raise MarketDataError(
            f"Não foi possível obter cotações de {ticker} ({detalhes}). "
            "Informe um preço manual ou ative o modo demonstração (CARTEIRA_DEMO=1).")

    def status_fontes(self):
        return [f.status() if hasattr(f, "status") else {"nome": f.nome, "configurada": True}
                for f in self.fontes]

    def preco_atual(self, ticker, preco_manual=None):
        if preco_manual:
            return float(preco_manual), "manual"
        try:
            serie, fonte = self.historico(ticker)
            return serie[-1][1], fonte
        except MarketDataError:
            return None, None
