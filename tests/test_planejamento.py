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
    meu = edgar.post("/api/plan/lancamentos", json={"tipo": "despesa", "data": "2026-11-10", "valor": 70}).get_json()["id"]
    assert eli.delete(f"/api/plan/lancamentos/{meu}").status_code == 404  # carteira que ela não edita
    # o administrador gerencia a carteira dela: pode lançar como titular "Eliandra" na visão da família
    eid = [x for x in edgar.get("/api/eu").get_json()["carteiras"] if x["nome"] == "Carteira Eliandra"][0]["id"]
    edgar.environ_base["HTTP_X_CARTEIRA"] = "todas"
    r2 = edgar.post("/api/plan/lancamentos", json={"tipo": "receita", "data": "2026-11-05", "valor": 10, "carteira_id": eid})
    assert r2.status_code == 201
    assert eli.post("/api/plan/lancamentos", json={"tipo": "receita", "data": "2026-11-05", "valor": 10,
                                                   "carteira_id": 1}).status_code == 403  # não edita a do Edgar
    edgar.delete(f"/api/plan/lancamentos/{meu}")
    edgar.delete(f"/api/plan/lancamentos/{r2.get_json()['id']}")
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


def test_receita_do_grupo_familiar(novo_app, com_modulo):
    app = novo_app(fonte)
    edgar = cliente_logado(app)
    edgar.post("/api/usuarios", json={"nome": "Eliandra", "email": "eli@x.com", "senha": "senha-eli-123",
                                      "criar_carteira": True, "nome_carteira": "Carteira Eliandra"})
    mes = dt.date.today().isoformat()[:7]
    edgar.post("/api/plan/lancamentos", json={"tipo": "receita", "data": f"{mes}-05", "valor": 6000})
    edgar.post("/api/plan/lancamentos", json={"tipo": "receita", "data": f"{mes}-05", "valor": 1800, "compartilhado": True})
    f = edgar.get(f"/api/plan/familia?mes={mes}").get_json()
    edg = next(p for p in f["pessoas"] if p["nome"] == "Edgar Machado")
    assert edg["renda"] == 6000 and f["totais"]["receitas_grupo"] == 1800  # não pesa na divisão proporcional
    assert f["totais"]["sobra"] == 7800
    lanc = edgar.get(f"/api/plan/lancamentos?mes={mes}").get_json()
    assert {p["nome"] for p in lanc["pessoas"]} == {"Edgar Machado", "Eliandra"}
    assert all(p["editar"] for p in lanc["pessoas"])  # o administrador lança para os dois


def test_membros_da_familia(novo_app, com_modulo):
    app = novo_app(fonte)
    edgar = cliente_logado(app)
    edgar.post("/api/usuarios", json={"nome": "Eliandra", "email": "eli@x.com", "senha": "senha-eli-123",
                                      "criar_carteira": True, "nome_carteira": "Carteira Eliandra"})
    m = edgar.get("/api/plan/membros").get_json()
    assert not m["configurado"] and {p["nome"] for p in m["membros"]} == {"Edgar Machado", "Eliandra"}
    # filho sem login, que não divide as contas
    r = edgar.post("/api/plan/membros", json={"nome": "Lucas", "parentesco": "filho"})
    lucas = r.get_json()["id"]
    assert r.status_code == 201
    membros = edgar.get("/api/plan/membros").get_json()["membros"]
    edgar.put("/api/plan/membros", json={"membros": [
        {**p, "nome": "Edgar" if p["nome"] == "Edgar Machado" else p["nome"],
         "parentesco": "conjuge" if p["nome"] == "Eliandra" else p["parentesco"]} for p in membros]})
    m = edgar.get("/api/plan/membros").get_json()
    por_nome = {p["nome"]: p for p in m["membros"]}
    assert m["configurado"] and set(por_nome) == {"Edgar", "Eliandra", "Lucas"}
    assert not por_nome["Lucas"]["divide"] and not por_nome["Lucas"]["tem_login"]
    # lança uma receita para o Lucas (mesada / estágio) e uma conta compartilhada paga por ele
    mes = dt.date.today().isoformat()[:7]
    edgar.post("/api/plan/lancamentos", json={"tipo": "receita", "data": f"{mes}-05", "valor": 900, "carteira_id": lucas})
    edgar.post("/api/plan/lancamentos", json={"tipo": "despesa", "data": f"{mes}-06", "valor": 100, "carteira_id": lucas,
                                              "compartilhado": True})
    f = edgar.get(f"/api/plan/familia?mes={mes}").get_json()
    assert {p["nome"] for p in f["pessoas"]} == {"Edgar", "Eliandra"}  # Lucas não entra na divisão
    assert f["fora_da_divisao"][0]["nome"] == "Lucas" and f["fora_da_divisao"][0]["pagou"] == 100
    eli = cliente_logado(app, "eli@x.com", "senha-eli-123")
    assert eli.put("/api/plan/membros", json={"membros": []}).status_code == 403
    assert eli.post("/api/plan/membros", json={"nome": "X"}).status_code == 403


