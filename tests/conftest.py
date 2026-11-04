import pytest

from app import create_app


def cliente_logado(app, email="edgar@exemplo.com", senha="senha-edgar-123", nome="Edgar Machado"):
    """Cliente de teste com sessão iniciada e cabeçalhos da aplicação."""
    c = app.test_client()
    c.environ_base["HTTP_X_REQUESTED_WITH"] = "fetch"
    conn = app.config["conn"]
    if conn.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] == 0:
        r = c.post("/auth/setup", json={"nome": nome, "email": email, "senha": senha,
                                        "nome_carteira": f"Carteira {nome}"})
        assert r.status_code == 201, r.get_json()
    else:
        r = c.post("/auth/login", json={"email": email, "senha": senha})
        assert r.status_code == 200, r.get_json()
    eu = c.get("/api/eu").get_json()
    if eu["carteiras"]:
        c.environ_base["HTTP_X_CARTEIRA"] = str(eu["carteiras"][0]["id"])
    return c


@pytest.fixture
def novo_app(tmp_path):
    def fabrica(fonte):
        return create_app(str(tmp_path / "t.db"), fonte, secret_key="teste")
    return fabrica
