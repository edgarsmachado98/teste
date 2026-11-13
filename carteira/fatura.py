"""Leitura de faturas de cartão de crédito (OFX, CSV e Excel) e categorização automática.

Cada fatura vira uma lista de itens {data, descricao, valor, tipo, parcela_num, parcela_total, fitid}:
  tipo = compra | estorno | pagamento | tarifa
O valor é sempre positivo; o tipo diz o sentido. Pagamentos da fatura são ignorados na importação
(o dinheiro já saiu da conta quando a fatura foi paga) e estornos entram como reembolso.
"""
import hashlib
import re
import unicodedata

from .importacao import ErroImportacao, _data, _numero, ler_abas

# ------------------------------------------------------------------ texto

def normalizar(texto):
    t = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode().upper()
    return re.sub(r"\s+", " ", t).strip()


RE_PARCELA = re.compile(r"(\bPARC(?:ELA)?\.?\s*)?\b(\d{1,2})\s*(?:/|DE)\s*(\d{1,2})\b")


def parcela_de(descricao):
    """'LOJA X PARC 03/10' ou 'LOJA X - Parcela 3/10' -> (3, 10, 'LOJA X'). Sem parcela: (None, None, desc).

    Sem a palavra PARC/PARCELA, só vale "n/total" no fim do texto (para não confundir com datas).
    """
    d = normalizar(descricao)
    for m in RE_PARCELA.finditer(d):
        n, total = int(m.group(2)), int(m.group(3))
        if not m.group(1) and d[m.end():].strip():
            continue
        if 1 <= n <= total <= 99 and total > 1:
            base = (d[:m.start()] + d[m.end():]).replace(" - ", " ")
            base = re.sub(r"\bPARC(ELA)?\b\.?", " ", base)
            return n, total, re.sub(r"\s+", " ", base).strip(" -*")
    return None, None, d


PAGAMENTO = ("PAGAMENTO RECEBIDO", "PAGAMENTO EM ", "PAGAMENTO EFETUADO", "PAGAMENTO DE FATURA", "PAGTO", "PGTO", "PAGAMENTO FATURA",
             "PAGAMENTO ON LINE", "PAGAMENTO ONLINE", "PAGAMENTO - OBRIGADO", "PAGAMENTO OBRIGADO", "PGTO FATURA")
TARIFA = ("IOF", "ANUIDADE", "TARIFA", "JUROS", "ENCARGOS", "MULTA")


def classificar(descricao, negativo_e_compra, valor):
    """Tipo do item a partir do texto e do sinal (já convertido para o padrão 'compra positiva')."""
    d = normalizar(descricao)
    if any(d.startswith(p) or p in d for p in PAGAMENTO):
        return "pagamento"
    if valor < 0:
        return "estorno"
    if any(re.search(rf"\b{t}\b", d) for t in TARIFA):
        return "tarifa"
    return "compra"


def chave_estabelecimento(descricao):
    """Chave curta do estabelecimento, usada para aprender a categoria.

    'IFOOD *RESTAURANTE BOM SAO PAULO BR' -> 'IFOOD RESTAURANTE'; 'UBER *TRIP HELP.UBER.COM' -> 'UBER TRIP'.
    """
    _, _, base = parcela_de(descricao)
    t = re.sub(r"[^A-Z ]", " ", base)
    palavras = [p for p in t.split() if len(p) >= 2 and p not in ("BR", "SAO", "PAULO", "RIO", "DE", "DO", "DA", "EM", "COM", "WWW")]
    return " ".join(palavras[:2])


# ------------------------------------------------------------------ OFX

def _tag(bloco, nome):
    m = re.search(rf"<{nome}>([^<\r\n]*)", bloco, re.I)
    return m.group(1).strip() if m else None


def ler_ofx(texto):
    cartao = "CREDITCARDMSGSRS" in texto.upper() or "CCSTMTRS" in texto.upper()
    itens = []
    for bloco in re.findall(r"<STMTTRN>(.*?)(?:</STMTTRN>|(?=<STMTTRN>)|</BANKTRANLIST>)", texto, re.S | re.I):
        data_txt = (_tag(bloco, "DTPOSTED") or "")[:8]
        valor = _numero((_tag(bloco, "TRNAMT") or "").replace(",", "."))
        desc = _tag(bloco, "MEMO") or _tag(bloco, "NAME") or ""
        if len(data_txt) != 8 or valor is None:
            continue
        data = f"{data_txt[:4]}-{data_txt[4:6]}-{data_txt[6:8]}"
        # no OFX, compras saem como valor negativo (débito) e pagamentos/estornos como positivo
        valor = -valor
        itens.append({"data": data, "descricao": desc, "valor_assinado": valor, "fitid": _tag(bloco, "FITID")})
    if not itens:
        raise ErroImportacao("O arquivo OFX não tem lançamentos.")
    return itens, cartao


