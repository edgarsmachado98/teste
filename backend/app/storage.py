"""Armazenamento externo em storage de rede (NAS) para evidências, backups e relatórios.

Os arquivos de evidência são sempre gravados primeiro no disco local (a detecção não pode
esperar a rede) e depois sincronizados para o NAS por uma tarefa em segundo plano:

- modo "espelho":   o local continua completo; o NAS guarda uma cópia (redundância).
- modo "principal": o NAS é o armazenamento oficial; o local guarda só os últimos
                    STORAGE_LOCAL_DAYS dias (cache) e o painel busca o restante no NAS.

Segurança: o NAS só é usado depois de "ativado" (arquivo marcador na raiz). Se o
compartilhamento não estiver conectado, a pasta não tem o marcador e nada é gravado nela,
evitando encher o disco local achando que é o NAS.
"""

from __future__ import annotations

import logging
import os
import shutil
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, or_, select

from .config import settings
from .database import SessionLocal
from .models import Event, StorageDeletion

log = logging.getLogger("vigia.storage")

MARKER = ".vigia-storage"
EVIDENCE_DIR = Path(settings.evidence_dir)
CLIP_WAIT = timedelta(minutes=2)  # o clipe chega alguns segundos depois do evento

_lock = threading.Lock()
_state = {
    "online": False,
    "error": "",
    "last_check": None,
    "last_sync": None,
    "offline_since": None,
    "alerted": False,
    "synced_files": 0,
}


def enabled() -> bool:
    return bool(settings.storage_nas_path)


def root() -> Path:
    return Path(settings.storage_nas_path)


def _share_root(path: str) -> str | None:
    """\\\\servidor\\compartilhamento a partir de um caminho UNC."""
    if not path.startswith("\\\\"):
        return None
    parts = path.lstrip("\\").split("\\")
    return f"\\\\{parts[0]}\\{parts[1]}" if len(parts) >= 2 else None


def connect(path: str | None = None, user: str | None = None, password: str | None = None) -> None:
    """Windows: autentica no compartilhamento com usuário próprio do NAS.

    Necessário quando o VigIA roda como serviço (conta SYSTEM, sem acesso à rede).
    Usa a API do Windows em vez de 'net use' para a senha não aparecer na linha de comando."""
    path = settings.storage_nas_path if path is None else path
    user = settings.storage_nas_user if user is None else user
    password = settings.storage_nas_password if password is None else password
    share = _share_root(path)
    if os.name != "nt" or not share or not user:
        return
    import ctypes
    from ctypes import wintypes

    class NetResource(ctypes.Structure):
        _fields_ = [("dwScope", wintypes.DWORD), ("dwType", wintypes.DWORD), ("dwDisplayType", wintypes.DWORD),
                    ("dwUsage", wintypes.DWORD), ("lpLocalName", wintypes.LPWSTR), ("lpRemoteName", wintypes.LPWSTR),
                    ("lpComment", wintypes.LPWSTR), ("lpProvider", wintypes.LPWSTR)]

    resource = NetResource(dwType=1, lpRemoteName=share)  # RESOURCETYPE_DISK
    code = ctypes.WinDLL("mpr").WNetAddConnection2W(ctypes.byref(resource), password, user, 0)
    # 0 = conectado; 1219 = já existe uma conexão com o servidor (ok)
    if code not in (0, 1219):
        raise OSError(f"não foi possível conectar a {share} (código {code}); confira usuário e senha do NAS")


def check() -> bool:
    """Atualiza e devolve se o NAS está acessível e ativado."""
    if not enabled():
        return False
    try:
        connect()
        base = root()
        if not base.is_dir():
            raise OSError(f"pasta {base} não encontrada (NAS desligado ou compartilhamento não conectado)")
        if not (base / MARKER).exists():
            raise OSError("armazenamento ainda não ativado – use 'Ativar' na tela Sistema")
        probe = base / f".probe-{uuid.uuid4().hex}"
        probe.write_bytes(b"ok")
        probe.unlink()
        online, error = True, ""
    except OSError as exc:
        online, error = False, str(exc)
    with _lock:
        now = datetime.now(timezone.utc)
        if online:
            _state["offline_since"] = None
        elif _state["offline_since"] is None:
            _state["offline_since"] = now
        _state.update(online=online, error=error, last_check=now)
    return online


def reset_state() -> None:
    """Chamado quando a configuração do NAS muda."""
    with _lock:
        _state.update(online=False, error="", offline_since=None, alerted=False)
    if enabled():
        check()


