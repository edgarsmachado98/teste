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


def test_fluxo():
    aportes = [ap("2025-01-10", "A", 10, 10), ap("2025-02-10", "A", 10, 20, taxas=10),
               ap("2025-03-05", "A", 5, 30, tipo="venda"), ap("2025-03-06", "B", 2, 50)]
    for i, a in enumerate(aportes):
        a["id"] = i
    provs = [{"ticker": "A", "tipo": "dividendo", "data_pagamento": "2025-03-20", "valor_total": 7.5},
             {"ticker": "A", "tipo": "jcp", "data_pagamento": "2025-12-20", "valor_total": 99}]  # futuro
    f = portfolio.fluxo(aportes, provs, "2025-02-01", "2025-12-31", "2025-06-30")
    t = f["totais"]
    assert t["compras"] == pytest.approx(210 + 100) and t["vendas"] == 150 and t["proventos"] == 7.5
    assert t["aporte_liquido"] == pytest.approx(160)
    assert t["lucro_realizado"] == pytest.approx(5 * (30 - 15.5))  # preço médio inclui a compra de janeiro
    assert [m["mes"] for m in f["por_mes"]] == ["2025-02", "2025-03"]
    assert f["lancamentos"][0]["tipo"] == "dividendo"
    assert {a["ticker"] for a in f["por_ativo"]} == {"A", "B"}


def test_visao_por_categoria():
    def linha(t, classe, qtd, custo, valor, prov=0, var=None):
        return {"ticker": t, "classe": classe, "quantidade": qtd, "custo": custo, "valor": valor,
                "preco_medio": custo / qtd if qtd else 0, "preco_atual": valor / qtd if qtd else None,
                "proventos_total": prov, "variacao_valor": var, "variacao_pct": None if var is None else var / (valor - var) * 100}
    linhas = [linha("A", "acao", 10, 100, 150, prov=10, var=5), linha("B", "acao", 10, 200, 180, var=-20),
              linha("C", "fii", 5, 500, 520, prov=30), linha("D", "acao", 0, 0, 0)]
    v = portfolio.visao_por_categoria(linhas, tamanho_ranking=2)
    fii, acoes = v["categorias"]  # ordenadas por valor (FII 520 > ações 330)
    assert acoes["classe"] == "acao" and acoes["quantidade_ativos"] == 2  # D (zerado) fica de fora
    assert acoes["valor"] == 330 and acoes["peso_pct"] == pytest.approx(330 / 850 * 100)
    assert acoes["rentabilidade_valor"] == pytest.approx(330 - 300 + 10)
    assert acoes["rentabilidade_pct"] == pytest.approx(40 / 300 * 100)
    assert acoes["variacao_valor"] == -15 and acoes["variacao_pct"] == pytest.approx(-15 / 345 * 100)
    assert fii["variacao_pct"] is None  # sem cotação do dia
    assert [a["ticker"] for a in acoes["ativos"]] == ["B", "A"]  # ordenados por valor
    r = v["ranking"]["rentabilidade"]
    assert [a["ticker"] for a in r["melhores"]] == ["A", "C"] and r["piores"][0]["ticker"] == "B"
