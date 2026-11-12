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

    def do_usuario(lid, cid):
        row = conn.execute("SELECT * FROM fin_lancamentos WHERE id = ? AND carteira_id = ?", (lid, cid)).fetchone()
        if row is None:
            raise ctx.ErroAcesso("Lançamento não encontrado.", 404)
        return dict(row)

    def cartao_valido(cid, cartao_id):
        if not cartao_id:
            return None
        ok = conn.execute("SELECT 1 FROM fin_cartoes WHERE id = ? AND carteira_id = ?", (cartao_id, cid)).fetchone()
        return cartao_id if ok else None

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
        cartao = d.get("cartao_id")
        cartao = int(cartao) if forma == "credito" and str(cartao or "").isdigit() else None
        return {"tipo": tipo, "data": data, "descricao": descricao, "valor": round(valor, 2),
                "valor_bruto": round(bruto, 2) if bruto is not None and tipo == "receita" else None,
                "categoria_id": cat, "forma": forma, "pago": 1 if d.get("pago", True) else 0, "cartao_id": cartao,
                "compartilhado": 1 if d.get("compartilhado") and tipo == "despesa" else 0}

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

    # ---------- cartões ----------
    def listar_cartoes(cids):
        marcas = ",".join("?" * len(cids))
        return db.rows(conn.execute(
            f"SELECT * FROM fin_cartoes WHERE carteira_id IN ({marcas}) AND ativo = 1 ORDER BY nome", cids))

    @app.get("/api/plan/cartoes")
    def plan_cartoes():
        return jsonify(listar_cartoes(ctx.carteiras_leitura()))

    @app.post("/api/plan/cartoes")
    def plan_criar_cartao():
        cid = ctx.carteira_atual("editar")
        d = request.get_json(silent=True) or {}
        nome = (d.get("nome") or "").strip()[:40]
        try:
            dia = int(d.get("dia_vencimento") or 0) or None
        except ValueError:
            dia = None
        if not nome:
            return erro("Informe o nome do cartão (ex.: Nubank, Itaú Visa).")
        if dia is not None and not 1 <= dia <= 31:
            return erro("Dia de vencimento inválido.")
        cur = conn.execute("INSERT INTO fin_cartoes (carteira_id, nome, dia_vencimento) VALUES (?, ?, ?)", (cid, nome, dia))
        conn.commit()
        return jsonify({"ok": True, "id": cur.lastrowid}), 201

    @app.delete("/api/plan/cartoes/<int:cartao_id>")
    def plan_excluir_cartao(cartao_id):
        """Desativa o cartão (os lançamentos continuam, sem perder o histórico)."""
        cid = ctx.carteira_atual("editar")
        conn.execute("UPDATE fin_cartoes SET ativo = 0 WHERE id = ? AND carteira_id = ?", (cartao_id, cid))
        conn.commit()
        return jsonify({"ok": True})

    # ---------- importação de fatura ----------
    def regras_usuario(cid):
        rows = conn.execute("SELECT padrao, categoria_id FROM fin_regras WHERE carteira_id = ?", (cid,)).fetchall()
        return sorted(((r["padrao"], r["categoria_id"]) for r in rows), key=lambda x: -len(x[0]))

    def categorias_por_nome():
        return {(c["tipo"], c["nome"]): c["id"] for c in categorias().values() if c["ativa"]}

    @app.post("/api/plan/fatura/previa")
    def plan_fatura_previa():
        cid = ctx.carteira_atual("editar")
        arq = request.files.get("arquivo")
        if not arq or not arq.filename:
            return erro("Selecione o arquivo da fatura.")
        cartao_id = cartao_valido(cid, int(request.form.get("cartao_id") or 0))
        if not cartao_id:
            return erro("Escolha o cartão desta fatura.")
        try:
            itens = fat.ler_fatura(arq.read(), arq.filename, request.form.get("senha") or None)  # senha não é guardada
        except ErroImportacao as e:
            return erro(str(e))
        regras, por_nome = regras_usuario(cid), categorias_por_nome()
        chaves = {r["chave_import"] for r in conn.execute(
            "SELECT chave_import FROM fin_lancamentos WHERE carteira_id = ? AND chave_import IS NOT NULL", (cid,))}
        for it in itens:
            it["chave"] = fat.chave_importacao(cartao_id, it)
            it["ja_importado"] = it["chave"] in chaves
            it["categoria_id"], it["origem_categoria"] = sugerir_categoria_item(it, regras, por_nome)
            it["categoria_sugerida"] = it["categoria_id"]
            it["marcado"] = it["tipo"] != "pagamento" and not it["ja_importado"]
        compras = [i for i in itens if i["tipo"] in ("compra", "tarifa")]
        return jsonify({
            "itens": itens, "cartao_id": cartao_id,
            "resumo": {"compras": len(compras), "total": round(sum(i["valor"] for i in compras), 2),
                       "estornos": round(sum(i["valor"] for i in itens if i["tipo"] == "estorno"), 2),
                       "ja_importados": sum(1 for i in itens if i["ja_importado"]),
                       "categorizados": sum(1 for i in compras if i["categoria_id"]),
                       "parceladas": sum(1 for i in compras if i["parcela_total"])}})

    def sugerir_categoria_item(it, regras, por_nome):
        if it["tipo"] == "pagamento":
            return None, None
        return fat.sugerir_categoria(it, regras, por_nome)

    @app.post("/api/plan/fatura/confirmar")
    def plan_fatura_confirmar():
        cid = ctx.carteira_atual("editar")
        d = request.get_json(silent=True) or {}
        cartao_id = cartao_valido(cid, int(d.get("cartao_id") or 0))
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
        criados, futuras_criadas, aprendidas = 0, 0, 0

        def inserir(tipo, data, desc, cat, valor, chave, pago, grupo=None, num=None, total=None):
            conn.execute(
                """INSERT INTO fin_lancamentos (carteira_id, tipo, data, descricao, categoria_id, valor, forma, pago,
                   parcela_grupo, parcela_num, parcela_total, cartao_id, chave_import)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (cid, tipo, data, desc, cat, valor, "credito", pago, grupo, num, total, cartao_id, chave))
            chaves.add(chave)

        for it in d.get("itens") or []:
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
            if not chave or chave in chaves:
                continue
            data_lanc = vencimento if vencimento else data
            num, total = it.get("parcela_num"), it.get("parcela_total")
            grupo = chave[2:].split("#")[0] if chave.startswith("p:") else None
            inserir(tipo, data_lanc, str(it.get("descricao") or "")[:120] or "Compra no cartão", cat, valor, chave, 1,
                    grupo, num, total)
            criados += 1
            if grupo and futuras and num and total and num < total:
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
                        "regras_aprendidas": aprendidas}), 201

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
        carteiras = ctx.carteiras_visiveis()
        cids = [c["id"] for c in carteiras]
        plan.materializar(conn, cids, mes_atual())
        modo, pesos = config("modo_familia", "proporcional"), config("pesos_familia", {})
        pessoas, totais = [], {"receitas": 0.0, "despesas": 0.0, "compartilhadas": 0.0}
        prov = plan.proventos_por_mes(ctx.listar_proventos(cids), ctx.hoje()) if cids else {}
        inv = plan.investido_por_mes(ctx.listar_aportes(cids)) if cids else {}
        for c in carteiras:
            lancs = lancamentos_do_mes([c["id"]], mes)
            renda = sum(l["valor"] for l in lancs if l["tipo"] == "receita")
            desp = sum(l["valor"] for l in lancs if l["tipo"] == "despesa")
            comum = sum(l["valor"] for l in lancs if l["tipo"] == "despesa" and l.get("compartilhado"))
            pessoas.append({"id": c["id"], "nome": c.get("dono_nome") or c["nome"], "carteira": c["nome"],
                            "renda": renda, "pagou": comum, "despesas_pessoais": desp - comum})
            totais["receitas"] += renda
            totais["despesas"] += desp
            totais["compartilhadas"] += comum
        acerto = plan.acerto_familia(pessoas, modo, pesos)
        investido, proventos = inv.get(mes, 0.0), prov.get(mes, 0.0)
        totais.update({"investido": investido, "proventos": proventos,
                       "sobra": totais["receitas"] + proventos - totais["despesas"] - investido})
        return jsonify({"mes": mes, "modo": modo, "modos": plan.MODOS_FAMILIA, "pesos": pesos, "totais": totais,
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
        cids = ctx.carteiras_leitura()
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
        return jsonify(orcamento_do_mes(ctx.carteiras_leitura(), mes_param()))

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
        cids = ctx.carteiras_leitura()
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
        cids = ctx.carteiras_leitura()
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
