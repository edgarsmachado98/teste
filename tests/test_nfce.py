import io
import os

import pytest

from carteira import nfce
from carteira.market import serie_simulada
from tests.conftest import cliente_logado

CHAVE = "53261112345678000195650010000123451000012344"
URL = f"https://www.fazenda.df.gov.br/nfce/qrcode?p={CHAVE}|2|1|1|ABCDEF0123456789"


def fonte(t):
    return serie_simulada(t, dias=300)


def pagina():
    return open(os.path.join(os.path.dirname(__file__), "fixtures", "nfce_padrao.html"), encoding="utf-8").read()


@pytest.fixture
def com_modulo(monkeypatch):
    monkeypatch.delenv("CARTEIRA_DEMO", raising=False)
    monkeypatch.setenv("CARTEIRA_MODULOS", "planejamento")


def test_chave_e_qrcode():
    assert nfce.chave_valida(CHAVE)
    assert not nfce.chave_valida(CHAVE[:-1] + "9")
    d = nfce.ler_qrcode(URL)
    assert (d["uf"], d["ano_mes"], d["cnpj"], d["numero"], d["serie"]) == ("DF", "2026-11", "12345678000195", 12345, 1)
    assert "total" not in d  # on-line: o valor só vem do portal
    off = nfce.ler_qrcode(f"https://www.fazenda.df.gov.br/nfce/qrcode?p={CHAVE}|2|1|03|105.00|6a6b|1|HASH")
    assert (off["dia"], off["total"]) == (3, 105.0)
    assert nfce.ler_qrcode(" ".join(CHAVE[i:i + 4] for i in range(0, 44, 4)))["chave"] == CHAVE  # chave digitada
    with pytest.raises(nfce.ErroNota):
        nfce.ler_qrcode("https://exemplo.com/qualquer")
    nfe = CHAVE[:20] + "55" + CHAVE[22:43]
    with pytest.raises(nfce.ErroNota, match="NF-e"):
        nfce.ler_qrcode(nfe + nfce._dv(nfe))


def test_pagina_padrao_com_troco_e_duas_formas():
    n = nfce.ajustar_pagamentos(nfce.ler_pagina(pagina()))
    assert n["emitente"] == "SUPERMERCADO BOM PRECO LTDA" and n["cnpj"] == "12345678000195"
    assert n["data"] == "2026-11-03T18:42" and n["total"] == 105.0 and n["desconto"] == 2.27
    assert [i["descricao"] for i in n["itens"]][:2] == ["ARROZ TIPO 1 5KG", "LEITE INTEGRAL 1L"]
    assert n["itens"][2]["qtd"] == 1.235 and n["itens"][2]["un"] == "KG"
    # 80 no crédito + 30 em dinheiro com 5 de troco = 105
    assert [(p["forma"], p["valor"]) for p in n["pagamentos"]] == [("credito", 80.0), ("dinheiro", 25.0)]


def test_formas_e_nome_da_loja():
    assert nfce.forma_pagamento("Pagamento Instantâneo (PIX)") == "pix"
    assert nfce.forma_pagamento("Cartão de Débito") == "debito"
    assert nfce.forma_pagamento("Vale Refeição") is None
    assert nfce.nome_loja("AUTO POSTO DO EIXO LTDA - EPP") == "Auto Posto do Eixo"


def test_portal_fora_do_ar_e_seguranca():
    def caiu(url):
        raise OSError("timeout")
    n = nfce.consultar(URL, caiu)
    assert n["fonte"] == "qrcode" and "não respondeu" in n["aviso"] and n["total"] is None
    vistos = []
    nfce.consultar(f"http://192.168.0.1/nfce?p={CHAVE}|2|1|1|X", lambda u: vistos.append(u) or "")
    assert vistos == []  # só acessa portais *.gov.br
    # alguns portais (RS) mostram a nota num quadro interno
    paginas = {URL: '<html><iframe src="https://dfe-portal.svrs.rs.gov.br/Dfe/QrCodeNFce?p=1"></iframe></html>',
               "https://dfe-portal.svrs.rs.gov.br/Dfe/QrCodeNFce?p=1": pagina()}
    assert nfce.consultar(URL, paginas.__getitem__)["total"] == 105.0


def test_posto_vira_combustivel():
    html = pagina().replace("SUPERMERCADO BOM PRECO LTDA", "AUTO POSTO EIXAO LTDA").replace(
        "ARROZ TIPO 1 5KG", "GASOLINA COMUM").replace("<strong>UN: </strong>UN</span>\n     <span class=\"RvlUnit\"><strong>Vl. Unit.:</strong>&nbsp;27,90",
                                                      "<strong>UN: </strong>LT</span>\n     <span class=\"RvlUnit\"><strong>Vl. Unit.:</strong>&nbsp;27,90")
    n = nfce.consultar(URL, lambda u: html)
    assert nfce.resumo_combustivel(n)["produto"] == "GASOLINA COMUM"


