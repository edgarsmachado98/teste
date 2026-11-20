"""Fontes de cotações. Cada fonte é tentada em ordem até uma responder.

Configuração por variáveis de ambiente:

    CARTEIRA_FONTES        ordem das fontes (padrão: brapi,dadosdemercado,yahoo)
    BRAPI_TOKEN            token da brapi.dev (sem token só PETR4, VALE3, MGLU3 e ITUB4 funcionam)
    DADOSDEMERCADO_TOKEN   token da Dados de Mercado (obrigatório para usar essa fonte)
    HGBRASIL_KEY           chave da HG Brasil (só cotação atual, usada como último recurso)
"""
import datetime as dt
import os
import re

import requests

TIMEOUT = 10
HEADERS = {"User-Agent": "carteira-aportes/1.0"}
B3_PATTERN = re.compile(r"^[A-Z]{4}\d{1,2}F?$")
CRIPTO = {"BTC", "ETH", "SOL", "ADA", "XRP"}


class FonteIndisponivel(Exception):
    """A fonte não está configurada ou não tem dados para o ticker."""


def _data_iso(valor):
    """Aceita timestamp Unix (s ou ms) ou texto ISO e devolve AAAA-MM-DD."""
    if isinstance(valor, (int, float)):
        if valor > 1e11:  # milissegundos
            valor /= 1000
        return dt.datetime.fromtimestamp(valor, dt.timezone.utc).date().isoformat()
    return str(valor)[:10]


def _primeiro(d, *chaves):
    for k in chaves:
        if d.get(k) is not None:
            return d[k]
    return None


def _normalizar(pontos):
    """Ordena por data, remove nulos e duplicatas (fica o último valor do dia)."""
    por_data = {}
    for data, fech in pontos:
        if data and fech is not None:
            por_data[data] = float(fech)
    return sorted(por_data.items())


def tipo_provento(rotulo):
    r = (rotulo or "").upper()
    if "JRS" in r or "JCP" in r or "JUROS" in r:
        return "jcp"
    if "RENDIMENTO" in r:
        return "rendimento"
    if "AMORT" in r:
        return "amortizacao"
    return "dividendo"


def fator_evento(tipo, valor):
    """Converte o fator informado pela fonte no multiplicador da quantidade.

    Desdobramento 1:2 -> 2; grupamento 10:1 -> 0,1; bonificação de 10% -> 1,1.
    As fontes não são consistentes (fator x percentual), por isso as faixas abaixo.
    """
    f = float(valor)
    if f <= 0:
        raise ValueError("fator inválido")
    if tipo == "grupamento":
        return f if f < 1 else 1 / f
    if tipo == "bonificacao":
        if f >= 2:          # informado em % (ex.: 10 -> 10%)
            return 1 + f / 100
        if f < 1:           # informado como fração (ex.: 0,1 -> 10%)
            return 1 + f
        return f            # já é o multiplicador (ex.: 1,1)
    return f if f >= 1 else 1 / f  # desdobramento


def tipo_evento(rotulo):
    r = (rotulo or "").upper()
    if "DESDOB" in r or "SPLIT" in r:
        return "desdobramento"
    if "GRUP" in r or "INPLIT" in r:
        return "grupamento"
    if "BONIF" in r:
        return "bonificacao"
    return None


def _num(v):
    """Aceita número ou dict no formato do Yahoo/brapi ({"raw": 1.2, "fmt": "1,2"})."""
    if isinstance(v, dict):
        v = v.get("raw")
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


# Indicadores fundamentalistas normalizados (chave -> rótulo).
CAMPOS_FUNDAMENTOS = {
    "pl": "P/L", "pvp": "P/VP", "lpa": "LPA", "vpa": "VPA", "roe": "ROE",
    "margem_liquida": "Margem líquida", "divida_pl": "Dívida/PL",
    "liquidez_corrente": "Liquidez corrente", "ev_ebitda": "EV/EBITDA",
    "valor_mercado": "Valor de mercado",
}


class Fonte:
    nome = "fonte"
    descricao = ""
    site = ""

    def configurada(self):
        return True

    def historico(self, ticker):
        raise NotImplementedError

    def proventos(self, ticker):
        """Lista de dicts: data_com, data_pagamento, valor (por cota/ação), tipo."""
        raise FonteIndisponivel(f"{self.nome} não fornece proventos")

    def fundamentos(self, ticker):
        """Dict com indicadores normalizados (ver CAMPOS_FUNDAMENTOS)."""
        raise FonteIndisponivel(f"{self.nome} não fornece fundamentos")

    def eventos(self, ticker):
        """Eventos corporativos: [{data_com, tipo, fator, descricao}] (fator multiplica a quantidade)."""
        raise FonteIndisponivel(f"{self.nome} não fornece eventos corporativos")

    def status(self):
        return {"nome": self.nome, "descricao": self.descricao, "site": self.site,
                "configurada": self.configurada()}


