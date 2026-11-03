"""API local do Edge: o detector da planta fala com ela exatamente como falava com o servidor
(BACKEND_URL=http://127.0.0.1:8100). As imagens ficam no storage do cliente; para a nuvem vão
os dados da ocorrência e a miniatura."""

import asyncio
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import httpx
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from pydantic import BaseModel

from . import __version__
from .config import HOME, EdgeConfig
from .outbox import Outbox
from .store import MediaStore
from .tunnel import Tunnel

log = logging.getLogger("vigia.edge")

HEALTH_EVERY = 60  # s: reenvia a saúde da câmera mesmo sem mudança (horário do último quadro)


class StatItem(BaseModel):
    rule_id: int
    observed: int
    violations: int


class StatsIn(BaseModel):
    camera_id: int
    items: list[StatItem]


def create_app(cfg: EdgeConfig) -> FastAPI:
    store = MediaStore(cfg.media_dir, cfg.live_dir)
    outbox = Outbox(cfg.outbox_dir)
    config_cache = HOME / "config-cameras.json"
    state = {"detector_seen_at": None, "health": {}, "cameras": 0}
    client = httpx.AsyncClient(base_url=cfg.cloud_url, headers=cfg.auth_headers, verify=cfg.verify, timeout=20)

    def status() -> dict:
        return {"media_ok": store.ok(), "media_dir": str(cfg.media_dir), "queue": outbox.size(),
                "cameras": state["cameras"], "retention_days": cfg.retention_days,
                "detector_seen_at": state["detector_seen_at"], **store.usage()}

    tunnel = Tunnel(cfg, store, status)

    async def maintenance() -> None:
        """Prazo de retenção vem da nuvem; a mídia vencida é apagada aqui mesmo (LGPD)."""
        while True:
            try:
                resp = await client.get("/api/edge/settings")
                resp.raise_for_status()
                cfg.retention_days = int(resp.json().get("retention_days", cfg.retention_days))
            except (httpx.HTTPError, ValueError) as exc:
                log.debug("sem configurações da nuvem: %s", exc)
            await asyncio.to_thread(store.purge, cfg.retention_days)
            await asyncio.sleep(6 * 3600)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        tasks = [asyncio.create_task(outbox.run(client)), asyncio.create_task(tunnel.run()),
                 asyncio.create_task(maintenance())]
        log.info("VigIA Edge %s – storage: %s (%s)", __version__, cfg.media_dir,
                 "ok" if store.ok() else "INACESSÍVEL")
        yield
        for t in tasks:
            t.cancel()
        await client.aclose()

    app = FastAPI(title="VigIA Edge", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.store, app.state.outbox, app.state.tunnel, app.state.status = store, outbox, tunnel, status

    def detector_auth(x_detector_key: str | None = Header(None)) -> None:
        import secrets
        if not x_detector_key or not secrets.compare_digest(x_detector_key, cfg.detector_key):
            raise HTTPException(401, "chave do detector inválida")
        state["detector_seen_at"] = datetime.now(timezone.utc).isoformat()

    guard = [Depends(detector_auth)]

    @app.get("/api/detector/config", dependencies=guard)
    async def detector_config():
        """Câmeras e regras da nuvem; sem internet, usa a última configuração recebida."""
        try:
            resp = await client.get("/api/edge/detector/config")
            resp.raise_for_status()
            cameras = resp.json()
            config_cache.write_text(json.dumps(cameras), encoding="utf-8")
        except (httpx.HTTPError, ValueError) as exc:
            if not config_cache.exists():
                raise HTTPException(503, f"nuvem inacessível e sem configuração salva: {exc}") from None
            cameras = json.loads(config_cache.read_text(encoding="utf-8"))
        state["cameras"] = len(cameras)
        return cameras

    @app.post("/api/detector/events", status_code=202, dependencies=guard)
    async def detector_event(camera_id: int = Form(...), rule_id: int = Form(...), message: str = Form(...),
                             boxes: str | None = Form(None), clip_id: str | None = Form(None),
                             snapshot: UploadFile | None = File(None)):
        now = datetime.now(timezone.utc)
        media_ref, thumb = None, None
        if snapshot is not None:
            jpeg = await snapshot.read()
            media_ref = await asyncio.to_thread(store.save_event_image, jpeg, now)
            thumb = await asyncio.to_thread(store.thumbnail, jpeg)
        data = {"camera_id": str(camera_id), "rule_id": str(rule_id), "message": message[:500],
                "boxes": boxes or "[]", "edge_ref": uuid.uuid4().hex, "captured_at": now.isoformat()}
        if clip_id:
            data["clip_id"] = clip_id[:40]
        if media_ref:
            data["media_ref"] = media_ref
        outbox.put("event", data, thumb)
        return {"queued": True, "media_ref": media_ref}

    @app.post("/api/detector/clips/{clip_id}", status_code=202, dependencies=guard)
    async def detector_clip(clip_id: str, frames: list[UploadFile] = File(...), duration: float = Form(...)):
        if len(frames) > 300 or not clip_id.replace("-", "").isalnum():
            raise HTTPException(400, "clipe inválido")
        jpegs = [await f.read() for f in frames]
        folder = await asyncio.to_thread(store.save_clip, clip_id[:40], jpegs)
        outbox.put("clip", {"clip_id": clip_id[:40], "folder": folder, "frames": len(jpegs),
                            "duration": max(float(duration), 0.1)})
        return {"queued": True}

    @app.post("/api/detector/cameras/{camera_id}/frame", status_code=204, dependencies=guard)
    async def detector_frame(camera_id: int, frame: UploadFile = File(...), health: str = Form("ok")):
        """Quadro ao vivo fica na caixa (a nuvem busca quando alguém abre "Ao vivo");
        a saúde da imagem sobe quando muda ou a cada minuto."""
        await asyncio.to_thread(store.save_live, camera_id, await frame.read())
        last = state["health"].get(camera_id)
        if last is None or last[0] != health or time.monotonic() - last[1] > HEALTH_EVERY:
            state["health"][camera_id] = (health, time.monotonic())
            try:
                (await client.post(f"/api/edge/cameras/{camera_id}/health", json={"health": health})).raise_for_status()
            except httpx.HTTPError:
                state["health"].pop(camera_id, None)  # tenta de novo no próximo quadro

    @app.post("/api/detector/stats", status_code=202, dependencies=guard)
    async def detector_stats(data: StatsIn):
        outbox.put("stats", {**data.model_dump(), "observed_at": datetime.now(timezone.utc).isoformat()})
        return {"queued": True}

    @app.get("/status")
    def edge_status():
        """Diagnóstico local (só na própria máquina): http://127.0.0.1:8100/status"""
        return {"version": __version__, "name": cfg.name, "cloud": cfg.cloud_url, "tunnel": tunnel.connected,
                "last_error": outbox.last_error, **status()}

    return app
