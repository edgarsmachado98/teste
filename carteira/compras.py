"""Módulo Compras: histórico de preços das notas fiscais (NFC-e) e lista de compras pelo menor preço.

Cada nota lida (QR Code, foto ou link) vira uma compra numa loja, com os itens e o preço unitário.
Os itens são agrupados em produtos pelo nome normalizado ("LEITE INTEGRAL 1 LT" e "Leite integral 1L"
viram o mesmo produto); o usuário pode juntar produtos que o sistema não reconheceu como iguais.

Com o histórico, a lista de compras mostra, para cada item, o último preço em cada mercado e monta
a melhor combinação (cada item onde está mais barato) e o total se comprar tudo num mercado só.
"""
import datetime as dt
import json
import re
import unicodedata

from . import db

ESQUEMA = """
CREATE TABLE IF NOT EXISTS cmp_lojas (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    cnpj       TEXT NOT NULL UNIQUE,
    razao      TEXT,
    nome       TEXT NOT NULL,           -- nome curto mostrado (o usuário pode trocar)
    endereco   TEXT
);

CREATE TABLE IF NOT EXISTS cmp_produtos (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    nome       TEXT NOT NULL,
    unidade    TEXT,                    -- UN, KG, L...
    criado_em  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- Nome do item como vem na nota (normalizado) -> produto. Juntar produtos = apontar apelidos para outro.
CREATE TABLE IF NOT EXISTS cmp_apelidos (
    chave      TEXT PRIMARY KEY,
    produto_id INTEGER NOT NULL REFERENCES cmp_produtos(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS cmp_compras (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    carteira_id INTEGER NOT NULL REFERENCES carteiras(id) ON DELETE CASCADE,
    chave       TEXT NOT NULL UNIQUE,    -- chave de acesso da NFC-e
    loja_id     INTEGER NOT NULL REFERENCES cmp_lojas(id),
    data        TEXT NOT NULL,           -- AAAA-MM-DD
    hora        TEXT,
    total       REAL,
    desconto    REAL NOT NULL DEFAULT 0,
    url         TEXT,
    criado_em   TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS cmp_compras_data ON cmp_compras (data);

CREATE TABLE IF NOT EXISTS cmp_itens (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    compra_id   INTEGER NOT NULL REFERENCES cmp_compras(id) ON DELETE CASCADE,
    produto_id  INTEGER NOT NULL REFERENCES cmp_produtos(id),
    descricao   TEXT NOT NULL,           -- como veio na nota
    qtd         REAL,
    un          TEXT,
    unitario    REAL,
    valor       REAL
);
CREATE INDEX IF NOT EXISTS cmp_itens_produto ON cmp_itens (produto_id);

CREATE TABLE IF NOT EXISTS cmp_lista (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    carteira_id INTEGER NOT NULL REFERENCES carteiras(id) ON DELETE CASCADE,
    produto_id  INTEGER REFERENCES cmp_produtos(id) ON DELETE SET NULL,
    texto       TEXT,                    -- item sem histórico de preço ("papel toalha")
    qtd         REAL NOT NULL DEFAULT 1,
    comprado    INTEGER NOT NULL DEFAULT 0,
    criado_em   TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
"""


def preparar(conn):
    conn.executescript(ESQUEMA)
    conn.commit()


# ------------------------------------------------------------------ nomes

def _sem_acento(t):
    return unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode()


UNIDADES = [  # tamanho da embalagem escrito de vários jeitos -> forma única
    (r"(\d+(?:[.,]\d+)?)\s*(?:LITROS?|LTS?|L)\b", "L"),
    (r"(\d+(?:[.,]\d+)?)\s*(?:ML)\b", "ML"),
    (r"(\d+(?:[.,]\d+)?)\s*(?:KGS?|KILOS?|QUILOS?)\b", "KG"),
    (r"(\d+(?:[.,]\d+)?)\s*(?:GRS?|GRAMAS?|G)\b", "G"),
    (r"(\d+)\s*(?:UNID(?:ADES)?|UNDS?|UN)\b", "UN"),
]


def _numero_curto(n):
    n = n.replace(",", ".")
    return n.rstrip("0").rstrip(".") if "." in n else n


