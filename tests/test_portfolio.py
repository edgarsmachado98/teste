import pytest

from carteira import portfolio


def ap(data, ticker, qtd, preco, tipo="compra", taxas=0):
    return {"data": data, "ticker": ticker, "quantidade": qtd, "preco": preco, "tipo": tipo, "taxas": taxas}


def test_preco_medio_e_venda():
    pos = portfolio.calcular_posicoes([
        ap("2024-01-01", "ABCD3", 10, 10),
        ap("2024-02-01", "ABCD3", 10, 20, taxas=10),
        ap("2024-03-01", "ABCD3", 5, 30, tipo="venda"),
    ])["ABCD3"]
    assert pos["quantidade"] == 15
    assert pos["preco_medio"] == pytest.approx(15.5)
    assert pos["realizado"] == pytest.approx(5 * (30 - 15.5))


def test_venda_maior_que_posicao():
    with pytest.raises(ValueError):
        portfolio.calcular_posicoes([ap("2024-01-01", "X", 1, 10), ap("2024-01-02", "X", 2, 10, "venda")])


def ativo(t, meta, classe="acao"):
    return {"ticker": t, "nome": "", "classe": classe, "meta_pct": meta}


def test_resumo_e_sugestao_prioriza_defasado():
    ativos = [ativo("A", 50), ativo("B", 50)]
    resumo = portfolio.resumo_carteira(ativos, [ap("2024-01-01", "A", 100, 10)], {"A": 10, "B": 10})
    assert resumo["total_valor"] == 1000
    s = portfolio.sugerir_aporte(resumo, 1000)
    compras = {x["ticker"]: x["quantidade"] for x in s["sugestoes"]}
    assert compras == {"B": 100}
    assert s["sobra"] == pytest.approx(0)


def test_sugestao_respeita_lote_inteiro_e_aproveita_sobra():
    ativos = [ativo("A", 50), ativo("B", 50, "cripto")]
    resumo = portfolio.resumo_carteira(ativos, [], {"A": 30, "B": 7})
    s = portfolio.sugerir_aporte(resumo, 100)
    compras = {x["ticker"]: x["quantidade"] for x in s["sugestoes"]}
    assert compras["A"] == 1  # ação: só unidades inteiras (R$ 30)
    assert compras["B"] == pytest.approx(70 / 7)  # cripto absorve a sobra
    assert s["sobra"] == pytest.approx(0, abs=1e-6)


def test_sugestao_valor_invalido():
    resumo = portfolio.resumo_carteira([ativo("A", 100)], [], {"A": 10})
    with pytest.raises(ValueError):
        portfolio.sugerir_aporte(resumo, 0)


def test_aportes_por_mes():
    serie = portfolio.aportes_por_mes([ap("2024-01-05", "A", 1, 100), ap("2024-01-20", "A", 1, 50),
                                       ap("2024-03-01", "A", 1, 60, "venda")])
    assert serie == [{"mes": "2024-01", "aporte": 150, "acumulado": 150},
                     {"mes": "2024-03", "aporte": -60, "acumulado": 90}]
