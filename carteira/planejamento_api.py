"""Rotas da API do módulo adicional Planejamento financeiro (/api/plan/...).

Registradas pelo app base com `registrar(app, ctx)`. Todas respondem 403 quando o módulo não
está ativo na licença (ver carteira/licenca.py).
"""
import datetime as dt
import json
import re

from flask import jsonify, request

from . import db, licenca
from . import fatura as fat
from . import nfce
from . import planejamento as plan
from .importacao import ErroImportacao

MODULO = "planejamento"


def registrar(app, ctx):
    """ctx: conn, erro, carteira_atual, carteiras_leitura, listar_aportes, listar_proventos, hoje."""
    conn, erro = ctx.conn, ctx.erro
    preparado = {"ok": False}

    @app.before_request
    def _modulo_planejamento():
        if not request.path.startswith("/api/plan/"):
            return None
        if not licenca.modulo_ativo(MODULO):
            return jsonify({"erro": "O módulo Planejamento financeiro não está incluído na licença desta instalação.",
                            "modulo": MODULO}), 403
        if not preparado["ok"]:
            plan.preparar(conn)
            preparado["ok"] = True
        return None

    def mes_atual():
        return ctx.hoje()[:7]

    def mes_param():
        m = (request.args.get("mes") or mes_atual())[:7]
        try:
            dt.date.fromisoformat(m + "-01")
        except ValueError:
            m = mes_atual()
        return m

    def categorias():
        return {c["id"]: c for c in db.rows(conn.execute("SELECT * FROM fin_categorias"))}

    def lancamentos_do_mes(cids, mes):
        marcas = ",".join("?" * len(cids))
        reais = db.rows(conn.execute(
            f"""SELECT * FROM fin_lancamentos WHERE carteira_id IN ({marcas}) AND substr(data, 1, 7) = ?
                ORDER BY data, id""", [*cids, mes]))
        if mes > mes_atual():
            reais += plan.projetar_recorrencias(conn, cids, mes)
        return reais

    # ---------- titular / permissões ----------
    # No planejamento, cada lançamento pertence a uma pessoa (a carteira dela). Quem pode editar
    # várias carteiras (ex.: o administrador da família) lança para qualquer uma delas, inclusive
    # na visão da família, escolhendo o titular.
    def pessoas():
        """Titulares possíveis: as carteiras visíveis, com o nome e o parentesco do cadastro de membros."""
        membros = {r["carteira_id"]: r for r in conn.execute("SELECT * FROM fin_membros")}
        out = []
        for c in ctx.carteiras_visiveis():
            m = membros.get(c["id"])
            if m is not None and not m["ativo"]:
                continue  # removido da família (os lançamentos continuam guardados)
            out.append({"id": c["id"], "nome": (m["nome"] if m else None) or c.get("dono_nome") or c["nome"],
                        "carteira": c["nome"], "parentesco": m["parentesco"] if m else "titular",
                        "divide": bool(m["divide"]) if m else True, "cadastrado": m is not None,
                        "nascimento": m["nascimento"] if m else None, "idade": idade(m["nascimento"] if m else None),
                        "tem_login": c.get("dono_id") is not None, "login": c.get("dono_nome"),
                        "editar": bool(c["permissoes"]["editar"]), "minha": c.get("dono_id") == ctx.usuario_id(),
                        "visivel": True})
        # quem divide as contas vê os demais membros que também dividem, mesmo sem acesso à carteira deles:
        # as contas da família e a divisão precisam aparecer no login de cada um (somente leitura)
        if any(p["minha"] and p["divide"] for p in out):
            vistos = {p["id"] for p in out}
            for cid, m in membros.items():
                if cid in vistos or not m["ativo"] or not m["divide"]:
                    continue
                c = conn.execute("""SELECT c.nome, c.dono_id, u.nome AS dono_nome FROM carteiras c
                                    LEFT JOIN usuarios u ON u.id = c.dono_id WHERE c.id = ?""", (cid,)).fetchone()
                if c is None:
                    continue
                out.append({"id": cid, "nome": m["nome"], "carteira": c["nome"], "parentesco": m["parentesco"],
                            "divide": True, "cadastrado": True, "nascimento": m["nascimento"], "idade": idade(m["nascimento"]),
                            "tem_login": c["dono_id"] is not None, "login": c["dono_nome"], "editar": False,
                            "minha": False, "visivel": False})
        return out

    def idade(nascimento):
        try:
            n = dt.date.fromisoformat(nascimento or "")
        except ValueError:
            return None
        h = dt.date.fromisoformat(ctx.hoje())
        return h.year - n.year - ((h.month, h.day) < (n.month, n.day))

    def cids_plan():
        """O planejamento é da família: considera todos os membros visíveis (ou só um, com ?pessoa=id).

        Não depende da carteira escolhida no menu de investimentos: um lançamento feito para outro membro
        precisa aparecer na lista, senão parece que não foi salvo (e acaba lançado duas vezes).
        """
        junto = config("modo_familia", "proporcional") == "junto"
        # no "tudo junto" a renda e as despesas de quem divide as contas formam um orçamento só
        ids = [p["id"] for p in pessoas() if p["visivel"] or (junto and p["divide"])]
        if not ids:
            raise ctx.ErroAcesso("Nenhuma carteira disponível.", 404)
        pessoa = request.args.get("pessoa")
        if pessoa and pessoa.isdigit() and int(pessoa) in ids:
            return [int(pessoa)]
        return ids

    def editaveis():
        return [p for p in pessoas() if p["editar"]]

    def cid_escrita(alvo=None):
        """Carteira onde gravar: a do titular escolhido, a selecionada ou, na visão da família, a própria."""
        ed = editaveis()
        if alvo not in (None, ""):
            try:
                alvo = int(alvo)
            except (TypeError, ValueError):
                alvo = None
            if alvo not in {p["id"] for p in ed}:
                raise ctx.ErroAcesso("Você não pode lançar para essa pessoa.", 403)
            return alvo
        cabecalho = request.headers.get("X-Carteira") or request.args.get("carteira") or ""
        if cabecalho and cabecalho != "todas":
            return ctx.carteira_atual("editar")
        if not ed:
            raise ctx.ErroAcesso("Você tem acesso somente de visualização.", 403)
        return next((p["id"] for p in ed if p["minha"]), ed[0]["id"])

    def exigir_edicao(cid):
        if cid not in {p["id"] for p in editaveis()}:
            raise ctx.ErroAcesso("Lançamento não encontrado.", 404)

    def do_usuario(lid, _cid=None):
        row = conn.execute("SELECT * FROM fin_lancamentos WHERE id = ?", (lid,)).fetchone()
        if row is None:
            raise ctx.ErroAcesso("Lançamento não encontrado.", 404)
        exigir_edicao(row["carteira_id"])
        return dict(row)

    def cartao_valido(cid, cartao_id):
        if not cartao_id:
            return None
        ok = conn.execute("SELECT 1 FROM fin_cartoes WHERE id = ? AND carteira_id = ?", (cartao_id, cid)).fetchone()
        return cartao_id if ok else None

    def numero(v, campo):
        """Aceita número ou texto no padrão brasileiro: '7.200' = 7200, '7.200,50', '7,5'."""
        try:
            if isinstance(v, str):
                t = re.sub(r"R\$|\s", "", v)
                if "," in t:
                    t = t.replace(".", "").replace(",", ".")
                elif re.fullmatch(r"-?\d{1,3}(\.\d{3})+", t):
                    t = t.replace(".", "")
                return float(t)
            return float(v)
        except (TypeError, ValueError):
            raise ValueError(f"Informe {campo} válido.") from None

    def ler_lancamento(d):
        tipo = d.get("tipo")
        if tipo not in ("receita", "despesa"):
            raise ValueError("Escolha receita ou despesa.")
        try:
            data = dt.date.fromisoformat(str(d.get("data") or "")[:10]).isoformat()
        except ValueError:
            raise ValueError("Informe uma data válida.") from None
        descricao = (d.get("descricao") or "").strip()[:120]
        valor = numero(d.get("valor"), "um valor")
        if valor < 0:
            raise ValueError("O valor não pode ser negativo.")
        bruto = d.get("valor_bruto")
        bruto = numero(bruto, "um valor bruto") if bruto not in (None, "") else None
        if bruto is not None and bruto < valor:
            raise ValueError("O valor bruto não pode ser menor que o líquido.")
        cat = d.get("categoria_id")
        cat = int(cat) if str(cat or "").isdigit() else None
        if cat is not None:
            c = conn.execute("SELECT tipo, nome FROM fin_categorias WHERE id = ?", (cat,)).fetchone()
            if c is None or c["tipo"] != tipo:
                raise ValueError("Categoria inválida para este lançamento.")
            descricao = descricao or c["nome"]
        descricao = descricao or ("Receita" if tipo == "receita" else "Despesa")
        forma = d.get("forma") if d.get("forma") in plan.FORMAS else None
        cartao = d.get("cartao_id")
        cartao = int(cartao) if forma == "credito" and str(cartao or "").isdigit() else None
        return {"tipo": tipo, "data": data, "descricao": descricao, "valor": round(valor, 2),
                "valor_bruto": round(bruto, 2) if bruto is not None and tipo == "receita" else None,
                "categoria_id": cat, "forma": forma, "pago": 1 if d.get("pago", True) else 0, "cartao_id": cartao,
                "compartilhado": 1 if d.get("compartilhado") else 0}

    # ---------- categorias ----------
    @app.get("/api/plan/categorias")
    def plan_categorias():
        cats = db.rows(conn.execute("SELECT * FROM fin_categorias WHERE ativa = 1 ORDER BY tipo, ordem, grupo, nome"))
        return jsonify({"categorias": cats, "formas": plan.FORMAS})

    @app.post("/api/plan/categorias")
    def plan_criar_categoria():
        cid_escrita()
        d = request.get_json(silent=True) or {}
        tipo, grupo, nome = d.get("tipo"), (d.get("grupo") or "").strip()[:40], (d.get("nome") or "").strip()[:40]
        if tipo not in ("receita", "despesa") or not grupo or not nome:
            return erro("Informe o tipo, o grupo e o nome da categoria.")
        existe = conn.execute("SELECT id FROM fin_categorias WHERE tipo = ? AND grupo = ? AND nome = ?",
                              (tipo, grupo, nome)).fetchone()
        if existe:
            conn.execute("UPDATE fin_categorias SET ativa = 1 WHERE id = ?", (existe["id"],))
            conn.commit()
            return jsonify({"ok": True, "id": existe["id"]})
        ordem = conn.execute("SELECT COALESCE(MAX(ordem), 0) + 1 FROM fin_categorias WHERE tipo = ? AND grupo = ?",
                             (tipo, grupo)).fetchone()[0]
        cur = conn.execute("INSERT INTO fin_categorias (tipo, grupo, nome, ordem) VALUES (?, ?, ?, ?)",
                           (tipo, grupo, nome, ordem if ordem > 1 else 9000))
        conn.commit()
        return jsonify({"ok": True, "id": cur.lastrowid}), 201

    # ---------- lançamentos ----------
    @app.get("/api/plan/lancamentos")
    def plan_lancamentos():
        cids = cids_plan()
        mes = mes_param()
        todos = pessoas()
        familia = divisao_do_mes(mes, todos)
        outros = [p["id"] for p in todos if p["divide"] and p["id"] not in cids]
        plan.materializar(conn, cids + outros, mes_atual())
        marcas = ",".join("?" * len(cids))
        recs = db.rows(conn.execute(
            f"SELECT * FROM fin_recorrencias WHERE carteira_id IN ({marcas}) ORDER BY tipo DESC, descricao", cids))
        lancs = lancamentos_do_mes(cids, mes)
        if outros and not request.args.get("pessoa"):
            # contas da família pagas por quem você não acompanha: aparecem com a sua parte (sem poder editar)
            for l in lancamentos_do_mes(outros, mes):
                if da_familia(l, familia):
                    lancs.append({**l, "alheio": True})
            m2 = ",".join("?" * len(outros))
            for r in db.rows(conn.execute(f"""SELECT * FROM fin_recorrencias WHERE carteira_id IN ({m2})
                                              AND tipo = 'despesa' AND compartilhado = 1""", outros)):
                recs.append({**r, "alheio": True})
            lancs.sort(key=lambda l: (l["data"], l.get("id") or 0))
        anotar_familia(lancs, familia)
        anotar_familia(recs, familia)
        return jsonify({"mes": mes, "mes_atual": mes_atual(), "lancamentos": lancs, "recorrencias": recs,
                        "pessoas": todos, "modo_familia": familia["modo"],
                        "minhas": [p["id"] for p in todos if p["minha"]]})

    # ---------- contas da família: o que entra na divisão e a parte de cada um ----------
    def divisao_do_mes(mes, todos=None):
        """Regra da família no mês: modo, peso de cada membro que divide as contas e os nomes."""
        modo, pesos_manuais = config("modo_familia", "proporcional"), config("pesos_familia", {})
        quem = [p for p in (todos or pessoas()) if p["divide"]]
        base = []
        for p in quem:
            renda = sum(l["valor"] for l in lancamentos_do_mes([p["id"]], mes)
                        if l["tipo"] == "receita" and not l.get("compartilhado"))
            base.append({"id": p["id"], "nome": p["nome"], "renda": renda, "pagou": 0.0})
        ac = plan.acerto_familia(base, modo, pesos_manuais)
        return {"modo": modo, "pesos": {p["id"]: p["peso"] / 100 for p in ac["pessoas"]},
                "nomes": {p["id"]: p["nome"] for p in quem}}

    def da_familia(l, familia):
        """Despesa da família: marcada como compartilhada ou, no "tudo junto", qualquer compra no cartão."""
        if l.get("tipo") != "despesa" or l["carteira_id"] not in familia["pesos"]:
            return False
        return bool(l.get("compartilhado")) or (familia["modo"] == "junto" and bool(l.get("cartao_id")))

    def anotar_familia(itens, familia):
        for l in itens:
            if not da_familia(l, familia):
                continue
            l["familia"] = True
            if familia["modo"] != "junto" and len(familia["pesos"]) > 1:
                l["partes"] = [{"id": i, "nome": familia["nomes"][i], "valor": round(l["valor"] * w, 2)}
                               for i, w in familia["pesos"].items()]

    def possivel_duplicado(cid, l, repetir):
        """Mesmo titular, tipo e valor, com a mesma categoria ou descrição: no mesmo mês (ou já fixo todo mês)."""
        def parecido(row):
            return (abs(row["valor"] - l["valor"]) < 0.005 and
                    ((l["categoria_id"] and row["categoria_id"] == l["categoria_id"]) or
                     (row["descricao"] or "").strip().lower() == l["descricao"].strip().lower()))
        mes = plan.mes_de(l["data"])
        for row in conn.execute("""SELECT * FROM fin_lancamentos WHERE carteira_id = ? AND tipo = ?
                                   AND substr(data, 1, 7) = ?""", (cid, l["tipo"], mes)):
            if parecido(row):
                return dict(row)
        for row in conn.execute("""SELECT * FROM fin_recorrencias WHERE carteira_id = ? AND tipo = ?
                                   AND inicio <= ? AND (fim IS NULL OR fim >= ?)""", (cid, l["tipo"], mes, mes)):
            if parecido(row):
                return {**dict(row), "mensal": True}
        return None

    @app.post("/api/plan/lancamentos")
    def plan_criar_lancamento():
        d = request.get_json(silent=True) or {}
        cid = cid_escrita(d.get("carteira_id"))
        try:
            l = ler_lancamento(d)
        except ValueError as e:
            return erro(str(e))
        repetir = d.get("repetir") or "nao"
        if not d.get("confirmar_duplicado"):
            igual = possivel_duplicado(cid, l, repetir)
            if igual:
                nome = next((p["nome"] for p in pessoas() if p["id"] == cid), "")
                quando = "todo mês" if igual.get("mensal") else "em " + "/".join(reversed(igual["data"].split("-")))
                valor = f"{igual['valor']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                return jsonify({"erro": f"Já existe “{igual['descricao']}” de R$ {valor} {quando} para {nome}. "
                                        "Lançar de novo vai somar duas vezes.", "duplicado": True}), 409
        if repetir == "mensal":
            fim = (d.get("fim") or "")[:7] or None
            if fim and fim < plan.mes_de(l["data"]):
                return erro("O mês final da repetição é anterior ao primeiro lançamento.")
            cur = conn.execute(
                """INSERT INTO fin_recorrencias (carteira_id, tipo, descricao, categoria_id, valor, valor_bruto, dia,
                   inicio, fim, forma, compartilhado) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (cid, l["tipo"], l["descricao"], l["categoria_id"], l["valor"], l["valor_bruto"],
                 int(l["data"][8:10]), plan.mes_de(l["data"]), fim, l["forma"], l["compartilhado"]))
            conn.commit()
            plan.materializar(conn, [cid], mes_atual())
            # a ocorrência do mês informado já está paga/recebida se o usuário marcou
            if l["pago"]:
                conn.execute("UPDATE fin_lancamentos SET pago = 1 WHERE recorrencia_id = ? AND data <= ?",
                             (cur.lastrowid, ctx.hoje()))
                conn.commit()
            return jsonify({"ok": True, "recorrencia_id": cur.lastrowid}), 201
        if repetir == "parcelado":
            try:
                n = int(d.get("parcelas") or 0)
            except ValueError:
                n = 0
            if not 2 <= n <= 120:
                return erro("Informe de 2 a 120 parcelas.")
            grupo = plan.novo_grupo_parcelas()
            for data, valor, num in plan.parcelas(l["valor"], n, l["data"]):
                conn.execute(
                    """INSERT INTO fin_lancamentos (carteira_id, tipo, data, descricao, categoria_id, valor, forma, pago,
                       parcela_grupo, parcela_num, parcela_total, cartao_id, compartilhado) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (cid, l["tipo"], data, l["descricao"], l["categoria_id"], valor, l["forma"],
                     1 if data <= ctx.hoje() or l["forma"] == "credito" else 0, grupo, num, n,
                     cartao_valido(cid, l["cartao_id"]), l["compartilhado"]))
            conn.commit()
            return jsonify({"ok": True, "parcelas": n}), 201
        cur = conn.execute(
            """INSERT INTO fin_lancamentos (carteira_id, tipo, data, descricao, categoria_id, valor, valor_bruto, forma,
               pago, obs, cartao_id, compartilhado) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (cid, l["tipo"], l["data"], l["descricao"], l["categoria_id"], l["valor"], l["valor_bruto"], l["forma"],
             l["pago"], (d.get("obs") or "")[:200] or None, cartao_valido(cid, l["cartao_id"]), l["compartilhado"]))
        conn.commit()
        return jsonify({"ok": True, "id": cur.lastrowid}), 201

    @app.put("/api/plan/lancamentos/<int:lid>")
    def plan_editar_lancamento(lid):
        atual = do_usuario(lid)
        cid = atual["carteira_id"]
        d = request.get_json(silent=True) or {}
        novo_titular = d.get("carteira_id")
        if novo_titular not in (None, "") and int(novo_titular) != cid:
            cid = cid_escrita(novo_titular)  # troca o titular (verifica a permissão)
            conn.execute("UPDATE fin_lancamentos SET carteira_id = ? WHERE id = ?", (cid, lid))
            if d.get("atualizar_proximos") and atual["recorrencia_id"]:
                conn.execute("UPDATE fin_recorrencias SET carteira_id = ? WHERE id = ?", (cid, atual["recorrencia_id"]))
                conn.execute("UPDATE fin_lancamentos SET carteira_id = ? WHERE recorrencia_id = ? AND data > ?",
                             (cid, atual["recorrencia_id"], atual["data"]))
        if set(d) <= {"pago"}:  # só marcar como pago/recebido
            conn.execute("UPDATE fin_lancamentos SET pago = ? WHERE id = ?", (1 if d.get("pago") else 0, lid))
            conn.commit()
            return jsonify({"ok": True})
        try:
            l = ler_lancamento({**atual, **d, "tipo": atual["tipo"]})
        except ValueError as e:
            return erro(str(e))
        conn.execute("""UPDATE fin_lancamentos SET data = ?, descricao = ?, categoria_id = ?, valor = ?, valor_bruto = ?,
                        forma = ?, pago = ?, cartao_id = ?, compartilhado = ? WHERE id = ?""",
                     (l["data"], l["descricao"], l["categoria_id"], l["valor"], l["valor_bruto"], l["forma"],
                      l["pago"], cartao_valido(cid, l["cartao_id"]), l["compartilhado"], lid))
        if d.get("atualizar_proximos") and atual["recorrencia_id"]:
            # muda também os próximos meses: o modelo da recorrência e as ocorrências futuras ainda não pagas
            conn.execute("""UPDATE fin_recorrencias SET descricao = ?, categoria_id = ?, valor = ?, valor_bruto = ?,
                            forma = ?, compartilhado = ? WHERE id = ? AND carteira_id = ?""",
                         (l["descricao"], l["categoria_id"], l["valor"], l["valor_bruto"], l["forma"],
                          l["compartilhado"], atual["recorrencia_id"], cid))
            conn.execute("""UPDATE fin_lancamentos SET descricao = ?, categoria_id = ?, valor = ?, valor_bruto = ?,
                            forma = ?, compartilhado = ? WHERE recorrencia_id = ? AND data > ? AND pago = 0""",
                         (l["descricao"], l["categoria_id"], l["valor"], l["valor_bruto"], l["forma"],
                          l["compartilhado"], atual["recorrencia_id"], l["data"]))
        conn.commit()
        return jsonify({"ok": True})

    @app.delete("/api/plan/lancamentos/<int:lid>")
    def plan_excluir_lancamento(lid):
        atual = do_usuario(lid)
        cid = atual["carteira_id"]
        escopo = request.args.get("escopo") or "este"
        removidos = 1
        if escopo == "proximos" and atual["recorrencia_id"]:
            # encerra a repetição no mês anterior a este e apaga este e os seguintes
            fim = plan.somar_meses(plan.mes_de(atual["data"]), -1)
            conn.execute("UPDATE fin_recorrencias SET fim = ? WHERE id = ? AND carteira_id = ?",
                         (fim, atual["recorrencia_id"], cid))
            removidos = conn.execute("DELETE FROM fin_lancamentos WHERE recorrencia_id = ? AND data >= ?",
                                     (atual["recorrencia_id"], atual["data"])).rowcount
            conn.execute("""DELETE FROM fin_recorrencias WHERE id = ? AND fim < inicio""", (atual["recorrencia_id"],))
        elif escopo == "proximos" and atual["parcela_grupo"]:
            removidos = conn.execute("DELETE FROM fin_lancamentos WHERE parcela_grupo = ? AND carteira_id = ? AND parcela_num >= ?",
                                     (atual["parcela_grupo"], cid, atual["parcela_num"])).rowcount
        else:
            conn.execute("DELETE FROM fin_lancamentos WHERE id = ?", (lid,))
        if atual.get("nota_id"):  # nota sem nenhum lançamento: some também (pode ser lida de novo)
            conn.execute("""DELETE FROM fin_notas WHERE id = ? AND NOT EXISTS
                            (SELECT 1 FROM fin_lancamentos WHERE nota_id = ?)""", (atual["nota_id"], atual["nota_id"]))
        conn.commit()
        return jsonify({"ok": True, "removidos": removidos})

    @app.delete("/api/plan/recorrencias/<int:rid>")
    def plan_encerrar_recorrencia(rid):
        """Encerra uma conta/receita recorrente: os meses já lançados ficam; os próximos deixam de existir."""
        r = conn.execute("SELECT * FROM fin_recorrencias WHERE id = ?", (rid,)).fetchone()
        if r is None:
            return erro("Recorrência não encontrada.", 404)
        exigir_edicao(r["carteira_id"])
        if request.args.get("tudo"):  # lançada por engano: some com todos os meses, inclusive os já lançados
            n = conn.execute("DELETE FROM fin_lancamentos WHERE recorrencia_id = ?", (rid,)).rowcount
            conn.execute("DELETE FROM fin_recorrencias WHERE id = ?", (rid,))
            conn.commit()
            return jsonify({"ok": True, "removidos": n})
        fim = mes_atual()
        conn.execute("DELETE FROM fin_lancamentos WHERE recorrencia_id = ? AND substr(data, 1, 7) > ?", (rid, fim))
        if r["inicio"] > fim:
            conn.execute("DELETE FROM fin_recorrencias WHERE id = ?", (rid,))
        else:
            conn.execute("UPDATE fin_recorrencias SET fim = ? WHERE id = ?", (fim, rid))
        conn.commit()
        return jsonify({"ok": True})

    # ---------- cartões ----------
    def listar_cartoes(cids):
        marcas = ",".join("?" * len(cids))
        return db.rows(conn.execute(
            f"SELECT * FROM fin_cartoes WHERE carteira_id IN ({marcas}) AND ativo = 1 ORDER BY nome", cids))

    @app.get("/api/plan/cartoes")
    def plan_cartoes():
        return jsonify(listar_cartoes(cids_plan()))

    def ler_cartao(d):
        nome = (d.get("nome") or "").strip()[:40]
        if not nome:
            raise ValueError("Informe o nome do cartão (ex.: Nubank, Itaú Visa).")
        dias = {}
        for campo, rotulo in (("dia_vencimento", "vencimento"), ("dia_fechamento", "fechamento")):
            try:
                dias[campo] = int(d.get(campo) or 0) or None
            except (TypeError, ValueError):
                dias[campo] = None
            if dias[campo] is not None and not 1 <= dias[campo] <= 31:
                raise ValueError(f"Dia de {rotulo} inválido.")
        limite = d.get("limite")
        limite = numero(limite, "um limite") if limite not in (None, "") else None
        final = re.sub(r"\D", "", str(d.get("final") or ""))[-4:] or None
        return {"nome": nome, "limite": limite if limite and limite > 0 else None, "final": final, **dias}

    @app.post("/api/plan/cartoes")
    def plan_criar_cartao():
        d = request.get_json(silent=True) or {}
        cid = cid_escrita(d.get("carteira_id"))
        try:
            c = ler_cartao(d)
        except ValueError as e:
            return erro(str(e))
        cur = conn.execute("""INSERT INTO fin_cartoes (carteira_id, nome, dia_vencimento, dia_fechamento, limite, final)
                              VALUES (?, ?, ?, ?, ?, ?)""",
                           (cid, c["nome"], c["dia_vencimento"], c["dia_fechamento"], c["limite"], c["final"]))
        conn.commit()
        return jsonify({"ok": True, "id": cur.lastrowid}), 201

    @app.put("/api/plan/cartoes/<int:cartao_id>")
    def plan_editar_cartao(cartao_id):
        atual = conn.execute("SELECT * FROM fin_cartoes WHERE id = ? AND ativo = 1", (cartao_id,)).fetchone()
        if atual is None:
            return erro("Cartão não encontrado.", 404)
        exigir_edicao(atual["carteira_id"])
        d = request.get_json(silent=True) or {}
        try:
            c = ler_cartao(d)
        except ValueError as e:
            return erro(str(e))
        dono = atual["carteira_id"]
        if d.get("carteira_id") not in (None, "") and int(d["carteira_id"]) != dono:
            dono = cid_escrita(d["carteira_id"])  # passa o cartão (e as compras dele) para outro membro
            conn.execute("UPDATE fin_lancamentos SET carteira_id = ? WHERE cartao_id = ?", (dono, cartao_id))
        conn.execute("""UPDATE fin_cartoes SET nome = ?, dia_vencimento = ?, dia_fechamento = ?, limite = ?, final = ?,
                        carteira_id = ? WHERE id = ?""",
                     (c["nome"], c["dia_vencimento"], c["dia_fechamento"], c["limite"], c["final"], dono, cartao_id))
        conn.commit()
        return jsonify({"ok": True})

    # ---------- faturas de um cartão, mês a mês ----------
    def faturas_do_cartao(cartao, hoje, meses_atras=12):
        f, v = cartao["dia_fechamento"], cartao["dia_vencimento"]
        desde = plan.somar_meses(hoje[:7], -meses_atras - 1) + "-01"
        lancs = db.rows(conn.execute(
            """SELECT * FROM fin_lancamentos WHERE cartao_id = ? AND data >= ? ORDER BY data, id""", (cartao["id"], desde)))
        grupos = {}
        for l in lancs:
            grupos.setdefault(plan.fatura_da_compra(l["data"], f, v), []).append(l)
        faturas = []
        for mes in sorted(grupos, reverse=True):
            if mes < plan.somar_meses(hoje[:7], -meses_atras):
                continue
            itens = grupos[mes]
            compras = sum(l["valor"] for l in itens if l["tipo"] == "despesa")
            creditos = sum(l["valor"] for l in itens if l["tipo"] == "receita")
            fecha, vence = plan.datas_da_fatura(mes, f, v)
            faturas.append({"mes": mes, "fechamento": fecha, "vencimento": vence,
                            "situacao": plan.situacao_fatura(mes, f, v, hoje), "total": round(compras - creditos, 2),
                            "compras": round(compras, 2), "creditos": round(creditos, 2),
                            "qtd": sum(1 for l in itens if l["tipo"] == "despesa"),
                            "importada": any(l["chave_import"] for l in itens), "itens": itens})
        return faturas

    def alertas_do_cartao(cartao, faturas, hoje):
        """Avisos de um cartão: vencimento chegando, fatura fechada sem importar, limite e gasto acima da média."""
        nome, out = cartao["nome"], []
        brl_ = lambda v: f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")  # noqa: E731
        data_br = lambda d: "/".join(reversed(d.split("-")))[:5]  # noqa: E731
        h = dt.date.fromisoformat(hoje)
        for fat_ in faturas:
            if fat_["vencimento"] and fat_["total"] > 0 and hoje <= fat_["vencimento"] and fat_["situacao"] in ("fechada", "aberta"):
                dias = (dt.date.fromisoformat(fat_["vencimento"]) - h).days
                if dias <= 5:
                    out.append({"nivel": "alerta", "codigo": "vencimento",
                                "titulo": f"Fatura do {nome} vence {'hoje' if dias == 0 else f'em {dias} dia(s)'} ({data_br(fat_['vencimento'])})",
                                "texto": f"Valor da fatura: {brl_(fat_['total'])}.", "chave": f"vence:{fat_['mes']}"})
        ja_importou = conn.execute("SELECT 1 FROM fin_lancamentos WHERE cartao_id = ? AND chave_import IS NOT NULL LIMIT 1",
                                   (cartao["id"],)).fetchone()
        fechadas = [x for x in faturas if x["situacao"] == "fechada" and x["fechamento"]]
        if ja_importou:
            for fat_ in fechadas:
                if not fat_["importada"] and (h - dt.date.fromisoformat(fat_["fechamento"])).days >= 1:
                    out.append({"nivel": "info", "codigo": "importar",
                                "titulo": f"A fatura de {plan.nome_mes(fat_['mes'])} do {nome} já fechou",
                                "texto": f"Fechou em {data_br(fat_['fechamento'])}. Importe o PDF/OFX para conferir as compras.",
                                "chave": f"importar:{fat_['mes']}"})
        if cartao.get("limite"):
            usado = sum(x["total"] for x in faturas if x["situacao"] in ("aberta", "fechada", "futura"))
            pct_ = usado / cartao["limite"] * 100
            if pct_ >= 80:
                out.append({"nivel": "alerta" if pct_ >= 95 else "info", "codigo": "limite",
                            "titulo": f"{nome}: {pct_:.0f}% do limite comprometido",
                            "texto": f"{brl_(usado)} de {brl_(cartao['limite'])}, somando a fatura atual e as parcelas futuras.",
                            "chave": f"limite:{int(pct_ // 5) * 5}"})
        aberta = next((x for x in faturas if x["situacao"] == "aberta"), None)
        anteriores = [x["total"] for x in faturas if x["situacao"] == "encerrada" and x["total"] > 0][:3]
        if aberta and len(anteriores) >= 2:
            media = sum(anteriores) / len(anteriores)
            if aberta["total"] >= 100 and aberta["total"] > media * 1.3:
                out.append({"nivel": "info", "codigo": "media",
                            "titulo": f"{nome}: fatura atual acima da média",
                            "texto": f"{brl_(aberta['total'])} até agora, contra a média de {brl_(media)} das últimas faturas.",
                            "chave": f"media:{aberta['mes']}"})
        return out

    @app.get("/api/plan/cartoes/<int:cartao_id>/faturas")
    def plan_faturas_cartao(cartao_id):
        cartao = next((c for c in listar_cartoes(cids_plan()) if c["id"] == cartao_id), None)
        if cartao is None:
            return erro("Cartão não encontrado.", 404)
        hoje = ctx.hoje()
        faturas = faturas_do_cartao(cartao, hoje)
        return jsonify({**resumo_do_cartao(cartao, faturas, hoje), "faturas": faturas,
                        "pessoas": [{"id": p["id"], "nome": p["nome"]} for p in pessoas() if p["editar"]], "hoje": hoje})

    def resumo_do_cartao(cartao, faturas, hoje, todos=None):
        dono = next((p for p in (todos or pessoas()) if p["id"] == cartao["carteira_id"]), None)
        aberta = next((x for x in faturas if x["situacao"] == "aberta"), None)
        a_vencer = sorted((x for x in faturas if x["situacao"] in ("fechada", "aberta")), key=lambda x: x["mes"])
        futuras = sum(x["total"] for x in faturas if x["situacao"] == "futura")
        usado = sum(x["total"] for x in faturas if x["situacao"] in ("aberta", "fechada", "futura"))
        aguardando = conn.execute("""SELECT COUNT(*) FROM fin_lancamentos WHERE cartao_id = ? AND tipo = 'despesa'
                                     AND chave_import IS NULL AND parcela_total IS NULL""", (cartao["id"],)).fetchone()[0]
        sem_itens = lambda f: {k: v for k, v in f.items() if k != "itens"} if f else None  # noqa: E731
        return {"cartao": {**cartao, "dono": dono["nome"] if dono else None, "pode_editar": bool(dono and dono["editar"]),
                           "dias_estimados": not cartao["dia_fechamento"] and bool(cartao["dia_vencimento"])},
                "alertas": alertas_do_cartao(cartao, faturas, hoje),
                "resumo": {"aberta": aberta["total"] if aberta else 0.0, "aberta_fecha": aberta["fechamento"] if aberta else None,
                           "em_aberto": round(sum(x["total"] for x in faturas if x["situacao"] in ("aberta", "fechada")), 2),
                           "proxima": sem_itens(a_vencer[0]) if a_vencer else None, "futuras": round(futuras, 2),
                           "usado": round(usado, 2),
                           "disponivel": round(cartao["limite"] - usado, 2) if cartao.get("limite") else None,
                           "aguardando": aguardando,
                           "ultimas": [{"mes": x["mes"], "total": x["total"]} for x in faturas
                                       if x["situacao"] in ("encerrada", "fechada", "aberta")][:6]}}

    @app.get("/api/plan/cartoes/resumo")
    def plan_resumo_cartoes():
        """Visão de todos os cartões: valores de cada um, totais e avisos."""
        hoje, todos = ctx.hoje(), pessoas()
        cartoes = [resumo_do_cartao(c, faturas_do_cartao(c, hoje, 6), hoje, todos) for c in listar_cartoes(cids_plan())]
        r = [c["resumo"] for c in cartoes]
        limites = sum(c["cartao"]["limite"] or 0 for c in cartoes)
        usado_com_limite = sum(c["resumo"]["usado"] for c in cartoes if c["cartao"]["limite"])
        proximas = sorted((dict(c["resumo"]["proxima"], cartao=c["cartao"]["nome"], cartao_id=c["cartao"]["id"])
                           for c in cartoes if c["resumo"]["proxima"] and c["resumo"]["proxima"]["vencimento"]
                           and c["resumo"]["proxima"]["vencimento"] >= hoje), key=lambda x: x["vencimento"])
        return jsonify({"cartoes": cartoes, "hoje": hoje,
                        "totais": {"aberta": round(sum(x["aberta"] for x in r), 2),
                                   "em_aberto": round(sum(x["em_aberto"] for x in r), 2),
                                   "a_vencer": round(sum(x["proxima"]["total"] for x in r if x["proxima"]), 2),
                                   "futuras": round(sum(x["futuras"] for x in r), 2), "limite": round(limites, 2),
                                   "usado": round(usado_com_limite, 2), "aguardando": sum(x["aguardando"] for x in r)},
                        "proximo_vencimento": proximas[0] if proximas else None,
                        "pessoas": [{"id": p["id"], "nome": p["nome"]} for p in todos if p["editar"]]})

    @app.delete("/api/plan/cartoes/<int:cartao_id>")
    def plan_excluir_cartao(cartao_id):
        """Desativa o cartão (os lançamentos continuam, sem perder o histórico)."""
        c = conn.execute("SELECT carteira_id FROM fin_cartoes WHERE id = ?", (cartao_id,)).fetchone()
        if c is None:
            return erro("Cartão não encontrado.", 404)
        exigir_edicao(c["carteira_id"])
        conn.execute("UPDATE fin_cartoes SET ativo = 0 WHERE id = ?", (cartao_id,))
        conn.commit()
        return jsonify({"ok": True})

    # ---------- importação de fatura ----------
    def regras_usuario(cid):
        rows = conn.execute("SELECT padrao, categoria_id FROM fin_regras WHERE carteira_id = ?", (cid,)).fetchall()
        return sorted(((r["padrao"], r["categoria_id"]) for r in rows), key=lambda x: -len(x[0]))

    def categorias_por_nome():
        return {(c["tipo"], c["nome"]): c["id"] for c in categorias().values() if c["ativa"]}

    def carteira_do_cartao(cartao_id):
        try:
            c = conn.execute("SELECT carteira_id FROM fin_cartoes WHERE id = ? AND ativo = 1",
                             (int(cartao_id or 0),)).fetchone()
        except ValueError:
            c = None
        if c is None or c["carteira_id"] not in {p["id"] for p in editaveis()}:
            return None, None
        return c["carteira_id"], int(cartao_id)

    @app.post("/api/plan/fatura/previa")
    def plan_fatura_previa():
        arq = request.files.get("arquivo")
        if not arq or not arq.filename:
            return erro("Selecione o arquivo da fatura.")
        cid, cartao_id = carteira_do_cartao(request.form.get("cartao_id"))
        if not cartao_id:
            return erro("Escolha o cartão desta fatura.")
        try:
            itens = fat.ler_fatura(arq.read(), arq.filename, request.form.get("senha") or None)  # senha não é guardada
        except ErroImportacao as e:
            return erro(str(e))
        regras, por_nome = regras_usuario(cid), categorias_por_nome()
        chaves = {r["chave_import"] for r in conn.execute(
            "SELECT chave_import FROM fin_lancamentos WHERE carteira_id = ? AND chave_import IS NOT NULL", (cid,))}
        datas_import = {r["chave_import"]: r["data"] for r in conn.execute(
            "SELECT chave_import, data FROM fin_lancamentos WHERE carteira_id = ? AND chave_import IS NOT NULL", (cid,))}
        for it in itens:
            it["chave"] = fat.chave_importacao(cartao_id, it)
            it["ja_importado"] = it["chave"] in chaves
            if it.get("antecipada") and it["ja_importado"] and datas_import.get(it["chave"], "")[:7] > it["data"][:7]:
                # a parcela já estava lançada num mês futuro: a importação a traz para esta fatura
                it["ja_importado"], it["antecipar"] = False, datas_import[it["chave"]]
            it["categoria_id"], it["origem_categoria"] = sugerir_categoria_item(it, regras, por_nome)
            it["categoria_sugerida"] = it["categoria_id"]
            it["marcado"] = it["tipo"] != "pagamento" and not it["ja_importado"]
        # já importado por uma versão anterior do leitor (descrição diferente, mesma compra): não duplica
        existentes = db.rows(conn.execute(
            """SELECT id, data, valor, descricao, parcela_num, parcela_total FROM fin_lancamentos
               WHERE cartao_id = ? AND chave_import IS NOT NULL""", (cartao_id,)))
        usados = set()
        for it in itens:
            if it["ja_importado"] or it.get("antecipar") or it["tipo"] == "pagamento":
                continue
            for e in existentes:
                if e["id"] in usados or abs(e["valor"] - it["valor"]) > 0.005 or not fat.mesmo_texto(e["descricao"], it["descricao"]):
                    continue
                if (it["parcela_total"] and (e["parcela_num"], e["parcela_total"]) == (it["parcela_num"], it["parcela_total"])) \
                        or (not it["parcela_total"] and e["data"] == it["data"]):
                    usados.add(e["id"])
                    it["ja_importado"], it["marcado"] = True, False
                    break
        # conciliação: compras deste cartão lançadas à mão que ainda aguardam a fatura
        fat.conciliar(itens, compras_aguardando(cartao_id))
        for it in itens:
            c = it["conciliacao"]
            if c:
                it["acao"] = "unir"
                if c["lancamento"].get("categoria_id"):  # a categoria escolhida por você prevalece
                    it["categoria_id"], it["origem_categoria"] = c["lancamento"]["categoria_id"], "sua"
        compras = [i for i in itens if i["tipo"] in ("compra", "tarifa")]
        return jsonify({
            "itens": itens, "cartao_id": cartao_id,
            "resumo": {"compras": len(compras), "total": round(sum(i["valor"] for i in compras), 2),
                       "estornos": round(sum(i["valor"] for i in itens if i["tipo"] == "estorno"), 2),
                       "ja_importados": sum(1 for i in itens if i["ja_importado"]),
                       "categorizados": sum(1 for i in compras if i["categoria_id"]),
                       "parceladas": sum(1 for i in compras if i["parcela_total"]),
                       "conciliadas": sum(1 for i in itens if (i["conciliacao"] or {}).get("tipo") == "exato"),
                       "possiveis": sum(1 for i in itens if (i["conciliacao"] or {}).get("tipo") == "possivel"),
                       "aguardando": len(compras_aguardando(cartao_id))}})

    def compras_aguardando(cartao_id):
        """Compras no crédito lançadas à mão neste cartão que ainda não foram conferidas com uma fatura."""
        return db.rows(conn.execute(
            """SELECT id, data, valor, descricao, parcela_num, parcela_total, parcela_grupo, categoria_id
               FROM fin_lancamentos WHERE cartao_id = ? AND tipo = 'despesa' AND chave_import IS NULL
               ORDER BY data, id""", (cartao_id,)))

    def sugerir_categoria_item(it, regras, por_nome):
        if it["tipo"] == "pagamento":
            return None, None
        return fat.sugerir_categoria(it, regras, por_nome)

    @app.post("/api/plan/fatura/confirmar")
    def plan_fatura_confirmar():
        d = request.get_json(silent=True) or {}
        cid, cartao_id = carteira_do_cartao(d.get("cartao_id"))
        if not cartao_id:
            return erro("Escolha o cartão desta fatura.")
        vencimento = None  # só vale quando o usuário escolhe lançar na data de vencimento
        if d.get("data_modo") == "vencimento":
            vencimento = d.get("vencimento")
            try:
                vencimento = dt.date.fromisoformat(str(vencimento)[:10]).isoformat()
            except ValueError:
                return erro("Informe a data de vencimento da fatura.")
        futuras = bool(d.get("parcelas_futuras", True))
        cats = categorias()
        chaves = {r["chave_import"] for r in conn.execute(
            "SELECT chave_import FROM fin_lancamentos WHERE carteira_id = ? AND chave_import IS NOT NULL", (cid,))}
        criados, futuras_criadas, aprendidas, conferidos, antecipadas = 0, 0, 0, 0, 0

        def inserir(tipo, data, desc, cat, valor, chave, pago, grupo=None, num=None, total=None):
            conn.execute(
                """INSERT INTO fin_lancamentos (carteira_id, tipo, data, descricao, categoria_id, valor, forma, pago,
                   parcela_grupo, parcela_num, parcela_total, cartao_id, chave_import)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (cid, tipo, data, desc, cat, valor, "credito", pago, grupo, num, total, cartao_id, chave))
            chaves.add(chave)

        # parcelas antecipadas por último: elas puxam para este mês a parcela futura já lançada
        for it in sorted(d.get("itens") or [], key=lambda x: bool(isinstance(x, dict) and x.get("antecipada"))):
            try:
                valor = round(float(it["valor"]), 2)
                data = dt.date.fromisoformat(str(it["data"])[:10]).isoformat()
                tipo_item = it["tipo"]
            except (KeyError, TypeError, ValueError):
                return erro("Item inválido na fatura.")
            if tipo_item == "pagamento" or valor <= 0:
                continue
            cat = it.get("categoria_id")
            cat = int(cat) if str(cat or "").isdigit() and int(cat) in cats else None
            tipo = "receita" if tipo_item == "estorno" else "despesa"
            if cat and cats[cat]["tipo"] != tipo:
                cat = None
            chave = str(it.get("chave") or "")[:60]
            if it.get("antecipada") and chave in chaves:
                futura = conn.execute("SELECT id, data FROM fin_lancamentos WHERE carteira_id = ? AND chave_import = ?",
                                      (cid, chave)).fetchone()
                data_nova = vencimento if vencimento else data
                if futura and futura["data"][:7] > data_nova[:7]:
                    conn.execute("UPDATE fin_lancamentos SET data = ?, valor = ?, descricao = ? WHERE id = ?",
                                 (data_nova, valor, str(it.get("descricao") or "")[:120] or "Parcela antecipada", futura["id"]))
                    antecipadas += 1
                continue
            if not chave or chave in chaves:
                continue
            unir = it.get("acao") == "unir" and str(it.get("lancamento_id") or "").isdigit()
            if unir:
                # mesma compra lançada à mão: confere e fica um lançamento só (valor da fatura, sua categoria)
                manual = conn.execute(
                    """SELECT * FROM fin_lancamentos WHERE id = ? AND cartao_id = ? AND chave_import IS NULL
                       AND tipo = 'despesa'""", (int(it["lancamento_id"]), cartao_id)).fetchone()
                if manual is None:
                    return erro("Uma compra a conferir não foi encontrada. Leia a fatura de novo.", 409)
                conn.execute("""UPDATE fin_lancamentos SET chave_import = ?, conferido_em = ?, valor = ?,
                                categoria_id = COALESCE(?, categoria_id) WHERE id = ?""",
                             (chave, ctx.hoje(), valor, cat, manual["id"]))
                chaves.add(chave)
                conferidos += 1
                est = fat.chave_estabelecimento(it.get("descricao") or "")
                cat_final = cat or manual["categoria_id"]
                if cat_final and est:  # aprende com a categoria que você deu à compra
                    conn.execute("""INSERT INTO fin_regras (carteira_id, padrao, categoria_id) VALUES (?, ?, ?)
                                    ON CONFLICT(carteira_id, padrao) DO UPDATE SET categoria_id = excluded.categoria_id,
                                    usos = usos + 1""", (cid, est, cat_final))
                continue
            data_lanc = vencimento if vencimento else data
            num, total = it.get("parcela_num"), it.get("parcela_total")
            grupo = chave[2:].split("#")[0] if chave.startswith("p:") else None
            inserir(tipo, data_lanc, str(it.get("descricao") or "")[:120] or "Compra no cartão", cat, valor, chave, 1,
                    grupo, num, total)
            criados += 1
            if grupo and futuras and num and total and num < total and not it.get("antecipada"):
                for k in range(num + 1, total + 1):
                    ch = f"p:{grupo}#{k}"
                    if ch in chaves:
                        continue
                    data_k = plan.data_no_mes(plan.somar_meses(data_lanc[:7], k - num), int(data_lanc[8:10]))
                    desc_k = re.sub(rf"\b0?{num}\s*(/|DE|de)\s*0?{total}\b", f"{k:02d}/{total:02d}",
                                    str(it.get("descricao") or ""), count=1)[:120]
                    inserir(tipo, data_k, desc_k, cat, valor, ch, 1, grupo, k, total)
                    futuras_criadas += 1
            # aprende: estabelecimento -> categoria escolhida
            est = fat.chave_estabelecimento(it.get("descricao") or "")
            sugerida = it.get("categoria_sugerida")
            if cat and est and tipo == "despesa" and (sugerida != cat or it.get("origem_categoria") == "aprendida"):
                # aprende o que o usuário escolheu ou corrigiu (aceitar a sugestão automática não vira regra)
                atual = conn.execute("SELECT categoria_id FROM fin_regras WHERE carteira_id = ? AND padrao = ?",
                                     (cid, est)).fetchone()
                if atual is None or atual["categoria_id"] != cat:
                    aprendidas += 1
                conn.execute("""INSERT INTO fin_regras (carteira_id, padrao, categoria_id) VALUES (?, ?, ?)
                                ON CONFLICT(carteira_id, padrao) DO UPDATE SET categoria_id = excluded.categoria_id,
                                usos = usos + 1""", (cid, est, cat))
        conn.commit()
        return jsonify({"ok": True, "lancamentos": criados, "parcelas_futuras": futuras_criadas,
                        "regras_aprendidas": aprendidas, "conferidos": conferidos,
                        "antecipadas": antecipadas}), 201

    @app.post("/api/plan/lancamentos/<int:lid>/desfazer-conferencia")
    def plan_desfazer_conferencia(lid):
        """Separa a compra lançada à mão da linha da fatura (a linha volta a ser importável)."""
        atual = do_usuario(lid)
        if not atual.get("conferido_em"):
            return erro("Este lançamento não foi conferido com uma fatura.")
        conn.execute("UPDATE fin_lancamentos SET chave_import = NULL, conferido_em = NULL WHERE id = ?", (lid,))
        conn.commit()
        return jsonify({"ok": True})

    # ---------- resumo ----------
    @app.get("/api/plan/resumo")
    def plan_resumo():
        cids = cids_plan()
        mes, hoje = mes_param(), ctx.hoje()
        plan.materializar(conn, cids, mes_atual())
        cats = categorias()
        prov = plan.proventos_por_mes(ctx.listar_proventos(cids), hoje)
        inv = plan.investido_por_mes(ctx.listar_aportes(cids))

        def resumo(m, anterior=None):
            return plan.resumo_mes(lancamentos_do_mes(cids, m), cats, m, prov.get(m, 0.0), inv.get(m, 0.0), anterior)

        anterior = resumo(plan.somar_meses(mes, -1))
        atual = resumo(mes, anterior)
        # série de 12 meses até o mês escolhido
        serie = []
        for m in plan.meses_entre(plan.somar_meses(mes, -11), mes):
            r = atual if m == mes else anterior if m == plan.somar_meses(mes, -1) else resumo(m)
            serie.append({"mes": m, "receitas": r["receitas"], "despesas": r["despesas"], "investido": r["investido"],
                          "projetado": m > mes_atual()})
        marcas = ",".join("?" * len(cids))
        desp_mes = {row["m"]: row["v"] for row in conn.execute(
            f"""SELECT substr(data, 1, 7) AS m, SUM(valor) AS v FROM fin_lancamentos
                WHERE tipo = 'despesa' AND carteira_id IN ({marcas}) GROUP BY m""", cids)}
        tem_lancamentos = conn.execute(
            f"SELECT 1 FROM fin_lancamentos WHERE carteira_id IN ({marcas}) LIMIT 1", cids).fetchone() is not None
        cartoes = []
        for c in listar_cartoes(cids):
            row = conn.execute(
                """SELECT SUM(CASE WHEN tipo = 'despesa' THEN valor ELSE -valor END) AS total,
                          SUM(CASE WHEN tipo = 'despesa' THEN 1 ELSE 0 END) AS qtd
                   FROM fin_lancamentos WHERE cartao_id = ? AND substr(data, 1, 7) = ?""", (c["id"], mes)).fetchone()
            if row["qtd"]:
                cartoes.append({"id": c["id"], "nome": c["nome"], "total": row["total"] or 0, "compras": row["qtd"],
                                "dia_vencimento": c["dia_vencimento"]})
        return jsonify({**atual, "cartoes": cartoes, "anterior": {k: anterior[k] for k in ("receitas", "despesas", "investido", "sobra")},
                        "serie": serie, "custo_de_vida": plan.custo_de_vida(desp_mes, mes_atual()),
                        "mes_atual": mes_atual(), "vazio": not tem_lancamentos})

    # ================================================================ fase 3: família
    def config(chave, padrao=None):
        row = conn.execute("SELECT valor FROM fin_config WHERE chave = ?", (chave,)).fetchone()
        return json.loads(row["valor"]) if row else padrao

    def salvar_config(chave, valor):
        conn.execute("INSERT INTO fin_config (chave, valor) VALUES (?, ?) ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor",
                     (chave, json.dumps(valor)))

    @app.get("/api/plan/familia")
    def plan_familia():
        mes = mes_param()
        carteiras = pessoas()
        cids = [c["id"] for c in carteiras]
        plan.materializar(conn, cids, mes_atual())
        modo, pesos = config("modo_familia", "proporcional"), config("pesos_familia", {})
        familia = divisao_do_mes(mes, carteiras)
        participantes, totais = [], {"receitas": 0.0, "despesas": 0.0, "compartilhadas": 0.0}
        itens = []  # cada conta da família do mês, com a parte de cada membro
        prov = plan.proventos_por_mes(ctx.listar_proventos(cids), ctx.hoje()) if cids else {}
        inv = plan.investido_por_mes(ctx.listar_aportes(cids)) if cids else {}
        for c in carteiras:
            lancs = lancamentos_do_mes([c["id"]], mes)
            renda = sum(l["valor"] for l in lancs if l["tipo"] == "receita" and not l.get("compartilhado"))
            totais["receitas_grupo"] = totais.get("receitas_grupo", 0.0) + sum(
                l["valor"] for l in lancs if l["tipo"] == "receita" and l.get("compartilhado"))
            desp = sum(l["valor"] for l in lancs if l["tipo"] == "despesa")
            comum = sum(l["valor"] for l in lancs if da_familia(l, familia) or (l["tipo"] == "despesa" and l.get("compartilhado")))
            for l in lancs:
                if da_familia(l, familia):
                    itens.append({**{k: l.get(k) for k in ("id", "tipo", "data", "descricao", "valor", "categoria_id", "cartao_id",
                                                        "recorrencia_id", "parcela_num", "parcela_total", "carteira_id",
                                                        "compartilhado")}, "pago_por": c["nome"]})
            participantes.append({"id": c["id"], "nome": c["nome"], "carteira": c["carteira"], "divide": c["divide"],
                                  "renda": renda, "pagou": comum, "despesas_pessoais": desp - comum})
            totais["receitas"] += renda
            totais["despesas"] += desp
            totais["compartilhadas"] += comum
        # só quem divide as contas entra no acerto; contas pagas por quem não divide ficam fora da divisão
        acerto = plan.acerto_familia([p for p in participantes if p["divide"]], modo, pesos)
        acerto["fora_da_divisao"] = [p for p in participantes if not p["divide"]]
        investido, proventos = inv.get(mes, 0.0), prov.get(mes, 0.0)
        totais.setdefault("receitas_grupo", 0.0)
        totais.update({"investido": investido, "proventos": proventos,
                       "sobra": totais["receitas"] + totais["receitas_grupo"] + proventos - totais["despesas"] - investido})
        anotar_familia(itens, familia)
        itens.sort(key=lambda l: (l["data"], l.get("id") or 0))
        return jsonify({"mes": mes, "modo": modo, "modos": plan.MODOS_FAMILIA, "pesos": pesos, "totais": totais,
                        "itens": itens, "minhas": [c["id"] for c in carteiras if c["minha"]],
                        **acerto, "pode_configurar": bool(ctx.eh_admin())})

    @app.put("/api/plan/familia")
    def plan_familia_config():
        if not ctx.eh_admin():
            return erro("Apenas o administrador define como a família divide as contas.", 403)
        d = request.get_json(silent=True) or {}
        modo = d.get("modo")
        if modo not in plan.MODOS_FAMILIA:
            return erro("Modo inválido.")
        salvar_config("modo_familia", modo)
        if modo == "personalizado":
            try:
                pesos = {str(int(k)): max(float(v), 0) for k, v in (d.get("pesos") or {}).items()}
            except (TypeError, ValueError):
                return erro("Percentuais inválidos.")
            if not sum(pesos.values()):
                return erro("Informe os percentuais de cada pessoa.")
            salvar_config("pesos_familia", pesos)
        conn.commit()
        return jsonify({"ok": True})

    # ================================================================ membros da família
    @app.get("/api/plan/membros")
    def plan_membros():
        return jsonify({"membros": pessoas(), "parentescos": plan.PARENTESCOS,
                        "configurado": bool(config("membros_configurados", False)), "pode_configurar": bool(ctx.eh_admin())})

    @app.put("/api/plan/membros")
    def plan_salvar_membros():
        if not ctx.eh_admin():
            return erro("Apenas o administrador cadastra os membros da família.", 403)
        visiveis = {p["id"] for p in pessoas()}
        for m in (request.get_json(silent=True) or {}).get("membros") or []:
            try:
                cid = int(m.get("id"))
            except (TypeError, ValueError):
                continue
            nome = (m.get("nome") or "").strip()[:60]
            if cid not in visiveis or not nome:
                continue
            parentesco = m.get("parentesco") if m.get("parentesco") in plan.PARENTESCOS else "outro"
            conn.execute("""INSERT INTO fin_membros (carteira_id, nome, parentesco, divide) VALUES (?, ?, ?, ?)
                            ON CONFLICT(carteira_id) DO UPDATE SET nome = excluded.nome, parentesco = excluded.parentesco,
                            divide = excluded.divide""", (cid, nome, parentesco, 1 if m.get("divide") else 0))
        salvar_config("membros_configurados", True)
        conn.commit()
        return jsonify({"ok": True})

    def ler_membro(d):
        nome = (d.get("nome") or "").strip()[:60]
        if not nome:
            raise ValueError("Informe o nome do membro da família.")
        nasc = (d.get("nascimento") or "").strip()[:10] or None
        if nasc:
            try:
                if dt.date.fromisoformat(nasc) > dt.date.fromisoformat(ctx.hoje()):
                    raise ValueError
            except ValueError:
                raise ValueError("Data de nascimento inválida.") from None
        return {"nome": nome, "parentesco": d.get("parentesco") if d.get("parentesco") in plan.PARENTESCOS else "outro",
                "nascimento": nasc, "divide": 1 if d.get("divide") else 0}

    @app.post("/api/plan/membros")
    def plan_novo_membro():
        """Membro da família sem login (filhos, pais...): ganha uma carteira própria para os lançamentos."""
        if not ctx.eh_admin():
            return erro("Apenas o administrador cadastra os membros da família.", 403)
        try:
            m = ler_membro(request.get_json(silent=True) or {})
        except ValueError as e:
            return erro(str(e))
        cid = ctx.criar_carteira(f"Carteira {m['nome']}", None)
        conn.execute("INSERT INTO fin_membros (carteira_id, nome, parentesco, divide, nascimento) VALUES (?, ?, ?, ?, ?)",
                     (cid, m["nome"], m["parentesco"], m["divide"], m["nascimento"]))
        salvar_config("membros_configurados", True)
        conn.commit()
        return jsonify({"ok": True, "id": cid}), 201

    @app.put("/api/plan/membros/<int:cid>")
    def plan_editar_membro(cid):
        if not ctx.eh_admin():
            return erro("Apenas o administrador cadastra os membros da família.", 403)
        if cid not in {p["id"] for p in pessoas()}:
            return erro("Membro não encontrado.", 404)
        try:
            m = ler_membro(request.get_json(silent=True) or {})
        except ValueError as e:
            return erro(str(e))
        conn.execute("""INSERT INTO fin_membros (carteira_id, nome, parentesco, divide, nascimento) VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(carteira_id) DO UPDATE SET nome = excluded.nome, parentesco = excluded.parentesco,
                        divide = excluded.divide, nascimento = excluded.nascimento, ativo = 1""",
                     (cid, m["nome"], m["parentesco"], m["divide"], m["nascimento"]))
        salvar_config("membros_configurados", True)
        conn.commit()
        return jsonify({"ok": True})

    @app.post("/api/plan/membros/<int:cid>/trocar")
    def plan_trocar_membros(cid):
        """Troca dois membros de lugar: nomes, parentesco e todo o planejamento (lançamentos, contas fixas,
        cartões, notas, orçamento e categorias aprendidas). Para quando tudo foi lançado no cadastro errado
        (ex.: o login do Edgar cadastrado com o nome da Eliandra). Os investimentos de cada carteira não mudam."""
        if not ctx.eh_admin():
            return erro("Apenas o administrador cadastra os membros da família.", 403)
        try:
            outro = int((request.get_json(silent=True) or {}).get("com"))
        except (TypeError, ValueError):
            return erro("Escolha com quem trocar.")
        ps = {p["id"]: p for p in pessoas()}
        if cid not in ps or outro not in ps or outro == cid:
            return erro("Escolha com quem trocar.")
        temp = -cid  # lugar provisório durante a troca (as chaves estrangeiras são conferidas no fim)
        conn.execute("PRAGMA defer_foreign_keys = ON")
        for tabela in ("fin_lancamentos", "fin_recorrencias", "fin_cartoes", "fin_notas", "fin_orcamento", "fin_regras"):
            conn.execute(f"UPDATE {tabela} SET carteira_id = ? WHERE carteira_id = ?", (temp, cid))
            conn.execute(f"UPDATE {tabela} SET carteira_id = ? WHERE carteira_id = ?", (cid, outro))
            conn.execute(f"UPDATE {tabela} SET carteira_id = ? WHERE carteira_id = ?", (outro, temp))
        a, b = ps[cid], ps[outro]
        for alvo, origem in ((cid, b), (outro, a)):
            conn.execute("""INSERT INTO fin_membros (carteira_id, nome, parentesco, divide, nascimento) VALUES (?, ?, ?, ?, ?)
                            ON CONFLICT(carteira_id) DO UPDATE SET nome = excluded.nome, parentesco = excluded.parentesco,
                            divide = excluded.divide, nascimento = excluded.nascimento, ativo = 1""",
                         (alvo, origem["nome"], origem["parentesco"], 1 if origem["divide"] else 0, origem["nascimento"]))
        salvar_config("membros_configurados", True)
        conn.commit()
        return jsonify({"ok": True})

    @app.delete("/api/plan/membros/<int:cid>")
    def plan_remover_membro(cid):
        """Tira o membro da família. Os lançamentos dele ficam guardados; quem tem login sai em Acessos e conta."""
        if not ctx.eh_admin():
            return erro("Apenas o administrador cadastra os membros da família.", 403)
        p = next((x for x in pessoas() if x["id"] == cid), None)
        if p is None:
            return erro("Membro não encontrado.", 404)
        if p["tem_login"]:
            return erro("Este membro tem login no sistema. Para tirar o acesso dele, use Acessos e conta.")
        conn.execute("""INSERT INTO fin_membros (carteira_id, nome, parentesco, divide, ativo) VALUES (?, ?, ?, 0, 0)
                        ON CONFLICT(carteira_id) DO UPDATE SET ativo = 0, divide = 0""", (cid, p["nome"], p["parentesco"]))
        conn.commit()
        return jsonify({"ok": True})

    # ================================================================ fase 4: objetivos
    CAMPOS_OBJ = ("tipo", "nome", "valor_alvo", "data_alvo", "valor_guardado", "aporte_mensal", "rentabilidade",
                  "renda_desejada", "idade_atual", "idade_alvo", "meses_reserva", "prioridade", "tickers")

    def ler_objetivo(d):
        tipo = d.get("tipo")
        if tipo not in plan.TIPOS_OBJETIVO:
            raise ValueError("Escolha o tipo do objetivo.")
        nome = (d.get("nome") or "").strip()[:80] or plan.TIPOS_OBJETIVO[tipo]
        def num(k, inteiro=False):
            v = d.get(k)
            if v in (None, ""):
                return None
            v = numero(v, "um número")
            if v < 0:
                raise ValueError("Os valores não podem ser negativos.")
            return int(v) if inteiro else v
        data_alvo = (d.get("data_alvo") or "")[:10] or None
        if data_alvo:
            if len(data_alvo) == 7:
                data_alvo += "-01"
            try:
                dt.date.fromisoformat(data_alvo)
            except ValueError:
                raise ValueError("Data do objetivo inválida.") from None
        o = {"tipo": tipo, "nome": nome, "valor_alvo": num("valor_alvo"), "data_alvo": data_alvo,
             "valor_guardado": num("valor_guardado") or 0, "aporte_mensal": num("aporte_mensal") or 0,
             "rentabilidade": num("rentabilidade") if d.get("rentabilidade") not in (None, "") else 4,
             "renda_desejada": num("renda_desejada"), "idade_atual": num("idade_atual", True),
             "idade_alvo": num("idade_alvo", True), "meses_reserva": num("meses_reserva", True),
             "prioridade": num("prioridade", True) or 2,
             "tickers": ",".join(sorted({t.strip().upper() for t in (d.get("tickers") or []) if str(t).strip()}))
             if isinstance(d.get("tickers"), list) else (d.get("tickers") or "").upper()}
        if o["rentabilidade"] > 30:
            raise ValueError("Rentabilidade real acima de 30% ao ano não é realista.")
        if tipo in ("aposentadoria", "renda_passiva") and not (o["renda_desejada"] or o["valor_alvo"]):
            raise ValueError("Informe a renda mensal desejada.")
        if tipo not in ("reserva", "aposentadoria", "renda_passiva") and not o["valor_alvo"]:
            raise ValueError("Informe o valor do objetivo.")
        if tipo == "aposentadoria" and not o["data_alvo"] and not (o["idade_atual"] and o["idade_alvo"]):
            raise ValueError("Informe a idade atual e a idade em que quer se aposentar (ou a data).")
        return o

    def custo_vida(cids):
        marcas = ",".join("?" * len(cids))
        desp = {row["m"]: row["v"] for row in conn.execute(
            f"""SELECT substr(data, 1, 7) AS m, SUM(valor) AS v FROM fin_lancamentos
                WHERE tipo = 'despesa' AND carteira_id IN ({marcas}) GROUP BY m""", cids)}
        cv = plan.custo_de_vida(desp, mes_atual())
        # ainda sem mês fechado: usa as despesas lançadas no mês atual como estimativa
        return cv if cv is not None else (desp.get(mes_atual()) or None)

    def avaliar_todos(cids):
        marcas = ",".join("?" * len(cids))
        objs = db.rows(conn.execute(
            f"SELECT * FROM fin_objetivos WHERE carteira_id IN ({marcas}) ORDER BY prioridade, id", cids))
        valores = ctx.valores_ativos(cids) if objs else {}
        cv = custo_vida(cids)
        return [plan.avaliar_objetivo(o, valores, cv, ctx.hoje()) for o in objs], cv

    @app.get("/api/plan/objetivos")
    def plan_objetivos():
        cids = cids_plan()
        objs, cv = avaliar_todos(cids)
        # sobra média dos últimos 3 meses fechados, para comparar com o aporte necessário
        cats, prov = categorias(), plan.proventos_por_mes(ctx.listar_proventos(cids), ctx.hoje())
        inv = plan.investido_por_mes(ctx.listar_aportes(cids))
        sobras = []
        for k in (1, 2, 3):
            m = plan.somar_meses(mes_atual(), -k)
            r = plan.resumo_mes(lancamentos_do_mes(cids, m), cats, m, prov.get(m, 0.0), inv.get(m, 0.0))
            if r["receitas"] or r["despesas"]:
                sobras.append(r["sobra"] + r["investido"])  # o que sobrou antes de investir
        ativos = sorted(ctx.valores_ativos(cids).items(), key=lambda x: -x[1])
        pendentes = [o for o in objs if o["situacao"] not in ("atingido", "incompleto")]
        return jsonify({"objetivos": objs, "tipos": plan.TIPOS_OBJETIVO, "custo_de_vida": cv,
                        "sobra_media": sum(sobras) / len(sobras) if sobras else None,
                        "total_necessario": sum(o["aporte_necessario"] or 0 for o in pendentes),
                        "total_planejado": sum(o["aporte_planejado"] for o in pendentes),
                        "ativos": [{"ticker": t, "valor": v} for t, v in ativos if v > 0]})

    @app.post("/api/plan/objetivos")
    def plan_criar_objetivo():
        cid = ctx.carteira_atual("editar")
        try:
            o = ler_objetivo(request.get_json(silent=True) or {})
        except ValueError as e:
            return erro(str(e))
        cur = conn.execute(
            f"INSERT INTO fin_objetivos (carteira_id, criado_em, {', '.join(CAMPOS_OBJ)}) VALUES (?, ?, {', '.join('?' * len(CAMPOS_OBJ))})",
            (cid, ctx.hoje(), *[o[k] for k in CAMPOS_OBJ]))
        conn.commit()
        return jsonify({"ok": True, "id": cur.lastrowid}), 201

    @app.put("/api/plan/objetivos/<int:oid>")
    def plan_editar_objetivo(oid):
        cid = ctx.carteira_atual("editar")
        if not conn.execute("SELECT 1 FROM fin_objetivos WHERE id = ? AND carteira_id = ?", (oid, cid)).fetchone():
            return erro("Objetivo não encontrado.", 404)
        try:
            o = ler_objetivo(request.get_json(silent=True) or {})
        except ValueError as e:
            return erro(str(e))
        conn.execute(f"UPDATE fin_objetivos SET {', '.join(f'{k} = ?' for k in CAMPOS_OBJ)} WHERE id = ?",
                     (*[o[k] for k in CAMPOS_OBJ], oid))
        conn.commit()
        return jsonify({"ok": True})

    @app.delete("/api/plan/objetivos/<int:oid>")
    def plan_excluir_objetivo(oid):
        cid = ctx.carteira_atual("editar")
        conn.execute("DELETE FROM fin_objetivos WHERE id = ? AND carteira_id = ?", (oid, cid))
        conn.commit()
        return jsonify({"ok": True})

    # ================================================================ fase 5: orçamento, projeção e IR
    def gastos_por_grupo(cids, mes):
        cats = categorias()
        out = {}
        for l in lancamentos_do_mes(cids, mes):
            if l["tipo"] == "despesa":
                g = cats[l["categoria_id"]]["grupo"] if l["categoria_id"] in cats else "Sem categoria"
                out[g] = out.get(g, 0.0) + l["valor"]
        return out

    def limites(cids):
        marcas = ",".join("?" * len(cids))
        out = {}
        for r in conn.execute(f"SELECT grupo, limite FROM fin_orcamento WHERE carteira_id IN ({marcas})", cids):
            out[r["grupo"]] = out.get(r["grupo"], 0.0) + r["limite"]
        return out

    def orcamento_do_mes(cids, mes):
        gasto, lim = gastos_por_grupo(cids, mes), limites(cids)
        medias = {}
        for k in (1, 2, 3):
            for g, v in gastos_por_grupo(cids, plan.somar_meses(mes, -k)).items():
                medias[g] = medias.get(g, 0.0) + v / 3
        h = dt.date.fromisoformat(ctx.hoje())
        fracao = None
        if mes == mes_atual():
            fracao = h.day / plan.calendar.monthrange(h.year, h.month)[1]
        grupos = [g for g in dict.fromkeys(
            [c["grupo"] for c in categorias().values() if c["tipo"] == "despesa" and c["ativa"]] + list(gasto))]
        itens = [{"grupo": g, "media_3m": medias.get(g, 0.0),
                  **plan.situacao_orcamento(lim.get(g, 0.0), gasto.get(g, 0.0), fracao)} for g in grupos]
        return {"mes": mes, "itens": itens, "fracao_mes": fracao,
                "total_limite": sum(lim.values()), "total_gasto": sum(gasto.values())}

    @app.get("/api/plan/orcamento")
    def plan_orcamento():
        return jsonify(orcamento_do_mes(cids_plan(), mes_param()))

    @app.put("/api/plan/orcamento")
    def plan_salvar_orcamento():
        cid = ctx.carteira_atual("editar")
        d = request.get_json(silent=True) or {}
        try:
            itens = {str(g)[:40]: numero(v, "um limite") for g, v in (d.get("limites") or {}).items() if v not in (None, "")}
        except ValueError as e:
            return erro(str(e))
        conn.execute("DELETE FROM fin_orcamento WHERE carteira_id = ?", (cid,))
        for g, v in itens.items():
            if v > 0:
                conn.execute("INSERT INTO fin_orcamento (carteira_id, grupo, limite) VALUES (?, ?, ?)", (cid, g, v))
        conn.commit()
        return jsonify({"ok": True})

    @app.get("/api/plan/projecao")
    def plan_projecao():
        """Próximos meses: receitas e despesas já previstas (fixas e parcelas) e o aporte planejado nos objetivos."""
        cids = cids_plan()
        plan.materializar(conn, cids, mes_atual())
        objs, _ = avaliar_todos(cids)
        aporte_obj = sum(o["aporte_planejado"] for o in objs if o["situacao"] != "atingido")
        meses, acumulado = [], 0.0
        for k in range(12):
            m = plan.somar_meses(mes_atual(), k)
            lancs = lancamentos_do_mes(cids, m)
            rec = sum(l["valor"] for l in lancs if l["tipo"] == "receita")
            desp = sum(l["valor"] for l in lancs if l["tipo"] == "despesa")
            parcelas = sum(l["valor"] for l in lancs if l["tipo"] == "despesa" and l.get("parcela_total"))
            saldo = rec - desp - aporte_obj
            acumulado += saldo
            meses.append({"mes": m, "receitas": rec, "despesas": desp, "parcelas": parcelas, "aporte_objetivos": aporte_obj,
                          "saldo": saldo, "acumulado": acumulado})
        return jsonify({"meses": meses, "aporte_objetivos": aporte_obj})

    @app.get("/api/plan/ir")
    def plan_ir():
        """Totais do ano para a declaração: rendimentos do trabalho e despesas que costumam ser dedutíveis."""
        cids = cids_plan()
        try:
            ano = int(request.args.get("ano") or ctx.hoje()[:4])
        except ValueError:
            return erro("Ano inválido.")
        cats = categorias()
        marcas = ",".join("?" * len(cids))
        lancs = db.rows(conn.execute(
            f"SELECT * FROM fin_lancamentos WHERE carteira_id IN ({marcas}) AND substr(data, 1, 4) = ?",
            [*cids, str(ano)]))
        bruto = liquido = 0.0
        dedut = {}
        for l in lancs:
            c = cats.get(l["categoria_id"])
            if l["tipo"] == "receita" and c and c["grupo"] == "Trabalho":
                bruto += l["valor_bruto"] or l["valor"]
                liquido += l["valor"]
            if l["tipo"] == "despesa" and c and c["nome"] in plan.DEDUTIVEIS_IR:
                chave = (plan.DEDUTIVEIS_IR[c["nome"]], c["nome"])
                dedut[chave] = dedut.get(chave, 0.0) + l["valor"]
        return jsonify({"ano": ano, "rendimentos_brutos": bruto, "rendimentos_liquidos": liquido,
                        "descontos": bruto - liquido,
                        "dedutiveis": [{"grupo": g, "categoria": n, "valor": v} for (g, n), v in sorted(dedut.items())]})

    # ================================================================ nota fiscal (NFC-e) pelo QR Code
    def nota_ja_lancada(chave):
        cids = cids_plan()
        marcas = ",".join("?" * len(cids))
        r = conn.execute(f"""SELECT n.id, n.criado_em, MIN(l.data) AS data, SUM(l.valor) AS valor FROM fin_notas n
                             LEFT JOIN fin_lancamentos l ON l.nota_id = n.id
                             WHERE n.chave = ? AND n.carteira_id IN ({marcas}) GROUP BY n.id""", [chave, *cids]).fetchone()
        return dict(r) if r else None

    @app.post("/api/plan/nfce/ler")
    def plan_nfce_ler():
        """Lê uma ou mais notas: textos do QR Code (lidos no celular) e/ou fotos (lidas aqui)."""
        cid = cid_escrita()
        d = request.get_json(silent=True) or {}
        entradas = [("texto", t, None) for t in (d.get("textos") or request.form.getlist("texto")) if str(t).strip()]
        for arq in request.files.getlist("foto"):
            if arq and arq.filename:
                entradas.append(("foto", arq.read(), arq.filename))
        if not entradas:
            return erro("Tire uma foto do QR Code do cupom ou cole o link / a chave da nota.")
        if len(entradas) > 20:
            return erro("Envie até 20 notas por vez.")
        abrir = app.config.get("nfce_abrir")  # nos testes, uma página de exemplo no lugar do portal
        regras, por_nome = regras_usuario(cid), categorias_por_nome()
        notas, falhas, vistas = [], [], set()
        for tipo, valor, nome in entradas:
            origem = nome or (str(valor)[:60] + ("…" if len(str(valor)) > 60 else ""))
            try:
                texto = nfce.ler_qrcode_da_foto(valor) if tipo == "foto" else str(valor)
                chave = nfce.ler_qrcode(texto)["chave"]
                if chave in vistas:
                    continue  # duas fotos do mesmo cupom
                vistas.add(chave)
                n = nfce.consultar(texto, abrir)
            except nfce.ErroNota as e:
                falhas.append({"origem": origem, "motivo": str(e)})
                continue
            n["categoria_id"], n["origem_categoria"] = nfce.sugerir_categoria(n, regras, por_nome, fat.sugerir_categoria)
            n["combustivel"] = nfce.resumo_combustivel(n)
            n["ja_lancada"] = nota_ja_lancada(n["chave"])
            n["arquivo"] = nome
            notas.append(n)
        return jsonify({"notas": notas, "falhas": falhas})

    @app.post("/api/plan/nfce/confirmar")
    def plan_nfce_confirmar():
        """Cria o(s) lançamento(s) da nota: um por forma de pagamento (ex.: parte no cartão, parte em dinheiro)."""
        d = request.get_json(silent=True) or {}
        cid = cid_escrita(d.get("carteira_id"))
        chave = re.sub(r"\s", "", str(d.get("chave") or "")).upper()
        if not nfce.chave_valida(chave):
            return erro("Chave de acesso da nota inválida.")
        if nota_ja_lancada(chave) and not d.get("forcar"):
            return erro("Esta nota já foi lançada.", 409)
        pags = [p for p in (d.get("pagamentos") or []) if p and str(p.get("valor") or "").strip() not in ("", "0")]
        if not pags:
            return erro("Informe o valor pago.")
        lancs = []
        for p in pags:
            try:
                l = ler_lancamento({"tipo": "despesa", "data": d.get("data"), "descricao": d.get("descricao"),
                                    "valor": p.get("valor"), "categoria_id": d.get("categoria_id"),
                                    "forma": p.get("forma"), "cartao_id": p.get("cartao_id"),
                                    "compartilhado": d.get("compartilhado"), "pago": True})
            except ValueError as e:
                return erro(str(e))
            if l["valor"] <= 0:
                continue
            if l["forma"] == "credito":
                l["cartao_id"] = cartao_valido(cid, l["cartao_id"])
                if not l["cartao_id"]:
                    return erro("Escolha o cartão de crédito usado nesta compra (é ele que confere com a fatura).")
            lancs.append(l)
        if not lancs:
            return erro("Informe o valor pago.")
        itens = [{k: i.get(k) for k in ("descricao", "qtd", "un", "unitario", "valor")}
                 for i in (d.get("itens") or [])[:300] if isinstance(i, dict)]
        url = d.get("url") if nfce.host_permitido(d.get("url") or "") else None
        conn.execute("""INSERT INTO fin_notas (carteira_id, chave, emitente, cnpj, emissao, total, itens, url)
                        VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(carteira_id, chave) DO UPDATE SET
                        emitente = excluded.emitente, itens = excluded.itens, total = excluded.total""",
                     (cid, chave, (d.get("emitente") or "")[:120] or None, (d.get("cnpj") or "")[:14] or None,
                      (d.get("emissao") or "")[:16] or None, d.get("total"), json.dumps(itens, ensure_ascii=False), url))
        nota_id = conn.execute("SELECT id FROM fin_notas WHERE carteira_id = ? AND chave = ?", (cid, chave)).fetchone()[0]
        ids = []
        for l in lancs:
            cur = conn.execute(
                """INSERT INTO fin_lancamentos (carteira_id, tipo, data, descricao, categoria_id, valor, forma, pago, obs,
                   cartao_id, compartilhado, nota_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (cid, "despesa", l["data"], l["descricao"], l["categoria_id"], l["valor"], l["forma"], 1,
                 f"NFC-e {int(chave[25:34])}", l["cartao_id"], l["compartilhado"], nota_id))
            ids.append(cur.lastrowid)
        est = fat.chave_estabelecimento(d.get("emitente") or "")
        if lancs[0]["categoria_id"] and est:  # aprende: próxima nota (ou fatura) desta loja já vem com a categoria
            conn.execute("""INSERT INTO fin_regras (carteira_id, padrao, categoria_id) VALUES (?, ?, ?)
                            ON CONFLICT(carteira_id, padrao) DO UPDATE SET categoria_id = excluded.categoria_id,
                            usos = usos + 1""", (cid, est, lancs[0]["categoria_id"]))
        conn.commit()
        return jsonify({"ok": True, "ids": ids, "nota_id": nota_id,
                        "aguardando_fatura": sum(1 for l in lancs if l["forma"] == "credito")}), 201

    @app.get("/api/plan/notas/<int:nid>")
    def plan_nota(nid):
        n = conn.execute("SELECT * FROM fin_notas WHERE id = ?", (nid,)).fetchone()
        if n is None or n["carteira_id"] not in cids_plan():
            return erro("Nota não encontrada.", 404)
        n = dict(n)
        n["itens"] = json.loads(n["itens"] or "[]")
        n["cnpj_formatado"] = nfce.formatar_cnpj(n["cnpj"])
        return jsonify(n)

    # ================================================================ alertas (sino e Telegram)
    def alertas_planejamento(cids, hoje):
        if not licenca.modulo_ativo(MODULO):
            return []
        if not preparado["ok"]:
            plan.preparar(conn)
            preparado["ok"] = True
        out = []
        chave = ",".join(map(str, cids))
        mes = hoje[:7]
        marcas = ",".join("?" * len(cids))
        limite3 = (dt.date.fromisoformat(hoje) + dt.timedelta(days=3)).isoformat()
        for l in db.rows(conn.execute(
                f"""SELECT * FROM fin_lancamentos WHERE carteira_id IN ({marcas}) AND tipo = 'despesa' AND pago = 0
                    AND data <= ? AND cartao_id IS NULL ORDER BY data""", [*cids, limite3])):
            vencida = l["data"] < hoje
            out.append({"tipo": "conta", "nivel": "alerta",
                        "titulo": f"{l['descricao']}: {'vencida' if vencida else 'vence'} em {'/'.join(reversed(l['data'].split('-')))}",
                        "texto": f"Conta de R$ {l['valor']:,.2f} ainda não marcada como paga.".replace(",", "X").replace(".", ",").replace("X", "."),
                        "chave": f"{chave}:conta:{l['id']}:{'vencida' if vencida else 'vence'}"})
        limite_fatura = (dt.date.fromisoformat(hoje) - dt.timedelta(days=70)).isoformat()
        for l in db.rows(conn.execute(
                f"""SELECT l.*, c.nome AS cartao FROM fin_lancamentos l JOIN fin_cartoes c ON c.id = l.cartao_id
                    WHERE l.carteira_id IN ({marcas}) AND l.tipo = 'despesa' AND l.chave_import IS NULL
                    AND l.data <= ? AND l.parcela_total IS NULL""", [*cids, limite_fatura])):
            out.append({"tipo": "conta", "nivel": "info",
                        "titulo": f"{l['descricao']} ({l['cartao']}) não apareceu nas faturas",
                        "texto": "Compra lançada há mais de dois meses e ainda não conferida com a fatura. "
                                 "Verifique se foi cancelada ou se a fatura foi importada.",
                        "chave": f"{chave}:cartao-pendente:{l['id']}"})
        for cartao in listar_cartoes(cids):
            for a in alertas_do_cartao(cartao, faturas_do_cartao(cartao, hoje, 4), hoje):
                out.append({"tipo": "cartao", "nivel": a["nivel"], "titulo": a["titulo"], "texto": a["texto"],
                            "chave": f"{chave}:cartao:{cartao['id']}:{a['chave']}"})
        orc = orcamento_do_mes(cids, mes)
        for i in orc["itens"]:
            if i["estado"] in ("atencao", "estourado"):
                pct = round(i["pct"])
                out.append({"tipo": "orcamento", "nivel": "alerta" if i["estado"] == "estourado" else "info",
                            "titulo": f"{i['grupo']}: {pct}% do orçamento do mês",
                            "texto": ("Limite ultrapassado." if i["estado"] == "estourado" else "Mais de 80% do limite já foi gasto.")
                            + f" Gasto R$ {i['gasto']:,.2f} de R$ {i['limite']:,.2f}.".replace(",", "X").replace(".", ",").replace("X", "."),
                            "chave": f"{chave}:orcamento:{mes}:{i['grupo']}:{i['estado']}"})
        return out

    app.config.setdefault("provedores_alertas", []).append(alertas_planejamento)
