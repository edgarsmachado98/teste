"""Uso do sistema (CPU, memória, disco) e alertas quando os limites da guia Parâmetros são
ultrapassados por um tempo contínuo."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from .config import settings

log = logging.getLogger("vigia.usage")

try:
    import psutil
except ImportError:  # sem psutil: só disco
    psutil = None

_lock = threading.Lock()
_sizes = {"evidence_bytes": None, "database_bytes": None, "measured_at": None}
_over_since: dict[str, float] = {}
_alerted: set[str] = set()


def _folder_size(path: Path) -> int:
    total = 0
    for root, _, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def measure_sizes() -> None:
    """Tamanho das evidências e do banco (custa varrer a pasta: feito a cada 10 min)."""
    evidence = Path(settings.evidence_dir)
    db_size = None
    if settings.database_url.startswith("sqlite:///"):
        db_file = Path(settings.database_url.removeprefix("sqlite:///"))
        db_size = db_file.stat().st_size if db_file.exists() else 0
    with _lock:
        _sizes.update(evidence_bytes=_folder_size(evidence) if evidence.exists() else 0,
                      database_bytes=db_size, measured_at=datetime.now(timezone.utc))


def snapshot() -> dict:
    evidence = Path(settings.evidence_dir)
    target = evidence if evidence.exists() else Path(".")
    disk = shutil.disk_usage(target)
    data = {
        "cpu_percent": None,
        "memory_percent": None,
        "memory_total": None,
        "disk_percent": round(disk.used / disk.total * 100, 1),
        "disk_total": disk.total,
        "disk_free": disk.free,
        "cpu_count": os.cpu_count(),
        "process_memory": None,
        **_sizes,
        "limits": {"cpu": settings.usage_alert_cpu, "memory": settings.usage_alert_memory,
                   "disk": settings.usage_alert_disk, "minutes": settings.usage_alert_minutes},
        "alerts": sorted(_alerted),
    }
    if psutil:
        mem = psutil.virtual_memory()
        data.update(cpu_percent=psutil.cpu_percent(interval=0.3), memory_percent=mem.percent, memory_total=mem.total)
        try:
            data["process_memory"] = sum(p.memory_info().rss for p in [psutil.Process(), *psutil.Process().children(True)])
        except psutil.Error:
            pass
    try:
        from . import storage

        if storage.enabled() and storage.status()["total_bytes"]:
            st = storage.status()
            data["nas_percent"] = round((1 - st["free_bytes"] / st["total_bytes"]) * 100, 1)
    except Exception:
        pass
    return data


LABELS = {"cpu": "uso de CPU", "memory": "uso de memória", "disk": "uso do disco"}


def evaluate(data: dict, now: float) -> list[tuple[str, bool, float]]:
    """Devolve mudanças de estado: (métrica, em_alerta, valor)."""
    changes = []
    for metric, key in (("cpu", "cpu_percent"), ("memory", "memory_percent"), ("disk", "disk_percent")):
        value = data.get(key)
        if value is None:
            continue
        limit = getattr(settings, f"usage_alert_{metric}")
        if value >= limit:
            _over_since.setdefault(metric, now)
            if metric not in _alerted and now - _over_since[metric] >= settings.usage_alert_minutes * 60:
                _alerted.add(metric)
                changes.append((metric, True, value))
        else:
            _over_since.pop(metric, None)
            if metric in _alerted and value < limit - 5:  # histerese: evita alertas repetidos na borda
                _alerted.discard(metric)
                changes.append((metric, False, value))
    return changes


async def usage_loop() -> None:
    from . import notifier
    from .ws import hub

    last_sizes = 0.0
    while True:
        try:
            if time.monotonic() - last_sizes > 600:
                await asyncio.to_thread(measure_sizes)
                last_sizes = time.monotonic()
            data = await asyncio.to_thread(snapshot)
            for metric, alerting, value in evaluate(data, time.monotonic()):
                label = LABELS[metric]
                limit = getattr(settings, f"usage_alert_{metric}")
                text = (f"⚠️ VigIA – {label} em {value:.0f}% (limite {limit}%) há mais de "
                        f"{settings.usage_alert_minutes} min." if alerting
                        else f"✅ VigIA – {label} normalizado ({value:.0f}%).")
                if alerting and metric == "disk":
                    text += " Libere espaço ou reduza a retenção de imagens na guia Parâmetros."
                await hub.broadcast({"kind": "usage_alert", "metric": metric, "alerting": alerting, "text": text})
                await asyncio.to_thread(notifier._safely, notifier.send_mail, settings.email_recipients,
                                        f"[VigIA] {label.capitalize()} {'acima do limite' if alerting else 'normalizado'}",
                                        text)
                log.warning(text)
        except Exception:
            log.exception("falha ao medir o uso do sistema")
        await asyncio.sleep(30)
