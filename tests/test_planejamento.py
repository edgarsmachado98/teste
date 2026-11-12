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
    monkeypatch.setenv("CARTEIRA_MODULOS", "nenhum")
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


# ------------------------------------------------------------------ fase 2: faturas
import io  # noqa: E402

from carteira import fatura as fat  # noqa: E402

OFX = """OFXHEADER:100
DATA:OFXSGML
<OFX><CREDITCARDMSGSRSV1><CCSTMTTRNRS><CCSTMTRS><BANKTRANLIST>
<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20261003000000[-3:BRT]<TRNAMT>-89.90<FITID>a1<MEMO>IFOOD *PIZZARIA BELLA SAO PAULO</STMTTRN>
<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20261005<TRNAMT>-420.00<FITID>a2<MEMO>MAGAZINE LUIZA PARC 03/10</STMTTRN>
<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20261007<TRNAMT>-55.20<FITID>a3<MEMO>POSTO SHELL AV BRASIL</STMTTRN>
<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20261008<TRNAMT>-13.37<FITID>a4<MEMO>IOF COMPRA INTERNACIONAL</STMTTRN>
<STMTTRN><TRNTYPE>CREDIT<DTPOSTED>20261009<TRNAMT>30.00<FITID>a5<MEMO>ESTORNO LOJA ABC</STMTTRN>
<STMTTRN><TRNTYPE>CREDIT<DTPOSTED>20261010<TRNAMT>2500.00<FITID>a6<MEMO>PAGAMENTO RECEBIDO</STMTTRN>
<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20261011<TRNAMT>-120.00<FITID>a7<MEMO>LOJA DESCONHECIDA XYZ</STMTTRN>
</BANKTRANLIST></CCSTMTRS></CCSTMTTRNRS></CREDITCARDMSGSRSV1></OFX>"""

CSV_NUBANK = """date,title,amount
2026-10-03,Ifood *Pizzaria Bella,89.90
2026-10-05,Magazine Luiza - Parcela 3/10,420.00
2026-10-10,Pagamento recebido,-2500.00
2026-10-12,Netflix.com,55.90
"""

CSV_ITAU = """data;lançamento;valor
03/10/2026;UBER *TRIP;-23,50
04/10/2026;DROGASIL 123;-45,10
06/10/2026;SUPERMERCADO DIA;-312,77
"""


def test_ler_ofx_e_classificar():
    itens = fat.ler_fatura(OFX.encode(), "fatura.ofx")
    tipos = [(i["descricao"][:14], i["tipo"], i["valor"]) for i in itens]
    assert tipos[0] == ("IFOOD *PIZZARI", "compra", 89.9)
    assert [i["tipo"] for i in itens] == ["compra", "compra", "compra", "tarifa", "estorno", "pagamento", "compra"]
    mag = itens[1]
    assert (mag["parcela_num"], mag["parcela_total"], mag["base"]) == (3, 10, "MAGAZINE LUIZA")
    assert itens[0]["data"] == "2026-10-03"


def test_ler_csv_de_bancos_diferentes():
    nu = fat.ler_fatura(CSV_NUBANK.encode(), "nubank.csv")
    assert [(i["tipo"], i["valor"]) for i in nu] == [("compra", 89.9), ("compra", 420.0), ("pagamento", 2500.0),
                                                    ("compra", 55.9)]
    itau = fat.ler_fatura(CSV_ITAU.encode("utf-8"), "itau.csv")  # compras negativas: o sinal é invertido
    assert [(i["tipo"], i["valor"]) for i in itau] == [("compra", 23.5), ("compra", 45.1), ("compra", 312.77)]
    with pytest.raises(fat.ErroImportacao, match="PDF"):
        fat.ler_fatura(b"%PDF-1.4", "fatura.pdf")


