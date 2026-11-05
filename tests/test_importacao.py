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
    assert r.get_json() == {"ok": True, "aportes": 1, "proventos": 3, "ativos": 0}
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
