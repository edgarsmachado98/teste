"""Módulo adicional: Planejamento financeiro (fase 1).

Receitas (bruto e líquido) e despesas por categoria, contas que se repetem todo mês, compras
parceladas e o resumo do mês, ligado à carteira de investimentos: os proventos entram como
receita e os aportes como dinheiro investido.

As tabelas ficam separadas das da carteira (prefixo fin_) e são criadas só quando o módulo é
usado, para que ele possa ser ativado ou desativado pela licença sem afetar o sistema base.
"""
import calendar
import datetime as dt
import uuid
from collections import defaultdict

from . import db
from .portfolio import eh_evento, sem_caixa

ESQUEMA = """
CREATE TABLE IF NOT EXISTS fin_categorias (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo   TEXT NOT NULL CHECK (tipo IN ('receita', 'despesa')),
    grupo  TEXT NOT NULL,
    nome   TEXT NOT NULL,
    ordem  INTEGER NOT NULL DEFAULT 0,
    ativa  INTEGER NOT NULL DEFAULT 1,
    UNIQUE (tipo, grupo, nome)
);

-- Contas e receitas que se repetem todo mês (salário, aluguel, escola, assinaturas...).
CREATE TABLE IF NOT EXISTS fin_recorrencias (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    carteira_id  INTEGER NOT NULL REFERENCES carteiras(id) ON DELETE CASCADE,
    tipo         TEXT NOT NULL CHECK (tipo IN ('receita', 'despesa')),
    descricao    TEXT NOT NULL,
    categoria_id INTEGER REFERENCES fin_categorias(id),
    valor        REAL NOT NULL CHECK (valor >= 0),      -- líquido (receita) ou valor da conta (despesa)
    valor_bruto  REAL,                                  -- receita: antes dos descontos
    dia          INTEGER NOT NULL CHECK (dia BETWEEN 1 AND 31),
    inicio       TEXT NOT NULL,                         -- AAAA-MM
    fim          TEXT,                                  -- AAAA-MM (vazio = sem fim)
    forma        TEXT,
    gerado_ate   TEXT                                   -- último mês já lançado (AAAA-MM)
);

CREATE TABLE IF NOT EXISTS fin_lancamentos (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    carteira_id    INTEGER NOT NULL REFERENCES carteiras(id) ON DELETE CASCADE,
    tipo           TEXT NOT NULL CHECK (tipo IN ('receita', 'despesa')),
    data           TEXT NOT NULL,
    descricao      TEXT NOT NULL,
    categoria_id   INTEGER REFERENCES fin_categorias(id),
    valor          REAL NOT NULL CHECK (valor >= 0),
    valor_bruto    REAL,
    forma          TEXT,
    pago           INTEGER NOT NULL DEFAULT 1,          -- despesa paga / receita recebida
    recorrencia_id INTEGER REFERENCES fin_recorrencias(id) ON DELETE SET NULL,
    parcela_grupo  TEXT,
    parcela_num    INTEGER,
    parcela_total  INTEGER,
    obs            TEXT
);
CREATE INDEX IF NOT EXISTS fin_lanc_data ON fin_lancamentos (carteira_id, data);
"""

FORMAS = {"pix": "Pix", "debito": "Débito", "credito": "Cartão de crédito", "boleto": "Boleto",
          "dinheiro": "Dinheiro", "transferencia": "Transferência", "debito_automatico": "Débito automático"}

CATEGORIAS_PADRAO = {
    "receita": {
        "Trabalho": ["Salário", "13º salário", "Férias", "PLR / bônus", "Pró-labore", "Freelance / autônomo"],
        "Aluguéis": ["Aluguel recebido"],
        "Benefícios": ["Aposentadoria / pensão", "Auxílios"],
        "Eventuais": ["Restituição do IR", "Venda de bens", "Presentes", "Outras receitas"],
    },
    "despesa": {
        "Moradia": ["Aluguel / financiamento", "Condomínio", "Energia", "Água", "Gás", "Internet / telefone",
                    "IPTU", "Manutenção"],
        "Alimentação": ["Mercado", "Restaurante", "Delivery", "Padaria"],
        "Transporte": ["Combustível", "Aplicativo / táxi", "Transporte público", "Manutenção do carro",
                       "Seguro do carro", "IPVA / licenciamento", "Estacionamento / pedágio"],
        "Saúde": ["Plano de saúde", "Farmácia", "Consultas / exames", "Academia"],
        "Educação": ["Escola / faculdade", "Cursos", "Livros / material"],
        "Lazer": ["Viagens", "Passeios", "Streaming / assinaturas", "Hobbies"],
        "Pessoais": ["Roupas", "Beleza / cuidados", "Presentes"],
        "Filhos e pets": ["Filhos", "Pets"],
        "Impostos e taxas": ["Imposto de renda", "Tarifas bancárias", "Outros impostos"],
        "Dívidas": ["Empréstimo", "Juros / multas", "Cartão (parcelamento de fatura)"],
        "Outros": ["Doações", "Outras despesas"],
    },
}

