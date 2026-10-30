"""Dimensionamento de recursos conforme a retenção de dados.

- plan():    estimativa para uma implantação (pré-venda), a partir de premissas editáveis.
- measure(): dados reais da instalação (tamanho médio das ocorrências, ocorrências por dia).
- project(): projeção do uso de disco com a retenção atual e retenção máxima que cabe.

Os números são estimativas para orientar a compra; valide com um piloto e, depois dele,
use os valores medidos (measure) como premissas."""

from __future__ import annotations

import math
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import settings
from .models import Camera, Event, RuleStat

MIN_DAYS = 3        # amostra mínima para projetar com dados reais
MIN_EVENTS = 20

MB = 1024**2
GB = 1024**3
TB = 1024**4

DISK_SIZES_TB = [2, 4, 6, 8, 12, 16, 20, 24]  # tamanhos comuns de discos para NAS
NAS_BAYS = [2, 4, 6, 8, 12]
SSD_SIZES_GB = [256, 512, 1024, 2048, 4096]

# Capacidade aproximada de inferência (quadros/s) do modelo YOLO nano a 640 px, por classe de
# hardware. Modelos maiores (s/m) e vários modelos em paralelo dividem esse número.
HARDWARE = [
    {"id": "cpu", "label": "Somente CPU (8 núcleos, sem GPU)", "fps": 15},
    {"id": "jetson", "label": "NVIDIA Jetson Orin Nano (borda)", "fps": 60},
    {"id": "gpu_entrada", "label": "GPU de entrada (RTX 3050 / GTX 1660)", "fps": 150},
    {"id": "gpu_media", "label": "GPU intermediária (RTX 3060 / 4060)", "fps": 300},
    {"id": "gpu_alta", "label": "GPU alta (RTX 4070 ou superior)", "fps": 600},
]
MODEL_FACTOR = {"n": 1.0, "s": 2.2, "m": 5.0}


@dataclass
class PlanInput:
    cameras: int = 16
    events_per_camera_day: float = 20
    retention_days: int = 30            # fotos e clipes
    event_retention_days: int = 730     # registros sem imagem
    clip_before: float = 5
    clip_after: float = 5
    analysis_fps: float = 3
    models: int = 2                     # ex.: pessoas + EPI
    model_size: str = "n"               # n | s | m
    frame_kb: float = 60                # quadro do clipe (JPEG 800 px)
    snapshot_kb: float = 180            # foto da ocorrência (JPEG 1280 px)
    stream_mbps: float = 2.0            # fluxo de cada câmera lido pelo detector (sub-stream)
    storage_mode: str = "espelho"       # sem_nas | espelho | principal
    local_days: int = 7                 # modo principal: dias no disco local
    raid: str = "raid6"                 # raid1 | raid5 | raid6 | raid10
    headroom: float = 0.3               # folga desejada (30% livre)
    backup_keep: int = 14
    nas_backup_keep: int = 60
    continuous: bool = False            # dimensionar também a gravação contínua (NVR)
    continuous_mbps: float = 4.0        # por câmera, fluxo principal
    continuous_days: int = 30
    continuous_codec: str = "h265"      # h264 | h265

    @classmethod
    def from_dict(cls, data: dict) -> "PlanInput":
        known = {f: data[f] for f in cls.__dataclass_fields__ if f in data and data[f] not in (None, "")}
        obj = cls(**known)
        obj.validate()
        return obj

    def validate(self) -> None:
        checks = [
            (1 <= self.cameras <= 2000, "câmeras: entre 1 e 2000"),
            (0 <= self.events_per_camera_day <= 5000, "ocorrências por câmera/dia: entre 0 e 5000"),
            (1 <= self.retention_days <= 3650, "retenção de imagens: entre 1 e 3650 dias"),
            (1 <= self.event_retention_days <= 7300, "retenção dos registros: entre 1 e 7300 dias"),
            (0 <= self.clip_before <= 30 and 0 <= self.clip_after <= 30, "clipe: até 30 s antes e depois"),
            (0.5 <= self.analysis_fps <= 30, "análise: entre 0,5 e 30 quadros/s"),
            (1 <= self.models <= 5, "modelos: entre 1 e 5"),
            (self.model_size in MODEL_FACTOR, "tamanho do modelo: n, s ou m"),
            (1 <= self.frame_kb <= 2000 and 1 <= self.snapshot_kb <= 5000, "tamanho de imagem inválido"),
            (0.1 <= self.stream_mbps <= 50, "fluxo da câmera: entre 0,1 e 50 Mbps"),
            (self.storage_mode in ("sem_nas", "espelho", "principal"), "modo: sem_nas, espelho ou principal"),
            (1 <= self.local_days <= 3650, "dias locais: entre 1 e 3650"),
            (self.raid in ("raid1", "raid5", "raid6", "raid10"), "RAID: raid1, raid5, raid6 ou raid10"),
            (0 <= self.headroom <= 0.8, "folga: entre 0% e 80%"),
            (0.5 <= self.continuous_mbps <= 50 and 1 <= self.continuous_days <= 3650, "gravação contínua inválida"),
            (self.continuous_codec in ("h264", "h265"), "codec: h264 ou h265"),
        ]
        for ok, message in checks:
            if not ok:
                raise ValueError(message)


