import datetime as dt
import io

import openpyxl
import pytest

from carteira import importacao
from carteira.market import serie_simulada
from tests.conftest import cliente_logado

NEG_CAB = ["Data do Negócio", "Tipo de Movimentação", "Mercado", "Prazo/Vencimento", "Instituição",
           "Código de Negociação", "Quantidade", "Preço", "Valor"]
NEG = [
    ["10/01/2025", "Compra", "Mercado à Vista", "-", "CORRETORA X", "PETR4", 100, 38.5, 3850],
    ["10/01/2025", "Compra", "Mercado Fracionário", "-", "CORRETORA X", "ITUB4F", 7, 31.2, 218.4],
    ["15/02/2025", "Venda", "Mercado à Vista", "-", "CORRETORA X", "PETR4", 40, 40.0, 1600],
    ["20/02/2025", "Compra", "Opção de Compra", "-", "CORRETORA X", "PETRB400", 100, 0.5, 50],
]
MOV_CAB = ["Entrada/Saída", "Data", "Movimentação", "Produto", "Instituição", "Quantidade",
           "Preço unitário", "Valor da Operação"]
MOV = [
    ["Credito", "20/03/2025", "Dividendo", "PETR4 - PETROLEO BRASILEIRO S.A. PETROBRAS", "X", 60, 1.1, 66.0],
    ["Credito", "21/03/2025", "Juros Sobre Capital Próprio", "ITUB4 - ITAU UNIBANCO HOLDING S.A.", "X", 7, 0.3, 2.1],
    ["Credito", "14/03/2025", "Rendimento", "KNRI11 - KINEA RENDA IMOBILIARIA FII", "X", 10, 1.0, "10,00"],
    ["Credito", "10/01/2025", "Transferência - Liquidação", "PETR4 - PETROLEO", "X", 100, "-", "-"],
    ["Credito", "05/03/2025", "Desdobro", "ITUB4 - ITAU", "X", 1, "-", "-"],
    ["Credito", "02/04/2025", "Compra", "Tesouro IPCA+ 2035", "X", 0.5, 2100.0, 1050.0],
    ["Debito", "30/04/2025", "Dividendo", "PETR4 - PETROLEO", "X", 60, 1.0, 60.0],
]


def xlsx(cabecalho, linhas, titulo=True):
    wb = openpyxl.Workbook()
    ws = wb.active
    if titulo:
        ws.append(["Extrato gerado pela Área do Investidor"])
        ws.append([])
    ws.append(cabecalho)
    for l in linhas:
        ws.append(l)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_negociacao():
    r = importacao.analisar_extrato(xlsx(NEG_CAB, NEG), "negociacao.xlsx")
    assert r["tipo_arquivo"] == "negociacao"
    assert [(a["ticker"], a["tipo"], a["quantidade"]) for a in r["aportes"]] == [
        ("PETR4", "compra", 100), ("ITUB4", "compra", 7), ("PETR4", "venda", 40)]
    assert r["aportes"][0]["data"] == "2025-01-10"
    assert len(r["ignorados"]) == 1 and "Opções" in r["ignorados"][0]["motivo"]


def test_movimentacao():
    r = importacao.analisar_extrato(xlsx(MOV_CAB, MOV), "mov.xlsx")
    assert r["tipo_arquivo"] == "movimentacao"
    assert [(p["ticker"], p["tipo"], p["valor_total"]) for p in r["proventos"]] == [
        ("PETR4", "dividendo", 66.0), ("ITUB4", "jcp", 2.1), ("KNRI11", "rendimento", 10.0)]
    assert r["aportes"] == [{"data": "2025-04-02", "ticker": "TESOURO IPCA+ 2035", "tipo": "compra",
                             "quantidade": 0.5, "preco": 2100.0, "taxas": 0.0, "classe": "renda_fixa",
                             "obs": "B3 Tesouro Direto"}]
    motivos = " ".join(g["motivo"] for g in r["ignorados"])
    assert "Negociação" in motivos and "Evento corporativo" in motivos and "provisionado" in motivos


def test_csv_brasileiro_e_datas_excel():
    texto = ";".join(NEG_CAB) + "\n" + "10/01/2025;Compra;Mercado à Vista;-;X;WEGE3;10;\"1.050,25\";10502,50\n"
    r = importacao.analisar_extrato(texto.encode("latin-1"), "neg.csv")
    assert r["aportes"][0]["preco"] == 1050.25
    linhas = [[dt.datetime(2025, 1, 10), "Compra", "Mercado à Vista", "-", "X", "VALE3", 5, 60, 300]]
    assert importacao.analisar_extrato(xlsx(NEG_CAB, linhas, False), "n.xlsx")["aportes"][0]["data"] == "2025-01-10"


def test_arquivos_invalidos():
    with pytest.raises(importacao.ErroImportacao, match="Não reconheci"):
        importacao.analisar_extrato(xlsx(["a", "b"], [[1, 2]]), "x.xlsx")
    with pytest.raises(importacao.ErroImportacao, match="PDF"):
        importacao.analisar_extrato(b"%PDF", "x.pdf")


def test_classe_provavel():
    assert importacao.classe_provavel("KNRI11") == "fii"
    assert importacao.classe_provavel("AAPL34") == "bdr"
    assert importacao.classe_provavel("BBAS3") == "acao"


def enviar(cliente, conteudo, nome):
    return cliente.post("/api/importar/b3/previa", data={"arquivo": (io.BytesIO(conteudo), nome)},
                        content_type="multipart/form-data")


