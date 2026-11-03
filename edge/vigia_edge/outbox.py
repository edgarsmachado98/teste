"""Fila de envio para a nuvem, gravada em disco.

Se a internet cair, o detector continua e as ocorrências ficam aqui, na ordem; são reenviadas
quando a conexão volta (sem duplicar: cada ocorrência leva um identificador próprio)."""

import asyncio
import json
import logging
import shutil
import time
import uuid
from pathlib import Path

import httpx

log = logging.getLogger("vigia.edge.outbox")


class Outbox:
    def __init__(self, folder: Path):
        self.dir = Path(folder)
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "rejeitados").mkdir(exist_ok=True)
        self.wake = asyncio.Event()
        self.last_error: str = ""

    def put(self, kind: str, data: dict, thumb: bytes | None = None) -> None:
        name = f"{time.time_ns():020d}-{uuid.uuid4().hex[:8]}"
        if thumb:
            (self.dir / f"{name}.thumb").write_bytes(thumb)
        tmp = self.dir / f"{name}.tmp"
        tmp.write_text(json.dumps({"kind": kind, "data": data, "thumb": bool(thumb)}, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.dir / f"{name}.json")  # só aparece na fila depois de gravado por inteiro
        self.wake.set()

    def items(self) -> list[Path]:
        return sorted(self.dir.glob("*.json"))

    def size(self) -> int:
        return len(self.items())

    async def run(self, client: httpx.AsyncClient) -> None:
        backoff = 1
        while True:
            items = self.items()
            if not items:
                self.wake.clear()
                try:
                    await asyncio.wait_for(self.wake.wait(), 30)
                except asyncio.TimeoutError:
                    pass
                continue
            head = items[0]
            try:
                await self._send(client, head)
                self._done(head)
                backoff, self.last_error = 1, ""
            except httpx.HTTPStatusError as exc:
                code = exc.response.status_code
                if code in (401, 403, 408, 429) or code >= 500:  # nuvem fora/credencial: tenta de novo depois
                    self.last_error = f"nuvem respondeu {code}"
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 60)
                else:  # dado recusado (ex.: câmera excluída): separa para análise e segue a fila
                    log.error("envio recusado (%s): %s – movido para fila/rejeitados", code, exc.response.text[:200])
                    self._reject(head)
            except (httpx.HTTPError, OSError) as exc:
                self.last_error = f"sem conexão com a nuvem ({type(exc).__name__})"
                log.warning("%s – %d item(ns) na fila", self.last_error, len(items))
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    async def _send(self, client: httpx.AsyncClient, path: Path) -> None:
        item = json.loads(path.read_text(encoding="utf-8"))
        kind, data = item["kind"], item["data"]
        if kind == "event":
            files = None
            thumb = path.with_suffix(".thumb")
            if item.get("thumb") and thumb.exists():
                files = {"thumb": ("miniatura.jpg", thumb.read_bytes(), "image/jpeg")}
            resp = await client.post("/api/edge/events", data=data, files=files)
        elif kind == "clip":
            resp = await client.post(f"/api/edge/clips/{data['clip_id']}", json=data)
            if resp.status_code == 404:  # o evento ainda não chegou (fila em ordem: raro) – tenta depois
                raise httpx.HTTPStatusError("evento pendente", request=resp.request,
                                            response=httpx.Response(503, request=resp.request))
        elif kind == "stats":
            resp = await client.post("/api/edge/stats", json=data)
        else:
            return
        resp.raise_for_status()

    def _done(self, path: Path) -> None:
        path.unlink(missing_ok=True)
        path.with_suffix(".thumb").unlink(missing_ok=True)

    def _reject(self, path: Path) -> None:
        for p in (path, path.with_suffix(".thumb")):
            if p.exists():
                shutil.move(str(p), self.dir / "rejeitados" / p.name)
