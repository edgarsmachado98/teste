"""Servidor web: gestão de aportes e análise de mercado."""
import datetime as dt
import os

from flask import Flask, jsonify, render_template, request



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

from carteira import analysis, db, portfolio, providers  # noqa: E402  (após carregar o .env)
from carteira.market import Mercado, MarketDataError, modo_demo  # noqa: E402


def create_app(db_path=None, fonte_mercado=None):
    app = Flask(__name__)
    conn = db.connect(db_path)
    mercado = Mercado(conn, fonte_mercado)
    app.config["conn"] = conn

    def erro(msg, status=400):
        return jsonify({"erro": msg}), status

    def listar_ativos():
        return db.rows(conn.execute("SELECT * FROM ativos ORDER BY ticker"))

    def listar_aportes():
        return db.rows(conn.execute("SELECT * FROM aportes ORDER BY data DESC, id DESC"))

    def montar_resumo():
        ativos = listar_ativos()
        aportes = listar_aportes()
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
                               tipos_provento=portfolio.TIPOS_PROVENTO, demo=modo_demo())

    # ---------- Ativos ----------
    @app.get("/api/ativos")
    def api_ativos():
        return jsonify(listar_ativos())

    @app.post("/api/ativos")
    def api_criar_ativo():
        d = request.get_json(force=True) or {}
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
            """INSERT INTO ativos (ticker, nome, classe, meta_pct, preco_manual)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(ticker) DO UPDATE SET nome=excluded.nome, classe=excluded.classe,
               meta_pct=excluded.meta_pct, preco_manual=excluded.preco_manual""",
            (ticker, d.get("nome") or "", classe, meta, manual))
        conn.commit()
        return jsonify({"ok": True, "ticker": ticker}), 201

    @app.delete("/api/ativos/<ticker>")
    def api_remover_ativo(ticker):
        ticker = ticker.upper()
        em_uso = conn.execute("SELECT COUNT(*) FROM aportes WHERE ticker = ?", (ticker,)).fetchone()[0]
        if em_uso:
            return erro("Ativo possui aportes registrados; remova-os antes.", 409)
        conn.execute("DELETE FROM ativos WHERE ticker = ?", (ticker,))
        conn.commit()
        return jsonify({"ok": True})

    # ---------- Aportes ----------
    @app.get("/api/aportes")
    def api_aportes():
        return jsonify(listar_aportes())

    @app.post("/api/aportes")
    def api_criar_aporte():
        d = request.get_json(force=True) or {}
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
        aportes = listar_aportes() + [{"id": 10**12, "data": data, "ticker": ticker, "tipo": tipo,
                                       "quantidade": qtd, "preco": preco, "taxas": taxas}]
        try:
            portfolio.calcular_posicoes(aportes)
        except ValueError as e:
            return erro(str(e))
        if not conn.execute("SELECT 1 FROM ativos WHERE ticker = ?", (ticker,)).fetchone():
            conn.execute("INSERT INTO ativos (ticker, classe) VALUES (?, ?)",
                         (ticker, d.get("classe") or "acao"))
        cur = conn.execute(
            "INSERT INTO aportes (data, ticker, tipo, quantidade, preco, taxas, obs) VALUES (?,?,?,?,?,?,?)",
            (data, ticker, tipo, qtd, preco, taxas, d.get("obs") or ""))
        conn.commit()
        return jsonify({"ok": True, "id": cur.lastrowid}), 201

    @app.delete("/api/aportes/<int:aid>")
    def api_remover_aporte(aid):
        restantes = [a for a in listar_aportes() if a["id"] != aid]
        try:
            portfolio.calcular_posicoes(restantes)
        except ValueError as e:
            return erro("Remover este aporte deixaria uma venda sem posição: " + str(e), 409)
        conn.execute("DELETE FROM aportes WHERE id = ?", (aid,))
        conn.commit()
        return jsonify({"ok": True})

    # ---------- Carteira ----------
    @app.get("/api/carteira")
    def api_carteira():
        resumo = montar_resumo()
        resumo["evolucao_aportes"] = portfolio.aportes_por_mes(listar_aportes())
        prov = portfolio.resumo_proventos(listar_proventos(), resumo, hoje())
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

    def listar_proventos():
        return db.rows(conn.execute("SELECT * FROM proventos ORDER BY data_pagamento DESC, id DESC"))

    def inserir_provento(d):
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
            """INSERT INTO proventos (ticker, tipo, data_com, data_pagamento, quantidade,
               valor_unitario, valor_total, obs) VALUES (?,?,?,?,?,?,?,?)""",
            (ticker, tipo, data_com, pagamento, qtd, unit, total, d.get("obs") or ""))
        return cur.lastrowid

    @app.get("/api/proventos")
    def api_proventos():
        lista = listar_proventos()
        return jsonify({"itens": lista,
                        "resumo": portfolio.resumo_proventos(lista, montar_resumo(), hoje())})

    @app.post("/api/proventos")
    def api_criar_provento():
        try:
            pid = inserir_provento(request.get_json(force=True) or {})
        except ValueError as e:
            return erro(str(e))
        conn.commit()
        return jsonify({"ok": True, "id": pid}), 201

    @app.delete("/api/proventos/<int:pid>")
    def api_remover_provento(pid):
        conn.execute("DELETE FROM proventos WHERE id = ?", (pid,))
        conn.commit()
        return jsonify({"ok": True})

    @app.get("/api/proventos/estimar")
    def api_estimar_proventos():
        """Busca proventos por ação nas fontes e calcula quanto você recebeu/receberá."""
        aportes = listar_aportes()
        forcar = request.args.get("atualizar") == "1"
        por_ticker, fontes, falhas = {}, {}, {}
        for t in sorted({a["ticker"] for a in aportes}):
            try:
                por_ticker[t], fontes[t] = mercado.proventos(t, forcar)
            except MarketDataError as e:
                falhas[t] = str(e)
        itens = portfolio.estimar_proventos(aportes, por_ticker, listar_proventos(), hoje())
        return jsonify({"itens": itens, "fontes": fontes, "falhas": falhas})

    @app.post("/api/proventos/importar")
    def api_importar_proventos():
        itens = (request.get_json(force=True) or {}).get("itens") or []
        try:
            for d in itens:
                inserir_provento({**d, "obs": d.get("obs") or "importado"})
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
        manual = conn.execute("SELECT preco_manual FROM ativos WHERE ticker = ?", (ticker,)).fetchone()
        preco, _ = mercado.preco_atual(ticker, manual["preco_manual"] if manual else None)
        out["preco"] = preco
        out["dividend_yield"] = portfolio.dividend_yield(itens, preco, hoje())
        out["proventos_por_ano"] = portfolio.proventos_por_ano(itens)
        out["proventos"] = sorted(itens, key=lambda x: x["data_com"], reverse=True)[:24]
        return jsonify(out)

    @app.post("/api/sugestao")
    def api_sugestao():
        d = request.get_json(force=True) or {}
        try:
            valor = float(d.get("valor"))
            return jsonify(portfolio.sugerir_aporte(montar_resumo(), valor))
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