def test_importar_fatura_categoriza_aprende_e_nao_duplica(novo_app, com_modulo):
    c = cliente_logado(novo_app(fonte))
    cartao = c.post("/api/plan/cartoes", json={"nome": "Nubank", "dia_vencimento": 15}).get_json()["id"]
    envio = lambda conteudo, nome: c.post("/api/plan/fatura/previa", content_type="multipart/form-data",  # noqa: E731
                                          data={"arquivo": (io.BytesIO(conteudo), nome), "cartao_id": cartao}).get_json()
    p = envio(OFX.encode(), "fatura.ofx")
    it = {i["descricao"][:12]: i for i in p["itens"]}
    nomes = {x["id"]: x["nome"] for x in c.get("/api/plan/categorias").get_json()["categorias"]}
    assert nomes[it["IFOOD *PIZZA"]["categoria_id"]] == "Delivery" and it["IFOOD *PIZZA"]["origem_categoria"] == "padrao"
    assert nomes[it["POSTO SHELL "]["categoria_id"]] == "Combustível"
    assert nomes[it["IOF COMPRA I"]["categoria_id"]] == "Tarifas bancárias"
    assert nomes[it["ESTORNO LOJA"]["categoria_id"]] == "Estornos e reembolsos"
    assert it["LOJA DESCONH"]["categoria_id"] is None
    assert nomes[it["MAGAZINE LUI"]["categoria_id"]] == "Compras (lojas e internet)"
    assert not it["PAGAMENTO RE"]["marcado"]
    assert p["resumo"]["compras"] == 5 and p["resumo"]["parceladas"] == 1
    # o usuário escolhe a categoria da loja desconhecida e importa (pagamento fica de fora)
    it["LOJA DESCONH"]["categoria_id"] = cat(c, "despesa", "Roupas")
    r = c.post("/api/plan/fatura/confirmar", json={"cartao_id": cartao, "itens": [i for i in p["itens"] if i["marcado"]],
                                                   "data_modo": "compra", "vencimento": "2026-11-15"})
    j = r.get_json()
    assert r.status_code == 201 and j["lancamentos"] == 6 and j["parcelas_futuras"] == 7
    assert j["regras_aprendidas"] == 1  # só a escolha do usuário; aceitar sugestões não vira regra
    out = c.get("/api/plan/lancamentos?mes=2026-10").get_json()["lancamentos"]
    assert {(l["tipo"], l["valor"]) for l in out} >= {("despesa", 89.9), ("receita", 30.0), ("despesa", 420.0)}
    assert all(l["cartao_id"] == cartao and l["forma"] == "credito" for l in out)
    # parcelas 4..10 lançadas nos meses seguintes
    nov = c.get("/api/plan/lancamentos?mes=2026-11").get_json()["lancamentos"]
    assert [(l["parcela_num"], l["parcela_total"], l["descricao"]) for l in nov] == [(4, 10, "MAGAZINE LUIZA PARC 04/10")]
    assert {l["data"][:7] for l in out} == {"2026-10"}  # data de cada compra (padrão), mesmo com vencimento enviado
    # aprendeu: a mesma loja já vem com a categoria escolhida
    p2 = envio(OFX.encode(), "fatura.ofx")
    loja = next(i for i in p2["itens"] if i["descricao"].startswith("LOJA DESCONHECIDA"))
    assert loja["origem_categoria"] == "aprendida" and nomes[loja["categoria_id"]] == "Roupas"
    # reimportar a mesma fatura: tudo marcado como já importado
    assert all(i["ja_importado"] for i in p2["itens"] if i["tipo"] != "pagamento")
    # fatura do mês seguinte com a parcela 4/10: já lançada, não duplica
    prox = OFX.replace("PARC 03/10", "PARC 04/10").replace("20261005", "20261105")
    p3 = envio(prox.encode(), "fatura-nov.ofx")
    assert next(i for i in p3["itens"] if i["parcela_num"] == 4)["ja_importado"]
    # resumo: gastos por cartão no mês (compras − estornos)
    res = c.get("/api/plan/resumo?mes=2026-10").get_json()
    assert res["cartoes"][0]["nome"] == "Nubank"
    assert res["cartoes"][0]["total"] == pytest.approx(89.9 + 420 + 55.2 + 13.37 + 120 - 30)


def test_fatura_na_data_de_vencimento(novo_app, com_modulo):
    c = cliente_logado(novo_app(fonte))
    cartao = c.post("/api/plan/cartoes", json={"nome": "Itaú"}).get_json()["id"]
    p = c.post("/api/plan/fatura/previa", content_type="multipart/form-data",
               data={"arquivo": (io.BytesIO(CSV_ITAU.encode()), "itau.csv"), "cartao_id": cartao}).get_json()
    c.post("/api/plan/fatura/confirmar", json={"cartao_id": cartao, "itens": p["itens"], "data_modo": "vencimento",
                                               "vencimento": "2026-11-10"})
    datas = {l["data"] for l in c.get("/api/plan/lancamentos?mes=2026-11").get_json()["lancamentos"]}
    assert datas == {"2026-11-10"}
    assert c.post("/api/plan/fatura/previa", content_type="multipart/form-data",
                  data={"arquivo": (io.BytesIO(b"x"), "a.csv"), "cartao_id": 999}).status_code == 400


