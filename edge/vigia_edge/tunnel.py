"""Túnel de saída com a nuvem (WebSocket sobre HTTPS, porta 443).

Só o Edge inicia a conexão: o cliente não abre portas. Pela conexão a nuvem pede os arquivos
que alguém abriu na tela e manda apagar mídia; o Edge informa a sua saúde a cada 30 s."""

import asyncio
import json
import logging
import time

import websockets
from websockets.asyncio.client import connect

from . import __version__

log = logging.getLogger("vigia.edge.tunnel")


class Tunnel:
    def __init__(self, cfg, store, status_fn):
        self.cfg, self.store, self.status_fn = cfg, store, status_fn
        self.connected = False
        self.started = time.monotonic()

    def _ssl(self):
        return self.cfg.ssl_context() if self.cfg.ws_url.startswith("wss://") else None

    async def run(self) -> None:
        backoff = 1
        while True:
            try:
                async with connect(self.cfg.ws_url, additional_headers=self.cfg.auth_headers, ssl=self._ssl(),
                                   max_size=None, ping_interval=20, ping_timeout=20, open_timeout=15) as ws:
                    self.connected, backoff = True, 1
                    log.info("túnel conectado a %s", self.cfg.cloud_url)
                    sender = asyncio.create_task(self._status_loop(ws))
                    try:
                        async for message in ws:
                            if isinstance(message, str):
                                asyncio.create_task(self._handle(ws, json.loads(message)))
                    finally:
                        sender.cancel()
            except websockets.InvalidStatus as exc:
                log.error("nuvem recusou o túnel (%s): credencial revogada?", exc.response.status_code)
            except (OSError, websockets.WebSocketException, asyncio.TimeoutError) as exc:
                if self.connected:
                    log.warning("túnel caiu: %s", exc)
            finally:
                self.connected = False
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)

    async def _status_loop(self, ws) -> None:
        while True:
            status = await asyncio.to_thread(self.status_fn)
            await ws.send(json.dumps({"type": "status", "version": __version__,
                                      "uptime_s": int(time.monotonic() - self.started), **status}))
            await asyncio.sleep(30)

    async def _handle(self, ws, msg: dict) -> None:
        op = msg.get("op")
        if op == "get":
            rid = str(msg.get("id", ""))[:32].ljust(32)
            data = await asyncio.to_thread(self.store.read, str(msg.get("path", "")))
            if data is None:
                await ws.send(json.dumps({"id": rid.strip(), "ok": False, "error": "arquivo não encontrado"}))
            else:
                await ws.send(rid.encode("ascii") + data)
        elif op == "delete":
            for rel in msg.get("paths", [])[:1000]:
                await asyncio.to_thread(self.store.delete, str(rel))