def test_fluxo_api(novo_app):
    c = cliente_logado(novo_app(lambda t: serie_simulada(t, dias=300)))
    previa = enviar(c, xlsx(NEG_CAB, NEG), "neg.xlsx").get_json()
    assert len(previa["aportes"]) == 3 and not any(a["ja_registrado"] for a in previa["aportes"])

    # Importar só a venda (sem a compra) é recusado
    assert c.post("/api/importar/b3/confirmar", json={"aportes": [previa["aportes"][2]]}).status_code == 409
    r = c.post("/api/importar/b3/confirmar", json={"aportes": previa["aportes"]})
    assert r.status_code == 201 and r.get_json()["aportes"] == 3
    posicoes = {a["ticker"]: a["quantidade"] for a in c.get("/api/carteira").get_json()["ativos"]}
    assert posicoes == {"PETR4": 60, "ITUB4": 7}

    # Reenviar o mesmo arquivo: tudo marcado como já lançado
    assert all(a["ja_registrado"] for a in enviar(c, xlsx(NEG_CAB, NEG), "neg.xlsx").get_json()["aportes"])

    mov = enviar(c, xlsx(MOV_CAB, MOV), "mov.xlsx").get_json()
    r = c.post("/api/importar/b3/confirmar", json={"aportes": mov["aportes"], "proventos": mov["proventos"]})
    assert {k: r.get_json()[k] for k in ("ok", "aportes", "proventos", "ativos")} == \
        {"ok": True, "aportes": 1, "proventos": 3, "ativos": 0}
    assert c.get("/api/proventos").get_json()["resumo"]["total"] == pytest.approx(78.1)
    classes = {a["ticker"]: a["classe"] for a in c.get("/api/ativos").get_json()}
    assert classes["TESOURO IPCA+ 2035"] == "renda_fixa"


def test_importacao_exige_permissao_de_controle(novo_app):
    app = novo_app(lambda t: serie_simulada(t, dias=300))
    edgar = cliente_logado(app)
    edgar.post("/api/usuarios", json={"nome": "Eliandra", "email": "eli@exemplo.com", "senha": "senha-eli-123"})
    cid = edgar.get("/api/eu").get_json()["carteiras"][0]["id"]
    edgar.put(f"/api/carteiras/{cid}/acessos", json={"email": "eli@exemplo.com", "ver": True})
    eli = cliente_logado(app, "eli@exemplo.com", "senha-eli-123")
    assert enviar(eli, xlsx(NEG_CAB, NEG), "neg.xlsx").status_code == 403


def test_eventos():
    cab = ["Produto", "Pagamento", "Tipo de Evento", "Instituição", "Quantidade", "Preço unitário", "Valor líquido"]
    linhas = [
        ["BBAS3 - BANCO DO BRASIL S/A", "28/02/2025", "Juros Sobre Capital Próprio", "X", 40, 0.25, 8.5],
        ["MXRF11 - MAXI RENDA FII", "14/03/2025", "Rendimento", "X", 150, 0.09, "13,50"],
        ["TAEE11 - TAESA", "15/12/2026", "Dividendo", "X", 30, 1.0, 30],
        ["ITUB4 - ITAU", "05/03/2025", "Bonificação em Ativos", "X", 3, "-", "-"],
    ]
    r = importacao.analisar_extrato(xlsx(cab, linhas), "eventos-2026.xlsx")
    assert r["tipo_arquivo"] == "eventos"
    assert [(p["ticker"], p["tipo"], p["valor_total"]) for p in r["proventos"]] == [
        ("BBAS3", "jcp", 8.5), ("MXRF11", "rendimento", 13.5), ("TAEE11", "dividendo", 30.0)]
    assert len(r["ignorados"]) == 1 and "Evento corporativo" in r["ignorados"][0]["motivo"]


def test_eventos_layout_previsao_de_pagamento():
    """Layout de 2026: colunas Tipo e Tipo de Evento, data em "Previsão de pagamento"."""
    cab = ["Produto", "Tipo", "Tipo de Evento", "Previsão de pagamento", "Instituição", "Conta",
           "Quantidade", "Preço unitário", "Valor líquido"]
    linhas = [
        ["PETR4 - PETROLEO BRASILEIRO S.A. PETROBRAS", "Ações", "Dividendo", "20/12/2026", "CORRETORA X", "123",
         100, 0.5, 50],
        ["MXRF11 - MAXI RENDA FII", "FII", "Rendimento", "14/11/2026", "CORRETORA X", "123", 150, 0.09, "13,50"],
        ["ITUB4 - ITAU", "Ações", "Juros Sobre Capital Próprio", "01/12/2026", "CORRETORA X", "123", 40, 0.2, 6.8],
    ]
    r = importacao.analisar_extrato(xlsx(cab, linhas), "eventos-2026-11-11-13-01-31.xlsx")
    assert r["tipo_arquivo"] == "eventos"
    assert [(p["ticker"], p["tipo"], p["data_pagamento"], p["valor_total"]) for p in r["proventos"]] == [
        ("PETR4", "dividendo", "2026-12-20", 50.0), ("MXRF11", "rendimento", "2026-11-14", 13.5),
        ("ITUB4", "jcp", "2026-12-01", 6.8)]


def test_erro_mostra_colunas():
    with pytest.raises(importacao.ErroImportacao, match="Tabelas encontradas: Coluna A, Coluna B, Coluna C"):
        importacao.analisar_extrato(xlsx(["Coluna A", "Coluna B", "Coluna C"], [[1, 2, 3]]), "x.xlsx")


def test_excel_da_b3_com_dimensao_errada():
    """Os arquivos da B3 declaram a dimensão da planilha como "A1"; o leitor precisa ignorar isso."""
    import re
    import zipfile
    cab = ["Produto", "Pagamento", "Tipo de Evento", "Instituição", "Quantidade", "Preço unitário", "Valor líquido"]
    original = xlsx(cab, [["BBAS3 - BANCO DO BRASIL S/A", "28/02/2025", "Dividendo", "X", 40, 0.25, 10]], False)
    zin, saida = zipfile.ZipFile(io.BytesIO(original)), io.BytesIO()
    with zipfile.ZipFile(saida, "w") as zout:
        for info in zin.infolist():
            dados = zin.read(info.filename)
            if info.filename.endswith("sheet1.xml"):
                dados = re.sub(rb'<dimension ref="[^"]+"/>', b'<dimension ref="A1"/>', dados)
            zout.writestr(info, dados)
    r = importacao.analisar_extrato(saida.getvalue(), "eventos.xlsx")
    assert r["tipo_arquivo"] == "eventos" and r["proventos"][0]["valor_total"] == 10


POS_CAB = ["Produto", "Instituição", "Conta", "Código de Negociação", "CNPJ da Empresa", "Código ISIN / Distribuição",
           "Tipo", "Escriturador", "Quantidade", "Quantidade Disponível", "Quantidade Indisponível", "Motivo",
           "Preço de Fechamento", "Valor Atualizado"]
TD_CAB = ["Produto", "Instituição", "Código ISIN", "Indexador", "Vencimento", "Quantidade", "Quantidade Disponível",
          "Quantidade Indisponível", "Motivo", "Valor Aplicado", "Valor bruto", "Valor líquido", "Valor Atualizado"]