# ------------------------------------------------------------------ conciliação com a fatura
def test_regras_de_conciliacao():
    item = lambda d, desc, v, n=None, t=None: {"data": d, "descricao": desc, "valor": v, "tipo": "compra",  # noqa: E731
                                                "parcela_num": n, "parcela_total": t}
    manuais = [
        {"id": 1, "data": "2026-11-05", "valor": 312.45, "descricao": "Supermercado", "parcela_num": None, "parcela_total": None},
        {"id": 2, "data": "2026-11-06", "valor": 8.0, "descricao": "Café", "parcela_num": None, "parcela_total": None},
        {"id": 3, "data": "2026-11-06", "valor": 8.0, "descricao": "Café", "parcela_num": None, "parcela_total": None},
        {"id": 4, "data": "2026-12-07", "valor": 420.0, "descricao": "Geladeira", "parcela_num": 2, "parcela_total": 10},
        {"id": 5, "data": "2026-11-18", "valor": 52.0, "descricao": "Amazon", "parcela_num": None, "parcela_total": None},
        {"id": 6, "data": "2026-10-01", "valor": 99.0, "descricao": "Antiga", "parcela_num": None, "parcela_total": None},
    ]
    itens = [item("2026-11-07", "BOM PRECO SUPERMERC", 312.45),        # +2 dias: mesma compra
             item("2026-11-06", "CAFETERIA", 8.0), item("2026-11-06", "CAFETERIA", 8.0), item("2026-11-06", "CAFETERIA", 8.0),
             item("2026-11-07", "MAGAZINE PARC 02/10", 419.99, 2, 10),   # parcela com parcela
             item("2026-11-18", "AMAZON US", 54.13),                     # câmbio: possível
             item("2026-11-20", "OUTRA LOJA", 99.0)]                     # mesmo valor, data longe: nova
    fat.conciliar(itens, manuais)
    res = [(i["conciliacao"] or {}).get("tipo") and (i["conciliacao"]["tipo"], i["conciliacao"]["lancamento"]["id"]) for i in itens]
    assert res[0] == ("exato", 1)
    assert sorted(r[1] for r in res[1:4] if r) == [2, 3] and res[1:4].count(None) == 1  # 3 cafés, 2 lançados
    assert res[4] == ("exato", 4) and res[5] == ("possivel", 5) and res[6] is None