def test_foto_do_qrcode():
    qrcode = pytest.importorskip("qrcode")
    pytest.importorskip("zxingcpp")
    from PIL import Image
    qr = qrcode.make(URL).convert("RGB").resize((300, 300))
    foto = Image.new("RGB", (1600, 2400), (235, 232, 225))  # cupom fotografado de longe
    foto.paste(qr, (650, 1900))
    buf = io.BytesIO()
    foto.save(buf, "JPEG", quality=85)
    assert nfce.ler_qrcode_da_foto(buf.getvalue()) == URL
    with pytest.raises(nfce.ErroNota):
        nfce.ler_qrcode_da_foto(b"nao e imagem")


def test_api_nota_fiscal(novo_app, com_modulo):
    app = novo_app(fonte)
    app.config["nfce_abrir"] = lambda url: pagina()
    c = cliente_logado(app)
    cats = c.get("/api/plan/categorias").get_json()["categorias"]
    mercado = next(x["id"] for x in cats if x["nome"] == "Mercado")
    r = c.post("/api/plan/nfce/ler", json={"textos": [URL, URL, "lixo"]}).get_json()
    assert len(r["notas"]) == 1 and len(r["falhas"]) == 1  # a mesma nota duas vezes conta uma
    n = r["notas"][0]
    assert n["fonte"] == "portal" and n["descricao"] == "Supermercado Bom Preco" and n["total"] == 105.0
    assert n["categoria_id"] == mercado and not n["ja_lancada"]
    cartao = c.post("/api/plan/cartoes", json={"nome": "Ourocard"}).get_json()["id"]
    corpo = {k: n[k] for k in ("chave", "url", "emitente", "cnpj", "total", "itens", "descricao")}
    corpo.update(emissao=n["data"], data=n["data"][:10], categoria_id=mercado,
                 pagamentos=[{"forma": "credito", "valor": 80}, {"forma": "dinheiro", "valor": 25}])
    assert "cartão" in c.post("/api/plan/nfce/confirmar", json=corpo).get_json()["erro"]
    corpo["pagamentos"][0]["cartao_id"] = cartao
    ok = c.post("/api/plan/nfce/confirmar", json=corpo)
    assert ok.status_code == 201 and len(ok.get_json()["ids"]) == 2 and ok.get_json()["aguardando_fatura"] == 1
    assert c.post("/api/plan/nfce/confirmar", json=corpo).status_code == 409  # não lança duas vezes
    lancs = c.get("/api/plan/lancamentos?mes=2026-11").get_json()["lancamentos"]
    da_nota = [l for l in lancs if l.get("nota_id")]
    assert sorted((l["forma"], l["valor"]) for l in da_nota) == [("credito", 80.0), ("dinheiro", 25.0)]
    credito = next(l for l in da_nota if l["forma"] == "credito")
    assert credito["cartao_id"] == cartao and credito["chave_import"] is None  # aguarda a fatura para conferir
    nota = c.get(f"/api/plan/notas/{credito['nota_id']}").get_json()
    assert len(nota["itens"]) == 4 and nota["cnpj_formatado"] == "12.345.678/0001-95"
    assert c.post("/api/plan/nfce/ler", json={"textos": [URL]}).get_json()["notas"][0]["ja_lancada"]
    # excluindo os lançamentos, a nota pode ser lida de novo
    for l in da_nota:
        c.delete(f"/api/plan/lancamentos/{l['id']}")
    assert not c.post("/api/plan/nfce/ler", json={"textos": [URL]}).get_json()["notas"][0]["ja_lancada"]


def test_valor_digitado_com_ponto_de_milhar(novo_app, com_modulo):
    c = cliente_logado(novo_app(fonte))
    for digitado, esperado in (("7.200", 7200.0), ("7.200,50", 7200.5), ("7,5", 7.5), ("R$ 1.234.567,89", 1234567.89),
                               ("7.5", 7.5), (7200, 7200.0)):
        lid = c.post("/api/plan/lancamentos", json={"tipo": "receita", "data": "2026-11-12", "descricao": "Salário",
                                                    "valor": digitado}).get_json()["id"]
        l = next(x for x in c.get("/api/plan/lancamentos?mes=2026-11").get_json()["lancamentos"] if x["id"] == lid)
        assert l["valor"] == esperado, digitado