GRUPO_PROVENTOS = "Investimentos"
NOME_PROVENTOS = "Proventos dos investimentos"


def preparar(conn):
    """Cria as tabelas do módulo e as categorias padrão (idempotente)."""
    conn.executescript(ESQUEMA)
    if conn.execute("SELECT COUNT(*) FROM fin_categorias").fetchone()[0] == 0:
        for tipo, grupos in CATEGORIAS_PADRAO.items():
            for g_i, (grupo, nomes) in enumerate(grupos.items()):
                for n_i, nome in enumerate(nomes):
                    conn.execute("INSERT INTO fin_categorias (tipo, grupo, nome, ordem) VALUES (?, ?, ?, ?)",
                                 (tipo, grupo, nome, g_i * 100 + n_i))
    conn.commit()


# ------------------------------------------------------------------ datas

def mes_de(data_iso):
    return data_iso[:7]


def somar_meses(mes, n):
    a, m = int(mes[:4]), int(mes[5:7]) - 1 + n
    return f"{a + m // 12:04d}-{m % 12 + 1:02d}"


def meses_entre(inicio, fim):
    m = inicio
    while m <= fim:
        yield m
        m = somar_meses(m, 1)


def data_no_mes(mes, dia):
    """Dia `dia` do mês, limitado ao último dia (31 em fevereiro vira 28/29)."""
    a, m = int(mes[:4]), int(mes[5:7])
    return dt.date(a, m, min(int(dia), calendar.monthrange(a, m)[1])).isoformat()


# ------------------------------------------------------------------ recorrências e parcelas

def materializar(conn, carteira_ids, ate_mes):
    """Lança as ocorrências das contas recorrentes até `ate_mes` (inclusive).

    Cada mês é lançado uma única vez (controle por `gerado_ate`): se o usuário excluir uma
    ocorrência, ela não volta. Ocorrências novas entram como não pagas / não recebidas.
    """
    ids = list(carteira_ids)
    marcas = ",".join("?" * len(ids))
    recs = db.rows(conn.execute(f"SELECT * FROM fin_recorrencias WHERE carteira_id IN ({marcas})", ids))
    criou = False
    for r in recs:
        inicio = somar_meses(r["gerado_ate"], 1) if r["gerado_ate"] else r["inicio"]
        fim = min(ate_mes, r["fim"]) if r["fim"] else ate_mes
        ultimo = None
        for mes in meses_entre(inicio, fim):
            conn.execute(
                """INSERT INTO fin_lancamentos (carteira_id, tipo, data, descricao, categoria_id, valor, valor_bruto,
                   forma, pago, recorrencia_id) VALUES (?,?,?,?,?,?,?,?,0,?)""",
                (r["carteira_id"], r["tipo"], data_no_mes(mes, r["dia"]), r["descricao"], r["categoria_id"],
                 r["valor"], r["valor_bruto"], r["forma"], r["id"]))
            ultimo, criou = mes, True
        if ultimo:
            conn.execute("UPDATE fin_recorrencias SET gerado_ate = ? WHERE id = ?", (ultimo, r["id"]))
    if criou:
        conn.commit()


def projetar_recorrencias(conn, carteira_ids, mes):
    """Ocorrências ainda não lançadas das recorrências em um mês futuro (só para projeção)."""
    ids = list(carteira_ids)
    marcas = ",".join("?" * len(ids))
    out = []
    for r in db.rows(conn.execute(f"SELECT * FROM fin_recorrencias WHERE carteira_id IN ({marcas})", ids)):
        if r["inicio"] <= mes and (not r["fim"] or mes <= r["fim"]) and (not r["gerado_ate"] or mes > r["gerado_ate"]):
            out.append({"id": None, "carteira_id": r["carteira_id"], "tipo": r["tipo"], "data": data_no_mes(mes, r["dia"]),
                        "descricao": r["descricao"], "categoria_id": r["categoria_id"], "valor": r["valor"],
                        "valor_bruto": r["valor_bruto"], "forma": r["forma"], "pago": 0, "recorrencia_id": r["id"],
                        "parcela_num": None, "parcela_total": None, "projetado": True})
    return out


def parcelas(valor_total, n, data_primeira):
    """Divide uma compra parcelada: [(data, valor, número)], a diferença de centavos na 1ª parcela."""
    n = int(n)
    base = round(valor_total / n, 2)
    primeira = round(valor_total - base * (n - 1), 2)
    mes, dia = data_primeira[:7], int(data_primeira[8:10])
    return [(data_no_mes(somar_meses(mes, i), dia), primeira if i == 0 else base, i + 1) for i in range(n)]


