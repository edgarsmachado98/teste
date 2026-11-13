"""Leitura da NFC-e (cupom fiscal eletrônico) a partir do QR Code impresso no cupom.

O QR Code da NFC-e contém o endereço do portal da Secretaria da Fazenda do estado e a chave de acesso
da nota (44 caracteres). A partir dele:

1. a chave já informa o estado, o mês de emissão, o CNPJ da loja e o número da nota;
2. a página pública do portal (a mesma que abre quando se lê o QR Code no celular) traz a loja, a data e
   hora, os itens, o valor pago e a forma de pagamento (dinheiro, Pix, débito, crédito...).

Quando o portal não responde (fora do ar, exige captcha, layout diferente), devolve o que dá para tirar
do próprio QR Code e o usuário completa o valor.

A foto pode ser lida no navegador (mais rápido, a imagem nem sai do celular) ou aqui no servidor
(zxing-cpp), que é mais tolerante a fotos tortas, escuras ou de longe.
"""
import html
import io
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

UF = {"11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP", "17": "TO", "21": "MA", "22": "PI",
      "23": "CE", "24": "RN", "25": "PB", "26": "PE", "27": "AL", "28": "SE", "29": "BA", "31": "MG", "32": "ES",
      "33": "RJ", "35": "SP", "41": "PR", "42": "SC", "43": "RS", "50": "MS", "51": "MT", "52": "GO", "53": "DF"}


class ErroNota(Exception):
    pass


# ------------------------------------------------------------------ chave de acesso

def _dv(chave43):
    """Dígito verificador (módulo 11, pesos 2 a 9 da direita para a esquerda). Aceita o CNPJ alfanumérico."""
    soma, peso = 0, 2
    for c in reversed(chave43):
        soma += (ord(c) - 48) * peso
        peso = 2 if peso == 9 else peso + 1
    resto = soma % 11
    return "0" if resto < 2 else str(11 - resto)


def chave_valida(chave):
    return bool(re.fullmatch(r"\d{6}[0-9A-Z]{14}\d{24}", chave or "")) and _dv(chave[:43]) == chave[43]


def dados_da_chave(chave):
    """Estado, ano/mês, CNPJ, modelo, série e número a partir da chave de acesso."""
    return {"chave": chave, "uf": UF.get(chave[:2], chave[:2]), "ano_mes": f"20{chave[2:4]}-{chave[4:6]}",
            "cnpj": chave[6:20], "modelo": chave[20:22], "serie": int(chave[22:25]), "numero": int(chave[25:34]),
            "tp_emis": chave[34]}


def formatar_cnpj(c):
    return f"{c[:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:]}" if len(c or "") == 14 else (c or "")


def ler_qrcode(texto):
    """Interpreta o conteúdo do QR Code (ou a chave digitada).

    Formatos do parâmetro p:
      on-line  v2: chave|2|ambiente|id_csc|hash            v3: chave|3|ambiente
      off-line v2: chave|2|ambiente|dia|valor|digest|id_csc|hash
      off-line v3: chave|3|ambiente|dia|valor|tp_dest|dest|assinatura
    No off-line o próprio QR Code já traz o dia da emissão e o valor total.
    """
    t = (texto or "").strip()
    if not t:
        raise ErroNota("Não encontramos o QR Code. Tente outra foto ou cole o link / a chave da nota.")
    url, p = None, None
    if re.match(r"(?i)^https?://", t):
        url = t
        q = urllib.parse.urlparse(t)
        params = urllib.parse.parse_qs(q.query, keep_blank_values=True)
        p = (params.get("p") or params.get("chNFe") or params.get("chave") or [""])[0]
        if not p:
            achou = re.search(r"\d{44}", t)
            p = achou.group(0) if achou else ""
    else:
        p = t
    partes = [x.strip() for x in p.split("|")]
    chave = re.sub(r"[\s.\-/]", "", partes[0]).upper()
    if not chave_valida(chave):
        raise ErroNota("Este QR Code não é de uma NFC-e (cupom fiscal) ou a chave de acesso está incompleta.")
    d = dados_da_chave(chave)
    if d["modelo"] != "65":
        raise ErroNota("Esta chave é de uma NF-e (nota de compra grande ou on-line), não de um cupom NFC-e. "
                       "Lance pelo formulário normalmente.")
    d["url"] = url
    d["versao"] = partes[1] if len(partes) > 1 else None
    if len(partes) >= 5 and re.fullmatch(r"\d{1,2}", partes[3]) and re.fullmatch(r"\d+(\.\d{1,2})?", partes[4]):
        d["dia"], d["total"] = int(partes[3]), float(partes[4])  # emitida off-line: dia e valor no próprio QR
    return d