# ------------------------------------------------------------------ CSV / Excel

COL_DATA = ("data", "date", "data da compra", "data compra", "data lancamento", "data de lancamento", "dt")
COL_DESC = ("descricao", "lancamento", "title", "estabelecimento", "historico", "description", "detalhe",
            "descricao do lancamento", "lançamento")
COL_VALOR = ("valor", "amount", "valor (r$)", "valor r$", "valor em r$", "valor brl", "valor original")


def _achar(nomes, opcoes):
    for o in opcoes:
        if o in nomes:
            return nomes.index(o)
    for i, n in enumerate(nomes):
        if any(n.startswith(o) for o in opcoes):
            return i
    return None


def ler_planilha_fatura(conteudo, nome_arquivo):
    from .importacao import _norm
    for _, linhas in ler_abas(conteudo, nome_arquivo):
        for i, linha in enumerate(linhas[:30]):
            nomes = [_norm(c) for c in linha]
            cd, cs, cv = _achar(nomes, COL_DATA), _achar(nomes, COL_DESC), _achar(nomes, COL_VALOR)
            if None in (cd, cs, cv):
                continue
            itens = []
            for l in linhas[i + 1:]:
                if max(cd, cs, cv) >= len(l):
                    continue
                data, valor = _data(l[cd]), _numero(l[cv])
                desc = str(l[cs] or "").strip()
                if data and valor is not None and desc:
                    itens.append({"data": data, "descricao": desc, "valor_assinado": valor, "fitid": None})
            if itens:
                # o sinal das compras varia por banco: a maioria dos itens de uma fatura são compras
                positivos = sum(1 for x in itens if x["valor_assinado"] > 0)
                if positivos < len(itens) / 2:
                    for x in itens:
                        x["valor_assinado"] = -x["valor_assinado"]
                return itens
    raise ErroImportacao("Não encontrei a tabela da fatura (colunas de data, descrição e valor). "
                         "Envie a fatura em OFX, CSV ou Excel.")


# ------------------------------------------------------------------ PDF

# Linha de lançamento no texto do PDF: "05/10 SUPERMERCADO X SAO PAULO BR 123,45" (valor em US$ opcional depois)
RE_LINHA_PDF = re.compile(
    r"^(\d{2})/(\d{2})(?:/(\d{2,4}))?\s+(.+?)\s+(-\s?)?(?:R\$\s*)?(\d{1,3}(?:\.\d{3})*,\d{2})(\s?-)?"
    r"(?:\s+(?:US\$\s*)?-?\d{1,3}(?:\.\d{3})*,\d{2}-?)?\s*$")
IGNORAR_PDF = ("SALDO", "TOTAL", "SUBTOTAL", "LIMITE", "PAGAMENTO MINIMO", "VALOR MINIMO", "MINIMO", "VENCIMENTO",
               "FATURA ANTERIOR", "ENCARGOS DO PROXIMO", "CUSTO EFETIVO", "TAXA", "PREVISAO", "MELHOR DATA",
               "DATA DE FECHAMENTO", "PERIODO", "COTACAO DO DOLAR", "DOLAR DE CONVERSAO")


# Layout com o mês por extenso (Nubank e outros): "05 OUT •••• 1234 Supermercados R$ 123,45" / "−R$ 9,90"
MESES = {"JAN": 1, "FEV": 2, "MAR": 3, "ABR": 4, "MAI": 5, "JUN": 6, "JUL": 7, "AGO": 8, "SET": 9, "OUT": 10,
         "NOV": 11, "DEZ": 12}
RE_LINHA_MES = re.compile(
    r"^(\d{1,2})\s+(JAN|FEV|MAR|ABR|MAI|JUN|JUL|AGO|SET|OUT|NOV|DEZ)[A-Z]*\.?(?:\s+(\d{4}))?\s+"
    r"(?:[•*·∙.]{2,}\s*(\d{4})\s+)?(.+?)\s+([−–-]\s?)?(?:R\$\s*)?([−–-]\s?)?(\d{1,3}(?:\.\d{3})*,\d{2})\s*$",
    re.IGNORECASE)
