"""Sistema de orçamentos — aplicação local (Flask + SQLite)."""
import datetime
import os
import sqlite3

from flask import (Flask, abort, g, redirect, render_template, request,
                   send_file, url_for)

import seed

BASE = os.path.dirname(os.path.abspath(__file__))

SCHEMA = """
CREATE TABLE IF NOT EXISTS empresa (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    nome TEXT, documento TEXT, telefone TEXT, email TEXT, endereco TEXT,
    apresentacao TEXT, pagamento TEXT, prazo TEXT, garantia TEXT
);
CREATE TABLE IF NOT EXISTS clientes (
    id INTEGER PRIMARY KEY, nome TEXT NOT NULL, documento TEXT, contato TEXT,
    telefone TEXT, email TEXT, endereco TEXT
);
CREATE TABLE IF NOT EXISTS produtos (
    id INTEGER PRIMARY KEY, descricao TEXT NOT NULL, categoria TEXT, marca TEXT,
    unidade TEXT DEFAULT 'un', custo REAL DEFAULT 0, margem REAL DEFAULT 30,
    tipo TEXT DEFAULT 'produto'
);
CREATE TABLE IF NOT EXISTS tipos (
    id INTEGER PRIMARY KEY, nome TEXT NOT NULL, escopo TEXT, nao_incluso TEXT
);
CREATE TABLE IF NOT EXISTS tipo_secoes (
    id INTEGER PRIMARY KEY, tipo_id INTEGER NOT NULL REFERENCES tipos(id) ON DELETE CASCADE,
    nome TEXT NOT NULL, ordem INTEGER
);
CREATE TABLE IF NOT EXISTS tipo_sugestoes (
    secao_id INTEGER NOT NULL REFERENCES tipo_secoes(id) ON DELETE CASCADE,
    produto_id INTEGER NOT NULL REFERENCES produtos(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS orcamentos (
    id INTEGER PRIMARY KEY, numero TEXT, cliente_id INTEGER REFERENCES clientes(id),
    titulo TEXT, tipos TEXT, status TEXT DEFAULT 'Rascunho', data TEXT,
    validade_dias INTEGER DEFAULT 15, desconto REAL DEFAULT 0, escopo TEXT,
    pagamento TEXT, prazo TEXT, garantia TEXT, nao_incluso TEXT,
    exibicao TEXT DEFAULT 'itens'
);
CREATE TABLE IF NOT EXISTS secoes (
    id INTEGER PRIMARY KEY, orcamento_id INTEGER NOT NULL REFERENCES orcamentos(id) ON DELETE CASCADE,
    grupo TEXT, nome TEXT NOT NULL, ordem INTEGER
);
CREATE TABLE IF NOT EXISTS itens (
    id INTEGER PRIMARY KEY, orcamento_id INTEGER NOT NULL REFERENCES orcamentos(id) ON DELETE CASCADE,
    secao_id INTEGER NOT NULL REFERENCES secoes(id) ON DELETE CASCADE,
    produto_id INTEGER REFERENCES produtos(id) ON DELETE SET NULL,
    descricao TEXT NOT NULL, marca TEXT, categoria TEXT, unidade TEXT, tipo TEXT DEFAULT 'produto',
    quantidade REAL DEFAULT 0, custo REAL DEFAULT 0, preco REAL DEFAULT 0,
    opcional INTEGER DEFAULT 0
);
"""

# Colunas acrescentadas depois da primeira versão (bancos já criados são atualizados).
NOVAS_COLUNAS = [("empresa", "slogan"), ("empresa", "razao_social"), ("empresa", "responsavel"),
                 ("empresa", "cidade"), ("orcamentos", "obra"), ("orcamentos", "objeto")]
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
         "setembro", "outubro", "novembro", "dezembro"]

STATUS = ["Rascunho", "Enviado", "Aprovado", "Recusado"]
EXIBICOES = [("itens", "Preços item a item"), ("secoes", "Só subtotais por seção"),
             ("total", "Só o total")]


