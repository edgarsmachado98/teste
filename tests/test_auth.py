import sqlite3

from carteira import db
from carteira.market import serie_simulada
from tests.conftest import cliente_logado


def fonte(t):
    return serie_simulada(t, dias=300)


def preparar(novo_app):
    """Edgar (admin) + Eliandra com carteira própria."""
    app = novo_app(fonte)
    edgar = cliente_logado(app)
    r = edgar.post("/api/usuarios", json={"nome": "Eliandra", "email": "eliandra@exemplo.com",
                                          "senha": "senha-eli-123", "criar_carteira": True,
                                          "nome_carteira": "Carteira Eliandra"})
    assert r.status_code == 201
    eliandra = cliente_logado(app, "eliandra@exemplo.com", "senha-eli-123")
    ids = {c["nome"]: c["id"] for c in edgar.get("/api/eu").get_json()["carteiras"]}
    return app, edgar, eliandra, ids["Carteira Edgar Machado"], ids["Carteira Eliandra"]


def com_carteira(cliente, cid):
    cliente.environ_base["HTTP_X_CARTEIRA"] = str(cid)
    return cliente


APORTE = {"data": "2025-01-10", "ticker": "ITUB4", "quantidade": 10, "preco": 30}


def test_sem_login(novo_app):
    c = novo_app(fonte).test_client()
    assert c.get("/").status_code == 302
    assert c.get("/login").status_code == 200
    assert c.get("/api/carteira", headers={"X-Carteira": "1"}).status_code == 401


def test_csrf_exige_cabecalho(novo_app):
    app = novo_app(fonte)
    cliente_logado(app)
    c = app.test_client()
    assert c.post("/auth/login", json={"email": "edgar@exemplo.com", "senha": "senha-edgar-123"}).status_code == 403


def test_setup_unico_e_login(novo_app):
    app = novo_app(fonte)
    c = cliente_logado(app)
    assert c.post("/auth/setup", json={"nome": "X", "email": "x@x.com", "senha": "12345678"}).status_code == 409
    anon = app.test_client()
    anon.environ_base["HTTP_X_REQUESTED_WITH"] = "fetch"
    assert anon.post("/auth/login", json={"email": "edgar@exemplo.com", "senha": "errada"}).status_code == 401
    for _ in range(5):
        anon.post("/auth/login", json={"email": "edgar@exemplo.com", "senha": "errada"})
    assert anon.post("/auth/login", json={"email": "edgar@exemplo.com", "senha": "senha-edgar-123"}).status_code == 429


def test_isolamento_entre_carteiras(novo_app):
    _, edgar, eliandra, c_edgar, c_eli = preparar(novo_app)
    assert [c["nome"] for c in eliandra.get("/api/eu").get_json()["carteiras"]] == ["Carteira Eliandra"]
    # Eliandra não acessa a carteira do Edgar
    assert com_carteira(eliandra, c_edgar).get("/api/carteira").status_code == 404
    # Mesmo ticker em carteiras diferentes não se mistura
    assert com_carteira(edgar, c_edgar).post("/api/aportes", json=APORTE).status_code == 201
    assert com_carteira(eliandra, c_eli).post("/api/aportes", json={**APORTE, "quantidade": 3}).status_code == 201
    q = lambda cl: cl.get("/api/carteira").get_json()["ativos"][0]["quantidade"]
    assert q(com_carteira(edgar, c_edgar)) == 10 and q(com_carteira(eliandra, c_eli)) == 3
    # Excluir aporte de outra carteira pelo id não tem efeito
    aid = com_carteira(edgar, c_edgar).get("/api/aportes").get_json()[0]["id"]
    com_carteira(eliandra, c_eli).delete(f"/api/aportes/{aid}")
    assert len(com_carteira(edgar, c_edgar).get("/api/aportes").get_json()) == 1


