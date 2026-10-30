"""Backup e restauração do sistema (SQLite).

O backup é um .zip com o banco de dados (cópia consistente, feita com o sistema rodando), um
manifesto e, opcionalmente, as evidências (fotos e clipes). Backups antigos em .db continuam
aceitos na restauração.

Restauração: valida o arquivo, faz antes um backup de segurança do estado atual e substitui o
conteúdo do banco em uso (API de backup do SQLite), aplicando depois a migração de esquema."""

from __future__ import annotations

import json
import logging
import re
import shutil
import sqlite3
import tempfile
import threading
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath

from .config import settings
from .timeutil import local_tz

log = logging.getLogger("vigia.backup")

NAME_RE = re.compile(r"vigia-\d{8}-\d{6}(-[a-z0-9-]+)?\.(zip|db)")
FORMAT_VERSION = 1
_lock = threading.Lock()  # um backup/restauração por vez


class BackupError(Exception):
    """Erro apresentável ao usuário."""


def sqlite_path() -> Path | None:
    url = settings.database_url
    return Path(url.removeprefix("sqlite:///")) if url.startswith("sqlite:///") else None


def backup_dir() -> Path:
    return Path(settings.backup_dir)


def evidence_dir() -> Path:
    return Path(settings.evidence_dir)


def _describe(path: Path) -> dict:
    stat = path.stat()
    info = {"name": path.name, "size": stat.st_size,
            "created_at": datetime.fromtimestamp(stat.st_mtime, local_tz()).isoformat(),
            "kind": "completo" if "-completo" in path.name else
                    "seguranca" if "-antes-restauracao" in path.name else
                    "importado" if "-importado" in path.name else "banco"}
    if path.suffix == ".zip":
        try:
            with zipfile.ZipFile(path) as zf:
                manifest = json.loads(zf.read("manifest.json"))
            info["evidence_files"] = manifest.get("evidence_files", 0)
            info["counts"] = manifest.get("counts", {})
        except (zipfile.BadZipFile, KeyError, ValueError):
            info["invalid"] = True
    return info


def list_backups() -> list[dict]:
    folder = backup_dir()
    if not folder.exists():
        return []
    files = [p for p in folder.iterdir() if NAME_RE.fullmatch(p.name)]
    return [_describe(f) for f in sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)]


def backup_path(name: str) -> Path:
    if not NAME_RE.fullmatch(name) or not (backup_dir() / name).is_file():
        raise BackupError("backup não encontrado")
    return backup_dir() / name


def _counts(db_file: Path) -> dict:
    with sqlite3.connect(db_file) as conn:
        tables = {r[0] for r in conn.execute("select name from sqlite_master where type='table'")}
        return {t: conn.execute(f"select count(*) from {t}").fetchone()[0]
                for t in ("users", "cameras", "rules", "events", "actions") if t in tables}


def _new_name(label: str = "") -> Path:
    stamp = f"{datetime.now(local_tz()):%Y%m%d-%H%M%S}"
    path = backup_dir() / f"vigia-{stamp}{'-' + label if label else ''}.zip"
    n = 1
    while path.exists():  # dois backups no mesmo segundo
        n += 1
        path = backup_dir() / f"vigia-{stamp}-{label + '-' if label else ''}{n}.zip"
    return path


def run_backup(include_evidence: bool = False, label: str = "", rotate: bool = True) -> dict:
    source = sqlite_path()
    if source is None:
        raise BackupError("Backup pelo painel disponível apenas para SQLite. No PostgreSQL, use pg_dump.")
    with _lock:
        return _run_backup(source, include_evidence, label or ("completo" if include_evidence else ""), rotate)


def _run_backup(source: Path, include_evidence: bool, label: str, rotate: bool) -> dict:
    folder = backup_dir()
    folder.mkdir(parents=True, exist_ok=True)
    target = _new_name(label)
    evidence_files = 0
    with tempfile.TemporaryDirectory() as tmp:
        snapshot = Path(tmp) / "vigia.db"
        with sqlite3.connect(source) as src, sqlite3.connect(snapshot) as dst:
            src.backup(dst)
        partial = target.with_suffix(".parcial")
        with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(snapshot, "vigia.db")
            if include_evidence and evidence_dir().exists():
                for f in sorted(evidence_dir().rglob("*")):
                    rel = f.relative_to(evidence_dir())
                    if f.is_file() and rel.parts[0] != "ao-vivo":
                        zf.write(f, f"evidencias/{rel.as_posix()}", compress_type=zipfile.ZIP_STORED)
                        evidence_files += 1
            manifest = {"format": FORMAT_VERSION, "app": "VigIA", "created_at": datetime.now(local_tz()).isoformat(),
                        "database": "sqlite", "evidence_files": evidence_files, "counts": _counts(snapshot)}
            zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        partial.replace(target)

    copied = ""
    if settings.backup_copy_dir:
        try:
            Path(settings.backup_copy_dir).mkdir(parents=True, exist_ok=True)
            copied = str(shutil.copy2(target, settings.backup_copy_dir))
        except OSError as exc:
            log.error("backup criado, mas a cópia para %s falhou: %s", settings.backup_copy_dir, exc)
            copied = f"falhou: {exc}"
    nas = ""
    try:
        from .storage import copy_to_nas

        nas = copy_to_nas(target, "backups", keep=settings.storage_backup_keep, pattern="vigia-*")
    except OSError as exc:
        log.error("backup criado, mas a cópia para o NAS falhou: %s", exc)
        nas = f"falhou: {exc}"
    if rotate:
        # a rotação não apaga backups de segurança (feitos antes de restaurações)
        rotating = [p for p in backup_dir().iterdir() if NAME_RE.fullmatch(p.name) and "-antes-restauracao" not in p.name]
        for old in sorted(rotating, key=lambda p: p.stat().st_mtime, reverse=True)[max(settings.backup_keep, 1):]:
            old.unlink(missing_ok=True)
    log.info("backup criado: %s (%d evidências)", target, evidence_files)
    return {**_describe(target), "copy": copied, "nas": nas}