def xlsx_posicao():
    wb = openpyxl.Workbook()
    abas = {
        "Acoes": (POS_CAB, [["ITUB4 - ITAU UNIBANCO", "CORRETORA X", "1", "ITUB4", "", "", "PN", "", 50, 50, 0, "", 35.0, 1750.0],
                            ["VALE3 - VALE S.A.", "CORRETORA X", "1", "VALE3", "", "", "ON", "", 10, 10, 0, "", 60.0, 600.0],
                            ["", "", "", "", "", "", "", "", "", "", "", "Total", "", 2350.0]]),
        "ETF": (POS_CAB, [["IVVB11 - ISHARES S&P 500", "CORRETORA X", "1", "IVVB11", "", "", "CI", "", 3, 3, 0, "", 400.0, 1200.0]]),
        "Tesouro Direto": (TD_CAB, [["Tesouro IPCA+ 2035", "CORRETORA X", "BR", "IPCA", "15/05/2035", 1.5, 1.5, 0, "",
                                     3000.0, 3300.0, 3250.0, 3300.0]]),
    }
    wb.remove(wb.active)
    for nome, (cab, linhas) in abas.items():
        ws = wb.create_sheet(nome)
        ws.append(cab)
        for l in linhas:
            ws.append(l)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_posicao():
    r = importacao.analisar_extrato(xlsx_posicao(), "posicao.xlsx")
    assert r["tipo_arquivo"] == "posicao"
    pos = {p["ticker"]: p for p in r["posicao"]}
    assert set(pos) == {"ITUB4", "VALE3", "IVVB11", "TESOURO IPCA+ 2035"}
    assert pos["IVVB11"]["classe"] == "etf" and pos["ITUB4"]["classe"] == "acao"
    td = pos["TESOURO IPCA+ 2035"]
    assert td["classe"] == "renda_fixa" and td["preco_medio"] == 2000 and td["preco_atual"] == 2200


def test_conciliacao():
    posicao = [{"ticker": "ITUB4", "classe": "acao", "quantidade": 50, "preco_medio": None},
               {"ticker": "VALE3", "classe": "acao", "quantidade": 10, "preco_medio": None}]
    novos = [{"data": "2026-03-10", "ticker": "ITUB4", "tipo": "compra", "quantidade": 20, "preco": 30},
             {"data": "2026-03-31", "ticker": "PETR4", "tipo": "venda", "quantidade": 23, "preco": 50},
             {"data": "2026-04-01", "ticker": "VALE3", "tipo": "compra", "quantidade": 15, "preco": 60}]
    c = importacao.conciliar_posicao(posicao, [], novos, "2026-11-05")
    iniciais = {i["ticker"]: i["quantidade"] for i in c["posicoes_iniciais"]}
    assert iniciais == {"ITUB4": 30, "PETR4": 23}  # PETR4 zerado na B3, mas vendido no período
    assert c["data_abertura"] == "2026-03-09"
    assert [d["ticker"] for d in c["divergencias"]] == ["VALE3"]  # sistema teria 15, B3 mostra 10


def test_importacao_completa_com_posicao(novo_app):
    c = cliente_logado(novo_app(lambda t: serie_simulada(t, dias=600)))
    neg = [["10/03/2026", "Compra", "Mercado à Vista", "-", "X", "ITUB4", 20, 30.0, 600],
           ["31/03/2026", "Venda", "Mercado à Vista", "-", "X", "PETR4", 23, 50.0, 1150]]
    r = c.post("/api/importar/b3/previa", content_type="multipart/form-data", data={"arquivo": [
        (io.BytesIO(xlsx_posicao()), "posicao.xlsx"), (io.BytesIO(xlsx(NEG_CAB, neg)), "negociacao.xlsx")]})
    previa = r.get_json()
    assert r.status_code == 200 and [a["tipo"] for a in previa["arquivos"]] == ["posicao", "negociacao"]
    ini = {i["ticker"]: i for i in previa["conciliacao"]["posicoes_iniciais"]}
    assert ini["ITUB4"]["quantidade"] == 30 and ini["PETR4"]["quantidade"] == 23 and ini["IVVB11"]["quantidade"] == 3
    assert ini["PETR4"]["preco"] is not None  # estimado pela cotação da data de abertura
    assert ini["TESOURO IPCA+ 2035"]["preco"] == 2000  # valor aplicado da B3

    abertura = [{"data": i["data"], "ticker": i["ticker"], "tipo": "compra", "quantidade": i["quantidade"],
                 "preco": i["preco"], "classe": i["classe"], "obs": "posição inicial"} for i in ini.values()]
    r = c.post("/api/importar/b3/confirmar", json={"aportes": abertura + previa["aportes"],
                                                    "ativos": previa["ajustes_ativos"]})
    assert r.status_code == 201, r.get_json()
    cart = {a["ticker"]: a for a in c.get("/api/carteira").get_json()["ativos"]}
    assert {t: a["quantidade"] for t, a in cart.items() if a["quantidade"]} == {
        "ITUB4": 50, "VALE3": 10, "IVVB11": 3, "TESOURO IPCA+ 2035": 1.5}
    assert cart["IVVB11"]["classe"] == "etf"
    assert cart["TESOURO IPCA+ 2035"]["preco_atual"] == 2200  # preço manual vindo da B3


FIXTURES = __import__("pathlib").Path(__file__).parent / "fixtures"


def ler_fixture(nome):
    return importacao.analisar_extrato((FIXTURES / nome).read_bytes(), nome)


def test_xls_antigo():
    r = ler_fixture("negociacao_b3.xls")
    assert r["tipo_arquivo"] == "negociacao"
    assert [(a["data"], a["ticker"], a["tipo"], a["quantidade"]) for a in r["aportes"]] == [
        ("2026-01-12", "BBAS3", "compra", 100), ("2026-02-03", "BBAS3", "venda", 40)]


def test_excel_html_de_banco_com_saldo():
    r = ler_fixture("posicao_banco.xls")
    pos = {p["ticker"]: p for p in r["posicao"]}
    assert len(pos) == 4  # linha "Total" ignorada
    cdb = pos["CDB DI BANCO EXEMPLO - VENC. 2028"]
    assert cdb["classe"] == "renda_fixa" and cdb["quantidade"] == 1 and cdb["preco_medio"] == 10000
    assert cdb["preco_atual"] == pytest.approx(11250.35)
    assert pos["FUNDO EXEMPLO MULTIMERCADO FIC FIM"]["classe"] == "outro"
    assert pos["BRASILPREV EXEMPLO PGBL"]["classe"] == "outro"


