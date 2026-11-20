from carteira.conferencia import nome_instituicao, por_instituicao


def test_nome_instituicao():
    assert nome_instituicao("Banco do Brasil") == "BB"
    assert nome_instituicao("Tesouro Direto · BB Banco de Investimento S/A") == "BB"
    assert nome_instituicao("Tesouro Direto · Nu Invest Corretora de Valores S.A.") == "Nubank"
    assert nome_instituicao("Tesouro Direto · instituição 820") == "instituição 820"


def linha(ticker, qtd, preco):
    return {"ticker": ticker, "quantidade": qtd, "preco_atual": preco, "valor": qtd * preco}


def test_tesouro_em_duas_instituicoes_e_saldo_sem_quantidade():
    relatorios = [
        {"origem": "Banco do Brasil", "nome": "bb.pdf", "importado_em": "2026-11-20T10:00",
         "itens": [{"ticker": "TESOURO IPCA+ 2029", "quantidade": 1, "sem_quantidade": True, "valor_atual": 2474.34},
                   {"ticker": "TESOURO IPCA+ 2050", "quantidade": 2.15, "valor_atual": 1792.54}]},
        {"origem": "Tesouro Direto · Nu Invest Corretora", "nome": "td.xlsx", "importado_em": "2026-11-20T10:00",
         "itens": [{"ticker": "TESOURO IPCA+ 2029", "quantidade": 0.06, "valor_atual": 239.45}]},
        {"origem": "B3", "nome": "b3.xlsx", "importado_em": "2026-11-20T10:00",
         "itens": [{"ticker": "TESOURO IPCA+ 2029", "quantidade": 0.68}]},
    ]
    sistema = [linha("TESOURO IPCA+ 2029", 0.68, 3990.87), linha("TESOURO IPCA+ 2050", 2.32, 833.74),
               linha("PETR4", 100, 30.0)]
    r = por_instituicao(relatorios, sistema)
    assert [(p["nome"], round(p["quantidade"], 2)) for p in r["TESOURO IPCA+ 2029"]] == [("BB", 0.62), ("Nubank", 0.06)]
    assert [(p["nome"], round(p["quantidade"], 2)) for p in r["TESOURO IPCA+ 2050"]] == [("BB", 2.15), ("outras", 0.17)]
    assert round(r["TESOURO IPCA+ 2050"][1]["valor"], 2) == round(0.17 * 833.74, 2)
    assert "PETR4" not in r  # só a B3 (todas as corretoras juntas): não diz a instituição


def test_mesma_instituicao_em_dois_relatorios_vale_o_mais_novo():
    relatorios = [
        {"origem": "Banco do Brasil", "nome": "a", "importado_em": "2026-10-01T10:00",
         "itens": [{"ticker": "X", "quantidade": 5}]},
        {"origem": "Tesouro Direto · BB Banco de Investimento S/A", "nome": "b", "importado_em": "2026-11-01T10:00",
         "itens": [{"ticker": "X", "quantidade": 4}]},
    ]
    r = por_instituicao(relatorios, [linha("X", 4, 10)])
    assert [(p["nome"], p["quantidade"]) for p in r["X"]] == [("BB", 4)]
