"""Importação de extratos da B3 e relatórios de investimentos (Excel .xlsx/.xls, CSV, HTML ou PDF).

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
        texto = _decodificar(conteudo)
        delim = ";" if texto.count(";") > texto.count(",") else ","
        return [(nome, [r for r in csv.reader(io.StringIO(texto), delimiter=delim)])]
    if nome.endswith((".xls", ".htm", ".html")):
        inicio = conteudo[:2048].lstrip(b"\xef\xbb\xbf \r\n\t").lower()
        if conteudo[:4] == b"PK\x03\x04":  # na verdade é .xlsx com a extensão errada
            return ler_abas(conteudo, nome + "x")
        if inicio.startswith(b"<") or b"<table" in inicio:
            # Muitos bancos exportam "Excel" que é, na verdade, uma tabela HTML.
            return _ler_html(conteudo)
        return _ler_xls(conteudo)
    if nome.endswith(".pdf"):
        return _ler_pdf(conteudo)
    raise ErroImportacao("Envie o relatório em Excel (.xlsx ou .xls), CSV ou PDF.")


def _decodificar(conteudo):
    for codificacao in ("utf-8-sig", "latin-1"):
        try:
            return conteudo.decode(codificacao)
        except UnicodeDecodeError:
            continue
    return conteudo.decode("utf-8", "ignore")


def _ler_xls(conteudo):
    """Excel 97-2003 (.xls)."""
    try:
        import xlrd
    except ImportError as e:
        raise ErroImportacao("Instale o pacote xlrd para ler arquivos .xls (pip install -r requirements.txt).") from e
    try:
        wb = xlrd.open_workbook(file_contents=conteudo)
    except Exception as e:
        raise ErroImportacao(f"Não foi possível abrir o arquivo .xls: {e}") from e
    abas = []
    for sh in wb.sheets():
        linhas = []
        for r in range(sh.nrows):
            linha = []
            for c in range(sh.ncols):
                cel = sh.cell(r, c)
                if cel.ctype == xlrd.XL_CELL_DATE:
                    try:
                        linha.append(xlrd.xldate.xldate_as_datetime(cel.value, wb.datemode))
                        continue
                    except Exception:
                        pass
                linha.append(cel.value)
            linhas.append(linha)
        abas.append((sh.name, linhas))
    return abas


def _ler_html(conteudo):
    """Tabelas de um HTML (formato usado por vários bancos ao 'exportar para Excel')."""
    from html.parser import HTMLParser

    class Tabelas(HTMLParser):
        def __init__(self):
            super().__init__()
            self.tabelas, self.linha, self.celula = [], None, None

        def handle_starttag(self, tag, attrs):
            if tag == "table":
                self.tabelas.append([])
            elif tag == "tr" and self.tabelas:
                self.linha = []
            elif tag in ("td", "th") and self.linha is not None:
                self.celula = []

        def handle_endtag(self, tag):
            if tag in ("td", "th") and self.celula is not None:
                self.linha.append(re.sub(r"\s+", " ", "".join(self.celula)).strip())
                self.celula = None
            elif tag == "tr" and self.linha is not None:
                self.tabelas[-1].append(self.linha)
                self.linha = None

        def handle_data(self, data):
            if self.celula is not None:
                self.celula.append(data)

    p = Tabelas()
    p.feed(_decodificar(conteudo))
    return [(f"Tabela {i + 1}", t) for i, t in enumerate(p.tabelas) if t]


def _linhas_por_posicao(palavras, tolerancia_linha=3, distancia_coluna=7):
    """Agrupa as palavras de uma página em linhas (mesma altura) e células (espaço largo entre palavras)."""
    linhas = []
    for w in sorted(palavras, key=lambda w: (round(w["top"]), w["x0"])):
        if linhas and abs(linhas[-1][0] - w["top"]) <= tolerancia_linha:
            linhas[-1][1].append(w)
        else:
            linhas.append([w["top"], [w]])
    resultado = []
    for _, ws in linhas:
        ws.sort(key=lambda w: w["x0"])
        celulas, atual, fim = [], [], None
        for w in ws:
            if atual and w["x0"] - fim > distancia_coluna:
                celulas.append(" ".join(atual))
                atual = []
            atual.append(w["text"])
            fim = w["x1"]
        celulas.append(" ".join(atual))
        resultado.append(celulas)
    return resultado


def _ler_pdf(conteudo):
    """Extrai as tabelas de cada página do PDF.

    Primeiro usa a detecção de tabelas do pdfplumber; se a página não tiver tabelas
    desenhadas, divide cada linha de texto em colunas pelos espaços largos entre elas.
    PDFs escaneados (imagem) não têm texto e não podem ser lidos.
    """
    try:
        import pdfplumber
    except ImportError as e:
        raise ErroImportacao("Instale o pacote pdfplumber para ler PDFs (pip install -r requirements.txt).") from e
    abas = []
    try:
        with pdfplumber.open(io.BytesIO(conteudo)) as pdf:
            for n, pagina in enumerate(pdf.pages, start=1):
                tabelas = pagina.extract_tables() or []
                for t, tabela in enumerate(tabelas, start=1):
                    abas.append((f"PDF página {n} tabela {t}",
                                 [[(c or "").replace("\n", " ").strip() for c in linha] for linha in tabela]))
                if not tabelas:  # sem tabela desenhada: monta as colunas pela posição das palavras
                    linhas = _linhas_por_posicao(pagina.extract_words(keep_blank_chars=False, use_text_flow=False))
                    if linhas:
                        abas.append((f"PDF página {n} texto", linhas))
    except ErroImportacao:
        raise
    except Exception as e:
        raise ErroImportacao(f"Não foi possível ler o PDF: {e}") from e
    if not abas:
        raise ErroImportacao("O PDF não tem texto legível (pode ser uma imagem escaneada). "
                             "Baixe o relatório em Excel, se possível.")
    return abas


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


def _norm_cab(texto):
    """Nome de coluna normalizado, sem datas e unidades: 'SALDO BRUTO 30/09/2026 (R$)' -> 'saldo bruto'."""
    t = _norm(texto)
    t = re.sub(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b|\b\d{1,2}/\d{4}\b|\(r\$\)|\br\$|\(%\)", " ", t)
    return re.sub(r"\s+", " ", t).strip(" -:")


def _indices_flexiveis(nomes, colunas, ultimos=()):
    """Índice de cada coluna pelo primeiro sinônimo encontrado.

    Para as chaves em `ultimos`, usa a última ocorrência (ex.: relatórios com "Saldo bruto" no
    início e no fim do período: vale o saldo mais recente).
    """
    idx = {}
    for chave, candidatos in colunas.items():
        for c in candidatos:
            if c in nomes:
                idx[chave] = len(nomes) - 1 - nomes[::-1].index(c) if chave in ultimos else nomes.index(c)
                break
    return idx


def _cabecalhos_candidatos(linhas, limite=8):
    """Linhas que parecem cabeçalhos de tabela (para a mensagem de erro)."""
    vistos = []
    for l in linhas:
        textos = [str(c).strip() for c in l if c not in (None, "") and str(c).strip()]
        if len(textos) < 3 or sum(_numero(t) is not None for t in textos) > len(textos) / 3:
            continue
        cab = ", ".join(textos)[:200]
        if cab not in vistos:
            vistos.append(cab)
        if len(vistos) >= limite:
            break
    return vistos


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
        raise ErroImportacao("O arquivo está vazio ou não pôde ser lido.")
    cabecalhos = _cabecalhos_candidatos(linhas)
    raise ErroImportacao("Não reconheci o relatório. São aceitos os extratos da B3 (Posição, Negociação, "
                         "Movimentação, Eventos) e relatórios de posição com uma tabela por ativo (nome do "
                         "ativo/produto e quantidade ou saldo)."
                         + (" Tabelas encontradas: " + " | ".join(cabecalhos) if cabecalhos else ""))


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
# Os sinônimos cobrem o extrato da B3 e relatórios de posição de bancos e corretoras.
COLUNAS_POSICAO = {
    "codigo": ("codigo de negociacao", "codigo", "ativo", "papel", "ticker", "codigo do ativo"),
    "produto": ("produto", "descricao", "titulo", "fundo", "aplicacao", "investimento", "nome do ativo",
                "nome", "ativo/produto"),
    "quantidade": ("quantidade", "qtd", "qtde", "quantidade de cotas", "qtde. cotas", "qtd. cotas", "cotas",
                   "quantidade total", "qtd total"),
    "preco": ("preco de fechamento", "preco de fechamento (r$)", "preco atualizado", "preco unitario",
              "pu atualizado", "preco atual", "cotacao", "valor da cota", "valor cota", "preco"),
    "valor": ("valor atualizado", "valor atualizado (r$)", "valor liquido", "valor bruto",
              "valor atualizado curva", "valor atualizado mtm", "saldo bruto", "saldo liquido", "saldo atual",
              "saldo", "valor de mercado", "valor atual", "valor bruto atual", "valor total", "total (r$)",
              "posicao", "saldo bruto (r$)", "saldo liquido (r$)"),
    "aplicado": ("valor aplicado", "valor aplicado (r$)", "valor investido", "valor de aquisicao",
                 "custo total", "total investido"),
    "preco_medio": ("preco medio", "preco medio (r$)", "pm", "custo medio", "preco medio de compra"),
    "vencimento": ("vencimento", "data de vencimento"),
}
CLASSE_POR_ABA = (("acao", "acao"), ("acoes", "acao"), ("bdr", "bdr"), ("etf", "etf"),
                  ("fundo", "fii"), ("fii", "fii"), ("tesouro", "renda_fixa"), ("renda fixa", "renda_fixa"),
                  ("coe", "renda_fixa"))
ETFS_CONHECIDOS = {"BOVA11", "IVVB11", "SMAL11", "HASH11", "DIVO11", "XINA11", "GOLD11", "BOVV11", "SPXI11",
                   "NASD11", "ACWI11", "EURP11", "FIND11", "MATB11", "IMAB11", "B5P211", "FIXA11", "QBTC11",
                   "BITH11", "ETHE11", "NTNS11", "LFTS11", "PIBB11", "BRAX11", "ECOO11", "SPXB11", "WRLD11"}


# Linhas de agrupamento/subtotal comuns em relatórios de carteira (não são ativos).
LINHAS_DE_GRUPO = {
    "renda fixa", "renda variavel", "acoes", "acao", "fundos imobiliarios", "fundos de investimento", "fundos",
    "fii", "fiis", "etf", "etfs", "bdr", "bdrs", "previdencia", "previdencia privada", "tesouro direto",
    "tesouro", "multimercado", "multimercados", "caixa", "saldo em conta", "conta corrente", "cripto",
    "criptoativos", "coe", "internacional", "exterior", "pos-fixado", "pre-fixado", "inflacao", "renda fixa pos",
    "renda fixa pre", "renda fixa inflacao", "fundos de renda fixa", "fundos multimercado", "fundos de acoes",
    "outros", "patrimonio", "patrimonio total", "carteira",
}


def _cabecalho_posicao(linhas):
    """Linha do cabeçalho de uma tabela de posição: (índice, colunas, largura) ou None."""
    for i, linha in enumerate(linhas[:80]):
        nomes = [_norm_cab(c) for c in linha]
        if "data do negocio" in nomes or "entrada/saida" in nomes or any("evento" in n for n in nomes):
            return None
        if nomes and nomes[0] in ("classe do ativo", "classe", "estrategia", "tipo de ativo", "mercado"):
            continue  # tabela de resumo por classe, não por ativo
        idx = _indices_flexiveis(nomes, COLUNAS_POSICAO, ultimos=("valor",))
        if ("codigo" in idx or "produto" in idx) and \
                (("quantidade" in idx and {"preco", "valor", "aplicado", "preco_medio"} & set(idx))
                 or ("valor" in idx and "data" not in nomes and "historico" not in nomes)):
            return i, idx, nomes
    return None


def classe_por_nome(nome):
    """Classe de produtos fora da bolsa pelo nome (relatórios de bancos)."""
    n = _norm(nome)
    if any(k in n for k in ("bolsa americ", "global", "exterior", "internac", "s&p", "nasdaq", "eua", "usa")):
        return "exterior"
    if re.search(r"\b(acoes|acao|ibovespa|dividendos|small caps?)\b", n):
        return "outro"  # fundo de ações
    if "poupan" in n:
        return "renda_fixa"
    if any(k in n for k in ("previd", "pgbl", "vgbl", "brasilprev")):
        return "outro"
    if any(re.search(rf"\b{k}\b", n) for k in ("fundo", "fic", "fim", "fia", "fi", "multimercado")):
        return "outro"
    if any(k in n for k in ("cripto", "bitcoin")):
        return "cripto"
    return "renda_fixa"  # CDB, LCA, LCI, Tesouro, debêntures, CRI, CRA, poupança...


def _celula(linha, i, nomes_cab):
    """Valor da coluna i; se vazio, tenta as colunas vizinhas sem cabeçalho (células mescladas no PDF)."""
    v = linha[i] if i < len(linha) else None
    if v in (None, "") or not str(v).strip():
        for j in (i + 1, i - 1):
            if 0 <= j < len(linha) and 0 <= j < len(nomes_cab) and not nomes_cab[j] and \
                    linha[j] not in (None, "") and str(linha[j]).strip():
                return linha[j]
    return v


def _nome_na_linha(linha, inicio):
    """Primeiro texto (não numérico) a partir da coluna do nome: cabeçalho "ATIVO" mesclado sobre 2 colunas."""
    for c in linha[inicio:]:
        t = str(c or "").strip()
        if t and _numero(t) is None and t not in ("R$", "-"):
            return t
    return None


# Nomes técnicos dos títulos públicos usados por bancos (ex.: relatório do Banco do Brasil).
TITULOS_PUBLICOS = (
    (r"^NTN-?B\s*PRINC", "TESOURO IPCA+"),
    (r"^NTN-?B\b", "TESOURO IPCA+ COM JUROS SEMESTRAIS"),
    (r"^NTN-?F\b", "TESOURO PREFIXADO COM JUROS SEMESTRAIS"),
    (r"^LTN\b", "TESOURO PREFIXADO"),
    (r"^LFT\b", "TESOURO SELIC"),
)


def titulo_tesouro_bb(nome):
    """'LFT-010329' -> ('TESOURO SELIC 2029', 'TESOURO SELIC 2029', '2029-03-01'); 'NTNB PRINC-150535' -> IPCA+ 2035."""
    n = re.sub(r"\s+", " ", str(nome or "")).strip().upper()
    for padrao, tipo in TITULOS_PUBLICOS:
        if re.match(padrao, n):
            m = re.search(r"(\d{6})\s*$", n)
            if not m:
                return None
            d = m.group(1)
            for formato in ("%d%m%y", "%y%m%d", "%Y%m"):
                try:
                    data = dt.datetime.strptime(d, formato).date()
                    break
                except ValueError:
                    continue
            else:
                return None
            ticker = f"{tipo} {data.year}"
            return ticker, ticker, data.isoformat()
    return None


def _realinhar(linha, largura, col_nome, sempre=False):
    """Ajusta linhas de PDF com número de colunas diferente do cabeçalho.

    Em PDFs sem tabela desenhada, um nome com espaços largos vira várias células e colunas vazias
    somem. Os textos à esquerda formam o nome do ativo e os números são encaixados nas colunas
    do cabeçalho da direita para a esquerda (onde ficam os valores nesses relatórios).
    """
    if len(linha) == largura and not sempre:
        return linha
    celulas = [str(c).strip() for c in linha if c not in (None, "") and str(c).strip() not in ("R$", "%", "-")]
    nome = []
    while celulas and _numero(celulas[0]) is None:
        nome.append(celulas.pop(0))
    if not nome or not celulas:
        return linha
    nova = [None] * largura
    nova[col_nome] = " ".join(nome)
    colunas = [i for i in range(largura) if i > col_nome]
    for i, valor in zip(colunas[-len(celulas):] if len(celulas) <= len(colunas) else colunas, celulas[-len(colunas):]):
        nova[i] = valor
    return nova


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
        inicio, idx, nomes_cab = achado
        largura = len(nomes_cab)
        col_nome = idx.get("codigo", idx.get("produto", 0))
        for n, linha in enumerate(linhas[inicio + 1:], start=inicio + 2):
            # PDF lido como texto: colunas montadas pela posição das palavras, sempre reorganiza
            linha = _realinhar(linha, largura, col_nome, sempre="texto" in aba)
            cel = {k: _celula(linha, i, nomes_cab) for k, i in idx.items()}
            for chave in ("codigo", "produto"):
                if chave in idx and not str(cel.get(chave) or "").strip():
                    cel[chave] = _nome_na_linha(linha, idx[chave])
            titulo = titulo_tesouro_bb(cel.get("codigo") or cel.get("produto"))
            if titulo:  # LFT-010329 -> TESOURO SELIC 2029
                cel["codigo"], cel["produto"], cel["vencimento"] = titulo
            produto = str(cel.get("produto") or "").strip()
            nome_norm = _norm(produto or cel.get("codigo"))
            if not any(c not in (None, "") for c in linha) or nome_norm.startswith(("total", "subtotal")) \
                    or nome_norm in LINHAS_DE_GRUPO:
                continue
            qtd = _numero(cel.get("quantidade"))
            saldo = _numero(cel.get("valor")) or _numero(cel.get("aplicado"))
            sem_quantidade = not qtd and bool(saldo and saldo > 0)
            if sem_quantidade:
                qtd = 1.0  # coluna de quantidade ausente ou vazia (CDB, fundos...): 1 unidade = saldo
            codigo = str(cel.get("codigo") or "").strip().upper()
            m = B3_TICKER.match(codigo)
            if m:
                ticker, origem = m.group(1), "b3"
            else:
                ticker, origem = ticker_do_produto(produto or codigo)
                if origem == "outro":  # CDB, LCA, fundos...: o nome (+ vencimento) identifica o título
                    venc = _data(cel.get("vencimento"))
                    nome_titulo = produto or str(cel.get("codigo") or "").strip()
                    ticker = re.sub(r"\s+", " ", f"{nome_titulo} {venc or ''}").strip().upper()[:60]
                    produto = produto or nome_titulo
                    origem = "renda_fixa"
            if not ticker or not qtd:
                lidos = " · ".join(str(c) for c in linha if c not in (None, ""))[:160]
                motivo = ("Sem nome/código do ativo." if not ticker else
                          "Sem quantidade nem saldo positivo.")
                ignorados.append({"linha": n, "descricao": f"{aba}: {lidos}", "motivo": motivo})
                continue
            valor, preco, aplicado = _numero(cel.get("valor")), _numero(cel.get("preco")), _numero(cel.get("aplicado"))
            preco_medio = _numero(cel.get("preco_medio"))
            if aplicado is None and preco_medio is not None:
                aplicado = preco_medio * qtd
            if preco is None and valor is not None:
                preco = valor / qtd
            classe = _classe_da_aba(aba, ticker, origem)
            if origem == "renda_fixa":
                classe = classe_por_nome(produto or codigo)
            if classe == "fii" and ticker in ETFS_CONHECIDOS:
                classe = "etf"
            texto_nome = produto or str(cel.get("codigo") or "")
            it = itens.setdefault(ticker, {"ticker": ticker, "classe": classe, "quantidade": 0.0,
                                           "sem_quantidade": sem_quantidade, "tesouro": origem == "tesouro",
                                           "vencimento": _data(cel.get("vencimento")),
                                           "valor_atual": 0.0, "custo_total": 0.0, "tem_custo": False,
                                           "nome": texto_nome.split(" - ", 1)[-1].strip()[:80] if " - " in texto_nome else ""})
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
    ops = list(aportes_existentes) + [a for a in aportes_novos if not a.get("ja_registrado")]
    for a in sorted(ops, key=lambda x: (x["data"], x.get("id") or 0)):
        if a.get("tipo") == "evento":
            saldo[a["ticker"]] = saldo.get(a["ticker"], 0.0) * a["fator"]
            continue
        sinal = 1 if a.get("tipo", "compra") == "compra" else -1
        saldo[a["ticker"]] = saldo.get(a["ticker"], 0.0) + sinal * float(a["quantidade"])
    todas = [a["data"] for a in list(aportes_existentes) + list(aportes_novos) if a.get("tipo") != "evento"]
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
            preco, origem = (p.get("preco_medio"), "valor aplicado informado no relatório") \
                if p and p.get("preco_medio") else (None, None)
            if preco is None and p and p.get("sem_quantidade"):
                # aplicação informada só pelo saldo: sem custo no relatório, usa o saldo atual
                preco, origem = p.get("preco_atual"), "saldo atual (custo não informado)"
            elif preco is None and p and p.get("classe") not in ("acao", "fii", "etf", "bdr") and p.get("preco_atual"):
                preco, origem = p["preco_atual"], "valor atual (custo não informado)"
            iniciais.append({"ticker": ticker, "classe": p["classe"] if p else classe_provavel(ticker),
                             "quantidade": diferenca, "data": data_abertura, "preco": preco,
                             "preco_origem": origem, "qtd_b3": qtd_b3})
        else:
            motivo = ("O sistema terá mais do que a B3 mostra: verifique vendas, grupamentos ou "
                      "transferências não importados." if p is not None else
                      "Não aparece na posição da B3. Se for um ativo fora da B3 (cripto, previdência...), ignore.")
            divergencias.append({"ticker": ticker, "qtd_b3": qtd_b3, "qtd_sistema": saldo.get(ticker, 0.0),
                                 "motivo": motivo})
    return {"data_abertura": data_abertura, "posicoes_iniciais": iniciais, "divergencias": divergencias}
