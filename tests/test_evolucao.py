import pytest

from carteira import evolucao
from carteira.indices import Indices, mensal_de_diario
from tests.conftest import cliente_logado


def ap(data, ticker, qtd, preco, tipo="compra"):
    return {"data": data, "ticker": ticker, "quantidade": qtd, "preco": preco, "tipo": tipo, "taxas": 0}


SERIE = [("2025-01-31", 11.0), ("2025-02-28", 11.0), ("2025-03-31", 12.1)]


def test_metodo_de_cotas_ignora_momento_do_aporte():
    aportes = [ap("2025-01-01", "A", 10, 10), ap("2025-02-01", "A", 10, 11)]
    ev = evolucao.calcular_evolucao(aportes, [], {"A": SERIE}, {"A": 12.1}, "2025-03-31")
    m = {x["mes"]: x for x in ev["meses"]}
    assert m["2025-01"]["rent_mes"] == pytest.approx(10)
    assert m["2025-02"]["rent_mes"] == pytest.approx(0)  # aporte de fevereiro não é "ganho"
    assert m["2025-03"]["rent_mes"] == pytest.approx(10)
    assert m["2025-03"]["rent_acum"] == pytest.approx(21)  # 1,1 x 1,0 x 1,1
    assert m["2025-03"]["patrimonio"] == pytest.approx(242) and m["2025-03"]["investido"] == 210
    # sobre o custo seria 242/210 - 1 = 15,2%: o método de cotas mede o desempenho do investimento


def test_proventos_contam_como_ganho_e_vendas_como_saida():
    aportes = [ap("2025-01-01", "A", 10, 10), ap("2025-03-01", "A", 5, 11, "venda")]
    provs = [{"ticker": "A", "data_pagamento": "2025-03-15", "valor_total": 5.5},
             {"ticker": "A", "data_pagamento": "2025-12-15", "valor_total": 99}]  # futuro: ignorado
    ev = evolucao.calcular_evolucao(aportes, provs, {"A": SERIE}, {"A": 12.1}, "2025-03-31")
    marco = ev["meses"][-1]
    # base = 110 - 55 (venda no dia 1, peso 1) = 55; ganho = 60,5 - 110 + 55 + 5,5 = 11
    assert marco["rent_mes"] == pytest.approx(11 / 55 * 100)
    assert marco["investido"] == pytest.approx(100 - 55) and marco["proventos"] == 5.5


def test_ativo_sem_historico_estimado_linearmente():
    aportes = [ap("2025-01-01", "CDB X", 1, 1000)]
    ev = evolucao.calcular_evolucao(aportes, [], {}, {"CDB X": 1090.0}, "2025-04-01")
    assert ev["estimados"] == ["CDB X"]
    meses = {x["mes"]: x["patrimonio"] for x in ev["meses"]}
    assert meses["2025-04"] == pytest.approx(1090)
    assert 1000 < meses["2025-02"] < meses["2025-03"] < 1090


def test_resumo_periodos_e_percentual_do_cdi():
    meses = [{"mes": "2025-11", "rent_mes": 1.0}, {"mes": "2025-12", "rent_mes": 2.0}, {"mes": "2026-01", "rent_mes": 1.0}]
    refs = {"cdi": [{"mes": m, "pct": 1.0} for m in ("2025-11", "2025-12", "2026-01")],
            "ibov": [{"mes": "2026-01", "pct": -2.0}]}
    r = evolucao.resumo_periodos(meses, refs, "2026-01-20")
    assert r["ano"]["carteira"] == pytest.approx(1.0) and r["ano"]["pct_cdi"] == pytest.approx(100)
    assert r["inicio"]["carteira"] == pytest.approx((1.01 * 1.02 * 1.01 - 1) * 100)
    assert r["inicio"]["ibov"] is None  # série incompleta no período: não compara
    assert r["mes"]["ibov"] == pytest.approx(-2.0)


def test_mensal_de_diario():
    serie = [("2025-01-30", 100.0), ("2025-01-31", 110.0), ("2025-02-27", 99.0), ("2025-02-28", 121.0)]
    assert mensal_de_diario(serie) == [{"mes": "2025-02", "pct": pytest.approx(10.0)}]


class MercadoFalso:
    def historico(self, t):
        assert t == "^BVSP"
        return [("2025-01-31", 100.0), ("2025-02-28", 105.0), ("2025-03-31", 99.75)], "yahoo"


def test_indices_com_cache(tmp_path):
    from carteira import db
    chamadas = []

    def bcb(codigo, inicio, fim):
        chamadas.append(codigo)
        return [{"mes": "2025-02", "pct": 0.99 if codigo == 4391 else 0.5},
                {"mes": "2025-03", "pct": 0.96 if codigo == 4391 else 0.3}]

    ind = Indices(db.connect(str(tmp_path / "x.db")), MercadoFalso(), bcb)
    s, falhas = ind.series("2025-02-01", "2025-03-31")
    assert falhas == {} and s["cdi"][0]["pct"] == 0.99 and s["ipca"][1]["pct"] == 0.3
    assert [round(x["pct"], 2) for x in s["ibov"]] == [5.0, -5.0]
    ind.series("2025-02-01", "2025-03-31")
    assert chamadas == [4391, 433]  # segunda consulta veio do cache


def test_api_evolucao_e_visao_da_familia(novo_app, tmp_path):
    serie = [("2025-01-31", 11.0), ("2025-02-28", 12.0)]
    app = novo_app(lambda t: serie)
    edgar = cliente_logado(app)
    edgar.post("/api/usuarios", json={"nome": "Eliandra", "email": "eli@exemplo.com", "senha": "senha-eli-123",
                                      "criar_carteira": True, "nome_carteira": "Carteira Eliandra"})
    ids = {c["nome"]: c["id"] for c in edgar.get("/api/eu").get_json()["carteiras"]}
    for nome, qtd in (("Carteira Edgar Machado", 10), ("Carteira Eliandra", 5)):
        edgar.environ_base["HTTP_X_CARTEIRA"] = str(ids[nome])
        edgar.post("/api/aportes", json={"data": "2025-01-01", "ticker": "ITUB4", "quantidade": qtd, "preco": 10})

    edgar.environ_base["HTTP_X_CARTEIRA"] = "todas"
    c = edgar.get("/api/carteira").get_json()
    assert c["ativos"][0]["quantidade"] == 15 and len(c["por_carteira"]) == 2
    assert {p["nome"]: p["valor"] for p in c["por_carteira"]} == {"Carteira Edgar Machado": 120, "Carteira Eliandra": 60}
    # visão da família é só leitura
    r = edgar.post("/api/aportes", json={"data": "2025-01-01", "ticker": "X", "quantidade": 1, "preco": 1})
    assert r.status_code == 400 and "família" in r.get_json()["erro"]

    ev = edgar.get("/api/evolucao").get_json()
    assert ev["meses"][0]["mes"] == "2025-01" and ev["meses"][0]["investido"] == 150
    assert ev["meses"][0]["rent_mes"] == pytest.approx(10)
    assert set(ev["falhas_referencias"]) == {"cdi", "ipca"}  # Banco Central indisponível nos testes
    assert ev["referencias"]["ibov"][0]["mes"] == "2025-02"  # Ibovespa pela fonte de cotações