def test_pdf_com_tabela():
    r = ler_fixture("posicao_corretora.pdf")
    pos = {p["ticker"]: p for p in r["posicao"]}
    assert {t: p["quantidade"] for t, p in pos.items()} == {"PETR4": 200, "KNRI11": 15, "IVVB11": 4}
    assert pos["PETR4"]["preco_medio"] == pytest.approx(32.10) and pos["IVVB11"]["classe"] == "etf"


def test_pdf_so_texto():
    r = ler_fixture("movimentacao_b3.pdf")
    assert r["tipo_arquivo"] == "movimentacao"
    assert [(p["ticker"], p["tipo"], p["valor_total"]) for p in r["proventos"]] == [
        ("BBAS3", "dividendo", 30.0), ("BBAS3", "jcp", 12.0)]


def test_api_relatorio_de_banco(novo_app):
    c = cliente_logado(novo_app(lambda t: serie_simulada(t, dias=300)))
    previa = c.post("/api/importar/b3/previa", content_type="multipart/form-data", data={"arquivo": [
        (io.BytesIO((FIXTURES / "posicao_banco.xls").read_bytes()), "posicao_banco.xls")]}).get_json()
    ini = {i["ticker"]: i for i in previa["conciliacao"]["posicoes_iniciais"]}
    assert ini["LCA AGRO EXEMPLO"]["preco"] == 5000 and ini["LCA AGRO EXEMPLO"]["quantidade"] == 1
    manual = {a["ticker"]: a["preco_manual"] for a in previa["ajustes_ativos"]}
    assert manual["LCA AGRO EXEMPLO"] == 5320


def test_relatorio_de_carteira_com_datas_nas_colunas():
    """Relatório com resumo por classe, colunas 'SALDO BRUTO <data>' (início e fim) e linhas de grupo."""
    r = ler_fixture("relatorio_carteira.pdf")
    pos = {p["ticker"]: p for p in r["posicao"]}
    assert set(pos) == {"CDB BANCO EXEMPLO 110% CDI - 15/01/2028", "TESOURO SELIC 2029", "KNRI11"}
    assert pos["TESOURO SELIC 2029"]["preco_atual"] == 10100  # saldo bruto do fim do período
    assert pos["CDB BANCO EXEMPLO 110% CDI - 15/01/2028"]["classe"] == "renda_fixa"


def test_api_estima_quantidade_de_ativo_de_bolsa_sem_quantidade(novo_app):
    c = cliente_logado(novo_app(lambda t: [("2026-01-02", 100.0), ("2026-11-04", 83.0)]))
    previa = c.post("/api/importar/b3/previa", content_type="multipart/form-data", data={"arquivo": [
        (io.BytesIO((FIXTURES / "relatorio_carteira.pdf").read_bytes()), "relatorio.pdf")]}).get_json()
    ini = {i["ticker"]: i for i in previa["conciliacao"]["posicoes_iniciais"]}
    assert ini["KNRI11"]["quantidade"] == 50 and ini["KNRI11"]["quantidade_estimada"]  # 4150 / 83
    assert ini["TESOURO SELIC 2029"]["quantidade"] == 1 and ini["TESOURO SELIC 2029"]["preco"] == 10100


def test_relatorio_com_coluna_de_quantidade_vazia():
    cab = ["ATIVO", "QUANTIDADE", "SALDO BRUTO 30/09/2025", "SALDO BRUTO 30/09/2026", "RENTABILIDADE (%)"]
    linhas = [["CDB BANCO X 100% CDI", "", "1.000,00", "R$ 1.100,00", "10,00"],
              ["Fundo Exemplo FIM", "-", "500,00", "550,00", "10,00"],
              ["BBAS3", "100", "2.500,00", "2.800,00", "12,00"],
              ["Ativo zerado", "", "0,00", "0,00", ""]]
    r = importacao.analisar_extrato(xlsx(cab, linhas), "relatorio.xlsx")
    pos = {p["ticker"]: p for p in r["posicao"]}
    assert pos["CDB BANCO X 100% CDI"]["quantidade"] == 1 and pos["CDB BANCO X 100% CDI"]["preco_atual"] == 1100
    assert pos["FUNDO EXEMPLO FIM"]["classe"] == "outro"
    assert pos["BBAS3"]["quantidade"] == 100 and pos["BBAS3"]["preco_atual"] == 28
    assert len(r["ignorados"]) == 1 and "saldo" in r["ignorados"][0]["motivo"]


def test_realinhar_linhas_de_pdf_com_colunas_desencontradas():
    from carteira.importacao import _posicao
    cab = ["ATIVO", "QUANTIDADE", "SALDO BRUTO 30/09/2025", "ENTRADAS", "SALDO BRUTO 30/09/2026", "RENTABILIDADE (%)"]
    linhas = [cab,
              ["CDB BANCO", "EXEMPLO 110% CDI", "15.000,00", "0,00", "16.700,00", "11,33"],   # nome partido, sem quantidade
              ["PETR4", "100", "3.000,00", "R$", "0,00", "3.850,00", "28,33"],               # "R$" solto
              ["LCA AGRO", "5.000,00", "5.320,00", "6,40"]]                                 # colunas vazias sumiram
    pos = {p["ticker"]: p for p in _posicao([("PDF página 1 texto", linhas)])[0]}
    assert pos["CDB BANCO EXEMPLO 110% CDI"]["preco_atual"] == 16700
    assert pos["PETR4"]["quantidade"] == 100 and pos["PETR4"]["valor_atual"] == 3850
    assert pos["LCA AGRO"]["preco_atual"] == 5320


CAB_BB = ["ATIVO", "", "SALDO BRUTO 30/10/2025", "ENTRADAS", "SAÍDAS", "SALDO BRUTO 31/10/2026",
          "PROVISÃO IR/IOF", "SALDO LÍQUIDO 31/10/2026", "PARTICIPAÇÃO"]
CAB_BB_EXTRA = CAB_BB[:6] + [""] + CAB_BB[6:]


