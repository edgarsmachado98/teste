"""Popula o banco com uma carteira de exemplo (use junto com CARTEIRA_DEMO=1)."""
from app import create_app
from carteira.market import modo_demo, serie_simulada


def preco_na_data(ticker, data, padrao):
    """No modo demo usa o preço simulado da data, para a carteira ficar coerente."""
    if not modo_demo() or ticker.startswith("TESOURO"):
        return padrao
    serie = dict(serie_simulada(ticker))
    datas = [d for d in sorted(serie) if d <= data]
    return serie[datas[-1]] if datas else padrao

ATIVOS = [
    ("ITUB4", "Itaú Unibanco", "acao", 15), ("VALE3", "Vale", "acao", 15),
    ("WEGE3", "WEG", "acao", 10), ("KNRI11", "Kinea Renda Imobiliária", "fii", 15),
    ("HGLG11", "CSHG Logística", "fii", 10), ("IVVB11", "iShares S&P 500", "etf", 20),
    ("TESOURO-IPCA", "Tesouro IPCA+ 2035", "renda_fixa", 15),
]
APORTES = [
    ("2025-01-10", "ITUB4", 100, 31.50), ("2025-01-10", "KNRI11", 20, 138.0),
    ("2025-02-12", "VALE3", 50, 58.20), ("2025-03-11", "IVVB11", 15, 320.0),
    ("2025-04-09", "WEGE3", 30, 52.0), ("2025-05-13", "HGLG11", 10, 158.0),
    ("2025-06-10", "TESOURO-IPCA", 2, 2150.0), ("2025-08-12", "ITUB4", 50, 35.1),
]

if __name__ == "__main__":
    app = create_app()
    with app.test_client() as c:
        for t, n, cl, m in ATIVOS:
            c.post("/api/ativos", json={"ticker": t, "nome": n, "classe": cl, "meta_pct": m,
                                        "preco_manual": 2400 if cl == "renda_fixa" else None})
        for d, t, q, p in APORTES:
            c.post("/api/aportes", json={"data": d, "ticker": t, "quantidade": q,
                                         "preco": preco_na_data(t, d, p)})
    print("Carteira de exemplo criada.")
