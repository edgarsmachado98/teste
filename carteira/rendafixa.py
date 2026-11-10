"""Renda fixa: valor atual pela taxa contratada, IR/IOF e valor líquido.

Indexadores (campo `indexador` do ativo, `taxa` ao ano):
  cdi      taxa% do CDI          ex.: 110 -> 110% do CDI (CDI diário, série 12 do Banco Central)
  selic    taxa% da Selic        ex.: 100 (Selic diária, série 11)
  ipca     IPCA + taxa% a.a.     ex.: 6.0 -> IPCA + 6% (IPCA mensal, série 433, pró-rata nos meses parciais)
  pre      prefixado taxa% a.a.  ex.: 12.5
  tesouro  preço oficial do Tesouro Direto (PU de resgate do dia), sem precisar da taxa

Os títulos são avaliados por lote (cada compra) e os resgates consomem os lotes mais antigos
primeiro (PEPS), como fazem bancos e corretoras. O IR segue a tabela regressiva (22,5% a 15%)
e o IOF a tabela dos primeiros 30 dias; títulos isentos não pagam IR.

Cálculos marcados na curva: o valor de mercado de um título (se vendido antes do vencimento)
pode ser diferente. Dias úteis consideram os feriados nacionais.
"""
import datetime as dt
from functools import lru_cache

INDEXADORES = {"cdi": "% do CDI", "selic": "% da Selic", "ipca": "IPCA +", "pre": "Prefixado",
               "tesouro": "Preço oficial do Tesouro"}


# ------------------------------------------------------------------ calendário

def _pascoa(ano):
    a, b, c = ano % 19, ano // 100, ano % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    mes = (h + m - 7 * n + 114) // 31
    dia = (h + m - 7 * n + 114) % 31 + 1
    return dt.date(ano, mes, dia)


@lru_cache(maxsize=64)
def feriados(ano):
    p = _pascoa(ano)
    fixos = [(1, 1), (4, 21), (5, 1), (9, 7), (10, 12), (11, 2), (11, 15), (12, 25)]
    if ano >= 2024:
        fixos.append((11, 20))  # Dia da Consciência Negra (feriado nacional desde 2024)
    moveis = [p - dt.timedelta(days=48), p - dt.timedelta(days=47), p - dt.timedelta(days=2),
              p + dt.timedelta(days=60)]  # Carnaval (seg e ter), Sexta-feira Santa, Corpus Christi
    return frozenset([dt.date(ano, m, d) for m, d in fixos] + moveis)


def dia_util(d):
    return d.weekday() < 5 and d not in feriados(d.year)


def dias_uteis(inicio, fim):
    """Dias úteis em [inicio, fim)."""
    if fim <= inicio:
        return 0
    total, d = 0, inicio
    while d < fim:
        if dia_util(d):
            total += 1
        d += dt.timedelta(days=1)
    return total


# ---------------------------------------------------------------- impostos

def aliquota_ir(dias):
    if dias <= 180:
        return 0.225
    if dias <= 360:
        return 0.20
    if dias <= 720:
        return 0.175
    return 0.15


IOF = [96, 93, 90, 86, 83, 80, 76, 73, 70, 66, 63, 60, 56, 53, 50, 46, 43, 40, 36, 33, 30, 26, 23, 20,
       16, 13, 10, 6, 3, 0]


def aliquota_iof(dias):
    """IOF regressivo sobre o rendimento nos resgates com menos de 30 dias."""
    return IOF[dias - 1] / 100 if 1 <= dias < 30 else (1.0 if dias <= 0 else 0.0)


# ----------------------------------------------------------------- fatores

def _d(x):
    return x if isinstance(x, dt.date) else dt.date.fromisoformat(x)


def fator_diario(pct, inicio, fim, serie):
    """Acumula uma taxa diária (% a.d., ex.: CDI) multiplicada por pct% em [inicio, fim).

    serie: lista ordenada [(data ISO, taxa % a.d.)]. Dias úteis sem taxa publicada (os mais
    recentes) usam a última taxa conhecida.
    """
    inicio, fim = _d(inicio), _d(fim)
    if not serie or fim <= inicio:
        return 1.0
    fator, ultima = 1.0, serie[0][1]
    publicadas = {}
    for data, taxa in serie:
        publicadas[data] = taxa
    d = inicio
    while d < fim:
        if dia_util(d):
            ultima = publicadas.get(d.isoformat(), ultima)
            fator *= 1 + ultima / 100 * pct / 100
        d += dt.timedelta(days=1)
    return fator


def fator_pre(taxa, inicio, fim):
    return (1 + taxa / 100) ** (dias_uteis(_d(inicio), _d(fim)) / 252)