def probe(path: str, user: str = "", password: str = "") -> dict:
    """Testa uma pasta de rede com os dados informados, sem salvar nada (botão 'Testar')."""
    result = {"ok": False, "exists": False, "writable": False, "activated": False,
              "free_bytes": None, "total_bytes": None, "message": ""}
    if not path:
        result["message"] = "informe o caminho da pasta de rede"
        return result
    try:
        connect(path, user, password)
        base = Path(path)
        if not base.is_dir():
            raise OSError("pasta não encontrada: confira o caminho, se o NAS está ligado e o usuário/senha")
        result["exists"] = True
        probe_file = base / f".probe-{uuid.uuid4().hex}"
        probe_file.write_bytes(b"ok")
        if probe_file.read_bytes() != b"ok":
            raise OSError("a leitura de teste não confere")
        probe_file.unlink()
        result["writable"] = True
        result["activated"] = (base / MARKER).exists()
        usage = shutil.disk_usage(base)
        result.update(free_bytes=usage.free, total_bytes=usage.total, ok=True,
                      message="conexão bem-sucedida" + ("" if result["activated"]
                                                         else " – salve e ative para começar a usar"))
    except OSError as exc:
        result["message"] = str(exc) if result["exists"] or "pasta" in str(exc) else f"sem acesso: {exc}"
        if result["exists"] and not result["writable"]:
            result["message"] = f"a pasta existe, mas não é possível gravar nela ({exc}); confira as permissões do usuário"
    return result


def activate() -> None:
    """Grava o marcador que autoriza o uso da pasta como armazenamento do VigIA."""
    if not enabled():
        raise OSError("STORAGE_NAS_PATH não configurado no .env")
    connect()
    base = root()
    if not base.is_dir():
        raise OSError(f"pasta {base} não encontrada; confira o caminho e se o NAS está ligado")
    (base / MARKER).write_text(f"VigIA – ativado em {datetime.now():%d/%m/%Y %H:%M}\n", encoding="utf-8")
    check()


def nas_path(rel: str) -> Path:
    return root() / "evidencias" / rel


def resolve(rel: str) -> Path | None:
    """Caminho do arquivo de evidência: disco local ou, se já saiu do cache, o NAS."""
    local = EVIDENCE_DIR / rel
    if local.exists():
        return local
    if enabled() and _state["online"]:
        remote = nas_path(rel)
        if remote.exists():
            return remote
    return None