# Seções da fatura em que o banco já agrupa as compras (BB): viram sugestão de categoria
CATEGORIAS_BANCO = {"RESTAURANTES": "Restaurante", "RESTAURANTE": "Restaurante", "SUPERMERCADOS": "Mercado",
                    "SUPERMERCADO": "Mercado", "EDUCACAO": "Cursos", "VESTUARIO": "Roupas", "SAUDE": "Farmácia",
                    "FARMACIAS": "Farmácia", "VIAGENS": "Viagens", "TURISMO": "Viagens", "HOTEIS": "Viagens",
                    "LAZER": "Passeios", "ENTRETENIMENTO": "Passeios", "COMBUSTIVEL": "Combustível", "POSTOS": "Combustível",
                    "AUTOMOTIVO": "Manutenção do carro", "TELEFONIA": "Internet / telefone", "VAREJO": "Compras (lojas e internet)",
                    "LOJAS": "Compras (lojas e internet)", "CASA E DECORACAO": "Manutenção", "PETS": "Pets",
                    "ASSINATURAS": "Streaming / assinaturas", "TRANSPORTE": "Aplicativo / táxi", "BELEZA": "Beleza / cuidados"}
SECOES_SEM_CATEGORIA = {"PAGAMENTOS/CREDITOS", "PAGAMENTOS / CREDITOS", "COMPRAS PARCELADAS", "SERVICOS", "OUTROS",
                        "OUTROS LANCAMENTOS", "DIVERSOS", "ENCARGOS", "TARIFAS"}
RE_PORTADOR_BB = re.compile(r"^(?:Cart[ãa]o\s+)?(.+?)\s*\((?:Cart[ãa]o\s*)?(?:final\s*)?(\d{4})\)\s*$", re.IGNORECASE)
# Sicredi: "05/out 14:32 Santa Maria Presencial Loja X R$ 99,90" (cidade e tipo de compra antes da loja;
# compras no exterior trazem o valor em dólar e a cotação antes do valor em reais)
RE_LINHA_DIA_MES = re.compile(
    r"^(\d{1,2})/(jan|fev|mar|abr|mai|jun|jul|ago|set|out|nov|dez)[a-z]*\.?(?:/(\d{2,4}))?\s+(?:\d{1,2}:\d{2}\s+)?(.+?)\s+"
    r"([−–-]\s?)?R\$\s*([−–-]\s?)?(\d{1,3}(?:\.\d{3})*,\d{2})\s*$", re.IGNORECASE)
TIPOS_COMPRA = r"(?:Presencial|Online|On-line|Internet|Digital|Contactless|Aproxima[çc][ãa]o|Carteira digital|Recorrente|Assinatura|Telefone)"

# Subtotal por portador do cartão (titular e adicionais): "Edgar S Machado R$ 1.234,56"
RE_PORTADOR = re.compile(r"^([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'.]*(?:\s+[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'.]*){1,5})\s+R\$\s*\d{1,3}(?:\.\d{3})*,\d{2}$")

# Leitura flexível (segunda tentativa): o lançamento pode estar no meio da linha (fatura em duas colunas),
# ter algo depois do valor (país, "BR", valor em US$ com texto) ou a data com ponto ("05.10").
RE_ITEM_FLEX = re.compile(
    r"(?<![\d/.])(\d{2})[/.](\d{2})(?:[/.](\d{2,4}))?\s+((?:(?!\b\d{2}[/.]\d{2}\b).)+?)\s+(-\s?)?(?:R\$\s*)?"
    r"(\d{1,3}(?:\.\d{3})*,\d{2})(\s?-|\s?D\b|\s?C\b)?(?=\s|$)")


def _texto_pdf(conteudo, senha=None):
    try:
        import pdfplumber
        from pdfminer.pdfdocument import PDFPasswordIncorrect
    except ImportError as e:
        raise ErroImportacao("Instale o pacote pdfplumber para ler PDFs (pip install -r requirements.txt).") from e
    import io as _io
    try:
        with pdfplumber.open(_io.BytesIO(conteudo), password=senha or "") as pdf:
            return [(p.extract_text() or "") for p in pdf.pages]
    except PDFPasswordIncorrect:
        raise ErroImportacao("Este PDF tem senha. Informe a senha da fatura (no BB costuma ser parte do CPF; "
                             "veja no e-mail da fatura)." if not senha else "Senha do PDF incorreta.") from None
    except Exception as e:  # o pdfplumber embrulha os erros do pdfminer
        if "password" in repr(e).lower() or "encrypt" in repr(e).lower():
            raise ErroImportacao("Este PDF tem senha. Informe a senha da fatura (no BB costuma ser parte do CPF; "
                                 "veja no e-mail da fatura)." if not senha else "Senha do PDF incorreta.") from None
        raise ErroImportacao(f"Não foi possível abrir o PDF ({e.__class__.__name__}).") from None


