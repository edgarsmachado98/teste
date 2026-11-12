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

CREATE TABLE IF NOT EXISTS fin_cartoes (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    carteira_id    INTEGER NOT NULL REFERENCES carteiras(id) ON DELETE CASCADE,
    nome           TEXT NOT NULL,
    dia_vencimento INTEGER CHECK (dia_vencimento BETWEEN 1 AND 31),
    ativo          INTEGER NOT NULL DEFAULT 1
);

-- Configurações do módulo (modo do casal, pesos da divisão...).
CREATE TABLE IF NOT EXISTS fin_config (
    chave TEXT PRIMARY KEY,
    valor TEXT
);

-- Limite mensal de gastos por grupo de despesa.
CREATE TABLE IF NOT EXISTS fin_orcamento (
    carteira_id INTEGER NOT NULL REFERENCES carteiras(id) ON DELETE CASCADE,
    grupo       TEXT NOT NULL,
    limite      REAL NOT NULL CHECK (limite >= 0),
    PRIMARY KEY (carteira_id, grupo)
);

-- Objetivos financeiros (reserva, aposentadoria, imóvel...).
CREATE TABLE IF NOT EXISTS fin_objetivos (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    carteira_id       INTEGER NOT NULL REFERENCES carteiras(id) ON DELETE CASCADE,
    tipo              TEXT NOT NULL,
    nome              TEXT NOT NULL,
    valor_alvo        REAL,
    data_alvo         TEXT,
    valor_guardado    REAL NOT NULL DEFAULT 0,   -- valor já guardado fora da carteira (poupança, conta...)
    aporte_mensal     REAL NOT NULL DEFAULT 0,   -- quanto pretende guardar por mês
    rentabilidade     REAL NOT NULL DEFAULT 4,   -- % ao ano acima da inflação
    renda_desejada    REAL,                      -- aposentadoria / renda passiva (R$/mês)
    idade_atual       INTEGER,
    idade_alvo        INTEGER,
    meses_reserva     INTEGER,
    prioridade        INTEGER NOT NULL DEFAULT 2,
    tickers           TEXT,                      -- ativos da carteira vinculados (separados por vírgula)
    criado_em         TEXT
);

-- Membros da família: quem é o titular de cada carteira no planejamento (com ou sem login no sistema).
CREATE TABLE IF NOT EXISTS fin_membros (
    carteira_id INTEGER PRIMARY KEY REFERENCES carteiras(id) ON DELETE CASCADE,
    nome        TEXT NOT NULL,
    parentesco  TEXT NOT NULL DEFAULT 'titular',
    divide      INTEGER NOT NULL DEFAULT 1      -- participa da divisão das contas da família
);

-- Estabelecimento -> categoria, aprendido com as correções do usuário na importação de faturas.
CREATE TABLE IF NOT EXISTS fin_regras (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    carteira_id  INTEGER NOT NULL REFERENCES carteiras(id) ON DELETE CASCADE,
    padrao       TEXT NOT NULL,
    categoria_id INTEGER NOT NULL REFERENCES fin_categorias(id) ON DELETE CASCADE,
    usos         INTEGER NOT NULL DEFAULT 1,
    UNIQUE (carteira_id, padrao)
);

-- Notas fiscais (NFC-e) lidas pelo QR Code: a loja e os itens ficam guardados junto do lançamento.
CREATE TABLE IF NOT EXISTS fin_notas (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    carteira_id  INTEGER NOT NULL REFERENCES carteiras(id) ON DELETE CASCADE,
    chave        TEXT NOT NULL,
    emitente     TEXT,
    cnpj         TEXT,
    emissao      TEXT,
    total        REAL,
    itens        TEXT,               -- JSON: [{descricao, qtd, un, unitario, valor}]
    url          TEXT,
    criado_em    TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE (carteira_id, chave)
);
"""

FORMAS = {"pix": "Pix", "debito": "Débito", "credito": "Cartão de crédito", "boleto": "Boleto",
          "dinheiro": "Dinheiro", "transferencia": "Transferência", "debito_automatico": "Débito automático"}

CATEGORIAS_PADRAO = {
    "receita": {
        "Trabalho": ["Salário", "13º salário", "Férias", "PLR / bônus", "Pró-labore", "Freelance / autônomo"],
        "Aluguéis": ["Aluguel recebido"],
        "Benefícios": ["Aposentadoria / pensão", "Auxílios"],
        "Eventuais": ["Restituição do IR", "Venda de bens", "Presentes", "Estornos e reembolsos", "Outras receitas"],
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
        "Pessoais": ["Roupas", "Beleza / cuidados", "Presentes", "Compras (lojas e internet)"],
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
    colunas = {r["name"] for r in conn.execute("PRAGMA table_info(fin_lancamentos)")}
    for coluna, definicao in (("cartao_id", "INTEGER REFERENCES fin_cartoes(id) ON DELETE SET NULL"),
                              ("chave_import", "TEXT"), ("compartilhado", "INTEGER NOT NULL DEFAULT 0"),
                              ("conferido_em", "TEXT"),  # compra lançada à mão conferida com a fatura (data)
                              ("nota_id", "INTEGER REFERENCES fin_notas(id) ON DELETE SET NULL")):  # veio de uma NFC-e
        if coluna not in colunas:
            conn.execute(f"ALTER TABLE fin_lancamentos ADD COLUMN {coluna} {definicao}")
    if "compartilhado" not in {r["name"] for r in conn.execute("PRAGMA table_info(fin_recorrencias)")}:
        conn.execute("ALTER TABLE fin_recorrencias ADD COLUMN compartilhado INTEGER NOT NULL DEFAULT 0")
    conn.execute("CREATE INDEX IF NOT EXISTS fin_lanc_chave ON fin_lancamentos (carteira_id, chave_import)")
    # categorias padrão (as que faltarem; novas versões podem trazer categorias novas)
    for tipo, grupos in CATEGORIAS_PADRAO.items():
        for g_i, (grupo, nomes) in enumerate(grupos.items()):
            for n_i, nome in enumerate(nomes):
                conn.execute("INSERT OR IGNORE INTO fin_categorias (tipo, grupo, nome, ordem) VALUES (?, ?, ?, ?)",
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
                   forma, pago, recorrencia_id, compartilhado) VALUES (?,?,?,?,?,?,?,?,0,?,?)""",
                (r["carteira_id"], r["tipo"], data_no_mes(mes, r["dia"]), r["descricao"], r["categoria_id"],
                 r["valor"], r["valor_bruto"], r["forma"], r["id"], r.get("compartilhado") or 0))
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
                        "compartilhado": r.get("compartilhado") or 0, "cartao_id": None,
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