@dataclass
class Item:
    label: str
    bytes: float
    note: str = ""


@dataclass
class PlanResult:
    per_event_bytes: float
    events_per_day: float
    daily_bytes: float
    local_items: list[Item] = field(default_factory=list)
    nas_items: list[Item] = field(default_factory=list)
    local_total: float = 0
    nas_total: float = 0
    local_recommended: dict = field(default_factory=dict)
    nas_recommended: dict | None = None
    compute: dict = field(default_factory=dict)
    network: dict = field(default_factory=dict)
    continuous: dict | None = None
    warnings: list[str] = field(default_factory=list)


def _db_bytes(events_per_day: float, event_retention_days: int, ppe_rules: int) -> float:
    """Banco: ~3 KB por ocorrência (com índices e histórico) + 1 linha/hora por regra de EPI."""
    events = events_per_day * event_retention_days
    stats = ppe_rules * 24 * min(event_retention_days, 3650) * 120
    return events * 3 * 1024 + stats + 20 * MB


def raid_usable(raw_disks: int, disk_bytes: float, raid: str) -> float:
    data_disks = {"raid1": raw_disks / 2, "raid10": raw_disks / 2, "raid5": raw_disks - 1, "raid6": raw_disks - 2}[raid]
    return max(data_disks, 0) * disk_bytes


def recommend_nas(required: float, raid: str) -> dict:
    """Menor combinação baias × disco que atende à capacidade útil exigida."""
    best = None
    for bays in NAS_BAYS:
        min_disks = {"raid1": 2, "raid10": 4, "raid5": 3, "raid6": 4}[raid]
        disks = bays if raid != "raid1" else 2
        if disks < min_disks or (raid == "raid10" and disks % 2):
            continue
        for size_tb in DISK_SIZES_TB:
            usable = raid_usable(disks, size_tb * TB, raid)
            if usable >= required:
                raw = disks * size_tb
                if best is None or (raw, bays) < (best["raw_tb"], best["bays"]):
                    best = {"bays": bays, "disks": disks, "disk_tb": size_tb, "raw_tb": raw,
                            "usable_bytes": usable, "raid": raid}
                break
        if raid == "raid1":
            break
    return best or {"bays": None, "disks": None, "disk_tb": None, "raw_tb": None, "usable_bytes": None,
                    "raid": raid, "note": "capacidade acima de um único NAS: considere vários volumes ou storage em rack"}


def recommend_ssd(required: float) -> dict:
    for size in SSD_SIZES_GB:
        if size * 10**9 * 0.93 >= required:  # capacidade formatada ~93% da nominal
            return {"size_gb": size}
    return {"size_gb": None, "note": "acima de 4 TB: use SSDs em RAID ou o modo principal com NAS"}


