"""Cálculo de posições, rentabilidade e sugestão de aporte (rebalanceamento)."""
import math
from collections import defaultdict

# Classes que só podem ser compradas em unidades inteiras.
CLASSES_INTEIRAS = {"acao", "fii", "etf", "bdr"}

CLASSES = {
    "acao": "Ação",
    "fii": "FII",
    "etf": "ETF",
    "bdr": "BDR",
    "renda_fixa": "Renda Fixa",
    "cripto": "Cripto",
    "exterior": "Exterior",
    "outro": "Outro",
}


def _trunc(x, casas=8):
    """Arredonda para baixo, garantindo que a sugestão nunca ultrapasse o valor do aporte."""
    f = 10 ** casas
    return math.floor(x * f) / f


def calcular_posicoes(aportes):
    """Consolida a lista de aportes (compras/vendas) em posições por ticker.

    Usa preço médio ponderado: vendas reduzem a quantidade ao custo médio
    e geram lucro/prejuízo realizado.
    """
    pos = defaultdict(lambda: {"quantidade": 0.0, "custo": 0.0, "realizado": 0.0,
                               "total_aportado": 0.0, "primeiro_aporte": None})
    for a in sorted(aportes, key=lambda x: (x["data"], x.get("id") or 0)):
        p = pos[a["ticker"]]
        qtd = float(a["quantidade"])
        preco = float(a["preco"])
        taxas = float(a.get("taxas") or 0)
        if p["primeiro_aporte"] is None:
            p["primeiro_aporte"] = a["data"]
        if a.get("tipo", "compra") == "compra":
            p["quantidade"] += qtd
            p["custo"] += qtd * preco + taxas
            p["total_aportado"] += qtd * preco + taxas
        else:
            if qtd > p["quantidade"] + 1e-9:
                raise ValueError(
                    f"Venda de {qtd} {a['ticker']} em {a['data']} excede a posição "
                    f"({p['quantidade']})")
            medio = p["custo"] / p["quantidade"] if p["quantidade"] else 0
            p["realizado"] += qtd * (preco - medio) - taxas
            p["quantidade"] -= qtd
            p["custo"] -= qtd * medio
            if p["quantidade"] < 1e-9:
                p["quantidade"], p["custo"] = 0.0, 0.0
    out = {}
    for t, p in pos.items():
        p["preco_medio"] = p["custo"] / p["quantidade"] if p["quantidade"] else 0.0
        out[t] = p
    return out


def resumo_carteira(ativos, aportes, precos_atuais):
    """Monta a visão da carteira com valor de mercado, P/L e alocação vs. meta."""
    posicoes = calcular_posicoes(aportes)
    ativos_por_ticker = {a["ticker"]: a for a in ativos}
    tickers = sorted(set(ativos_por_ticker) | set(posicoes))

    linhas = []
    for t in tickers:
        p = posicoes.get(t, {"quantidade": 0.0, "custo": 0.0, "realizado": 0.0,
                             "preco_medio": 0.0, "total_aportado": 0.0})
        a = ativos_por_ticker.get(t, {})
        preco = precos_atuais.get(t)
        valor = p["quantidade"] * preco if preco is not None else p["custo"]
        lucro = valor - p["custo"]
        linhas.append({
            "ticker": t,
            "nome": a.get("nome") or "",
            "classe": a.get("classe") or "outro",
            "meta_pct": float(a.get("meta_pct") or 0),
            "quantidade": p["quantidade"],
            "preco_medio": p["preco_medio"],
            "preco_atual": preco,
            "custo": p["custo"],
            "valor": valor,
            "lucro": lucro,
            "lucro_pct": (lucro / p["custo"] * 100) if p["custo"] else 0.0,
            "realizado": p["realizado"],
            "total_aportado": p["total_aportado"],
        })

    total = sum(l["valor"] for l in linhas)
    soma_metas = sum(l["meta_pct"] for l in linhas)
    for l in linhas:
        l["peso_pct"] = l["valor"] / total * 100 if total else 0.0
        l["meta_norm_pct"] = l["meta_pct"] / soma_metas * 100 if soma_metas else 0.0
        l["desvio_pct"] = l["peso_pct"] - l["meta_norm_pct"]

    por_classe = defaultdict(float)
    for l in linhas:
        por_classe[l["classe"]] += l["valor"]

    custo = sum(l["custo"] for l in linhas)
    return {
        "ativos": linhas,
        "total_valor": total,
        "total_custo": custo,
        "lucro": total - custo,
        "lucro_pct": (total - custo) / custo * 100 if custo else 0.0,
        "realizado": sum(l["realizado"] for l in linhas),
        "soma_metas": soma_metas,
        "por_classe": [{"classe": c, "rotulo": CLASSES.get(c, c), "valor": v,
                        "pct": v / total * 100 if total else 0.0}
                       for c, v in sorted(por_classe.items(), key=lambda x: -x[1])],
    }


