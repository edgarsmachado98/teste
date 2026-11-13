"""Imposto de Renda sobre renda variável (pessoa física) e relatório para a declaração anual.

Regras aplicadas (conferir sempre com a legislação vigente e um contador):

Apuração mensal das vendas
  - Operações comuns (swing trade) de ações, ETFs e BDRs: 15% sobre o lucro líquido do mês.
    Ações: isento quando o total de vendas de ações no mês é até R$ 20.000 (a isenção não vale para
    ETFs, BDRs, FIIs nem day trade). Prejuízos em meses isentos continuam compensáveis.
  - Day trade (compra e venda do mesmo ativo no mesmo dia): 20%, com prejuízos compensáveis só
    com lucros de day trade; IRRF de 1% sobre o lucro.
  - FIIs: 20% sobre o lucro, prejuízos compensáveis só com FIIs.
  - Criptoativos: 15% sobre o lucro quando as vendas do mês passam de R$ 35.000.
  - IRRF "dedo-duro" de 0,005% sobre as vendas comuns é descontado do imposto do mês.
  - DARF código 6015, vencimento no último dia útil do mês seguinte; valores abaixo de R$ 10 são
    somados ao mês seguinte.
  - O custo usa o preço médio (com taxas) e considera desdobramentos e bonificações. Renda fixa,
    fundos e previdência não entram: o imposto é retido na fonte.

Declaração anual (DIRPF)
  - Bens e Direitos: situação em 31/12 pelo custo de aquisição, com grupo/código sugeridos.
  - Rendimentos isentos: dividendos, rendimentos de FII, lucro em vendas de ações até R$ 20 mil/mês.
  - Tributação exclusiva: juros sobre capital próprio.
"""
import datetime as dt
from collections import defaultdict

from carteira.rendafixa import dia_util

ISENCAO_ACOES = 20000.0
ISENCAO_CRIPTO = 35000.0
ALIQUOTA = {"comum": 0.15, "daytrade": 0.20, "fii": 0.20, "cripto": 0.15}
IRRF_COMUM = 0.00005
IRRF_DAYTRADE = 0.01
DARF_MINIMO = 10.0

CATEGORIA_CLASSE = {"acao": "acoes", "etf": "etf", "bdr": "bdr", "fii": "fii", "cripto": "cripto"}
NOME_POOL = {"comum": "Operações comuns (ações, ETFs, BDRs)", "daytrade": "Day trade", "fii": "Fundos imobiliários",
             "cripto": "Criptoativos"}

# Grupo e código em Bens e Direitos (DIRPF). Os marcados como "conferir" variam entre versões do programa.
BENS_DIREITOS = {
    "acao": ("03", "01", "Ações (inclusive listadas em bolsa)"),
    "fii": ("07", "03", "Fundos de Investimento Imobiliário (FII)"),
    "etf": ("07", "09", "Fundos de índice (ETF): conferir no programa"),
    "bdr": ("04", "04", "BDR: conferir no programa"),
    "renda_fixa": ("04", "02", "Títulos públicos e privados sujeitos à tributação (Tesouro, CDB, debêntures)"),
    "cripto": ("08", "01", "Criptoativos: conferir o código pelo tipo de ativo"),
}
RF_ISENTA = ("04", "03", "Títulos isentos (LCI, LCA, CRI, CRA)")


def _ultimo_dia_util_mes_seguinte(mes):
    a, m = int(mes[:4]), int(mes[5:7])
    a, m = (a + 1, 1) if m == 12 else (a, m + 1)
    d = (dt.date(a + (m == 12), 1 if m == 12 else m + 1, 1)) - dt.timedelta(days=1)
    while not dia_util(d) or (d.month == 12 and d.day in (24, 31)):  # sem expediente bancário
        d -= dt.timedelta(days=1)
    return d.isoformat()