# ================================================================== fase 3: família / casal

MODOS_FAMILIA = {
    "proporcional": "Proporcional à renda: cada um paga as contas da família na proporção do que ganha",
    "meio": "Meio a meio: as contas da família são divididas igualmente",
    "personalizado": "Personalizado: percentuais definidos por vocês",
    "junto": "Tudo junto: a renda é somada e as contas saem do caixa comum (sem acerto)",
}


def acerto_familia(pessoas, modo="proporcional", pesos_manuais=None):
    """Divisão das contas da família no mês e quem transfere para quem.

    pessoas: [{id, nome, renda, pagou}] — renda líquida do mês e quanto cada um pagou de contas da família.
    Retorna {pessoas: [... + peso, cota, saldo], transferencias: [{de, para, valor}], total}.
    """
    total = sum(p["pagou"] for p in pessoas)
    n = len(pessoas) or 1
    if modo == "proporcional":
        renda = sum(max(p["renda"], 0) for p in pessoas)
        pesos = {p["id"]: (max(p["renda"], 0) / renda if renda > 0 else 1 / n) for p in pessoas}
    elif modo == "personalizado" and pesos_manuais:
        soma = sum(float(pesos_manuais.get(str(p["id"]), 0) or 0) for p in pessoas)
        pesos = {p["id"]: (float(pesos_manuais.get(str(p["id"]), 0) or 0) / soma if soma > 0 else 1 / n) for p in pessoas}
    else:
        pesos = {p["id"]: 1 / n for p in pessoas}
    saida = []
    for p in pessoas:
        cota = total * pesos[p["id"]] if modo != "junto" else p["pagou"]
        saida.append({**p, "peso": pesos[p["id"]] * 100, "cota": cota, "saldo": p["pagou"] - cota})
    transferencias = []
    if modo != "junto":
        devedores = sorted(([p["nome"], -p["saldo"]] for p in saida if p["saldo"] < -0.005), key=lambda x: -x[1])
        credores = sorted(([p["nome"], p["saldo"]] for p in saida if p["saldo"] > 0.005), key=lambda x: -x[1])
        i = j = 0
        while i < len(devedores) and j < len(credores):
            v = min(devedores[i][1], credores[j][1])
            transferencias.append({"de": devedores[i][0], "para": credores[j][0], "valor": round(v, 2)})
            devedores[i][1] -= v
            credores[j][1] -= v
            if devedores[i][1] <= 0.005:
                i += 1
            if credores[j][1] <= 0.005:
                j += 1
    return {"pessoas": saida, "transferencias": transferencias, "total": total, "modo": modo}


# ================================================================== fase 4: objetivos

TIPOS_OBJETIVO = {
    "reserva": "Reserva de emergência",
    "aposentadoria": "Aposentadoria / independência financeira",
    "renda_passiva": "Renda passiva",
    "patrimonio": "Patrimônio",
    "imovel": "Imóvel",
    "carro": "Carro",
    "educacao": "Educação dos filhos",
    "viagem": "Viagem",
    "divida": "Quitar dívida",
    "outro": "Outro objetivo",
}
TAXA_RETIRADA = 0.04   # regra dos 4%: 25 vezes a renda anual desejada
RENDIMENTO_RENDA = 0.06  # renda passiva: rendimento anual médio da carteira de renda (dividendos, FIIs)


def meses_ate(hoje_iso, data_iso):
    h, d = dt.date.fromisoformat(hoje_iso), dt.date.fromisoformat(data_iso)
    return max((d.year - h.year) * 12 + d.month - h.month, 0)


