"""Cálculo de posições, rentabilidade, sugestão de aporte e proventos."""
import datetime as dt
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


TIPOS_EVENTO = {"desdobramento": "Desdobramento", "grupamento": "Grupamento",
                "bonificacao": "Bonificação", "outro": "Outro evento"}


def com_eventos(aportes, eventos):
    """Junta aportes e eventos corporativos numa única lista de operações.

    Cada evento vira uma operação {"tipo": "evento", "fator": f}: a quantidade é multiplicada
    por f e o custo total não muda (o preço médio se ajusta). Os eventos ficam depois das
    compras/vendas do mesmo dia (valem para quem tinha o ativo ao fim da data com).
    """
    ops = list(aportes)
    for i, e in enumerate(eventos):
        ops.append({"id": 10 ** 15 + (e.get("id") or i), "data": e["data"], "ticker": e["ticker"],
                    "tipo": "evento", "fator": float(e["fator"]), "evento": e["tipo"],
                    "quantidade": 0.0, "preco": 0.0, "taxas": 0.0})
    return ops


def eh_evento(a):
    return a.get("tipo") == "evento"


# Ajustes de posição (lançados a partir de um relatório, sem a operação real):
#   compra      compra com data aproximada (entra como compra normal)
#   bonificacao ações recebidas, custo informado (pode ser zero); não é saída de dinheiro
#   venda       venda com data aproximada (gera resultado e entra no IR)
#   baixa       saída sem venda (transferência, ajuste): sai pelo preço médio, sem lucro/prejuízo e fora do IR
AJUSTES = {"compra": "Compra (ajuste)", "bonificacao": "Bonificação (ajuste)",
           "venda": "Venda (ajuste)", "baixa": "Baixa sem resultado (ajuste)"}


def eh_baixa(a):
    return a.get("ajuste") == "baixa"


def sem_caixa(a):
    """Ajustes que não movimentam dinheiro (não entram no fluxo financeiro)."""
    return a.get("ajuste") in ("baixa", "bonificacao")


def calcular_posicoes(aportes):
    """Consolida a lista de aportes (compras/vendas) em posições por ticker.

    Usa preço médio ponderado: vendas reduzem a quantidade ao custo médio
    e geram lucro/prejuízo realizado.
    """
    pos = defaultdict(lambda: {"quantidade": 0.0, "custo": 0.0, "realizado": 0.0,
                               "total_aportado": 0.0, "primeiro_aporte": None})
    for a in sorted(aportes, key=lambda x: (x["data"], x.get("id") or 0)):
        p = pos[a["ticker"]]
        if eh_evento(a):
            p["quantidade"] *= a["fator"]
            continue
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
                q = lambda v: f"{v:g}".replace(".", ",")  # noqa: E731
                d = "/".join(reversed(a["data"].split("-")))
                raise ValueError(
                    f"Venda de {q(qtd)} {a['ticker']} em {d} é maior que a quantidade que o sistema "
                    f"conhece nessa data ({q(p['quantidade'])})")
            medio = p["custo"] / p["quantidade"] if p["quantidade"] else 0
            if not eh_baixa(a):  # a baixa sai pelo preço médio: sem resultado
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
            if residual > 0:  # só ativos que ainda estão abaixo do valor que deveriam receber
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
        if eh_evento(a):
            continue
        sinal = 1 if a.get("tipo", "compra") == "compra" else -1
        meses[a["data"][:7]] += sinal * float(a["quantidade"]) * float(a["preco"])
    acumulado = 0.0
    serie = []
    for m in sorted(meses):
        acumulado += meses[m]
        serie.append({"mes": m, "aporte": meses[m], "acumulado": acumulado})
    return serie


# ---------------------------------------------------------------- Proventos

TIPOS_PROVENTO = {
    "dividendo": "Dividendo",
    "jcp": "JCP",
    "rendimento": "Rendimento",
    "amortizacao": "Amortização",
    "outro": "Outro",
}
IR_JCP = 0.15  # JCP sofre retenção de 15% de IR na fonte


def quantidade_na_data(aportes, ticker, data):
    """Quantidade do ativo ao fim do dia `data` (compras - vendas e eventos até a data, inclusive)."""
    qtd = 0.0
    for a in sorted((x for x in aportes if x["ticker"] == ticker and x["data"] <= data),
                    key=lambda x: (x["data"], x.get("id") or 0)):
        if eh_evento(a):
            qtd *= a["fator"]
        else:
            qtd += float(a["quantidade"]) * (1 if a.get("tipo", "compra") == "compra" else -1)
    return max(qtd, 0.0)


