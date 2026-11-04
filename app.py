"""Servidor web: gestão de aportes e análise de mercado."""
import datetime as dt
import os
import secrets
import time

from flask import Flask, g, jsonify, redirect, render_template, request, session, url_for



def carregar_env(caminho=".env"):
    """Lê variáveis de um arquivo .env (CHAVE=valor) sem sobrescrever as já definidas."""
    if not os.path.exists(caminho):
        return
    with open(caminho, encoding="utf-8") as f:
        for linha in f:
            linha = linha.strip()
            if not linha or linha.startswith("#") or "=" not in linha:
                continue
            chave, valor = linha.split("=", 1)
            os.environ.setdefault(chave.strip(), valor.strip().strip('"').strip("'"))


carregar_env(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

from carteira import analysis, auth, db, portfolio, providers  # noqa: E402  (após carregar o .env)
from carteira.auth import ErroAcesso  # noqa: E402
from carteira.market import Mercado, MarketDataError, modo_demo  # noqa: E402


def chave_secreta(db_path):
    """SECRET_KEY do ambiente ou gerada uma vez e guardada ao lado do banco."""
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    pasta = os.path.dirname(os.path.abspath(db_path or os.environ.get("CARTEIRA_DB", "carteira.db")))
    caminho = os.path.join(pasta, ".secret_key")
    if not os.path.exists(caminho):
        with open(caminho, "w", encoding="utf-8") as f:
            f.write(secrets.token_hex(32))
    with open(caminho, encoding="utf-8") as f:
        return f.read().strip()


MAX_TENTATIVAS = 5
BLOQUEIO_SEG = 300


def create_app(db_path=None, fonte_mercado=None, secret_key=None):
    app = Flask(__name__)
    app.secret_key = secret_key or chave_secreta(db_path)
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                      PERMANENT_SESSION_LIFETIME=dt.timedelta(days=14))
    conn = db.connect(db_path)
    mercado = Mercado(conn, fonte_mercado)
    app.config["conn"] = conn
    tentativas = {}  # (email, ip) -> [falhas, bloqueado_ate]

    def erro(msg, status=400):
        return jsonify({"erro": msg}), status

    @app.teardown_request
    def fechar_conexao(_exc):
        conn.rollback()  # descarta transações não confirmadas por erro
        conn.close()

    @app.errorhandler(ErroAcesso)
    def tratar_erro_acesso(e):
        conn.rollback()
        return erro(str(e), e.status)

    # ---------- Autenticação ----------
    ROTAS_PUBLICAS = {"login", "auth_login", "auth_setup", "static"}

    @app.before_request
    def verificar_sessao():
        # Proteção CSRF: requisições que alteram dados precisam do cabeçalho enviado pelo fetch
        # da própria aplicação (formulários de outros sites não conseguem enviá-lo).
        if request.method not in ("GET", "HEAD", "OPTIONS") and \
                request.headers.get("X-Requested-With") != "fetch":
            return erro("Requisição inválida.", 403)
        g.usuario = None
        uid = session.get("uid")
        if uid:
            u = auth.obter_usuario(conn, uid)
            if u is not None and u["ativo"]:
                g.usuario = u
            else:
                session.clear()
        if g.usuario is None and request.endpoint not in ROTAS_PUBLICAS:
            if request.path.startswith("/api/"):
                return erro("Faça login para continuar.", 401)
            return redirect(url_for("login"))

    def exigir_admin():
        if not g.usuario["admin"]:
            raise ErroAcesso("Apenas administradores podem fazer isso.", 403)

    def carteira_atual(permissao="ver"):
        """Carteira indicada pelo cabeçalho X-Carteira, verificando a permissão do usuário."""
        try:
            cid = int(request.headers.get("X-Carteira") or request.args.get("carteira") or 0)
        except ValueError:
            cid = 0
        if not cid:
            raise ErroAcesso("Selecione uma carteira.")
        p = auth.permissoes(conn, g.usuario, cid)
        if not p["ver"]:
            raise ErroAcesso("Carteira não encontrada ou sem permissão de acesso.", 404)
        if not p[permissao]:
            msg = {"editar": "Você tem acesso somente de visualização a esta carteira.",
                   "gerenciar": "Você não pode gerenciar os acessos desta carteira."}[permissao]
            raise ErroAcesso(msg, 403)
        return cid

    @app.get("/login")
    def login():
        if g.usuario is not None:
            return redirect(url_for("index"))
        return render_template("login.html", configurar=not auth.existe_usuario(conn), demo=modo_demo())

    def iniciar_sessao(uid):
        session.clear()
        session.permanent = True
        session["uid"] = uid

    @app.post("/auth/login")
    def auth_login():
        d = request.get_json(silent=True) or {}
        email = (d.get("email") or "").strip().lower()
        chave = (email, request.remote_addr)
        falhas, ate = tentativas.get(chave, [0, 0])
        if ate > time.time():
            return erro(f"Muitas tentativas. Aguarde {int(ate - time.time()) // 60 + 1} minuto(s).", 429)
        u = auth.autenticar(conn, email, d.get("senha"))
        if u is None:
            falhas += 1
            tentativas[chave] = [0, time.time() + BLOQUEIO_SEG] if falhas >= MAX_TENTATIVAS else [falhas, 0]
            return erro("E-mail ou senha incorretos.", 401)
        tentativas.pop(chave, None)
        iniciar_sessao(u["id"])
        return jsonify({"ok": True})

    @app.post("/auth/setup")
    def auth_setup():
        d = request.get_json(silent=True) or {}
        uid, _ = auth.configuracao_inicial(conn, d.get("nome"), d.get("email"), d.get("senha"),
                                           d.get("nome_carteira"))
        conn.commit()
        iniciar_sessao(uid)
        return jsonify({"ok": True}), 201

    @app.post("/auth/logout")
    def auth_logout():
        session.clear()
        return jsonify({"ok": True})

    @app.get("/api/eu")
    def api_eu():
        return jsonify({"usuario": auth.publico(g.usuario),
                        "carteiras": auth.carteiras_do_usuario(conn, g.usuario)})

    @app.post("/api/eu/senha")
    def api_alterar_senha():
        d = request.get_json(silent=True) or {}
        if auth.autenticar(conn, g.usuario["email"], d.get("atual")) is None:
            return erro("Senha atual incorreta.", 403)
        auth.alterar_senha(conn, g.usuario["id"], d.get("nova"))
        conn.commit()
        return jsonify({"ok": True})

    # ---------- Usuários (administrador) ----------
    @app.get("/api/usuarios")
    def api_usuarios():
        exigir_admin()
        return jsonify(auth.listar_usuarios(conn))

    @app.post("/api/usuarios")
    def api_criar_usuario():
        exigir_admin()
        d = request.get_json(silent=True) or {}
        uid = auth.criar_usuario(conn, d.get("email"), d.get("nome"), d.get("senha"), bool(d.get("admin")))
        if d.get("criar_carteira"):
            auth.criar_carteira(conn, d.get("nome_carteira") or f"Carteira {d.get('nome', '').strip()}", uid)
        conn.commit()
        return jsonify({"ok": True, "id": uid}), 201

    @app.patch("/api/usuarios/<int:uid>")
    def api_atualizar_usuario(uid):
        exigir_admin()
        d = request.get_json(silent=True) or {}
        if uid == g.usuario["id"] and d.get("ativo") is False:
            return erro("Você não pode desativar a própria conta.", 409)
        auth.atualizar_usuario(conn, uid, d.get("nome"),
                               None if "admin" not in d else bool(d["admin"]),
                               None if "ativo" not in d else bool(d["ativo"]))
        if d.get("senha"):
            auth.alterar_senha(conn, uid, d["senha"])
        conn.commit()
        return jsonify({"ok": True})

    # ---------- Carteiras e acessos ----------
    @app.post("/api/carteiras")
    def api_criar_carteira():
        d = request.get_json(silent=True) or {}
        dono = g.usuario["id"]
        if d.get("dono_id") not in (None, "", dono):
            exigir_admin()  # só administradores criam carteiras para outras pessoas
            dono = int(d["dono_id"])
        cid = auth.criar_carteira(conn, d.get("nome"), dono)
        conn.commit()
        return jsonify({"ok": True, "id": cid}), 201

    @app.patch("/api/carteiras/<int:cid>")
    def api_atualizar_carteira(cid):
        d = request.get_json(silent=True) or {}
        if not auth.permissoes(conn, g.usuario, cid)["gerenciar"]:
            raise ErroAcesso("Você não pode alterar esta carteira.", 403)
        mudar_dono = "dono_id" in d
        if mudar_dono:
            exigir_admin()
        auth.renomear_carteira(conn, cid, d.get("nome") or auth.obter_carteira(conn, cid)["nome"],
                               int(d["dono_id"]) if d.get("dono_id") else None, mudar_dono)
        conn.commit()
        return jsonify({"ok": True})

    @app.delete("/api/carteiras/<int:cid>")
    def api_excluir_carteira(cid):
        c = auth.obter_carteira(conn, cid)
        if c is None or not (g.usuario["admin"] or c["dono_id"] == g.usuario["id"]):
            raise ErroAcesso("Só o dono ou um administrador pode excluir a carteira.", 403)
        auth.excluir_carteira(conn, cid)
        conn.commit()
        return jsonify({"ok": True})

    def exigir_gerenciar(cid):
        if not auth.permissoes(conn, g.usuario, cid)["gerenciar"]:
            raise ErroAcesso("Você não pode gerenciar os acessos desta carteira.", 403)

    @app.get("/api/carteiras/<int:cid>/acessos")
    def api_acessos(cid):
        exigir_gerenciar(cid)
        c = auth.obter_carteira(conn, cid)
        dono = auth.publico(auth.obter_usuario(conn, c["dono_id"])) if c["dono_id"] else None
        return jsonify({"carteira": {"id": c["id"], "nome": c["nome"]}, "dono": dono,
                        "acessos": auth.listar_acessos(conn, cid)})

    @app.put("/api/carteiras/<int:cid>/acessos")
    def api_definir_acesso(cid):
        exigir_gerenciar(cid)
        d = request.get_json(silent=True) or {}
        auth.definir_acesso(conn, cid, d.get("email"), bool(d.get("ver", True)),
                            bool(d.get("editar")), bool(d.get("gerenciar")))
        conn.commit()
        return jsonify({"ok": True})

    @app.delete("/api/carteiras/<int:cid>/acessos/<int:uid>")
    def api_remover_acesso(cid, uid):
        exigir_gerenciar(cid)
        auth.remover_acesso(conn, cid, uid)
        conn.commit()
        return jsonify({"ok": True})

    # ---------- Dados da carteira ----------
    def listar_ativos(cid):
        return db.rows(conn.execute("SELECT * FROM ativos WHERE carteira_id = ? ORDER BY ticker", (cid,)))

    def listar_aportes(cid):
        return db.rows(conn.execute(
            "SELECT * FROM aportes WHERE carteira_id = ? ORDER BY data DESC, id DESC", (cid,)))

    def montar_resumo(cid):
        ativos = listar_ativos(cid)
        aportes = listar_aportes(cid)
        manuais = {a["ticker"]: a["preco_manual"] for a in ativos}
        tickers = set(manuais) | {a["ticker"] for a in aportes}
        precos, fontes = {}, {}
        for t in tickers:
            p, f = mercado.preco_atual(t, manuais.get(t))
            if p is not None:
                precos[t], fontes[t] = p, f
        resumo = portfolio.resumo_carteira(ativos, aportes, precos)
        for l in resumo["ativos"]:
            l["fonte_preco"] = fontes.get(l["ticker"])
        return resumo

    @app.get("/")
    def index():
        return render_template("index.html", classes=portfolio.CLASSES,
                               tipos_provento=portfolio.TIPOS_PROVENTO, demo=modo_demo(),
                               usuario=auth.publico(g.usuario))

    # ---------- Ativos ----------
    @app.get("/api/ativos")
    def api_ativos():
        return jsonify(listar_ativos(carteira_atual()))

    @app.post("/api/ativos")
    def api_criar_ativo():
        cid = carteira_atual("editar")
        d = request.get_json(silent=True) or {}
        ticker = (d.get("ticker") or "").upper().strip()
        if not ticker:
            return erro("Ticker é obrigatório.")
        classe = d.get("classe") or "acao"
        if classe not in portfolio.CLASSES:
            return erro("Classe inválida.")
        try:
            meta = float(d.get("meta_pct") or 0)
            manual = float(d["preco_manual"]) if d.get("preco_manual") not in (None, "") else None
        except (TypeError, ValueError):
            return erro("Meta e preço manual devem ser numéricos.")
        if meta < 0:
            return erro("A meta não pode ser negativa.")
        conn.execute(
            """INSERT INTO ativos (carteira_id, ticker, nome, classe, meta_pct, preco_manual)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(carteira_id, ticker) DO UPDATE SET nome=excluded.nome, classe=excluded.classe,
               meta_pct=excluded.meta_pct, preco_manual=excluded.preco_manual""",
            (cid, ticker, d.get("nome") or "", classe, meta, manual))
        conn.commit()
        return jsonify({"ok": True, "ticker": ticker}), 201

    @app.delete("/api/ativos/<ticker>")
    def api_remover_ativo(ticker):
        cid = carteira_atual("editar")
        ticker = ticker.upper()
        em_uso = conn.execute("SELECT COUNT(*) FROM aportes WHERE carteira_id = ? AND ticker = ?",
                              (cid, ticker)).fetchone()[0]
        if em_uso:
            return erro("Ativo possui aportes registrados; remova-os antes.", 409)
        conn.execute("DELETE FROM ativos WHERE carteira_id = ? AND ticker = ?", (cid, ticker))
        conn.commit()
        return jsonify({"ok": True})

    # ---------- Aportes ----------
    @app.get("/api/aportes")
    def api_aportes():
        return jsonify(listar_aportes(carteira_atual()))

    @app.post("/api/aportes")
    def api_criar_aporte():
        cid = carteira_atual("editar")
        d = request.get_json(silent=True) or {}
        ticker = (d.get("ticker") or "").upper().strip()
        tipo = d.get("tipo") or "compra"
        try:
            data = dt.date.fromisoformat(d.get("data") or dt.date.today().isoformat()).isoformat()
            qtd = float(d.get("quantidade"))
            preco = float(d.get("preco"))
            taxas = float(d.get("taxas") or 0)
        except (TypeError, ValueError):
            return erro("Data, quantidade, preço e taxas devem ser válidos.")
        if not ticker or tipo not in ("compra", "venda") or qtd <= 0 or preco < 0 or taxas < 0:
            return erro("Dados do aporte inválidos.")
        aportes = listar_aportes(cid) + [{"id": 10**12, "data": data, "ticker": ticker, "tipo": tipo,
                                       "quantidade": qtd, "preco": preco, "taxas": taxas}]
        try:
            portfolio.calcular_posicoes(aportes)
        except ValueError as e:
            return erro(str(e))
        if not conn.execute("SELECT 1 FROM ativos WHERE carteira_id = ? AND ticker = ?",
                            (cid, ticker)).fetchone():
            conn.execute("INSERT INTO ativos (carteira_id, ticker, classe) VALUES (?, ?, ?)",
                         (cid, ticker, d.get("classe") or "acao"))
        cur = conn.execute(
            """INSERT INTO aportes (carteira_id, data, ticker, tipo, quantidade, preco, taxas, obs)
               VALUES (?,?,?,?,?,?,?,?)""",
            (cid, data, ticker, tipo, qtd, preco, taxas, d.get("obs") or ""))
        conn.commit()
        return jsonify({"ok": True, "id": cur.lastrowid}), 201

    @app.delete("/api/aportes/<int:aid>")
    def api_remover_aporte(aid):
        cid = carteira_atual("editar")
        restantes = [a for a in listar_aportes(cid) if a["id"] != aid]
        try:
            portfolio.calcular_posicoes(restantes)
        except ValueError as e:
            return erro("Remover este aporte deixaria uma venda sem posição: " + str(e), 409)
        conn.execute("DELETE FROM aportes WHERE id = ? AND carteira_id = ?", (aid, cid))
        conn.commit()
        return jsonify({"ok": True})

    # ---------- Carteira ----------
    @app.get("/api/carteira")
    def api_carteira():
        cid = carteira_atual()
        resumo = montar_resumo(cid)
        resumo["evolucao_aportes"] = portfolio.aportes_por_mes(listar_aportes(cid))
        prov = portfolio.resumo_proventos(listar_proventos(cid), resumo, hoje())
        por_ativo = {p["ticker"]: p for p in prov["por_ativo"]}
        for l in resumo["ativos"]:
            p = por_ativo.get(l["ticker"], {})
            l["proventos_total"] = p.get("total", 0.0)
            l["proventos_12m"] = p.get("ult_12m", 0.0)
            l["yoc_pct"] = p.get("yoc_pct")
        resumo["proventos"] = {k: prov[k] for k in ("total", "ult_12m", "media_mensal_12m", "yoc_pct", "dy_pct")}
        return jsonify(resumo)

    # ---------- Proventos ----------
    def hoje():
        return dt.date.today().isoformat()

    def listar_proventos(cid):
        return db.rows(conn.execute(
            "SELECT * FROM proventos WHERE carteira_id = ? ORDER BY data_pagamento DESC, id DESC", (cid,)))

    def inserir_provento(cid, d):
        ticker = (d.get("ticker") or "").upper().strip()
        tipo = d.get("tipo") or "dividendo"
        if not ticker or tipo not in portfolio.TIPOS_PROVENTO:
            raise ValueError("Ticker e tipo válidos são obrigatórios.")
        try:
            pagamento = dt.date.fromisoformat(d.get("data_pagamento") or "").isoformat()
            data_com = dt.date.fromisoformat(d["data_com"]).isoformat() if d.get("data_com") else None
            qtd = float(d["quantidade"]) if d.get("quantidade") not in (None, "") else None
            unit = float(d["valor_unitario"]) if d.get("valor_unitario") not in (None, "") else None
            total = float(d["valor_total"]) if d.get("valor_total") not in (None, "") else None
        except (TypeError, ValueError):
            raise ValueError("Datas e valores do provento devem ser válidos.")
        if total is None and qtd is not None and unit is not None:
            total = round(qtd * unit, 2)
        if total is None or total < 0:
            raise ValueError("Informe o valor total (ou quantidade e valor por cota).")
        cur = conn.execute(
            """INSERT INTO proventos (carteira_id, ticker, tipo, data_com, data_pagamento, quantidade,
               valor_unitario, valor_total, obs) VALUES (?,?,?,?,?,?,?,?,?)""",
            (cid, ticker, tipo, data_com, pagamento, qtd, unit, total, d.get("obs") or ""))
        return cur.lastrowid

    @app.get("/api/proventos")
    def api_proventos():
        cid = carteira_atual()
        lista = listar_proventos(cid)
        return jsonify({"itens": lista,
                        "resumo": portfolio.resumo_proventos(lista, montar_resumo(cid), hoje())})

    @app.post("/api/proventos")
    def api_criar_provento():
        cid = carteira_atual("editar")
        try:
            pid = inserir_provento(cid, request.get_json(silent=True) or {})
        except ValueError as e:
            return erro(str(e))
        conn.commit()
        return jsonify({"ok": True, "id": pid}), 201

    @app.delete("/api/proventos/<int:pid>")
    def api_remover_provento(pid):
        cid = carteira_atual("editar")
        conn.execute("DELETE FROM proventos WHERE id = ? AND carteira_id = ?", (pid, cid))
        conn.commit()
        return jsonify({"ok": True})

    @app.get("/api/proventos/estimar")
    def api_estimar_proventos():
        """Busca proventos por ação nas fontes e calcula quanto você recebeu/receberá."""
        cid = carteira_atual()
        aportes = listar_aportes(cid)
        forcar = request.args.get("atualizar") == "1"
        por_ticker, fontes, falhas = {}, {}, {}
        for t in sorted({a["ticker"] for a in aportes}):
            try:
                por_ticker[t], fontes[t] = mercado.proventos(t, forcar)
            except MarketDataError as e:
                falhas[t] = str(e)
        itens = portfolio.estimar_proventos(aportes, por_ticker, listar_proventos(cid), hoje())
        return jsonify({"itens": itens, "fontes": fontes, "falhas": falhas})

    @app.post("/api/proventos/importar")
    def api_importar_proventos():
        cid = carteira_atual("editar")
        itens = (request.get_json(silent=True) or {}).get("itens") or []
        try:
            for d in itens:
                inserir_provento(cid, {**d, "obs": d.get("obs") or "importado"})
        except ValueError as e:
            conn.rollback()
            return erro(str(e))
        conn.commit()
        return jsonify({"ok": True, "importados": len(itens)}), 201

    # ---------- Fundamentos ----------
    @app.get("/api/fundamentos/<ticker>")
    def api_fundamentos(ticker):
        ticker = ticker.upper()
        forcar = request.args.get("atualizar") == "1"
        out = {"ticker": ticker, "campos": list(providers.CAMPOS_FUNDAMENTOS.items())}
        try:
            out["indicadores"], out["fonte_indicadores"] = mercado.fundamentos(ticker, forcar)
        except MarketDataError as e:
            out["indicadores"], out["erro_indicadores"] = None, str(e)
        try:
            itens, out["fonte_proventos"] = mercado.proventos(ticker, forcar)
        except MarketDataError as e:
            itens, out["erro_proventos"] = [], str(e)
        cid = int(request.headers.get("X-Carteira") or 0) if (request.headers.get("X-Carteira") or "").isdigit() else 0
        if cid and not auth.permissoes(conn, g.usuario, cid)["ver"]:
            cid = 0
        manual = conn.execute("SELECT preco_manual FROM ativos WHERE carteira_id = ? AND ticker = ?",
                              (cid, ticker)).fetchone()
        preco, _ = mercado.preco_atual(ticker, manual["preco_manual"] if manual else None)
        out["preco"] = preco
        out["dividend_yield"] = portfolio.dividend_yield(itens, preco, hoje())
        out["proventos_por_ano"] = portfolio.proventos_por_ano(itens)
        out["proventos"] = sorted(itens, key=lambda x: x["data_com"], reverse=True)[:24]
        return jsonify(out)

    @app.post("/api/sugestao")
    def api_sugestao():
        cid = carteira_atual()
        d = request.get_json(silent=True) or {}
        try:
            valor = float(d.get("valor"))
            return jsonify(portfolio.sugerir_aporte(montar_resumo(cid), valor))
        except (TypeError, ValueError) as e:
            return erro(str(e) if isinstance(e, ValueError) and str(e) else "Valor inválido.")

    # ---------- Mercado ----------
    @app.get("/api/mercado/<ticker>")
    def api_mercado(ticker):
        try:
            rf = float(request.args.get("rf", 10)) / 100
            serie, fonte = mercado.historico(ticker, forcar=request.args.get("atualizar") == "1")
        except ValueError:
            return erro("Taxa livre de risco inválida.")
        except MarketDataError as e:
            return erro(str(e), 502)
        dias = int(request.args.get("dias", 0) or 0)
        datas = [d for d, _ in serie]
        fech = [c for _, c in serie]
        try:
            res = analysis.analisar(datas, fech, rf)
        except ValueError as e:
            return erro(f"{e} A fonte '{fonte}' retornou apenas {len(fech)} cotação(ões).", 422)
        if dias and dias < len(datas):
            for k in ("datas", "fechamento", "mm20", "mm50", "mm200", "bollinger_sup",
                      "bollinger_inf", "rsi", "macd", "macd_sinal", "macd_hist"):
                res[k] = res[k][-dias:]
        res["ticker"] = ticker.upper()
        res["fonte"] = fonte
        return jsonify(res)

    @app.get("/api/fontes")
    def api_fontes():
        return jsonify({"demo": modo_demo(), "fontes": mercado.status_fontes()})

    @app.get("/api/comparar")
    def api_comparar():
        tickers = [t.strip().upper() for t in request.args.get("tickers", "").split(",") if t.strip()]
        if len(tickers) < 2:
            return erro("Informe ao menos dois tickers separados por vírgula.")
        series, falhas = {}, {}
        for t in tickers[:8]:
            try:
                series[t] = dict(mercado.historico(t)[0])
            except MarketDataError as e:
                falhas[t] = str(e)
        if len(series) < 2:
            return erro("Não foi possível obter ao menos dois históricos. " + "; ".join(falhas.values()), 502)
        datas = sorted(set.intersection(*(set(s) for s in series.values())))
        dias = int(request.args.get("dias", 252) or 252)
        datas = datas[-dias:]
        if len(datas) < 3:
            return erro("Históricos sem datas em comum suficientes.")
        precos = {t: [s[d] for d in datas] for t, s in series.items()}
        retornos = {t: analysis.retornos_diarios(p) for t, p in precos.items()}
        nomes = list(precos)
        return jsonify({
            "datas": datas,
            "base100": {t: [v / p[0] * 100 for v in p] for t, p in precos.items()},
            "correlacao": [[analysis.correlacao(retornos[a], retornos[b]) for b in nomes] for a in nomes],
            "tickers": nomes,
            "estatisticas": {t: {"retorno": p[-1] / p[0] - 1,
                                 "volatilidade": analysis.volatilidade_anual(p),
                                 "max_drawdown": analysis.max_drawdown(p)} for t, p in precos.items()},
            "falhas": falhas,
        })

    return app


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)),
                     debug=os.environ.get("FLASK_DEBUG") == "1")