def ler_fixture(nome):
    import os
    return open(os.path.join(os.path.dirname(__file__), "fixtures", nome), "rb").read()


def test_fatura_pdf_estilo_bb():
    itens = fat.ler_fatura(ler_fixture("fatura_cartao_bb.pdf"), "fatura.pdf")
    resumo = [(i["data"], i["tipo"], i["valor"]) for i in itens]
    assert resumo == [("2026-11-04", "pagamento", 2500.0), ("2026-11-05", "compra", 312.45),
                      ("2026-11-07", "compra", 189.9), ("2026-11-10", "compra", 420.0), ("2026-11-15", "compra", 55.9),
                      ("2026-11-18", "compra", 52.3), ("2026-11-20", "tarifa", 1.83), ("2026-11-25", "estorno", 30.0),
                      ("2026-11-30", "compra", 30.0)]
    assert itens[3]["parcela_num"] == 3 and itens[3]["parcela_total"] == 10
    # saldo anterior, total da fatura e pagamento mínimo não viram lançamentos
    assert not any("SALDO" in i["descricao"] or "Total" in i["descricao"] for i in itens)


def test_fatura_pdf_com_senha():
    conteudo = ler_fixture("fatura_cartao_bb_senha.pdf")
    with pytest.raises(fat.ErroImportacao, match="tem senha"):
        fat.ler_fatura(conteudo, "fatura.pdf")
    with pytest.raises(fat.ErroImportacao, match="incorreta"):
        fat.ler_fatura(conteudo, "fatura.pdf", "000")
    assert len(fat.ler_fatura(conteudo, "fatura.pdf", "12345")) == 9


def test_ano_da_fatura_pelo_vencimento():
    import datetime as dt
    assert fat._ano_referencia("Vencimento: 10/01/2027") == dt.date(2027, 1, 10)


def test_api_fatura_pdf_com_senha(novo_app, com_modulo):
    c = cliente_logado(novo_app(fonte))
    cartao = c.post("/api/plan/cartoes", json={"nome": "Ourocard"}).get_json()["id"]
    envio = lambda **extra: c.post("/api/plan/fatura/previa", content_type="multipart/form-data", data={  # noqa: E731
        "arquivo": (io.BytesIO(ler_fixture("fatura_cartao_bb_senha.pdf")), "fatura.pdf"), "cartao_id": cartao, **extra})
    assert "senha" in envio().get_json()["erro"]
    p = envio(senha="12345").get_json()
    assert p["resumo"]["compras"] == 7 and p["resumo"]["parceladas"] == 1


# ------------------------------------------------------------------ fase 3: família
def test_acerto_proporcional_e_meio_a_meio():
    pessoas = [{"id": 1, "nome": "Edgar", "renda": 6000, "pagou": 3000},
               {"id": 2, "nome": "Eliandra", "renda": 4000, "pagou": 1000}]
    r = plan.acerto_familia(pessoas, "proporcional")
    assert r["total"] == 4000 and [round(p["cota"]) for p in r["pessoas"]] == [2400, 1600]
    assert r["transferencias"] == [{"de": "Eliandra", "para": "Edgar", "valor": 600.0}]
    r = plan.acerto_familia(pessoas, "meio")
    assert r["transferencias"] == [{"de": "Eliandra", "para": "Edgar", "valor": 1000.0}]
    assert plan.acerto_familia(pessoas, "junto")["transferencias"] == []
    r = plan.acerto_familia(pessoas, "personalizado", {"1": 70, "2": 30})
    assert r["transferencias"][0]["valor"] == pytest.approx(200)