class Brapi(Fonte):
    nome = "brapi"
    descricao = "brapi.dev: ações, FIIs, ETFs e BDRs da B3"
    site = "https://brapi.dev"
    URL = "https://brapi.dev/api/quote/{ticker}"
    SANDBOX = {"PETR4", "VALE3", "MGLU3", "ITUB4"}
    # Planos diferentes liberam períodos diferentes; tenta do maior para o menor.
    PERIODOS = ("5y", "2y", "1y", "6mo", "3mo")

    def __init__(self, token=None):
        self.token = token if token is not None else os.environ.get("BRAPI_TOKEN", "")

    def configurada(self):
        return True  # funciona sem token para os tickers de teste

    def _preparar(self, ticker):
        t = ticker.upper()
        if not B3_PATTERN.match(t):
            raise FonteIndisponivel("brapi cobre apenas ativos da B3")
        if not self.token and t not in self.SANDBOX:
            raise FonteIndisponivel("brapi sem BRAPI_TOKEN só atende PETR4, VALE3, MGLU3 e ITUB4")
        headers = dict(HEADERS)
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return t, headers

    def _resultado(self, ticker, params):
        t, headers = self._preparar(ticker)
        resp = requests.get(self.URL.format(ticker=t), headers=headers, timeout=TIMEOUT, params=params)
        if resp.status_code in (400, 401, 402, 403):
            raise FonteIndisponivel(f"brapi recusou a consulta (HTTP {resp.status_code}): {resp.text[:150]}")
        resp.raise_for_status()
        resultados = resp.json().get("results") or []
        if not resultados:
            raise FonteIndisponivel(f"brapi não encontrou {t}")
        return resultados[0]

    def proventos(self, ticker):
        r = self._resultado(ticker, {"dividends": "true"})
        itens = []
        for d in (r.get("dividendsData") or {}).get("cashDividends") or []:
            valor = _num(d.get("rate"))
            data_com = d.get("lastDatePrior") or d.get("approvedOn")
            if not valor or not data_com:
                continue
            pagamento = d.get("paymentDate")
            itens.append({"data_com": _data_iso(data_com),
                          "data_pagamento": _data_iso(pagamento) if pagamento else None,
                          "valor": valor, "tipo": tipo_provento(d.get("label"))})
        if not itens and "dividendsData" not in r:
            raise FonteIndisponivel("brapi não retornou dados de proventos (verifique o plano)")
        return itens

    def eventos(self, ticker):
        r = self._resultado(ticker, {"dividends": "true"})
        dados = r.get("dividendsData") or {}
        if "stockDividends" not in dados:
            raise FonteIndisponivel("brapi não retornou eventos corporativos (verifique o plano)")
        itens = []
        for e in dados.get("stockDividends") or []:
            tipo = tipo_evento(e.get("label"))
            data_com = e.get("lastDatePrior") or e.get("approvedOn")
            fator = _num(e.get("factor"))
            if not tipo or not data_com or not fator:
                continue
            try:
                multiplicador = fator_evento(tipo, fator)
            except ValueError:
                continue
            itens.append({"data_com": _data_iso(data_com), "tipo": tipo, "fator": multiplicador,
                          "descricao": e.get("label") or ""})
        return itens

    def fundamentos(self, ticker):
        try:
            r = self._resultado(ticker, {"fundamental": "true",
                                         "modules": "defaultKeyStatistics,financialData,summaryProfile"})
        except FonteIndisponivel:
            r = self._resultado(ticker, {"fundamental": "true"})  # plano sem módulos
        est = r.get("defaultKeyStatistics") or {}
        fin = r.get("financialData") or {}
        perfil = r.get("summaryProfile") or {}
        divida_pl = _num(fin.get("debtToEquity"))
        out = {
            "nome": r.get("longName") or r.get("shortName"),
            "setor": perfil.get("sector"),
            "pl": _num(r.get("priceEarnings")) or _num(est.get("trailingPE")),
            "pvp": _num(est.get("priceToBook")),
            "lpa": _num(r.get("earningsPerShare")) or _num(est.get("trailingEps")),
            "vpa": _num(est.get("bookValue")),
            "roe": _num(fin.get("returnOnEquity")),
            "margem_liquida": _num(fin.get("profitMargins")) or _num(est.get("profitMargins")),
            # Yahoo/brapi informam dívida/PL em %, ex.: 85.3 -> 0.853
            "divida_pl": divida_pl / 100 if divida_pl is not None else None,
            "liquidez_corrente": _num(fin.get("currentRatio")),
            "ev_ebitda": _num(est.get("enterpriseToEbitda")),
            "valor_mercado": _num(r.get("marketCap")),
        }
        if all(out[k] is None for k in CAMPOS_FUNDAMENTOS):
            raise FonteIndisponivel("brapi não retornou indicadores fundamentalistas")
        return out

    def historico(self, ticker):
        t, headers = self._preparar(ticker)
        ultimo_erro = None
        for periodo in self.PERIODOS:
            resp = requests.get(self.URL.format(ticker=t), headers=headers, timeout=TIMEOUT,
                                params={"range": periodo, "interval": "1d"})
            if resp.status_code in (400, 401, 402, 403):  # período não permitido no plano
                ultimo_erro = f"HTTP {resp.status_code}: {resp.text[:150]}"
                continue
            resp.raise_for_status()
            resultados = resp.json().get("results") or []
            if not resultados:
                raise FonteIndisponivel(f"brapi não encontrou {t}")
            r = resultados[0]
            serie = _normalizar(
                (_data_iso(p.get("date")), _primeiro(p, "adjustedClose", "close"))
                for p in r.get("historicalDataPrice") or [])
            if r.get("regularMarketPrice") is not None:
                # cotação do momento (durante o pregão o histórico diário ainda não tem o dia de hoje)
                hoje = _data_iso(r.get("regularMarketTime") or dt.date.today().isoformat())
                if not serie or serie[-1][0] <= hoje:
                    serie = _normalizar(list(serie) + [(hoje, float(r["regularMarketPrice"]))])
            if serie:
                return serie
            ultimo_erro = "resposta sem histórico"
        raise FonteIndisponivel(f"brapi: {ultimo_erro}")


