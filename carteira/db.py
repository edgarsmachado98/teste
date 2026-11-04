"""Camada de persistência (SQLite)."""
import os
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS ativos (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker       TEXT NOT NULL UNIQUE,
    nome         TEXT,
    classe       TEXT NOT NULL DEFAULT 'acao',
    meta_pct     REAL NOT NULL DEFAULT 0,
    preco_manual REAL
);

CREATE TABLE IF NOT EXISTS aportes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
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

CREATE TABLE IF NOT EXISTS precos_meta (
    ticker      TEXT PRIMARY KEY,
    atualizado  TEXT NOT NULL,
    fonte       TEXT NOT NULL
);
"""


def connect(path=None):
    path = path or os.environ.get("CARTEIRA_DB", "carteira.db")
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def rows(cursor):
    return [dict(r) for r in cursor.fetchall()]
