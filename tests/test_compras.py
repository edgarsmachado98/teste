import os

import pytest

from carteira import compras as cmp
from carteira import nfce
from carteira.market import serie_simulada
from tests.conftest import cliente_logado

CHAVE_A = "53261112345678000195650010000123451000012344"


def chave(numero):
    base = CHAVE_A[:25] + f"{numero:09d}" + CHAVE_A[34:43]
    return base + nfce._dv(base)


def url(ch):
    return f"https://www.fazenda.df.gov.br/nfce/qrcode?p={ch}|2|1|1|ABCDEF"


def fonte(t):
    return serie_simulada(t, dias=300)


def pagina_a():
    return open(os.path.join(os.path.dirname(__file__), "fixtures", "nfce_padrao.html"), encoding="utf-8").read()


def pagina_b():
    """Outro mercado: arroz e café mais baratos, leite mais caro."""
    return (pagina_a().replace("SUPERMERCADO BOM PRECO LTDA", "ATACADO ECONOMIA LTDA").replace("12.345.678/0001-95", "98.765.432/0001-10")
            .replace("&nbsp;27,90", "&nbsp;24,50").replace(">27,90<", ">24,50<").replace("&nbsp;5,49", "&nbsp;5,99")
            .replace(">32,94<", ">35,94<").replace("&nbsp;18,90", "&nbsp;16,90").replace(">37,80<", ">33,80<")
            .replace("ARROZ TIPO 1 5KG", "Arroz Tipo 1 5 kg").replace("03/11/2026 18:42:10", "10/11/2026 10:05:00"))


@pytest.fixture
def com_compras(monkeypatch):
    monkeypatch.delenv("CARTEIRA_DEMO", raising=False)
    monkeypatch.setenv("CARTEIRA_MODULOS", "planejamento,compras")


def test_nomes_dos_produtos():
    assert cmp.chave_produto("Leite Integral ITALAC 1 LT") == cmp.chave_produto("LEITE INTEGRAL ITALAC 1L")
    assert cmp.chave_produto("Arroz Tipo 1 5 kg") == cmp.chave_produto("ARROZ TIPO 1 5KG")
    assert cmp.chave_produto("Café Torrado 500 GR") == "CAFE TORRADO 500G"
    assert cmp.chave_produto("Refri 2,0L") == "REFRI 2L"
    assert cmp.nome_loja("ATACADO ECONOMIA LTDA - EPP") == "Atacado Economia"


def test_lista_pelo_menor_preco():
    precos = {1: {10: {"unitario": 27.9, "data": "2026-11-03", "loja": "A", "loja_id": 10},
                  20: {"unitario": 24.5, "data": "2026-11-10", "loja": "B", "loja_id": 20}},
              2: {10: {"unitario": 5.49, "data": "2026-11-03", "loja": "A", "loja_id": 10},
                  20: {"unitario": 5.99, "data": "2026-11-10", "loja": "B", "loja_id": 20}}}
    r = cmp.montar_lista([{"id": 1, "produto_id": 1, "nome": "Arroz", "qtd": 1}, {"id": 2, "produto_id": 2, "nome": "Leite", "qtd": 6},
                          {"id": 3, "produto_id": None, "nome": "Papel toalha", "qtd": 1}], precos, {10: "A", 20: "B"}, "2026-11-20")
    assert r["melhor"]["total"] == round(24.5 + 6 * 5.49, 2)
    assert {g["loja"]: g["itens"] for g in r["melhor"]["lojas"]} == {"B": ["Arroz"], "A": ["Leite"]}
    assert r["um_mercado"]["loja"] == "B" and r["um_mercado"]["total"] == round(24.5 + 6 * 5.99, 2)  # empate em itens: o mais barato
    assert r["economia"] == round(r["um_mercado"]["total"] - r["melhor"]["total"], 2)
    assert r["itens"][0]["economia"] == 3.4