def _ano_referencia(texto):
    """Data de vencimento da fatura (ou a data completa mais recente do texto), para completar o ano."""
    import datetime as _dt
    t = normalizar(texto)
    m = re.search(r"VENCIMENTO[^0-9]{0,40}(\d{2})/(\d{2})/(\d{4})", t)
    if m:
        return _dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    m = re.search(r"VENCIMENTO[^0-9]{0,40}(\d{1,2}) (JAN|FEV|MAR|ABR|MAI|JUN|JUL|AGO|SET|OUT|NOV|DEZ)[A-Z]* (\d{4})", t)
    if m:
        return _dt.date(int(m.group(3)), MESES[m.group(2)], int(m.group(1)))
    datas = []
    for d, mth, a in re.findall(r"\b(\d{2})/(\d{2})/(\d{4})\b", t):
        try:
            datas.append(_dt.date(int(a), int(mth), int(d)))
        except ValueError:
            continue
    return max(datas) if datas else _dt.date.today()


def ler_pdf_fatura(conteudo, senha=None):
    """Lançamentos de uma fatura em PDF (texto), linha a linha: data dd/mm, descrição e valor em R$."""
    paginas = _texto_pdf(conteudo, senha)
    texto = "\n".join(paginas)
    if not texto.strip():
        raise ErroImportacao("O PDF não tem texto (parece escaneado). Baixe a fatura em PDF pelo app ou site do banco.")
    ref = _ano_referencia(texto)
    itens = _itens_do_texto(texto, ref)
    if not itens:  # layout diferente: tenta achar os lançamentos em qualquer ponto da linha
        itens = _itens_do_texto(texto, ref, flexivel=True)
    if not itens:
        try:  # texto montado pelas palavras (alguns PDFs saem com as colunas embaralhadas)
            itens = _itens_do_texto("\n".join(_linhas_por_palavras(conteudo, senha)), ref, flexivel=True)
        except Exception:
            itens = []
    if itens and sum(1 for x in itens if x["valor_assinado"] > 0) < len(itens) / 2:
        for x in itens:  # banco que mostra as compras com sinal negativo
            x["valor_assinado"] = -x["valor_assinado"]
    com_cidade = [x for x in itens if x.pop("com_cidade", False)]
    if com_cidade:  # BB: "LOJA X SANTA MARIA" / "LOJA XSANTA MARIA" -> "LOJA X"
        for x, nova in zip(com_cidade, sem_cidade([x["descricao"] for x in com_cidade])):
            x["descricao"] = nova
    if not itens:
        raise ErroImportacao("Não encontrei lançamentos neste PDF. Rode o diagnóstico da fatura "
                             "(python diagnostico_fatura.py \"arquivo.pdf\" --senha SUA_SENHA) e envie o arquivo "
                             "diagnostico_fatura.txt que ele cria (os números saem mascarados).")
    return itens


def sem_cidade(descricoes):
    """Tira a cidade do fim das descrições (o BB imprime "LOJA <cidade> BR", às vezes colada no nome quando
    o nome ocupa a coluna toda). A cidade é o final que se repete em várias compras: "SANTA MARIA" aparece
    em muitas; "LANCHES SANTA MARIA" em poucas (é a loja, não a cidade)."""
    textos = [normalizar(d) for d in descricoes]
    candidatos = set()
    for t in textos:
        ws = t.split()
        for k in (1, 2, 3):
            if len(ws) > k:
                candidatos.add(" ".join(ws[-k:]))
    # quantas descrições terminam com o candidato (inclusive coladas: "LTSANTA MARIA" termina com "SANTA MARIA")
    cont = {c: sum(1 for t in textos if t.endswith(c)) for c in candidatos}
    cidades = []
    for c, n in cont.items():
        ws = c.split()
        if n < 2 or len(c) < 5 or not re.fullmatch(r"[A-Z ]+", c) or re.search(r"\bPARC\b", c):
            continue
        # um final mais curto que aparece em mais compras mostra que este inclui parte do nome da loja
        if any(cont.get(" ".join(ws[i:]), 0) > n for i in range(1, len(ws))):
            continue
        if len({t[:-len(c)].strip() for t in textos if t.endswith(c)}) < 2:  # uma loja só repetida: não é cidade
            continue
        cidades.append(c)
    cidades.sort(key=len, reverse=True)
    saida = []
    for d in descricoes:
        nova = d
        for c in cidades:
            if normalizar(d).endswith(c):
                if len(d) - len(c) >= 3:
                    nova = d[:len(d) - len(c)].rstrip(" -")
                break
        saida.append(nova)
    return saida


def chave_texto(descricao):
    """Descrição só com letras e números, sem país no fim: para reconhecer o mesmo lançamento importado
    com versões diferentes do leitor ("LOJA XSANTA MARIA BR" e "LOJA X")."""
    t = re.sub(r"[^A-Z0-9]", "", normalizar(parcela_de(descricao)[2]))
    return re.sub(r"(BR|BRR)$", "", t)


