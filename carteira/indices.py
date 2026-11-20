"""Índices de referência mensais: CDI e IPCA (Banco Central) e Ibovespa.

Fontes:
- CDI: série 4391 do SGS/Banco Central ("CDI acumulado no mês", % a.m.)
- IPCA: série 433 do SGS/Banco Central (variação mensal, %)
- Ibovespa: fechamentos diários do índice (^BVSP) pelas fontes de cotação do sistema

Cada série é guardada em cache por um dia (tabela cache_dados).
"""
import datetime as dt
import json
import random

import requests

from carteira.market import MarketDataError, modo_demo, serie_simulada

BCB_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados"
SERIES_BCB = {"cdi": 4391, "ipca": 433}
NOMES = {"cdi": "CDI", "ipca": "IPCA", "ibov": "Ibovespa"}


SERIES_DIARIAS = {"cdi": 12, "selic": 11}  # % ao dia, por dia útil


def buscar_bcb_bruto(codigo, inicio, fim):
    """Série do SGS como [(data ISO, valor)]."""
    resp = requests.get(BCB_URL.format(codigo=codigo), timeout=20, params={
        "formato": "json",
        "dataInicial": dt.date.fromisoformat(inicio).strftime("%d/%m/%Y"),
        "dataFinal": dt.date.fromisoformat(fim).strftime("%d/%m/%Y")})
    resp.raise_for_status()
    out = []
    for item in resp.json():
        d, m, a = item["data"].split("/")
        out.append((f"{a}-{m}-{d}", float(str(item["valor"]).replace(",", "."))))
    return out


def buscar_bcb(codigo, inicio, fim):
    """Série mensal do SGS como [{"mes": "AAAA-MM", "pct": float}]."""
    return [{"mes": d[:7], "pct": v} for d, v in buscar_bcb_bruto(codigo, inicio, fim)]


def _diaria_simulada(nome, inicio, fim):
    rng = random.Random("diaria-" + nome)
    d, fim_d, out = dt.date.fromisoformat(inicio), dt.date.fromisoformat(fim), []
    while d <= fim_d:
        if d.weekday() < 5:
            out.append((d.isoformat(), round(0.0455 + rng.uniform(-0.002, 0.002), 6)))
        d += dt.timedelta(days=1)
    return out


def _simulado(nome, inicio, fim):
    rng = random.Random(nome)
    a, m = int(inicio[:4]), int(inicio[5:7])
    out = []
    while f"{a:04d}-{m:02d}" <= fim[:7]:
        base = {"cdi": 0.95, "ipca": 0.40}[nome]
        out.append({"mes": f"{a:04d}-{m:02d}", "pct": round(base + rng.uniform(-0.12, 0.12), 4)})
        m += 1
        if m == 13:
            a, m = a + 1, 1
    return out


def mensal_de_diario(serie):
    """Retorno mensal (%) a partir de fechamentos diários [(data, valor)]."""
    fechamento = {}
    for d, v in serie:
        fechamento[d[:7]] = v  # o último do mês prevalece (série ordenada)
    meses = sorted(fechamento)
    return [{"mes": m, "pct": (fechamento[m] / fechamento[a] - 1) * 100}
            for a, m in zip(meses, meses[1:]) if fechamento[a]]


class Indices:
    def __init__(self, conn, mercado, fonte_bcb=None):
        """fonte_bcb(codigo, inicio, fim) -> [(data ISO, valor)] (padrão: API do Banco Central)."""
        self.conn, self.mercado = conn, mercado
        self.fonte_bcb_bruta = fonte_bcb or buscar_bcb_bruto
        self.fonte_bcb = lambda c, i, f: [{"mes": d[:7], "pct": v} for d, v in self.fonte_bcb_bruta(c, i, f)]

    def diaria(self, nome, inicio, fim):
        """CDI ou Selic diários [(data, % a.d.)] desde `inicio` (cache por ano inicial)."""
        if modo_demo():
            return _diaria_simulada(nome, inicio, fim)
        codigo = SERIES_DIARIAS[nome]
        ini = f"{inicio[:4]}-01-01"
        dados = self._cache(f"BCB:{codigo}:{ini}", lambda: self.fonte_bcb_bruta(codigo, ini, fim))
        return [tuple(x) for x in dados if x[0] >= inicio]

    def ipca_mensal(self, inicio, fim):
        """{"AAAA-MM": %} do IPCA desde o mês de `inicio`."""
        if modo_demo():
            return {x["mes"]: x["pct"] for x in _simulado("ipca", inicio, fim)}
        ini = f"{inicio[:4]}-01-01"
        dados = self._cache(f"BCB:433:{ini}", lambda: self.fonte_bcb(433, ini, fim))
        return {x["mes"]: x["pct"] for x in dados}

    def _cache(self, chave, gerar):
        hoje = dt.date.today().isoformat()
        row = self.conn.execute("SELECT * FROM cache_dados WHERE ticker = ? AND tipo = 'indice'",
                                (chave,)).fetchone()
        if row and row["atualizado"] == hoje:
            return json.loads(row["conteudo"])
        try:
            dados = gerar()
        except Exception:
            if row:
                return json.loads(row["conteudo"])  # sem rede: usa o último valor salvo
            raise
        self.conn.execute("INSERT OR REPLACE INTO cache_dados (ticker, tipo, atualizado, fonte, conteudo) "
                          "VALUES (?, 'indice', ?, ?, ?)", (chave, hoje, "bcb", json.dumps(dados)))
        self.conn.commit()
        return dados

    def series(self, inicio, fim):
        """{"cdi": [...], "ipca": [...], "ibov": [...]} e as falhas por índice."""
        out, falhas = {}, {}
        for nome, codigo in SERIES_BCB.items():
            try:
                if modo_demo():
                    out[nome] = _simulado(nome, inicio, fim)
                else:
                    # pede desde janeiro do ano inicial, para o cache servir a outras consultas
                    ini = f"{inicio[:4]}-01-01"
                    dados = self._cache(f"BCB:{codigo}:{ini}", lambda c=codigo, i=ini: self.fonte_bcb(c, i, fim))
                    out[nome] = [d for d in dados if inicio[:7] <= d["mes"] <= fim[:7]]
            except Exception as e:
                falhas[nome] = f"{NOMES[nome]}: {e}"
        try:
            serie = serie_simulada("^BVSP") if modo_demo() else self.mercado.historico("^BVSP")[0]
            out["ibov"] = [d for d in mensal_de_diario(serie) if inicio[:7] <= d["mes"] <= fim[:7]]
        except (MarketDataError, Exception) as e:
            falhas["ibov"] = f"Ibovespa: {e}"
        return out, falhas