class DadosDeMercado(Fonte):
    nome = "dadosdemercado"
    descricao = "Dados de Mercado: cotações, índices e dividendos da B3"
    site = "https://www.dadosdemercado.com.br/api/docs"
    URL = "https://api.dadosdemercado.com.br/v1/tickers/{ticker}/quotes"

    def __init__(self, token=None):
        self.token = token if token is not None else os.environ.get("DADOSDEMERCADO_TOKEN", "")

    def configurada(self):
        return bool(self.token)

    def historico(self, ticker):
        if not self.token:
            raise FonteIndisponivel("DADOSDEMERCADO_TOKEN não configurado")
        t = ticker.upper()
        inicio = (dt.date.today() - dt.timedelta(days=730)).isoformat()
        resp = requests.get(self.URL.format(ticker=t), timeout=TIMEOUT,
                            headers={**HEADERS, "Authorization": f"Bearer {self.token}"},
                            params={"period_init": inicio})
        if resp.status_code == 404:
            raise FonteIndisponivel(f"Dados de Mercado não encontrou {t}")
        resp.raise_for_status()
        dados = resp.json()
        if isinstance(dados, dict):
            dados = _primeiro(dados, "data", "quotes", "results") or []
        serie = _normalizar(
            (_data_iso(_primeiro(p, "date", "data", "trade_date")),
             _primeiro(p, "adj_close", "close", "fechamento", "price"))
            for p in dados if isinstance(p, dict))
        if not serie:
            raise FonteIndisponivel("Dados de Mercado retornou histórico vazio")
        return serie