def taxa_mensal(anual_pct):
    return (1 + anual_pct / 100) ** (1 / 12) - 1


def aporte_necessario(alvo, atual, meses, r):
    """Aporte mensal constante para ir de `atual` a `alvo` em `meses`, rendendo `r` ao mês."""
    if atual >= alvo:
        return 0.0
    if meses <= 0:
        return alvo - atual
    cresc = (1 + r) ** meses
    if r == 0:
        return (alvo - atual) / meses
    return max((alvo - atual * cresc) * r / (cresc - 1), 0.0)


def meses_para_atingir(alvo, atual, aporte, r, limite=1200):
    """Quantos meses até atingir o alvo com o aporte mensal (None se não chega em 100 anos)."""
    v, m = atual, 0
    while v < alvo:
        if m >= limite:
            return None
        v = v * (1 + r) + aporte
        m += 1
    return m


def avaliar_objetivo(o, valor_ativos, custo_vida, hoje):
    """Valor-alvo, quanto já tem, aporte mensal necessário, previsão e situação de um objetivo.

    Valores em reais de hoje: a rentabilidade é a real (acima da inflação).
    """
    tipo = o["tipo"]
    alvo, data_alvo = o.get("valor_alvo"), o.get("data_alvo")
    explicacao = None
    if tipo == "reserva" and not alvo and custo_vida:
        meses_res = o.get("meses_reserva") or 6
        alvo = custo_vida * meses_res
        explicacao = f"{meses_res} meses do custo de vida médio"
    if tipo == "aposentadoria" and o.get("renda_desejada"):
        alvo = alvo or o["renda_desejada"] * 12 / TAXA_RETIRADA
        explicacao = explicacao or "25 vezes a renda anual desejada (regra dos 4%)"
        if not data_alvo and o.get("idade_atual") and o.get("idade_alvo"):
            anos = max(int(o["idade_alvo"]) - int(o["idade_atual"]), 0)
            h = dt.date.fromisoformat(hoje)
            data_alvo = dt.date(h.year + anos, h.month, 1).isoformat()
    if tipo == "renda_passiva" and o.get("renda_desejada"):
        alvo = alvo or o["renda_desejada"] * 12 / RENDIMENTO_RENDA
        explicacao = explicacao or f"patrimônio que rende {RENDIMENTO_RENDA * 100:.0f}% ao ano em proventos"
    if not data_alvo:
        data_alvo = dt.date.fromisoformat(somar_meses(hoje[:7], 12) + "-01").isoformat()
    tickers = [t for t in (o.get("tickers") or "").split(",") if t]
    em_ativos = sum(valor_ativos.get(t, 0.0) for t in tickers)
    atual = float(o.get("valor_guardado") or 0) + em_ativos
    alvo = float(alvo or 0)
    r = taxa_mensal(float(o.get("rentabilidade") or 0))
    meses = meses_ate(hoje, data_alvo)
    necessario = aporte_necessario(alvo, atual, meses, r) if alvo else None
    planejado = float(o.get("aporte_mensal") or 0)
    previsto = meses_para_atingir(alvo, atual, planejado, r) if alvo else None
    if not alvo:
        situacao = "incompleto"
    elif atual >= alvo:
        situacao = "atingido"
    elif necessario is not None and planejado >= necessario - 0.01:
        situacao = "no_ritmo"
    elif necessario and planejado >= necessario * 0.6:
        situacao = "atrasado"
    else:
        situacao = "em_risco"
    data_prevista = None
    if previsto is not None:
        data_prevista = somar_meses(hoje[:7], previsto) + "-01"
    return {**o, "tickers": tickers, "valor_alvo_calc": alvo, "data_alvo_calc": data_alvo, "explicacao": explicacao,
            "valor_atual": atual, "em_ativos": em_ativos, "progresso": min(atual / alvo * 100, 100) if alvo else 0,
            "meses": meses, "taxa_mensal": r, "aporte_necessario": necessario, "aporte_planejado": planejado,
            "meses_previstos": previsto, "data_prevista": data_prevista, "situacao": situacao,
            "rotulo_tipo": TIPOS_OBJETIVO.get(tipo, tipo)}


# ================================================================== fase 5: orçamento, projeção e IR

# Categorias que costumam ser dedutíveis na declaração completa do IR (conferir as regras do ano).
DEDUTIVEIS_IR = {"Plano de saúde": "Saúde", "Consultas / exames": "Saúde", "Escola / faculdade": "Educação"}


def situacao_orcamento(limite, gasto, fracao_mes=None):
    pct = gasto / limite * 100 if limite else None
    projecao = gasto / fracao_mes if fracao_mes and fracao_mes > 0 else None
    estado = "sem_limite" if not limite else "estourado" if gasto > limite else "atencao" if pct >= 80 else "ok"
    return {"limite": limite, "gasto": gasto, "pct": pct, "estado": estado, "projecao_mes": projecao}


PARENTESCOS = {"titular": "Titular", "conjuge": "Cônjuge / companheiro(a)", "filho": "Filho(a)",
               "pai_mae": "Pai / mãe", "outro": "Outro"}