def plan(p: PlanInput) -> PlanResult:
    clip_frames = min((p.clip_before + p.clip_after) * p.analysis_fps, 90)
    per_event = p.snapshot_kb * 1024 + clip_frames * p.frame_kb * 1024
    events_day = p.cameras * p.events_per_camera_day
    daily = events_day * per_event
    images_full = daily * p.retention_days
    ppe_rules = p.cameras  # premissa: uma regra de EPI por câmera
    db = _db_bytes(events_day, p.event_retention_days, ppe_rules)
    backup_zip = db * 0.45  # o banco comprime bem no .zip
    res = PlanResult(per_event_bytes=per_event, events_per_day=events_day, daily_bytes=daily)

    system = 60 * GB  # sistema operacional, Python, modelos e logs
    live = p.cameras * 150 * 1024
    if p.storage_mode == "principal":
        local_images = daily * min(p.local_days, p.retention_days)
        note = f"cache dos últimos {min(p.local_days, p.retention_days)} dias"
    else:
        local_images = images_full
        note = f"{p.retention_days} dias de retenção"
    res.local_items = [
        Item("Sistema, IA e logs", system),
        Item("Fotos e clipes das ocorrências", local_images, note),
        Item("Banco de dados", db, f"{p.event_retention_days} dias de registros"),
        Item("Backups locais do banco", backup_zip * p.backup_keep, f"{p.backup_keep} backups"),
        Item("Imagens ao vivo", live),
    ]
    res.local_total = sum(i.bytes for i in res.local_items)
    res.local_recommended = recommend_ssd(res.local_total / (1 - p.headroom))

    if p.storage_mode != "sem_nas":
        res.nas_items = [
            Item("Fotos e clipes das ocorrências", images_full, f"{p.retention_days} dias de retenção"),
            Item("Backups do banco", backup_zip * p.nas_backup_keep, f"{p.nas_backup_keep} backups"),
            Item("Relatórios mensais (PDF)", 12 * 300 * 1024 * max(p.event_retention_days / 365, 1)),
        ]
        res.nas_total = sum(i.bytes for i in res.nas_items)
    else:
        res.warnings.append("Sem NAS, as evidências e os backups ficam num único disco: uma falha perde tudo. "
                            "Recomenda-se ao menos um NAS de 2 baias em RAID 1.")

    if p.continuous:
        codec = 1.0 if p.continuous_codec == "h264" else 0.55
        per_cam_day = p.continuous_mbps * codec * 1e6 / 8 * 86400
        total = per_cam_day * p.cameras * p.continuous_days
        res.continuous = {"per_camera_day_bytes": per_cam_day, "total_bytes": total,
                          "note": "Gravação contínua é feita pelo NVR/DVR, não pelo VigIA. Dimensione-o à parte "
                                  "ou some ao NAS se ele também for o destino do NVR. Use discos de vigilância."}
        res.nas_items.append(Item("Gravação contínua (NVR) – opcional", total,
                                  f"{p.continuous_days} dias, {p.continuous_codec.upper()}"))
        res.nas_total += total

    if res.nas_items:
        res.nas_recommended = recommend_nas(res.nas_total / (1 - p.headroom), p.raid)

    # Processamento
    load = p.cameras * p.analysis_fps * p.models * MODEL_FACTOR[p.model_size]
    options = [{**h, "usage": load / h["fps"], "ok": load <= h["fps"] * 0.7} for h in HARDWARE]
    suggested = next((h for h in options if h["ok"]), None)
    res.compute = {
        "inferences_per_second": load,
        "options": options,
        "suggested": suggested["label"] if suggested else None,
        "servers_needed": 1 if suggested else math.ceil(load / (HARDWARE[-1]["fps"] * 0.7)),
        "ram_gb": next((g for g in (8, 16, 32, 64, 128) if g >= 4 + p.cameras * 0.25 + (2 if p.models > 1 else 0)), 128),
        "cpu_cores": max(4, math.ceil(4 + p.cameras / 4)),
    }
    if not suggested:
        res.warnings.append(f"A carga de IA ({load:.0f} inferências/s) passa de uma GPU alta: divida as câmeras "
                            f"em {res.compute['servers_needed']} servidores de processamento.")
    inbound = p.cameras * p.stream_mbps
    res.network = {"inbound_mbps": inbound,
                   "nas_mbps": daily * 8 / 86400 / 1e6 * 5,  # pico ~5× a média
                   "recommendation": "1 Gbps" if inbound < 600 else "10 Gbps ou mais de uma interface de rede"}
    if p.stream_mbps > 4:
        res.warnings.append("Use o sub-stream das câmeras (720p, 1–2 Mbps) para a análise: a IA trabalha "
                            "em 640 px e o fluxo principal só aumenta o uso de rede e CPU.")
    return res


def result_dict(res: PlanResult) -> dict:
    data = asdict(res)
    data["local_items"] = [asdict(i) for i in res.local_items]
    data["nas_items"] = [asdict(i) for i in res.nas_items]
    return data


# ---------- Dados reais da instalação ----------

