"""Importação dos extratos da Área do Investidor da B3 (Excel ou CSV).

Extratos suportados (menu Extratos da Área do Investidor):
- Negociação: compras e vendas na bolsa (ações, FIIs, ETFs, BDRs).
  Colunas: Data do Negócio, Tipo de Movimentação, Mercado, Prazo/Vencimento, Instituição,
  Código de Negociação, Quantidade, Preço, Valor.
- Movimentação: proventos (dividendos, JCP, rendimentos, amortizações), compras/vendas de
  Tesouro Direto e eventos (desdobramentos, bonificações...).
  Colunas: Entrada/Saída, Data, Movimentação, Produto, Instituição, Quantidade,
  Preço unitário, Valor da Operação.

Os nomes de coluna são comparados sem acentos e sem diferenciar maiúsculas, para tolerar
pequenas mudanças de layout. Nada é gravado aqui: as funções devolvem uma prévia.
"""
import csv
import datetime as dt
import io
import re
import unicodedata

B3_TICKER = re.compile(r"^([A-Z]{4}\d{1,2})F?$")


class ErroImportacao(Exception):
    pass


def _norm(texto):
    texto = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", texto).strip().lower()


def _numero(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("R$", "").replace(" ", "")
    if s in ("-", "--"):
        return None
    if "," in s:  # formato brasileiro 1.234,56
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _data(v):
    if isinstance(v, dt.datetime):
        return v.date().isoformat()
    if isinstance(v, dt.date):
        return v.isoformat()
    s = str(v or "").strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y"):
        try:
            return dt.datetime.strptime(s[:10], fmt).date().isoformat()
        except ValueError:
            continue
    return None


def ler_planilha(conteudo, nome_arquivo):
    """Lê .xlsx ou .csv e devolve todas as linhas (de todas as abas) em uma lista."""
    return [linha for _, linhas in ler_abas(conteudo, nome_arquivo) for linha in linhas]


def ler_abas(conteudo, nome_arquivo):
    """Lê .xlsx ou .csv e devolve [(nome_da_aba, linhas)]."""
    nome = (nome_arquivo or "").lower()
    if nome.endswith((".xlsx", ".xlsm")):
        try:
            import openpyxl
        except ImportError as e:
            raise ErroImportacao("Instale o pacote openpyxl para ler arquivos Excel "
                                 "(pip install -r requirements.txt).") from e
        import warnings
        try:
            # Sem read_only: os arquivos gerados pela B3 trazem a dimensão da planilha errada
            # (ex.: "A1"), e no modo read_only o openpyxl leria só a primeira célula.
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")  # "Workbook contains no default style"
                wb = openpyxl.load_workbook(io.BytesIO(conteudo), data_only=True)
        except Exception as e:
            raise ErroImportacao(f"Não foi possível abrir o Excel: {e}") from e
        return [(ws.title, [list(r) for r in ws.iter_rows(values_only=True)]) for ws in wb.worksheets]
    if nome.endswith((".csv", ".txt")):
        for codificacao in ("utf-8-sig", "latin-1"):
            try:
                texto = conteudo.decode(codificacao)
                break
            except UnicodeDecodeError:
                continue
        delim = ";" if texto.count(";") > texto.count(",") else ","
        return [(nome, [r for r in csv.reader(io.StringIO(texto), delimiter=delim)])]
    if nome.endswith(".xls"):
        raise ErroImportacao("Formato .xls antigo não suportado. Baixe o extrato em .xlsx ou abra no Excel "
                             "e salve como .xlsx.")
    if nome.endswith(".pdf"):
        raise ErroImportacao("Extratos em PDF não são suportados. Na Área do Investidor, baixe em Excel.")
    raise ErroImportacao("Envie o extrato em Excel (.xlsx) ou CSV.")


COLUNAS_NEGOCIACAO = {"data": "data do negocio", "tipo": "tipo de movimentacao",
                      "ticker": "codigo de negociacao", "quantidade": "quantidade", "preco": "preco",
                      "valor": "valor", "mercado": "mercado", "instituicao": "instituicao"}
COLUNAS_MOVIMENTACAO = {"es": "entrada/saida", "data": "data", "mov": "movimentacao",
                        "produto": "produto", "quantidade": "quantidade",
                        "preco": "preco unitario", "valor": "valor da operacao",
                        "instituicao": "instituicao"}


# Extrato de Eventos (proventos recebidos/provisionados). O layout varia; aceitamos sinônimos.
COLUNAS_EVENTOS = {
    "produto": ("produto", "ativo", "codigo de negociacao"),
    "tipo": ("tipo de evento", "tipo evento", "evento", "tipo de provento", "tipo"),
    "data": ("pagamento", "data de pagamento", "data do pagamento", "data pagamento", "data"),
    "quantidade": ("quantidade", "qtd", "quantidade base"),
    "preco": ("preco unitario", "valor unitario", "valor por cota", "valor por acao"),
    "valor": ("valor liquido", "valor liquido (r$)", "valor total", "valor da operacao", "valor bruto",
              "valor", "total"),
}


def _indices_flexiveis(nomes, colunas):
    idx = {}
    for chave, candidatos in colunas.items():
        for c in candidatos:
            if c in nomes:
                idx[chave] = nomes.index(c)
                break
    return idx


def _localizar_cabecalho(linhas):
    for i, linha in enumerate(linhas):
        nomes = [_norm(c) for c in linha]
        if "codigo de negociacao" in nomes and "data do negocio" in nomes:
            return "negociacao", i, nomes
        if "movimentacao" in nomes and "produto" in nomes and "entrada/saida" in nomes:
            return "movimentacao", i, nomes
        idx = _indices_flexiveis(nomes, COLUNAS_EVENTOS)
        if {"produto", "tipo", "data", "valor"} <= set(idx) and \
                any("evento" in n or "provento" in n for n in nomes):
            return "eventos", i, nomes
    if not any(c not in (None, "") for l in linhas for c in l):
        raise ErroImportacao("A planilha está vazia ou não pôde ser lida.")
    cabecalhos = next((", ".join(str(c) for c in l if c not in (None, ""))
                       for l in linhas if sum(c not in (None, "") for c in l) >= 3), "")
    raise ErroImportacao("Não reconheci o arquivo. Use os extratos de Posição, Negociação, Movimentação ou Eventos "
                         "da Área do Investidor da B3, sem alterar o cabeçalho."
                         + (f" Colunas encontradas: {cabecalhos[:300]}" if cabecalhos else ""))


def _registros(linhas, inicio, nomes, colunas):
    idx = {}
    for chave, nome in colunas.items():
        if nome in nomes:
            idx[chave] = nomes.index(nome)
    for n, linha in enumerate(linhas[inicio + 1:], start=inicio + 2):
        if not any(c not in (None, "") for c in linha):
            continue
        reg = {k: (linha[i] if i < len(linha) else None) for k, i in idx.items()}
        reg["_linha"] = n
        yield reg


def ticker_do_produto(produto):
    """'PETR4 - PETROLEO BRASILEIRO S.A.' -> 'PETR4'; Tesouro -> 'TESOURO IPCA+ 2035'."""
    p = str(produto or "").strip()
    primeiro = p.split(" - ")[0].strip().upper()
    m = B3_TICKER.match(primeiro)
    if m:
        return m.group(1), "b3"
    if _norm(p).startswith("tesouro"):
        return re.sub(r"\s+", " ", p.split(" - ")[0]).strip().upper(), "tesouro"
    return primeiro, "outro"


def classe_provavel(ticker, origem="b3"):
    if origem in ("tesouro", "renda_fixa"):
        return "renda_fixa"
    if ticker in ETFS_CONHECIDOS:
        return "etf"
    final = re.sub(r"^[A-Z]{4}", "", ticker)
    if final == "11":
        return "fii"  # pode ser ETF ou unit: ajuste em "Ativos e metas" se necessário
    if final in ("31", "32", "33", "34", "35", "39"):
        return "bdr"
    return "acao"


def _negociacao(linhas, inicio, nomes):
    aportes, ignorados = [], []
    for r in _registros(linhas, inicio, nomes, COLUNAS_NEGOCIACAO):
        tipo = _norm(r.get("tipo"))
        data, qtd, preco = _data(r.get("data")), _numero(r.get("quantidade")), _numero(r.get("preco"))
        bruto = str(r.get("ticker") or "").strip().upper()
        m = B3_TICKER.match(bruto)
        mercado = _norm(r.get("mercado"))
        if "opcao" in mercado or "termo" in mercado or "futuro" in mercado:
            ignorados.append({"linha": r["_linha"], "descricao": f"{bruto} ({r.get('mercado')})",
                              "motivo": "Opções, termo e futuros não são controlados pelo sistema."})
            continue
        if tipo not in ("compra", "venda") or not m or not data or not qtd or preco is None:
            ignorados.append({"linha": r["_linha"], "descricao": f"{r.get('tipo')} {bruto}".strip(),
                              "motivo": "Linha incompleta ou tipo de operação desconhecido."})
            continue
        ticker = m.group(1)
        aportes.append({"data": data, "ticker": ticker, "tipo": tipo, "quantidade": qtd, "preco": preco,
                        "taxas": 0.0, "classe": classe_provavel(ticker),
                        "obs": f"B3 {r.get('instituicao') or ''}".strip()})
    return aportes, [], ignorados


TIPOS_PROVENTO_B3 = {
    "dividendo": "dividendo", "juros sobre capital proprio": "jcp", "rendimento": "rendimento",
    "amortizacao": "amortizacao", "restituicao de capital": "outro",
}
EVENTOS = ("desdobro", "grupamento", "bonificacao", "subscricao", "direito", "cessao",
           "incorporacao", "fracao", "atualizacao", "transferencia")


def _movimentacao(linhas, inicio, nomes):
    aportes, proventos, ignorados = [], [], []
    for r in _registros(linhas, inicio, nomes, COLUNAS_MOVIMENTACAO):
        mov = _norm(r.get("mov"))
        credito = _norm(r.get("es")).startswith("credito")
        data = _data(r.get("data"))
        ticker, origem = ticker_do_produto(r.get("produto"))
        desc = f"{r.get('mov')} · {r.get('produto')}"
        valor = _numero(r.get("valor"))
        qtd, preco = _numero(r.get("quantidade")), _numero(r.get("preco"))

        tipo_prov = next((t for chave, t in TIPOS_PROVENTO_B3.items() if mov.startswith(chave)), None)
        if tipo_prov and credito:
            if not data or valor is None:
                ignorados.append({"linha": r["_linha"], "descricao": desc, "motivo": "Sem data ou valor."})
                continue
            proventos.append({"ticker": ticker, "tipo": tipo_prov, "data_pagamento": data,
                              "quantidade": qtd, "valor_unitario": preco, "valor_total": round(valor, 2),
                              "obs": "B3"})
            continue
        if origem == "tesouro" and mov in ("compra", "venda", "resgate", "vencimento"):
            if not data or not qtd:
                ignorados.append({"linha": r["_linha"], "descricao": desc, "motivo": "Sem data ou quantidade."})
                continue
            if preco is None and valor is not None:
                preco = valor / qtd
            aportes.append({"data": data, "ticker": ticker, "tipo": "compra" if mov == "compra" else "venda",
                            "quantidade": qtd, "preco": preco or 0.0, "taxas": 0.0, "classe": "renda_fixa",
                            "obs": "B3 Tesouro Direto"})
            continue
        if mov.startswith("transferencia") or mov in ("compra", "venda"):
            motivo = "Compras e vendas de bolsa vêm do extrato de Negociação (evita duplicar)."
        elif any(mov.startswith(e) for e in EVENTOS):
            motivo = "Evento corporativo: ajuste a quantidade manualmente (ex.: desdobramento, bonificação)."
        elif tipo_prov and not credito:
            motivo = "Provento provisionado/débito: será importado quando for creditado."
        else:
            motivo = "Movimentação não reconhecida."
        ignorados.append({"linha": r["_linha"], "descricao": desc, "motivo": motivo})
    return aportes, proventos, ignorados


def _eventos(linhas, inicio, nomes):
    """Extrato de Eventos: um provento por linha (já creditado ou provisionado)."""
    idx = _indices_flexiveis(nomes, COLUNAS_EVENTOS)
    proventos, ignorados = [], []
    for n, linha in enumerate(linhas[inicio + 1:], start=inicio + 2):
        if not any(c not in (None, "") for c in linha):
            continue
        r = {k: (linha[i] if i < len(linha) else None) for k, i in idx.items()}
        tipo_txt = _norm(r.get("tipo"))
        ticker, _ = ticker_do_produto(r.get("produto"))
        desc = f"{r.get('tipo')} · {r.get('produto')}"
        tipo = next((t for chave, t in TIPOS_PROVENTO_B3.items() if tipo_txt.startswith(chave)), None)
        if tipo is None and tipo_txt.startswith("jcp"):
            tipo = "jcp"
        if tipo is None:
            motivo = ("Evento corporativo: ajuste a quantidade manualmente."
                      if any(tipo_txt.startswith(e) for e in EVENTOS) else "Tipo de evento não reconhecido.")
            ignorados.append({"linha": n, "descricao": desc, "motivo": motivo})
            continue
        data, valor = _data(r.get("data")), _numero(r.get("valor"))
        if not data or valor is None or not ticker:
            ignorados.append({"linha": n, "descricao": desc, "motivo": "Sem data de pagamento ou valor."})
            continue
        proventos.append({"ticker": ticker, "tipo": tipo, "data_pagamento": data,
                          "quantidade": _numero(r.get("quantidade")), "valor_unitario": _numero(r.get("preco")),
                          "valor_total": round(valor, 2), "obs": "B3 eventos"})
    return [], proventos, ignorados


# ------------------------------------------------------------------ Posição
# Extrato de Posição: uma aba por tipo de ativo (Ações, BDR, ETF, Fundo de Investimento,
# Tesouro Direto, Renda Fixa...). Mostra o que existe hoje em cada instituição.
COLUNAS_POSICAO = {
    "codigo": ("codigo de negociacao", "codigo"),
    "produto": ("produto",),
    "quantidade": ("quantidade",),
    "preco": ("preco de fechamento", "preco de fechamento (r$)", "preco atualizado", "preco unitario",
              "pu atualizado"),
    "valor": ("valor atualizado", "valor atualizado (r$)", "valor liquido", "valor bruto",
              "valor atualizado curva", "valor atualizado mtm"),
    "aplicado": ("valor aplicado", "valor aplicado (r$)"),
    "vencimento": ("vencimento", "data de vencimento"),
}
CLASSE_POR_ABA = (("acao", "acao"), ("acoes", "acao"), ("bdr", "bdr"), ("etf", "etf"),
                  ("fundo", "fii"), ("fii", "fii"), ("tesouro", "renda_fixa"), ("renda fixa", "renda_fixa"),
                  ("coe", "renda_fixa"))
ETFS_CONHECIDOS = {"BOVA11", "IVVB11", "SMAL11", "HASH11", "DIVO11", "XINA11", "GOLD11", "BOVV11", "SPXI11",
                   "NASD11", "ACWI11", "EURP11", "FIND11", "MATB11", "IMAB11", "B5P211", "FIXA11", "QBTC11",
                   "BITH11", "ETHE11", "NTNS11", "LFTS11", "PIBB11", "BRAX11", "ECOO11", "SPXB11", "WRLD11"}


def _cabecalho_posicao(linhas):
    for i, linha in enumerate(linhas[:30]):
        nomes = [_norm(c) for c in linha]
        if "data do negocio" in nomes or "entrada/saida" in nomes or any("evento" in n for n in nomes):
            return None
        idx = _indices_flexiveis(nomes, COLUNAS_POSICAO)
        if "quantidade" in idx and ("codigo" in idx or "produto" in idx) and \
                ({"preco", "valor", "aplicado"} & set(idx)):
            return i, idx
    return None


def _classe_da_aba(aba, ticker, origem):
    a = _norm(aba)
    for chave, classe in CLASSE_POR_ABA:
        if chave in a:
            return classe
    return classe_provavel(ticker, origem)


def _posicao(abas):
    itens, ignorados = {}, []
    for aba, linhas in abas:
        achado = _cabecalho_posicao(linhas)
        if not achado:
            continue
        inicio, idx = achado
        for n, linha in enumerate(linhas[inicio + 1:], start=inicio + 2):
            cel = {k: (linha[i] if i < len(linha) else None) for k, i in idx.items()}
            produto = str(cel.get("produto") or "").strip()
            if not any(c not in (None, "") for c in linha) or _norm(produto).startswith("total") \
                    or _norm(cel.get("codigo")).startswith("total"):
                continue
            qtd = _numero(cel.get("quantidade"))
            codigo = str(cel.get("codigo") or "").strip().upper()
            m = B3_TICKER.match(codigo)
            if m:
                ticker, origem = m.group(1), "b3"
            else:
                ticker, origem = ticker_do_produto(produto or codigo)
                if origem == "outro":  # CDB, LCA, debêntures...: produto + vencimento identificam o título
                    venc = _data(cel.get("vencimento"))
                    ticker = re.sub(r"\s+", " ", f"{produto} {venc or ''}").strip().upper()[:60]
                    origem = "renda_fixa"
            if not ticker or not qtd:
                ignorados.append({"linha": n, "descricao": f"{aba}: {produto or codigo}",
                                  "motivo": "Sem código ou quantidade."})
                continue
            valor, preco, aplicado = _numero(cel.get("valor")), _numero(cel.get("preco")), _numero(cel.get("aplicado"))
            if preco is None and valor is not None:
                preco = valor / qtd
            classe = _classe_da_aba(aba, ticker, origem)
            if classe == "fii" and ticker in ETFS_CONHECIDOS:
                classe = "etf"
            it = itens.setdefault(ticker, {"ticker": ticker, "classe": classe, "quantidade": 0.0,
                                           "valor_atual": 0.0, "custo_total": 0.0, "tem_custo": False,
                                           "nome": produto.split(" - ", 1)[-1][:80] if " - " in produto else ""})
            it["quantidade"] += qtd
            it["valor_atual"] += valor if valor is not None else (preco or 0) * qtd
            if aplicado is not None:
                it["custo_total"] += aplicado
                it["tem_custo"] = True
    posicao = []
    for it in itens.values():
        it["preco_atual"] = it["valor_atual"] / it["quantidade"] if it["quantidade"] else None
        it["preco_medio"] = it["custo_total"] / it["quantidade"] if it["tem_custo"] and it["quantidade"] else None
        del it["custo_total"], it["tem_custo"]
        posicao.append(it)
    return sorted(posicao, key=lambda x: x["ticker"]), ignorados


def analisar_extrato(conteudo, nome_arquivo):
    abas = ler_abas(conteudo, nome_arquivo)
    if any(_cabecalho_posicao(linhas) for _, linhas in abas):
        posicao, ignorados = _posicao(abas)
        return {"tipo_arquivo": "posicao", "aportes": [], "proventos": [], "ignorados": ignorados,
                "posicao": posicao}
    linhas = [linha for _, ls in abas for linha in ls]
    tipo, inicio, nomes = _localizar_cabecalho(linhas)
    if tipo == "negociacao":
        aportes, proventos, ignorados = _negociacao(linhas, inicio, nomes)
    elif tipo == "eventos":
        aportes, proventos, ignorados = _eventos(linhas, inicio, nomes)
    else:
        aportes, proventos, ignorados = _movimentacao(linhas, inicio, nomes)
    return {"tipo_arquivo": tipo, "aportes": aportes, "proventos": proventos, "ignorados": ignorados,
            "posicao": []}


def marcar_duplicados(previa, aportes_existentes, proventos_existentes):
    """Marca itens já lançados na carteira (mesma data, ativo, tipo, quantidade e preço/valor)."""
    def chave_ap(a):
        return (a["data"], a["ticker"], a.get("tipo", "compra"), round(float(a["quantidade"]), 6),
                round(float(a["preco"]), 2))

    def chave_pr(p):
        return (p["data_pagamento"], p["ticker"], p["tipo"], round(float(p["valor_total"]), 2))

    existentes_ap = {}
    for a in aportes_existentes:
        existentes_ap[chave_ap(a)] = existentes_ap.get(chave_ap(a), 0) + 1
    existentes_pr = {}
    for p in proventos_existentes:
        existentes_pr[chave_pr(p)] = existentes_pr.get(chave_pr(p), 0) + 1
    # Contagem permite duas compras idênticas no mesmo dia (ambas aparecem no extrato).
    for lista, existentes, chave in ((previa["aportes"], existentes_ap, chave_ap),
                                     (previa["proventos"], existentes_pr, chave_pr)):
        for item in lista:
            k = chave(item)
            if existentes.get(k, 0) > 0:
                item["ja_registrado"] = True
                existentes[k] -= 1
            else:
                item["ja_registrado"] = False
    return previa


def _dia_anterior(data_iso):
    return (dt.date.fromisoformat(data_iso) - dt.timedelta(days=1)).isoformat()


def conciliar_posicao(posicao, aportes_existentes, aportes_novos, hoje):
    """Compara a posição da B3 com o que o sistema terá após a importação.

    Para cada ativo, posição inicial = quantidade na B3 - (quantidade no sistema + compras - vendas novas).
    Se positiva, é o que você já tinha antes do período dos extratos: vira uma compra de abertura
    no dia anterior à primeira operação. Se negativa, há eventos ou vendas que o sistema não conhece.
    Ativos zerados na B3 mas vendidos nos extratos também recebem posição inicial.
    """
    saldo = {}
    for a in list(aportes_existentes) + [a for a in aportes_novos if not a.get("ja_registrado")]:
        sinal = 1 if a.get("tipo", "compra") == "compra" else -1
        saldo[a["ticker"]] = saldo.get(a["ticker"], 0.0) + sinal * float(a["quantidade"])
    todas = [a["data"] for a in list(aportes_existentes) + list(aportes_novos)]
    data_abertura = _dia_anterior(min(todas)) if todas else hoje
    na_b3 = {p["ticker"]: p for p in posicao}

    iniciais, divergencias = [], []
    for ticker in sorted(set(na_b3) | set(saldo)):
        p = na_b3.get(ticker)
        qtd_b3 = p["quantidade"] if p else 0.0
        diferenca = round(qtd_b3 - saldo.get(ticker, 0.0), 8)
        if abs(diferenca) < 1e-9:
            continue
        if diferenca > 0:
            iniciais.append({"ticker": ticker, "classe": p["classe"] if p else classe_provavel(ticker),
                             "quantidade": diferenca, "data": data_abertura,
                             "preco": p.get("preco_medio") if p else None,
                             "preco_origem": "valor aplicado na B3" if p and p.get("preco_medio") else None,
                             "qtd_b3": qtd_b3})
        else:
            motivo = ("O sistema terá mais do que a B3 mostra: verifique vendas, grupamentos ou "
                      "transferências não importados." if p is not None else
                      "Não aparece na posição da B3. Se for um ativo fora da B3 (cripto, previdência...), ignore.")
            divergencias.append({"ticker": ticker, "qtd_b3": qtd_b3, "qtd_sistema": saldo.get(ticker, 0.0),
                                 "motivo": motivo})
    return {"data_abertura": data_abertura, "posicoes_iniciais": iniciais, "divergencias": divergencias}
