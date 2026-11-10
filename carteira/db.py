"""Camada de persistência (SQLite)."""
import os
import sqlite3
import threading

SCHEMA = """
CREATE TABLE IF NOT EXISTS usuarios (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    email      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    nome       TEXT NOT NULL,
    senha_hash TEXT NOT NULL,
    admin      INTEGER NOT NULL DEFAULT 0,
    ativo      INTEGER NOT NULL DEFAULT 1,
    criado_em  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS carteiras (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    nome      TEXT NOT NULL,
    dono_id   INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    criada_em TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Permissões de um usuário sobre uma carteira (o dono e os administradores têm todas).
CREATE TABLE IF NOT EXISTS acessos (
    carteira_id    INTEGER NOT NULL REFERENCES carteiras(id) ON DELETE CASCADE,
    usuario_id     INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    pode_ver       INTEGER NOT NULL DEFAULT 1,
    pode_editar    INTEGER NOT NULL DEFAULT 0,
    pode_gerenciar INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (carteira_id, usuario_id)
);

CREATE TABLE IF NOT EXISTS ativos (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    carteira_id  INTEGER NOT NULL DEFAULT 1 REFERENCES carteiras(id) ON DELETE CASCADE,
    ticker       TEXT NOT NULL,
    nome         TEXT,
    classe       TEXT NOT NULL DEFAULT 'acao',
    meta_pct     REAL NOT NULL DEFAULT 0,
    preco_manual REAL,
    UNIQUE (carteira_id, ticker)
);

CREATE TABLE IF NOT EXISTS aportes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    carteira_id INTEGER NOT NULL DEFAULT 1 REFERENCES carteiras(id) ON DELETE CASCADE,
    data       TEXT NOT NULL,
    ticker     TEXT NOT NULL,
    tipo       TEXT NOT NULL DEFAULT 'compra' CHECK (tipo IN ('compra', 'venda')),
    quantidade REAL NOT NULL CHECK (quantidade > 0),
    preco      REAL NOT NULL CHECK (preco >= 0),
    taxas      REAL NOT NULL DEFAULT 0,
    obs        TEXT
);

CREATE TABLE IF NOT EXISTS precos (
    ticker     TEXT NOT NULL,
    data       TEXT NOT NULL,
    fechamento REAL NOT NULL,
    fonte      TEXT NOT NULL DEFAULT 'yahoo',
    PRIMARY KEY (ticker, data)
);

CREATE TABLE IF NOT EXISTS proventos (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    carteira_id    INTEGER NOT NULL DEFAULT 1 REFERENCES carteiras(id) ON DELETE CASCADE,
    ticker         TEXT NOT NULL,
    tipo           TEXT NOT NULL DEFAULT 'dividendo'
                   CHECK (tipo IN ('dividendo', 'jcp', 'rendimento', 'amortizacao', 'outro')),
    data_com       TEXT,
    data_pagamento TEXT NOT NULL,
    quantidade     REAL,
    valor_unitario REAL,
    valor_total    REAL NOT NULL CHECK (valor_total >= 0),
    obs            TEXT
);

-- Cache de respostas das fontes (proventos por ação, fundamentos) em JSON.
CREATE TABLE IF NOT EXISTS cache_dados (
    ticker     TEXT NOT NULL,
    tipo       TEXT NOT NULL,
    atualizado TEXT NOT NULL,
    fonte      TEXT NOT NULL,
    conteudo   TEXT NOT NULL,
    PRIMARY KEY (ticker, tipo)
);

CREATE TABLE IF NOT EXISTS precos_meta (
    ticker      TEXT PRIMARY KEY,
    atualizado  TEXT NOT NULL,
    fonte       TEXT NOT NULL
);
"""


INDICES = """
CREATE INDEX IF NOT EXISTS idx_aportes_carteira ON aportes (carteira_id, data);
CREATE INDEX IF NOT EXISTS idx_proventos_carteira ON proventos (carteira_id, data_pagamento);
CREATE INDEX IF NOT EXISTS idx_acessos_usuario ON acessos (usuario_id);
"""


def _colunas(conn, tabela):
    return {r[1] for r in conn.execute(f"PRAGMA table_info({tabela})")}


