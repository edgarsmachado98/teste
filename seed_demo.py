"""Cria usuários e carteiras de exemplo (use junto com CARTEIRA_DEMO=1).

Usuários criados:
    edgar@exemplo.com     / demo12345  (administrador, dono da "Carteira Edgar Machado")
    eliandra@exemplo.com  / demo12345  (dona da "Carteira Eliandra")
"""
import sys

from app import create_app
from carteira.market import modo_demo, serie_simulada

SENHA = "demo12345"

CARTEIRA_EDGAR = {
    "ativos": [
        ("ITUB4", "Itaú Unibanco", "acao", 15), ("VALE3", "Vale", "acao", 15),
        ("WEGE3", "WEG", "acao", 10), ("KNRI11", "Kinea Renda Imobiliária", "fii", 15),
        ("HGLG11", "CSHG Logística", "fii", 10), ("IVVB11", "iShares S&P 500", "etf", 20),
        ("TESOURO IPCA+ 2035", "Tesouro IPCA+ 2035", "renda_fixa", 10),
        ("CDB BANCO EXEMPLO", "CDB 110% CDI", "renda_fixa", 5),
        ("LCA AGRO EXEMPLO", "LCA 95% CDI", "renda_fixa", 0),
    ],
    "renda_fixa": {
        "TESOURO IPCA+ 2035": {"indexador": "tesouro"},
        "CDB BANCO EXEMPLO": {"indexador": "cdi", "taxa": 110, "vencimento": "2027-06-15"},
        "LCA AGRO EXEMPLO": {"indexador": "cdi", "taxa": 95, "vencimento": "2026-12-10", "isento_ir": True},
    },
    "aportes": [
        ("2025-01-10", "ITUB4", 100, 31.50), ("2025-01-10", "KNRI11", 20, 138.0),
        ("2025-02-12", "VALE3", 50, 58.20), ("2025-03-11", "IVVB11", 15, 320.0),
        ("2025-04-09", "WEGE3", 30, 52.0), ("2025-05-13", "HGLG11", 10, 158.0),
        ("2025-06-10", "TESOURO IPCA+ 2035", 2, 2150.0), ("2025-08-12", "ITUB4", 50, 35.1),
        ("2025-03-05", "CDB BANCO EXEMPLO", 1, 5000.0), ("2025-12-10", "LCA AGRO EXEMPLO", 1, 3000.0),
    ],
}

CARTEIRA_ELIANDRA = {
    "ativos": [
        ("BBAS3", "Banco do Brasil", "acao", 20), ("TAEE11", "Taesa", "acao", 20),
        ("MXRF11", "Maxi Renda", "fii", 25), ("BOVA11", "iShares Ibovespa", "etf", 15),
        ("TESOURO SELIC 2029", "Tesouro Selic 2029", "renda_fixa", 20),
        ("CDB IPCA EXEMPLO", "CDB IPCA + 6,5%", "renda_fixa", 0),
    ],
    "renda_fixa": {
        "TESOURO SELIC 2029": {"indexador": "tesouro"},
        "CDB IPCA EXEMPLO": {"indexador": "ipca", "taxa": 6.5, "vencimento": "2029-05-15"},
    },
    "aportes": [
        ("2025-02-05", "BBAS3", 40, 27.0), ("2025-02-05", "MXRF11", 150, 9.6),
        ("2025-04-07", "TAEE11", 30, 34.0), ("2025-06-09", "BOVA11", 10, 128.0),
        ("2025-07-08", "TESOURO SELIC 2029", 1, 15800.0), ("2025-10-06", "CDB IPCA EXEMPLO", 1, 4000.0), ("2025-09-10", "MXRF11", 100, 9.9),
    ],
}


def preco_na_data(ticker, data, padrao):
    """No modo demo usa o preço simulado da data, para a carteira ficar coerente."""
    if not modo_demo() or ticker.startswith(("TESOURO", "CDB", "LCA")):
        return padrao
    serie = dict(serie_simulada(ticker))
    datas = [d for d in sorted(serie) if d <= data]
    return serie[datas[-1]] if datas else padrao


def popular(c, dados):
    for t, n, cl, m in dados["ativos"]:
        c.post("/api/ativos", json={"ticker": t, "nome": n, "classe": cl, "meta_pct": m,
                                    **dados.get("renda_fixa", {}).get(t, {})})
    for d, t, q, p in dados["aportes"]:
        c.post("/api/aportes", json={"data": d, "ticker": t, "quantidade": q,
                                     "preco": preco_na_data(t, d, p)})
    est = c.get("/api/proventos/estimar").get_json()
    recebidos = [i for i in est["itens"] if i["status"] == "recebido" and not i["ja_registrado"]]
    if recebidos:
        c.post("/api/proventos/importar", json={"itens": recebidos})
    return len(recebidos)


def cliente(app):
    c = app.test_client()
    c.environ_base["HTTP_X_REQUESTED_WITH"] = "fetch"
    return c


if __name__ == "__main__":
    app = create_app()
    conn = app.config["conn"]
    if conn.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] or \
            conn.execute("SELECT COUNT(*) FROM aportes").fetchone()[0]:
        sys.exit("O banco já tem dados. Apague o arquivo do banco (ex.: demo.db) e rode de novo.")

    edgar = cliente(app)
    edgar.post("/auth/setup", json={"nome": "Edgar Machado", "email": "edgar@exemplo.com",
                                    "senha": SENHA, "nome_carteira": "Carteira Edgar Machado"})
    edgar.post("/api/usuarios", json={"nome": "Eliandra", "email": "eliandra@exemplo.com", "senha": SENHA,
                                      "criar_carteira": True, "nome_carteira": "Carteira Eliandra"})
    ids = {c["nome"]: c["id"] for c in edgar.get("/api/eu").get_json()["carteiras"]}

    edgar.environ_base["HTTP_X_CARTEIRA"] = str(ids["Carteira Edgar Machado"])
    n1 = popular(edgar, CARTEIRA_EDGAR)
    # O Edgar (administrador) gerencia também a carteira da Eliandra.
    edgar.environ_base["HTTP_X_CARTEIRA"] = str(ids["Carteira Eliandra"])
    n2 = popular(edgar, CARTEIRA_ELIANDRA)
    # Exemplo de compartilhamento: Eliandra pode visualizar a carteira do Edgar.
    edgar.put(f"/api/carteiras/{ids['Carteira Edgar Machado']}/acessos",
              json={"email": "eliandra@exemplo.com", "ver": True})

    print("Dados de exemplo criados.")
    print(f"  Carteira Edgar Machado: {n1} proventos importados")
    print(f"  Carteira Eliandra:      {n2} proventos importados")
    print(f"Login: edgar@exemplo.com (administrador) ou eliandra@exemplo.com, senha {SENHA}")