def test_api_conciliacao_com_a_fatura(novo_app, com_modulo):
    c = cliente_logado(novo_app(fonte))
    cartao = c.post("/api/plan/cartoes", json={"nome": "Nubank"}).get_json()["id"]
    mercado = cat(c, "despesa", "Mercado")
    # compras lançadas na hora, no crédito
    lid = c.post("/api/plan/lancamentos", json={"tipo": "despesa", "data": "2026-10-06", "descricao": "Pizza de sexta",
                                                "valor": 89.90, "forma": "credito", "cartao_id": cartao,
                                                "categoria_id": cat(c, "despesa", "Restaurante")}).get_json()["id"]
    c.post("/api/plan/lancamentos", json={"tipo": "despesa", "data": "2026-10-05", "descricao": "Magazine", "valor": 4200,
                                          "forma": "credito", "cartao_id": cartao, "repetir": "parcelado", "parcelas": 10,
                                          "categoria_id": cat(c, "despesa", "Compras (lojas e internet)")})
    c.post("/api/plan/lancamentos", json={"tipo": "despesa", "data": "2026-10-11", "descricao": "Loja", "valor": 118.0,
                                          "forma": "credito", "cartao_id": cartao, "categoria_id": mercado})
    # fatura com PARC 03/10 (a 3ª parcela manual é de 05/12, mas parcela casa por número)
    p = c.post("/api/plan/fatura/previa", content_type="multipart/form-data",
               data={"arquivo": (io.BytesIO(OFX.encode()), "fatura.ofx"), "cartao_id": cartao}).get_json()
    por = {i["descricao"][:12]: i for i in p["itens"]}
    assert por["IFOOD *PIZZA"]["conciliacao"]["tipo"] == "exato" and por["IFOOD *PIZZA"]["conciliacao"]["lancamento"]["id"] == lid
    assert por["IFOOD *PIZZA"]["origem_categoria"] == "sua"  # mantém a categoria que você escolheu
    assert por["MAGAZINE LUI"]["conciliacao"]["tipo"] == "exato"
    assert por["LOJA DESCONH"]["conciliacao"]["tipo"] == "possivel"  # 118 x 120
    assert por["POSTO SHELL "]["conciliacao"] is None
    assert p["resumo"]["conciliadas"] == 2 and p["resumo"]["possiveis"] == 1
    # o usuário diz que a "Loja" é outra compra; importa o resto
    itens = []
    for i in p["itens"]:
        if not i["marcado"]:
            continue
        i = {**i}
        if i["conciliacao"]:
            i["lancamento_id"] = i["conciliacao"]["lancamento"]["id"]
            i["acao"] = "nova" if i["descricao"].startswith("LOJA DESCONHECIDA") else "unir"
        itens.append(i)
    r = c.post("/api/plan/fatura/confirmar", json={"cartao_id": cartao, "itens": itens}).get_json()
    assert r["conferidos"] == 2 and r["lancamentos"] == 4 and r["parcelas_futuras"] == 0  # parcelas já existiam
    out = c.get("/api/plan/lancamentos?mes=2026-10").get_json()["lancamentos"]
    pizza = next(l for l in out if l["id"] == lid)
    assert pizza["conferido_em"] and pizza["descricao"] == "Pizza de sexta" and pizza["valor"] == 89.9
    assert sum(1 for l in out if l["valor"] == 89.9) == 1  # não duplicou
    assert {l["valor"] for l in out if l["descricao"] == "Loja" or l["descricao"].startswith("LOJA DESC")} == {118.0, 120.0}
    # reimportar a fatura: as conferidas aparecem como já importadas
    p2 = c.post("/api/plan/fatura/previa", content_type="multipart/form-data",
                data={"arquivo": (io.BytesIO(OFX.encode()), "fatura.ofx"), "cartao_id": cartao}).get_json()
    assert next(i for i in p2["itens"] if i["descricao"].startswith("IFOOD"))["ja_importado"]
    # desfazer a conferência separa de novo
    assert c.post(f"/api/plan/lancamentos/{lid}/desfazer-conferencia").status_code == 200
    p3 = c.post("/api/plan/fatura/previa", content_type="multipart/form-data",
                data={"arquivo": (io.BytesIO(OFX.encode()), "fatura.ofx"), "cartao_id": cartao}).get_json()
    assert next(i for i in p3["itens"] if i["descricao"].startswith("IFOOD"))["conciliacao"]["tipo"] == "exato"