def migrar(conn):
    """Atualiza bancos criados antes do controle de acesso.

    Os dados existentes passam a pertencer à carteira 1 ("Carteira principal"), sem dono;
    na configuração inicial ela é atribuída ao primeiro administrador.
    """
    precisa = any("carteira_id" not in _colunas(conn, t) for t in ("ativos", "aportes", "proventos"))
    if not precisa:
        return
    conn.execute("PRAGMA foreign_keys = OFF")
    with conn:
        if not conn.execute("SELECT 1 FROM carteiras WHERE id = 1").fetchone():
            conn.execute("INSERT INTO carteiras (id, nome) VALUES (1, 'Carteira principal')")
        if "carteira_id" not in _colunas(conn, "ativos"):
            # ticker deixou de ser único globalmente: recria a tabela.
            conn.execute("ALTER TABLE ativos RENAME TO ativos_antigo")
            conn.execute("""CREATE TABLE ativos (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                carteira_id  INTEGER NOT NULL DEFAULT 1 REFERENCES carteiras(id) ON DELETE CASCADE,
                ticker       TEXT NOT NULL,
                nome         TEXT,
                classe       TEXT NOT NULL DEFAULT 'acao',
                meta_pct     REAL NOT NULL DEFAULT 0,
                preco_manual REAL,
                UNIQUE (carteira_id, ticker))""")
            conn.execute("""INSERT INTO ativos (id, carteira_id, ticker, nome, classe, meta_pct, preco_manual)
                            SELECT id, 1, ticker, nome, classe, meta_pct, preco_manual FROM ativos_antigo""")
            conn.execute("DROP TABLE ativos_antigo")
        for tabela in ("aportes", "proventos"):
            if "carteira_id" not in _colunas(conn, tabela):
                conn.execute(f"ALTER TABLE {tabela} ADD COLUMN carteira_id INTEGER NOT NULL DEFAULT 1 "
                             "REFERENCES carteiras(id) ON DELETE CASCADE")
    conn.execute("PRAGMA foreign_keys = ON")


def _abrir(path):
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


class Conexao:
    """Uma conexão SQLite por thread.

    O servidor atende requisições em paralelo, e uma conexão sqlite3 não pode ser
    usada por várias threads ao mesmo tempo (as consultas se misturam).
    """

    def __init__(self, path):
        self.path = path
        self._local = threading.local()

    def _conn(self):
        c = getattr(self._local, "conn", None)
        if c is None:
            c = self._local.conn = _abrir(self.path)
        return c

    def execute(self, *a):
        return self._conn().execute(*a)

    def executemany(self, *a):
        return self._conn().executemany(*a)

    def executescript(self, *a):
        return self._conn().executescript(*a)

    def commit(self):
        self._conn().commit()

    def rollback(self):
        self._conn().rollback()

    def close(self):
        """Fecha a conexão da thread atual (chamado ao fim de cada requisição)."""
        c = getattr(self._local, "conn", None)
        if c is not None:
            c.close()
            self._local.conn = None


# Colunas acrescentadas depois da criação das tabelas: (tabela, coluna, definição).
COLUNAS_NOVAS = [
    # Renda fixa: como calcular o valor atual do título
    ("ativos", "indexador", "TEXT"),            # cdi | selic | ipca | pre | tesouro | NULL (manual/mercado)
    ("ativos", "taxa", "REAL"),                 # % do CDI/Selic, taxa real (IPCA+) ou taxa prefixada, ao ano
    ("ativos", "vencimento", "TEXT"),
    ("ativos", "isento_ir", "INTEGER NOT NULL DEFAULT 0"),  # LCI, LCA, CRI, CRA, debêntures incentivadas
]


def adicionar_colunas(conn):
    for tabela, coluna, definicao in COLUNAS_NOVAS:
        if coluna not in _colunas(conn, tabela):
            conn.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {definicao}")


def connect(path=None):
    path = path or os.environ.get("CARTEIRA_DB", "carteira.db")
    inicial = _abrir(path)
    inicial.execute("PRAGMA foreign_keys = OFF")
    inicial.executescript(SCHEMA)
    migrar(inicial)
    adicionar_colunas(inicial)
    inicial.executescript(INDICES)
    inicial.execute("PRAGMA journal_mode = WAL")  # leituras não bloqueiam escritas
    inicial.commit()
    inicial.close()
    return Conexao(path)


def rows(cursor):
    return [dict(r) for r in cursor.fetchall()]
