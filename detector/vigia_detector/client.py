"""Comunicação com o backend: configuração, eventos, clipes, quadros ao vivo e estatísticas."""

import json
import logging
import queue
import threading
import time

import httpx

log = logging.getLogger("vigia.client")


class BackendClient:
    def __init__(self, base_url: str, api_key: str, verify: str | bool = True):
        # verify: True (certificados do sistema) ou caminho do certificado da instalação (HTTPS próprio)
        self.http = httpx.Client(base_url=base_url.rstrip("/"), headers={"X-Detector-Key": api_key},
                                 timeout=30, verify=verify)
        # Eventos e clipes vão para uma fila, na ordem: o clipe sempre chega depois do seu evento,
        # e se o backend cair por alguns segundos nada se perde.
        self.outbox: queue.Queue = queue.Queue(maxsize=500)
        threading.Thread(target=self._sender, daemon=True, name="event-sender").start()

    def get_config(self) -> list[dict]:
        resp = self.http.get("/api/detector/config")
        resp.raise_for_status()
        return resp.json()

    def _enqueue(self, description: str, path: str, data: dict, files: list) -> None:
        try:
            self.outbox.put_nowait((description, path, data, files))
        except queue.Full:
            log.error("fila de envio cheia – descartando %s", description)

    def send_event(self, camera_id: int, rule_id: int, message: str, jpeg: bytes,
                   boxes: list | None = None, clip_id: str | None = None) -> None:
        data = {"camera_id": camera_id, "rule_id": rule_id, "message": message, "boxes": json.dumps(boxes or [])}
        if clip_id:
            data["clip_id"] = clip_id
        self._enqueue(f"evento: câmera {camera_id} – {message}", "/api/detector/events", data,
                      [("snapshot", ("evento.jpg", jpeg, "image/jpeg"))])

    def send_clip(self, clip_id: str, frames: list[bytes], duration: float) -> None:
        files = [("frames", (f"{i:04d}.jpg", jpeg, "image/jpeg")) for i, jpeg in enumerate(frames)]
        self._enqueue(f"clipe {clip_id[:8]} ({len(frames)} quadros)", f"/api/detector/clips/{clip_id}",
                      {"duration": f"{duration:.2f}"}, files)

    def send_frame(self, camera_id: int, jpeg: bytes, health: str = "ok") -> None:
        try:
            self.http.post(
                f"/api/detector/cameras/{camera_id}/frame",
                data={"health": health},
                files={"frame": ("frame.jpg", jpeg, "image/jpeg")},
            ).raise_for_status()
        except httpx.HTTPError as exc:
            log.debug("falha ao enviar quadro ao vivo: %s", exc)

    def send_stats(self, camera_id: int, items: list[dict]) -> None:
        try:
            self.http.post("/api/detector/stats", json={"camera_id": camera_id, "items": items}).raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("falha ao enviar estatísticas de conformidade: %s", exc)

    def _sender(self) -> None:
        while True:
            description, path, data, files = self.outbox.get()
            for attempt in range(6):
                try:
                    self.http.post(path, data=data, files=files).raise_for_status()
                    log.info("enviado %s", description)
                    break
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code < 500:
                        log.error("%s rejeitado (%s): %s", description, exc.response.status_code, exc.response.text)
                        break
                    time.sleep(2**attempt)
                except httpx.HTTPError as exc:
                    log.warning("backend indisponível (%s), tentando novamente", exc)
                    time.sleep(2**attempt)