def test_api_compras_ponta_a_ponta(novo_app, com_compras):
    app = novo_app(fonte)
    paginas = {url(CHAVE_A): pagina_a(), url(chave(777)): pagina_b()}
    app.config["nfce_abrir"] = paginas.__getitem__
    c = cliente_logado(app)
    lida = c.post("/api/compras/ler", json={"textos": [url(CHAVE_A)]}).get_json()
    assert lida["planejamento"] and lida["notas"][0]["loja_nome"] == "Supermercado Bom Preco"
    n = lida["notas"][0]
    assert c.post("/api/compras/registrar", json=n).status_code == 201
    assert c.post("/api/compras/registrar", json=n).get_json()["nova"] is False  # não duplica
    # a segunda nota já mostra onde cada item saiu mais barato antes
    n2 = c.post("/api/compras/ler", json={"textos": [url(chave(777))]}).get_json()["notas"][0]
    leite = next(i for i in n2["itens"] if i["descricao"].startswith("LEITE"))
    assert leite["mais_barato"]["unitario"] == 5.49 and leite["mais_barato"]["loja"] == "Supermercado Bom Preco"
    c.post("/api/compras/registrar", json=n2)

    prods = {p["nome"]: p for p in c.get("/api/compras/produtos").get_json()["produtos"]}
    arroz = prods["Arroz Tipo 1 5KG"]
    assert arroz["compras"] == 2 and arroz["menor"]["unitario"] == 24.5 and arroz["menor"]["loja"] == "Atacado Economia"
    det = c.get(f"/api/compras/produtos/{arroz['id']}").get_json()
    assert len(det["historico"]) == 2 and set(det["nomes_nas_notas"]) == {"ARROZ TIPO 1 5KG", "Arroz Tipo 1 5 kg"}

    r = c.get("/api/compras/resumo?dias=30").get_json()
    assert r["compras"] == 2 and r["gasto"] == 210.0 and {l["nome"] for l in r["lojas"]} == {"Supermercado Bom Preco", "Atacado Economia"}
    assert sum(l["mais_barato_em"] for l in r["lojas"]) == 4

    # lista de compras
    assert c.post("/api/compras/lista", json={"produto_id": arroz["id"], "qtd": 2}).status_code == 201
    c.post("/api/compras/lista", json={"texto": "leite integral 1l", "qtd": 6})  # reconhece o produto pelo nome
    c.post("/api/compras/lista", json={"texto": "Papel toalha"})
    lista = c.get("/api/compras/lista").get_json()
    assert lista["com_preco"] == 2 and lista["pendentes"] == 3
    assert {g["loja"] for g in lista["melhor"]["lojas"]} == {"Atacado Economia", "Supermercado Bom Preco"}
    assert lista["melhor"]["total"] == round(2 * 24.5 + 6 * 5.49, 2)
    assert c.post("/api/compras/lista", json={"produto_id": arroz["id"], "qtd": 1}).get_json()["somado"]
    item = next(i for i in lista["itens"] if i["nome"] == "Papel toalha")
    c.put(f"/api/compras/lista/{item['id']}", json={"comprado": True})
    assert c.delete("/api/compras/lista").get_json()["removidos"] == 1
    assert c.get("/api/compras/buscar?q=caf").get_json()[0]["nome"] == "Cafe Torrado 500G"

    # juntar dois produtos que o sistema não reconheceu como iguais
    banana = prods["Banana Prata KG"]["id"]
    cafe = prods["Cafe Torrado 500G"]["id"]
    assert c.post(f"/api/compras/produtos/{cafe}/juntar", json={"com": banana}).get_json()["ok"]
    assert "Banana Prata KG" not in {p["nome"] for p in c.get("/api/compras/produtos").get_json()["produtos"]}


def test_nota_do_planejamento_entra_nas_compras(novo_app, com_compras):
    app = novo_app(fonte)
    app.config["nfce_abrir"] = lambda u: pagina_a()
    c = cliente_logado(app)
    n = c.post("/api/plan/nfce/ler", json={"textos": [url(CHAVE_A)]}).get_json()["notas"][0]
    corpo = {k: n[k] for k in ("chave", "url", "emitente", "cnpj", "total", "itens", "descricao")}
    corpo.update(emissao=n["data"], data=n["data"][:10], pagamentos=[{"forma": "pix", "valor": 105}])
    assert c.post("/api/plan/nfce/confirmar", json=corpo).status_code == 201
    r = c.get("/api/compras/resumo?dias=3650").get_json()
    assert r["compras"] == 1 and r["ultimas"][0]["loja"] == "Supermercado Bom Preco"


def test_modulo_compras_bloqueado(novo_app, monkeypatch):
    monkeypatch.delenv("CARTEIRA_DEMO", raising=False)
    monkeypatch.setenv("CARTEIRA_MODULOS", "planejamento")
    c = cliente_logado(novo_app(fonte))
    assert c.get("/api/compras/lista").status_code == 403
    assert b"tab-cmp-lista" not in c.get("/").data