def _dir_size(path: Path) -> int:
    total = 0
    if path.is_dir():
        for root, _, files in os.walk(path):
            for name in files:
                try:
                    total += os.path.getsize(os.path.join(root, name))
                except OSError:
                    pass
    return total


def measure(db: Session, days: int = 30) -> dict:
    """Tamanho médio real das ocorrências e volume diário (últimos `days` dias)."""
    from .storage import resolve

    since = datetime.now(timezone.utc) - timedelta(days=days)
    recent = db.scalars(select(Event).where(Event.created_at >= since)).all()
    first = min((e.created_at for e in recent), default=None)
    span_days = max((datetime.now(timezone.utc) - first).total_seconds() / 86400, 1) if first else days
    span_days = min(span_days, days)
    events_day = len(recent) / span_days if recent else 0

    sample = [e for e in recent if e.image_file or e.clip_dir][-300:]
    sizes, frame_sizes, snap_sizes = [], [], []
    for e in sample:
        total = 0
        if e.image_file and (p := resolve(e.image_file)):
            snap_sizes.append(p.stat().st_size)
            total += p.stat().st_size
        if e.clip_dir:
            folder = resolve(e.clip_dir)
            if folder:
                clip = _dir_size(folder)
                total += clip
                if e.clip_frames:
                    frame_sizes.append(clip / e.clip_frames)
        if total:
            sizes.append(total)
    cameras = db.scalar(select(func.count()).select_from(Camera).where(Camera.enabled)) or 0
    return {
        "days_observed": round(span_days, 1),
        "events_total": len(recent),
        "events_per_day": round(events_day, 1),
        "cameras": cameras,
        "events_per_camera_day": round(events_day / cameras, 1) if cameras else None,
        "avg_event_bytes": sum(sizes) / len(sizes) if sizes else None,
        "avg_frame_kb": round(sum(frame_sizes) / len(frame_sizes) / 1024, 1) if frame_sizes else None,
        "avg_snapshot_kb": round(sum(snap_sizes) / len(snap_sizes) / 1024, 1) if snap_sizes else None,
        "sampled_events": len(sizes),
        "ppe_hours": db.scalar(select(func.count()).select_from(RuleStat)) or 0,
    }


def project(m: dict, disk_total: float, disk_free: float, used_by_evidence: float,
            nas_total: float | None = None, nas_free: float | None = None) -> dict:
    """Projeção com a retenção atual: uso em regime, quando o disco enche e retenção máxima."""
    per_event = m["avg_event_bytes"] or 0
    daily = m["events_per_day"] * per_event
    retention = settings.retention_days
    principal = settings.storage_mode == "principal" and bool(settings.storage_nas_path)
    local_days = min(settings.storage_local_days, retention) if principal else retention

    out = {"daily_bytes": daily, "retention_days": retention, "local_days": local_days, "mode":
           "principal" if principal else ("espelho" if settings.storage_nas_path else "sem_nas")}
    if not daily or m["days_observed"] < MIN_DAYS or m["events_total"] < MIN_EVENTS:
        out["message"] = (f"Dados insuficientes para uma projeção confiável ({m['events_total']} ocorrência(s) em "
                          f"{m['days_observed']} dia(s); mínimo de {MIN_EVENTS} ocorrências em {MIN_DAYS} dias). "
                          "Enquanto isso, use 'Planejar implantação' com as premissas típicas.")
        return out

    steady_local = daily * local_days
    # o que já está ocupado por outras coisas no disco continua lá
    others = max(disk_total - disk_free - used_by_evidence, 0)
    limit = disk_total * settings.usage_alert_disk / 100
    out.update(
        steady_local_bytes=steady_local,
        local_fits=others + steady_local <= limit,
        local_max_days=int(max(limit - others, 0) / daily),
        days_until_alert=None,
    )
    growing = used_by_evidence < steady_local
    if growing:
        room = limit - (disk_total - disk_free)
        out["days_until_alert"] = max(int(room / daily), 0) if room > 0 else 0
    if nas_total:
        # considera o NAS dedicado ao VigIA (recomendado)
        steady_nas = daily * retention
        nas_limit = nas_total * settings.usage_alert_disk / 100
        out.update(steady_nas_bytes=steady_nas, nas_fits=steady_nas <= nas_limit,
                   nas_max_days=int(nas_limit / daily))
    return out