def test_cadastro_de_membros(novo_app, com_modulo):
    c = cliente_logado(novo_app(fonte))
    r = c.post("/api/plan/membros", json={"nome": "Lucas Machado", "parentesco": "filho", "nascimento": "2015-03-10"})
    lid = r.get_json()["id"]
    m = next(p for p in c.get("/api/plan/membros").get_json()["membros"] if p["id"] == lid)
    assert (m["nome"], m["parentesco"], m["divide"], m["tem_login"]) == ("Lucas Machado", "filho", False, False)
    assert m["idade"] >= 10
    assert c.post("/api/plan/membros", json={"nome": "X", "nascimento": "2999-01-01"}).status_code == 400
    assert c.put(f"/api/plan/membros/{lid}", json={"nome": "Lucas", "parentesco": "filho", "divide": True}).status_code == 200
    m = next(p for p in c.get("/api/plan/membros").get_json()["membros"] if p["id"] == lid)
    assert m["nome"] == "Lucas" and m["divide"] and m["nascimento"] is None
    # despesa paga pelo membro
    assert c.post("/api/plan/lancamentos", json={"tipo": "despesa", "data": "2026-11-05", "valor": 50,
                                                 "carteira_id": lid}).status_code == 201
    minha = next(p for p in c.get("/api/plan/membros").get_json()["membros"] if p["minha"])
    assert "login" in c.delete(f"/api/plan/membros/{minha['id']}").get_json()["erro"]  # quem tem login não sai por aqui
    assert c.delete(f"/api/plan/membros/{lid}").status_code == 200
    assert lid not in {p["id"] for p in c.get("/api/plan/membros").get_json()["membros"]}


def test_lancamento_repetido_e_lista_da_familia(novo_app, com_modulo):
    c = cliente_logado(novo_app(fonte))
    filho = c.post("/api/plan/membros", json={"nome": "Edgar Filho", "parentesco": "filho"}).get_json()["id"]
    sal = cat(c, "receita", "Salário")
    corpo = {"tipo": "receita", "data": "2026-11-05", "descricao": "Salario Edgar", "valor": 7200, "categoria_id": sal,
             "carteira_id": filho, "repetir": "mensal"}
    assert c.post("/api/plan/lancamentos", json=corpo).status_code == 201
    r = c.post("/api/plan/lancamentos", json={**corpo, "repetir": "nao"})  # o mesmo salário de novo
    assert r.status_code == 409 and r.get_json()["duplicado"] and "Salario Edgar" in r.get_json()["erro"]
    assert c.post("/api/plan/lancamentos", json={**corpo, "confirmar_duplicado": True}).status_code == 201
    # aparece na lista mesmo com outra carteira escolhida no menu de investimentos
    d = c.get("/api/plan/lancamentos?mes=2026-11").get_json()
    assert sum(1 for l in d["lancamentos"] if l["carteira_id"] == filho) == 2
    assert len([r for r in d["recorrencias"] if r["carteira_id"] == filho]) == 2
    so_filho = c.get(f"/api/plan/lancamentos?mes=2026-11&pessoa={filho}").get_json()["lancamentos"]
    assert {l["carteira_id"] for l in so_filho} == {filho}
    # a repetida, lançada por engano, sai de vez (com o mês já lançado)
    rid = max(r["id"] for r in d["recorrencias"] if r["carteira_id"] == filho)
    assert c.delete(f"/api/plan/recorrencias/{rid}?tudo=1").get_json()["removidos"] == 1
    d = c.get("/api/plan/lancamentos?mes=2026-11").get_json()
    assert sum(1 for l in d["lancamentos"] if l["carteira_id"] == filho) == 1