def mesmo_texto(a, b):
    a, b = chave_texto(a), chave_texto(b)
    return bool(a and b) and (a.startswith(b) or b.startswith(a)) and min(len(a), len(b)) >= 5


def _linhas_por_palavras(conteudo, senha=None):
    """Remonta as linhas do PDF pela posição das palavras (topo), da esquerda para a direita."""
    import io as _io
    import pdfplumber
    linhas = []
    with pdfplumber.open(_io.BytesIO(conteudo), password=senha or "") as pdf:
        for p in pdf.pages:
            grupos = {}
            for w in p.extract_words(x_tolerance=1.5, y_tolerance=2, keep_blank_chars=False):
                grupos.setdefault(round(w["top"] / 3), []).append(w)
            for _, ws in sorted(grupos.items()):
                linhas.append(" ".join(w["text"] for w in sorted(ws, key=lambda w: w["x0"])))
    return linhas


def _itens_do_texto(texto, ref, flexivel=False):
    import datetime as _dt
    itens, portador, secao, final_bb = [], None, None, None
    for linha in texto.splitlines():
        linha = linha.strip()
        chave_secao = normalizar(linha)
        if chave_secao in CATEGORIAS_BANCO or chave_secao in SECOES_SEM_CATEGORIA:
            secao = CATEGORIAS_BANCO.get(chave_secao)
            continue
        mb = RE_PORTADOR_BB.match(linha)
        if mb:
            portador, final_bb, secao = mb.group(1).strip(), mb.group(2), None
            continue
        if not flexivel:
            md = RE_LINHA_DIA_MES.match(linha)
            if md:
                dia, mes_txt, ano, desc, menos1, menos2, valor = md.groups()
                # tira cidade + tipo de compra do começo e o valor em dólar/cotação do fim
                desc = re.sub(rf"^.*?\b{TIPOS_COMPRA}\s+", "", desc, count=1, flags=re.IGNORECASE)
                desc = re.sub(r"(\s+-?\d{1,3}(?:\.\d{3})*,\d{2,4}){1,2}$", "", desc)
                item = _item_pdf((dia.zfill(2), f"{MESES[mes_txt.upper()[:3]]:02d}", ano, desc, menos1 or menos2, valor, None), ref)
                if item:
                    item.update(portador=portador, final=final_bb, categoria_banco=secao)
                    itens.append(item)
                continue
            mm = RE_LINHA_MES.match(linha)
            if mm:
                dia, mes_txt, ano, final, desc, menos1, menos2, valor = mm.groups()
                item = _item_pdf((dia.zfill(2), f"{MESES[mes_txt.upper()[:3]]:02d}", ano, desc, menos1 or menos2, valor, None), ref)
                if item:
                    item.update(final=final, portador=portador)
                    itens.append(item)
                continue
            mp = RE_PORTADOR.match(linha)
            if mp and not any(p in normalizar(mp.group(1)) for p in IGNORAR_PDF + ("FATURA", "PAGAR", "PAGAMENTO", "COMPRAS",
                                                                                     "LANCAMENTOS", "ANTERIOR", "JUROS")):
                portador = mp.group(1).strip()
                continue
        achados = list(RE_ITEM_FLEX.finditer(linha)) if flexivel else [m for m in [RE_LINHA_PDF.match(linha)] if m]
        for m in achados:
            item = _item_pdf(m.groups()[:7], ref)
            if item:
                item.update(portador=portador, final=final_bb, categoria_banco=secao)
                itens.append(item)
    return itens


def _item_pdf(grupos, ref):
    import datetime as _dt
    if True:
        dia, mes, ano_txt, desc, menos_antes, valor_txt, menos_depois = grupos
        menos_antes = (menos_antes or "").replace("−", "-").replace("–", "-") or None
        desc_n = normalizar(desc)
        if any(desc_n.startswith(p) or f" {p} " in f" {desc_n} " for p in IGNORAR_PDF) and not \
                any(p in desc_n for p in PAGAMENTO):
            return None
        if not re.search(r"[A-Z]{2}", desc_n):  # só números/símbolos: não é uma compra
            return None
        try:
            dia_i, mes_i = int(dia), int(mes)
            if ano_txt:
                ano = int(ano_txt) + (2000 if len(ano_txt) == 2 else 0)
            else:  # sem ano: o do vencimento; compras de meses depois dele são do ano anterior
                ano = ref.year if mes_i <= ref.month else ref.year - 1
            data = _dt.date(ano, mes_i, dia_i).isoformat()
        except ValueError:
            return None
        valor = _numero(valor_txt)
        credito = (menos_depois or "").strip() == "C"
        if menos_antes or (menos_depois and credito or (menos_depois or "").strip() == "-") \
                or re.search(r"\b(CR|CREDITO)\s*$", desc_n):
            valor = -valor
        # tira o país e o "R$" que alguns bancos imprimem antes do valor: "LOJA X SANTA MARIA BR R$"
        com_pais = bool(re.search(r"\s[A-Z]{2}(\s+R\$)?\s*$", desc.strip()))
        desc = re.sub(r"(\s+[A-Z]{2})?\s+R\$\s*$", "", desc.strip())
        desc = re.sub(r"\s+BR$", "", desc)
        return {"data": data, "descricao": desc.strip(), "valor_assinado": valor, "fitid": None, "com_cidade": com_pais}