def abas_relatorio_bb():
    """Estrutura do 'Portfólio de Investimentos' do Banco do Brasil (cabeçalho ATIVO mesclado)."""
    return [
        ("PDF página 3 tabela 1", [["CLASSE DO ATIVO", "", "SALDO BRUTO 30/10/2025", "ENTRADAS", "SAÍDAS",
                                    "SALDO BRUTO 31/10/2026", "PROVISÃO IR/IOF", "SALDO LÍQUIDO 31/10/2026", "RENTABILIDADE (%)"],
                                   ["", "RENDA FIXA PÓS CDI", "R$ 0,00", "R$ 500,00", "R$ 0,00", "R$ 520,00", "R$ 3,00", "R$ 517,00", "4,00%"]]),
        ("PDF página 4 tabela 1", [CAB_BB,
                                   ["", "POUPANCA OURO", "R$ 1,00", "R$ 0,00", "R$ 0,00", "R$ 1,05", "R$ 0,00", "R$ 1,05", "0,01%"],
                                   ["", "LFT-010329", "R$ 0,00", "R$ 500,00", "R$ 0,00", "R$ 520,00", "R$ 3,00", "R$ 517,00", "1,00%"]]),
        ("PDF página 4 tabela 2", [CAB_BB,
                                   ["", "NTNB PRINC-150535", "R$ 2.000,00", "R$ 0,00", "R$ 0,00", "R$ 2.200,00", "R$ 30,00", "R$ 2.170,00", "5,00%"]]),
        ("PDF página 4 tabela 3", [CAB_BB_EXTRA,
                                   ["", "PETR4 - PETROBRAS", "R$ 3.000,00", "R$ 0,00", "R$ 0,00", "R$ 3.800,00", "", "R$ 0,00", "R$ 3.800,00", "8,00%"],
                                   ["", "XPML11 - FII XP MALL", "R$ 0,00", "R$ 1.000,00", "R$ 50,00", "", "R$ 1.100,00", "R$ 0,00", "R$ 1.100,00", "2,00%"]]),
        ("PDF página 5 tabela 2", [CAB_BB,
                                   ["", "ACOES BOLSA AMERICAN", "R$ 3.000,00", "R$ 0,00", "R$ 0,00", "R$ 3.300,00", "R$ 60,00", "R$ 3.240,00", "7,00%"],
                                   ["", "IVVB11 - ISHARE SP500", "R$ 0,00", "R$ 1.000,00", "R$ 0,00", "R$ 1.050,00", "R$ 0,00", "R$ 1.050,00", "2,00%"]]),
        ("PDF página 5 tabela 3", [["PRAZO EM DIAS", "", "TOTAL BRUTO", "BRUTO BLOQUEADO", "BRUTO DISPONÍVEL",
                                    "LÍQUIDO DISPONÍVEL", "PARTICIPAÇÃO (%)"],
                                   ["", "De 0 a 0", "R$ 12.000,00", "R$ 0,00", "R$ 12.000,00", "R$ 11.900,00", "100,00%"]]),
    ]


def test_relatorio_banco_do_brasil():
    from carteira.importacao import _posicao
    posicao, ignorados = _posicao(abas_relatorio_bb())
    pos = {p["ticker"]: p for p in posicao}
    assert set(pos) == {"POUPANCA OURO", "TESOURO SELIC 2029", "TESOURO IPCA+ 2035", "PETR4", "XPML11",
                        "ACOES BOLSA AMERICAN", "IVVB11"}
    assert ignorados == []
    assert pos["TESOURO SELIC 2029"]["vencimento"] == "2029-03-01" and pos["TESOURO SELIC 2029"]["tesouro"]
    assert pos["TESOURO IPCA+ 2035"]["valor_atual"] == 2200 and pos["TESOURO IPCA+ 2035"]["classe"] == "renda_fixa"
    assert pos["PETR4"]["classe"] == "acao" and pos["PETR4"]["valor_atual"] == 3800 and pos["PETR4"]["nome"] == "PETROBRAS"
    assert pos["XPML11"]["valor_atual"] == 1100  # saldo na coluna vizinha sem cabeçalho
    assert pos["ACOES BOLSA AMERICAN"]["classe"] == "exterior"
    assert pos["IVVB11"]["classe"] == "etf"


def test_api_relatorio_bb_estima_quantidades(tmp_path, monkeypatch):
    import datetime as dt
    from app import create_app
    from carteira import importacao as imp

    hoje_iso, hoje = dt.date.today().isoformat(), dt.date.today().strftime("%d/%m/%Y")
    csv_t = ("Tipo Titulo;Data Vencimento;Data Base;Taxa Compra Manha;Taxa Venda Manha;PU Compra Manha;PU Venda Manha;PU Base Manha\n"
             f"Tesouro IPCA+;15/05/2035;{hoje};7;7;2250,00;2200,00;2199,00\n"
             f"Tesouro Selic;01/03/2029;{hoje};0;0;17400,00;520,00;519,00\n")
    cotacoes = {"PETR4": 38.0, "XPML11": 110.0, "IVVB11": 350.0}
    app = create_app(str(tmp_path / "t.db"), lambda t: [("2026-01-02", 1.0), (hoje_iso, cotacoes[t])],
                     secret_key="x", fonte_bcb=lambda *a: [], fonte_tesouro=lambda: csv_t)
    c = cliente_logado(app)
    monkeypatch.setattr(imp, "ler_abas", lambda conteudo, nome: abas_relatorio_bb())
    previa = c.post("/api/importar/b3/previa", content_type="multipart/form-data",
                    data={"arquivo": [(io.BytesIO(b"%PDF"), "relatorio_bb.pdf")]}).get_json()
    ini = {i["ticker"]: i for i in previa["conciliacao"]["posicoes_iniciais"]}
    assert ini["PETR4"]["quantidade"] == 100 and ini["PETR4"]["quantidade_estimada"]  # 3.800 / 38
    assert ini["XPML11"]["quantidade"] == 10
    assert ini["TESOURO IPCA+ 2035"]["quantidade"] == 1 and ini["TESOURO IPCA+ 2035"]["preco"] == 2200
    assert ini["POUPANCA OURO"]["preco"] == pytest.approx(1.05)
    assert ini["ACOES BOLSA AMERICAN"]["classe"] == "exterior"
    ajustes = {a["ticker"]: a for a in previa["ajustes_ativos"]}
    assert ajustes["TESOURO IPCA+ 2035"]["indexador"] == "tesouro"
    assert ajustes["TESOURO SELIC 2029"]["vencimento"] == "2029-03-01"

    abertura = [{"data": i["data"], "ticker": t, "tipo": "compra", "quantidade": i["quantidade"],
                 "preco": i["preco"], "classe": i["classe"]} for t, i in ini.items()]
    r = c.post("/api/importar/b3/confirmar", json={"aportes": abertura, "ativos": previa["ajustes_ativos"]})
    assert r.status_code == 201, r.get_json()
    ativos = {a["ticker"]: a for a in c.get("/api/ativos").get_json()}
    assert ativos["TESOURO IPCA+ 2035"]["indexador"] == "tesouro" and ativos["IVVB11"]["classe"] == "etf"