def test_api_familia(novo_app, com_modulo):
    app = novo_app(fonte)
    edgar = cliente_logado(app)
    edgar.post("/api/usuarios", json={"nome": "Eliandra", "email": "eli@x.com", "senha": "senha-eli-123",
                                      "criar_carteira": True, "nome_carteira": "Carteira Eliandra"})
    eli = cliente_logado(app, "eli@x.com", "senha-eli-123")
    mes = dt.date.today().isoformat()[:7]
    edgar.post("/api/plan/lancamentos", json={"tipo": "receita", "data": f"{mes}-05", "valor": 6000})
    eli.post("/api/plan/lancamentos", json={"tipo": "receita", "data": f"{mes}-05", "valor": 4000})
    edgar.post("/api/plan/lancamentos", json={"tipo": "despesa", "data": f"{mes}-10", "valor": 3000, "compartilhado": True})
    eli.post("/api/plan/lancamentos", json={"tipo": "despesa", "data": f"{mes}-10", "valor": 1000, "compartilhado": True})
    eli.post("/api/plan/lancamentos", json={"tipo": "despesa", "data": f"{mes}-11", "valor": 300})  # pessoal
    f = edgar.get(f"/api/plan/familia?mes={mes}").get_json()
    assert f["modo"] == "proporcional" and f["pode_configurar"]
    assert f["totais"]["compartilhadas"] == 4000 and f["totais"]["despesas"] == 4300
    assert f["transferencias"] == [{"de": "Eliandra", "para": "Edgar Machado", "valor": 600.0}]
    assert eli.put("/api/plan/familia", json={"modo": "meio"}).status_code == 403  # só o administrador
    assert edgar.put("/api/plan/familia", json={"modo": "meio"}).status_code == 200
    assert edgar.get(f"/api/plan/familia?mes={mes}").get_json()["transferencias"][0]["valor"] == 1000


# ------------------------------------------------------------------ fase 4: objetivos
def test_calculos_de_objetivo():
    assert plan.aporte_necessario(12000, 0, 12, 0) == 1000
    pmt = plan.aporte_necessario(100000, 10000, 120, plan.taxa_mensal(4))
    v = 10000
    for _ in range(120):
        v = v * (1 + plan.taxa_mensal(4)) + pmt
    assert v == pytest.approx(100000, rel=1e-6)
    assert plan.meses_para_atingir(1000, 0, 100, 0) == 10
    assert plan.meses_para_atingir(1000, 0, 0, 0) is None
    hoje = "2026-11-12"
    apos = plan.avaliar_objetivo({"tipo": "aposentadoria", "renda_desejada": 10000, "idade_atual": 40, "idade_alvo": 60,
                                  "rentabilidade": 4, "aporte_mensal": 0, "valor_guardado": 0}, {}, None, hoje)
    assert apos["valor_alvo_calc"] == 3_000_000 and apos["data_alvo_calc"] == "2046-11-01"
    assert apos["situacao"] == "em_risco" and apos["aporte_necessario"] > 0
    res = plan.avaliar_objetivo({"tipo": "reserva", "meses_reserva": 6, "valor_guardado": 5000, "tickers": "TESOURO SELIC 2029",
                                 "aporte_mensal": 2000, "rentabilidade": 0}, {"TESOURO SELIC 2029": 10000}, 4000, hoje)
    assert res["valor_alvo_calc"] == 24000 and res["valor_atual"] == 15000 and res["situacao"] == "no_ritmo"


def test_api_objetivos(novo_app, com_modulo):
    c = cliente_logado(novo_app(fonte))
    c.post("/api/aportes", json={"data": "2025-01-02", "ticker": "ITUB4", "quantidade": 100, "preco": 30})
    assert c.post("/api/plan/objetivos", json={"tipo": "imovel"}).get_json()["erro"] == "Informe o valor do objetivo."
    assert "idade" in c.post("/api/plan/objetivos", json={"tipo": "aposentadoria", "renda_desejada": 8000}).get_json()["erro"]
    r = c.post("/api/plan/objetivos", json={"tipo": "imovel", "nome": "Entrada do apartamento", "valor_alvo": 120000,
                                            "data_alvo": "2031-01", "aporte_mensal": 1500, "tickers": ["itub4"]})
    assert r.status_code == 201
    o = c.get("/api/plan/objetivos").get_json()
    obj = o["objetivos"][0]
    assert obj["tickers"] == ["ITUB4"] and obj["em_ativos"] > 0 and obj["data_alvo_calc"] == "2031-01-01"
    assert obj["aporte_necessario"] > 0 and o["total_necessario"] == pytest.approx(obj["aporte_necessario"])
    assert any(a["ticker"] == "ITUB4" for a in o["ativos"])
    oid = obj["id"]
    assert c.put(f"/api/plan/objetivos/{oid}", json={**{k: obj[k] for k in ("tipo", "nome", "data_alvo")},
                                                     "valor_alvo": 1, "tickers": ["ITUB4"]}).status_code == 200
    assert c.get("/api/plan/objetivos").get_json()["objetivos"][0]["situacao"] == "atingido"
    c.delete(f"/api/plan/objetivos/{oid}")
    assert c.get("/api/plan/objetivos").get_json()["objetivos"] == []


