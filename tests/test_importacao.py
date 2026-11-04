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
    assert r.get_json() == {"ok": True, "aportes": 1, "proventos": 3}
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
    with pytest.raises(importacao.ErroImportacao, match="Colunas encontradas: Coluna A, Coluna B, Coluna C"):
        importacao.analisar_extrato(xlsx(["Coluna A", "Coluna B", "Coluna C"], [[1, 2, 3]]), "x.xlsx")
