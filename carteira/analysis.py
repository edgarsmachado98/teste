"""Indicadores técnicos e estatísticas de risco/retorno (Python puro)."""
import math

DIAS_UTEIS_ANO = 252


def sma(valores, n):
    out, soma = [], 0.0
    for i, v in enumerate(valores):
        soma += v
        if i >= n:
            soma -= valores[i - n]
        out.append(soma / n if i >= n - 1 else None)
    return out


def ema(valores, n):
    out, k, atual = [], 2 / (n + 1), None
    for i, v in enumerate(valores):
        if i < n - 1:
            out.append(None)
            continue
        if atual is None:
            atual = sum(valores[i - n + 1:i + 1]) / n
        else:
            atual = v * k + atual * (1 - k)
        out.append(atual)
    return out


def rsi(valores, n=14):
    """RSI de Wilder."""
    out = [None] * len(valores)
    if len(valores) <= n:
        return out
    ganhos = perdas = 0.0
    for i in range(1, n + 1):
        d = valores[i] - valores[i - 1]
        ganhos += max(d, 0)
        perdas += max(-d, 0)
    ganho_m, perda_m = ganhos / n, perdas / n

    def calc(g, p):
        if p == 0:
            return 100.0 if g > 0 else 50.0
        return 100 - 100 / (1 + g / p)

    out[n] = calc(ganho_m, perda_m)
    for i in range(n + 1, len(valores)):
        d = valores[i] - valores[i - 1]
        ganho_m = (ganho_m * (n - 1) + max(d, 0)) / n
        perda_m = (perda_m * (n - 1) + max(-d, 0)) / n
        out[i] = calc(ganho_m, perda_m)
    return out


def macd(valores, rapida=12, lenta=26, sinal=9):
    e_r, e_l = ema(valores, rapida), ema(valores, lenta)
    linha = [a - b if a is not None and b is not None else None for a, b in zip(e_r, e_l)]
    inicio = next((i for i, v in enumerate(linha) if v is not None), len(linha))
    sinal_parcial = ema(linha[inicio:], sinal) if len(linha) - inicio >= sinal else []
    linha_sinal = [None] * inicio + sinal_parcial
    linha_sinal += [None] * (len(linha) - len(linha_sinal))
    hist = [a - b if a is not None and b is not None else None for a, b in zip(linha, linha_sinal)]
    return linha, linha_sinal, hist


def bollinger(valores, n=20, k=2):
    medias = sma(valores, n)
    sup, inf = [], []
    for i, m in enumerate(medias):
        if m is None:
            sup.append(None)
            inf.append(None)
            continue
        janela = valores[i - n + 1:i + 1]
        dp = math.sqrt(sum((x - m) ** 2 for x in janela) / n)
        sup.append(m + k * dp)
        inf.append(m - k * dp)
    return medias, sup, inf


def retornos_diarios(valores):
    return [valores[i] / valores[i - 1] - 1 for i in range(1, len(valores)) if valores[i - 1]]


def volatilidade_anual(valores):
    r = retornos_diarios(valores)
    if len(r) < 2:
        return None
    m = sum(r) / len(r)
    var = sum((x - m) ** 2 for x in r) / (len(r) - 1)
    return math.sqrt(var) * math.sqrt(DIAS_UTEIS_ANO)


def max_drawdown(valores):
    pico, mdd = None, 0.0
    for v in valores:
        pico = v if pico is None or v > pico else pico
        if pico:
            mdd = min(mdd, v / pico - 1)
    return mdd


def retorno_periodo(valores, dias):
    if len(valores) <= dias or not valores[-dias - 1]:
        return None
    return valores[-1] / valores[-dias - 1] - 1


def sharpe(valores, taxa_livre_risco_anual=0.10):
    r = retornos_diarios(valores)
    if len(r) < 2:
        return None
    rf_diario = (1 + taxa_livre_risco_anual) ** (1 / DIAS_UTEIS_ANO) - 1
    exc = [x - rf_diario for x in r]
    m = sum(exc) / len(exc)
    dp = math.sqrt(sum((x - m) ** 2 for x in exc) / (len(exc) - 1))
    return (m / dp) * math.sqrt(DIAS_UTEIS_ANO) if dp else None