def ler_fatura(conteudo, nome_arquivo, senha=None):
    """Lê a fatura e devolve os itens já classificados."""
    nome = (nome_arquivo or "").lower()
    if nome.endswith((".ofx", ".qfx")) or conteudo[:200].upper().lstrip().startswith((b"OFXHEADER", b"<OFX", b"<?XML")) \
            and b"<STMTTRN>" in conteudo.upper():
        for cod in ("utf-8", "latin-1"):
            try:
                texto = conteudo.decode(cod)
                break
            except UnicodeDecodeError:
                continue
        brutos, _ = ler_ofx(texto)
    elif nome.endswith(".pdf") or conteudo[:5] == b"%PDF-":
        brutos = ler_pdf_fatura(conteudo, senha)
    else:
        brutos = ler_planilha_fatura(conteudo, nome_arquivo)
    itens, vistos = [], {}
    for b in brutos:
        tipo = classificar(b["descricao"], True, b["valor_assinado"])
        n, total, base = parcela_de(b["descricao"])
        # parcela antecipada ("Antecipada - Loja - Parcela 10/12"): é a mesma parcela da compra, cobrada antes
        antecipada = bool(re.match(r"ANTECIPAD[AO]\b", base))
        if antecipada:
            base = re.sub(r"^ANTECIPAD[AO]\s*-?\s*", "", base)
        chave_bruta = b["fitid"] or f"{b['data']}|{normalizar(b['descricao'])}|{abs(b['valor_assinado']):.2f}"
        vistos[chave_bruta] = vistos.get(chave_bruta, 0) + 1  # compras idênticas no mesmo dia
        itens.append({"data": b["data"], "descricao": re.sub(r"\s+", " ", b["descricao"]).strip()[:120],
                      "valor": round(abs(b["valor_assinado"]), 2), "tipo": tipo,
                      "parcela_num": n, "parcela_total": total, "base": base,
                      "estabelecimento": chave_estabelecimento(re.sub(r"(?i)^antecipad[ao]\s*-?\s*", "", b["descricao"])),
                      "antecipada": antecipada, "portador": b.get("portador"), "final": b.get("final"),
                      "categoria_banco": b.get("categoria_banco"),
                      "id_arquivo": f"{chave_bruta}#{vistos[chave_bruta]}"})
    return itens


def chave_importacao(cartao_id, item):
    """Identifica o lançamento para não importar duas vezes (a parcela n de uma compra é sempre a mesma)."""
    if item.get("parcela_total"):
        grupo = grupo_parcelas(cartao_id, item)
        return f"p:{grupo}#{item['parcela_num']}"
    return "f:" + hashlib.sha1(f"{cartao_id}|{item['id_arquivo']}".encode()).hexdigest()[:20]


def grupo_parcelas(cartao_id, item):
    return hashlib.sha1(f"{cartao_id}|{item['base']}|{item['parcela_total']}|{item['valor']:.2f}".encode()).hexdigest()[:12]


# ------------------------------------------------------------------ categorias