def _copy_file(src: Path, dst: Path) -> None:
    """Cópia atômica: grava com nome temporário e renomeia; confere o tamanho."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() and dst.stat().st_size == src.stat().st_size:
        return
    tmp = dst.with_name(f".{dst.name}.{uuid.uuid4().hex[:8]}.tmp")
    shutil.copyfile(src, tmp)
    if tmp.stat().st_size != src.stat().st_size:
        tmp.unlink(missing_ok=True)
        raise OSError(f"cópia incompleta de {src.name}")
    os.replace(tmp, dst)


def _event_files(event: Event) -> list[str]:
    files = [event.image_file] if event.image_file else []
    if event.clip_dir:
        files += [f"{event.clip_dir}/{i:04d}.jpg" for i in range(event.clip_frames or 0)]
    return files


def _remove_rel(base: Path, rel: str) -> None:
    target = base / rel
    if target.is_dir():
        shutil.rmtree(target, ignore_errors=True)
    else:
        target.unlink(missing_ok=True)


def remove(rel: str | None, db=None) -> None:
    """Apaga um arquivo/pasta de evidência do disco local e do NAS (retenção/LGPD).
    Se o NAS estiver inacessível, a exclusão fica pendente e é feita quando ele voltar."""
    if not rel:
        return
    _remove_rel(EVIDENCE_DIR, rel)
    if not enabled():
        return
    if _state["online"]:
        try:
            _remove_rel(root() / "evidencias", rel)
            return
        except OSError:
            pass
    if db is not None:
        db.add(StorageDeletion(rel_path=rel))


def sync_once(now: datetime | None = None) -> dict:
    """Envia ao NAS as evidências pendentes, processa exclusões pendentes e, no modo
    principal, libera o cache local antigo. Seguro para chamar repetidamente."""
    now = now or datetime.now(timezone.utc)
    result = {"synced_events": 0, "copied_files": 0, "deleted": 0, "freed_events": 0, "online": False}
    if not check():
        return result
    result["online"] = True
    with SessionLocal() as db:
        # 1) Exclusões pendentes (LGPD) primeiro
        for pending in db.scalars(select(StorageDeletion)).all():
            _remove_rel(root() / "evidencias", pending.rel_path)
            db.delete(pending)
            result["deleted"] += 1
        db.commit()

        # 2) Evidências ainda não copiadas (espera o clipe chegar, ou desiste dele após 2 min)
        pending = db.scalars(select(Event).where(
            Event.media_synced_at.is_(None),
            or_(Event.image_file.is_not(None), Event.clip_dir.is_not(None)),
        ).order_by(Event.created_at).limit(500)).all()
        for event in pending:
            if event.clip_id and not event.clip_dir and now - event.created_at < CLIP_WAIT:
                continue
            try:
                for rel in _event_files(event):
                    src = EVIDENCE_DIR / rel
                    if src.exists():
                        _copy_file(src, nas_path(rel))
                        result["copied_files"] += 1
                event.media_synced_at = now
                result["synced_events"] += 1
                db.commit()
            except OSError as exc:
                db.rollback()
                log.warning("falha ao copiar evidências da ocorrência %s para o NAS: %s", event.id, exc)
                check()
                break

        # 3) Modo principal: remove do disco local o que já está seguro no NAS há mais de N dias
        if settings.storage_mode == "principal":
            cutoff = now - timedelta(days=max(settings.storage_local_days, 0))
            old = db.scalars(select(Event).where(Event.media_synced_at.is_not(None), Event.created_at < cutoff,
                                                 or_(Event.image_file.is_not(None), Event.clip_dir.is_not(None)))).all()
            for event in old:
                files = _event_files(event)
                if not all(nas_path(rel).exists() for rel in files):
                    event.media_synced_at = None  # algo sumiu no NAS: reenviar antes de apagar
                    continue
                local_any = False
                for rel in files:
                    if (EVIDENCE_DIR / rel).exists():
                        local_any = True
                        (EVIDENCE_DIR / rel).unlink()
                if event.clip_dir:
                    shutil.rmtree(EVIDENCE_DIR / event.clip_dir, ignore_errors=True)
                result["freed_events"] += local_any
            db.commit()

    with _lock:
        _state["last_sync"] = now
        _state["synced_files"] += result["copied_files"]
    if result["copied_files"] or result["deleted"] or result["freed_events"]:
        log.info("NAS: %(synced_events)d ocorrências enviadas (%(copied_files)d arquivos), %(deleted)d exclusões, "
                 "%(freed_events)d liberadas do disco local", result)
    return result


def copy_to_nas(src: Path, folder: str, keep: int | None = None, pattern: str = "*") -> str:
    """Copia um arquivo (backup, relatório) para uma pasta do NAS, com rotação opcional."""
    if not enabled() or not check():
        return ""
    dest_dir = root() / folder
    dest = dest_dir / src.name
    _copy_file(src, dest)
    if keep:
        for old in sorted(dest_dir.glob(pattern), reverse=True)[keep:]:
            old.unlink(missing_ok=True)
    return str(dest)


def write_to_nas(name: str, data: bytes, folder: str) -> str:
    if not enabled() or not check():
        return ""
    dest_dir = root() / folder
    dest_dir.mkdir(parents=True, exist_ok=True)
    tmp = dest_dir / f".{name}.tmp"
    tmp.write_bytes(data)
    os.replace(tmp, dest_dir / name)
    return str(dest_dir / name)


def status() -> dict:
    with SessionLocal() as db:
        pending_count = db.scalar(select(func.count()).select_from(Event).where(
            Event.media_synced_at.is_(None), or_(Event.image_file.is_not(None), Event.clip_dir.is_not(None))))
        deletions = db.scalar(select(func.count()).select_from(StorageDeletion))
    info = {
        "enabled": enabled(),
        "path": settings.storage_nas_path,
        "mode": settings.storage_mode,
        "local_days": settings.storage_local_days,
        "user": settings.storage_nas_user,
        "pending_events": pending_count,
        "pending_deletions": deletions,
        **{k: v for k, v in _state.items() if k != "alerted"},
        "activated": False,
        "total_bytes": None,
        "free_bytes": None,
    }
    if enabled() and _state["online"]:
        try:
            usage = shutil.disk_usage(root())
            info.update(activated=True, total_bytes=usage.total, free_bytes=usage.free)
        except OSError:
            pass
    elif enabled():
        try:
            info["activated"] = (root() / MARKER).exists()
        except OSError:
            pass
    return info


def offline_alert_due() -> tuple[bool, bool]:
    """(deve alertar que caiu, deve avisar que voltou) – controla para avisar uma vez só."""
    with _lock:
        since = _state["offline_since"]
        if _state["online"] and _state["alerted"]:
            _state["alerted"] = False
            return False, True
        if since and not _state["alerted"] and \
                datetime.now(timezone.utc) - since >= timedelta(minutes=settings.storage_offline_alert_minutes):
            _state["alerted"] = True
            return True, False
    return False, False


async def storage_loop() -> None:
    import asyncio

    from . import notifier
    from .ws import hub

    while True:
        if enabled():
            try:
                await asyncio.to_thread(sync_once)
            except Exception:
                log.exception("falha na sincronização com o NAS")
            went_down, came_back = offline_alert_due()
            if went_down or came_back:
                label = "acessível novamente" if came_back else f"inacessível: {_state['error']}"
                payload = {"kind": "storage_health", "online": came_back, "label": label}
                await hub.broadcast(payload)
                text = (f"{'✅' if came_back else '⚠️'} VigIA – armazenamento de rede {label}."
                        + ("" if came_back else " As evidências continuam salvas no computador e serão enviadas "
                                                "quando o NAS voltar."))
                await asyncio.to_thread(notifier._safely, notifier.send_mail, settings.email_recipients,
                                        f"[VigIA] Armazenamento de rede {'normalizado' if came_back else 'indisponível'}",
                                        text)
        await asyncio.sleep(max(settings.storage_sync_interval, 10))

