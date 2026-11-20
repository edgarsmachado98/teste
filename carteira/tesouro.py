"""Preços oficiais do Tesouro Direto (Tesouro Transparente, dados abertos).

O arquivo PrecoTaxaTesouroDireto.csv traz, para cada título e dia, as taxas e os preços
unitários (PU) de compra e de venda. Usamos o "PU Venda Manhã" (valor que o investidor
recebe ao vender ao Tesouro); quando ausente, o "PU Base Manhã".

O arquivo é grande (todo o histórico): ele é baixado no máximo uma vez por dia e só os
títulos usados nas carteiras são guardados em cache.
"""
import csv
import datetime as dt
import io
import json
import math
import os
import random
import re
import unicodedata

import requests

URL_PADRAO = ("https://www.tesourotransparente.gov.br/ckan/dataset/df56aa42-484a-4a59-8184-7676580c81e3/"
              "resource/796d2059-14e9-44e3-80c9-2d9e30b405c1/download/PrecoTaxaTesouroDireto.csv")


def _norm(t):
    t = unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", t).strip()


def identificar(nome, vencimento=None):
    """'TESOURO IPCA+ 2035' -> ('tesouro ipca+', 2035, None). Com vencimento completo, usa a data."""
    n = _norm(nome)
    if not n.startswith("tesouro"):
        return None
    ano = None
    if vencimento:
        ano = int(str(vencimento)[:4])
    else:
        m = re.search(r"\b(20\d{2})\b", n)
        ano = int(m.group(1)) if m else None
    tipo = re.sub(r"\b20\d{2}\b|\d{1,2}/\d{1,2}/\d{2,4}|-", " ", n)
    tipo = re.sub(r"\s+", " ", tipo).strip()
    return tipo, ano, (str(vencimento)[:10] if vencimento and len(str(vencimento)) >= 10 else None)


def _numero(v):
    v = str(v or "").strip().replace(".", "").replace(",", ".")
    try:
        return float(v)
    except ValueError:
        return None


def ler_csv(texto, procurados):
    """Extrai do CSV oficial os preços dos títulos procurados.

    procurados: {chave: (tipo_normalizado, ano, vencimento ISO ou None)}
    Retorna {chave: [(data ISO, PU)]} ordenado por data e {chave: vencimento ISO}.
    """
    leitor = csv.reader(io.StringIO(texto), delimiter=";")
    cab = [_norm(c) for c in next(leitor)]
    i_tipo, i_venc, i_base = cab.index("tipo titulo"), cab.index("data vencimento"), cab.index("data base")
    i_pu = cab.index("pu venda manha") if "pu venda manha" in cab else None
    i_pub = cab.index("pu base manha") if "pu base manha" in cab else None
    out = {k: {} for k in procurados}
    vencimentos = {}
    for linha in leitor:
        if len(linha) <= max(i_tipo, i_venc, i_base):
            continue
        tipo = _norm(linha[i_tipo])
        d, m, a = linha[i_venc].split("/")
        venc = f"{a}-{m}-{d}"
        for chave, (t, ano, venc_exato) in procurados.items():
            if tipo != t or (venc_exato and venc != venc_exato) or (ano and int(a) != ano):
                continue
            pu = _numero(linha[i_pu]) if i_pu is not None else None
            if not pu and i_pub is not None:
                pu = _numero(linha[i_pub])
            if pu:
                db, mb, ab = linha[i_base].split("/")
                out[chave][f"{ab}-{mb}-{db}"] = pu
                vencimentos[chave] = venc
    return {k: sorted(v.items()) for k, v in out.items()}, vencimentos


def baixar_csv():
    url = os.environ.get("TESOURO_CSV_URL") or URL_PADRAO
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    return resp.content.decode("utf-8-sig", errors="replace") if b"\xc3" in resp.content[:200000] \
        else resp.content.decode("latin-1")


PRECO_INICIAL_SIMULADO = {"tesouro selic": 14500, "tesouro ipca+": 1900, "tesouro prefixado": 620}
VENCIMENTO_SIMULADO = {"tesouro selic": "03-01", "tesouro ipca+": "05-15", "tesouro prefixado": "01-01"}


def _simulado(chave, fim, tipo=None):
    """Série plausível para o modo demonstração (preço inicial típico de cada tipo de título)."""
    rng = random.Random(chave)
    base = PRECO_INICIAL_SIMULADO.get(tipo, 3000)
    preco, d = base * rng.uniform(0.95, 1.05), dt.date.fromisoformat(fim) - dt.timedelta(days=900)
    out = []
    while d <= dt.date.fromisoformat(fim):
        if d.weekday() < 5:
            preco *= math.exp(0.10 / 252 + rng.gauss(0, 0.002))
            out.append((d.isoformat(), round(preco, 2)))
        d += dt.timedelta(days=1)
    return out


class Tesouro:
    def __init__(self, conn, fonte_csv=None):
        self.conn = conn
        self.fonte_csv = fonte_csv or baixar_csv

    def precos(self, titulos, demo=False):
        """titulos: {ticker: (nome, vencimento)} -> ({ticker: [(data, PU)]}, {ticker: erro}, {ticker: vencimento})."""
        hoje = dt.date.today().isoformat()
        procurados, resultado, erros, vencimentos = {}, {}, {}, {}
        for ticker, (nome, venc) in titulos.items():
            ident = identificar(nome, venc)
            if not ident or not ident[1]:
                erros[ticker] = "Não identifiquei o título e o ano de vencimento pelo nome (ex.: TESOURO IPCA+ 2035)."
                continue
            if demo:
                resultado[ticker] = _simulado(ticker, hoje, ident[0])
                vencimentos[ticker] = ident[2] or f"{ident[1]}-{VENCIMENTO_SIMULADO.get(ident[0], '01-01')}"
                continue
            row = self.conn.execute("SELECT * FROM cache_dados WHERE ticker = ? AND tipo = 'tesouro'",
                                    (ticker,)).fetchone()
            if row and row["atualizado"] == hoje:
                cache = json.loads(row["conteudo"])
                resultado[ticker] = [tuple(x) for x in cache["serie"]]
                vencimentos[ticker] = cache.get("vencimento")
            else:
                procurados[ticker] = ident
        if procurados:
            try:
                novos, venc_novos = ler_csv(self.fonte_csv(), procurados)
            except Exception as e:  # sem rede: usa o último preço salvo, se houver
                novos, venc_novos = {}, {}
                for ticker in procurados:
                    row = self.conn.execute("SELECT conteudo FROM cache_dados WHERE ticker = ? AND tipo = 'tesouro'",
                                            (ticker,)).fetchone()
                    if row:
                        cache = json.loads(row["conteudo"])
                        resultado[ticker] = [tuple(x) for x in cache["serie"]]
                        vencimentos[ticker] = cache.get("vencimento")
                    else:
                        erros[ticker] = f"Preços do Tesouro indisponíveis: {e}"
            for ticker, serie in novos.items():
                if not serie:
                    erros[ticker] = "Título não encontrado nos preços oficiais do Tesouro."
                    continue
                resultado[ticker], vencimentos[ticker] = serie, venc_novos.get(ticker)
                self.conn.execute("INSERT OR REPLACE INTO cache_dados (ticker, tipo, atualizado, fonte, conteudo) "
                                  "VALUES (?, 'tesouro', ?, 'tesouro', ?)",
                                  (ticker, hoje, json.dumps({"serie": serie, "vencimento": vencimentos[ticker]})))
            self.conn.commit()
        return resultado, erros, vencimentos
