/* Banco de dados SQLite (módulo node:sqlite, embutido no Node 22.13+). */
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { DatabaseSync } = require('node:sqlite');

const ESQUEMA = `
CREATE TABLE IF NOT EXISTS usuarios (
  id            TEXT PRIMARY KEY,
  nome          TEXT NOT NULL,
  login         TEXT NOT NULL UNIQUE,
  perfil        TEXT NOT NULL CHECK (perfil IN ('admin', 'operador', 'consulta')),
  ativo         INTEGER NOT NULL DEFAULT 1,
  senha_hash    TEXT NOT NULL,
  tentativas    INTEGER NOT NULL DEFAULT 0,
  bloqueado_ate INTEGER NOT NULL DEFAULT 0,
  criado_em     TEXT NOT NULL,
  ultimo_acesso TEXT
);

CREATE TABLE IF NOT EXISTS sessoes (
  token_hash TEXT PRIMARY KEY,
  usuario_id TEXT NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
  criada_em  INTEGER NOT NULL,
  expira_em  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS setores (
  id                 TEXT PRIMARY KEY,
  nome               TEXT NOT NULL UNIQUE COLLATE NOCASE,
  minimo_por_dia     INTEGER NOT NULL DEFAULT 0,
  dias_funcionamento TEXT NOT NULL,
  funciona_feriados  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS colaboradores (
  id        TEXT PRIMARY KEY,
  nome      TEXT NOT NULL,
  matricula TEXT NOT NULL UNIQUE,
  sexo      TEXT NOT NULL CHECK (sexo IN ('F', 'M')),
  setor_id  TEXT NOT NULL REFERENCES setores(id),
  jornada   TEXT NOT NULL,
  entrada   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS feriados (
  data TEXT PRIMARY KEY,
  nome TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS configuracoes (
  chave TEXT PRIMARY KEY,
  valor TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS escala (
  id            INTEGER PRIMARY KEY CHECK (id = 1),
  inicio        TEXT NOT NULL,
  fim           TEXT NOT NULL,
  dados         TEXT NOT NULL,
  gerada_por    TEXT,
  gerada_em     TEXT NOT NULL,
  atualizada_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS auditoria (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  em            TEXT NOT NULL,
  usuario_id    TEXT,
  usuario_login TEXT,
  acao          TEXT NOT NULL,
  detalhe       TEXT
);

CREATE TABLE IF NOT EXISTS contratos_representante (
  id            TEXT PRIMARY KEY,
  razao_social  TEXT NOT NULL,
  cnpj          TEXT NOT NULL,
  situacao      TEXT NOT NULL DEFAULT 'ativo' CHECK (situacao IN ('ativo', 'encerrado')),
  dados         TEXT NOT NULL,
  criado_por    TEXT,
  criado_em     TEXT NOT NULL,
  atualizado_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS indices (
  serie         TEXT NOT NULL,
  mes           TEXT NOT NULL,
  valor         REAL NOT NULL,
  fonte         TEXT NOT NULL DEFAULT 'manual',
  atualizado_em TEXT NOT NULL,
  PRIMARY KEY (serie, mes)
);

CREATE TABLE IF NOT EXISTS distratos (
  id            TEXT PRIMARY KEY,
  contrato_id   TEXT NOT NULL REFERENCES contratos_representante(id),
  representada  TEXT NOT NULL CHECK (representada IN ('cia', 'alimentos')),
  data_distrato TEXT NOT NULL,
  total         REAL NOT NULL DEFAULT 0,
  dados         TEXT NOT NULL,
  criado_por    TEXT,
  criado_em     TEXT NOT NULL,
  atualizado_em TEXT NOT NULL,
  UNIQUE (contrato_id, representada)
);

CREATE INDEX IF NOT EXISTS idx_sessoes_usuario ON sessoes(usuario_id);
CREATE INDEX IF NOT EXISTS idx_contratos_cnpj ON contratos_representante(cnpj);
CREATE INDEX IF NOT EXISTS idx_colaboradores_setor ON colaboradores(setor_id);
`;

function abrirBanco(arquivo) {
  if (arquivo !== ':memory:') fs.mkdirSync(path.dirname(path.resolve(arquivo)), { recursive: true });
  const db = new DatabaseSync(arquivo);
  db.exec('PRAGMA foreign_keys = ON; PRAGMA busy_timeout = 5000;');
  if (arquivo !== ':memory:') db.exec('PRAGMA journal_mode = WAL;');
  db.exec(ESQUEMA);

  /** Executa fn dentro de uma transação; desfaz tudo se lançar erro. */
  db.transacao = (fn) => {
    db.exec('BEGIN IMMEDIATE');
    try {
      const r = fn();
      db.exec('COMMIT');
      return r;
    } catch (e) {
      db.exec('ROLLBACK');
      throw e;
    }
  };
  return db;
}

module.exports = { abrirBanco };