def sugerir_aporte(resumo, valor_aporte):
    """Distribui um novo aporte entre os ativos para aproximar a carteira da meta.

    Estratégia: calcula o valor-alvo de cada ativo considerando o patrimônio
    *após* o aporte; o dinheiro vai primeiro para os ativos abaixo da meta,
    proporcionalmente ao déficit. Depois converte em quantidades (inteiras para
    ações/FIIs/ETFs) e tenta reaproveitar a sobra comprando unidades extras dos
    ativos mais defasados que ainda caibam no saldo.
    """
    if valor_aporte <= 0:
        raise ValueError("O valor do aporte deve ser positivo.")
    elegiveis = [l for l in resumo["ativos"]
                 if l["meta_pct"] > 0 and l["preco_atual"]]
    if not elegiveis:
        raise ValueError("Nenhum ativo com meta de alocação e preço disponível.")

    soma_metas = sum(l["meta_pct"] for l in elegiveis)
    total_apos = sum(l["valor"] for l in resumo["ativos"]) + valor_aporte

    deficits = {}
    for l in elegiveis:
        alvo = l["meta_pct"] / soma_metas * total_apos
        deficits[l["ticker"]] = max(0.0, alvo - l["valor"])
    soma_def = sum(deficits.values())

    alocado = {}
    if soma_def <= 0:
        for l in elegiveis:
            alocado[l["ticker"]] = valor_aporte * l["meta_pct"] / soma_metas
    elif soma_def >= valor_aporte:
        for t, d in deficits.items():
            alocado[t] = valor_aporte * d / soma_def
    else:
        sobra = valor_aporte - soma_def
        for l in elegiveis:
            alocado[l["ticker"]] = deficits[l["ticker"]] + sobra * l["meta_pct"] / soma_metas

    por_ticker = {l["ticker"]: l for l in elegiveis}
    compras = {}
    gasto = 0.0
    for t, v in alocado.items():
        l = por_ticker[t]
        inteiro = l["classe"] in CLASSES_INTEIRAS
        qtd = math.floor(v / l["preco_atual"]) if inteiro else _trunc(v / l["preco_atual"])
        compras[t] = qtd
        gasto += qtd * l["preco_atual"]

    # Reaproveita a sobra: compra 1 unidade do ativo com maior déficit residual que caiba.
    saldo = valor_aporte - gasto
    while True:
        candidatos = []
        for t, l in por_ticker.items():
            if l["classe"] not in CLASSES_INTEIRAS or l["preco_atual"] > saldo + 1e-9:
                continue
            residual = alocado[t] - compras[t] * l["preco_atual"]
            candidatos.append((residual, t))
        if not candidatos:
            break
        _, t = max(candidatos)
        compras[t] += 1
        saldo -= por_ticker[t]["preco_atual"]

    # O que ainda sobrar vai para ativos fracionáveis (cripto, renda fixa...), se houver.
    fracionaveis = [l for l in elegiveis if l["classe"] not in CLASSES_INTEIRAS]
    if saldo > 0.01 and fracionaveis:
        soma_f = sum(l["meta_pct"] for l in fracionaveis)
        for l in fracionaveis:
            compras[l["ticker"]] += _trunc(saldo * l["meta_pct"] / soma_f / l["preco_atual"])
        saldo = valor_aporte - sum(compras[t] * por_ticker[t]["preco_atual"] for t in compras)

    sugestoes = []
    for t in sorted(compras, key=lambda x: -compras[x] * por_ticker[x]["preco_atual"]):
        l = por_ticker[t]
        valor = compras[t] * l["preco_atual"]
        novo_valor = l["valor"] + valor
        sugestoes.append({
            "ticker": t,
            "classe": l["classe"],
            "preco": l["preco_atual"],
            "quantidade": compras[t],
            "valor": valor,
            "peso_atual_pct": l["peso_pct"],
            "peso_apos_pct": novo_valor / total_apos * 100,
            "meta_pct": l["meta_pct"] / soma_metas * 100,
        })
    return {
        "valor_aporte": valor_aporte,
        "valor_utilizado": valor_aporte - saldo,
        "sobra": saldo,
        "sugestoes": [s for s in sugestoes if s["quantidade"] > 0],
    }


def aportes_por_mes(aportes):
    """Série mensal de aportes líquidos e do total investido acumulado."""
    meses = defaultdict(float)
    for a in aportes:
        sinal = 1 if a.get("tipo", "compra") == "compra" else -1
        meses[a["data"][:7]] += sinal * float(a["quantidade"]) * float(a["preco"])
    acumulado = 0.0
    serie = []
    for m in sorted(meses):
        acumulado += meses[m]
        serie.append({"mes": m, "aporte": meses[m], "acumulado": acumulado})
    return serie