# Palavra no nome do estabelecimento -> categoria padrão (as regras aprendidas com o usuário vêm antes).
REGRAS_PADRAO = [
    (("UBER EATS", "IFOOD", "RAPPI", "ZE DELIVERY", "AIQFOME", "DELIVERY"), "Delivery"),
    (("UBER", "99 ", "99APP", "99POP", "CABIFY", "TAXI"), "Aplicativo / táxi"),
    (("POSTO", "SHELL", "IPIRANGA", "PETROBRAS", "BR MANIA", "COMBUSTIV", "AUTO POSTO", "ALE "), "Combustível"),
    (("SEM PARAR", "CONECTCAR", "VELOE", "MOVE MAIS", "ESTACIONAMENTO", "ESTAPAR", "PEDAGIO", "ZUL "), "Estacionamento / pedágio"),
    (("NETFLIX", "SPOTIFY", "DISNEY", "HBO", "MAX ", "PRIME VIDEO", "AMAZON PRIME", "GLOBOPLAY", "YOUTUBE", "APPLE.COM",
      "GOOGLE ONE", "DEEZER", "PARAMOUNT", "CRUNCHYROLL", "STAR+"), "Streaming / assinaturas"),
    (("DROGA", "FARMA", "RAIA", "PACHECO", "PAGUE MENOS", "DROGASIL", "PANVEL", "NISSEI"), "Farmácia"),
    (("SMART FIT", "SMARTFIT", "BODYTECH", "BLUEFIT", "ACADEMIA", "GYMPASS", "WELLHUB", "TOTALPASS"), "Academia"),
    (("LABORATORIO", "CLINICA", "HOSPITAL", "MEDIC", "ODONTO", "DENTAL", "EXAME"), "Consultas / exames"),
    (("SUPERMERC", "MERCADO", "CARREFOUR", "ASSAI", "ATACADAO", "PAO DE ACUCAR", "EXTRA ", "SAMS CLUB", "MAKRO",
      "HORTIFRUTI", "SACOLAO", "ATACADISTA", "BIG ", "GUANABARA", "ZAFFARI", "SAVEGNAGO", "OBA "), "Mercado"),
    (("PADARIA", "PANIFICADORA", "CONFEITARIA"), "Padaria"),
    (("RESTAURANTE", "BURGER", "MCDONALD", "MC DONALD", "OUTBACK", "PIZZA", "LANCHONETE", "BAR ", "CHURRASC", "SUSHI",
      "CAFE", "STARBUCKS", "SUBWAY", "HABIBS", "SPOLETO", "MADERO", "COCO BAMBU", "BK "), "Restaurante"),
    (("LATAM", "GOL LINHAS", "AZUL LINHAS", "AZUL ", "DECOLAR", "AIRBNB", "BOOKING", "HOTEL", "POUSADA", "123MILHAS",
      "SMILES", "CVC", "LOCALIZA", "MOVIDA", "UNIDAS"), "Viagens"),
    (("CINEMA", "CINEMARK", "INGRESSO", "SYMPLA", "TEATRO", "SHOW", "PARQUE"), "Passeios"),
    (("CLARO", "VIVO", "TIM ", "OI ", "NET ", "SKY"), "Internet / telefone"),
    (("ENEL", "CEMIG", "COPEL", "LIGHT", "CPFL", "CELESC", "COELBA", "EQUATORIAL", "ENERGISA", "NEOENERGIA"), "Energia"),
    (("SABESP", "COPASA", "SANEPAR", "CEDAE", "EMBASA", "CORSAN", "SANEAMENTO"), "Água"),
    (("COMGAS", "ULTRAGAZ", "LIQUIGAS", "SUPERGASBRAS"), "Gás"),
    (("RENNER", "RIACHUELO", "C&A", "C A ", "ZARA", "HERING", "CENTAURO", "NETSHOES", "SHEIN", "MARISA", "DAFITI",
      "NIKE", "ADIDAS", "AREZZO"), "Roupas"),
    (("BOTICARIO", "NATURA", "SEPHORA", "SALAO", "BARBEARIA", "ESTETICA"), "Beleza / cuidados"),
    (("PETZ", "COBASI", "PET ", "VETERIN"), "Pets"),
    (("LIVRARIA", "SARAIVA", "KINDLE", "UDEMY", "ALURA", "COURSERA", "PAPELARIA"), "Livros / material"),
    (("ESCOLA", "COLEGIO", "FACULDADE", "UNIVERSIDADE", "MENSALIDADE"), "Escola / faculdade"),
    (("MAGAZINE LUIZA", "MAGALU", "AMAZON", "MERCADOLIVRE", "MERCADO LIVRE", "MERCADOPAGO", "SHOPEE", "ALIEXPRESS",
      "CASAS BAHIA", "PONTO FRIO", "AMERICANAS", "SUBMARINO", "KABUM", "FAST SHOP", "TEMU", "SHEIN"), "Compras (lojas e internet)"),
    (("IOF", "ANUIDADE", "TARIFA"), "Tarifas bancárias"),
    (("JUROS", "ENCARGOS", "MULTA"), "Juros / multas"),
    (("SEGURO AUTO", "PORTO SEGURO", "AZUL SEGUROS", "TOKIO MARINE"), "Seguro do carro"),
    (("OFICINA", "AUTO PECAS", "AUTOPECAS", "PNEU", "MECANICA", "LAVA JATO", "LAVA RAPIDO"), "Manutenção do carro"),
    (("LEROY", "TELHANORTE", "C&C", "MATERIAL DE CONSTRUCAO", "TOK STOK", "TOKSTOK", "ETNA", "CAMICADO"), "Manutenção"),
]


