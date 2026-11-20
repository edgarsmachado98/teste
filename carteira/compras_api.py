"""API do módulo Compras (licenciado à parte). Integra com o Planejamento quando os dois estão ativos:
notas lançadas lá entram no histórico de compras, e uma compra registrada aqui pode virar despesa lá."""
import datetime as dt

from flask import jsonify, request

from . import compras as cmp
from . import db, licenca, nfce

MODULO = "compras"


def registrar(app, ctx):
    """ctx: conn, erro, carteiras_visiveis, usuario_id, hoje, ErroAcesso."""
    conn, erro = ctx.conn, ctx.erro
    preparado = {"ok": False}

    def preparar():
        if not preparado["ok"]:
            cmp.preparar(conn)
            cmp.importar_notas_do_planejamento(conn)
            preparado["ok"] = True

    @app.before_request
    def _modulo_compras():
        if not request.path.startswith("/api/compras/"):
            return None
        if not licenca.modulo_ativo(MODULO):
            return jsonify({"erro": "O módulo Compras não está incluído na licença desta instalação.", "modulo": MODULO}), 403
        preparar()
        return None

    # nota lançada no Planejamento -> histórico de compras (quando o módulo Compras está ativo)
    def ao_lancar_nota(carteira_id, nota):
        if not licenca.modulo_ativo(MODULO):
            return
        preparar()
        cmp.registrar_compra(conn, carteira_id, nota)
    app.config.setdefault("ganchos_nota", []).append(ao_lancar_nota)

    def cids():
        """A família toda: compras e lista são da casa."""
        ids = [c["id"] for c in ctx.carteiras_visiveis()]
        if not ids:
            raise ctx.ErroAcesso("Nenhuma carteira disponível.", 404)
        return ids

    def cid_escrita():
        cs = ctx.carteiras_visiveis()
        minha = next((c for c in cs if c.get("dono_id") == ctx.usuario_id() and c["permissoes"]["editar"]), None)
        ed = minha or next((c for c in cs if c["permissoes"]["editar"]), None)
        if not ed:
            raise ctx.ErroAcesso("Você tem acesso somente de visualização.", 403)
        return ed["id"]

    def marcas(ids):
        return ",".join("?" * len(ids))

    def periodo():
        try:
            dias = max(7, min(int(request.args.get("dias") or 90), 3650))
        except ValueError:
            dias = 90
        return dias, (dt.date.fromisoformat(ctx.hoje()) - dt.timedelta(days=dias)).isoformat()

    # ---------------------------------------------------------------- leitura das notas
    @app.post("/api/compras/ler")
    def cmp_ler():
        """Lê notas (texto do QR Code ou foto) e compara cada item com o que já foi pago antes."""
        d = request.get_json(silent=True) or {}
        entradas = [("texto", t, None) for t in (d.get("textos") or request.form.getlist("texto")) if str(t).strip()]
        for arq in request.files.getlist("foto"):
            if arq and arq.filename:
                entradas.append(("foto", arq.read(), arq.filename))
        if not entradas:
            return erro("Escaneie o QR Code do cupom, escolha uma foto ou cole o link da nota.")
        abrir = app.config.get("nfce_abrir")
        ids = cids()
        notas, falhas, vistas = [], [], set()
        for tipo, valor, nome in entradas[:20]:
            try:
                texto = nfce.ler_qrcode_da_foto(valor) if tipo == "foto" else str(valor)
                chave = nfce.ler_qrcode(texto)["chave"]
                if chave in vistas:
                    continue
                vistas.add(chave)
                n = nfce.consultar(texto, abrir)
            except nfce.ErroNota as e:
                falhas.append({"origem": nome or str(valor)[:60], "motivo": str(e)})
                continue
            ja = conn.execute("SELECT id, data FROM cmp_compras WHERE chave = ?", (n["chave"],)).fetchone()
            n["ja_registrada"] = dict(ja) if ja else None
            n["loja_nome"] = cmp.nome_loja(n.get("emitente")) if n.get("emitente") else None
            comparar_itens(n, ids)
            notas.append(n)
        return jsonify({"notas": notas, "falhas": falhas, "planejamento": licenca.modulo_ativo("planejamento")})

    def comparar_itens(nota, ids):
        """Para cada item: o menor preço já pago em outro mercado (se for mais barato)."""
        pids = {}
        for it in nota.get("itens") or []:
            row = conn.execute("SELECT produto_id FROM cmp_apelidos WHERE chave = ?", (cmp.chave_produto(it["descricao"]),)).fetchone()
            if row:
                pids[it["descricao"]] = row["produto_id"]
        precos = cmp.precos_por_loja(conn, ids, list(set(pids.values())))
        cnpj = nota.get("cnpj")
        loja = conn.execute("SELECT id FROM cmp_lojas WHERE cnpj = ?", (cnpj,)).fetchone() if cnpj else None
        for it in nota.get("itens") or []:
            ps = precos.get(pids.get(it["descricao"])) or {}
            outros = sorted((p for lid, p in ps.items() if not loja or lid != loja["id"]), key=lambda p: p["unitario"])
            unit = it.get("unitario") or (it.get("valor") / it["qtd"] if it.get("valor") and it.get("qtd") else None)
            if outros and unit and outros[0]["unitario"] < unit - 0.009:
                it["mais_barato"] = outros[0]

    @app.post("/api/compras/diagnostico")
    def cmp_diagnostico():
        """Estrutura da página da nota no portal (números mascarados), para ajustar o leitor ao estado."""
        from .nfce_diag import diagnosticar
        texto = str((request.get_json(silent=True) or {}).get("texto") or "")
        return jsonify({"texto": diagnosticar(texto, app.config.get("nfce_abrir"))})

    @app.post("/api/compras/registrar")
    def cmp_registrar():
        d = request.get_json(silent=True) or {}
        if not nfce.chave_valida(str(d.get("chave") or "")):
            return erro("Chave de acesso inválida.")
        itens = [i for i in (d.get("itens") or []) if isinstance(i, dict)][:400]
        compra_id, nova = cmp.registrar_compra(conn, cid_escrita(), {**d, "itens": itens,
                                                                     "url": d.get("url") if nfce.host_permitido(d.get("url") or "") else None})
        conn.commit()
        return jsonify({"ok": True, "id": compra_id, "nova": nova}), 201 if nova else 200

    # ---------------------------------------------------------------- mercados e compras
    @app.get("/api/compras/resumo")
    def cmp_resumo():
        ids = cids()
        dias, desde = periodo()
        compras = db.rows(conn.execute(
            f"""SELECT c.*, l.nome AS loja, (SELECT COUNT(*) FROM cmp_itens i WHERE i.compra_id = c.id) AS qtd_itens
                FROM cmp_compras c JOIN cmp_lojas l ON l.id = c.loja_id
                WHERE c.carteira_id IN ({marcas(ids)}) ORDER BY c.data DESC, c.id DESC""", ids))
        no_periodo = [c for c in compras if c["data"] >= desde]
        total = sum(c["total"] or 0 for c in no_periodo)
        # em quantos produtos cada loja tem o menor preço (preços dos últimos 90 dias)
        recentes = cmp.precos_por_loja(conn, ids, desde=(dt.date.fromisoformat(ctx.hoje()) - dt.timedelta(days=90)).isoformat())
        mais_barato = {}
        for por_loja in recentes.values():
            if len(por_loja) > 1:
                melhor = min(por_loja.values(), key=lambda p: p["unitario"])
                mais_barato[melhor["loja_id"]] = mais_barato.get(melhor["loja_id"], 0) + 1
        lojas = {}
        for c in compras:
            lj = lojas.setdefault(c["loja_id"], {"id": c["loja_id"], "nome": c["loja"], "gasto": 0.0, "visitas": 0,
                                                 "ultima": c["data"], "mais_barato_em": mais_barato.get(c["loja_id"], 0),
                                                 "total_geral": 0.0})
            lj["total_geral"] += c["total"] or 0
            if c["data"] >= desde:
                lj["gasto"] += c["total"] or 0
                lj["visitas"] += 1
        for lj in lojas.values():
            lj["ticket"] = round(lj["gasto"] / lj["visitas"], 2) if lj["visitas"] else None
            lj["gasto"] = round(lj["gasto"], 2)
            info = conn.execute("SELECT cnpj, endereco FROM cmp_lojas WHERE id = ?", (lj["id"],)).fetchone()
            lj["cnpj"], lj["endereco"] = nfce.formatar_cnpj(info["cnpj"]), info["endereco"]
        return jsonify({"dias": dias, "gasto": round(total, 2), "compras": len(no_periodo),
                        "ticket": round(total / len(no_periodo), 2) if no_periodo else None,
                        "itens": sum(c["qtd_itens"] for c in no_periodo),
                        "lojas": sorted(lojas.values(), key=lambda x: (-x["gasto"], -x["total_geral"])),
                        "ultimas": compras[:30], "tem_compras": bool(compras)})

    @app.get("/api/compras/compras/<int:compra_id>")
    def cmp_compra(compra_id):
        c = conn.execute(f"""SELECT c.*, l.nome AS loja, l.cnpj, l.endereco FROM cmp_compras c JOIN cmp_lojas l ON l.id = c.loja_id
                             WHERE c.id = ? AND c.carteira_id IN ({marcas(cids())})""", [compra_id, *cids()]).fetchone()
        if c is None:
            return erro("Compra não encontrada.", 404)
        itens = db.rows(conn.execute("""SELECT i.*, p.nome AS produto FROM cmp_itens i JOIN cmp_produtos p ON p.id = i.produto_id
                                        WHERE i.compra_id = ? ORDER BY i.id""", (compra_id,)))
        return jsonify({**dict(c), "cnpj": nfce.formatar_cnpj(c["cnpj"]), "itens": itens})

    @app.delete("/api/compras/compras/<int:compra_id>")
    def cmp_excluir_compra(compra_id):
        n = conn.execute(f"DELETE FROM cmp_compras WHERE id = ? AND carteira_id IN ({marcas(cids())})",
                         [compra_id, *cids()]).rowcount
        conn.commit()
        return jsonify({"ok": bool(n)})

    @app.put("/api/compras/lojas/<int:loja_id>")
    def cmp_renomear_loja(loja_id):
        nome = ((request.get_json(silent=True) or {}).get("nome") or "").strip()[:60]
        if not nome:
            return erro("Informe o nome do mercado.")
        conn.execute("UPDATE cmp_lojas SET nome = ? WHERE id = ?", (nome, loja_id))
        conn.commit()
        return jsonify({"ok": True})

    # ---------------------------------------------------------------- produtos e preços
    def estatisticas_produtos(ids, produto_ids=None, busca=None, loja_id=None):
        filtro, args = "", list(ids)
        if produto_ids is not None:
            filtro += f" AND i.produto_id IN ({marcas(produto_ids) or 'NULL'})"
            args += list(produto_ids)
        rows = conn.execute(
            f"""SELECT i.produto_id, p.nome, p.unidade, i.unitario, i.un, c.data, c.loja_id, l.nome AS loja FROM cmp_itens i
                JOIN cmp_compras c ON c.id = i.compra_id JOIN cmp_produtos p ON p.id = i.produto_id
                JOIN cmp_lojas l ON l.id = c.loja_id
                WHERE c.carteira_id IN ({marcas(ids)}) AND i.unitario > 0 {filtro} ORDER BY c.data, c.id""", args).fetchall()
        prods = {}
        for r in rows:
            p = prods.setdefault(r["produto_id"], {"id": r["produto_id"], "nome": r["nome"], "un": r["un"] or r["unidade"],
                                                   "compras": 0, "historico": [], "lojas": {}})
            p["compras"] += 1
            p["historico"].append((r["data"], r["unitario"]))
            p["lojas"][r["loja_id"]] = {"loja_id": r["loja_id"], "loja": r["loja"], "unitario": round(r["unitario"], 2), "data": r["data"]}
            p["ultimo"] = {"unitario": round(r["unitario"], 2), "loja": r["loja"], "loja_id": r["loja_id"], "data": r["data"]}
        termo = cmp.chave_produto(busca) if busca else None
        out = []
        for p in prods.values():
            if termo and not all(w in cmp.chave_produto(p["nome"]) for w in termo.split()):
                continue
            if loja_id and loja_id not in p["lojas"]:
                continue
            atuais = sorted(p["lojas"].values(), key=lambda x: x["unitario"])
            hist = p.pop("historico")
            limite = (dt.date.fromisoformat(ctx.hoje()) - dt.timedelta(days=180)).isoformat()
            p.update(menor=atuais[0], maior=atuais[-1], lojas=atuais, qtd_lojas=len(atuais),
                     variacao=cmp.variacao([h for h in hist if h[0] >= limite]),
                     media=round(sum(v for _, v in hist) / len(hist), 2))
            out.append(p)
        return out

    @app.get("/api/compras/produtos")
    def cmp_produtos():
        loja = request.args.get("loja")
        lista = estatisticas_produtos(cids(), busca=(request.args.get("busca") or "").strip() or None,
                                      loja_id=int(loja) if str(loja or "").isdigit() else None)
        ordem = request.args.get("ordem") or "compras"
        chave = {"compras": lambda p: (-p["compras"], p["nome"]), "nome": lambda p: p["nome"],
                 "alta": lambda p: -(p["variacao"] or -999), "economia": lambda p: -(p["maior"]["unitario"] - p["menor"]["unitario"])}
        lista.sort(key=chave.get(ordem, chave["compras"]))
        lojas = db.rows(conn.execute(f"""SELECT DISTINCT l.id, l.nome FROM cmp_lojas l JOIN cmp_compras c ON c.loja_id = l.id
                                         WHERE c.carteira_id IN ({marcas(cids())}) ORDER BY l.nome""", cids()))
        return jsonify({"produtos": lista[:500], "total": len(lista), "lojas": lojas})

    @app.get("/api/compras/produtos/<int:pid>")
    def cmp_produto(pid):
        ids = cids()
        p = conn.execute("SELECT * FROM cmp_produtos WHERE id = ?", (pid,)).fetchone()
        if p is None:
            return erro("Produto não encontrado.", 404)
        hist = db.rows(conn.execute(
            f"""SELECT c.id AS compra_id, c.data, l.nome AS loja, c.loja_id, i.qtd, i.un, i.unitario, i.valor, i.descricao
                FROM cmp_itens i JOIN cmp_compras c ON c.id = i.compra_id JOIN cmp_lojas l ON l.id = c.loja_id
                WHERE i.produto_id = ? AND c.carteira_id IN ({marcas(ids)}) ORDER BY c.data, c.id""", [pid, *ids]))
        nomes = sorted({h["descricao"] for h in hist})
        est = (estatisticas_produtos(ids, [pid]) or [None])[0]
        return jsonify({"produto": dict(p), "historico": hist, "nomes_nas_notas": nomes, "resumo": est})

    @app.put("/api/compras/produtos/<int:pid>")
    def cmp_renomear_produto(pid):
        nome = ((request.get_json(silent=True) or {}).get("nome") or "").strip()[:80]
        if not nome:
            return erro("Informe o nome do produto.")
        conn.execute("UPDATE cmp_produtos SET nome = ? WHERE id = ?", (nome, pid))
        conn.commit()
        return jsonify({"ok": True})

    @app.post("/api/compras/produtos/<int:pid>/juntar")
    def cmp_juntar(pid):
        """Junta outro produto neste (mesmo item com nomes diferentes em mercados diferentes)."""
        try:
            outro = int((request.get_json(silent=True) or {}).get("com"))
        except (TypeError, ValueError):
            return erro("Escolha o produto a juntar.")
        if not conn.execute("SELECT 1 FROM cmp_produtos WHERE id = ?", (outro,)).fetchone():
            return erro("Produto não encontrado.", 404)
        cmp.juntar_produtos(conn, pid, outro)
        conn.commit()
        return jsonify({"ok": True})

    # ---------------------------------------------------------------- lista de compras
    @app.get("/api/compras/lista")
    def cmp_lista():
        ids = cids()
        rows = db.rows(conn.execute(
            f"""SELECT li.*, p.nome AS produto, p.unidade FROM cmp_lista li LEFT JOIN cmp_produtos p ON p.id = li.produto_id
                WHERE li.carteira_id IN ({marcas(ids)}) ORDER BY li.comprado, li.id""", ids))
        itens = [{"id": r["id"], "produto_id": r["produto_id"], "nome": r["produto"] or r["texto"] or "Item",
                  "qtd": r["qtd"], "comprado": bool(r["comprado"]), "un": r["unidade"]} for r in rows]
        precos = cmp.precos_por_loja(conn, ids, [i["produto_id"] for i in itens if i["produto_id"]])
        lojas = {r["id"]: r["nome"] for r in conn.execute("SELECT id, nome FROM cmp_lojas")}
        lista = cmp.montar_lista(itens, precos, lojas, ctx.hoje())
        # sugestões: o que a casa compra com frequência e não está na lista
        na_lista = {i["produto_id"] for i in itens if i["produto_id"]}
        desde = (dt.date.fromisoformat(ctx.hoje()) - dt.timedelta(days=120)).isoformat()
        freq = conn.execute(
            f"""SELECT i.produto_id, p.nome, COUNT(DISTINCT c.id) AS vezes FROM cmp_itens i
                JOIN cmp_compras c ON c.id = i.compra_id JOIN cmp_produtos p ON p.id = i.produto_id
                WHERE c.carteira_id IN ({marcas(ids)}) AND c.data >= ? GROUP BY i.produto_id
                HAVING vezes >= 2 ORDER BY vezes DESC, p.nome LIMIT 24""", [*ids, desde]).fetchall()
        lista["sugestoes"] = [{"produto_id": r["produto_id"], "nome": r["nome"], "vezes": r["vezes"]}
                              for r in freq if r["produto_id"] not in na_lista][:12]
        return jsonify(lista)

    @app.post("/api/compras/lista")
    def cmp_lista_adicionar():
        d = request.get_json(silent=True) or {}
        pid = d.get("produto_id")
        pid = int(pid) if str(pid or "").isdigit() else None
        texto = (d.get("texto") or "").strip()[:80]
        if not pid and texto:  # texto que bate com um produto conhecido vira o produto
            row = conn.execute("SELECT produto_id FROM cmp_apelidos WHERE chave = ?", (cmp.chave_produto(texto),)).fetchone()
            pid = row["produto_id"] if row else None
        if not pid and not texto:
            return erro("Digite o item.")
        try:
            qtd = max(0.001, float(str(d.get("qtd") or 1).replace(",", ".")))
        except ValueError:
            qtd = 1
        ids = cids()
        if pid:
            ja = conn.execute(f"SELECT id, qtd FROM cmp_lista WHERE produto_id = ? AND comprado = 0 AND carteira_id IN ({marcas(ids)})",
                              [pid, *ids]).fetchone()
            if ja:  # já está na lista: soma a quantidade
                conn.execute("UPDATE cmp_lista SET qtd = qtd + ? WHERE id = ?", (qtd, ja["id"]))
                conn.commit()
                return jsonify({"ok": True, "id": ja["id"], "somado": True})
        cur = conn.execute("INSERT INTO cmp_lista (carteira_id, produto_id, texto, qtd) VALUES (?, ?, ?, ?)",
                           (cid_escrita(), pid, None if pid else texto, qtd))
        conn.commit()
        return jsonify({"ok": True, "id": cur.lastrowid}), 201

    @app.put("/api/compras/lista/<int:item_id>")
    def cmp_lista_editar(item_id):
        d = request.get_json(silent=True) or {}
        ids = cids()
        if "comprado" in d:
            conn.execute(f"UPDATE cmp_lista SET comprado = ? WHERE id = ? AND carteira_id IN ({marcas(ids)})",
                         [1 if d["comprado"] else 0, item_id, *ids])
        if "qtd" in d:
            try:
                qtd = float(str(d["qtd"]).replace(",", "."))
            except ValueError:
                return erro("Quantidade inválida.")
            if qtd <= 0:
                conn.execute(f"DELETE FROM cmp_lista WHERE id = ? AND carteira_id IN ({marcas(ids)})", [item_id, *ids])
            else:
                conn.execute(f"UPDATE cmp_lista SET qtd = ? WHERE id = ? AND carteira_id IN ({marcas(ids)})", [qtd, item_id, *ids])
        conn.commit()
        return jsonify({"ok": True})

    @app.delete("/api/compras/lista/<int:item_id>")
    def cmp_lista_remover(item_id):
        conn.execute(f"DELETE FROM cmp_lista WHERE id = ? AND carteira_id IN ({marcas(cids())})", [item_id, *cids()])
        conn.commit()
        return jsonify({"ok": True})

    @app.delete("/api/compras/lista")
    def cmp_lista_limpar():
        """Tira da lista o que já foi comprado (ou tudo, com ?tudo=1)."""
        filtro = "" if request.args.get("tudo") else " AND comprado = 1"
        n = conn.execute(f"DELETE FROM cmp_lista WHERE carteira_id IN ({marcas(cids())}){filtro}", cids()).rowcount
        conn.commit()
        return jsonify({"ok": True, "removidos": n})

    @app.get("/api/compras/buscar")
    def cmp_buscar():
        """Produtos conhecidos para o campo de adicionar à lista (com o menor preço recente)."""
        termo = (request.args.get("q") or "").strip()
        if len(termo) < 2:
            return jsonify([])
        achados = estatisticas_produtos(cids(), busca=termo)
        achados.sort(key=lambda p: (-p["compras"], p["nome"]))
        return jsonify([{"id": p["id"], "nome": p["nome"], "menor": p["menor"], "compras": p["compras"]} for p in achados[:8]])