def test_contas_da_familia_aparecem_para_todos(novo_app, com_modulo):
    app = novo_app(fonte)
    edgar = cliente_logado(app)
    edgar.post("/api/usuarios", json={"nome": "Eliandra", "email": "eli@x.com", "senha": "senha-eli-123",
                                      "criar_carteira": True, "nome_carteira": "Carteira Eliandra"})
    membros = edgar.get("/api/plan/membros").get_json()["membros"]
    ids = {p["nome"]: p["id"] for p in membros}
    for p in membros:
        edgar.put(f"/api/plan/membros/{p['id']}", json={"nome": p["nome"], "parentesco": p["parentesco"], "divide": True})
    eli = cliente_logado(app, "eli@x.com", "senha-eli-123")
    mes = dt.date.today().isoformat()[:7]
    # meio a meio: a conta fixa compartilhada que o Edgar paga aparece no login da Eliandra com a parte dela
    edgar.put("/api/plan/familia", json={"modo": "meio"})
    edgar.post("/api/plan/lancamentos", json={"tipo": "despesa", "data": f"{mes}-05", "descricao": "Aluguel", "valor": 2000,
                                              "repetir": "mensal", "compartilhado": True})
    edgar.post("/api/plan/lancamentos", json={"tipo": "despesa", "data": f"{mes}-06", "descricao": "Barbearia", "valor": 50})
    d = eli.get(f"/api/plan/lancamentos?mes={mes}").get_json()
    alu = next(l for l in d["lancamentos"] if l["descricao"] == "Aluguel")
    assert alu["alheio"] and alu["familia"] and {p["valor"] for p in alu["partes"]} == {1000.0}
    assert not any(l["descricao"] == "Barbearia" for l in d["lancamentos"])  # o que é pessoal continua pessoal
    assert any(r["descricao"] == "Aluguel" and r["alheio"] for r in d["recorrencias"])
    assert eli.put(f"/api/plan/lancamentos/{alu['id']}", json={"valor": 1}).status_code == 404  # só leitura
    f = eli.get(f"/api/plan/familia?mes={mes}").get_json()
    assert {p["nome"] for p in f["pessoas"]} == {"Edgar Machado", "Eliandra"} and f["total"] == 2000
    assert [x["valor"] for x in f["itens"][0]["partes"]] == [1000.0, 1000.0]  # como ficou a divisão de cada conta
    # tudo junto: as compras no cartão do Edgar entram nas despesas do mês da Eliandra, sem precisar marcar
    edgar.put("/api/plan/familia", json={"modo": "junto"})
    cartao = edgar.post("/api/plan/cartoes", json={"nome": "Ourocard"}).get_json()["id"]
    edgar.post("/api/plan/lancamentos", json={"tipo": "despesa", "data": f"{mes}-07", "descricao": "Mercado", "valor": 300,
                                              "forma": "credito", "cartao_id": cartao})
    d = eli.get(f"/api/plan/lancamentos?mes={mes}").get_json()
    merc = next(l for l in d["lancamentos"] if l["descricao"] == "Mercado")
    assert merc["familia"] and "partes" not in merc and d["modo_familia"] == "junto"
    r = eli.get(f"/api/plan/resumo?mes={mes}").get_json()
    assert r["despesas"] >= 2300  # aluguel + fatura do Edgar compõem as despesas do mês dela
    assert ids["Eliandra"] in {p["id"] for p in eli.get(f"/api/plan/lancamentos?mes={mes}").get_json()["pessoas"] if p["minha"]}


def test_trocar_membros_de_lugar(novo_app, com_modulo):
    c = cliente_logado(novo_app(fonte))
    eu = next(p for p in c.get("/api/plan/membros").get_json()["membros"] if p["minha"])
    # o login do Edgar foi cadastrado como "Eliandra", e o Edgar virou um membro sem login
    c.put(f"/api/plan/membros/{eu['id']}", json={"nome": "Eliandra Lopes dos Santos", "parentesco": "conjuge", "divide": True})
    edgar = c.post("/api/plan/membros", json={"nome": "Edgar da Silva Machado", "parentesco": "titular", "divide": True}).get_json()["id"]
    c.post("/api/plan/lancamentos", json={"tipo": "receita", "data": "2026-11-05", "descricao": "Salario Moinho", "valor": 5100})
    c.post("/api/plan/lancamentos", json={"tipo": "receita", "data": "2026-11-05", "descricao": "Salario Edgar", "valor": 7200,
                                          "carteira_id": edgar, "repetir": "mensal"})
    assert c.post(f"/api/plan/membros/{eu['id']}/trocar", json={"com": edgar}).get_json()["ok"]
    m = {p["id"]: p for p in c.get("/api/plan/membros").get_json()["membros"]}
    assert (m[eu["id"]]["nome"], m[eu["id"]]["parentesco"]) == ("Edgar da Silva Machado", "titular")
    assert (m[edgar]["nome"], m[edgar]["parentesco"]) == ("Eliandra Lopes dos Santos", "conjuge")
    d = c.get("/api/plan/lancamentos?mes=2026-11").get_json()
    dono = {l["descricao"]: l["carteira_id"] for l in d["lancamentos"]}
    assert dono == {"Salario Edgar": eu["id"], "Salario Moinho": edgar}
    assert {r["descricao"]: r["carteira_id"] for r in d["recorrencias"]} == {"Salario Edgar": eu["id"]}


