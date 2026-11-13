import pytest

from app import create_app, num, brl


@pytest.fixture
def client(tmp_path):
    app = create_app(str(tmp_path))
    app.config["TESTING"] = True
    return app.test_client()


def test_num_e_brl():
    assert num("1.234,56") == 1234.56
    assert num("12.5") == 12.5
    assert num("") == 0
    assert brl(1234.5) == "R$ 1.234,50"


def test_paginas_abrem(client):
    for rota in ["/orcamentos", "/orcamentos/novo", "/catalogo", "/clientes", "/empresa"]:
        assert client.get(rota).status_code == 200


def test_fluxo_orcamento(client):
    # tipo 2 = Câmeras (CFTV); cria com cliente novo
    r = client.post("/orcamentos/novo", data={"tipos": ["2"], "novo_cliente": "Loja Teste"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/orcamentos/1")
    pagina = client.get("/orcamentos/1").get_data(as_text=True)
    assert "Câmera IP dome" in pagina and "Gravação e armazenamento" in pagina

    # item 1 = Câmera IP dome: 4 un, custo 200, preço 300; desconto 100
    r = client.post("/orcamentos/1", data={
        "titulo": "CFTV Loja", "cliente_id": "1", "status": "Enviado", "desconto": "100,00",
        "validade_dias": "10", "exibicao": "itens",
        "i1_desc": "Câmera IP dome", "i1_qtd": "4", "i1_custo": "200,00", "i1_preco": "300,00"})
    assert r.status_code == 302

    proposta = client.get("/orcamentos/1/proposta").get_data(as_text=True)
    assert "Loja Teste" in proposta
    assert "TOTAL — CÂMERAS" in proposta and "R$ 1.200,00" in proposta
    assert "TOTAL GERAL DA PROPOSTA" in proposta and "R$ 1.100,00" in proposta
    assert "Câmera IP bullet" not in proposta  # quantidade zero não aparece

    cotacao = client.get("/orcamentos/1/cotacao").get_data(as_text=True)
    assert "Câmera IP dome" in cotacao
    assert "Loja Teste" not in cotacao and "300,00" not in cotacao and "200,00" not in cotacao

    lista = client.get("/orcamentos?status=Enviado").get_data(as_text=True)
    assert "CFTV Loja" in lista and "R$ 1.100,00" in lista


def test_combina_tipos_e_item_avulso(client):
    client.post("/orcamentos/novo", data={"tipos": ["1", "3"], "novo_cliente": "X"})
    pagina = client.get("/orcamentos/1").get_data(as_text=True)
    assert "Infraestrutura de rede · Cabeamento" in pagina and "Alarme · Sensores" in pagina
    client.post("/orcamentos/1/itens", data={
        "secao_id": "1", "descricao": "Visita técnica", "tipo": "servico",
        "quantidade": "1", "preco": "150"})
    assert "Visita técnica" in client.get("/orcamentos/1/proposta").get_data(as_text=True)
    # serviço não entra na lista de cotação
    assert "Visita técnica" not in client.get("/orcamentos/1/cotacao").get_data(as_text=True)


def test_novo_exige_tipo(client):
    r = client.post("/orcamentos/novo", data={"novo_cliente": "X"})
    assert "Escolha pelo menos um tipo" in r.get_data(as_text=True)