def test_identificar_origem():
    from carteira.importacao import identificar_origem
    assert identificar_origem([], "negociacao") == "B3"
    assert identificar_origem([("Pág", [["RELATÓRIO"], ["bb.com.br/investimentos"]])], "posicao") == "Banco do Brasil"
    assert identificar_origem([("x", [["XP Investimentos CCTVM"]])], "posicao") == "XP"
    assert identificar_origem([("Acoes", [POS_CAB])], "posicao") == "B3"
    assert identificar_origem([("x", [["Histórico de posições"]])], "posicao") == "Outra instituição"  # "rico" não engana


def item(t, classe, q, v, **kw):
    return {"ticker": t, "classe": classe, "quantidade": q, "valor_atual": v, "preco_atual": v / q, "preco_medio": None, **kw}


def test_mesclar_posicoes():
    from carteira.importacao import mesclar_posicoes
    b3 = ("posicao_b3.xlsx", "B3", [item("PETR4", "acao", 100, 3800), item("TESOURO IPCA+ 2035", "renda_fixa", 1, 2200, tesouro=True)])
    bb = ("bb.pdf", "Banco do Brasil", [item("PETR4", "acao", 1, 3800, sem_quantidade=True),
                                        item("TESOURO IPCA+ 2035", "renda_fixa", 1, 2200, tesouro=True),
                                        item("POUPANCA OURO", "renda_fixa", 1, 500)])
    xp = ("xp.pdf", "XP", [item("PETR4", "acao", 50, 1900), item("FUNDO XP", "outro", 1, 1000)])
    pos, conf = mesclar_posicoes([b3, bb])
    p = {i["ticker"]: i for i in pos}
    assert p["PETR4"]["quantidade"] == 100 and p["PETR4"]["origem"] == "B3"
    assert "POUPANCA OURO" in p and p["POUPANCA OURO"]["origem"] == "Banco do Brasil"
    assert {c["ticker"] for c in conf} == {"PETR4", "TESOURO IPCA+ 2035"}

    pos, conf = mesclar_posicoes([("bb2.pdf", "Banco do Brasil", [item("PETR4", "acao", 100, 3800)]), xp])
    p = {i["ticker"]: i for i in pos}
    assert p["PETR4"]["quantidade"] == 150 and p["PETR4"]["valor_atual"] == 5700  # instituições diferentes: soma
    assert conf[0]["acao"] == "somado"

    pos, conf = mesclar_posicoes([bb, ("bb_copia.pdf", "Banco do Brasil", bb[2])])
    assert {i["ticker"]: i["quantidade"] for i in pos}["POUPANCA OURO"] == 1 and len(conf) == 3


def xlsx_relatorio(instituicao, linhas):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append([f"Relatório de posição - {instituicao}"])
    ws.append(["Ativo", "Quantidade", "Preço médio", "Saldo atual"])
    for l in linhas:
        ws.append(l)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_api_varios_relatorios_e_reimportacao(novo_app):
    c = cliente_logado(novo_app(lambda t: serie_simulada(t, dias=300)))
    b3 = xlsx_posicao()  # ITUB4 50, VALE3 10, IVVB11 3, Tesouro IPCA+ 2035
    bb = xlsx_relatorio("Banco do Brasil", [["ITUB4", 50, 30, 1750], ["FUNDO BB RF REFERENCIADO DI", "", "", 8000]])
    enviar = lambda *arqs, modo="completa": c.post(  # noqa: E731
        "/api/importar/b3/previa", content_type="multipart/form-data",
        data={"arquivo": [(io.BytesIO(conteudo), nome) for nome, conteudo in arqs], "modo": modo}).get_json()
    previa = enviar(("posicao_b3.xlsx", b3), ("bb.xlsx", bb))
    assert [a["origem"] for a in previa["arquivos"]] == ["B3", "Banco do Brasil"]
    pos = {p["ticker"]: p for p in previa["posicao"]}
    assert pos["ITUB4"]["quantidade"] == 50 and pos["ITUB4"]["origem"] == "B3"  # não duplicou
    assert pos["FUNDO BB RF REFERENCIADO DI"]["origem"] == "Banco do Brasil"
    assert any(x["ticker"] == "ITUB4" for x in previa["conflitos"])
    ini_itub = next(i for i in previa["conciliacao"]["posicoes_iniciais"] if i["ticker"] == "ITUB4")
    assert ini_itub["preco"] == 30  # preço médio do BB aproveitado para a posição da B3

    ini = previa["conciliacao"]["posicoes_iniciais"]
    abertura = [{"data": i["data"], "ticker": i["ticker"], "tipo": "compra", "quantidade": i["quantidade"],
                 "preco": i["preco"] or 10, "classe": i["classe"]} for i in ini]
    r = c.post("/api/importar/b3/confirmar", json={"aportes": abertura, "arquivos": previa["arquivos"]})
    assert r.status_code == 201
    de_novo = enviar(("posicao_b3.xlsx", b3))
    assert de_novo["arquivos"][0]["ja_importado"]  # aviso de arquivo já importado
    assert de_novo["conciliacao"]["posicoes_iniciais"] == []  # e nada a acrescentar
    assert c.get("/api/importacoes").get_json()[0]["origem"] in ("B3", "Banco do Brasil")

    # outra corretora, importada depois: "parcial" soma ao que já existe
    xp = xlsx_relatorio("XP Investimentos", [["ITUB4", 20, 31, 700]])
    completa = enviar(("xp.xlsx", xp))
    # completa: parece que sobra ITUB4 -> proposto como ajuste (baixa); VALE3/IVVB11 ausentes ficam desmarcados
    aj = {a["ticker"]: a for a in completa["ajustes"]}
    assert aj["ITUB4"]["diferenca"] == -30 and aj["ITUB4"]["acao"] == "baixa" and aj["ITUB4"]["marcado"]
    assert not aj["VALE3"]["marcado"] and completa["aviso_ajustes"]
    parcial = enviar(("xp.xlsx", xp), modo="parcial")
    assert parcial["arquivos"][0]["origem"] == "XP"
    assert {i["ticker"]: i["quantidade"] for i in parcial["conciliacao"]["posicoes_iniciais"]} == {"ITUB4": 20}