def apurar(operacoes, classes, ate_mes=None):
    """Apuração mensal desde a primeira operação.

    operacoes: aportes + eventos (com_eventos); classes: {ticker: classe}
    Retorna lista de meses com o detalhamento por categoria, imposto devido e DARF.
    """
    pos = defaultdict(lambda: [0.0, 0.0])  # ticker -> [quantidade, custo]
    por_mes = defaultdict(lambda: {
        "vendas": defaultdict(float), "resultado": defaultdict(float), "vendas_daytrade": 0.0,
        "resultado_daytrade": 0.0, "operacoes": []})

    por_dia = defaultdict(list)
    for a in operacoes:
        por_dia[(a["data"], a["ticker"])].append(a)

    for (data, ticker) in sorted(por_dia, key=lambda k: (k[0], k[1])):
        ops = sorted(por_dia[(data, ticker)], key=lambda x: x.get("id") or 0)
        cat = CATEGORIA_CLASSE.get(classes.get(ticker, "acao"))
        p = pos[ticker]
        compras = [o for o in ops if o.get("tipo", "compra") == "compra"]
        vendas = [o for o in ops if o.get("tipo") == "venda" and o.get("ajuste") != "baixa"]
        baixas = [o for o in ops if o.get("ajuste") == "baixa"]
        eventos = [o for o in ops if o.get("tipo") == "evento"]
        qc = sum(float(o["quantidade"]) for o in compras)
        qv = sum(float(o["quantidade"]) for o in vendas)
        vc = sum(float(o["quantidade"]) * float(o["preco"]) + float(o.get("taxas") or 0) for o in compras)
        vv_bruto = sum(float(o["quantidade"]) * float(o["preco"]) for o in vendas)
        tx_v = sum(float(o.get("taxas") or 0) for o in vendas)
        mes = por_mes[data[:7]]

        dt_qtd = min(qc, qv) if cat else 0.0
        if dt_qtd > 0:  # day trade: compra e venda no mesmo dia
            custo_dt = vc * dt_qtd / qc
            venda_dt = (vv_bruto - tx_v) * dt_qtd / qv
            mes["resultado_daytrade"] += venda_dt - custo_dt
            mes["vendas_daytrade"] += vv_bruto * dt_qtd / qv
            mes["operacoes"].append({"data": data, "ticker": ticker, "tipo": "daytrade", "quantidade": dt_qtd,
                                     "venda": venda_dt, "custo": custo_dt, "resultado": venda_dt - custo_dt})
        # o restante: compras entram na posição e vendas saem pelo preço médio
        if qc - dt_qtd > 1e-12:
            p[0] += qc - dt_qtd
            p[1] += vc * (qc - dt_qtd) / qc
        if qv - dt_qtd > 1e-12:
            q = qv - dt_qtd
            medio = p[1] / p[0] if p[0] else 0.0
            venda = (vv_bruto - tx_v) * q / qv
            custo = medio * min(q, p[0])
            p[1] -= custo
            p[0] = max(p[0] - q, 0.0)
            if cat:
                mes["vendas"][cat] += vv_bruto * q / qv
                mes["resultado"][cat] += venda - custo
                mes["operacoes"].append({"data": data, "ticker": ticker, "tipo": cat, "quantidade": q,
                                         "venda": venda, "custo": custo, "resultado": venda - custo})
        for b in baixas:  # saída sem venda: reduz a posição pelo preço médio, fora da apuração
            q = float(b["quantidade"])
            medio = p[1] / p[0] if p[0] else 0.0
            p[1] -= medio * min(q, p[0])
            p[0] = max(p[0] - q, 0.0)
        for e in eventos:
            p[0] *= e["fator"]

    if not por_mes:
        return []
    meses_ord = sorted(por_mes)
    primeiro, ultimo = meses_ord[0], max(meses_ord[-1], ate_mes or meses_ord[-1])
    prejuizo = {"comum": 0.0, "daytrade": 0.0, "fii": 0.0}
    acumulado_darf = 0.0
    saida = []
    a, m = int(primeiro[:4]), int(primeiro[5:])
    while f"{a:04d}-{m:02d}" <= ultimo:
        chave = f"{a:04d}-{m:02d}"
        d = por_mes.get(chave) or {"vendas": {}, "resultado": {}, "vendas_daytrade": 0.0,
                                    "resultado_daytrade": 0.0, "operacoes": []}
        vendas, res = d["vendas"], d["resultado"]
        vendas_acoes = vendas.get("acoes", 0.0)
        isento = 0 < vendas_acoes <= ISENCAO_ACOES
        lucro_isento = res.get("acoes", 0.0) if isento and res.get("acoes", 0.0) > 0 else 0.0
        resultado_comum = res.get("acoes", 0.0) - lucro_isento + res.get("etf", 0.0) + res.get("bdr", 0.0)

        pools = {}
        for nome, resultado in (("comum", resultado_comum), ("daytrade", d["resultado_daytrade"]),
                                ("fii", res.get("fii", 0.0))):
            base = resultado + prejuizo[nome]
            if base > 0:
                imposto, prejuizo[nome] = base * ALIQUOTA[nome], 0.0
            else:
                imposto, prejuizo[nome] = 0.0, base
            pools[nome] = {"resultado": resultado, "base": max(base, 0.0), "imposto": imposto}
        cripto_vendas, cripto_res = vendas.get("cripto", 0.0), res.get("cripto", 0.0)
        cripto_imp = cripto_res * ALIQUOTA["cripto"] if cripto_vendas > ISENCAO_CRIPTO and cripto_res > 0 else 0.0
        pools["cripto"] = {"resultado": cripto_res, "base": cripto_res if cripto_imp else 0.0, "imposto": cripto_imp}

        vendas_tributaveis = sum(v for k, v in vendas.items() if k in ("etf", "bdr", "fii")) + \
            (vendas_acoes if not isento else 0.0)
        irrf = vendas_tributaveis * IRRF_COMUM + max(d["resultado_daytrade"], 0) * IRRF_DAYTRADE
        devido = sum(p["imposto"] for p in pools.values())
        a_pagar = max(devido - irrf, 0.0) + acumulado_darf
        if a_pagar >= DARF_MINIMO:
            darf, acumulado_darf = round(a_pagar, 2), 0.0
        else:
            darf, acumulado_darf = 0.0, a_pagar
        saida.append({
            "mes": chave, "vendas_acoes": vendas_acoes, "isento": isento, "lucro_isento": lucro_isento,
            "vendas": dict(vendas), "resultados": dict(res), "pools": pools,
            "prejuizo_acumulado": {k: -v for k, v in prejuizo.items()},
            "imposto_devido": devido, "irrf": min(irrf, devido) if devido else 0.0, "darf": darf,
            "darf_acumulado_proximo": acumulado_darf,
            "vencimento": _ultimo_dia_util_mes_seguinte(chave) if darf else None,
            "operacoes": d["operacoes"],
        })
        m += 1
        if m == 13:
            a, m = a + 1, 1
    return saida


