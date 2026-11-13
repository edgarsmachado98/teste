import datetime as dt

import pytest

from carteira import rendafixa as rf
from carteira.market import serie_simulada
from tests.conftest import cliente_logado

D = dt.date


def test_dias_uteis_e_feriados():
    assert rf.dias_uteis(D(2025, 1, 1), D(2026, 1, 1)) == 252
    assert D(2026, 2, 16) in rf.feriados(2026) and D(2026, 4, 3) in rf.feriados(2026)  # Carnaval, Sexta Santa
    assert rf.dias_uteis(D(2025, 1, 6), D(2025, 1, 6)) == 0


def test_fatores():
    um_ano = (D(2025, 1, 1), D(2026, 1, 1))  # 252 dias úteis
    assert rf.fator_pre(12, *um_ano) == pytest.approx(1.12)
    cdi = [(d.isoformat(), 0.05) for d in (D(2025, 1, 1) + dt.timedelta(days=i) for i in range(365))]
    assert rf.fator_diario(100, *um_ano, cdi) == pytest.approx(1.0005 ** 252)
    assert rf.fator_diario(110, *um_ano, cdi) == pytest.approx(1.00055 ** 252)
    # dias sem taxa publicada usam a última conhecida
    assert rf.fator_diario(100, *um_ano, cdi[:10]) == pytest.approx(1.0005 ** 252)
    ipca = {"2025-01": 1.0, "2025-02": 2.0}
    assert rf.fator_ipca(0, D(2025, 1, 1), D(2025, 2, 1), ipca) == pytest.approx(1.01)
    meio_fev = rf.fator_ipca(0, D(2025, 2, 1), D(2025, 2, 15), ipca)
    assert meio_fev == pytest.approx(1.02 ** (14 / 28))
    assert rf.fator_ipca(0, D(2025, 3, 1), D(2025, 4, 1), ipca) == pytest.approx(1.02)  # mês sem IPCA: último


def test_impostos():
    assert rf.aliquota_ir(100) == .225 and rf.aliquota_ir(200) == .20 and rf.aliquota_ir(500) == .175
    assert rf.aliquota_ir(721) == .15
    assert rf.aliquota_iof(1) == .96 and rf.aliquota_iof(29) == .03 and rf.aliquota_iof(30) == 0


def test_lotes_peps():
    aportes = [{"data": "2025-01-10", "quantidade": 1, "preco": 1000, "tipo": "compra"},
               {"data": "2025-03-10", "quantidade": 1, "preco": 2000, "tipo": "compra"},
               {"data": "2025-06-10", "quantidade": 1.5, "preco": 2500, "tipo": "venda"}]
    assert rf.lotes_peps(aportes) == [("2025-03-10", 0.5, 2000)]


def test_avaliar_cdb_e_isento():
    cdi = [(d.isoformat(), 0.05) for d in (D(2025, 1, 1) + dt.timedelta(days=i) for i in range(400))]
    aportes = [{"data": "2025-01-01", "quantidade": 1, "preco": 10000, "tipo": "compra"}]
    cdb = {"indexador": "cdi", "taxa": 100, "vencimento": "2028-01-01"}
    r = rf.avaliar(cdb, aportes, "2026-01-01", {"cdi": cdi})
    bruto = 10000 * 1.0005 ** 252
    assert r["bruto"] == pytest.approx(bruto) and r["aplicado"] == 10000
    assert r["ir"] == pytest.approx((bruto - 10000) * .175)  # 365 dias
    assert r["liquido"] == pytest.approx(bruto - r["ir"]) and r["iof"] == 0
    assert r["dias_para_vencer"] == 730
    lca = dict(cdb, isento_ir=1)
    assert rf.avaliar(lca, aportes, "2026-01-01", {"cdi": cdi})["ir"] == 0
    # após o vencimento o título para de render
    venc = rf.avaliar(dict(cdb, vencimento="2025-07-01"), aportes, "2026-01-01", {"cdi": cdi})
    assert venc["vencido"] and venc["bruto"] < bruto
    assert rf.avaliar({"indexador": None}, aportes, "2026-01-01", {}) is None


def test_avaliar_tesouro_pelo_preco_oficial():
    aportes = [{"data": "2025-01-01", "quantidade": 0.5, "preco": 2000, "tipo": "compra"}]
    r = rf.avaliar({"indexador": "tesouro"}, aportes, "2026-01-01", {}, preco_tesouro=2200)
    assert r["bruto"] == pytest.approx(1100) and r["preco_unitario"] == pytest.approx(2200)


