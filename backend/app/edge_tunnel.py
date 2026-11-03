"""Túnel com os VigIA Edge.

O Edge abre um WebSocket de SAÍDA para a nuvem (porta 443): o cliente não abre portas nem precisa
de VPN. Por esse canal a nuvem pede arquivos (imagem, quadro do clipe, ao vivo) só quando alguém
os abre na tela, e manda apagar mídia vencida.

Protocolo (texto = JSON, binário = 32 bytes do id do pedido + conteúdo):
  nuvem → edge  {"op": "get", "id": "<hex32>", "path": "2026/11/03/abc.jpg"}
  edge  → nuvem  binário (id + bytes)  ou  {"id": "...", "ok": false, "error": "..."}
  nuvem → edge  {"op": "delete", "paths": [...]}
  edge  → nuvem  {"type": "status", ...}   (a cada 30 s: disco, fila, storage, versão)

Uma instância por cliente roda com um único processo, então o registro das conexões fica em memória.
"""

import asyncio
import logging
import time
import uuid
from collections import OrderedDict

from fastapi import WebSocket

log = logging.getLogger("vigia.edge")

FETCH_TIMEOUT = 12.0
MAX_FILE = 20 * 1024 * 1024


class EdgeOffline(Exception):
    pass


class MediaCache:
    """Cache em memória dos arquivos vindos do Edge (abrir de novo a mesma ocorrência é instantâneo)."""

    def __init__(self, max_bytes: int = 64 * 1024 * 1024, ttl: float = 600):
        self.max_bytes, self.ttl = max_bytes, ttl
        self.items: OrderedDict[tuple, tuple[float, bytes]] = OrderedDict()
        self.size = 0

    def get(self, key: tuple, ttl: float | None = None) -> bytes | None:
        item = self.items.get(key)
        if item is None:
            return None
        stored_at, data = item
        if time.monotonic() - stored_at > (ttl if ttl is not None else self.ttl):
            self.pop(key)
            return None
        self.items.move_to_end(key)
        return data

    def put(self, key: tuple, data: bytes) -> None:
        if len(data) > self.max_bytes // 4:
            return
        self.pop(key)
        self.items[key] = (time.monotonic(), data)
        self.size += len(data)
        while self.size > self.max_bytes:
            self.pop(next(iter(self.items)))

    def pop(self, key: tuple) -> None:
        item = self.items.pop(key, None)
        if item:
            self.size -= len(item[1])


class EdgeHub:
    def __init__(self):
        self.sockets: dict[int, WebSocket] = {}
        self.pending: dict[str, asyncio.Future] = {}
        self.cache = MediaCache()

    def online(self, edge_id: int | None) -> bool:
        return edge_id in self.sockets

    def connected_ids(self) -> list[int]:
        return list(self.sockets)

    async def attach(self, edge_id: int, ws: WebSocket) -> None:
        old = self.sockets.get(edge_id)
        self.sockets[edge_id] = ws
        if old is not None:  # o mesmo Edge reconectou: derruba a conexão antiga
            try:
                await old.close(code=4000)
            except Exception:  # noqa: BLE001
                pass

    def detach(self, edge_id: int, ws: WebSocket) -> None:
        if self.sockets.get(edge_id) is ws:
            del self.sockets[edge_id]

    async def disconnect(self, edge_id: int) -> None:
        """Revogação: encerra o túnel na hora."""
        ws = self.sockets.pop(edge_id, None)
        if ws is not None:
            try:
                await ws.close(code=4003)
            except Exception:  # noqa: BLE001
                pass

    def handle_binary(self, data: bytes) -> None:
        rid = data[:32].decode("ascii", "replace")
        fut = self.pending.get(rid)
        if fut and not fut.done():
            fut.set_result(data[32:])

    def handle_error(self, msg: dict) -> None:
        fut = self.pending.get(str(msg.get("id")))
        if fut and not fut.done():
            fut.set_exception(FileNotFoundError(msg.get("error") or "arquivo não encontrado no Edge"))

    async def fetch(self, edge_id: int, path: str, cache_ttl: float | None = None) -> bytes:
        key = (edge_id, path)
        cached = self.cache.get(key, cache_ttl)
        if cached is not None:
            return cached
        ws = self.sockets.get(edge_id)
        if ws is None:
            raise EdgeOffline()
        rid = uuid.uuid4().hex
        fut = asyncio.get_running_loop().create_future()
        self.pending[rid] = fut
        try:
            await ws.send_json({"op": "get", "id": rid, "path": path})
            data = await asyncio.wait_for(fut, FETCH_TIMEOUT)
        except (asyncio.TimeoutError, RuntimeError) as exc:
            raise EdgeOffline() from exc
        finally:
            self.pending.pop(rid, None)
        self.cache.put(key, data)
        return data

    async def delete(self, edge_id: int, paths: list[str]) -> bool:
        """Pede ao Edge que apague mídia (retenção/LGPD). Se estiver offline, a retenção local
        do próprio Edge apaga depois, pelo mesmo prazo."""
        for p in paths:
            self.cache.pop((edge_id, p))
        ws = self.sockets.get(edge_id)
        if ws is None or not paths:
            return False
        try:
            await ws.send_json({"op": "delete", "paths": paths})
            return True
        except Exception:  # noqa: BLE001
            return False


hub = EdgeHub()