def _br(valor, casas, enxuto=False):
    """Número no formato brasileiro: 1234.5 -> '1.234,50' (enxuto: sem zeros finais)."""
    txt = f"{valor:,.{casas}f}"
    if enxuto and "." in txt:
        txt = txt.rstrip("0").rstrip(".")
    return txt.replace(",", "X").replace(".", ",").replace("X", ".")


def _posicao_em(operacoes, data):
    pos = defaultdict(lambda: [0.0, 0.0])
    for a in sorted(operacoes, key=lambda x: (x["data"], x.get("id") or 0)):
        if a["data"] > data:
            break
        p = pos[a["ticker"]]
        if a.get("tipo") == "evento":
            p[0] *= a["fator"]
        elif a.get("tipo", "compra") == "compra":
            p[0] += float(a["quantidade"])
            p[1] += float(a["quantidade"]) * float(a["preco"]) + float(a.get("taxas") or 0)
        else:
            medio = p[1] / p[0] if p[0] else 0.0
            q = min(float(a["quantidade"]), p[0])
            p[1] -= medio * q
            p[0] -= q
    return {t: (q, c) for t, (q, c) in pos.items()}


def declaracao(operacoes, proventos, ativos, apuracao, ano):
    """Dados para a declaração do ano-calendário `ano`."""
    fim, fim_ant = f"{ano}-12-31", f"{ano - 1}-12-31"
    atual, anterior = _posicao_em(operacoes, fim), _posicao_em(operacoes, fim_ant)
    info = {a["ticker"]: a for a in ativos}
    bens = []
    operou_no_ano = {o["ticker"] for o in operacoes if o["data"][:4] == str(ano)}
    for t in sorted(set(atual) | set(anterior)):
        q1, c1 = atual.get(t, (0.0, 0.0))
        q0, c0 = anterior.get(t, (0.0, 0.0))
        if q1 <= 1e-9 and q0 <= 1e-9 and t not in operou_no_ano:
            continue  # comprado e vendido no ano também é informado (com saldos zerados)
        a = info.get(t, {})
        classe = a.get("classe", "acao")
        grupo, codigo, descricao = RF_ISENTA if classe == "renda_fixa" and a.get("isento_ir") else \
            BENS_DIREITOS.get(classe, ("99", "99", "Outros bens e direitos: conferir"))
        nome = a.get("nome") or ""
        unidade = "cotas" if classe in ("fii", "etf") else "unidades" if classe in ("renda_fixa", "cripto") else "ações"
        if abs(q1 - 1) < 1e-9:
            unidade = {"cotas": "cota", "unidades": "unidade", "ações": "ação"}[unidade]
        disc = (f"{_br(q1, 8, enxuto=True)} {unidade} de {t}{f' ({nome})' if nome else ''}, "
                f"custo médio de aquisição R$ {_br(c1 / q1 if q1 else 0, 2)}")
        if q1 <= 1e-9:
            disc = f"{t}{f' ({nome})' if nome else ''}: posição totalmente vendida em {ano}."
        bens.append({"ticker": t, "classe": classe, "grupo": grupo, "codigo": codigo, "descricao_codigo": descricao,
                     "quantidade": q1, "situacao_anterior": c0, "situacao_atual": c1, "discriminacao": disc})

    recebidos = [p for p in proventos if p["data_pagamento"][:4] == str(ano)]
    por = defaultdict(lambda: defaultdict(float))
    for p in recebidos:
        por[p["tipo"]][p["ticker"]] += float(p["valor_total"])

    def linhas(tipo):
        return [{"ticker": t, "valor": v} for t, v in sorted(por[tipo].items())]

    meses_ano = [m for m in apuracao if m["mes"].startswith(str(ano))]
    isentos = [
        {"codigo": "09", "titulo": "Lucros e dividendos recebidos", "itens": linhas("dividendo")},
        {"codigo": "99", "titulo": "Outros: rendimentos de FII e de outros fundos", "itens": linhas("rendimento")},
        {"codigo": "20", "titulo": "Ganhos líquidos em vendas de ações até R$ 20.000,00 no mês",
         "itens": [{"ticker": m["mes"], "valor": m["lucro_isento"]} for m in meses_ano if m["lucro_isento"] > 0]},
        {"codigo": "18", "titulo": "Bonificações em ações",
         "itens": [{"ticker": f"{o['ticker']} ({o['data']})", "valor": None}
                   for o in operacoes if o.get("tipo") == "evento" and o.get("evento") == "bonificacao"
                   and o["data"][:4] == str(ano)]},
    ]
    exclusivos = [{"codigo": "10", "titulo": "Juros sobre capital próprio", "itens": linhas("jcp")}]
    for grupo in isentos + exclusivos:
        grupo["total"] = sum(i["valor"] or 0 for i in grupo["itens"])
    return {"ano": ano, "bens": bens, "isentos": isentos, "exclusivos": exclusivos,
            "renda_variavel": [{k: m[k] for k in ("mes", "pools", "prejuizo_acumulado", "imposto_devido", "irrf", "darf")}
                               for m in meses_ano]}