class Yahoo(Fonte):
    nome = "yahoo"
    descricao = "Yahoo Finance: B3, exterior e cripto (sem token)"
    site = "https://finance.yahoo.com"
    URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"

    @staticmethod
    def simbolo(ticker):
        """PETR4 -> PETR4.SA ; BTC -> BTC-USD ; demais permanecem iguais."""
        t = ticker.upper().strip()
        if "." in t or "-" in t or t.startswith("^"):
            return t
        if B3_PATTERN.match(t):
            return t + ".SA"
        if t in CRIPTO:
            return t + "-USD"
        return t

    def historico(self, ticker):
        resp = requests.get(self.URL.format(symbol=self.simbolo(ticker)),
                            params={"range": "5y", "interval": "1d"},
                            headers={"User-Agent": "Mozilla/5.0"}, timeout=TIMEOUT)
        resp.raise_for_status()
        dados = resp.json()["chart"]
        if dados.get("error") or not dados.get("result"):
            raise FonteIndisponivel(f"Yahoo não encontrou {ticker}")
        r = dados["result"][0]
        closes = (r.get("indicators", {}).get("quote") or [{}])[0].get("close") or []
        serie = _normalizar((_data_iso(t), c) for t, c in zip(r.get("timestamp") or [], closes))
        if not serie:
            raise FonteIndisponivel(f"Yahoo sem cotações para {ticker}")
        return serie

    def proventos(self, ticker):
        """Dividendos por ação. O Yahoo informa a data ex; a data com é o dia útil anterior.
        Não há data de pagamento nem distinção dividendo/JCP."""
        resp = requests.get(self.URL.format(symbol=self.simbolo(ticker)),
                            params={"range": "5y", "interval": "1mo", "events": "div"},
                            headers={"User-Agent": "Mozilla/5.0"}, timeout=TIMEOUT)
        resp.raise_for_status()
        dados = resp.json()["chart"]
        if dados.get("error") or not dados.get("result"):
            raise FonteIndisponivel(f"Yahoo não encontrou {ticker}")
        eventos = (dados["result"][0].get("events") or {}).get("dividends") or {}
        itens = []
        for ev in eventos.values():
            ex = dt.date.fromisoformat(_data_iso(ev["date"]))
            com = ex - dt.timedelta(days=3 if ex.weekday() == 0 else 1)
            itens.append({"data_com": com.isoformat(), "data_pagamento": None,
                          "valor": float(ev["amount"]), "tipo": "dividendo"})
        return sorted(itens, key=lambda x: x["data_com"])

    def eventos(self, ticker):
        """Desdobramentos e grupamentos (o Yahoo não distingue bonificação de desdobramento)."""
        resp = requests.get(self.URL.format(symbol=self.simbolo(ticker)),
                            params={"range": "5y", "interval": "1mo", "events": "split"},
                            headers={"User-Agent": "Mozilla/5.0"}, timeout=TIMEOUT)
        resp.raise_for_status()
        dados = resp.json()["chart"]
        if dados.get("error") or not dados.get("result"):
            raise FonteIndisponivel(f"Yahoo não encontrou {ticker}")
        itens = []
        for ev in ((dados["result"][0].get("events") or {}).get("splits") or {}).values():
            num, den = float(ev.get("numerator") or 0), float(ev.get("denominator") or 0)
            if not num or not den:
                continue
            ex = dt.date.fromisoformat(_data_iso(ev["date"]))
            com = ex - dt.timedelta(days=3 if ex.weekday() == 0 else 1)
            fator = num / den
            itens.append({"data_com": com.isoformat(), "fator": fator,
                          "tipo": "desdobramento" if fator > 1 else "grupamento",
                          "descricao": ev.get("splitRatio") or f"{num:g}:{den:g}"})
        return sorted(itens, key=lambda x: x["data_com"])


class HGBrasil(Fonte):
    """Só cotação atual (com atraso de 15 min a 1 h). Usada quando nenhuma fonte de histórico responde."""
    nome = "hgbrasil"
    descricao = "HG Brasil: cotação atual com atraso (sem histórico)"
    site = "https://hgbrasil.com"
    URL = "https://api.hgbrasil.com/finance/stock_price"

    def __init__(self, key=None):
        self.key = key if key is not None else os.environ.get("HGBRASIL_KEY", "")

    def configurada(self):
        return bool(self.key)

    def historico(self, ticker):
        if not self.key:
            raise FonteIndisponivel("HGBRASIL_KEY não configurada")
        t = ticker.upper()
        resp = requests.get(self.URL, params={"key": self.key, "symbol": t.lower()},
                            headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        resultados = resp.json().get("results") or {}
        r = resultados.get(t) or resultados.get(t.lower()) or {}
        if r.get("error") or r.get("price") is None:
            raise FonteIndisponivel(r.get("message") or f"HG Brasil não encontrou {t}")
        data = _data_iso(r.get("updated_at") or dt.date.today().isoformat())
        return [(data, float(r["price"]))]


DISPONIVEIS = {c.nome: c for c in (Brapi, DadosDeMercado, Yahoo, HGBrasil)}
ORDEM_PADRAO = "brapi,dadosdemercado,yahoo,hgbrasil"


def fontes_configuradas():
    nomes = os.environ.get("CARTEIRA_FONTES") or ORDEM_PADRAO
    fontes = []
    for n in (x.strip().lower() for x in nomes.split(",")):
        if n in DISPONIVEIS:
            fontes.append(DISPONIVEIS[n]())
    return fontes
