"""Backup do banco de dados (SQLite) com rotação e cópia opcional para outra pasta."""

import logging
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from .config import settings
from .timeutil import local_tz

log = logging.getLogger("vigia.backup")


def sqlite_path() -> Path | None:
    url = settings.database_url
    return Path(url.removeprefix("sqlite:///")) if url.startswith("sqlite:///") else None


def backup_dir() -> Path:
    return Path(settings.backup_dir)


def list_backups() -> list[dict]:
    folder = backup_dir()
    if not folder.exists():
        return []
    files = sorted(folder.glob("vigia-*.db"), reverse=True)
    return [{"name": f.name, "size": f.stat().st_size,
             "created_at": datetime.fromtimestamp(f.stat().st_mtime, local_tz()).isoformat()} for f in files]


def run_backup() -> dict:
    """Cópia consistente do banco (API de backup do SQLite, segura com o sistema rodando)."""
    source = sqlite_path()
    if source is None:
        raise RuntimeError("Backup automático disponível apenas para SQLite. No PostgreSQL, use pg_dump.")
    folder = backup_dir()
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"vigia-{datetime.now(local_tz()):%Y%m%d-%H%M%S}.db"
    with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
        src.backup(dst)
    copied = ""
    if settings.backup_copy_dir:
        try:
            Path(settings.backup_copy_dir).mkdir(parents=True, exist_ok=True)
            copied = str(shutil.copy2(target, settings.backup_copy_dir))
        except OSError as exc:
            log.error("backup criado, mas a cópia para %s falhou: %s", settings.backup_copy_dir, exc)
            copied = f"falhou: {exc}"
    for old in sorted(folder.glob("vigia-*.db"), reverse=True)[max(settings.backup_keep, 1):]:
        old.unlink(missing_ok=True)
    log.info("backup criado: %s", target)
    return {"name": target.name, "size": target.stat().st_size, "copy": copied}
