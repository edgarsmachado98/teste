import pytest

from carteira import impostos, portfolio
from tests.conftest import cliente_logado


def ap(data, ticker, qtd, preco, tipo="compra", id_=None, taxas=0):
    return {"id": id_, "data": data, "ticker": ticker, "quantidade": qtd, "preco": preco, "tipo": tipo, "taxas": taxas}


CLASSES = {"A": "acao", "B": "acao", "F": "fii", "E": "etf"}


def mes(apuracao, chave):
    return next(m for m in apuracao if m["mes"] == chave)


def test_venda_ate_20_mil_isenta():
    ops = [ap("2025-01-02", "A", 1000, 10, id_=1), ap("2025-02-10", "A", 1000, 15, "venda", 2)]
    r = mes(impostos.apurar(ops, CLASSES), "2025-02")
    assert r["isento"] and r["lucro_isento"] == pytest.approx(5000)
    assert r["imposto_devido"] == 0 and r["darf"] == 0


def test_venda_acima_de_20_mil_e_irrf():
    ops = [ap("2025-01-02", "A", 1000, 20, id_=1), ap("2025-02-10", "A", 1000, 23, "venda", 2)]
    r = mes(impostos.apurar(ops, CLASSES), "2025-02")
    assert not r["isento"] and r["pools"]["comum"]["imposto"] == pytest.approx(450)
    assert r["irrf"] == pytest.approx(23000 * 0.00005)
    assert r["darf"] == pytest.approx(450 - 1.15) and r["vencimento"] == "2025-03-31"


def test_prejuizo_compensado_inclusive_de_mes_isento():
    ops = [ap("2025-01-02", "A", 1000, 10, id_=1), ap("2025-01-02", "B", 2000, 20, id_=2),
           ap("2025-02-10", "A", 1000, 9.5, "venda", 3),          # mês isento (R$ 9.500), prejuízo de 500
           ap("2025-03-10", "B", 2000, 21.5, "venda", 4)]         # R$ 43.000, lucro de 3.000
    ap_ = impostos.apurar(ops, CLASSES)
    fev, mar = mes(ap_, "2025-02"), mes(ap_, "2025-03")
    assert fev["isento"] and fev["prejuizo_acumulado"]["comum"] == pytest.approx(500)
    assert mar["pools"]["comum"]["base"] == pytest.approx(2500)
    assert mar["pools"]["comum"]["imposto"] == pytest.approx(375)
    assert mar["prejuizo_acumulado"]["comum"] == 0


def test_etf_nao_tem_isencao_e_fii_20():
    ops = [ap("2025-01-02", "E", 10, 100, id_=1), ap("2025-01-02", "F", 10, 100, id_=2),
           ap("2025-02-10", "E", 10, 110, "venda", 3), ap("2025-02-10", "F", 10, 160, "venda", 4)]
    r = mes(impostos.apurar(ops, CLASSES), "2025-02")
    assert r["pools"]["comum"]["imposto"] == pytest.approx(15)  # 100 x 15%
    assert r["pools"]["fii"]["imposto"] == pytest.approx(120)  # 600 x 20%


def test_darf_abaixo_de_10_acumula():
    ops = [ap("2025-01-02", "F", 10, 100, id_=1), ap("2025-02-10", "F", 1, 130, "venda", 2),
           ap("2025-03-10", "F", 1, 130, "venda", 3)]
    ap_ = impostos.apurar(ops, CLASSES)
    fev, mar = mes(ap_, "2025-02"), mes(ap_, "2025-03")
    assert fev["darf"] == 0 and fev["darf_acumulado_proximo"] == pytest.approx(6 - 130 * 0.00005)
    assert mar["darf"] == pytest.approx(2 * (6 - 130 * 0.00005), abs=0.01)


