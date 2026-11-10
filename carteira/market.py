"""Obtenção de cotações com várias fontes, cache em SQLite e modo demonstração."""
import datetime as dt
import hashlib
import json
import math
import os
import random
import re
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


def proventos_simulados(ticker):
    """Proventos determinísticos para o modo demonstração.

    Tickers terminados em 11 pagam mensalmente (como FIIs); ações, trimestralmente.
    Ativos fora do padrão da B3 (ex.: Tesouro) não pagam.
    """
    t = ticker.upper()
    if not re.match(r"^[A-Z]{4}\d{1,2}$", t):
        return []
    serie = serie_simulada(t)
    rng = random.Random(t)
    mensal = t.endswith("11")
    rendimento_anual = rng.uniform(0.08, 0.11) if mensal else rng.uniform(0.03, 0.08)
    passo = 1 if mensal else 3
    itens = []
    hoje = dt.date.today()
    precos = dict(serie)
    datas = sorted(precos)
    ano, mes = dt.date.fromisoformat(datas[0]).year, dt.date.fromisoformat(datas[0]).month
    while dt.date(ano, mes, 1) <= hoje:
        data_com = dt.date(ano, mes, 1 if mensal else 15)
        while data_com.weekday() >= 5:
            data_com += dt.timedelta(days=1)
        anteriores = [d for d in datas if d <= data_com.isoformat()]
        if anteriores:
            preco = precos[anteriores[-1]]
            valor = round(preco * rendimento_anual / (12 / passo) * rng.uniform(0.85, 1.15), 4)
            pagamento = data_com + dt.timedelta(days=14 if mensal else 30)
            tipo = "rendimento" if mensal else ("jcp" if rng.random() < 0.3 else "dividendo")
            itens.append({"data_com": data_com.isoformat(), "data_pagamento": pagamento.isoformat(),
                          "valor": valor, "tipo": tipo})
        mes += passo
        while mes > 12:
            mes -= 12
            ano += 1
    return itens


def eventos_simulados(ticker):
    """Modo demonstração: uma bonificação de 10% em ITUB4 e um desdobramento 1:2 em WEGE3."""
    t = ticker.upper()
    if t == "ITUB4":
        return [{"data_com": "2025-12-19", "tipo": "bonificacao", "fator": 1.1, "descricao": "BONIFICACAO 10%"}]
    if t == "WEGE3":
        return [{"data_com": "2026-03-16", "tipo": "desdobramento", "fator": 2.0, "descricao": "DESDOBRAMENTO 1:2"}]
    return []


def fundamentos_simulados(ticker):
    rng = random.Random("fund-" + ticker.upper())
    preco = serie_simulada(ticker)[-1][1]
    pl = rng.uniform(4, 30)
    pvp = rng.uniform(0.6, 4)
    return {
        "nome": f"{ticker.upper()} (simulado)",
        "setor": {"ITUB4": "Bancos", "BBAS3": "Bancos", "VALE3": "Mineração", "WEGE3": "Bens industriais",
                  "TAEE11": "Energia elétrica", "PETR4": "Petróleo e gás", "EGIE3": "Energia elétrica",
                  "SAPR11": "Saneamento"}.get(ticker.upper(), "Outros"),
        "pl": pl, "pvp": pvp, "lpa": preco / pl, "vpa": preco / pvp,
        "roe": pvp / pl, "margem_liquida": rng.uniform(0.03, 0.35),
        "divida_pl": rng.uniform(0, 2), "liquidez_corrente": rng.uniform(0.7, 3),
        "ev_ebitda": rng.uniform(3, 18), "valor_mercado": preco * rng.uniform(1e8, 5e9),
    }


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

    # ---- Proventos e fundamentos (mesma lógica de fallback, com cache em JSON) ----
    def _consultar(self, ticker, metodo, simulador, forcar=False):
        ticker = ticker.upper()
        hoje = dt.date.today().isoformat()
        row = self.conn.execute("SELECT * FROM cache_dados WHERE ticker = ? AND tipo = ?",
                                (ticker, metodo)).fetchone()
        if row and row["atualizado"] == hoje and not forcar:
            return json.loads(row["conteudo"]), row["fonte"]
        erros = []
        if modo_demo():
            candidatos = [("simulado", simulador)]
        else:
            candidatos = [(f.nome, getattr(f, metodo, None)) for f in self.fontes]
        for nome, func in candidatos:
            if func is None:
                continue
            try:
                dados = func(ticker)
            except Exception as exc:  # FonteIndisponivel, rede, formato inesperado...
                erros.append(f"{nome}: {exc}")
                continue
            self.conn.execute(
                "INSERT OR REPLACE INTO cache_dados (ticker, tipo, atualizado, fonte, conteudo) "
                "VALUES (?, ?, ?, ?, ?)", (ticker, metodo, hoje, nome, json.dumps(dados)))
            self.conn.commit()
            return dados, nome
        if row:
            return json.loads(row["conteudo"]), "cache"
        raise MarketDataError(f"Sem {metodo} para {ticker} ({'; '.join(erros) or 'nenhuma fonte disponível'}).")

    def proventos(self, ticker, forcar=False):
        """Proventos por ação/cota informados pelas fontes: (lista, fonte)."""
        return self._consultar(ticker, "proventos", proventos_simulados, forcar)

    def fundamentos(self, ticker, forcar=False):
        return self._consultar(ticker, "fundamentos", fundamentos_simulados, forcar)

    def eventos(self, ticker, forcar=False):
        """Eventos corporativos informados pelas fontes: (lista, fonte)."""
        return self._consultar(ticker, "eventos", eventos_simulados, forcar)

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