def delete_backup(name: str) -> None:
    backup_path(name).unlink()


# ---------- Restauração ----------

def _safe_member(name: str) -> bool:
    p = PurePosixPath(name)
    return not p.is_absolute() and ".." not in p.parts and (
        name in ("vigia.db", "manifest.json") or (p.parts[0] == "evidencias" and len(p.parts) > 1))


def _validate_db(db_file: Path) -> dict:
    try:
        with sqlite3.connect(f"file:{db_file}?mode=ro", uri=True) as conn:
            if conn.execute("pragma integrity_check").fetchone()[0] != "ok":
                raise BackupError("o banco de dados do backup está corrompido")
            tables = {r[0] for r in conn.execute("select name from sqlite_master where type='table'")}
    except sqlite3.DatabaseError as exc:
        raise BackupError(f"o arquivo não é um banco de dados do VigIA válido ({exc})") from None
    if not {"cameras", "events"} <= tables:
        raise BackupError("o arquivo não é um backup do VigIA (tabelas não encontradas)")
    counts = _counts(db_file)
    if "users" in tables and counts.get("users", 0) == 0:
        raise BackupError("o backup não tem nenhum usuário; ninguém conseguiria entrar após a restauração")
    return counts


def inspect_file(path: Path, workdir: Path) -> tuple[Path, zipfile.ZipFile | None, dict]:
    """Extrai e valida o banco do backup. Devolve (banco, zip ou None, contagens)."""
    if path.suffix == ".db":
        db_file = workdir / "vigia.db"
        shutil.copyfile(path, db_file)
        return db_file, None, _validate_db(db_file)
    try:
        zf = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        raise BackupError("arquivo .zip inválido ou corrompido") from None
    names = zf.namelist()
    if "vigia.db" not in names:
        zf.close()
        raise BackupError("o .zip não contém o banco de dados do VigIA (vigia.db)")
    unsafe = [n for n in names if not _safe_member(n)]
    if unsafe:
        zf.close()
        raise BackupError(f"o .zip contém caminhos não permitidos (ex.: {unsafe[0]})")
    if zf.testzip() is not None:
        zf.close()
        raise BackupError("o .zip está corrompido")
    db_file = workdir / "vigia.db"
    with zf.open("vigia.db") as src, open(db_file, "wb") as dst:
        shutil.copyfileobj(src, dst)
    return db_file, zf, _validate_db(db_file)


def restore(path: Path) -> dict:
    target = sqlite_path()
    if target is None:
        raise BackupError("Restauração pelo painel disponível apenas para SQLite.")
    from .database import engine
    from .migrate import migrate

    with _lock, tempfile.TemporaryDirectory() as tmp:
        db_file, zf, counts = inspect_file(path, Path(tmp))
        try:
            safety = _run_backup(target, include_evidence=False, label="antes-restauracao", rotate=False)
            engine.dispose()  # fecha as conexões abertas do sistema
            with sqlite3.connect(db_file) as src, sqlite3.connect(target, timeout=30) as dst:
                src.backup(dst)
            engine.dispose()
            migrate()  # backup de versão anterior: acrescenta as colunas novas

            restored_files = 0
            if zf is not None:
                for name in zf.namelist():
                    if name.startswith("evidencias/") and not name.endswith("/"):
                        dest = evidence_dir() / PurePosixPath(name).relative_to("evidencias")
                        if not dest.exists():
                            dest.parent.mkdir(parents=True, exist_ok=True)
                            with zf.open(name) as src_f, open(dest, "wb") as dst_f:
                                shutil.copyfileobj(src_f, dst_f)
                            restored_files += 1
        finally:
            if zf is not None:
                zf.close()

    from .settings_store import apply_overrides

    warnings = apply_overrides()  # configurações do painel que vieram no backup
    log.warning("sistema restaurado a partir de %s (backup de segurança: %s)", path.name, safety["name"])
    return {"restored_from": path.name, "counts": counts, "evidence_files": restored_files,
            "safety_backup": safety["name"], "warnings": warnings}
