"""Rotas da API do módulo adicional Planejamento financeiro (/api/plan/...).

Registradas pelo app base com `registrar(app, ctx)`. Todas respondem 403 quando o módulo não
está ativo na licença (ver carteira/licenca.py).
"""
import datetime as dt

from flask import jsonify, request

from . import db, licenca
from . import planejamento as plan

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

    def do_usuario(lid, cid):
        row = conn.execute("SELECT * FROM fin_lancamentos WHERE id = ? AND carteira_id = ?", (lid, cid)).fetchone()
        if row is None:
            raise ctx.ErroAcesso("Lançamento não encontrado.", 404)
        return dict(row)

    def numero(v, campo):
        try:
            return float(str(v).replace(".", "").replace(",", ".")) if isinstance(v, str) and "," in v else float(v)
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
        return {"tipo": tipo, "data": data, "descricao": descricao, "valor": round(valor, 2),
                "valor_bruto": round(bruto, 2) if bruto is not None and tipo == "receita" else None,
                "categoria_id": cat, "forma": forma, "pago": 1 if d.get("pago", True) else 0}

    # ---------- categorias ----------
    @app.get("/api/plan/categorias")
    def plan_categorias():
        cats = db.rows(conn.execute("SELECT * FROM fin_categorias WHERE ativa = 1 ORDER BY tipo, ordem, grupo, nome"))
        return jsonify({"categorias": cats, "formas": plan.FORMAS})

    @app.post("/api/plan/categorias")
    def plan_criar_categoria():
        ctx.carteira_atual("editar")
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
        cids = ctx.carteiras_leitura()
        mes = mes_param()
        plan.materializar(conn, cids, mes_atual())
        marcas = ",".join("?" * len(cids))
        recs = db.rows(conn.execute(
            f"SELECT * FROM fin_recorrencias WHERE carteira_id IN ({marcas}) ORDER BY tipo DESC, descricao", cids))
        return jsonify({"mes": mes, "mes_atual": mes_atual(), "lancamentos": lancamentos_do_mes(cids, mes),
                        "recorrencias": recs})

    @app.post("/api/plan/lancamentos")
    def plan_criar_lancamento():
        cid = ctx.carteira_atual("editar")
        d = request.get_json(silent=True) or {}
        try:
            l = ler_lancamento(d)
        except ValueError as e:
            return erro(str(e))
        repetir = d.get("repetir") or "nao"
        if repetir == "mensal":
            fim = (d.get("fim") or "")[:7] or None
            if fim and fim < plan.mes_de(l["data"]):
                return erro("O mês final da repetição é anterior ao primeiro lançamento.")
            cur = conn.execute(
                """INSERT INTO fin_recorrencias (carteira_id, tipo, descricao, categoria_id, valor, valor_bruto, dia,
                   inicio, fim, forma) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (cid, l["tipo"], l["descricao"], l["categoria_id"], l["valor"], l["valor_bruto"],
                 int(l["data"][8:10]), plan.mes_de(l["data"]), fim, l["forma"]))
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
                       parcela_grupo, parcela_num, parcela_total) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (cid, l["tipo"], data, l["descricao"], l["categoria_id"], valor, l["forma"],
                     1 if data <= ctx.hoje() else 0, grupo, num, n))
            conn.commit()
            return jsonify({"ok": True, "parcelas": n}), 201
        cur = conn.execute(
            """INSERT INTO fin_lancamentos (carteira_id, tipo, data, descricao, categoria_id, valor, valor_bruto, forma,
               pago, obs) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (cid, l["tipo"], l["data"], l["descricao"], l["categoria_id"], l["valor"], l["valor_bruto"], l["forma"],
             l["pago"], (d.get("obs") or "")[:200] or None))
        conn.commit()
        return jsonify({"ok": True, "id": cur.lastrowid}), 201

    @app.put("/api/plan/lancamentos/<int:lid>")
    def plan_editar_lancamento(lid):
        cid = ctx.carteira_atual("editar")
        atual = do_usuario(lid, cid)
        d = request.get_json(silent=True) or {}
        if set(d) <= {"pago"}:  # só marcar como pago/recebido
            conn.execute("UPDATE fin_lancamentos SET pago = ? WHERE id = ?", (1 if d.get("pago") else 0, lid))
            conn.commit()
            return jsonify({"ok": True})
        try:
            l = ler_lancamento({**atual, **d, "tipo": atual["tipo"]})
        except ValueError as e:
            return erro(str(e))
        conn.execute("""UPDATE fin_lancamentos SET data = ?, descricao = ?, categoria_id = ?, valor = ?, valor_bruto = ?,
                        forma = ?, pago = ? WHERE id = ?""",
                     (l["data"], l["descricao"], l["categoria_id"], l["valor"], l["valor_bruto"], l["forma"],
                      l["pago"], lid))
        if d.get("atualizar_proximos") and atual["recorrencia_id"]:
            # muda também os próximos meses: o modelo da recorrência e as ocorrências futuras ainda não pagas
            conn.execute("""UPDATE fin_recorrencias SET descricao = ?, categoria_id = ?, valor = ?, valor_bruto = ?,
                            forma = ? WHERE id = ? AND carteira_id = ?""",
                         (l["descricao"], l["categoria_id"], l["valor"], l["valor_bruto"], l["forma"],
                          atual["recorrencia_id"], cid))
            conn.execute("""UPDATE fin_lancamentos SET descricao = ?, categoria_id = ?, valor = ?, valor_bruto = ?,
                            forma = ? WHERE recorrencia_id = ? AND data > ? AND pago = 0""",
                         (l["descricao"], l["categoria_id"], l["valor"], l["valor_bruto"], l["forma"],
                          atual["recorrencia_id"], l["data"]))
        conn.commit()
        return jsonify({"ok": True})

    @app.delete("/api/plan/lancamentos/<int:lid>")
    def plan_excluir_lancamento(lid):
        cid = ctx.carteira_atual("editar")
        atual = do_usuario(lid, cid)
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
        conn.commit()
        return jsonify({"ok": True, "removidos": removidos})

    @app.delete("/api/plan/recorrencias/<int:rid>")
    def plan_encerrar_recorrencia(rid):
        """Encerra uma conta/receita recorrente: os meses já lançados ficam; os próximos deixam de existir."""
        cid = ctx.carteira_atual("editar")
        r = conn.execute("SELECT * FROM fin_recorrencias WHERE id = ? AND carteira_id = ?", (rid, cid)).fetchone()
        if r is None:
            return erro("Recorrência não encontrada.", 404)
        fim = mes_atual()
        conn.execute("DELETE FROM fin_lancamentos WHERE recorrencia_id = ? AND substr(data, 1, 7) > ?", (rid, fim))
        if r["inicio"] > fim:
            conn.execute("DELETE FROM fin_recorrencias WHERE id = ?", (rid,))
        else:
            conn.execute("UPDATE fin_recorrencias SET fim = ? WHERE id = ?", (fim, rid))
        conn.commit()
        return jsonify({"ok": True})

    # ---------- resumo ----------
    @app.get("/api/plan/resumo")
    def plan_resumo():
        cids = ctx.carteiras_leitura()
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
        return jsonify({**atual, "anterior": {k: anterior[k] for k in ("receitas", "despesas", "investido", "sobra")},
                        "serie": serie, "custo_de_vida": plan.custo_de_vida(desp_mes, mes_atual()),
                        "mes_atual": mes_atual(), "vazio": not tem_lancamentos})