def correlacao(a, b):
    n = min(len(a), len(b))
    if n < 3:
        return None
    a, b = a[-n:], b[-n:]
    ma, mb = sum(a) / n, sum(b) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    va = math.sqrt(sum((x - ma) ** 2 for x in a))
    vb = math.sqrt(sum((y - mb) ** 2 for y in b))
    return cov / (va * vb) if va and vb else None


def sinais(fech, mm_curta, mm_longa, rsi_v, macd_l, macd_s):
    """Leitura objetiva dos indicadores. Não é recomendação de investimento."""
    out = []
    preco = fech[-1]
    if mm_longa[-1] is not None:
        if preco > mm_longa[-1]:
            out.append(("alta", "Preço acima da média de 200 dias (tendência de alta de longo prazo)."))
        else:
            out.append(("baixa", "Preço abaixo da média de 200 dias (tendência de baixa de longo prazo)."))
    if mm_curta[-1] is not None and mm_longa[-1] is not None and len(mm_curta) > 1 \
            and mm_curta[-2] is not None and mm_longa[-2] is not None:
        if mm_curta[-2] <= mm_longa[-2] and mm_curta[-1] > mm_longa[-1]:
            out.append(("alta", "Cruzamento dourado: MM50 cruzou acima da MM200."))
        elif mm_curta[-2] >= mm_longa[-2] and mm_curta[-1] < mm_longa[-1]:
            out.append(("baixa", "Cruzamento da morte: MM50 cruzou abaixo da MM200."))
    r = rsi_v[-1]
    if r is not None:
        if r >= 70:
            out.append(("baixa", f"RSI em {r:.0f}: região de sobrecompra."))
        elif r <= 30:
            out.append(("alta", f"RSI em {r:.0f}: região de sobrevenda."))
        else:
            out.append(("neutro", f"RSI em {r:.0f}: zona neutra."))
    if len(macd_l) > 1 and None not in (macd_l[-1], macd_s[-1], macd_l[-2], macd_s[-2]):
        if macd_l[-2] <= macd_s[-2] and macd_l[-1] > macd_s[-1]:
            out.append(("alta", "MACD cruzou acima da linha de sinal."))
        elif macd_l[-2] >= macd_s[-2] and macd_l[-1] < macd_s[-1]:
            out.append(("baixa", "MACD cruzou abaixo da linha de sinal."))
        elif macd_l[-1] > macd_s[-1]:
            out.append(("alta", "MACD acima da linha de sinal (momento positivo)."))
        else:
            out.append(("baixa", "MACD abaixo da linha de sinal (momento negativo)."))
    return [{"tipo": t, "texto": s} for t, s in out]


def analisar(datas, fech, taxa_livre_risco=0.10):
    if len(fech) < 2:
        raise ValueError("Histórico insuficiente para análise.")
    mm20, sup, inf = bollinger(fech, 20)
    mm50 = sma(fech, 50)
    mm200 = sma(fech, 200)
    rsi14 = rsi(fech, 14)
    m_l, m_s, m_h = macd(fech)
    return {
        "datas": datas,
        "fechamento": fech,
        "mm20": mm20, "mm50": mm50, "mm200": mm200,
        "bollinger_sup": sup, "bollinger_inf": inf,
        "rsi": rsi14,
        "macd": m_l, "macd_sinal": m_s, "macd_hist": m_h,
        "estatisticas": {
            "preco": fech[-1],
            "minimo": min(fech),
            "maximo": max(fech),
            "retorno_1m": retorno_periodo(fech, 21),
            "retorno_3m": retorno_periodo(fech, 63),
            "retorno_6m": retorno_periodo(fech, 126),
            "retorno_12m": retorno_periodo(fech, 252),
            "retorno_total": fech[-1] / fech[0] - 1 if fech[0] else None,
            "volatilidade": volatilidade_anual(fech),
            "max_drawdown": max_drawdown(fech),
            "sharpe": sharpe(fech, taxa_livre_risco),
        },
        "sinais": sinais(fech, mm50, mm200, rsi14, m_l, m_s),
    }
