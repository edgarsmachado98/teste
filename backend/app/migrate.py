"""Migração simples: cria tabelas novas e adiciona colunas que faltam em tabelas existentes.

Mantém os dados de quem já usava versões anteriores. Só adiciona (nunca remove ou altera)
colunas; para mudanças mais complexas, adotar Alembic."""

import logging

from sqlalchemy import inspect, text

from .database import Base, engine

log = logging.getLogger("vigia.migrate")


def migrate() -> None:
    from . import models  # noqa: F401  (registra as tabelas em Base.metadata)

    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            existing = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing:
                    continue
                coltype = column.type.compile(dialect=engine.dialect)
                conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN "{column.name}" {coltype}'))
                log.info("migração: coluna %s.%s adicionada", table.name, column.name)
