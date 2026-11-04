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
    """Lê .xlsx ou .csv e devolve a lista de linhas (listas de células)."""
    nome = (nome_arquivo or "").lower()
    if nome.endswith((".xlsx", ".xlsm")):
        try:
            import openpyxl
        except ImportError as e:
            raise ErroImportacao("Instale o pacote openpyxl para ler arquivos Excel "
                                 "(pip install -r requirements.txt).") from e
        try:
            wb = openpyxl.load_workbook(io.BytesIO(conteudo), read_only=True, data_only=True)
        except Exception as e:
            raise ErroImportacao(f"Não foi possível abrir o Excel: {e}") from e
        linhas = []
        for ws in wb.worksheets:
            linhas.extend(list(r) for r in ws.iter_rows(values_only=True))
        return linhas
    if nome.endswith((".csv", ".txt")):
        for codificacao in ("utf-8-sig", "latin-1"):
            try:
                texto = conteudo.decode(codificacao)
                break
            except UnicodeDecodeError:
                continue
        delim = ";" if texto.count(";") > texto.count(",") else ","
        return [r for r in csv.reader(io.StringIO(texto), delimiter=delim)]
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


def _localizar_cabecalho(linhas):
    for i, linha in enumerate(linhas):
        nomes = [_norm(c) for c in linha]
        if "codigo de negociacao" in nomes and "data do negocio" in nomes:
            return "negociacao", i, nomes
        if "movimentacao" in nomes and "produto" in nomes and "entrada/saida" in nomes:
            return "movimentacao", i, nomes
    raise ErroImportacao("Não reconheci o arquivo. Use o extrato de Negociação ou de Movimentação "
                         "da Área do Investidor da B3, sem alterar o cabeçalho.")


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
    if origem == "tesouro":
        return "renda_fixa"
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


def analisar_extrato(conteudo, nome_arquivo):
    linhas = ler_planilha(conteudo, nome_arquivo)
    tipo, inicio, nomes = _localizar_cabecalho(linhas)
    if tipo == "negociacao":
        aportes, proventos, ignorados = _negociacao(linhas, inicio, nomes)
    else:
        aportes, proventos, ignorados = _movimentacao(linhas, inicio, nomes)
    return {"tipo_arquivo": tipo, "aportes": aportes, "proventos": proventos, "ignorados": ignorados}


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
