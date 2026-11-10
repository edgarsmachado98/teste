import datetime as dt

import pytest

from carteira import notificacoes, portfolio
from tests.conftest import cliente_logado


def test_aplicar_metas_classe():
    ativos = [{"ticker": "A", "classe": "acao", "meta_pct": 1}, {"ticker": "B", "classe": "acao", "meta_pct": 3},
              {"ticker": "F", "classe": "fii", "meta_pct": 0}, {"ticker": "G", "classe": "fii", "meta_pct": 0},
              {"ticker": "H", "classe": "fii", "meta_pct": 0}]
    r = {a["ticker"]: a["meta_pct"] for a in portfolio.aplicar_metas_classe(
        ativos, {"acao": 60, "fii": 40}, com_posicao={"A", "B", "F", "G"})}
    assert r["A"] == pytest.approx(15) and r["B"] == pytest.approx(45)
    assert r["F"] == pytest.approx(20) and r["G"] == pytest.approx(20) and r["H"] == 0  # H sem posição
    assert portfolio.aplicar_metas_classe(ativos, {}) is ativos


def serie(preco_ontem, preco_hoje):
    hoje = dt.date.today()
    return [((hoje - dt.timedelta(days=400)).isoformat(), preco_ontem * 0.9),
            ((hoje - dt.timedelta(days=1)).isoformat(), preco_ontem), (hoje.isoformat(), preco_hoje)]


class Fonte:
    nome = "brapi"
    PRECOS = {"AAAA3": (10, 10), "BBBB3": (20, 18), "FUND11": (100, 100), "WATC3": (50, 40)}

    def historico(self, t):
        if t not in self.PRECOS:
            raise RuntimeError("não encontrado")
        return serie(*self.PRECOS[t])

    def proventos(self, t):
        hoje = dt.date.today()
        if t == "WATC3":
            return [{"data_com": (hoje - dt.timedelta(days=100)).isoformat(), "data_pagamento": None, "valor": 3.0, "tipo": "dividendo"}]
        if t == "AAAA3":
            return [{"data_com": (hoje + dt.timedelta(days=3)).isoformat(),
                     "data_pagamento": (hoje + dt.timedelta(days=20)).isoformat(), "valor": 0.5, "tipo": "dividendo"}]
        return []

    def fundamentos(self, t):
        return {"setor": "Bancos" if t == "AAAA3" else "Energia", "lpa": 4.0, "vpa": 25.0, "pl": 10.0, "pvp": 1.6}


@pytest.fixture
def c(novo_app):
    return cliente_logado(novo_app([Fonte()]))


def compras(c):
    hoje = dt.date.today()
    d = (hoje - dt.timedelta(days=200)).isoformat()
    c.post("/api/aportes", json={"data": d, "ticker": "AAAA3", "quantidade": 100, "preco": 9})     # 1.000
    c.post("/api/aportes", json={"data": d, "ticker": "BBBB3", "quantidade": 100, "preco": 20})    # 1.800
    c.post("/api/aportes", json={"data": d, "ticker": "FUND11", "classe": "fii", "quantidade": 2, "preco": 100})  # 200
    c.post("/api/ativos", json={"ticker": "CDB X", "classe": "renda_fixa", "preco_manual": 1000,
                                "vencimento": (hoje + dt.timedelta(days=20)).isoformat()})
    c.post("/api/aportes", json={"data": d, "ticker": "CDB X", "classe": "renda_fixa", "quantidade": 1, "preco": 1000})


def test_metas_classe_e_sugestao(c):
    compras(c)
    assert c.put("/api/metas-classe", json={"metas": {"acao": 50, "fii": 30, "renda_fixa": 20}}).status_code == 200
    cats = {k["classe"]: k for k in c.get("/api/carteira").get_json()["categorias"]}
    assert cats["acao"]["meta_pct"] == pytest.approx(50) and cats["fii"]["meta_pct"] == pytest.approx(30)
    assert cats["fii"]["desvio_pct"] == pytest.approx(200 / 4000 * 100 - 30)
    s = c.post("/api/sugestao", json={"valor": 1000}).get_json()
    valores = {x["ticker"]: x["valor"] for x in s["sugestoes"]}
    assert "BBBB3" not in valores  # ações já acima da meta da categoria
    assert max(valores, key=valores.get) == "FUND11"  # FII é a categoria mais abaixo da meta
    assert valores["FUND11"] == 800 and valores["AAAA3"] == 170
    assert c.get("/api/metas-classe").get_json()["metas"]["renda_fixa"] == 20