def _somar_dias(data_iso, dias):
    return (dt.date.fromisoformat(data_iso) + dt.timedelta(days=dias)).isoformat()


def estimar_proventos(aportes, proventos_fonte, registrados, hoje):
    """Cruza os proventos por ação informados pelas fontes com a sua posição na data com.

    proventos_fonte: {ticker: [{"data_com", "data_pagamento", "valor", "tipo"}]}
    registrados: proventos já lançados (para não duplicar)
    Retorna itens com status 'recebido' (pagamento já ocorreu) ou 'a_receber'.
    JCP é calculado líquido de 15% de IR.
    """
    chaves = {(r["ticker"], r.get("data_com"), r["tipo"]) for r in registrados}
    chaves_pag = {(r["ticker"], r["data_pagamento"], r["tipo"]) for r in registrados}
    itens = []
    for ticker, lista in proventos_fonte.items():
        for p in lista:
            data_com = p["data_com"]
            if data_com > hoje:
                continue  # data com ainda não chegou: posição indefinida
            qtd = quantidade_na_data(aportes, ticker, data_com)
            if qtd <= 0:
                continue
            bruto = float(p["valor"])
            unitario = bruto * (1 - IR_JCP) if p["tipo"] == "jcp" else bruto
            pagamento = p.get("data_pagamento")
            estimado = pagamento is None
            if estimado:
                pagamento = _somar_dias(data_com, 30)
            itens.append({
                "ticker": ticker,
                "tipo": p["tipo"],
                "data_com": data_com,
                "data_pagamento": pagamento,
                "pagamento_estimado": estimado,
                "quantidade": qtd,
                "valor_unitario": unitario,
                "valor_bruto_unitario": bruto,
                "valor_total": round(qtd * unitario, 2),
                "status": "recebido" if pagamento <= hoje else "a_receber",
                "ja_registrado": (ticker, data_com, p["tipo"]) in chaves
                                 or (ticker, pagamento, p["tipo"]) in chaves_pag,
            })
    return sorted(itens, key=lambda x: (x["data_pagamento"], x["ticker"]), reverse=True)


def resumo_proventos(proventos, resumo, hoje, meses=24):
    """Indicadores de renda passiva a partir dos proventos registrados."""
    d_hoje = dt.date.fromisoformat(hoje)
    inicio_12m = _somar_dias(hoje, -365)

    recebidos = [p for p in proventos if p["data_pagamento"] <= hoje]
    total = sum(p["valor_total"] for p in recebidos)
    ult_12m = sum(p["valor_total"] for p in recebidos if p["data_pagamento"] > inicio_12m)

    por_mes = defaultdict(lambda: defaultdict(float))
    for p in recebidos:
        por_mes[p["data_pagamento"][:7]][p["tipo"]] += p["valor_total"]
    serie = []
    ano, mes = d_hoje.year, d_hoje.month
    for _ in range(meses):
        chave = f"{ano:04d}-{mes:02d}"
        serie.append({"mes": chave, **{t: por_mes[chave].get(t, 0.0) for t in TIPOS_PROVENTO}})
        mes -= 1
        if mes == 0:
            mes, ano = 12, ano - 1
    serie.reverse()

    por_ticker = defaultdict(lambda: {"total": 0.0, "ult_12m": 0.0})
    for p in recebidos:
        por_ticker[p["ticker"]]["total"] += p["valor_total"]
        if p["data_pagamento"] > inicio_12m:
            por_ticker[p["ticker"]]["ult_12m"] += p["valor_total"]
    linhas = {l["ticker"]: l for l in resumo["ativos"]}
    ativos = []
    for t, v in sorted(por_ticker.items(), key=lambda x: -x[1]["ult_12m"]):
        l = linhas.get(t, {})
        custo, valor = l.get("custo") or 0, l.get("valor") or 0
        ativos.append({"ticker": t, "total": v["total"], "ult_12m": v["ult_12m"],
                       "yoc_pct": v["ult_12m"] / custo * 100 if custo else None,
                       "dy_pct": v["ult_12m"] / valor * 100 if valor else None})

    return {
        "total": total,
        "ult_12m": ult_12m,
        "media_mensal_12m": ult_12m / 12,
        "a_receber": sum(p["valor_total"] for p in proventos if p["data_pagamento"] > hoje),
        "yoc_pct": ult_12m / resumo["total_custo"] * 100 if resumo["total_custo"] else None,
        "dy_pct": ult_12m / resumo["total_valor"] * 100 if resumo["total_valor"] else None,
        "por_mes": serie,
        "por_ativo": ativos,
    }