def test_day_trade():
    ops = [ap("2025-02-10", "A", 100, 10, id_=1), ap("2025-02-10", "A", 100, 11, "venda", 2)]
    r = mes(impostos.apurar(ops, CLASSES), "2025-02")
    assert r["pools"]["daytrade"]["resultado"] == pytest.approx(100)
    assert r["pools"]["daytrade"]["imposto"] == pytest.approx(20)
    assert r["irrf"] == pytest.approx(1.0) and r["darf"] == pytest.approx(19)
    assert r["vendas_acoes"] == 0  # day trade não conta para o limite de R$ 20 mil


def test_eventos_ajustam_custo_da_venda():
    ops = portfolio.com_eventos([ap("2025-01-02", "A", 1000, 30, id_=1), ap("2025-03-10", "A", 2000, 16, "venda", 2)],
                                [{"id": 1, "data": "2025-02-01", "ticker": "A", "tipo": "desdobramento", "fator": 2}])
    r = mes(impostos.apurar(ops, CLASSES), "2025-03")
    assert r["resultados"]["acoes"] == pytest.approx(2000)  # 32.000 - 30.000


def test_vencimento_em_dezembro():
    assert impostos._ultimo_dia_util_mes_seguinte("2025-11") == "2025-12-30"


def test_declaracao():
    ops = [ap("2024-06-01", "A", 100, 10, id_=1), ap("2025-03-01", "A", 50, 12, id_=2),
           ap("2025-01-02", "F", 10, 100, id_=3), ap("2025-05-10", "F", 10, 110, "venda", 4)]
    provs = [{"ticker": "A", "tipo": "dividendo", "data_pagamento": "2025-04-01", "valor_total": 50},
             {"ticker": "A", "tipo": "jcp", "data_pagamento": "2025-08-01", "valor_total": 17},
             {"ticker": "F", "tipo": "rendimento", "data_pagamento": "2025-02-14", "valor_total": 8},
             {"ticker": "A", "tipo": "dividendo", "data_pagamento": "2024-12-01", "valor_total": 99}]
    ativos = [{"ticker": "A", "classe": "acao", "nome": "Empresa A"}, {"ticker": "F", "classe": "fii", "nome": ""}]
    d = impostos.declaracao(ops, provs, ativos, impostos.apurar(ops, {"A": "acao", "F": "fii"}), 2025)
    bens = {b["ticker"]: b for b in d["bens"]}
    assert bens["A"]["situacao_anterior"] == 1000 and bens["A"]["situacao_atual"] == 1600
    assert (bens["A"]["grupo"], bens["A"]["codigo"]) == ("03", "01")
    assert "150 ações de A (Empresa A)" in bens["A"]["discriminacao"] and "10,67" in bens["A"]["discriminacao"]
    assert bens["F"]["situacao_atual"] == 0 and "vendida" in bens["F"]["discriminacao"]
    isentos = {g["codigo"]: g for g in d["isentos"]}
    assert isentos["09"]["total"] == 50 and isentos["99"]["total"] == 8
    assert d["exclusivos"][0]["total"] == 17


def test_api_impostos(novo_app):
    from carteira.market import serie_simulada
    c = cliente_logado(novo_app(lambda t: serie_simulada(t, dias=300)))
    c.post("/api/aportes", json={"data": "2025-01-02", "ticker": "ITUB4", "quantidade": 1000, "preco": 30})
    c.post("/api/aportes", json={"data": "2025-02-10", "ticker": "ITUB4", "tipo": "venda", "quantidade": 1000, "preco": 33})
    r = c.get("/api/impostos?ano=2025").get_json()
    fev = next(m for m in r["apuracao"] if m["mes"] == "2025-02")
    assert fev["pools"]["comum"]["imposto"] == pytest.approx(450)
    assert r["resumo"]["darf_total"] == pytest.approx(fev["darf"]) and 2025 in r["anos"]
    assert r["declaracao"]["ano"] == 2025
    # IR é por pessoa: a visão da família não se aplica
    c.environ_base["HTTP_X_CARTEIRA"] = "todas"
    assert c.get("/api/impostos?ano=2025").status_code == 400