def test_admin_gerencia_carteira_da_eliandra(novo_app):
    _, edgar, _, _, c_eli = preparar(novo_app)
    com_carteira(edgar, c_eli)
    assert edgar.post("/api/aportes", json=APORTE).status_code == 201
    assert edgar.get(f"/api/carteiras/{c_eli}/acessos").get_json()["dono"]["nome"] == "Eliandra"


def test_niveis_de_permissao(novo_app):
    _, edgar, eliandra, c_edgar, _ = preparar(novo_app)
    url = f"/api/carteiras/{c_edgar}/acessos"
    # somente visualização
    assert edgar.put(url, json={"email": "eliandra@exemplo.com", "ver": True}).status_code == 200
    com_carteira(eliandra, c_edgar)
    assert eliandra.get("/api/carteira").status_code == 200
    assert eliandra.post("/api/aportes", json=APORTE).status_code == 403
    assert eliandra.get(url).status_code == 403
    perms = {c["id"]: c["permissoes"] for c in eliandra.get("/api/eu").get_json()["carteiras"]}
    assert perms[c_edgar] == {"ver": True, "editar": False, "gerenciar": False}
    # controle
    edgar.put(url, json={"email": "eliandra@exemplo.com", "editar": True})
    assert eliandra.post("/api/aportes", json=APORTE).status_code == 201
    # gerenciar
    edgar.put(url, json={"email": "eliandra@exemplo.com", "editar": True, "gerenciar": True})
    assert eliandra.get(url).status_code == 200
    # revogar
    uid = edgar.get(url).get_json()["acessos"][0]["usuario_id"]
    edgar.delete(f"{url}/{uid}")
    assert eliandra.get("/api/carteira").status_code == 404


def test_somente_admin_gerencia_usuarios(novo_app):
    _, edgar, eliandra, _, c_eli = preparar(novo_app)
    assert eliandra.get("/api/usuarios").status_code == 403
    assert eliandra.post("/api/usuarios", json={"nome": "X", "email": "x@x.com", "senha": "12345678"}).status_code == 403
    # Eliandra pode criar uma carteira para si, mas não para outra pessoa
    assert eliandra.post("/api/carteiras", json={"nome": "Reserva"}).status_code == 201
    assert eliandra.post("/api/carteiras", json={"nome": "Y", "dono_id": 1}).status_code == 403
    # o último administrador não pode perder o papel
    assert edgar.patch("/api/usuarios/1", json={"admin": False}).status_code == 409
    # administrador desativa Eliandra: a sessão dela deixa de valer
    uid = next(u["id"] for u in edgar.get("/api/usuarios").get_json() if u["nome"] == "Eliandra")
    assert edgar.patch(f"/api/usuarios/{uid}", json={"ativo": False}).status_code == 200
    assert eliandra.get("/api/eu").status_code == 401


def test_alterar_senha(novo_app):
    app, _, eliandra, _, _ = preparar(novo_app)
    assert eliandra.post("/api/eu/senha", json={"atual": "errada", "nova": "nova-senha-1"}).status_code == 403
    assert eliandra.post("/api/eu/senha", json={"atual": "senha-eli-123", "nova": "curta"}).status_code == 400
    assert eliandra.post("/api/eu/senha", json={"atual": "senha-eli-123", "nova": "nova-senha-1"}).status_code == 200
    cliente_logado(app, "eliandra@exemplo.com", "nova-senha-1")


def test_migracao_de_banco_antigo(tmp_path, novo_app):
    caminho = tmp_path / "t.db"
    antigo = sqlite3.connect(caminho)
    antigo.executescript("""
        CREATE TABLE ativos (id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT NOT NULL UNIQUE, nome TEXT,
            classe TEXT NOT NULL DEFAULT 'acao', meta_pct REAL NOT NULL DEFAULT 0, preco_manual REAL);
        CREATE TABLE aportes (id INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT NOT NULL, ticker TEXT NOT NULL,
            tipo TEXT NOT NULL DEFAULT 'compra', quantidade REAL NOT NULL, preco REAL NOT NULL,
            taxas REAL NOT NULL DEFAULT 0, obs TEXT);
        INSERT INTO ativos (ticker, meta_pct) VALUES ('WEGE3', 100);
        INSERT INTO aportes (data, ticker, quantidade, preco) VALUES ('2025-01-02', 'WEGE3', 7, 40);
    """)
    antigo.commit()
    antigo.close()
    db.connect(str(caminho)).close()
    edgar = cliente_logado(novo_app(fonte))
    cart = edgar.get("/api/eu").get_json()["carteiras"]
    assert [c["nome"] for c in cart] == ["Carteira Edgar Machado"] and cart[0]["sou_dono"]
    assert edgar.get("/api/carteira").get_json()["ativos"][0]["quantidade"] == 7