def proventos_por_ano(itens):
    """Soma dos proventos por ação agrupados pelo ano da data com."""
    anos = defaultdict(float)
    for p in itens:
        anos[p["data_com"][:4]] += float(p["valor"])
    return [{"ano": a, "valor": v} for a, v in sorted(anos.items())]


def dividend_yield(itens, preco, hoje):
    """DY dos últimos 12 meses (pela data com) em relação ao preço atual."""
    if not preco:
        return None
    inicio = _somar_dias(hoje, -365)
    soma = sum(float(p["valor"]) for p in itens if inicio < p["data_com"] <= hoje)
    return soma / preco


# ---------------------------------------------------------------- Fluxo

def fluxo(aportes, proventos, inicio, fim, hoje):
    """Visão geral de compras, vendas e proventos recebidos no período [inicio, fim].

    O lucro realizado de cada venda usa o preço médio do momento da venda (todas as
    operações anteriores são consideradas, mesmo fora do período).
    """
    pos = defaultdict(lambda: [0.0, 0.0])  # ticker -> [quantidade, custo]
    lancamentos = []
    for a in sorted(aportes, key=lambda x: (x["data"], x.get("id") or 0)):
        p = pos[a["ticker"]]
        if eh_evento(a):
            p[0] *= a["fator"]
            continue
        qtd, preco, taxas = float(a["quantidade"]), float(a["preco"]), float(a.get("taxas") or 0)
        lucro = None
        if a.get("tipo", "compra") == "compra":
            p[0] += qtd
            p[1] += qtd * preco + taxas
            valor = qtd * preco + taxas
        else:
            medio = p[1] / p[0] if p[0] else 0.0
            lucro = qtd * (preco - medio) - taxas
            p[1] -= medio * min(qtd, p[0])
            p[0] = max(p[0] - qtd, 0.0)
            valor = qtd * preco - taxas
        if eh_baixa(a):
            lucro = None
        if inicio <= a["data"] <= fim and not sem_caixa(a):
            lancamentos.append({"data": a["data"], "ticker": a["ticker"], "tipo": a.get("tipo", "compra"),
                                "quantidade": qtd, "preco": preco, "valor": valor, "lucro": lucro,
                                "obs": a.get("obs") or ""})
    for p in proventos:
        if inicio <= p["data_pagamento"] <= min(fim, hoje):
            lancamentos.append({"data": p["data_pagamento"], "ticker": p["ticker"], "tipo": p["tipo"],
                                "quantidade": p.get("quantidade"), "preco": p.get("valor_unitario"),
                                "valor": float(p["valor_total"]), "lucro": None, "obs": p.get("obs") or ""})

    por_mes = defaultdict(lambda: {"compras": 0.0, "vendas": 0.0, "proventos": 0.0})
    por_ativo = defaultdict(lambda: {"compras": 0.0, "vendas": 0.0, "proventos": 0.0, "lucro_realizado": 0.0})
    for l in lancamentos:
        chave = "compras" if l["tipo"] == "compra" else "vendas" if l["tipo"] == "venda" else "proventos"
        por_mes[l["data"][:7]][chave] += l["valor"]
        por_ativo[l["ticker"]][chave] += l["valor"]
        if l["lucro"] is not None:
            por_ativo[l["ticker"]]["lucro_realizado"] += l["lucro"]

    meses = []
    if lancamentos:
        a, m = int(min(por_mes)[:4]), int(min(por_mes)[5:])
        ultimo = max(por_mes)
        while f"{a:04d}-{m:02d}" <= ultimo:
            chave = f"{a:04d}-{m:02d}"
            v = por_mes.get(chave, {"compras": 0.0, "vendas": 0.0, "proventos": 0.0})
            meses.append({"mes": chave, **v, "liquido": v["compras"] - v["vendas"]})
            m += 1
            if m == 13:
                a, m = a + 1, 1

    totais = {k: sum(v[k] for v in por_mes.values()) for k in ("compras", "vendas", "proventos")}
    totais["aporte_liquido"] = totais["compras"] - totais["vendas"]
    totais["lucro_realizado"] = sum(l["lucro"] for l in lancamentos if l["lucro"] is not None)
    totais["operacoes"] = sum(1 for l in lancamentos if l["tipo"] in ("compra", "venda"))
    totais["recebimentos"] = sum(1 for l in lancamentos if l["tipo"] not in ("compra", "venda"))
    return {
        "inicio": inicio, "fim": fim, "totais": totais, "por_mes": meses,
        "por_ativo": sorted(({"ticker": t, **v} for t, v in por_ativo.items()),
                            key=lambda x: -(x["compras"] + x["vendas"] + x["proventos"])),
        "lancamentos": sorted(lancamentos, key=lambda x: (x["data"], x["ticker"]), reverse=True),
    }