# ------------------------------------------------------------------ fase 5: orçamento, projeção, IR, alertas
def test_orcamento_projecao_ir_e_alertas(novo_app, com_modulo):
    c = cliente_logado(novo_app(fonte))
    hoje = dt.date.today()
    mes = hoje.isoformat()[:7]
    c.post("/api/plan/lancamentos", json={"tipo": "receita", "data": f"{mes}-01", "valor": 8000, "valor_bruto": 10000,
                                          "categoria_id": cat(c, "receita", "Salário"), "repetir": "mensal"})
    c.post("/api/plan/lancamentos", json={"tipo": "despesa", "data": f"{mes}-01", "valor": 900,
                                          "categoria_id": cat(c, "despesa", "Mercado")})
    c.post("/api/plan/lancamentos", json={"tipo": "despesa", "data": f"{mes}-02", "valor": 1200,
                                          "categoria_id": cat(c, "despesa", "Plano de saúde"), "repetir": "mensal"})
    c.post("/api/plan/lancamentos", json={"tipo": "despesa", "data": hoje.isoformat(), "valor": 300, "pago": False,
                                          "descricao": "Conta de luz", "categoria_id": cat(c, "despesa", "Energia")})
    c.put("/api/plan/orcamento", json={"limites": {"Alimentação": 1000, "Saúde": 1000, "Lazer": ""}})
    o = {i["grupo"]: i for i in c.get(f"/api/plan/orcamento?mes={mes}").get_json()["itens"]}
    assert o["Alimentação"]["estado"] == "atencao" and o["Alimentação"]["pct"] == 90
    assert o["Saúde"]["estado"] == "estourado" and o["Lazer"]["estado"] == "sem_limite"
    p = c.get("/api/plan/projecao").get_json()["meses"]
    assert len(p) == 12 and p[1]["receitas"] == 8000 and p[1]["despesas"] == 1200
    ir = c.get(f"/api/plan/ir?ano={hoje.year}").get_json()
    assert ir["rendimentos_brutos"] >= 10000 and ir["descontos"] >= 2000
    assert any(d["categoria"] == "Plano de saúde" for d in ir["dedutiveis"])
    alertas = c.get("/api/alertas").get_json()["itens"]
    tipos = {a["tipo"] for a in alertas}
    assert {"orcamento", "conta"} <= tipos
    assert any("Conta de luz" in a["titulo"] for a in alertas)


def test_alertas_do_modulo_somem_sem_licenca(novo_app, monkeypatch):
    monkeypatch.delenv("CARTEIRA_DEMO", raising=False)
    monkeypatch.setenv("CARTEIRA_MODULOS", "nenhum")
    c = cliente_logado(novo_app(fonte))
    assert not any(a["tipo"] in ("orcamento", "conta") for a in c.get("/api/alertas").get_json()["itens"])


def test_modulos_liberados_na_fase_de_testes(monkeypatch):
    from carteira import licenca
    monkeypatch.delenv("CARTEIRA_DEMO", raising=False)
    monkeypatch.delenv("CARTEIRA_MODULOS", raising=False)
    assert licenca.modulos_ativos() == {"planejamento"}  # sem configurar nada: liberado
    monkeypatch.setenv("CARTEIRA_MODULOS", "nenhum")
    assert licenca.modulos_ativos() == set()
    monkeypatch.setattr(licenca, "LIBERADO_EM_TESTE", False)
    monkeypatch.delenv("CARTEIRA_MODULOS", raising=False)
    assert licenca.modulos_ativos() == set()  # depois dos testes: só com a licença