def test_requisicoes_em_paralelo(novo_app):
    """Várias threads usando o banco ao mesmo tempo (como no servidor real)."""
    from concurrent.futures import ThreadPoolExecutor
    app, edgar, eliandra, c_edgar, c_eli = preparar(novo_app)
    com_carteira(edgar, c_edgar).post("/api/aportes", json=APORTE)

    def consulta(i):
        c = cliente_logado(app, "eliandra@exemplo.com", "senha-eli-123") if i % 2 else \
            cliente_logado(app)
        cid = c_eli if i % 2 else c_edgar
        c.environ_base["HTTP_X_CARTEIRA"] = str(cid)
        return [c.get(u).status_code for u in ("/api/carteira", "/api/aportes", "/api/eu")]

    with ThreadPoolExecutor(8) as ex:
        resultados = list(ex.map(consulta, range(24)))
    assert all(r == [200, 200, 200] for r in resultados)


def test_backup(novo_app, tmp_path, monkeypatch):
    import sqlite3
    monkeypatch.setenv("CARTEIRA_BACKUP_DIR", str(tmp_path / "copias"))
    _, edgar, eliandra, c_edgar, _ = preparar(novo_app)
    com_carteira(edgar, c_edgar).post("/api/aportes", json=APORTE)
    assert eliandra.get("/api/backup").status_code == 403  # só administradores
    assert edgar.post("/api/backup").status_code == 201
    copias = edgar.get("/api/backup").get_json()["copias"]
    assert len(copias) == 1 and copias[0]["nome"].startswith("carteira-")
    copia = sqlite3.connect(tmp_path / "copias" / copias[0]["nome"])
    assert copia.execute("SELECT COUNT(*) FROM aportes").fetchone()[0] == 1
    r = edgar.get("/api/backup/baixar")
    assert r.status_code == 200 and r.data[:15] == b"SQLite format 3"
    assert len(edgar.get("/api/backup").get_json()["copias"]) == 1  # o arquivo baixado não fica na pasta


def test_zerar_dados_da_carteira(novo_app):
    _, edgar, eliandra, c_edgar, c_eli = preparar(novo_app)
    assert com_carteira(edgar, c_edgar).post("/api/aportes", json=APORTE).status_code == 201
    assert com_carteira(eliandra, c_eli).post("/api/aportes", json=APORTE).status_code == 201
    url = f"/api/carteiras/{c_edgar}/zerar"
    # Eliandra não gerencia a carteira do Edgar
    assert eliandra.post(url, json={"confirmacao": "Carteira Edgar Machado"}).status_code == 403
    # confirmação errada não apaga nada
    assert edgar.post(url, json={"confirmacao": "outra"}).status_code == 400
    assert len(com_carteira(edgar, c_edgar).get("/api/aportes").get_json()) == 1
    r = edgar.post(url, json={"confirmacao": "carteira edgar machado"})
    assert r.status_code == 200 and r.get_json()["removidos"]["aportes"] == 1
    assert r.get_json()["backup"].startswith("antes-importacao-")
    assert com_carteira(edgar, c_edgar).get("/api/aportes").get_json() == []
    assert com_carteira(edgar, c_edgar).get("/api/carteira").get_json()["ativos"] == []
    # a outra carteira continua intacta
    assert len(com_carteira(eliandra, c_eli).get("/api/aportes").get_json()) == 1
