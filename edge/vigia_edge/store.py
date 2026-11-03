"""Mídia no storage do cliente: imagens das ocorrências, quadros dos clipes e miniaturas."""

import io
import logging
import os
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

log = logging.getLogger("vigia.edge.store")

THUMB_WIDTH = 320


class MediaStore:
    def __init__(self, media_dir: Path, live_dir: Path):
        self.root = Path(media_dir)
        self.live = Path(live_dir)

    # ---------- gravação ----------
    def _write(self, rel: str, data: bytes) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)

    def save_event_image(self, jpeg: bytes, when: datetime | None = None) -> str:
        when = when or datetime.now(timezone.utc)
        rel = f"{when:%Y/%m/%d}/{uuid.uuid4().hex}.jpg"
        self._write(rel, jpeg)
        return rel

    def save_clip(self, clip_id: str, frames: list[bytes], when: datetime | None = None) -> str:
        when = when or datetime.now(timezone.utc)
        folder = f"clipes/{when:%Y/%m/%d}/{clip_id}"
        for i, jpeg in enumerate(frames):
            self._write(f"{folder}/{i:04d}.jpg", jpeg)
        return folder

    def save_live(self, camera_id: int, jpeg: bytes) -> None:
        self.live.mkdir(parents=True, exist_ok=True)
        path = self.live / f"{camera_id}.jpg"
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(jpeg)
        tmp.replace(path)

    @staticmethod
    def thumbnail(jpeg: bytes) -> bytes | None:
        """Miniatura (≈15 KB) que sobe para a nuvem: listas e painel abrem sem buscar a imagem inteira."""
        try:
            img = Image.open(io.BytesIO(jpeg)).convert("RGB")
        except Exception:  # noqa: BLE001
            return None
        img.thumbnail((THUMB_WIDTH, THUMB_WIDTH * 3 // 4 * 2))
        out = io.BytesIO()
        img.save(out, "JPEG", quality=72, optimize=True)
        return out.getvalue()

    # ---------- leitura pelo túnel ----------
    def resolve(self, rel: str) -> Path | None:
        """Só entrega arquivos de dentro do storage (ou o quadro ao vivo). Nada de '..' ou caminho absoluto."""
        if not rel or rel.startswith(("/", "\\")) or ".." in rel.replace("\\", "/").split("/") or ":" in rel:
            return None
        if rel.startswith("ao-vivo/"):
            name = rel.split("/", 1)[1]
            path = (self.live / name).resolve()
            base = self.live.resolve()
        else:
            path = (self.root / rel).resolve()
            base = self.root.resolve()
        if base not in path.parents or not path.is_file() or path.suffix.lower() != ".jpg":
            return None
        return path

    def read(self, rel: str) -> bytes | None:
        path = self.resolve(rel)
        return path.read_bytes() if path else None

    def delete(self, rel: str) -> None:
        if not rel or rel.startswith(("/", "\\")) or ".." in rel.replace("\\", "/").split("/"):
            return
        path = (self.root / rel).resolve()
        if self.root.resolve() not in path.parents:
            return
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink(missing_ok=True)

    # ---------- saúde e retenção ----------
    def ok(self) -> bool:
        """O storage do cliente está acessível e gravável?"""
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            probe = self.root / ".vigia-teste"
            probe.write_bytes(b"ok")
            probe.unlink()
            return True
        except OSError:
            return False

    def usage(self) -> dict:
        try:
            du = shutil.disk_usage(self.root)
            return {"disk_free_gb": round(du.free / 1e9, 1), "disk_total_gb": round(du.total / 1e9, 1)}
        except OSError:
            return {}

    def purge(self, retention_days: int) -> int:
        """Retenção (LGPD): apaga a mídia mais antiga que o prazo definido na nuvem."""
        if retention_days <= 0 or not self.root.exists():
            return 0
        cutoff = time.time() - retention_days * 86400
        removed = 0
        for dirpath, dirnames, filenames in os.walk(self.root, topdown=False):
            for name in filenames:
                p = Path(dirpath) / name
                try:
                    if p.suffix == ".jpg" and p.stat().st_mtime < cutoff:
                        p.unlink()
                        removed += 1
                except OSError:
                    pass
            if dirpath != str(self.root):
                try:
                    os.rmdir(dirpath)  # só remove se ficou vazia
                except OSError:
                    pass
        if removed:
            log.info("retenção: %d arquivo(s) com mais de %d dias apagado(s)", removed, retention_days)
        return removed