def novo_grupo_parcelas():
    return uuid.uuid4().hex[:12]


# ------------------------------------------------------------------ resumo

def _nome_categoria(categorias, cid):
    c = categorias.get(cid)
    return (c["grupo"], c["nome"]) if c else ("Sem categoria", "Sem categoria")


def investido_por_mes(aportes):
    """Dinheiro que foi para investimentos em cada mês: compras − vendas (ajustes sem caixa fora)."""
    por_mes = defaultdict(float)
    for a in aportes:
        if eh_evento(a) or sem_caixa(a):
            continue
        sinal = 1 if a.get("tipo", "compra") == "compra" else -1
        por_mes[mes_de(a["data"])] += sinal * (float(a["quantidade"]) * float(a["preco"]) + float(a.get("taxas") or 0) * sinal)
    return por_mes


def proventos_por_mes(proventos, hoje):
    """Proventos já pagos, por mês de pagamento."""
    por_mes = defaultdict(float)
    for p in proventos:
        if p["data_pagamento"] <= hoje:
            por_mes[mes_de(p["data_pagamento"])] += float(p["valor_total"])
    return por_mes


def resumo_mes(lancamentos, categorias, mes, proventos_mes, investido_mes, anterior=None):
    """Resumo de um mês: totais, receitas e despesas por categoria, contas a pagar e indicadores.

    lancamentos: do mês (reais e projetados); categorias: {id: row}; proventos_mes / investido_mes:
    valores vindos da carteira; anterior: resumo do mês anterior (para comparar os grupos).
    """
    receitas = [l for l in lancamentos if l["tipo"] == "receita"]
    despesas = [l for l in lancamentos if l["tipo"] == "despesa"]
    rec_cat, desp_grupo, desp_cat = defaultdict(float), defaultdict(float), defaultdict(float)
    for l in receitas:
        grupo, nome = _nome_categoria(categorias, l["categoria_id"])
        rec_cat[(grupo, nome)] += l["valor"]
    if proventos_mes:
        rec_cat[(GRUPO_PROVENTOS, NOME_PROVENTOS)] += proventos_mes
    for l in despesas:
        grupo, nome = _nome_categoria(categorias, l["categoria_id"])
        desp_grupo[grupo] += l["valor"]
        desp_cat[(grupo, nome)] += l["valor"]
    total_rec = sum(rec_cat.values())
    total_desp = sum(desp_grupo.values())
    bruto = sum((l["valor_bruto"] if l.get("valor_bruto") else l["valor"]) for l in receitas)
    liquido_trabalho = sum(l["valor"] for l in receitas)
    sobra = total_rec - total_desp - investido_mes
    ant_grupos = {g["grupo"]: g["valor"] for g in (anterior or {}).get("despesas_por_grupo", [])}
    return {
        "mes": mes,
        "receitas": total_rec, "despesas": total_desp, "investido": investido_mes, "sobra": sobra,
        "receita_bruta": bruto + proventos_mes, "descontos": bruto - liquido_trabalho, "proventos": proventos_mes,
        "taxa_poupanca": investido_mes / total_rec * 100 if total_rec > 0 else None,
        "cobertura_proventos": proventos_mes / total_desp * 100 if total_desp > 0 else None,
        "receitas_por_categoria": sorted(({"grupo": g, "categoria": n, "valor": v} for (g, n), v in rec_cat.items()),
                                         key=lambda x: -x["valor"]),
        "despesas_por_grupo": sorted(({"grupo": g, "valor": v, "pct": v / total_desp * 100 if total_desp else 0,
                                       "anterior": ant_grupos.get(g)} for g, v in desp_grupo.items()),
                                     key=lambda x: -x["valor"]),
        "despesas_por_categoria": sorted(({"grupo": g, "categoria": n, "valor": v} for (g, n), v in desp_cat.items()),
                                         key=lambda x: -x["valor"]),
        "a_pagar": sorted(({"id": l["id"], "data": l["data"], "descricao": l["descricao"], "valor": l["valor"],
                            "projetado": bool(l.get("projetado"))}
                           for l in despesas if not l["pago"]), key=lambda x: x["data"]),
        "a_receber": sorted(({"id": l["id"], "data": l["data"], "descricao": l["descricao"], "valor": l["valor"],
                              "projetado": bool(l.get("projetado"))}
                             for l in receitas if not l["pago"]), key=lambda x: x["data"]),
    }


def custo_de_vida(despesas_por_mes, mes_atual, meses=12):
    """Média das despesas dos últimos meses fechados que têm lançamentos (até `meses`)."""
    fechados = sorted(((m, v) for m, v in despesas_por_mes.items() if m < mes_atual and v > 0))[-meses:]
    return sum(v for _, v in fechados) / len(fechados) if fechados else None