CSV_TESOURO = """Tipo Titulo;Data Vencimento;Data Base;Taxa Compra Manha;Taxa Venda Manha;PU Compra Manha;PU Venda Manha;PU Base Manha
Tesouro IPCA+;15/05/2035;31/01/2025;7,10;7,22;2050,00;2010,00;2009,00
Tesouro IPCA+;15/05/2035;{hoje};7,05;7,17;2250,00;2200,00;2199,00
"""


def test_api_renda_fixa(novo_app):
    hoje = dt.date.today()
    cdi = [((hoje - dt.timedelta(days=i)).isoformat(), 0.05) for i in range(800, -1, -1)]

    def bcb(codigo, inicio, fim):
        assert codigo in (11, 12, 433, 4391)
        return [(d, v) for d, v in cdi if inicio <= d <= fim] if codigo == 12 else []

    app = novo_app(lambda t: serie_simulada(t, dias=300), fonte_bcb=bcb)
    c = cliente_logado(app)
    inicio = (hoje - dt.timedelta(days=400)).isoformat()
    assert c.post("/api/ativos", json={"ticker": "CDB BANCO X", "classe": "renda_fixa", "indexador": "cdi",
                                       "taxa": 110, "vencimento": (hoje + dt.timedelta(days=60)).isoformat()}).status_code == 201
    assert c.post("/api/ativos", json={"ticker": "LCA Y", "classe": "renda_fixa", "indexador": "cdi"}).status_code == 400
    c.post("/api/aportes", json={"data": inicio, "ticker": "CDB BANCO X", "quantidade": 1, "preco": 10000})
    c.post("/api/aportes", json={"data": inicio, "ticker": "CDB SEM CONFIG", "classe": "renda_fixa",
                                 "quantidade": 1, "preco": 5000})
    c.post("/api/ativos", json={"ticker": "CDB SEM CONFIG", "classe": "renda_fixa", "preco_manual": 5300})

    r = c.get("/api/renda-fixa").get_json()
    itens = {i["ticker"]: i for i in r["itens"]}
    cdb = itens["CDB BANCO X"]
    assert cdb["fonte"] == "curva" and cdb["bruto"] > 10000 and cdb["ir"] > 0
    assert cdb["liquido"] == pytest.approx(cdb["bruto"] - cdb["ir"] - cdb["iof"])
    assert itens["CDB SEM CONFIG"]["fonte"] == "manual" and itens["CDB SEM CONFIG"]["bruto"] == 5300
    assert r["totais"]["sem_configuracao"] == 1
    assert r["itens"][0]["ticker"] == "CDB BANCO X"  # ordenado pelo vencimento mais próximo

    cart = {a["ticker"]: a for a in c.get("/api/carteira").get_json()["ativos"]}
    assert cart["CDB BANCO X"]["fonte_preco"] == "curva"
    assert cart["CDB BANCO X"]["valor"] == pytest.approx(cdb["bruto"])
    ev = c.get("/api/evolucao").get_json()
    assert "CDB BANCO X" not in ev["estimados"] and "CDB SEM CONFIG" in ev["estimados"]


def test_api_tesouro_preco_oficial(tmp_path):
    from app import create_app
    hoje = dt.date.today()
    csv_t = CSV_TESOURO.replace("{hoje}", hoje.strftime("%d/%m/%Y"))
    app = create_app(str(tmp_path / "t.db"), lambda t: serie_simulada(t, dias=300), secret_key="x",
                     fonte_bcb=lambda *a: [], fonte_tesouro=lambda: csv_t)
    c = cliente_logado(app)
    c.post("/api/ativos", json={"ticker": "TESOURO IPCA+ 2035", "classe": "renda_fixa", "indexador": "tesouro"})
    c.post("/api/aportes", json={"data": "2025-01-31", "ticker": "TESOURO IPCA+ 2035", "quantidade": 0.5, "preco": 2010})
    item = c.get("/api/renda-fixa").get_json()["itens"][0]
    assert item["fonte"] == "tesouro" and item["bruto"] == pytest.approx(1100)
    assert item["vencimento"] == "2035-05-15"  # vencimento oficial, sem precisar cadastrar


def test_ler_csv_tesouro_com_vencimento():
    from carteira import tesouro
    csv_t = CSV_TESOURO.replace("{hoje}", "04/11/2026")
    serie, venc = tesouro.ler_csv(csv_t, {"A": tesouro.identificar("TESOURO IPCA+ 2035")})
    assert serie["A"][-1] == ("2026-11-04", 2200.0) and venc == {"A": "2035-05-15"}