def fator_ipca(taxa, inicio, fim, ipca_mensal):
    """IPCA acumulado (pró-rata por dias corridos nos meses parciais) x juro real (dias úteis/252).

    ipca_mensal: {"AAAA-MM": % do mês}. Meses ainda sem IPCA publicado usam o último conhecido.
    """
    inicio, fim = _d(inicio), _d(fim)
    if fim <= inicio:
        return 1.0
    ultimo = None
    for chave in sorted(ipca_mensal):
        ultimo = ipca_mensal[chave]
    fator, d = 1.0, inicio
    while d < fim:
        prox = (d.replace(day=1) + dt.timedelta(days=32)).replace(day=1)
        trecho_fim = min(prox, fim)
        dias_mes = (prox - d.replace(day=1)).days
        frac = (trecho_fim - d).days / dias_mes
        taxa_mes = ipca_mensal.get(d.strftime("%Y-%m"), ultimo or 0.0)
        fator *= (1 + taxa_mes / 100) ** frac
        d = trecho_fim
    return fator * fator_pre(taxa, inicio, fim)


# -------------------------------------------------------------------- lotes

def lotes_peps(aportes):
    """Lotes em aberto (data, quantidade, preço unitário) após os resgates, do mais antigo ao mais novo."""
    lotes = []
    for a in sorted(aportes, key=lambda x: (x["data"], x.get("id") or 0)):
        q = float(a["quantidade"])
        if a.get("tipo", "compra") == "compra":
            unit = (q * float(a["preco"]) + float(a.get("taxas") or 0)) / q
            lotes.append([a["data"], q, unit])
        else:
            while q > 1e-12 and lotes:
                usado = min(q, lotes[0][1])
                lotes[0][1] -= usado
                q -= usado
                if lotes[0][1] <= 1e-12:
                    lotes.pop(0)
    return [tuple(l) for l in lotes]


def avaliar(ativo, aportes, data, indices, preco_tesouro=None):
    """Valor de um título de renda fixa na data.

    ativo: dict com indexador, taxa, vencimento, isento_ir
    indices: {"cdi": [(data, % a.d.)], "selic": [...], "ipca": {"AAAA-MM": %}}
    preco_tesouro: PU oficial do título na data (indexador "tesouro")
    Retorna dict com aplicado, bruto, ir, iof, liquido, rendimento e os lotes — ou None
    se o indexador não estiver configurado.
    """
    idx = (ativo.get("indexador") or "").lower()
    if idx not in INDEXADORES:
        return None
    data = _d(data)
    venc = _d(ativo["vencimento"]) if ativo.get("vencimento") else None
    ate = min(data, venc) if venc else data  # depois do vencimento o título para de render
    taxa = float(ativo.get("taxa") or 0)
    lotes = [l for l in lotes_peps(aportes) if l[0] <= data.isoformat()]
    if idx == "tesouro" and not preco_tesouro:
        return None
    detalhes, aplicado, bruto, ir, iof = [], 0.0, 0.0, 0.0, 0.0
    for d_lote, qtd, unit in lotes:
        inicio = _d(d_lote)
        if idx == "cdi":
            fator = fator_diario(taxa or 100, inicio, ate, indices.get("cdi") or [])
        elif idx == "selic":
            fator = fator_diario(taxa or 100, inicio, ate, indices.get("selic") or [])
        elif idx == "ipca":
            fator = fator_ipca(taxa, inicio, ate, indices.get("ipca") or {})
        elif idx == "pre":
            fator = fator_pre(taxa, inicio, ate)
        else:  # tesouro
            fator = preco_tesouro / unit if unit else 1.0
        custo, valor = qtd * unit, qtd * unit * fator
        rendimento = max(valor - custo, 0.0)
        dias = (data - inicio).days
        iof_lote = rendimento * aliquota_iof(dias)
        ir_lote = 0.0 if ativo.get("isento_ir") else (rendimento - iof_lote) * aliquota_ir(dias)
        aplicado, bruto, ir, iof = aplicado + custo, bruto + valor, ir + ir_lote, iof + iof_lote
        detalhes.append({"data": d_lote, "quantidade": qtd, "aplicado": custo, "bruto": valor, "dias": dias})
    qtd_total = sum(l[1] for l in lotes)
    return {"aplicado": aplicado, "bruto": bruto, "ir": ir, "iof": iof, "liquido": bruto - ir - iof,
            "rendimento": bruto - aplicado, "quantidade": qtd_total,
            "preco_unitario": bruto / qtd_total if qtd_total else None,
            "dias_para_vencer": (venc - data).days if venc else None, "vencido": bool(venc and data >= venc),
            "lotes": detalhes}
