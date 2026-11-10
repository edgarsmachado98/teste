"""Evolução do patrimônio e rentabilidade pelo método de cotas (TWR).

Para cada mês, desde o primeiro aporte:
  patrimonio   valor de mercado no fim do mês (posição x último fechamento até a data)
  investido    aportes líquidos acumulados (compras - vendas, em dinheiro)
  rent_mes     rentabilidade do mês pelo método Dietz modificado: elimina o efeito do momento
               dos aportes, como no "método de cotas" usado pelos fundos e pelas plataformas
               de consolidação. Proventos recebidos contam como ganho.
  rent_acum    rentabilidade acumulada (meses encadeados)

Ativos sem histórico de cotação (renda fixa, fundos com preço manual) são avaliados por
estimativa: o ganho atual (preço manual / custo) é distribuído linearmente desde a primeira
compra. Eles aparecem em `estimados`.
"""
import calendar
import datetime as dt
from bisect import bisect_right
from collections import defaultdict


def _fim_do_mes(ano, mes):
    return dt.date(ano, mes, calendar.monthrange(ano, mes)[1])


def meses_entre(inicio, fim):
    """Lista de (ano, mes) de inicio até fim (datas ISO), inclusive."""
    a, m = int(inicio[:4]), int(inicio[5:7])
    fa, fm = int(fim[:4]), int(fim[5:7])
    out = []
    while (a, m) <= (fa, fm):
        out.append((a, m))
        m += 1
        if m == 13:
            a, m = a + 1, 1
    return out


class _Historico:
    """Estado (quantidade, custo) de cada ativo ao longo do tempo."""

    def __init__(self, aportes):
        self.eventos = defaultdict(list)  # ticker -> [(data, qtd, custo)] após cada operação
        estado = defaultdict(lambda: [0.0, 0.0])
        for a in sorted(aportes, key=lambda x: (x["data"], x.get("id") or 0)):
            q, p, tx = float(a["quantidade"]), float(a["preco"]), float(a.get("taxas") or 0)
            e = estado[a["ticker"]]
            if a.get("tipo", "compra") == "compra":
                e[0] += q
                e[1] += q * p + tx
            else:
                medio = e[1] / e[0] if e[0] else 0.0
                e[1] -= medio * min(q, e[0])
                e[0] = max(e[0] - q, 0.0)
            self.eventos[a["ticker"]].append((a["data"], e[0], e[1]))
        self.datas = {t: [d for d, _, _ in ev] for t, ev in self.eventos.items()}

    def em(self, ticker, data):
        i = bisect_right(self.datas.get(ticker, []), data)
        if i == 0:
            return 0.0, 0.0
        _, q, c = self.eventos[ticker][i - 1]
        return q, c

    def primeira(self, ticker):
        return self.datas[ticker][0] if self.datas.get(ticker) else None


def _preco_em(serie_datas, serie_valores, data):
    i = bisect_right(serie_datas, data)
    return serie_valores[i - 1] if i else None


def calcular_evolucao(aportes, proventos, series, precos_atuais, hoje):
    """series: {ticker: [(data, fechamento)]}; precos_atuais: {ticker: preço de hoje (inclui manuais)}."""
    if not aportes:
        return {"meses": [], "estimados": []}
    hist = _Historico(aportes)
    tickers = list(hist.eventos)
    idx_series = {t: ([d for d, _ in s], [v for _, v in s]) for t, s in series.items() if s}
    estimados = sorted(t for t in tickers if t not in idx_series)
    hoje_d = dt.date.fromisoformat(hoje)

    # Ganho atual dos ativos sem histórico, para a estimativa linear.
    ganho_estimado = {}
    for t in estimados:
        q, c = hist.em(t, hoje)
        preco = precos_atuais.get(t)
        ganho_estimado[t] = (q * preco / c - 1) if q and c and preco else 0.0

    def patrimonio_em(data):
        total = 0.0
        for t in tickers:
            q, custo = hist.em(t, data)
            if q <= 0:
                continue
            if t in idx_series:
                datas, valores = idx_series[t]
                preco = precos_atuais.get(t) if data >= hoje else _preco_em(datas, valores, data)
                total += q * preco if preco is not None else custo  # antes do histórico: custo
            else:
                inicio = dt.date.fromisoformat(hist.primeira(t))
                dias = max((hoje_d - inicio).days, 1)
                frac = min(max((dt.date.fromisoformat(data) - inicio).days / dias, 0.0), 1.0)
                total += custo * (1 + ganho_estimado[t] * frac)
        return total

    fluxos = defaultdict(list)  # "AAAA-MM" -> [(dia, valor)] (+ compra, - venda)
    for a in aportes:
        valor = float(a["quantidade"]) * float(a["preco"]) + float(a.get("taxas") or 0) \
            if a.get("tipo", "compra") == "compra" else -(float(a["quantidade"]) * float(a["preco"])
                                                            - float(a.get("taxas") or 0))
        fluxos[a["data"][:7]].append((int(a["data"][8:10]), valor))
    rendas = defaultdict(float)
    for p in proventos:
        if p["data_pagamento"] <= hoje:
            rendas[p["data_pagamento"][:7]] += float(p["valor_total"])

    inicio = min(a["data"] for a in aportes)
    meses, anterior, investido, acum = [], 0.0, 0.0, 1.0
    for ano, mes in meses_entre(inicio, hoje):
        chave = f"{ano:04d}-{mes:02d}"
        fim = min(_fim_do_mes(ano, mes), hoje_d).isoformat()
        dias_mes = calendar.monthrange(ano, mes)[1]
        valor = patrimonio_em(fim)
        fl = fluxos.get(chave, [])
        soma_fluxos = sum(v for _, v in fl)
        ponderado = sum(v * (dias_mes - dia + 1) / dias_mes for dia, v in fl)
        renda = rendas.get(chave, 0.0)
        base = anterior + ponderado
        rent = (valor - anterior - soma_fluxos + renda) / base if base > 0 else 0.0
        acum *= 1 + rent
        investido += soma_fluxos
        meses.append({"mes": chave, "patrimonio": valor, "investido": investido, "aporte_liquido": soma_fluxos,
                      "proventos": renda, "rent_mes": rent * 100, "rent_acum": (acum - 1) * 100})
        anterior = valor
    return {"meses": meses, "estimados": estimados}


def acumular(pcts):
    """Rentabilidade acumulada (%) de uma lista de rentabilidades mensais (%)."""
    total = 1.0
    for p in pcts:
        total *= 1 + p / 100
    return (total - 1) * 100


def resumo_periodos(meses, referencias, hoje):
    """Rentabilidade da carteira e das referências: mês atual, ano, 12 meses e desde o início."""
    por_mes = {m["mes"]: m["rent_mes"] for m in meses}
    todos = sorted(por_mes)
    ano = hoje[:4]
    periodos = {"mes": todos[-1:], "ano": [m for m in todos if m.startswith(ano)],
                "12m": todos[-12:], "inicio": todos}
    out = {}
    for nome, lista in periodos.items():
        item = {"carteira": acumular(por_mes[m] for m in lista) if lista else None}
        for ref, serie in referencias.items():
            mapa = dict((r["mes"], r["pct"]) for r in serie)
            if lista and all(m in mapa for m in lista):
                item[ref] = acumular(mapa[m] for m in lista)
            else:
                item[ref] = None
        cdi = item.get("cdi")
        item["pct_cdi"] = item["carteira"] / cdi * 100 if cdi and item["carteira"] is not None and cdi > 0 else None
        out[nome] = item
    return out