# ------------------------------------------------------------------ portal da Sefaz

class _Html(HTMLParser):
    """Árvore mínima: cada elemento guarda tag, atributos e texto (com o dos filhos)."""

    VAZIAS = {"br", "img", "input", "meta", "link", "hr", "col", "area", "base", "wbr", "source"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.elementos, self.pilha = [], []

    def handle_starttag(self, tag, attrs):
        el = {"tag": tag, "attrs": dict(attrs), "texto": [], "classes": set((dict(attrs).get("class") or "").split())}
        self.elementos.append(el)
        if tag in self.VAZIAS:
            if tag == "br":
                for p in self.pilha:
                    p["texto"].append("\n")
            return
        self.pilha.append(el)

    def handle_endtag(self, tag):
        for i in range(len(self.pilha) - 1, -1, -1):
            if self.pilha[i]["tag"] == tag:
                del self.pilha[i:]
                return

    def handle_data(self, data):
        for p in self.pilha:
            p["texto"].append(data)


def _limpo(t):
    return re.sub(r"\s+", " ", html.unescape(t or "")).strip()


def _num(t):
    t = re.sub(r"[^\d,.\-]", "", t or "")
    if not t:
        return None
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def _sem_acento(t):
    return unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()


def forma_pagamento(texto):
    """Texto do cupom -> forma de pagamento do sistema (ou None quando não há equivalente, ex.: vale-refeição)."""
    t = _sem_acento(texto)
    if "pix" in t or "instantaneo" in t:
        return "pix"
    if "credito" in t and "loja" not in t:
        return "credito"
    if "debito" in t:
        return "debito"
    if "dinheiro" in t or "especie" in t:
        return "dinheiro"
    if "boleto" in t:
        return "boleto"
    if "transfer" in t:
        return "transferencia"
    return None


RE_DATA = re.compile(r"(\d{2})/(\d{2})/(\d{4})\s+(\d{2}):(\d{2})(?::(\d{2}))?")


def ler_pagina(texto_html):
    """Dados da nota na página de consulta pública (layout nacional usado pela maioria dos estados).

    Elementos do layout: div.txtTopo (loja), div.text (CNPJ e endereço), span.txtTit/txtTit2 (produto),
    span.Rqtd, span.RUN, span.RvlUnit, span.valor (itens), div#totalNota com label + span.totalNumb
    (quantidade, valor total, descontos, valor a pagar, formas de pagamento, troco) e a data de emissão.
    Para layouts diferentes, um leitor de texto procura os mesmos rótulos ("Valor a pagar", "Emissão"...).
    """
    p = _Html()
    p.feed(texto_html or "")
    els = p.elementos
    txt = lambda el: _limpo("".join(el["texto"]))  # noqa: E731
    classe = lambda c: [el for el in els if c in el["classes"]]  # noqa: E731
    pagina = _limpo(re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", texto_html or "")))
    nota = {"emitente": None, "cnpj": None, "endereco": None, "data": None, "total": None, "desconto": 0.0,
            "itens": [], "pagamentos": [], "troco": 0.0}

    topo = classe("txtTopo")
    if topo:
        nota["emitente"] = txt(topo[0])
    for el in classe("text"):
        t = txt(el)
        m = re.search(r"CNPJ:?\s*([\d./\-A-Z]{14,18})", t)
        if m and not nota["cnpj"]:
            nota["cnpj"] = re.sub(r"[^0-9A-Z]", "", m.group(1))
        elif t and not nota["endereco"] and not t.upper().startswith("CNPJ"):
            nota["endereco"] = t

    # itens: cada linha da tabela de resultados tem o nome e o valor
    nomes = classe("txtTit2") or [el for el in classe("txtTit") if el["tag"] == "span" and "totalNumb" not in el["classes"]]
    qtds, uns, units, vals = classe("Rqtd"), classe("RUN"), classe("RvlUnit"), \
        [el for el in classe("valor") if el["tag"] == "span"]
    for i, n in enumerate(nomes):
        item = {"descricao": txt(n)[:80],
                "qtd": _num(txt(qtds[i]).split(":")[-1]) if i < len(qtds) else None,
                "un": txt(uns[i]).split(":")[-1].strip() if i < len(uns) else "",
                "unitario": _num(txt(units[i]).split(":")[-1]) if i < len(units) else None,
                "valor": _num(txt(vals[i])) if i < len(vals) else None}
        if item["descricao"]:
            nota["itens"].append(item)

    # totais e pagamentos: pares rótulo -> valor dentro de #totalNota / #linhaTotal / #linhaForma
    # o layout alterna <label>rótulo</label><span class="totalNumb">valor</span>
    pares, rotulo = [], None
    for el in els:
        if el["tag"] == "label":
            rotulo = el
        elif "totalNumb" in el["classes"] and rotulo is not None:
            pares.append((txt(rotulo), txt(el), "tx" in rotulo["classes"]))
            rotulo = None
    em_formas = False
    for rot, val, eh_forma in pares:
        r = _sem_acento(rot)
        v = _num(val)
        if "forma de pagamento" in r:
            em_formas = True
            continue
        if "troco" in r:
            nota["troco"] = v or 0.0
            continue
        if eh_forma or em_formas:
            if v is not None and v > 0:
                nota["pagamentos"].append({"forma_texto": rot, "forma": forma_pagamento(rot), "valor": v})
            continue
        if "a pagar" in r:
            nota["total"] = v
        elif "desconto" in r and v:
            nota["desconto"] = v
        elif "valor total" in r and nota["total"] is None:
            nota["total"] = v

    # leitor de texto: outros layouts (e conferência do layout padrão)
    if nota["total"] is None:
        m = re.search(r"(?i)valor\s+(?:a\s+pagar|total(?:\s+da\s+nota)?)\s*(?:R\$)?\s*:?\s*([\d.]+,\d{2})", pagina)
        if m:
            nota["total"] = _num(m.group(1))
    if not nota["pagamentos"]:
        for m in re.finditer(r"(?i)(dinheiro|pix|pagamento instant[âa]neo|cart[ãa]o de cr[ée]dito|cart[ãa]o de d[ée]bito"
                             r"|vale (?:alimenta[çc][ãa]o|refei[çc][ãa]o)|boleto banc[áa]rio)\s*(?:R\$)?\s*:?\s*([\d.]+,\d{2})",
                             pagina):
            nota["pagamentos"].append({"forma_texto": m.group(1), "forma": forma_pagamento(m.group(1)),
                                       "valor": _num(m.group(2))})
    if not nota["cnpj"]:
        m = re.search(r"CNPJ:?\s*(\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2})", pagina)
        if m:
            nota["cnpj"] = re.sub(r"\D", "", m.group(1))
    m = re.search(r"(?i)emiss[ãa]o:?\s*" + RE_DATA.pattern, pagina) or RE_DATA.search(pagina)
    if m:
        g = m.groups()[-6:]
        nota["data"] = f"{g[2]}-{g[1]}-{g[0]}T{g[3]}:{g[4]}"
    return nota


def ajustar_pagamentos(nota):
    """Troco sai do dinheiro; sem forma informada, o total fica numa forma 'não informada'."""
    total = nota.get("total")
    pags = nota["pagamentos"]
    troco = nota.get("troco") or 0
    if total and pags:
        soma = sum(p["valor"] for p in pags)
        sobra = round(soma - total, 2)
        if sobra > 0:
            troco = max(troco, sobra)
        if troco:
            for p in pags:
                if p["forma"] == "dinheiro" and p["valor"] > troco:
                    p["valor"] = round(p["valor"] - troco, 2)
                    break
    if not pags and total:
        nota["pagamentos"] = [{"forma_texto": "não informada", "forma": None, "valor": total}]
    return nota


# ------------------------------------------------------------------ acesso ao portal

class _SoGovBr(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not host_permitido(newurl):
            raise ErroNota("O portal redirecionou para um endereço fora do governo; a consulta foi interrompida.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def host_permitido(url):
    """Só consulta portais oficiais (*.gov.br): o servidor nunca acessa um endereço qualquer vindo de um QR Code."""
    try:
        q = urllib.parse.urlparse(url)
    except ValueError:
        return False
    host = (q.hostname or "").lower()
    return q.scheme in ("http", "https") and (host.endswith(".gov.br") or host == "gov.br")


def _abrir(url, timeout=15):
    abridor = urllib.request.build_opener(_SoGovBr)
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/124.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml", "Accept-Language": "pt-BR,pt;q=0.9"})
    with abridor.open(req, timeout=timeout) as r:
        bruto = r.read(3_000_000)
        cs = r.headers.get_content_charset()
    for cod in filter(None, (cs, "utf-8", "latin-1")):
        try:
            return bruto.decode(cod)
        except (UnicodeDecodeError, LookupError):
            continue
    return bruto.decode("latin-1", "replace")


def buscar_pagina(url, abrir=None):
    """Baixa a página da nota; segue o quadro interno que alguns portais usam (ex.: RS)."""
    abrir = abrir or _abrir
    if not host_permitido(url):
        raise ErroNota("Este QR Code não aponta para um portal da Secretaria da Fazenda.")
    pagina = abrir(url)
    if "txtTopo" not in pagina:
        m = re.search(r"""(?is)<i?frame[^>]+src=["']([^"']+)["']""", pagina)
        if m:
            interno = urllib.parse.urljoin(url, html.unescape(m.group(1)))
            if host_permitido(interno):
                pagina = abrir(interno)
    return pagina


def consultar(texto_qr, abrir=None):
    """Chave + dados do portal. Nunca falha por causa do portal: devolve 'aviso' e o que conseguiu."""
    d = ler_qrcode(texto_qr)
    nota = {"emitente": None, "cnpj": d["cnpj"], "endereco": None, "data": None, "total": d.get("total"),
            "desconto": 0.0, "itens": [], "pagamentos": [], "troco": 0.0}
    fonte, aviso = "qrcode", None
    if d.get("url"):
        try:
            lida = ler_pagina(buscar_pagina(d["url"], abrir))
            if lida["total"] or lida["itens"]:
                nota.update({k: v for k, v in lida.items() if v not in (None, [], "")})
                fonte = "portal"
            else:
                aviso = ("O portal da Sefaz abriu, mas não mostrou os dados da nota (pode pedir uma verificação "
                         "\"não sou um robô\"). Confira o valor e a forma de pagamento.")
        except ErroNota as e:
            aviso = str(e)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            aviso = "O portal da Sefaz não respondeu agora. Confira o valor e a forma de pagamento; dá para lançar assim mesmo."
    else:
        aviso = "Só a chave foi informada: complete o valor e a forma de pagamento."
    if not nota["data"]:
        dia = d.get("dia")
        nota["data"] = f"{d['ano_mes']}-{dia:02d}" if dia else None
    ajustar_pagamentos(nota)
    nota["cnpj"] = nota["cnpj"] or d["cnpj"]
    return {**d, **nota, "cnpj_formatado": formatar_cnpj(nota["cnpj"]), "fonte": fonte, "aviso": aviso,
            "descricao": nome_loja(nota["emitente"]) or f"Compra · CNPJ {formatar_cnpj(nota['cnpj'])}"}


def nome_loja(razao):
    """'SUPERMERCADO BOM PRECO LTDA - EPP' -> 'Supermercado Bom Preco'."""
    if not razao:
        return None
    t = re.sub(r"\s*-\s*(ME|EPP|EIRELI)\s*$", "", razao.strip(), flags=re.I)
    t = re.sub(r"(?i)\s+(LTDA|EIRELI|S\.?/?A\.?|ME|EPP)\.?$", "", t)
    t = re.sub(r"\s+", " ", t).strip(" -.")
    pequenas = {"de", "da", "do", "das", "dos", "e"}
    return " ".join(p.lower() if p.lower() in pequenas and i else p.capitalize() for i, p in enumerate(t.split()))[:80]


# ------------------------------------------------------------------ categoria

COMBUSTIVEIS = ("GASOLINA", "ETANOL", "DIESEL", "ALCOOL", "GNV", "ARLA")


def sugerir_categoria(nota, regras_usuario, categorias_por_nome, sugerir_por_texto):
    """Primeiro o que o usuário já escolheu para esta loja; depois o nome da loja; depois os itens."""
    from .fatura import chave_estabelecimento, normalizar
    nome = nota.get("emitente") or ""
    cid, origem = (sugerir_por_texto({"tipo": "compra", "descricao": nome, "estabelecimento": chave_estabelecimento(nome)},
                                     regras_usuario, categorias_por_nome) if nome else (None, None))
    if origem == "aprendida":
        return cid, origem
    itens = " ".join(normalizar(i["descricao"]) for i in nota.get("itens") or [])
    if any(re.search(rf"\b{c}\b", itens) for c in COMBUSTIVEIS):
        return categorias_por_nome.get(("despesa", "Combustível")), "padrao"
    if cid:
        return cid, origem
    if len(nota.get("itens") or []) >= 4:  # vários itens sem pista no nome: compra de mercado
        return categorias_por_nome.get(("despesa", "Mercado")), "padrao"
    return None, None


def resumo_combustivel(nota):
    """'42,5 L de gasolina a R$ 6,19/L' quando a nota é de abastecimento."""
    from .fatura import normalizar
    for i in nota.get("itens") or []:
        d = normalizar(i["descricao"])
        if any(c in d for c in COMBUSTIVEIS) and i.get("qtd") and (i.get("un") or "").upper().startswith("L"):
            unit = i.get("unitario") or ((i.get("valor") or 0) / i["qtd"])
            return {"litros": i["qtd"], "preco_litro": round(unit, 3), "produto": i["descricao"]}
    return None


# ------------------------------------------------------------------ foto

def ler_qrcode_da_foto(conteudo):
    """Procura o QR Code numa foto (servidor). Tenta a foto inteira, reduzida e a metade de baixo ampliada."""
    try:
        import zxingcpp
        from PIL import Image, ImageOps
    except ImportError:
        raise ErroNota("A leitura da foto no servidor precisa do pacote zxing-cpp "
                       "(pip install -r requirements.txt). Cole o link do QR Code ou a chave da nota.") from None
    try:
        img = Image.open(io.BytesIO(conteudo))
        img = ImageOps.exif_transpose(img).convert("L")
    except Exception:
        raise ErroNota("Não foi possível abrir a imagem. Envie uma foto em JPG ou PNG.") from None
    tentativas = [img]
    lado = max(img.size)
    for alvo in (2000, 1200):
        if lado > alvo:
            f = alvo / lado
            tentativas.append(img.resize((int(img.width * f), int(img.height * f))))
    w, h = img.size
    tentativas.append(img.crop((0, h // 2, w, h)))
    tentativas.append(ImageOps.autocontrast(img))
    for t in tentativas:
        for r in zxingcpp.read_barcodes(t):
            if r.text and ("|" in r.text or "nfce" in r.text.lower() or re.search(r"\d{44}", r.text)):
                return r.text
    raise ErroNota("Não encontramos o QR Code nesta foto. Fotografe de perto, com o QR Code inteiro e sem reflexo.")