# ------------------------------------------------- Visão geral por categoria

def visao_por_categoria(linhas, tamanho_ranking=5):
    """Agrupa as posições abertas por categoria (classe) e monta a classificação dos ativos.

    Para cada ativo e categoria:
      valor            valor de mercado atual
      peso_pct         % da carteira
      variacao_valor   variação do dia em R$ (último fechamento x anterior) e variacao_pct em %
      rentabilidade    valorização (valor - custo) + proventos recebidos, em R$ e % sobre o custo
    Ativos sem cotação do dia (preço manual) entram com variação zero na categoria.
    """
    abertas = [l for l in linhas if l["quantidade"] > 0]
    total = sum(l["valor"] for l in abertas)

    soma_metas = sum(l.get("meta_pct") or 0 for l in abertas) or 0

    def metricas(itens):
        valor = sum(l["valor"] for l in itens)
        custo = sum(l["custo"] for l in itens)
        prov = sum(l.get("proventos_total") or 0 for l in itens)
        var_valor = sum(l["variacao_valor"] or 0 for l in itens if l.get("variacao_valor") is not None)
        com_var = [l for l in itens if l.get("variacao_valor") is not None]
        base_var = sum(l["valor"] - l["variacao_valor"] for l in com_var)
        rent_valor = valor - custo + prov
        meta = sum(l.get("meta_pct") or 0 for l in itens) / soma_metas * 100 if soma_metas else None
        peso = valor / total * 100 if total else 0.0
        return {
            "valor": valor, "custo": custo, "proventos": prov,
            "peso_pct": peso, "meta_pct": meta, "desvio_pct": peso - meta if meta is not None else None,
            "variacao_valor": var_valor if com_var else None,
            "variacao_pct": var_valor / base_var * 100 if com_var and base_var else None,
            "valorizacao_pct": (valor - custo) / custo * 100 if custo else None,
            "rentabilidade_valor": rent_valor,
            "rentabilidade_pct": rent_valor / custo * 100 if custo else None,
        }

    grupos = defaultdict(list)
    for l in abertas:
        grupos[l["classe"]].append(l)
    categorias = []
    for classe, itens in grupos.items():
        ativos = []
        for l in sorted(itens, key=lambda x: -x["valor"]):
            m = metricas([l])
            m["variacao_valor"], m["variacao_pct"] = l.get("variacao_valor"), l.get("variacao_pct")
            ativos.append({"ticker": l["ticker"], "nome": l.get("nome") or "", "quantidade": l["quantidade"],
                           "preco_medio": l["preco_medio"], "preco_atual": l["preco_atual"], **m})
        categorias.append({"classe": classe, "rotulo": CLASSES.get(classe, classe),
                           "quantidade_ativos": len(itens), **metricas(itens), "ativos": ativos})
    categorias.sort(key=lambda c: -c["valor"])

    todos = [a for c in categorias for a in c["ativos"]]
    for a, c in ((a, c) for c in categorias for a in c["ativos"]):
        a["classe"], a["rotulo_classe"] = c["classe"], c["rotulo"]

    def ranking(chave):
        validos = sorted((a for a in todos if a.get(chave) is not None), key=lambda a: -a[chave])
        k = min(tamanho_ranking, (len(validos) + 1) // 2)  # carteiras pequenas: sem repetir ativos nas listas
        restantes = validos[k:]
        return {"melhores": validos[:k], "piores": sorted(restantes[-tamanho_ranking:], key=lambda a: a[chave])}

    return {
        "categorias": categorias,
        "total_categorias": metricas(abertas),
        "ranking": {"rentabilidade": ranking("rentabilidade_pct"), "variacao": ranking("variacao_pct")},
    }


# ------------------------------------------------- Agenda e projeção de renda

def _valor_liquido(tipo, valor):
    return valor * (1 - IR_JCP) if tipo == "jcp" else valor


def agenda_proventos(operacoes, proventos_fonte, registrados, hoje):
    """Próximos recebimentos.

    status:
      a_receber   data com já passou e o pagamento é futuro (valor certo, pela quantidade na data com)
      lancado     provento já registrado com pagamento futuro
      anunciado   data com futura: valor pela quantidade atual, se for mantida até a data com
    """
    posicoes = calcular_posicoes(operacoes)
    itens = []
    estimados = estimar_proventos(operacoes, proventos_fonte, registrados, hoje)
    for e in estimados:
        if e["status"] == "a_receber" and not e["ja_registrado"]:
            itens.append({**e, "status": "a_receber"})
    for r in registrados:
        if r["data_pagamento"] > hoje:
            itens.append({"ticker": r["ticker"], "tipo": r["tipo"], "data_com": r.get("data_com"),
                          "data_pagamento": r["data_pagamento"], "pagamento_estimado": False,
                          "quantidade": r.get("quantidade"), "valor_unitario": r.get("valor_unitario"),
                          "valor_total": float(r["valor_total"]), "status": "lancado"})
    for ticker, lista in proventos_fonte.items():
        qtd = posicoes.get(ticker, {}).get("quantidade", 0)
        if qtd <= 0:
            continue
        for p in lista:
            if p["data_com"] <= hoje:
                continue
            unit = _valor_liquido(p["tipo"], float(p["valor"]))
            pagamento = p.get("data_pagamento") or _somar_dias(p["data_com"], 30)
            itens.append({"ticker": ticker, "tipo": p["tipo"], "data_com": p["data_com"], "data_pagamento": pagamento,
                          "pagamento_estimado": not p.get("data_pagamento"), "quantidade": qtd,
                          "valor_unitario": unit, "valor_total": round(qtd * unit, 2), "status": "anunciado"})
    return sorted(itens, key=lambda x: (x["data_pagamento"], x["ticker"]))


def projecao_renda(operacoes, proventos_fonte, registrados, hoje, meses=12):
    """Renda passiva prevista para os próximos `meses`, mês a mês.

    confirmado: agenda (a receber, lançados e anunciados)
    projetado:  repete os proventos dos últimos 12 meses (por ação/cota, mesma época do ano) com a
                quantidade atual. Ativos sem dados nas fontes usam os proventos registrados.
    """
    posicoes = calcular_posicoes(operacoes)
    agenda = agenda_proventos(operacoes, proventos_fonte, registrados, hoje)
    inicio_mes = hoje[:7]
    d = dt.date.fromisoformat(hoje[:7] + "-01")
    chaves = []
    for _ in range(meses):
        chaves.append(d.strftime("%Y-%m"))
        d = (d + dt.timedelta(days=32)).replace(day=1)
    fim = chaves[-1]
    por_mes = {m: {"mes": m, "confirmado": 0.0, "projetado": 0.0} for m in chaves}
    por_ativo = defaultdict(lambda: {"confirmado": 0.0, "projetado": 0.0})
    ocupados = set()
    for a in agenda:
        m = a["data_pagamento"][:7]
        if inicio_mes <= m <= fim:
            por_mes[m]["confirmado"] += a["valor_total"]
            por_ativo[a["ticker"]]["confirmado"] += a["valor_total"]
            ocupados.add((a["ticker"], m))

    um_ano_atras = _somar_dias(hoje, -365)

    def projetar(ticker, pagamento_passado, valor):
        m = _somar_dias(pagamento_passado, 365)[:7]
        if (ticker, m) in ocupados or not (inicio_mes <= m <= fim) or m == inicio_mes and \
                _somar_dias(pagamento_passado, 365) <= hoje:
            return
        por_mes[m]["projetado"] += valor
        por_ativo[ticker]["projetado"] += valor

    com_fonte = set()
    for ticker, lista in proventos_fonte.items():
        qtd = posicoes.get(ticker, {}).get("quantidade", 0)
        if qtd <= 0 or not lista:
            continue
        com_fonte.add(ticker)
        for p in lista:
            if um_ano_atras < p["data_com"] <= hoje:
                pagamento = p.get("data_pagamento") or _somar_dias(p["data_com"], 30)
                projetar(ticker, pagamento, qtd * _valor_liquido(p["tipo"], float(p["valor"])))
    for r in registrados:
        t = r["ticker"]
        qtd = posicoes.get(t, {}).get("quantidade", 0)
        if t in com_fonte or qtd <= 0 or not (um_ano_atras < r["data_pagamento"] <= hoje):
            continue
        qtd_epoca = r.get("quantidade") or quantidade_na_data(operacoes, t, r.get("data_com") or r["data_pagamento"])
        valor = float(r["valor_total"]) * (qtd / qtd_epoca if qtd_epoca else 1)
        projetar(t, r["data_pagamento"], valor)

    lista_meses = [{**v, "total": v["confirmado"] + v["projetado"]} for v in por_mes.values()]
    total = sum(m["total"] for m in lista_meses)
    return {
        "meses": lista_meses,
        "agenda": agenda,
        "total_12m": total,
        "media_mensal": total / meses,
        "confirmado": sum(m["confirmado"] for m in lista_meses),
        "por_ativo": sorted(({"ticker": t, **v, "total": v["confirmado"] + v["projetado"]}
                             for t, v in por_ativo.items()), key=lambda x: -x["total"]),
    }


def numero_magico(linhas, proventos_fonte, registrados, operacoes, hoje):
    """Para cada FII: quantas cotas fazem o rendimento mensal comprar uma cota nova."""
    um_ano_atras = _somar_dias(hoje, -365)
    out = []
    for l in linhas:
        if l["classe"] != "fii" or l["quantidade"] <= 0 or not l.get("preco_atual"):
            continue
        t = l["ticker"]
        por_cota = sum(float(p["valor"]) for p in proventos_fonte.get(t, []) if um_ano_atras < p["data_com"] <= hoje)
        if not por_cota:  # sem fonte: proventos registrados divididos pela quantidade da época
            for r in registrados:
                if r["ticker"] == t and um_ano_atras < r["data_pagamento"] <= hoje:
                    q = r.get("quantidade") or quantidade_na_data(operacoes, t, r.get("data_com") or r["data_pagamento"])
                    por_cota += float(r["valor_total"]) / q if q else 0
        mensal = por_cota / 12
        if mensal <= 0:
            continue
        necessarias = math.ceil(l["preco_atual"] / mensal)
        out.append({"ticker": t, "preco": l["preco_atual"], "rendimento_mensal_cota": mensal,
                    "cotas_necessarias": necessarias, "cotas_atuais": l["quantidade"],
                    "faltam": max(necessarias - l["quantidade"], 0),
                    "progresso_pct": min(l["quantidade"] / necessarias * 100, 100),
                    "investimento_faltante": max(necessarias - l["quantidade"], 0) * l["preco_atual"]})
    return sorted(out, key=lambda x: -x["progresso_pct"])


# ------------------------------------------------------- metas por categoria

def aplicar_metas_classe(ativos, metas_classe, com_posicao=()):
    """Converte metas por categoria em metas por ativo (rebalanceamento em dois níveis).

    metas_classe: {classe: %}. Dentro de cada categoria, a meta é dividida pelas metas dos ativos
    (proporcionalmente); se nenhum ativo da categoria tiver meta, divide igualmente entre os que
    têm posição. Categorias sem meta ficam com 0%. Sem metas por categoria, nada muda.
    """
    if not metas_classe or not any(v > 0 for v in metas_classe.values()):
        return ativos
    por_classe = defaultdict(list)
    for a in ativos:
        por_classe[a["classe"]].append(a)
    novos = []
    for classe, lista in por_classe.items():
        meta_classe = float(metas_classe.get(classe) or 0)
        soma = sum(float(a.get("meta_pct") or 0) for a in lista)
        candidatos = [a for a in lista if a["ticker"] in com_posicao] or lista
        for a in lista:
            if soma > 0:
                parte = float(a.get("meta_pct") or 0) / soma
            else:
                parte = 1 / len(candidatos) if a in candidatos else 0.0
            novos.append({**a, "meta_pct": meta_classe * parte, "meta_ativo_original": a.get("meta_pct")})
    return novos