def test_fatura_pdf_layout_nubank(novo_app, com_modulo):
    from carteira import fatura as fat
    itens = fat.ler_fatura(ler_fixture("fatura_nubank_exemplo.pdf"), "Nubank_2026-11-10.pdf")
    por = {i["descricao"]: i for i in itens}
    assert len(itens) == 6 and por["Supermercados"]["data"] == "2026-10-05" and por["Supermercados"]["valor"] == 512.3
    assert por["Pagamento em 08 OUT"]["tipo"] == "pagamento"
    assert por["Desconto Antecipação Loja Exemplo"]["tipo"] == "estorno"
    ant = por["Antecipada - Loja Exemplo - Parcela 4/10"]
    assert ant["antecipada"] and (ant["parcela_num"], ant["parcela_total"]) == (4, 10)
    assert ant["base"] == por["Loja Exemplo - Parcela 3/10"]["base"]  # mesma compra parcelada
    assert por["Farmacia Bem Estar"]["portador"] == "Beltrana de Tal" and por["Farmacia Bem Estar"]["final"] == "9876"
    # importando: a parcela 3/10 gera as futuras e a 4/10 antecipada fica neste mês, sem duplicar
    c = cliente_logado(novo_app(fonte))
    cartao = c.post("/api/plan/cartoes", json={"nome": "Nubank"}).get_json()["id"]
    r = c.post("/api/plan/fatura/previa", data={"cartao_id": cartao, "arquivo": (io.BytesIO(
        ler_fixture("fatura_nubank_exemplo.pdf")), "Nubank.pdf")}, content_type="multipart/form-data").get_json()
    sel = [i for i in r["itens"] if i["marcado"]]
    ok = c.post("/api/plan/fatura/confirmar", json={"cartao_id": cartao, "itens": sel, "parcelas_futuras": True}).get_json()
    assert ok["antecipadas"] == 1
    loja = []
    for m in ("2026-10", "2026-11", "2026-12"):
        loja += [l for l in c.get(f"/api/plan/lancamentos?mes={m}").get_json()["lancamentos"] if "Loja Exemplo" in l["descricao"]
                 and l["tipo"] == "despesa"]
    assert sorted((l["data"][:7], l["parcela_num"]) for l in loja) == [("2026-10", 3), ("2026-10", 4), ("2026-12", 5)]  # a 4ª saiu de novembro


