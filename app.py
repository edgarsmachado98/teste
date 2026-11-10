"""Servidor web: gestão de aportes e análise de mercado."""
import bisect
import datetime as dt
import hashlib
from collections import defaultdict
import io
import os
import secrets
import time

from flask import Flask, g, jsonify, redirect, render_template, request, send_file, session, url_for



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

from carteira import analysis, auth, db, evolucao, impostos, portfolio, providers, rendafixa  # noqa: E402
from carteira.tesouro import Tesouro  # noqa: E402
from carteira import backup, notificacoes  # noqa: E402
from carteira.indices import NOMES as NOMES_INDICES, Indices  # noqa: E402
from carteira.auth import ErroAcesso  # noqa: E402
from carteira.importacao import (ErroImportacao, analisar_extrato, conciliar_posicao,  # noqa: E402
                                 marcar_duplicados, mesclar_posicoes)
from carteira.market import Mercado, MarketDataError, agora_brasilia, em_pregao, intervalo_pregao, modo_demo  # noqa: E402


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


def brl(v):
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_data(iso):
    return f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}"


MAX_TENTATIVAS = 5
LIMITE_CONCENTRACAO = float(os.environ.get("CARTEIRA_LIMITE_ATIVO") or 20)   # % da carteira em um ativo
LIMITE_SETOR = float(os.environ.get("CARTEIRA_LIMITE_SETOR") or 35)         # % da carteira em um setor
LIMITE_DESVIO = float(os.environ.get("CARTEIRA_LIMITE_DESVIO") or 5)        # pontos percentuais fora da meta
BLOQUEIO_SEG = 300