def num(texto, padrao=0.0):
    """Converte '1.234,56' ou '12.5' em número."""
    t = (texto or "").strip().replace("R$", "").replace(" ", "")
    if not t:
        return padrao
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return padrao


def brl(valor):
    s = f"{(valor or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


def qtd(valor):
    v = valor or 0
    if float(v).is_integer():
        return str(int(v))
    return f"{v:.2f}".replace(".", ",")


def create_app(data_dir=None):
    app = Flask(__name__)
    data_dir = data_dir or os.environ.get("ORCAMENTOS_DATA") or os.path.join(BASE, "data")
    os.makedirs(data_dir, exist_ok=True)
    db_path = os.path.join(data_dir, "orcamentos.db")
    logo_path = os.path.join(data_dir, "logo")
    app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024
    app.jinja_env.filters.update(brl=brl, qtd=qtd)

    def db():
        if "db" not in g:
            g.db = sqlite3.connect(db_path)
            g.db.row_factory = sqlite3.Row
            g.db.execute("PRAGMA foreign_keys = ON")
        return g.db

    @app.teardown_appcontext
    def fechar(_exc):
        con = g.pop("db", None)
        if con is not None:
            con.close()

    def iniciar_banco():
        con = sqlite3.connect(db_path)
        con.executescript(SCHEMA)
        for tabela, coluna in NOVAS_COLUNAS:
            existentes = [r[1] for r in con.execute(f"PRAGMA table_info({tabela})")]
            if coluna not in existentes:
                con.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} TEXT")
        if con.execute("SELECT COUNT(*) FROM empresa").fetchone()[0] == 0:
            e = seed.EMPRESA
            con.execute(
                "INSERT INTO empresa (id, nome, apresentacao, pagamento, prazo, garantia)"
                " VALUES (1, ?, ?, ?, ?, ?)",
                (e["nome"], e["apresentacao"], e["pagamento"], e["prazo"], e["garantia"]))
        if con.execute("SELECT COUNT(*) FROM tipos").fetchone()[0] == 0:
            produtos = {}
            for t in seed.TIPOS:
                tid = con.execute(
                    "INSERT INTO tipos (nome, escopo, nao_incluso) VALUES (?, ?, ?)",
                    (t["nome"], t["escopo"], t["nao_incluso"])).lastrowid
                for ordem, (secao, itens) in enumerate(t["secoes"]):
                    sid = con.execute(
                        "INSERT INTO tipo_secoes (tipo_id, nome, ordem) VALUES (?, ?, ?)",
                        (tid, secao, ordem)).lastrowid
                    for desc, un, cat, tipo in itens:
                        if desc not in produtos:
                            produtos[desc] = con.execute(
                                "INSERT INTO produtos (descricao, unidade, categoria, tipo)"
                                " VALUES (?, ?, ?, ?)", (desc, un, cat, tipo)).lastrowid
                        con.execute("INSERT INTO tipo_sugestoes VALUES (?, ?)",
                                    (sid, produtos[desc]))
        con.commit()
        con.close()

    iniciar_banco()

    def empresa():
        return db().execute("SELECT * FROM empresa WHERE id = 1").fetchone()

    @app.context_processor
    def contexto():
        return {"tem_logo": os.path.exists(logo_path), "STATUS": STATUS,
                "EXIBICOES": EXIBICOES}

    def carregar(oid):
        """Orçamento com seções, itens e totais."""
        o = db().execute(
            "SELECT o.*, c.nome AS cliente_nome, c.documento AS cliente_documento,"
            " c.contato AS cliente_contato, c.endereco AS cliente_endereco"
            " FROM orcamentos o LEFT JOIN clientes c ON c.id = o.cliente_id"
            " WHERE o.id = ?", (oid,)).fetchone()
        if o is None:
            abort(404)
        secoes = []
        subtotal = custo = opcionais = 0.0
        grupos = set()
        for s in db().execute(
                "SELECT * FROM secoes WHERE orcamento_id = ? ORDER BY ordem, id", (oid,)):
            itens = db().execute(
                "SELECT * FROM itens WHERE secao_id = ? ORDER BY id", (s["id"],)).fetchall()
            sub = sum(i["quantidade"] * i["preco"] for i in itens if not i["opcional"])
            custo += sum(i["quantidade"] * i["custo"] for i in itens if not i["opcional"])
            opcionais += sum(i["quantidade"] * i["preco"] for i in itens if i["opcional"])
            subtotal += sub
            grupos.add(s["grupo"])
            secoes.append({"secao": s, "itens": itens, "subtotal": sub})
        total = max(subtotal - (o["desconto"] or 0), 0)
        tot = {"subtotal": subtotal, "total": total, "custo": custo, "opcionais": opcionais,
               "margem": ((total - custo) / total * 100) if total else 0}
        return o, secoes, tot, len(grupos) > 1

    # ---------- Orçamentos ----------
    @app.route("/")
    def inicio():
        return redirect(url_for("orcamentos"))

    @app.route("/orcamentos")
    def orcamentos():
        status = request.args.get("status", "")
        sql = ("SELECT o.*, c.nome AS cliente_nome,"
               " (SELECT COALESCE(SUM(quantidade * preco), 0) FROM itens i"
               "   WHERE i.orcamento_id = o.id AND i.opcional = 0) - o.desconto AS total"
               " FROM orcamentos o LEFT JOIN clientes c ON c.id = o.cliente_id")
        args = ()
        if status in STATUS:
            sql += " WHERE o.status = ?"
            args = (status,)
        lista = db().execute(sql + " ORDER BY o.id DESC", args).fetchall()
        return render_template("orcamentos.html", lista=lista, status=status)

    @app.route("/orcamentos/novo", methods=["GET", "POST"])
    def novo():
        con = db()
        erro = None
        if request.method == "POST":
            tipo_ids = request.form.getlist("tipos")
            cliente_id = request.form.get("cliente_id") or None
            novo_cliente = request.form.get("novo_cliente", "").strip()
            if not tipo_ids:
                erro = "Escolha pelo menos um tipo de orçamento."
            elif not cliente_id and not novo_cliente:
                erro = "Escolha um cliente ou informe o nome de um novo."
            else:
                if novo_cliente:
                    cliente_id = con.execute(
                        "INSERT INTO clientes (nome) VALUES (?)", (novo_cliente,)).lastrowid
                marca = ",".join("?" * len(tipo_ids))
                tipos = con.execute(
                    f"SELECT * FROM tipos WHERE id IN ({marca}) ORDER BY id", tipo_ids).fetchall()
                emp = empresa()
                hoje = datetime.date.today()
                seq = con.execute(
                    "SELECT COUNT(*) FROM orcamentos WHERE numero LIKE ?",
                    (f"{hoje.year}-%",)).fetchone()[0] + 1
                nomes = " + ".join(t["nome"] for t in tipos)
                oid = con.execute(
                    "INSERT INTO orcamentos (numero, cliente_id, titulo, tipos, data, escopo,"
                    " pagamento, prazo, garantia, nao_incluso, exibicao)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,'secoes')",
                    (f"{hoje.year}-{seq:04d}", cliente_id,
                     request.form.get("titulo", "").strip() or nomes, nomes, hoje.isoformat(),
                     "\n".join(t["escopo"] or "" for t in tipos),
                     emp["pagamento"], emp["prazo"], emp["garantia"],
                     "\n".join(t["nao_incluso"] or "" for t in tipos))).lastrowid
                ordem = 0
                for t in tipos:
                    for s in con.execute(
                            "SELECT * FROM tipo_secoes WHERE tipo_id = ? ORDER BY ordem",
                            (t["id"],)).fetchall():
                        sid = con.execute(
                            "INSERT INTO secoes (orcamento_id, grupo, nome, ordem)"
                            " VALUES (?,?,?,?)", (oid, t["nome"], s["nome"], ordem)).lastrowid
                        ordem += 1
                        for p in con.execute(
                                "SELECT p.* FROM tipo_sugestoes ts JOIN produtos p"
                                " ON p.id = ts.produto_id WHERE ts.secao_id = ? ORDER BY p.id",
                                (s["id"],)).fetchall():
                            inserir_item(con, oid, sid, p, 0)
                con.commit()
                return redirect(url_for("editar", oid=oid))
        return render_template(
            "novo.html", erro=erro,
            tipos=con.execute("SELECT * FROM tipos ORDER BY id").fetchall(),
            clientes=con.execute("SELECT * FROM clientes ORDER BY nome").fetchall())

    def inserir_item(con, oid, sid, p, quantidade):
        preco = round((p["custo"] or 0) * (1 + (p["margem"] or 0) / 100), 2)
        con.execute(
            "INSERT INTO itens (orcamento_id, secao_id, produto_id, descricao, marca, categoria,"
            " unidade, tipo, quantidade, custo, preco) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (oid, sid, p["id"], p["descricao"], p["marca"], p["categoria"], p["unidade"],
             p["tipo"], quantidade, p["custo"] or 0, preco))

    @app.route("/orcamentos/<int:oid>", methods=["GET", "POST"])
    def editar(oid):
        con = db()
        if request.method == "POST":
            f = request.form
            status = f.get("status") if f.get("status") in STATUS else "Rascunho"
            exib = f.get("exibicao") if f.get("exibicao") in dict(EXIBICOES) else "itens"
            con.execute(
                "UPDATE orcamentos SET titulo=?, cliente_id=?, status=?, validade_dias=?,"
                " desconto=?, escopo=?, pagamento=?, prazo=?, garantia=?, nao_incluso=?,"
                " exibicao=?, obra=?, objeto=? WHERE id=?",
                (f.get("titulo", "").strip(), f.get("cliente_id") or None, status,
                 int(num(f.get("validade_dias"), 15)), num(f.get("desconto")),
                 f.get("escopo", ""), f.get("pagamento", ""), f.get("prazo", ""),
                 f.get("garantia", ""), f.get("nao_incluso", ""), exib,
                 f.get("obra", "").strip(), f.get("objeto", ""), oid))
            for i in con.execute("SELECT id FROM itens WHERE orcamento_id = ?", (oid,)).fetchall():
                k = f"i{i['id']}_"
                if k + "qtd" in f:
                    con.execute(
                        "UPDATE itens SET descricao=?, quantidade=?, custo=?, preco=?, opcional=?"
                        " WHERE id=?",
                        (f.get(k + "desc", "").strip() or "Item", num(f.get(k + "qtd")),
                         num(f.get(k + "custo")), num(f.get(k + "preco")),
                         1 if f.get(k + "opc") else 0, i["id"]))
            con.commit()
            return redirect(url_for("editar", oid=oid))
        o, secoes, tot, varios = carregar(oid)
        return render_template(
            "editar.html", o=o, secoes=secoes, tot=tot, varios=varios,
            clientes=con.execute("SELECT * FROM clientes ORDER BY nome").fetchall(),
            produtos=con.execute(
                "SELECT * FROM produtos ORDER BY categoria, descricao").fetchall())

    @app.route("/orcamentos/<int:oid>/itens", methods=["POST"])
    def adicionar_item(oid):
        con = db()
        f = request.form
        s = con.execute("SELECT id FROM secoes WHERE id = ? AND orcamento_id = ?",
                        (f.get("secao_id"), oid)).fetchone()
        if s is None:
            abort(404)
        quantidade = num(f.get("quantidade"), 1)
        p = con.execute("SELECT * FROM produtos WHERE id = ?",
                        (f.get("produto_id") or 0,)).fetchone()
        if p is not None:
            inserir_item(con, oid, s["id"], p, quantidade)
        elif f.get("descricao", "").strip():
            con.execute(
                "INSERT INTO itens (orcamento_id, secao_id, descricao, unidade, tipo, quantidade,"
                " custo, preco) VALUES (?,?,?,?,?,?,?,?)",
                (oid, s["id"], f["descricao"].strip(), f.get("unidade", "un").strip() or "un",
                 "servico" if f.get("tipo") == "servico" else "produto", quantidade,
                 num(f.get("custo")), num(f.get("preco"))))
        con.commit()
        return redirect(url_for("editar", oid=oid) + f"#s{s['id']}")

    @app.route("/orcamentos/<int:oid>/itens/<int:iid>/excluir", methods=["POST"])
    def excluir_item(oid, iid):
        db().execute("DELETE FROM itens WHERE id = ? AND orcamento_id = ?", (iid, oid))
        db().commit()
        return redirect(url_for("editar", oid=oid))

    @app.route("/orcamentos/<int:oid>/excluir", methods=["POST"])
    def excluir_orcamento(oid):
        db().execute("DELETE FROM orcamentos WHERE id = ?", (oid,))
        db().commit()
        return redirect(url_for("orcamentos"))

    @app.route("/orcamentos/<int:oid>/proposta")
    def proposta(oid):
        o, secoes, tot, varios = carregar(oid)
        # Blocos numerados: um por tipo (com subgrupos por seção) quando há vários tipos;
        # senão, um por seção.
        blocos, opcionais = [], []
        for s in secoes:
            itens = [i for i in s["itens"] if i["quantidade"] > 0 and not i["opcional"]]
            opcionais += [i for i in s["itens"] if i["quantidade"] > 0 and i["opcional"]]
            if not itens:
                continue
            if varios:
                grupo = s["secao"]["grupo"]
                if not blocos or blocos[-1]["titulo"] != grupo:
                    blocos.append({"titulo": grupo, "subs": [], "total": 0})
                blocos[-1]["subs"].append({"nome": s["secao"]["nome"], "itens": itens})
                blocos[-1]["total"] += s["subtotal"]
            else:
                blocos.append({"titulo": s["secao"]["nome"], "total": s["subtotal"],
                               "subs": [{"nome": None, "itens": itens}]})
        data = datetime.date.fromisoformat(o["data"])
        return render_template(
            "proposta.html", o=o, blocos=blocos, opcionais=opcionais, tot=tot, emp=empresa(),
            total_opcionais=tot["opcionais"], data=data.strftime("%d/%m/%Y"),
            data_extenso=f"{data.day} de {MESES[data.month - 1]} de {data.year}",
            linhas=lambda txt: [l.strip() for l in (txt or "").splitlines() if l.strip()])

    @app.route("/orcamentos/<int:oid>/cotacao")
    def cotacao(oid):
        o, secoes, _tot, _varios = carregar(oid)
        grupos = {}
        for s in secoes:
            for i in s["itens"]:
                if i["quantidade"] <= 0 or i["tipo"] == "servico":
                    continue
                cat = i["categoria"] or s["secao"]["nome"]
                chave = (i["descricao"], i["unidade"])
                linha = grupos.setdefault(cat, {}).setdefault(
                    chave, {"descricao": i["descricao"], "marca": i["marca"] or "",
                            "unidade": i["unidade"], "quantidade": 0})
                linha["quantidade"] += i["quantidade"]
        categorias = [(c, list(v.values())) for c, v in sorted(grupos.items())]
        return render_template("cotacao.html", o=o, categorias=categorias, emp=empresa(),
                               hoje=datetime.date.today().strftime("%d/%m/%Y"))

    # ---------- Catálogo ----------
    def dados_produto(f):
        return (f.get("descricao", "").strip(), f.get("categoria", "").strip(),
                f.get("marca", "").strip(), f.get("unidade", "").strip() or "un",
                num(f.get("custo")), num(f.get("margem"), 30),
                "servico" if f.get("tipo") == "servico" else "produto")

    @app.route("/catalogo", methods=["GET", "POST"])
    def catalogo():
        con = db()
        if request.method == "POST":
            d = dados_produto(request.form)
            if d[0]:
                con.execute("INSERT INTO produtos (descricao, categoria, marca, unidade, custo,"
                            " margem, tipo) VALUES (?,?,?,?,?,?,?)", d)
                con.commit()
            return redirect(url_for("catalogo"))
        return render_template("catalogo.html", produtos=con.execute(
            "SELECT * FROM produtos ORDER BY categoria, descricao").fetchall())

    @app.route("/catalogo/<int:pid>", methods=["POST"])
    def salvar_produto(pid):
        if request.form.get("acao") == "excluir":
            db().execute("DELETE FROM produtos WHERE id = ?", (pid,))
        else:
            d = dados_produto(request.form)
            if d[0]:
                db().execute("UPDATE produtos SET descricao=?, categoria=?, marca=?, unidade=?,"
                             " custo=?, margem=?, tipo=? WHERE id=?", d + (pid,))
        db().commit()
        return redirect(url_for("catalogo"))

    # ---------- Clientes ----------
    CAMPOS_CLIENTE = ["nome", "documento", "contato", "telefone", "email", "endereco"]

    @app.route("/clientes", methods=["GET", "POST"])
    def clientes():
        con = db()
        if request.method == "POST":
            d = [request.form.get(c, "").strip() for c in CAMPOS_CLIENTE]
            if d[0]:
                con.execute("INSERT INTO clientes (nome, documento, contato, telefone, email,"
                            " endereco) VALUES (?,?,?,?,?,?)", d)
                con.commit()
            return redirect(url_for("clientes"))
        return render_template("clientes.html", clientes=con.execute(
            "SELECT * FROM clientes ORDER BY nome").fetchall())

    @app.route("/clientes/<int:cid>", methods=["POST"])
    def salvar_cliente(cid):
        con = db()
        if request.form.get("acao") == "excluir":
            con.execute("UPDATE orcamentos SET cliente_id = NULL WHERE cliente_id = ?", (cid,))
            con.execute("DELETE FROM clientes WHERE id = ?", (cid,))
        else:
            d = [request.form.get(c, "").strip() for c in CAMPOS_CLIENTE]
            if d[0]:
                con.execute("UPDATE clientes SET nome=?, documento=?, contato=?, telefone=?,"
                            " email=?, endereco=? WHERE id=?", d + [cid])
        con.commit()
        return redirect(url_for("clientes"))

    # ---------- Empresa ----------
    CAMPOS_EMPRESA = ["nome", "slogan", "razao_social", "responsavel", "cidade",
                      "documento", "telefone", "email", "endereco", "apresentacao",
                      "pagamento", "prazo", "garantia"]

    @app.route("/empresa", methods=["GET", "POST"])
    def pagina_empresa():
        if request.method == "POST":
            d = [request.form.get(c, "").strip() for c in CAMPOS_EMPRESA]
            db().execute("UPDATE empresa SET " + ", ".join(f"{c}=?" for c in CAMPOS_EMPRESA)
                         + " WHERE id = 1", d)
            db().commit()
            arq = request.files.get("logo")
            if arq and arq.filename and arq.mimetype in ("image/png", "image/jpeg", "image/gif", "image/webp"):
                arq.save(logo_path)
            if request.form.get("remover_logo") and os.path.exists(logo_path):
                os.remove(logo_path)
            return redirect(url_for("pagina_empresa"))
        return render_template("empresa.html", emp=empresa())

    @app.route("/logo")
    def logo():
        if not os.path.exists(logo_path):
            abort(404)
        return send_file(logo_path, max_age=0)

    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=5000, debug=False)