def sugerir_categoria(item, regras_usuario, categorias_por_nome):
    """(categoria_id, origem): 'aprendida' (regras do usuário), 'padrao' (palavras-chave) ou (None, None)."""
    if item["tipo"] == "estorno":
        cid = categorias_por_nome.get(("receita", "Estornos e reembolsos"))
        return cid, "padrao" if cid else None
    est = item["estabelecimento"]
    for padrao, cid in regras_usuario:  # mais específica (mais longa) primeiro
        if est == padrao or est.startswith(padrao + " ") or (padrao and padrao in normalizar(item["descricao"])):
            return cid, "aprendida"
    desc = " " + normalizar(item["descricao"]) + " "
    for palavras, nome in REGRAS_PADRAO:
        if any(p in desc or desc.lstrip().startswith(p.strip() + " ") for p in palavras):
            cid = categorias_por_nome.get(("despesa", nome))
            if cid:
                return cid, "padrao"
    if item.get("categoria_banco"):  # a categoria que o próprio banco deu na fatura
        cid = categorias_por_nome.get(("despesa", item["categoria_banco"]))
        if cid:
            return cid, "banco"
    return None, None


# ------------------------------------------------------------------ conciliação

DIAS_EXATO = 3          # mesma compra: mesmo valor e data até 3 dias de diferença
DIAS_POSSIVEL = 5       # possível correspondência: valor próximo (câmbio, IOF) e data até 5 dias
TOLERANCIA_PARCELA = 1.00


def _dias(a, b):
    import datetime as _dt
    return abs((_dt.date.fromisoformat(a) - _dt.date.fromisoformat(b)).days)


def _parecido(desc_a, desc_b):
    """Quantas palavras (de 3+ letras) as duas descrições têm em comum (só para desempate)."""
    pa = {p for p in re.sub(r"[^A-Z ]", " ", normalizar(desc_a)).split() if len(p) >= 3}
    pb = {p for p in re.sub(r"[^A-Z ]", " ", normalizar(desc_b)).split() if len(p) >= 3}
    return len(pa & pb)


def conciliar(itens, manuais):
    """Marca em cada item da fatura se ele corresponde a uma compra lançada à mão no mesmo cartão.

    itens: linhas da fatura (ainda não importadas); manuais: lançamentos do cartão ainda não conferidos
    [{id, data, valor, descricao, parcela_num, parcela_total, categoria_id}].
    Cada item ganha "conciliacao": {tipo: "exato"|"possivel", lancamento: {...}} ou None.
    Cada lançamento manual casa com no máximo uma linha; os exatos são resolvidos antes dos possíveis.
    """
    livres = {m["id"]: m for m in manuais}
    candidatos = [i for i in itens if i["tipo"] in ("compra", "tarifa") and not i.get("ja_importado")]
    for i in itens:
        i["conciliacao"] = None

    def escolher(item, filtro):
        opcoes = [m for m in livres.values() if filtro(m)]
        if not opcoes:
            return None
        return min(opcoes, key=lambda m: (_dias(m["data"], item["data"]) if not item.get("parcela_total") else 0,
                                          -_parecido(m["descricao"], item["descricao"]), m["id"]))

    # 1) parcela com parcela (mesmo total de parcelas, mesmo número, valor da parcela igual)
    for it in candidatos:
        if it.get("parcela_total"):
            m = escolher(it, lambda m, it=it: m.get("parcela_total") == it["parcela_total"]
                         and m.get("parcela_num") == it["parcela_num"]
                         and abs(m["valor"] - it["valor"]) <= TOLERANCIA_PARCELA)
            if m:
                it["conciliacao"] = {"tipo": "exato", "lancamento": m}
                del livres[m["id"]]
    # 2) mesmo valor e data próxima
    for it in candidatos:
        if it["conciliacao"] is None and not it.get("parcela_total"):
            m = escolher(it, lambda m, it=it: not m.get("parcela_total") and abs(m["valor"] - it["valor"]) < 0.005
                         and _dias(m["data"], it["data"]) <= DIAS_EXATO)
            if m:
                it["conciliacao"] = {"tipo": "exato", "lancamento": m}
                del livres[m["id"]]
    # 3) valor próximo (compra internacional, arredondamento): o usuário confirma
    for it in candidatos:
        if it["conciliacao"] is None:
            def proximo(m, it=it):
                limite = max(5.0, it["valor"] * 0.10)
                mesma_parcela = (m.get("parcela_total") or None) == (it.get("parcela_total") or None)
                return mesma_parcela and abs(m["valor"] - it["valor"]) <= limite and \
                    (it.get("parcela_total") or _dias(m["data"], it["data"]) <= DIAS_POSSIVEL)
            m = escolher(it, proximo)
            if m:
                it["conciliacao"] = {"tipo": "possivel", "lancamento": m}
                del livres[m["id"]]
    return itens