def test_fatura_pdf_bb_com_secoes():
    from carteira import fatura as fat
    itens = fat.ler_fatura(ler_fixture("fatura_bb_secoes.pdf"), "fatura_bb.pdf")
    por = {i["descricao"]: i for i in itens}
    assert set(por) == {"PGTO DEBITO CONTA 1234 000012345 200", "CANTINA DO BAIRRO LTD",
                        "EMPORIO CENTRAL", "LAVANDERIA AZUL", "LOJA DE MOVEIS PARC 02/05"}
    assert por["PGTO DEBITO CONTA 1234 000012345 200"]["tipo"] == "pagamento"
    assert por["CANTINA DO BAIRRO LTD"]["categoria_banco"] == "Restaurante"
    assert por["LAVANDERIA AZUL"]["categoria_banco"] is None  # "Serviços" é genérico demais
    assert por["CANTINA DO BAIRRO LTD"]["data"] == "2026-10-05"
    assert (por["LOJA DE MOVEIS PARC 02/05"]["parcela_num"], por["LOJA DE MOVEIS PARC 02/05"]["parcela_total"]) == (2, 5)
    assert {i["portador"] for i in itens} == {"Fulano de Tal"} and {i["final"] for i in itens} == {"1234"}
    compras = sum(i["valor"] for i in itens if i["tipo"] == "compra")
    assert round(compras, 2) == 241.40  # confere com o total da fatura
    cats = {("despesa", "Restaurante"): 7, ("despesa", "Mercado"): 8}
    assert fat.sugerir_categoria(por["CANTINA DO BAIRRO LTD"], [], cats) == (7, "banco")
    # a cidade sai mesmo colada no nome (o BB corta o nome na largura da coluna)
    assert fat.sem_cidade(["DIARIO CONVENIENCIAS LTSANTA MARIA", "LEONES MINIMERCADO LTD SANTA MARIA", "ART LANCHES SANTA MARIA",
                           "NONO LUDOVICO PORTO ALEGRE"]) == ["DIARIO CONVENIENCIAS LT", "LEONES MINIMERCADO LTD", "ART LANCHES",
                                                              "NONO LUDOVICO PORTO ALEGRE"]
    assert fat.sem_cidade(["ART LANCHES SANTA MARIA", "ART LANCHES SANTA MARIA"]) == ["ART LANCHES SANTA MARIA"] * 2
    assert fat.mesmo_texto("DIARIO CONVENIENCIAS LTSANTA MARIA BR", "DIARIO CONVENIENCIAS LT")


def test_fatura_pdf_layout_sicredi():
    from carteira import fatura as fat
    itens = fat.ler_fatura(ler_fixture("fatura_sicredi_exemplo.pdf"), "Fatura_2026-11_Sicredi.pdf")
    por = {i["descricao"]: i for i in itens}
    assert set(por) == {"Padaria Pao Quente", "Loja Virtual Exemplo 02/05", "Servico Nuvem", "Mercado Bom Dia"}
    assert por["Padaria Pao Quente"]["data"] == "2026-10-03" and por["Servico Nuvem"]["valor"] == 56.0  # valor em reais
    assert (por["Loja Virtual Exemplo 02/05"]["parcela_num"], por["Loja Virtual Exemplo 02/05"]["parcela_total"]) == (2, 5)
    assert {i["portador"] for i in itens} == {"Fulano Tal"} and {i["final"] for i in itens} == {"4321"}
    assert round(sum(i["valor"] for i in itens), 2) == 365.40


def test_corrige_descricoes_antigas_do_bb_e_nao_duplica(novo_app, com_modulo):
    app = novo_app(fonte)
    c = cliente_logado(app)
    cartao = c.post("/api/plan/cartoes", json={"nome": "Ourocard"}).get_json()["id"]
    conn = app.config["conn"]
    cid = conn.execute("SELECT carteira_id FROM fin_cartoes WHERE id = ?", (cartao,)).fetchone()[0]
    antigas = [("2026-10-05", "CANTINA DO BAIRRO LTDSANTA MARIA BR", 45.90), ("2026-10-07", "EMPORIO CENTRAL SANTA MARIA BR", 120.50),
               ("2026-10-08", "LAVANDERIA AZUL SANTA MARIA BR", 35.00)]
    for i, (d, desc, v) in enumerate(antigas):  # como a versão anterior do leitor gravava
        conn.execute("""INSERT INTO fin_lancamentos (carteira_id, tipo, data, descricao, valor, forma, pago, cartao_id, chave_import)
                        VALUES (?, 'despesa', ?, ?, ?, 'credito', 1, ?, ?)""", (cid, d, desc, v, cartao, f"f:antiga{i}"))
    conn.execute("DELETE FROM fin_config WHERE chave = 'descricoes_bb_v1'")
    conn.commit()
    plan.preparar(conn)
    descs = {r[0] for r in conn.execute("SELECT descricao FROM fin_lancamentos WHERE cartao_id = ?", (cartao,))}
    assert descs == {"CANTINA DO BAIRRO LTD", "EMPORIO CENTRAL", "LAVANDERIA AZUL"}
    # importar a mesma fatura de novo não duplica o que já entrou com o nome antigo
    r = c.post("/api/plan/fatura/previa", data={"cartao_id": cartao, "arquivo": (io.BytesIO(
        ler_fixture("fatura_bb_secoes.pdf")), "fatura_bb.pdf")}, content_type="multipart/form-data").get_json()
    por = {i["descricao"]: i for i in r["itens"]}
    assert all(por[d]["ja_importado"] for d in ("CANTINA DO BAIRRO LTD", "EMPORIO CENTRAL", "LAVANDERIA AZUL"))
    assert not por["LOJA DE MOVEIS PARC 02/05"]["ja_importado"]


