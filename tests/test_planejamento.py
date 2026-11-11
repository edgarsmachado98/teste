import datetime as dt

import pytest

from carteira import planejamento as plan
from carteira.market import serie_simulada
from tests.conftest import cliente_logado


def fonte(t):
    return serie_simulada(t, dias=300)


@pytest.fixture
def com_modulo(monkeypatch):
    monkeypatch.delenv("CARTEIRA_DEMO", raising=False)
    monkeypatch.setenv("CARTEIRA_MODULOS", "planejamento")


def cat(c, tipo, nome):
    cats = c.get("/api/plan/categorias").get_json()["categorias"]
    return next(x["id"] for x in cats if x["tipo"] == tipo and x["nome"] == nome)


def test_modulo_bloqueado_sem_licenca(novo_app, monkeypatch):
    monkeypatch.delenv("CARTEIRA_DEMO", raising=False)
    monkeypatch.delenv("CARTEIRA_MODULOS", raising=False)
    c = cliente_logado(novo_app(fonte))
    r = c.get("/api/plan/resumo")
    assert r.status_code == 403 and r.get_json()["modulo"] == "planejamento"
    mods = {m["codigo"]: m["ativo"] for m in c.get("/api/eu").get_json()["modulos"]}
    assert mods == {"planejamento": False}
    assert b"plan-resumo" not in c.get("/").data  # telas do módulo não aparecem


def test_lancamentos_e_resumo_do_mes(novo_app, com_modulo):
    c = cliente_logado(novo_app(fonte))
    assert b"plan-resumo" in c.get("/").data
    hoje = dt.date.today()
    mes = hoje.isoformat()[:7]
    d = lambda dia: f"{mes}-{dia:02d}"  # noqa: E731
    r = c.post("/api/plan/lancamentos", json={"tipo": "receita", "data": d(5), "categoria_id": cat(c, "receita", "Salário"),
                                              "valor": 8000, "valor_bruto": 10500})
    assert r.status_code == 201
    c.post("/api/plan/lancamentos", json={"tipo": "despesa", "data": d(10), "descricao": "Supermercado",
                                          "categoria_id": cat(c, "despesa", "Mercado"), "valor": "1.250,50"})
    c.post("/api/plan/lancamentos", json={"tipo": "despesa", "data": d(1), "categoria_id": cat(c, "despesa", "Condomínio"),
                                          "valor": 900, "pago": False})
    # aporte na carteira entra como dinheiro investido; provento pago, como receita
    c.post("/api/aportes", json={"data": d(3), "ticker": "ITUB4", "quantidade": 10, "preco": 30})
    c.post("/api/proventos", json={"ticker": "ITUB4", "tipo": "dividendo", "data_pagamento": d(1), "valor_total": 25})
    r = c.get(f"/api/plan/resumo?mes={mes}").get_json()
    assert r["receitas"] == pytest.approx(8025) and r["proventos"] == pytest.approx(25)
    assert r["descontos"] == pytest.approx(2500) and r["receita_bruta"] == pytest.approx(10525)
    assert r["despesas"] == pytest.approx(2150.5) and r["investido"] == pytest.approx(300)
    assert r["sobra"] == pytest.approx(8025 - 2150.5 - 300)
    assert r["taxa_poupanca"] == pytest.approx(300 / 8025 * 100)
    grupos = {g["grupo"]: g["valor"] for g in r["despesas_por_grupo"]}
    assert grupos == {"Alimentação": pytest.approx(1250.5), "Moradia": 900}
    assert [a["descricao"] for a in r["a_pagar"]] == ["Condomínio"]
    assert any(x["categoria"] == plan.NOME_PROVENTOS for x in r["receitas_por_categoria"])
    assert len(r["serie"]) == 12 and r["serie"][-1]["mes"] == mes


def test_validacoes(novo_app, com_modulo):
    c = cliente_logado(novo_app(fonte))
    base = {"tipo": "despesa", "data": "2026-11-10", "valor": 100}
    assert c.post("/api/plan/lancamentos", json={**base, "tipo": "x"}).status_code == 400
    assert c.post("/api/plan/lancamentos", json={**base, "data": "31/02"}).get_json()["erro"] == "Informe uma data válida."
    assert c.post("/api/plan/lancamentos", json={**base, "valor": "abc"}).status_code == 400
    r = c.post("/api/plan/lancamentos", json={**base, "categoria_id": cat(c, "receita", "Salário")})
    assert "Categoria inválida" in r.get_json()["erro"]
    r = c.post("/api/plan/lancamentos", json={"tipo": "receita", "data": "2026-11-05", "valor": 100, "valor_bruto": 90})
    assert "bruto" in r.get_json()["erro"]