def chave_produto(descricao):
    """Nome normalizado que identifica o produto entre notas e mercados.

    'Leite Integral ITALAC 1 LT' e 'LEITE INTEGRAL ITALAC 1L' -> 'LEITE INTEGRAL ITALAC 1L'.
    """
    t = _sem_acento(descricao).upper()
    t = re.sub(r"\(.*?\)", " ", t)                    # códigos entre parênteses
    t = re.sub(r"[^A-Z0-9.,/ ]", " ", t)
    for padrao, un in UNIDADES:
        t = re.sub(padrao, lambda m, un=un: _numero_curto(m.group(1)) + un, t)
    t = re.sub(r"(?<=\d)[.,](?=\d)", ".", t)
    t = re.sub(r"[.,/]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def nome_bonito(descricao):
    """'LEITE INTEGRAL ITALAC 1L' -> 'Leite Integral Italac 1L' (siglas e tamanhos ficam em maiúsculas)."""
    pequenas = {"DE", "DA", "DO", "DAS", "DOS", "E", "C", "COM", "SEM", "P", "PARA"}
    out = []
    for i, p in enumerate(re.sub(r"\s+", " ", str(descricao or "")).strip().split(" ")):
        up = p.upper()
        if re.search(r"\d", p) or (len(p) <= 3 and up not in pequenas and not re.search(r"[AEIOU]", up)):
            out.append(up)
        elif up in pequenas and i:
            out.append(p.lower())
        else:
            out.append(p[:1].upper() + p[1:].lower())
    return " ".join(out)[:80]


def nome_loja(razao):
    """'SUPERMERCADO BOM PRECO LTDA - EPP' -> 'Supermercado Bom Preco'."""
    t = re.sub(r"(?i)\s*-?\s*\b(LTDA|EIRELI|S\.?/?A\.?|ME|EPP|MEI)\b\.?", "", str(razao or "")).strip(" -.")
    return nome_bonito(t) or "Loja"


# ------------------------------------------------------------------ gravação

def produto_de(conn, descricao, un=None):
    """Produto do item (cria na primeira vez)."""
    chave = chave_produto(descricao)
    if not chave:
        chave = "SEM NOME"
    row = conn.execute("SELECT produto_id FROM cmp_apelidos WHERE chave = ?", (chave,)).fetchone()
    if row:
        return row["produto_id"]
    cur = conn.execute("INSERT INTO cmp_produtos (nome, unidade) VALUES (?, ?)",
                       (nome_bonito(descricao), (un or "").upper()[:6] or None))
    conn.execute("INSERT INTO cmp_apelidos (chave, produto_id) VALUES (?, ?)", (chave, cur.lastrowid))
    return cur.lastrowid


def registrar_compra(conn, carteira_id, nota):
    """Grava a nota (dict do leitor de NFC-e). Devolve (compra_id, nova?). Não duplica a mesma chave."""
    chave = str(nota.get("chave") or "").strip()
    if not chave:
        raise ValueError("Nota sem chave de acesso.")
    existe = conn.execute("SELECT id FROM cmp_compras WHERE chave = ?", (chave,)).fetchone()
    if existe:
        return existe["id"], False
    cnpj = re.sub(r"[^0-9A-Z]", "", str(nota.get("cnpj") or "")) or "00000000000000"
    loja = conn.execute("SELECT id FROM cmp_lojas WHERE cnpj = ?", (cnpj,)).fetchone()
    if loja:
        loja_id = loja["id"]
        if nota.get("emitente"):
            conn.execute("UPDATE cmp_lojas SET razao = COALESCE(razao, ?), endereco = COALESCE(endereco, ?) WHERE id = ?",
                         (nota.get("emitente"), nota.get("endereco"), loja_id))
    else:
        loja_id = conn.execute("INSERT INTO cmp_lojas (cnpj, razao, nome, endereco) VALUES (?, ?, ?, ?)",
                               (cnpj, nota.get("emitente"), nome_loja(nota.get("emitente") or f"CNPJ {cnpj}"),
                                nota.get("endereco"))).lastrowid
    data_hora = str(nota.get("data") or nota.get("emissao") or "")
    data = data_hora[:10] if re.match(r"\d{4}-\d{2}-\d{2}", data_hora) else dt.date.today().isoformat()
    hora = data_hora[11:16] if len(data_hora) >= 16 else None
    compra_id = conn.execute(
        """INSERT INTO cmp_compras (carteira_id, chave, loja_id, data, hora, total, desconto, url)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (carteira_id, chave, loja_id, data, hora, nota.get("total"), nota.get("desconto") or 0, nota.get("url"))).lastrowid
    for it in nota.get("itens") or []:
        desc = str(it.get("descricao") or "").strip()
        if not desc:
            continue
        qtd, valor, unit = it.get("qtd"), it.get("valor"), it.get("unitario")
        if unit is None and valor is not None and qtd:
            unit = round(valor / qtd, 4)
        conn.execute("""INSERT INTO cmp_itens (compra_id, produto_id, descricao, qtd, un, unitario, valor)
                        VALUES (?, ?, ?, ?, ?, ?, ?)""",
                     (compra_id, produto_de(conn, desc, it.get("un")), desc[:120], qtd, (it.get("un") or "")[:6] or None,
                      unit, valor))
    return compra_id, True


def importar_notas_do_planejamento(conn):
    """Traz para o histórico as notas já lançadas no Planejamento (uma vez por nota)."""
    try:
        notas = db.rows(conn.execute("SELECT * FROM fin_notas"))
    except Exception:
        return 0
    novas = 0
    for n in notas:
        if conn.execute("SELECT 1 FROM cmp_compras WHERE chave = ?", (n["chave"],)).fetchone():
            continue
        itens = json.loads(n.get("itens") or "[]")
        if not itens:
            continue
        registrar_compra(conn, n["carteira_id"], {**n, "itens": itens, "data": n.get("emissao") or n.get("criado_em")})
        novas += 1
    if novas:
        conn.commit()
    return novas


def juntar_produtos(conn, destino, origem):
    """O produto `origem` passa a ser o mesmo que `destino` (itens, apelidos e lista)."""
    if destino == origem:
        return
    for tabela in ("cmp_itens", "cmp_lista"):
        conn.execute(f"UPDATE {tabela} SET produto_id = ? WHERE produto_id = ?", (destino, origem))
    conn.execute("UPDATE cmp_apelidos SET produto_id = ? WHERE produto_id = ?", (destino, origem))
    conn.execute("DELETE FROM cmp_produtos WHERE id = ?", (origem,))


# ------------------------------------------------------------------ consultas

def precos_por_loja(conn, cids, produto_ids=None, desde=None):
    """{produto_id: {loja_id: {unitario, data, loja}}} com o preço mais recente de cada produto em cada loja."""
    marcas = ",".join("?" * len(cids))
    filtro, args = "", list(cids)
    if produto_ids is not None:
        if not produto_ids:
            return {}
        filtro += f" AND i.produto_id IN ({','.join('?' * len(produto_ids))})"
        args += list(produto_ids)
    if desde:
        filtro += " AND c.data >= ?"
        args.append(desde)
    rows = conn.execute(
        f"""SELECT i.produto_id, c.loja_id, l.nome AS loja, c.data, i.unitario FROM cmp_itens i
            JOIN cmp_compras c ON c.id = i.compra_id JOIN cmp_lojas l ON l.id = c.loja_id
            WHERE c.carteira_id IN ({marcas}) AND i.unitario IS NOT NULL AND i.unitario > 0 {filtro}
            ORDER BY c.data, c.id""", args).fetchall()
    out = {}
    for r in rows:  # em ordem de data: o último que entra é o mais recente
        out.setdefault(r["produto_id"], {})[r["loja_id"]] = {"unitario": round(r["unitario"], 2), "data": r["data"],
                                                              "loja": r["loja"], "loja_id": r["loja_id"]}
    return out


def montar_lista(itens, precos, lojas, hoje, dias_velho=60):
    """Melhor combinação (cada item no mercado mais barato) e o total de comprar tudo num mercado só.

    itens: [{id, produto_id, nome, qtd, comprado}]; precos: saída de precos_por_loja; lojas: {id: nome}.
    """
    limite = (dt.date.fromisoformat(hoje) - dt.timedelta(days=dias_velho)).isoformat()
    por_loja = {lid: {"loja_id": lid, "loja": nome, "total": 0.0, "itens": 0, "faltam": []} for lid, nome in lojas.items()}
    combinacao, total_melhor, com_preco = {}, 0.0, 0
    saida = []
    pendentes = [i for i in itens if not i.get("comprado")]
    for it in itens:
        ps = sorted((precos.get(it.get("produto_id")) or {}).values(), key=lambda p: p["unitario"])
        melhor = ps[0] if ps else None
        linha = {**it, "precos": [{**p, "antigo": p["data"] < limite} for p in ps], "melhor": melhor}
        if melhor and len(ps) > 1:
            linha["economia"] = round((ps[-1]["unitario"] - melhor["unitario"]) * (it.get("qtd") or 1), 2)
        saida.append(linha)
        if it.get("comprado"):
            continue
        if melhor:
            com_preco += 1
            valor = melhor["unitario"] * (it.get("qtd") or 1)
            total_melhor += valor
            g = combinacao.setdefault(melhor["loja_id"], {"loja_id": melhor["loja_id"], "loja": melhor["loja"], "total": 0.0, "itens": []})
            g["total"] += valor
            g["itens"].append(it.get("nome"))
        for lid, info in por_loja.items():
            p = next((x for x in ps if x["loja_id"] == lid), None)
            if p:
                info["total"] += p["unitario"] * (it.get("qtd") or 1)
                info["itens"] += 1
            elif melhor:
                info["faltam"].append(it.get("nome"))
    lojas_ord = sorted((x for x in por_loja.values() if x["itens"]), key=lambda x: (-x["itens"], x["total"]))
    for x in lojas_ord:
        x["total"] = round(x["total"], 2)
    for g in combinacao.values():
        g["total"] = round(g["total"], 2)
    # "um mercado só": o que tem mais itens da lista (no empate, o mais barato)
    unico = lojas_ord[0] if lojas_ord else None
    economia = None
    if unico and unico["itens"] == com_preco and com_preco:
        economia = round(unico["total"] - total_melhor, 2)
    return {"itens": saida, "pendentes": len(pendentes), "com_preco": com_preco,
            "melhor": {"total": round(total_melhor, 2), "lojas": sorted(combinacao.values(), key=lambda g: -g["total"])},
            "um_mercado": unico, "por_loja": lojas_ord, "economia": economia}


def variacao(precos_datados):
    """% entre o primeiro e o último preço [(data, preço)] (ordenados por data)."""
    if len(precos_datados) < 2 or not precos_datados[0][1]:
        return None
    return round((precos_datados[-1][1] / precos_datados[0][1] - 1) * 100, 1)