def test_movimentacao_b3_em_pdf():
    """Extrato de Movimentação da B3 em PDF: registros em várias linhas, agrupados por data."""
    r = ler_fixture("movimentacao_b3_layout.pdf")
    assert r["tipo_arquivo"] == "movimentacao" and r["origem"] == "B3"
    assert [(p["data_pagamento"], p["ticker"], p["tipo"], p["valor_total"]) for p in r["proventos"]] == [
        ("2026-11-10", "VGHF11", "rendimento", 7.92), ("2026-11-10", "ITUB4", "jcp", 30.0),
        ("2026-10-15", "MXRF11", "rendimento", 10.0)]
    motivos = [g["motivo"] for g in r["ignorados"]]
    assert sum("Negociação" in m for m in motivos) == 2 and any("Evento corporativo" in m for m in motivos)


def test_copia_de_seguranca_antes_da_importacao(novo_app, tmp_path, monkeypatch):
    import sqlite3
    monkeypatch.setenv("CARTEIRA_BACKUP_DIR", str(tmp_path / "copias"))
    c = cliente_logado(novo_app(lambda t: serie_simulada(t, dias=300)))
    c.post("/api/aportes", json={"data": "2025-01-02", "ticker": "PETR4", "quantidade": 10, "preco": 30})
    r = c.post("/api/importar/b3/confirmar", json={"aportes": [
        {"data": "2025-02-03", "ticker": "VALE3", "tipo": "compra", "quantidade": 5, "preco": 60}]})
    assert r.status_code == 201
    nome = r.get_json()["copia_seguranca"]
    assert nome.startswith("antes-importacao-")
    copia = sqlite3.connect(tmp_path / "copias" / nome)
    assert [t for (t,) in copia.execute("SELECT ticker FROM aportes")] == ["PETR4"]  # estado de antes
    assert any(x["nome"] == nome for x in c.get("/api/backup").get_json()["copias"])


def test_ajustes_de_quantidade_pelo_relatorio(novo_app):
    c = cliente_logado(novo_app(lambda t: serie_simulada(t, dias=300)))
    for t, q, p in (("ITUB4", 100, 30), ("VALE3", 10, 60), ("BBAS3", 20, 25)):
        assert c.post("/api/aportes", json={"data": "2025-01-02", "ticker": t, "quantidade": q, "preco": p}).status_code == 201
    rel = xlsx_relatorio("XP Investimentos", [["ITUB4", 60, 30, 1800], ["VALE3", 20, 30, 600], ["WEGE3", 5, 40, 200]])
    previa = c.post("/api/importar/b3/previa", content_type="multipart/form-data",
                    data={"arquivo": (io.BytesIO(rel), "xp.xlsx"), "modo": "completa"}).get_json()
    aj = {a["ticker"]: a for a in previa["ajustes"]}
    assert (aj["ITUB4"]["diferenca"], aj["ITUB4"]["acao"], aj["ITUB4"]["marcado"]) == (-40, "baixa", True)
    assert (aj["VALE3"]["diferenca"], aj["VALE3"]["fator"]) == (10, 2)
    assert aj["WEGE3"]["diferenca"] == 5 and aj["WEGE3"]["fator"] is None and aj["WEGE3"]["marcado"]
    assert not aj["BBAS3"]["marcado"]  # ausente do relatório: só com confirmação
    assert previa["conciliacao"]["posicoes_iniciais"] == [] and previa["conciliacao"]["divergencias"] == []

    hoje = aj["ITUB4"]["data"]
    ajustes = [{"ticker": "ITUB4", "classe": "acao", "data": hoje, "acao": "baixa", "quantidade": 40, "preco": 35},
               {"ticker": "VALE3", "classe": "acao", "data": hoje, "acao": "desdobramento", "fator": 2},
               {"ticker": "WEGE3", "classe": "acao", "data": hoje, "acao": "bonificacao", "quantidade": 5, "preco": 0}]
    r = c.post("/api/importar/b3/confirmar", json={"ajustes": ajustes})
    assert r.status_code == 201 and r.get_json()["ajustes"] == 3
    pos = {a["ticker"]: a for a in c.get("/api/carteira").get_json()["ativos"]}
    assert pos["ITUB4"]["quantidade"] == 60 and pos["ITUB4"]["preco_medio"] == pytest.approx(30)
    assert pos["ITUB4"]["realizado"] == 0  # baixa: sem lucro nem prejuízo
    assert pos["VALE3"]["quantidade"] == 20 and pos["VALE3"]["custo"] == pytest.approx(600)
    assert pos["WEGE3"]["quantidade"] == 5 and pos["WEGE3"]["custo"] == 0
    imp = c.get(f"/api/impostos?ano={hoje[:4]}").get_json()
    assert imp["resumo"]["vendas_acoes"] == 0  # a baixa não conta como venda no IR
    fluxo = c.get(f"/api/fluxo?inicio={hoje}&fim={hoje}").get_json()
    assert fluxo["totais"]["vendas"] == 0 and fluxo["totais"]["compras"] == 0  # ajustes sem dinheiro

    # Depois chega o extrato de negociação com a venda real de ITUB4: o ajuste anterior é substituído
    neg = xlsx(NEG_CAB, [["10/03/2025", "Venda", "Mercado à Vista", "-", "CORRETORA X", "ITUB4", 40, 33, 1320]])
    previa = enviar(c, neg, "neg.xlsx").get_json()
    assert [(a["ticker"], a["ajuste"]) for a in previa["ajustes_anteriores"]] == [("ITUB4", "baixa")]
    r = c.post("/api/importar/b3/confirmar", json={
        "aportes": previa["aportes"], "remover_ajustes": [a["id"] for a in previa["ajustes_anteriores"]]})
    assert r.status_code == 201 and r.get_json()["ajustes_removidos"] == 1
    pos = {a["ticker"]: a for a in c.get("/api/carteira").get_json()["ativos"]}
    assert pos["ITUB4"]["quantidade"] == 60 and pos["ITUB4"]["realizado"] == pytest.approx(120)


