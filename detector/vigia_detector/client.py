"""Comunicação com o backend: configuração, eventos e quadros ao vivo."""

import logging
import queue
import threading
import time

import httpx

log = logging.getLogger("vigia.client")


class BackendClient:
    def __init__(self, base_url: str, api_key: str):
        self.http = httpx.Client(base_url=base_url.rstrip("/"), headers={"X-Detector-Key": api_key}, timeout=15)
        # Eventos vão para uma fila: se o backend cair por alguns segundos, nada se perde.
        self.events: queue.Queue = queue.Queue(maxsize=500)
        threading.Thread(target=self._sender, daemon=True, name="event-sender").start()

    def get_config(self) -> list[dict]:
        resp = self.http.get("/api/detector/config")
        resp.raise_for_status()
        return resp.json()

    def send_event(self, camera_id: int, rule_id: int, message: str, jpeg: bytes) -> None:
        try:
            self.events.put_nowait((camera_id, rule_id, message, jpeg))
        except queue.Full:
            log.error("fila de eventos cheia – descartando evento da câmera %s", camera_id)

    def send_frame(self, camera_id: int, jpeg: bytes) -> None:
        try:
            self.http.post(
                f"/api/detector/cameras/{camera_id}/frame", files={"frame": ("frame.jpg", jpeg, "image/jpeg")}
            ).raise_for_status()
        except httpx.HTTPError as exc:
            log.debug("falha ao enviar quadro ao vivo: %s", exc)

    def _sender(self) -> None:
        while True:
            camera_id, rule_id, message, jpeg = self.events.get()
            for attempt in range(5):
                try:
                    self.http.post(
                        "/api/detector/events",
                        data={"camera_id": camera_id, "rule_id": rule_id, "message": message},
                        files={"snapshot": ("evento.jpg", jpeg, "image/jpeg")},
                    ).raise_for_status()
                    log.info("evento enviado: câmera %s – %s", camera_id, message)
                    break
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code < 500:
                        log.error("evento rejeitado (%s): %s", exc.response.status_code, exc.response.text)
                        break
                    time.sleep(2**attempt)
                except httpx.HTTPError as exc:
                    log.warning("backend indisponível (%s), tentando novamente", exc)
                    time.sleep(2**attempt)