def create_app(db_path=None, fonte_mercado=None, secret_key=None, fonte_bcb=None, fonte_tesouro=None):
    app = Flask(__name__)
    app.secret_key = secret_key or chave_secreta(db_path)
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                      PERMANENT_SESSION_LIFETIME=dt.timedelta(days=14),
                      MAX_CONTENT_LENGTH=10 * 1024 * 1024)  # extratos de até 10 MB
    conn = db.connect(db_path)
    mercado = Mercado(conn, fonte_mercado)
    indices = Indices(conn, mercado, fonte_bcb)
    tesouro = Tesouro(conn, fonte_tesouro)
    app.config["conn"] = conn
    tentativas = {}  # (email, ip) -> [falhas, bloqueado_ate]

    def erro(msg, status=400):
        return jsonify({"erro": msg}), status

    @app.teardown_request
    def fechar_conexao(_exc):
        conn.rollback()  # descarta transações não confirmadas por erro
        conn.close()

    @app.errorhandler(413)
    def arquivo_grande(_e):
        return erro("Arquivo muito grande (limite de 10 MB).", 413)

    @app.errorhandler(ErroAcesso)
    def tratar_erro_acesso(e):
        conn.rollback()
        return erro(str(e), e.status)

    # ---------- Autenticação ----------
    ROTAS_PUBLICAS = {"login", "auth_login", "auth_setup", "static", "manifest", "service_worker"}

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
        valor = request.headers.get("X-Carteira") or request.args.get("carteira") or ""
        if valor == "todas":
            raise ErroAcesso("Na visão da família os dados são só para consulta. "
                             "Selecione uma carteira para fazer alterações.")
        try:
            cid = int(valor or 0)
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

    def carteiras_leitura():
        """Carteiras para consulta: a selecionada, ou todas as visíveis na visão da família."""
        if (request.headers.get("X-Carteira") or request.args.get("carteira")) == "todas":
            ids = [c["id"] for c in auth.carteiras_do_usuario(conn, g.usuario)]
            if not ids:
                raise ErroAcesso("Nenhuma carteira disponível.", 404)
            return ids
        return [carteira_atual()]

    # ---------- Aplicativo instalável (PWA) ----------
    @app.get("/manifest.webmanifest")
    def manifest():
        return jsonify({
            "name": "Carteira de Aportes", "short_name": "Carteira", "lang": "pt-BR",
            "start_url": "/", "scope": "/", "display": "standalone",
            "background_color": "#0f1a33", "theme_color": "#0f1a33",
            "description": "Gestão de aportes, proventos e análise de investimentos da família",
            "icons": [{"src": "/static/icons/icon-192.png", "sizes": "192x192", "type": "image/png"},
                      {"src": "/static/icons/icon-512.png", "sizes": "512x512", "type": "image/png"},
                      {"src": "/static/icons/maskable-512.png", "sizes": "512x512", "type": "image/png",
                       "purpose": "maskable"}],
        }), 200, {"Content-Type": "application/manifest+json"}

    @app.get("/sw.js")
    def service_worker():
        resp = send_file(os.path.join(app.static_folder, "sw.js"), mimetype="text/javascript")
        resp.headers["Cache-Control"] = "no-cache"
        resp.headers["Service-Worker-Allowed"] = "/"
        return resp

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

    # ---------- Cópia de segurança (administrador) ----------
    @app.get("/api/backup")
    def api_backup():
        exigir_admin()
        pasta = backup.pasta_padrao(conn.path)
        copias = backup.listar(pasta) + backup.listar(pasta, backup.PREFIXO_IMPORTACAO)
        copias.sort(key=lambda c: c["modificado"], reverse=True)
        return jsonify({"pasta": pasta, "copias": [{k: c[k] for k in ("nome", "tamanho", "modificado")} for c in copias]})

    @app.post("/api/backup")
    def api_fazer_backup():
        exigir_admin()
        caminho = backup.fazer_backup(conn.path)
        return jsonify({"ok": True, "arquivo": caminho}), 201

    @app.get("/api/backup/baixar")
    def api_baixar_backup():
        exigir_admin()
        nome = f"carteira-{dt.datetime.now().strftime('%Y-%m-%d-%H%M')}.db"
        caminho = backup.fazer_backup(conn.path, nome=f"download-{nome}")
        try:
            dados = open(caminho, "rb").read()
        finally:
            os.remove(caminho)
        return send_file(io.BytesIO(dados), as_attachment=True, download_name=nome,
                         mimetype="application/vnd.sqlite3")

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
    def filtro_carteiras(cids):
        ids = cids if isinstance(cids, (list, tuple)) else [cids]
        return f"carteira_id IN ({','.join('?' * len(ids))})", list(ids)

    def listar_ativos(cids):
        f, ids = filtro_carteiras(cids)
        return db.rows(conn.execute(f"SELECT * FROM ativos WHERE {f} ORDER BY ticker", ids))

    def listar_aportes(cids):
        f, ids = filtro_carteiras(cids)
        return db.rows(conn.execute(f"SELECT * FROM aportes WHERE {f} ORDER BY data DESC, id DESC", ids))

    def listar_eventos(cids):
        f, ids = filtro_carteiras(cids)
        return db.rows(conn.execute(f"SELECT * FROM eventos WHERE {f} ORDER BY data DESC, id DESC", ids))

    def listar_operacoes(cids):
        """Aportes + eventos corporativos: base de todos os cálculos de posição."""
        return portfolio.com_eventos(listar_aportes(cids), listar_eventos(cids))

    def configs_renda_fixa(ativos):
        cfg = {}
        for a in ativos:
            if (a.get("indexador") or "") in rendafixa.INDEXADORES and a["ticker"] not in cfg:
                cfg[a["ticker"]] = a
        return cfg

    def avaliar_renda_fixa(ativos, aportes, datas):
        """Valor dos títulos com indexador configurado em cada data: ({ticker: {data: resultado}}, erros)."""
        cfg = configs_renda_fixa(ativos)
        por_ticker = {}
        for a in aportes:
            if a["ticker"] in cfg:
                por_ticker.setdefault(a["ticker"], []).append(a)
        if not por_ticker:
            return {}, {}
        hoje_ = hoje()
        inicio = min(a["data"] for lista in por_ticker.values() for a in lista)
        usados = {cfg[t]["indexador"] for t in por_ticker}
        idx, erros = {}, {}
        for nome in ("cdi", "selic"):
            if nome in usados:
                try:
                    idx[nome] = indices.diaria(nome, inicio, hoje_)
                except Exception as e:
                    erros.update({t: f"{nome.upper()} indisponível: {e}" for t in por_ticker if cfg[t]["indexador"] == nome})
        if "ipca" in usados:
            try:
                idx["ipca"] = indices.ipca_mensal(inicio, hoje_)
            except Exception as e:
                erros.update({t: f"IPCA indisponível: {e}" for t in por_ticker if cfg[t]["indexador"] == "ipca"})
        pus = {}
        titulos = {t: (cfg[t].get("nome") or t if not t.upper().startswith("TESOURO") else t, cfg[t].get("vencimento"))
                   for t in por_ticker if cfg[t]["indexador"] == "tesouro"}
        if titulos:
            pus, erros_t, venc_t = tesouro.precos(titulos, demo=modo_demo())
            erros.update(erros_t)
            for t, venc in venc_t.items():  # vencimento oficial do título, se não foi informado
                if venc and not cfg[t].get("vencimento"):
                    cfg[t] = {**cfg[t], "vencimento": venc}
        g.vencimentos_tesouro = {t: cfg[t].get("vencimento") for t in titulos}
        resultado = {}
        for t, lista in por_ticker.items():
            if t in erros:
                continue
            serie_pu = pus.get(t) or []
            datas_pu = [d for d, _ in serie_pu]
            resultado[t] = {}
            for d in datas:
                i = bisect.bisect_right(datas_pu, d) if serie_pu else 0
                pu = serie_pu[i - 1][1] if i else None
                resultado[t][d] = rendafixa.avaliar(cfg[t], lista, d, idx, pu)
        return resultado, erros

    def cotacoes(ativos, aportes, com_series=False):
        """Preço atual (renda fixa pela curva, manual ou de mercado), fonte, fechamento anterior e histórico."""
        manuais = {a["ticker"]: a["preco_manual"] for a in ativos if a["preco_manual"]}
        tickers = {a["ticker"] for a in ativos} | {a["ticker"] for a in aportes}
        precos, fontes, anteriores, series = {}, {}, {}, {}
        hoje_ = hoje()
        datas = [hoje_]
        if com_series and aportes:  # fins de mês desde o primeiro aporte, para a evolução
            primeiro = min(a["data"] for a in aportes)
            fins = (evolucao._fim_do_mes(ano, mes).isoformat() for ano, mes in evolucao.meses_entre(primeiro, hoje_))
            datas = sorted({f for f in fins if f < hoje_} | {hoje_})
        rf, _ = avaliar_renda_fixa(ativos, aportes, datas)
        for t, por_data in rf.items():
            atual = por_data.get(hoje_)
            if not atual or not atual["preco_unitario"]:
                continue
            precos[t] = atual["preco_unitario"]
            fontes[t] = "tesouro" if configs_renda_fixa(ativos)[t]["indexador"] == "tesouro" else "curva"
            if com_series:
                series[t] = [(d, r["preco_unitario"]) for d, r in sorted(por_data.items())
                             if r and r["preco_unitario"]]
        for t in tickers:
            if t in precos:
                continue
            if manuais.get(t):
                precos[t], fontes[t] = float(manuais[t]), "manual"
                continue
            try:
                serie, fonte = mercado.historico(t)
            except MarketDataError:
                continue
            precos[t], fontes[t], series[t] = serie[-1][1], fonte, serie
            if len(serie) >= 2:
                anteriores[t] = serie[-2][1]  # fechamento do pregão anterior, para a variação do dia
        return precos, fontes, anteriores, series

    def metas_classe(cid):
        if isinstance(cid, (list, tuple)):
            if len(cid) != 1:
                return {}  # visão da família: cada carteira tem as suas metas
            cid = cid[0]
        return {r["classe"]: r["meta_pct"] for r in conn.execute(
            "SELECT classe, meta_pct FROM metas_classe WHERE carteira_id = ?", (cid,))}

    def montar_resumo(cid):
        ativos = listar_ativos(cid)
        aportes = listar_operacoes(cid)
        precos, fontes, anteriores, _ = cotacoes(ativos, aportes)
        com_posicao = {t for t, p in portfolio.calcular_posicoes(aportes).items() if p["quantidade"] > 0}
        ativos = portfolio.aplicar_metas_classe(ativos, metas_classe(cid), com_posicao)
        resumo = portfolio.resumo_carteira(ativos, aportes, precos)
        for l in resumo["ativos"]:
            l["fonte_preco"] = fontes.get(l["ticker"])
            ant, atual = anteriores.get(l["ticker"]), precos.get(l["ticker"])
            if ant and atual and l["quantidade"]:
                l["variacao_pct"] = (atual / ant - 1) * 100
                l["variacao_valor"] = l["quantidade"] * (atual - ant)
            else:
                l["variacao_pct"] = l["variacao_valor"] = None
        resumo.update(portfolio.visao_por_categoria(resumo["ativos"]))
        return resumo

    @app.get("/")
    def index():
        return render_template("index.html", classes=portfolio.CLASSES, indexadores=rendafixa.INDEXADORES,
                               tipos_provento=portfolio.TIPOS_PROVENTO, demo=modo_demo(),
                               usuario=auth.publico(g.usuario))

    # ---------- Ativos ----------
    @app.get("/api/ativos")
    def api_ativos():
        return jsonify(listar_ativos(carteiras_leitura()))

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
        indexador = (d.get("indexador") or "").lower() or None
        if indexador and indexador not in rendafixa.INDEXADORES:
            return erro("Indexador inválido.")
        try:
            meta = float(d.get("meta_pct") or 0)
            manual = float(d["preco_manual"]) if d.get("preco_manual") not in (None, "") else None
            taxa = float(str(d["taxa"]).replace(",", ".")) if d.get("taxa") not in (None, "") else None
            vencimento = dt.date.fromisoformat(d["vencimento"]).isoformat() if d.get("vencimento") else None
        except (TypeError, ValueError):
            return erro("Meta, preço manual, taxa e vencimento devem ser válidos.")
        if meta < 0:
            return erro("A meta não pode ser negativa.")
        if indexador in ("cdi", "selic", "ipca", "pre") and taxa is None:
            return erro("Informe a taxa contratada (ex.: 110 para 110% do CDI, 6 para IPCA + 6%).")
        conn.execute(
            """INSERT INTO ativos (carteira_id, ticker, nome, classe, meta_pct, preco_manual,
                                  indexador, taxa, vencimento, isento_ir, setor)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(carteira_id, ticker) DO UPDATE SET nome=excluded.nome, classe=excluded.classe,
               meta_pct=excluded.meta_pct, preco_manual=excluded.preco_manual, indexador=excluded.indexador,
               taxa=excluded.taxa, vencimento=excluded.vencimento, isento_ir=excluded.isento_ir,
               setor=excluded.setor""",
            (cid, ticker, d.get("nome") or "", classe, meta, manual, indexador, taxa, vencimento,
             int(bool(d.get("isento_ir"))), (d.get("setor") or "").strip() or None))
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
        return jsonify(listar_aportes(carteiras_leitura()))

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
        aportes = listar_operacoes(cid) + [{"id": 10**12, "data": data, "ticker": ticker, "tipo": tipo,
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
        restantes = [a for a in listar_operacoes(cid) if a["id"] != aid]
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
        cid = carteiras_leitura()
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
        resumo.update(portfolio.visao_por_categoria(resumo["ativos"]))
        tickers_mercado = [l["ticker"] for l in resumo["ativos"] if l.get("fonte_preco") not in (None, "manual", "curva", "tesouro")]
        resumo["cotacoes_em"] = mercado.atualizado_em(tickers_mercado)
        resumo["em_pregao"] = em_pregao()
        resumo["intervalo_minutos"] = intervalo_pregao()
        resumo["por_carteira"] = []
        if len(cid) > 1:  # visão da família: quanto cada carteira representa
            nomes = {c["id"]: c for c in auth.carteiras_do_usuario(conn, g.usuario)}
            for i in cid:
                r = montar_resumo(i)
                resumo["por_carteira"].append({
                    "id": i, "nome": nomes[i]["nome"], "dono": nomes[i]["dono_nome"],
                    "valor": r["total_valor"], "custo": r["total_custo"], "lucro": r["lucro"],
                    "lucro_pct": r["lucro_pct"],
                    "peso_pct": r["total_valor"] / resumo["total_valor"] * 100 if resumo["total_valor"] else 0})
            resumo["por_carteira"].sort(key=lambda x: -x["valor"])
        return jsonify(resumo)

    # ---------- Renda fixa ----------
    @app.get("/api/renda-fixa")
    def api_renda_fixa():
        cids = carteiras_leitura()
        ativos, aportes = listar_ativos(cids), listar_operacoes(cids)
        hoje_ = hoje()
        posicoes = portfolio.calcular_posicoes(aportes)
        cfg = configs_renda_fixa(ativos)
        rf, erros = avaliar_renda_fixa(ativos, aportes, [hoje_])
        vistos, itens = set(), []
        for a in ativos:
            t = a["ticker"]
            if t in vistos or not (a["classe"] == "renda_fixa" or t in cfg):
                continue
            vistos.add(t)
            p = posicoes.get(t)
            if not p or p["quantidade"] <= 0:
                continue
            c = cfg.get(t, a)
            if getattr(g, "vencimentos_tesouro", {}).get(t) and not c.get("vencimento"):
                c = {**c, "vencimento": g.vencimentos_tesouro[t]}
            r = (rf.get(t) or {}).get(hoje_)
            item = {"ticker": t, "nome": a.get("nome") or "", "indexador": c.get("indexador"),
                    "taxa": c.get("taxa"), "vencimento": c.get("vencimento"), "isento_ir": bool(c.get("isento_ir")),
                    "quantidade": p["quantidade"], "aplicado": p["custo"], "erro": erros.get(t)}
            if r:
                item.update({k: r[k] for k in ("bruto", "ir", "iof", "liquido", "rendimento", "dias_para_vencer",
                                                "vencido")})
                item["fonte"] = "tesouro" if c.get("indexador") == "tesouro" else "curva"
            else:  # sem indexador (ou índice indisponível): preço manual, sem cálculo de impostos
                valor = p["quantidade"] * a["preco_manual"] if a.get("preco_manual") else p["custo"]
                venc = c.get("vencimento")
                item.update({"bruto": valor, "ir": None, "iof": None, "liquido": None,
                             "rendimento": valor - p["custo"], "fonte": "manual" if a.get("preco_manual") else "custo",
                             "dias_para_vencer": (dt.date.fromisoformat(venc) - dt.date.fromisoformat(hoje_)).days
                             if venc else None, "vencido": bool(venc and venc <= hoje_)})
            item["rendimento_pct"] = item["rendimento"] / item["aplicado"] * 100 if item["aplicado"] else None
            itens.append(item)
        itens.sort(key=lambda x: (x["dias_para_vencer"] is None, x["dias_para_vencer"] or 0))
        com_liquido = [i for i in itens if i["liquido"] is not None]
        return jsonify({
            "itens": itens, "indexadores": rendafixa.INDEXADORES,
            "totais": {"aplicado": sum(i["aplicado"] for i in itens), "bruto": sum(i["bruto"] for i in itens),
                       "ir": sum(i["ir"] or 0 for i in itens), "iof": sum(i["iof"] or 0 for i in itens),
                       "liquido": sum(i["liquido"] for i in com_liquido) + sum(i["bruto"] for i in itens
                                                                                if i["liquido"] is None),
                       "sem_configuracao": sum(1 for i in itens if not i["indexador"])},
        })

    # ---------- Atualização das cotações ----------
    def tickers_de_mercado(cids=None):
        """Tickers com cotação de mercado: ativos das carteiras (ou de todas) e listas de acompanhamento."""
        if cids:
            f, ids = filtro_carteiras(cids)
            ativos = conn.execute(f"SELECT ticker, classe, preco_manual, indexador FROM ativos WHERE {f}", ids).fetchall()
            extras = conn.execute(f"SELECT ticker FROM acompanhamento WHERE {f}", ids).fetchall()
        else:
            ativos = conn.execute("SELECT ticker, classe, preco_manual, indexador FROM ativos").fetchall()
            extras = conn.execute("SELECT ticker FROM acompanhamento").fetchall()
        tickers = {a["ticker"] for a in ativos if not a["preco_manual"] and not a["indexador"]
                   and a["classe"] in ("acao", "fii", "etf", "bdr", "cripto", "exterior")}
        return sorted(tickers | {e["ticker"] for e in extras})

    def atualizar_cotacoes(tickers, forcar=False):
        ok, falhas = 0, {}
        for t in tickers:
            try:
                mercado.historico(t, forcar=forcar)
                ok += 1
            except MarketDataError as e:
                falhas[t] = str(e)
        return ok, falhas

    @app.post("/api/cotacoes/atualizar")
    def api_atualizar_cotacoes():
        cids = carteiras_leitura()
        ok, falhas = atualizar_cotacoes(tickers_de_mercado(cids), forcar=True)
        return jsonify({"ok": True, "atualizados": ok, "falhas": falhas,
                        "em": agora_brasilia().isoformat(timespec="minutes")})

    app.config["atualizar_cotacoes"] = lambda: atualizar_cotacoes(tickers_de_mercado())

    # ---------- Evolução e rentabilidade ----------
    @app.get("/api/evolucao")
    def api_evolucao():
        cids = carteiras_leitura()
        aportes = listar_operacoes(cids)
        hoje_ = hoje()
        precos, _, _, series = cotacoes(listar_ativos(cids), aportes, com_series=True)
        ev = evolucao.calcular_evolucao(aportes, listar_proventos(cids), series, precos, hoje_)
        referencias, falhas = {}, {}
        if ev["meses"]:
            inicio = ev["meses"][0]["mes"] + "-01"
            referencias, falhas = indices.series(inicio, hoje_)
        ev["referencias"] = referencias
        ev["nomes_referencias"] = NOMES_INDICES
        ev["falhas_referencias"] = falhas
        ev["resumo"] = evolucao.resumo_periodos(ev["meses"], referencias, hoje_) if ev["meses"] else {}
        return jsonify(ev)

    # ---------- Proventos ----------
    def hoje():
        return dt.date.today().isoformat()

    def listar_proventos(cids):
        f, ids = filtro_carteiras(cids)
        return db.rows(conn.execute(
            f"SELECT * FROM proventos WHERE {f} ORDER BY data_pagamento DESC, id DESC", ids))

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
        cid = carteiras_leitura()
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
        cid = carteiras_leitura()
        aportes = listar_operacoes(cid)
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

    # ---------- Fluxo: compras, vendas e recebidos ----------
    @app.get("/api/fluxo")
    def api_fluxo():
        cid = carteiras_leitura()
        hoje_ = hoje()
        try:
            inicio = dt.date.fromisoformat(request.args.get("inicio") or "0001-01-01").isoformat()
            fim = dt.date.fromisoformat(request.args.get("fim") or hoje_).isoformat()
        except ValueError:
            return erro("Período inválido.")
        if inicio > fim:
            return erro("A data inicial deve ser anterior à final.")
        return jsonify(portfolio.fluxo(listar_operacoes(cid), listar_proventos(cid), inicio, fim, hoje_))

    # ---------- Importação de extratos da B3 ----------
    def preco_em(ticker, data):
        """Fechamento do ativo na data (ou no último pregão antes dela), se houver cotação."""
        try:
            serie, _ = mercado.historico(ticker)
        except MarketDataError:
            return None
        anteriores = [c for d, c in serie if d <= data]
        return anteriores[-1] if anteriores else None

    @app.post("/api/importar/b3/previa")
    def api_importar_b3_previa():
        """Lê um ou mais extratos (Posição, Negociação, Movimentação, Eventos) e monta a prévia."""
        cid = carteira_atual("editar")
        arquivos = [a for a in request.files.getlist("arquivo") if a and a.filename]
        if not arquivos:
            return erro("Selecione o arquivo do extrato.")
        modo = request.form.get("modo") or "completa"  # completa | parcial (soma ao que já existe)
        previa = {"arquivos": [], "aportes": [], "proventos": [], "ignorados": [], "posicao": [], "modo": modo}
        por_arquivo, vistos = [], set()
        for arq in arquivos:
            conteudo = arq.read()
            digest = hashlib.sha256(conteudo).hexdigest()
            if digest in vistos:
                continue  # o mesmo arquivo selecionado duas vezes
            vistos.add(digest)
            try:
                r = analisar_extrato(conteudo, arq.filename)
            except ErroImportacao as e:
                return erro(f"{arq.filename}: {e}")
            anterior = conn.execute("SELECT importado_em FROM importacoes WHERE carteira_id = ? AND hash = ?",
                                    (cid, digest)).fetchone()
            previa["arquivos"].append({"nome": arq.filename, "tipo": r["tipo_arquivo"], "origem": r["origem"],
                                       "hash": digest, "ja_importado": anterior["importado_em"] if anterior else None})
            for chave in ("aportes", "proventos"):
                previa[chave].extend({**x, "origem": r["origem"]} for x in r[chave])
            if r["posicao"]:
                por_arquivo.append((arq.filename, r["origem"], r["posicao"]))
            previa["ignorados"].extend({**g, "arquivo": arq.filename} for g in r["ignorados"])
        previa["posicao"], previa["conflitos"] = mesclar_posicoes(por_arquivo)
        tipos = [a["tipo"] for a in previa["arquivos"]]
        if "movimentacao" in tipos and "eventos" in tipos:
            previa["aviso"] = ("Você enviou Movimentação e Eventos: os proventos podem aparecer duas vezes. "
                               "Desmarque os de um dos dois.")
        previa["tipo_arquivo"] = tipos[0] if len(tipos) == 1 else "varios"
        existentes = listar_operacoes(cid)
        marcar_duplicados(previa, listar_aportes(cid), listar_proventos(cid))
        previa["conciliacao"] = None
        estimadas = set()
        for p in previa["posicao"]:
            # Relatórios só com saldo: para ativos de bolsa, estima a quantidade pela cotação atual.
            if p.get("sem_quantidade") and p["classe"] in portfolio.CLASSES_INTEIRAS and p.get("valor_atual"):
                cotacao, _ = mercado.preco_atual(p["ticker"])
                if cotacao and round(p["valor_atual"] / cotacao) >= 1:
                    p["quantidade"] = float(round(p["valor_atual"] / cotacao))
                    p["preco_atual"], p["sem_quantidade"] = cotacao, False
                    estimadas.add(p["ticker"])
        # Tesouro informado só pelo saldo: quantidade de títulos pelo preço oficial do dia
        tesouros = {p["ticker"]: (p["ticker"], p.get("vencimento")) for p in previa["posicao"]
                    if p.get("tesouro") and p.get("sem_quantidade") and p.get("valor_atual")}
        if tesouros:
            pus, _, _ = tesouro.precos(tesouros, demo=modo_demo())
            for p in previa["posicao"]:
                serie_pu = pus.get(p["ticker"])
                if serie_pu:
                    pu = serie_pu[-1][1]
                    p["quantidade"] = round(p["valor_atual"] / pu, 2)
                    p["preco_atual"], p["sem_quantidade"] = pu, False
                    estimadas.add(p["ticker"])
        if previa["posicao"]:
            # parcial: o relatório mostra só uma instituição; a posição dele soma ao que já existe
            base = [] if modo == "parcial" else existentes
            conc = conciliar_posicao(previa["posicao"], base, previa["aportes"], hoje())
            for item in conc["posicoes_iniciais"]:
                item["quantidade_estimada"] = item["ticker"] in estimadas
            for item in conc["posicoes_iniciais"]:
                if item["preco"] is None and item["classe"] in portfolio.CLASSES_INTEIRAS:
                    item["preco"] = preco_em(item["ticker"], item["data"])
                    if item["preco"] is not None:
                        item["preco_origem"] = f"cotação de {item['data']} (estimado)"
            previa["conciliacao"] = conc
            ativos = {a["ticker"]: a for a in listar_ativos(cid)}
            previa["ajustes_ativos"] = [
                {"ticker": p["ticker"], "classe": p["classe"], "nome": p["nome"],
                 "classe_atual": ativos.get(p["ticker"], {}).get("classe"),
                 "indexador": "tesouro" if p.get("tesouro") and not p.get("sem_quantidade") else None,
                 "vencimento": p.get("vencimento"),
                 # renda fixa, Tesouro, fundos e previdência não têm cotação online: usa o valor do relatório
                 "preco_manual": round(p["preco_atual"], 6)
                 if p["classe"] not in portfolio.CLASSES_INTEIRAS and p["preco_atual"] else None}
                for p in previa["posicao"]]
            # a classe da posição (aba do extrato) é mais confiável que a sugerida pelo ticker
            classes = {p["ticker"]: p["classe"] for p in previa["posicao"]}
            for a in previa["aportes"]:
                a["classe"] = classes.get(a["ticker"], a["classe"])
        return jsonify(previa)

    @app.get("/api/importacoes")
    def api_importacoes():
        f, ids = filtro_carteiras(carteiras_leitura())
        return jsonify(db.rows(conn.execute(
            f"SELECT nome, origem, tipo, importado_em FROM importacoes WHERE {f} ORDER BY importado_em DESC LIMIT 50", ids)))

    @app.post("/api/importar/b3/confirmar")
    def api_importar_b3_confirmar():
        cid = carteira_atual("editar")
        d = request.get_json(silent=True) or {}
        try:  # cópia de segurança do banco antes de gravar a importação
            copia = backup.antes_de_importar(conn.path)
        except Exception as e:
            return erro(f"Importação cancelada: não foi possível fazer a cópia de segurança antes ({e}).", 500)
        novos_aportes, novos_proventos = d.get("aportes") or [], d.get("proventos") or []
        validos = []
        for a in novos_aportes:
            try:
                item = {"id": 10**12 + len(validos), "data": dt.date.fromisoformat(a["data"]).isoformat(),
                        "ticker": str(a["ticker"]).upper().strip(), "tipo": a.get("tipo", "compra"),
                        "quantidade": float(a["quantidade"]), "preco": float(a["preco"]),
                        "taxas": float(a.get("taxas") or 0), "classe": a.get("classe") or "acao",
                        "obs": a.get("obs") or "importado B3"}
            except (KeyError, TypeError, ValueError):
                return erro("Operação inválida na importação.")
            if item["tipo"] not in ("compra", "venda") or item["quantidade"] <= 0 or not item["ticker"] \
                    or item["classe"] not in portfolio.CLASSES:
                return erro(f"Operação inválida: {item['ticker']} em {item['data']}.")
            validos.append(item)
        try:
            portfolio.calcular_posicoes(listar_operacoes(cid) + validos)
        except ValueError as e:
            return erro(f"{e} Importe um período maior (desde a primeira compra) ou registre a posição "
                        "inicial antes de importar as vendas.", 409)
        for aj in d.get("ativos") or []:
            ticker = str(aj.get("ticker") or "").upper().strip()
            classe = aj.get("classe") if aj.get("classe") in portfolio.CLASSES else None
            if not ticker or not classe:
                continue
            manual = aj.get("preco_manual")
            manual = float(manual) if manual not in (None, "") else None
            indexador = aj.get("indexador") if aj.get("indexador") in rendafixa.INDEXADORES else None
            vencimento = aj.get("vencimento") or None
            conn.execute(
                """INSERT INTO ativos (carteira_id, ticker, nome, classe, preco_manual, indexador, vencimento)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(carteira_id, ticker) DO UPDATE SET classe = excluded.classe,
                   nome = CASE WHEN excluded.nome != '' THEN excluded.nome ELSE ativos.nome END,
                   preco_manual = COALESCE(excluded.preco_manual, ativos.preco_manual),
                   indexador = COALESCE(excluded.indexador, ativos.indexador),
                   vencimento = COALESCE(excluded.vencimento, ativos.vencimento)""",
                (cid, ticker, (aj.get("nome") or "")[:80], classe, manual, indexador, vencimento))
        existentes = {r["ticker"] for r in listar_ativos(cid)}
        for a in validos:
            if a["ticker"] not in existentes:
                conn.execute("INSERT INTO ativos (carteira_id, ticker, classe) VALUES (?, ?, ?)",
                             (cid, a["ticker"], a["classe"]))
                existentes.add(a["ticker"])
            conn.execute(
                """INSERT INTO aportes (carteira_id, data, ticker, tipo, quantidade, preco, taxas, obs)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (cid, a["data"], a["ticker"], a["tipo"], a["quantidade"], a["preco"], a["taxas"], a["obs"]))
        try:
            for p in novos_proventos:
                inserir_provento(cid, {**p, "obs": p.get("obs") or "importado B3"})
        except ValueError as e:
            conn.rollback()
            return erro(str(e))
        agora = dt.datetime.now().isoformat(timespec="minutes")
        for a in d.get("arquivos") or []:
            if a.get("hash"):
                conn.execute("""INSERT OR IGNORE INTO importacoes (carteira_id, hash, nome, origem, tipo, importado_em)
                                VALUES (?, ?, ?, ?, ?, ?)""",
                             (cid, a["hash"], (a.get("nome") or "")[:200], a.get("origem"), a.get("tipo"), agora))
        conn.commit()
        return jsonify({"ok": True, "copia_seguranca": os.path.basename(copia),
                        "aportes": len(validos), "proventos": len(novos_proventos),
                        "ativos": len(d.get("ativos") or [])}), 201

    # ---------- Eventos corporativos ----------
    @app.get("/api/eventos")
    def api_eventos():
        return jsonify({"itens": listar_eventos(carteiras_leitura()), "tipos": portfolio.TIPOS_EVENTO})

    @app.post("/api/eventos")
    def api_criar_evento():
        cid = carteira_atual("editar")
        d = request.get_json(silent=True) or {}
        ticker = (d.get("ticker") or "").upper().strip()
        tipo = d.get("tipo") or "desdobramento"
        try:
            data = dt.date.fromisoformat(d.get("data") or "").isoformat()
            fator = float(str(d.get("fator")).replace(",", "."))
        except (TypeError, ValueError):
            return erro("Data e fator do evento devem ser válidos.")
        if not ticker or tipo not in portfolio.TIPOS_EVENTO or fator <= 0:
            return erro("Ticker, tipo e fator (maior que zero) são obrigatórios.")
        duplicado = conn.execute("SELECT 1 FROM eventos WHERE carteira_id = ? AND ticker = ? AND data = ? AND tipo = ?",
                                 (cid, ticker, data, tipo)).fetchone()
        if duplicado:
            return erro("Este evento já está registrado.", 409)
        cur = conn.execute("INSERT INTO eventos (carteira_id, ticker, data, tipo, fator, obs) VALUES (?,?,?,?,?,?)",
                           (cid, ticker, data, tipo, fator, d.get("obs") or ""))
        conn.commit()
        return jsonify({"ok": True, "id": cur.lastrowid}), 201

    @app.delete("/api/eventos/<int:eid>")
    def api_remover_evento(eid):
        cid = carteira_atual("editar")
        restantes = portfolio.com_eventos(listar_aportes(cid), [e for e in listar_eventos(cid) if e["id"] != eid])
        try:
            portfolio.calcular_posicoes(restantes)
        except ValueError as e:
            return erro("Remover este evento deixaria uma venda maior que a posição: " + str(e), 409)
        conn.execute("DELETE FROM eventos WHERE id = ? AND carteira_id = ?", (eid, cid))
        conn.commit()
        return jsonify({"ok": True})

    @app.get("/api/eventos/sugeridos")
    def api_eventos_sugeridos():
        """Eventos informados pelas fontes que afetam a carteira e ainda não foram registrados."""
        cid = carteiras_leitura()
        ops, hoje_ = listar_operacoes(cid), hoje()
        registrados = {(e["ticker"], e["data"], e["tipo"]) for e in listar_eventos(cid)}
        primeiro = {}
        for a in ops:
            if a.get("tipo") != "evento":
                primeiro[a["ticker"]] = min(primeiro.get(a["ticker"], a["data"]), a["data"])
        itens, falhas = [], {}
        for t in sorted(primeiro):
            try:
                eventos, fonte = mercado.eventos(t, request.args.get("atualizar") == "1")
            except MarketDataError as e:
                falhas[t] = str(e)
                continue
            for e in eventos:
                if not (primeiro[t] <= e["data_com"] <= hoje_) or (t, e["data_com"], e["tipo"]) in registrados:
                    continue
                qtd = portfolio.quantidade_na_data(ops, t, e["data_com"])
                if qtd <= 0:
                    continue
                itens.append({"ticker": t, "data": e["data_com"], "tipo": e["tipo"], "fator": e["fator"],
                              "descricao": e.get("descricao") or "", "fonte": fonte,
                              "quantidade_antes": qtd, "quantidade_depois": qtd * e["fator"]})
        return jsonify({"itens": sorted(itens, key=lambda x: x["data"], reverse=True), "falhas": falhas})

    # ---------- Agenda e projeção de renda ----------
    @app.get("/api/proventos/agenda")
    def api_agenda():
        cids = carteiras_leitura()
        ops, hoje_ = listar_operacoes(cids), hoje()
        registrados = listar_proventos(cids)
        resumo = montar_resumo(cids)
        fonte_por_ticker, falhas = {}, {}
        for t in sorted({l["ticker"] for l in resumo["ativos"] if l["quantidade"] > 0}):
            try:
                fonte_por_ticker[t], _ = mercado.proventos(t)
            except MarketDataError as e:
                falhas[t] = str(e)
        proj = portfolio.projecao_renda(ops, fonte_por_ticker, registrados, hoje_)
        proj["numero_magico"] = portfolio.numero_magico(resumo["ativos"], fonte_por_ticker, registrados, ops, hoje_)
        metas = [r["meta_renda_mensal"] for r in conn.execute(
            f"SELECT meta_renda_mensal FROM carteiras WHERE id IN ({','.join('?' * len(cids))})", cids)]
        proj["meta_mensal"] = sum(m for m in metas if m) or None
        proj["falhas"] = falhas
        return jsonify(proj)

    @app.put("/api/carteiras/<int:cid>/meta-renda")
    def api_meta_renda(cid):
        if not auth.permissoes(conn, g.usuario, cid)["editar"]:
            raise ErroAcesso("Você não pode alterar esta carteira.", 403)
        d = request.get_json(silent=True) or {}
        try:
            valor = float(d["valor"]) if d.get("valor") not in (None, "") else None
        except (TypeError, ValueError):
            return erro("Valor inválido.")
        conn.execute("UPDATE carteiras SET meta_renda_mensal = ? WHERE id = ?", (valor, cid))
        conn.commit()
        return jsonify({"ok": True})

    # ---------- Imposto de Renda ----------
    @app.get("/api/impostos")
    def api_impostos():
        if (request.headers.get("X-Carteira") or request.args.get("carteira")) == "todas":
            return erro("O Imposto de Renda é calculado por pessoa: selecione a carteira de uma pessoa.", 400)
        cid = carteira_atual()
        hoje_ = hoje()
        try:
            ano = int(request.args.get("ano") or hoje_[:4])
        except ValueError:
            return erro("Ano inválido.")
        ops, ativos, provs = listar_operacoes(cid), listar_ativos(cid), listar_proventos(cid)
        classes = {a["ticker"]: a["classe"] for a in ativos}
        apuracao = impostos.apurar(ops, classes, ate_mes=hoje_[:7])
        meses = [m for m in apuracao if m["mes"].startswith(str(ano))]
        ultimo = meses[-1] if meses else None
        anos = sorted({int(o["data"][:4]) for o in ops} | {int(p["data_pagamento"][:4]) for p in provs}
                      | {int(hoje_[:4])}, reverse=True)
        return jsonify({
            "ano": ano, "anos": anos, "apuracao": meses, "nomes_pools": impostos.NOME_POOL,
            "resumo": {
                "imposto_devido": sum(m["imposto_devido"] for m in meses),
                "darf_total": sum(m["darf"] for m in meses),
                "lucro_isento": sum(m["lucro_isento"] for m in meses),
                "vendas_acoes": sum(m["vendas_acoes"] for m in meses),
                "prejuizo_acumulado": ultimo["prejuizo_acumulado"] if ultimo else {},
                "darfs_pendentes": [{"mes": m["mes"], "valor": m["darf"], "vencimento": m["vencimento"]}
                                    for m in meses if m["darf"] and m["vencimento"] >= hoje_],
            },
            "declaracao": impostos.declaracao(ops, provs, ativos, apuracao, ano),
        })

    # ---------- Metas por categoria e diversificação ----------
    @app.get("/api/metas-classe")
    def api_metas_classe():
        cid = carteira_atual()
        return jsonify({"metas": metas_classe(cid), "classes": portfolio.CLASSES})

    @app.put("/api/metas-classe")
    def api_salvar_metas_classe():
        cid = carteira_atual("editar")
        d = request.get_json(silent=True) or {}
        try:
            metas = {c: float(v) for c, v in (d.get("metas") or {}).items() if v not in (None, "") and c in portfolio.CLASSES}
        except (TypeError, ValueError):
            return erro("As metas devem ser números.")
        if any(v < 0 for v in metas.values()):
            return erro("As metas não podem ser negativas.")
        conn.execute("DELETE FROM metas_classe WHERE carteira_id = ?", (cid,))
        conn.executemany("INSERT INTO metas_classe (carteira_id, classe, meta_pct) VALUES (?, ?, ?)",
                         [(cid, c, v) for c, v in metas.items() if v > 0])
        conn.commit()
        return jsonify({"ok": True, "soma": sum(metas.values())})

    def setor_do_ativo(a):
        if a.get("setor"):
            return a["setor"]
        classe = a.get("classe")
        if classe in ("acao", "bdr"):
            try:
                f, _ = mercado.fundamentos(a["ticker"])
                if f and f.get("setor"):
                    return f["setor"]
            except MarketDataError:
                pass
            return "Setor não informado"
        return {"fii": "Fundos imobiliários", "etf": "ETFs", "renda_fixa": "Renda fixa", "cripto": "Criptoativos",
                "exterior": "Exterior"}.get(classe, "Outros")

    def indexador_do_ativo(a):
        classe, idx, nome = a.get("classe"), (a.get("indexador") or ""), a["ticker"].upper()
        if classe != "renda_fixa":
            return "Renda variável" if classe in ("acao", "fii", "etf", "bdr") else portfolio.CLASSES.get(classe, "Outros")
        if idx in ("cdi", "selic") or "SELIC" in nome:
            return "Pós-fixado (CDI/Selic)"
        if idx == "ipca" or "IPCA" in nome:
            return "Inflação (IPCA+)"
        if idx == "pre" or "PREFIXADO" in nome:
            return "Prefixado"
        return "Renda fixa sem indexador"

    @app.get("/api/diversificacao")
    def api_diversificacao():
        cids = carteiras_leitura()
        resumo = montar_resumo(cids)
        ativos = {a["ticker"]: a for a in listar_ativos(cids)}
        total = resumo["total_valor"] or 0
        setores, indexadores, prazos, concentracao = defaultdict(float), defaultdict(float), defaultdict(float), []
        hoje_d = dt.date.fromisoformat(hoje())
        for l in resumo["ativos"]:
            if l["quantidade"] <= 0:
                continue
            a = {**ativos.get(l["ticker"], {}), "ticker": l["ticker"], "classe": l["classe"]}
            setores[setor_do_ativo(a)] += l["valor"]
            indexadores[indexador_do_ativo(a)] += l["valor"]
            venc = a.get("vencimento")
            if l["classe"] in ("acao", "fii", "etf", "bdr", "cripto") or "TESOURO" in l["ticker"].upper():
                prazo = "Resgate em até 2 dias úteis"
            elif venc:
                anos = (dt.date.fromisoformat(venc) - hoje_d).days / 365
                prazo = "Vence em até 1 ano" if anos <= 1 else "Vence em 1 a 3 anos" if anos <= 3 else "Vence em mais de 3 anos"
            else:
                prazo = "Prazo não informado"
            prazos[prazo] += l["valor"]
            if total and l["valor"] / total * 100 >= LIMITE_CONCENTRACAO:
                concentracao.append({"tipo": "ativo", "nome": l["ticker"], "pct": l["valor"] / total * 100})
        def lista(d):
            return [{"nome": k, "valor": v, "pct": v / total * 100 if total else 0} for k, v in sorted(d.items(), key=lambda x: -x[1])]
        for s_ in lista(setores):
            if s_["pct"] >= LIMITE_SETOR and s_["nome"] not in ("Renda fixa", "Setor não informado"):
                concentracao.append({"tipo": "setor", "nome": s_["nome"], "pct": s_["pct"]})
        metas = metas_classe(cids)
        soma = sum(metas.values())
        categorias = {c["classe"]: c for c in resumo["categorias"]}
        comparacao = [{"classe": c, "rotulo": portfolio.CLASSES[c],
                       "atual_pct": categorias[c]["peso_pct"] if c in categorias else 0.0,
                       "meta_pct": metas.get(c, 0) / soma * 100 if soma else None,
                       "valor": categorias[c]["valor"] if c in categorias else 0.0}
                      for c in portfolio.CLASSES if c in categorias or metas.get(c)]
        return jsonify({"setores": lista(setores), "indexadores": lista(indexadores),
                        "prazos": lista(prazos), "concentracao": concentracao, "metas_classe": metas,
                        "categorias": comparacao, "limites": {"ativo": LIMITE_CONCENTRACAO, "setor": LIMITE_SETOR}})

    # ---------- Lista de acompanhamento ----------
    def analise_ativo(ticker):
        """Cotação, variação do dia, DY, P/L, P/VP, preço-teto (Bazin) e preço justo (Graham)."""
        out = {"ticker": ticker}
        try:
            serie, fonte = mercado.historico(ticker)
            out["preco"], out["fonte"] = serie[-1][1], fonte
            out["variacao_pct"] = (serie[-1][1] / serie[-2][1] - 1) * 100 if len(serie) > 1 and serie[-2][1] else None
        except MarketDataError as e:
            out["erro"] = str(e)
            return out
        try:
            provs, _ = mercado.proventos(ticker)
        except MarketDataError:
            provs = []
        um_ano = (dt.date.today() - dt.timedelta(days=365)).isoformat()
        div12 = sum(float(p["valor"]) for p in provs if um_ano < p["data_com"] <= hoje())
        out["proventos_12m"] = div12
        out["dy_pct"] = div12 / out["preco"] * 100 if out["preco"] else None
        out["preco_teto_bazin"] = div12 / 0.06 if div12 else None  # DY mínimo de 6% ao ano
        try:
            f, _ = mercado.fundamentos(ticker)
        except MarketDataError:
            f = {}
        f = f or {}
        out.update({k: f.get(k) for k in ("pl", "pvp", "lpa", "vpa", "setor")})
        lpa, vpa = f.get("lpa"), f.get("vpa")
        out["preco_justo_graham"] = (22.5 * lpa * vpa) ** 0.5 if lpa and vpa and lpa > 0 and vpa > 0 else None
        for chave, nome in (("preco_teto_bazin", "margem_bazin_pct"), ("preco_justo_graham", "margem_graham_pct")):
            out[nome] = (out[chave] / out["preco"] - 1) * 100 if out.get(chave) and out["preco"] else None
        return out

    @app.get("/api/acompanhamento")
    def api_acompanhamento():
        cids = carteiras_leitura()
        f, ids = filtro_carteiras(cids)
        itens = db.rows(conn.execute(f"SELECT * FROM acompanhamento WHERE {f} ORDER BY ticker", ids))
        alertas = db.rows(conn.execute(f"SELECT * FROM alertas_preco WHERE {f} ORDER BY ticker, preco", ids))
        posicoes = portfolio.calcular_posicoes(listar_operacoes(cids))
        vistos, out = set(), []
        for i in itens:
            if i["ticker"] in vistos:
                continue
            vistos.add(i["ticker"])
            r = analise_ativo(i["ticker"])
            r.update({"id": i["id"], "carteira_id": i["carteira_id"], "obs": i["obs"] or "",
                      "quantidade": (posicoes.get(i["ticker"]) or {}).get("quantidade", 0),
                      "alertas": [a for a in alertas if a["ticker"] == i["ticker"]]})
            out.append(r)
        return jsonify({"itens": out, "alertas_sem_lista": [a for a in alertas if a["ticker"] not in vistos]})

    @app.post("/api/acompanhamento")
    def api_add_acompanhamento():
        cid = carteira_atual("editar")
        d = request.get_json(silent=True) or {}
        ticker = (d.get("ticker") or "").upper().strip()
        if not ticker:
            return erro("Informe o ticker.")
        try:
            mercado.historico(ticker)
        except MarketDataError as e:
            return erro(f"Não encontrei cotações para {ticker}: {e}", 404)
        conn.execute("INSERT OR IGNORE INTO acompanhamento (carteira_id, ticker, obs) VALUES (?, ?, ?)",
                     (cid, ticker, d.get("obs") or ""))
        conn.commit()
        return jsonify({"ok": True}), 201

    @app.delete("/api/acompanhamento/<int:iid>")
    def api_remover_acompanhamento(iid):
        cid = carteira_atual("editar")
        row = conn.execute("SELECT ticker FROM acompanhamento WHERE id = ? AND carteira_id = ?", (iid, cid)).fetchone()
        if row:
            conn.execute("DELETE FROM alertas_preco WHERE carteira_id = ? AND ticker = ?", (cid, row["ticker"]))
            conn.execute("DELETE FROM acompanhamento WHERE id = ?", (iid,))
            conn.commit()
        return jsonify({"ok": True})

    @app.post("/api/alertas-preco")
    def api_add_alerta_preco():
        cid = carteira_atual("editar")
        d = request.get_json(silent=True) or {}
        ticker, condicao = (d.get("ticker") or "").upper().strip(), d.get("condicao")
        try:
            preco = float(str(d.get("preco")).replace(",", "."))
        except (TypeError, ValueError):
            return erro("Preço inválido.")
        if not ticker or condicao not in ("acima", "abaixo") or preco <= 0:
            return erro("Informe ticker, condição (acima/abaixo) e preço.")
        conn.execute("INSERT INTO alertas_preco (carteira_id, ticker, condicao, preco) VALUES (?, ?, ?, ?)",
                     (cid, ticker, condicao, preco))
        conn.commit()
        return jsonify({"ok": True}), 201

    @app.delete("/api/alertas-preco/<int:aid>")
    def api_remover_alerta_preco(aid):
        cid = carteira_atual("editar")
        conn.execute("DELETE FROM alertas_preco WHERE id = ? AND carteira_id = ?", (aid, cid))
        conn.commit()
        return jsonify({"ok": True})

    # ---------- Alertas ----------
    def calcular_alertas(cids):
        """Alertas da carteira (ou das carteiras). nivel: 'alerta' (pede atenção) ou 'info'."""
        hoje_ = hoje()
        hoje_d = dt.date.fromisoformat(hoje_)
        em = lambda dias: (hoje_d + dt.timedelta(days=dias)).isoformat()  # noqa: E731
        out = []

        def add(tipo, nivel, titulo, texto, ref):
            out.append({"tipo": tipo, "nivel": nivel, "titulo": titulo, "texto": texto,
                        "chave": f"{','.join(map(str, cids))}:{tipo}:{ref}"})

        resumo = montar_resumo(cids)
        ops = listar_operacoes(cids)
        for l in resumo["ativos"]:
            if l["quantidade"] <= 0:
                continue
            if l.get("variacao_pct") is not None and l["variacao_pct"] <= -5:
                add("queda", "alerta", f"{l['ticker']} caiu {l['variacao_pct']:.1f}% no dia".replace(".", ","),
                    "Queda forte no último pregão.", f"{l['ticker']}:{hoje_}")
            if l["peso_pct"] >= LIMITE_CONCENTRACAO:
                add("concentracao", "alerta", f"{l['ticker']} é {l['peso_pct']:.0f}% da carteira",
                    f"Acima do limite de {LIMITE_CONCENTRACAO:.0f}% em um único ativo.", l["ticker"])
        for c in resumo.get("categorias", []):
            if c.get("desvio_pct") is not None and abs(c["desvio_pct"]) >= LIMITE_DESVIO and metas_classe(cids):
                acima = c["desvio_pct"] > 0
                add("desvio", "alerta", f"{c['rotulo']} {'acima' if acima else 'abaixo'} da meta",
                    f"Atual {c['peso_pct']:.1f}% x meta {c['meta_pct']:.1f}%. "
                    f"{'Direcione os próximos aportes para outras categorias.' if acima else 'Priorize esta categoria nos próximos aportes.'}"
                    .replace(".", ",", 2), c["classe"])

        f, ids = filtro_carteiras(cids)
        for a in db.rows(conn.execute(f"SELECT * FROM alertas_preco WHERE {f}", ids)):
            try:
                preco = mercado.historico(a["ticker"])[0][-1][1]
            except MarketDataError:
                continue
            if (a["condicao"] == "acima" and preco >= a["preco"]) or (a["condicao"] == "abaixo" and preco <= a["preco"]):
                add("preco", "alerta", f"{a['ticker']} {'subiu acima' if a['condicao'] == 'acima' else 'caiu abaixo'} de {brl(a['preco'])}",
                    f"Cotação atual: {brl(preco)}.", f"{a['id']}:{hoje_}")

        fonte = {}
        for t in {l["ticker"] for l in resumo["ativos"] if l["quantidade"] > 0 and l["classe"] in ("acao", "fii", "etf", "bdr")}:
            try:
                fonte[t], _ = mercado.proventos(t)
            except MarketDataError:
                pass
        for item in portfolio.agenda_proventos(ops, fonte, listar_proventos(cids), hoje_):
            if item["status"] == "anunciado" and item.get("data_com") and item["data_com"] <= em(7):
                add("data_com", "info", f"Data com de {item['ticker']} em {fmt_data(item['data_com'])}",
                    f"Quem tiver o ativo ao fim do dia recebe {brl(item['valor_unitario'])} por ação/cota "
                    f"(pagamento {fmt_data(item['data_pagamento'])}).", f"{item['ticker']}:{item['data_com']}")
            elif item["status"] in ("a_receber", "lancado") and item["data_pagamento"] <= em(7):
                add("pagamento", "info", f"{item['ticker']} paga {brl(item['valor_total'])} em {fmt_data(item['data_pagamento'])}",
                    "Provento a receber nos próximos dias.", f"{item['ticker']}:{item['data_pagamento']}")

        for a in listar_ativos(cids):
            venc = a.get("vencimento") or (getattr(g, "vencimentos_tesouro", {}) or {}).get(a["ticker"])
            if venc and hoje_ <= venc <= em(30) and (portfolio.calcular_posicoes(ops).get(a["ticker"]) or {}).get("quantidade", 0) > 0:
                add("vencimento", "alerta", f"{a['ticker']} vence em {fmt_data(venc)}",
                    "Planeje o reinvestimento do valor.", f"{a['ticker']}:{venc}")

        if len(cids) == 1:
            classes = {a["ticker"]: a["classe"] for a in listar_ativos(cids)}
            for m in impostos.apurar(ops, classes, ate_mes=hoje_[:7]):
                if m["darf"] and hoje_ <= m["vencimento"] <= em(10):
                    add("darf", "alerta", f"DARF de {brl(m['darf'])} vence em {fmt_data(m['vencimento'])}",
                        f"Imposto sobre as vendas de {m['mes'][5:]}/{m['mes'][:4]} (código 6015).", m["mes"])
        ordem = {"alerta": 0, "info": 1}
        return sorted(out, key=lambda x: ordem[x["nivel"]])

    @app.get("/api/alertas")
    def api_alertas():
        return jsonify({"itens": calcular_alertas(carteiras_leitura()),
                        "telegram": bool(os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"))})

    app.config["calcular_alertas"] = calcular_alertas

    @app.post("/api/alertas/teste-telegram")
    def api_teste_telegram():
        exigir_admin()
        try:
            notificacoes.enviar_telegram("✅ Carteira de Aportes: os alertas por Telegram estão funcionando.")
        except Exception as e:
            return erro(f"Não foi possível enviar: {e}", 502)
        return jsonify({"ok": True})

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


def cotacoes_automaticas(app):
    """Enquanto o servidor estiver no ar, atualiza as cotações durante o pregão (e uma vez após o fechamento)."""
    import threading
    import time

    def laco():
        fechamento_feito = None
        while True:
            try:
                agora = agora_brasilia()
                depois_do_fechamento = agora.hour >= 18 and fechamento_feito != agora.date()
                if em_pregao() or depois_do_fechamento:
                    with app.app_context():
                        app.config["atualizar_cotacoes"]()
                        app.config["conn"].close()
                    if depois_do_fechamento and not em_pregao():
                        fechamento_feito = agora.date()
            except Exception as e:  # nunca derruba o servidor
                print(f"[cotacoes] falhou: {e}")
            time.sleep(intervalo_pregao() * 60)

    threading.Thread(target=laco, name="cotacoes", daemon=True).start()


if __name__ == "__main__":
    aplicacao = create_app()
    if os.environ.get("CARTEIRA_BACKUP", "1") != "0":
        backup.iniciar_automatico(aplicacao.config["conn"].path)
    notificacoes.iniciar_automatico(aplicacao)
    if os.environ.get("CARTEIRA_ATUALIZACAO_AUTOMATICA", "1") != "0":
        cotacoes_automaticas(aplicacao)
    aplicacao.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)),
                  debug=os.environ.get("FLASK_DEBUG") == "1")