def test_recorrencia_mensal(novo_app, com_modulo):
    c = cliente_logado(novo_app(fonte))
    mes = dt.date.today().isoformat()[:7]
    inicio = plan.somar_meses(mes, -2)
    r = c.post("/api/plan/lancamentos", json={"tipo": "despesa", "data": f"{inicio}-28", "descricao": "Escola",
                                              "categoria_id": cat(c, "despesa", "Escola / faculdade"), "valor": 1200,
                                              "repetir": "mensal"})
    assert r.status_code == 201
    lancs = lambda m: c.get(f"/api/plan/lancamentos?mes={m}").get_json()["lancamentos"]  # noqa: E731
    # lançada nos 3 meses até o atual; no futuro aparece como projeção
    assert [len(lancs(m)) for m in (inicio, plan.somar_meses(inicio, 1), mes)] == [1, 1, 1]
    futuro = lancs(plan.somar_meses(mes, 2))
    assert len(futuro) == 1 and futuro[0]["projetado"]
    # excluir uma ocorrência não a recria
    oc = lancs(mes)[0]
    c.delete(f"/api/plan/lancamentos/{oc['id']}")
    assert lancs(mes) == []
    # editar valor também para os próximos meses e encerrar a repetição
    oc = lancs(plan.somar_meses(inicio, 1))[0]
    c.put(f"/api/plan/lancamentos/{oc['id']}", json={"valor": 1300, "atualizar_proximos": True})
    assert lancs(plan.somar_meses(mes, 1))[0]["valor"] == 1300
    rid = c.get(f"/api/plan/lancamentos?mes={mes}").get_json()["recorrencias"][0]["id"]
    c.delete(f"/api/plan/recorrencias/{rid}")
    assert lancs(plan.somar_meses(mes, 1)) == []


def test_parcelado(novo_app, com_modulo):
    c = cliente_logado(novo_app(fonte))
    r = c.post("/api/plan/lancamentos", json={"tipo": "despesa", "data": "2026-01-31", "descricao": "Geladeira",
                                              "valor": 1000, "repetir": "parcelado", "parcelas": 3, "forma": "credito"})
    assert r.status_code == 201
    datas = []
    for m in ("2026-01", "2026-02", "2026-03"):
        l = c.get(f"/api/plan/lancamentos?mes={m}").get_json()["lancamentos"]
        datas += [(x["data"], x["valor"], x["parcela_num"], x["parcela_total"]) for x in l]
    assert datas == [("2026-01-31", 333.34, 1, 3), ("2026-02-28", 333.33, 2, 3), ("2026-03-31", 333.33, 3, 3)]
    # excluir a 2ª e as seguintes
    pid = c.get("/api/plan/lancamentos?mes=2026-02").get_json()["lancamentos"][0]["id"]
    assert c.delete(f"/api/plan/lancamentos/{pid}?escopo=proximos").get_json()["removidos"] == 2


def test_isolamento_e_familia(novo_app, com_modulo):
    app = novo_app(fonte)
    edgar = cliente_logado(app)
    edgar.post("/api/usuarios", json={"nome": "Eliandra", "email": "eli@x.com", "senha": "senha-eli-123",
                                      "criar_carteira": True, "nome_carteira": "Carteira Eliandra"})
    eli = cliente_logado(app, "eli@x.com", "senha-eli-123")
    r = eli.post("/api/plan/lancamentos", json={"tipo": "despesa", "data": "2026-11-10", "valor": 50})
    lid = r.get_json()["id"]
    assert edgar.delete(f"/api/plan/lancamentos/{lid}").status_code == 404  # outra carteira
    edgar.environ_base["HTTP_X_CARTEIRA"] = "todas"
    edgar.post("/api/plan/lancamentos", json={"tipo": "despesa", "data": "2026-11-10", "valor": 1})
    assert edgar.get("/api/plan/resumo?mes=2026-11").get_json()["despesas"] == 50  # visão da família soma


def test_custo_de_vida():
    assert plan.custo_de_vida({"2026-08": 3000, "2026-09": 0, "2026-10": 5000, "2026-11": 9999}, "2026-11") == 4000
    assert plan.custo_de_vida({}, "2026-11") is None