def test_diversificacao(c):
    compras(c)
    c.post("/api/ativos", json={"ticker": "BBBB3", "classe": "acao", "setor": "Energia elétrica"})
    d = c.get("/api/diversificacao").get_json()
    setores = {s["nome"]: s["valor"] for s in d["setores"]}
    assert setores == {"Energia elétrica": 1800, "Renda fixa": 1000, "Bancos": 1000, "Fundos imobiliários": 200}
    idx = {s["nome"] for s in d["indexadores"]}
    assert idx == {"Renda variável", "Renda fixa sem indexador"}
    prazos = {s["nome"]: s["valor"] for s in d["prazos"]}
    assert prazos["Vence em até 1 ano"] == 1000 and prazos["Resgate em até 2 dias úteis"] == 3000
    conc = {(x["tipo"], x["nome"]) for x in d["concentracao"]}
    assert ("ativo", "BBBB3") in conc and ("setor", "Energia elétrica") in conc


def test_acompanhamento_e_alertas(c):
    compras(c)
    assert c.post("/api/acompanhamento", json={"ticker": "NAOEXISTE"}).status_code == 404
    assert c.post("/api/acompanhamento", json={"ticker": "watc3"}).status_code == 201
    item = c.get("/api/acompanhamento").get_json()["itens"][0]
    assert item["preco"] == 40 and item["dy_pct"] == pytest.approx(7.5)
    assert item["preco_teto_bazin"] == pytest.approx(50) and item["margem_bazin_pct"] == pytest.approx(25)
    assert item["preco_justo_graham"] == pytest.approx((22.5 * 4 * 25) ** .5)
    assert c.post("/api/alertas-preco", json={"ticker": "WATC3", "condicao": "abaixo", "preco": 45}).status_code == 201

    alertas = c.get("/api/alertas").get_json()["itens"]
    tipos = {a["tipo"] for a in alertas}
    assert {"preco", "queda", "concentracao", "data_com", "vencimento"} <= tipos
    queda = next(a for a in alertas if a["tipo"] == "queda")
    assert "BBBB3" in queda["titulo"]

    enviados = []
    app = c.application
    assert notificacoes.verificar_e_enviar(app, enviados.append) == len(alertas)
    assert notificacoes.verificar_e_enviar(app, enviados.append) == 0  # não repete
    assert "<b>" in enviados[0]

    iid = item["id"]
    assert c.delete(f"/api/acompanhamento/{iid}").status_code == 200
    assert c.get("/api/acompanhamento").get_json()["itens"] == []


def test_alerta_darf(c):
    hoje = dt.date.today()
    mes_passado = (hoje.replace(day=1) - dt.timedelta(days=1)).replace(day=10).isoformat()
    c.post("/api/aportes", json={"data": "2024-01-02", "ticker": "AAAA3", "quantidade": 3000, "preco": 5})
    c.post("/api/aportes", json={"data": mes_passado, "ticker": "AAAA3", "tipo": "venda", "quantidade": 3000, "preco": 10})
    alertas = c.get("/api/alertas").get_json()["itens"]
    vence = next((a for a in alertas if a["tipo"] == "darf"), None)
    ultimo_dia = (hoje.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
    if (ultimo_dia - hoje).days <= 10:
        assert vence and "2.250" in vence["titulo"]  # 15.000 x 15%
    c.environ_base["HTTP_X_CARTEIRA"] = "todas"
    # na visão da família (uma carteira só aqui) o cálculo de DARF não é feito por carteira consolidada


def test_pwa_publico(novo_app):
    app = novo_app([Fonte()])
    anon = app.test_client()
    m = anon.get("/manifest.webmanifest")
    assert m.status_code == 200 and m.get_json()["display"] == "standalone"
    sw = anon.get("/sw.js")
    assert sw.status_code == 200 and b"caches" in sw.data