def test_ajuste_venda_entra_no_ir():
    from carteira import impostos, portfolio
    ops = [{"id": 1, "data": "2025-01-02", "ticker": "ITUB4", "tipo": "compra", "quantidade": 100, "preco": 30},
           {"id": 2, "data": "2025-06-02", "ticker": "ITUB4", "tipo": "venda", "quantidade": 40, "preco": 35,
            "ajuste": "venda"},
           {"id": 3, "data": "2025-06-03", "ticker": "ITUB4", "tipo": "venda", "quantidade": 10, "preco": 99,
            "ajuste": "baixa"}]
    assert portfolio.calcular_posicoes(ops)["ITUB4"]["realizado"] == pytest.approx(200)
    meses = {m["mes"]: m for m in impostos.apurar(ops, {"ITUB4": "acao"})}
    assert meses["2025-06"]["vendas_acoes"] == pytest.approx(1400)


def test_vendas_antes_da_posicao_inicial_antiga(novo_app):
    """Importação anterior criou a posição inicial em 01/04; agora chega um extrato com venda em 31/03."""
    c = cliente_logado(novo_app(lambda t: serie_simulada(t, dias=600)))
    r = c.post("/api/importar/b3/confirmar", json={"aportes": [
        {"data": "2026-04-01", "ticker": "PETR4", "tipo": "compra", "quantidade": 14, "preco": 30,
         "classe": "acao", "obs": "posição inicial (importação)"}]})
    assert r.status_code == 201
    neg = xlsx(NEG_CAB, [["31/03/2026", "Venda", "Mercado à Vista", "-", "CORRETORA X", "PETR4", 14, 35, 490]])
    # só o extrato: a venda vem antes da posição conhecida -> recusa com orientação
    so_neg = enviar(c, neg, "neg.xlsx").get_json()
    assert so_neg["ajustes_anteriores"] == []
    r = c.post("/api/importar/b3/confirmar", json={"aportes": so_neg["aportes"]})
    assert r.status_code == 409 and "Posição atual" in r.get_json()["erro"]
    # extrato + posição atual (14): substitui a posição inicial antiga por 28 antes da venda
    pos = xlsx_relatorio("B3", [["PETR4", 14, 30, 420]])
    previa = c.post("/api/importar/b3/previa", content_type="multipart/form-data", data={
        "arquivo": [(io.BytesIO(neg), "neg.xlsx"), (io.BytesIO(pos), "posicao.xlsx")]}).get_json()
    assert [(a["ticker"], a["ajuste"]) for a in previa["ajustes_anteriores"]] == [("PETR4", "posicao_inicial")]
    ini = previa["conciliacao"]["posicoes_iniciais"]
    assert [(i["ticker"], i["quantidade"], i["data"]) for i in ini] == [("PETR4", 28, "2026-03-30")]
    r = c.post("/api/importar/b3/confirmar", json={
        "aportes": [{**i, "tipo": "compra", "preco": 30} for i in ini] + previa["aportes"],
        "remover_ajustes": [a["id"] for a in previa["ajustes_anteriores"]]})
    assert r.status_code == 201
    pos = {a["ticker"]: a for a in c.get("/api/carteira").get_json()["ativos"]}
    assert pos["PETR4"]["quantidade"] == 14 and pos["PETR4"]["realizado"] == pytest.approx(70)


def test_conciliacao_cobre_vendas_anteriores_mesmo_com_total_igual():
    # o total bate (14 + 9 - 23 = 0), mas a venda de 31/03 acontece antes da compra de 10/04
    existentes = [{"id": 1, "data": "2026-03-01", "ticker": "PETR4", "tipo": "compra", "quantidade": 14, "preco": 30}]
    novos = [{"data": "2026-03-31", "ticker": "PETR4", "tipo": "venda", "quantidade": 23, "preco": 35},
             {"data": "2026-04-10", "ticker": "PETR4", "tipo": "compra", "quantidade": 9, "preco": 36}]
    c = importacao.conciliar_posicao([], existentes, novos, "2026-11-05")
    assert [(i["ticker"], i["quantidade"]) for i in c["posicoes_iniciais"]] == [("PETR4", 9)]
    assert [d["ticker"] for d in c["divergencias"]] == ["PETR4"]


def _xlsx_strict(linhas_xml):
    import zipfile
    ns = "http://purl.oclc.org/ooxml/spreadsheetml/main"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("xl/workbook.xml", f'<workbook xmlns="{ns}" xmlns:r="http://purl.oclc.org/ooxml/officeDocument/'
                   'relationships"><sheets><sheet name="Extrato" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/'
                   '2006/relationships"><Relationship Id="rId1" Type="x" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr("xl/worksheets/sheet1.xml", f'<worksheet xmlns="{ns}"><dimension ref="A1:G1"/><sheetData>'
                   f'{linhas_xml}</sheetData></worksheet>')
    return buf.getvalue()


def test_xlsx_que_o_openpyxl_nao_le_inteiro():
    txt = lambda t: f'<c t="inlineStr"><is><t>{t}</t></is></c>'  # noqa: E731
    xml = (f'<row r="1">{txt("EXTRATO CONSOLIDADO - 11/2026")}</row>'
           f'<row>{txt("Título")}{txt("Quantidade")}{txt("Valor bruto")}</row>'
           f'<row>{txt("Tesouro Selic 2029")}<c><v>1.5</v></c><c><v>24000.5</v></c></row>')
    abas = importacao.ler_abas(_xlsx_strict(xml), "extrato.xlsx")
    assert abas == [("Extrato", [["EXTRATO CONSOLIDADO - 11/2026"], ["Título", "Quantidade", "Valor bruto"],
                                 ["Tesouro Selic 2029", 1.5, 24000.5]])]


def test_leitura_bruta_igual_a_do_openpyxl():
    conteudo = xlsx(NEG_CAB, NEG)
    wb = openpyxl.load_workbook(io.BytesIO(conteudo), data_only=True)
    esperado = [[c for c in r] for r in wb.active.iter_rows(values_only=True)]
    bruto = importacao.ler_xlsx_bruto(conteudo)[0][1]
    assert [[c for c in l if c is not None] for l in bruto] == [[c for c in l if c is not None] for l in esperado]