def test_ciclo_da_fatura():
    # Nubank: fecha dia 3 e vence dia 10; BB: fecha dia 28 e vence dia 5 do mês seguinte
    assert plan.fatura_da_compra("2026-10-03", 3, 10) == "2026-10" and plan.fatura_da_compra("2026-10-04", 3, 10) == "2026-11"
    assert plan.fatura_da_compra("2026-10-28", 28, 5) == "2026-11" and plan.fatura_da_compra("2026-10-29", 28, 5) == "2026-12"
    assert plan.datas_da_fatura("2026-11", 28, 5) == ("2026-10-28", "2026-11-05")
    assert plan.dias_do_cartao(None, 10) == (3, 10)  # sem o fechamento: 7 dias antes do vencimento
    assert plan.fatura_da_compra("2026-10-20", None, None) == "2026-10"
    assert [plan.situacao_fatura("2026-11", 3, 10, h) for h in ("2026-11-02", "2026-11-05", "2026-11-12")] == \
        ["aberta", "fechada", "encerrada"]


def test_pagina_do_cartao_e_avisos(novo_app, com_modulo):
    c = cliente_logado(novo_app(fonte))
    hoje = dt.date.today()
    venc = (hoje + dt.timedelta(days=3)).day
    fecha = (hoje - dt.timedelta(days=4)).day
    cartao = c.post("/api/plan/cartoes", json={"nome": "Nubank", "dia_vencimento": venc, "dia_fechamento": fecha,
                                               "limite": "1.000,00", "final": "•••• 1234"}).get_json()["id"]
    antes = (hoje - dt.timedelta(days=10)).isoformat()   # entra na fatura que já fechou e vence em 3 dias
    depois = (hoje - dt.timedelta(days=1)).isoformat()   # entra na fatura aberta
    c.post("/api/plan/lancamentos", json={"tipo": "despesa", "data": antes, "descricao": "Mercado", "valor": 600,
                                          "forma": "credito", "cartao_id": cartao})
    c.post("/api/plan/lancamentos", json={"tipo": "despesa", "data": depois, "descricao": "TV", "valor": 900,
                                          "forma": "credito", "cartao_id": cartao, "repetir": "parcelado", "parcelas": 3})
    d = c.get(f"/api/plan/cartoes/{cartao}/faturas").get_json()
    assert d["cartao"]["final"] == "1234" and d["cartao"]["limite"] == 1000
    sit = {f["situacao"]: f for f in d["faturas"]}
    assert sit["fechada"]["total"] == 600 and sit["aberta"]["total"] == 300 and d["resumo"]["futuras"] == 600
    assert d["resumo"]["usado"] == 1500 and d["resumo"]["disponivel"] == -500
    codigos = {a["codigo"] for a in d["alertas"]}
    assert {"vencimento", "limite"} <= codigos
    # os avisos dos cartões também vão para o sino
    titulos = " ".join(a["titulo"] for a in c.get("/api/alertas").get_json()["itens"])
    assert "Fatura do Nubank vence" in titulos and "limite" in titulos
    assert c.put(f"/api/plan/cartoes/{cartao}", json={"nome": "Nubank Ultravioleta", "dia_vencimento": 15,
                                                      "dia_fechamento": 8, "limite": 5000}).status_code == 200
    assert c.get(f"/api/plan/cartoes/{cartao}/faturas").get_json()["cartao"]["nome"] == "Nubank Ultravioleta"
