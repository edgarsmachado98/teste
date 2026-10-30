"""Uma thread por câmera: lê o vídeo, roda a IA, aplica as regras e envia alertas."""

from __future__ import annotations

import logging
import threading
import time
import unicodedata
from datetime import datetime

import cv2
import numpy as np

from .imagehealth import ImageHealth
from .rules import Detection, RuleTracker, Violation, in_schedule, observe

log = logging.getLogger("vigia.worker")

GREEN, RED, YELLOW = (60, 200, 60), (40, 40, 230), (0, 200, 255)


def is_stream(source: str) -> bool:
    return source.split("://")[0].lower() in {"rtsp", "rtsps", "rtmp", "http", "https"} or source.isdigit()


def ascii_text(text: str) -> str:
    """As fontes do OpenCV não têm acentos: 'máscara' viraria 'm??scara'."""
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def draw(frame: np.ndarray, detections: list[Detection], rules: list[dict], violation: Violation | None = None):
    img = frame.copy()
    h, w = img.shape[:2]
    offenders = set(violation.detections) if violation else set()

    for rule in rules:
        if rule.get("zone"):
            pts = np.array([[x * w, y * h] for x, y in rule["zone"]], dtype=np.int32)
            highlight = violation is not None and violation.rule_id == rule["id"]
            cv2.polylines(img, [pts], True, RED if highlight else YELLOW, 2)

    for det in detections:
        x1, y1, x2, y2 = int(det.box[0] * w), int(det.box[1] * h), int(det.box[2] * w), int(det.box[3] * h)
        color = RED if det in offenders else GREEN
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
        cv2.putText(img, f"{det.label} {det.confidence:.0%}", (x1, max(15, y1 - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)

    if violation:
        banner = f"{ascii_text(violation.message)} | {datetime.now():%d/%m/%Y %H:%M:%S}"
        cv2.rectangle(img, (0, 0), (w, 32), RED, -1)
        cv2.putText(img, banner, (10, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2, cv2.LINE_AA)
    return img


def to_jpeg(img: np.ndarray, max_width: int = 1280, quality: int = 85) -> bytes:
    h, w = img.shape[:2]
    if w > max_width:
        img = cv2.resize(img, (max_width, int(h * max_width / w)))
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return buf.tobytes() if ok else b""


class CameraWorker(threading.Thread):
    def __init__(self, camera: dict, engine, engine_lock: threading.Lock, client,
                 analysis_fps: float = 3.0, live_interval: float = 2.0, stats_interval: float = 60.0):
        super().__init__(daemon=True, name=f"camera-{camera['id']}")
        self.camera = camera
        self.rules = camera["rules"]
        self.engine = engine
        self.engine_lock = engine_lock
        self.client = client
        self.analysis_period = 1.0 / analysis_fps
        self.live_interval = live_interval
        self.stats_interval = stats_interval
        self.tracker = RuleTracker()
        self.health = ImageHealth()
        self.stats: dict[int, list[int]] = {}
        self.stop_event = threading.Event()

    def update(self, camera: dict) -> None:
        self.rules = camera["rules"]

    def stop(self) -> None:
        self.stop_event.set()

    def run(self) -> None:
        source = self.camera["source"]
        stream = is_stream(source)
        backoff = 2
        while not self.stop_event.is_set():
            cap = cv2.VideoCapture(int(source) if source.isdigit() else source)
            if not cap.isOpened():
                log.warning("[%s] não foi possível abrir %s – nova tentativa em %ss", self.camera["name"], source, backoff)
                self.stop_event.wait(backoff)
                backoff = min(backoff * 2, 60)
                continue
            log.info("[%s] conectado", self.camera["name"])
            backoff = 2
            self._loop(cap, stream)
            cap.release()

    def _loop(self, cap: cv2.VideoCapture, stream: bool) -> None:
        file_delay = 0 if stream else 1.0 / (cap.get(cv2.CAP_PROP_FPS) or 25)
        last_analysis = last_live = 0.0
        last_stats = time.monotonic()
        while not self.stop_event.is_set():
            # Em streams é preciso consumir os quadros continuamente para não acumular atraso.
            if not cap.grab():
                if not stream:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)  # arquivo de teste: reinicia
                    continue
                log.warning("[%s] stream perdido, reconectando", self.camera["name"])
                return
            if file_delay:
                time.sleep(file_delay)

            now = time.monotonic()
            if now - last_analysis < self.analysis_period:
                continue
            last_analysis = now
            ok, frame = cap.retrieve()
            if not ok:
                continue

            with self.engine_lock:
                detections = self.engine.detect(frame)
            rules = self.rules
            wall = datetime.now()
            for violation in self.tracker.update(rules, detections, now, wall):
                img = draw(frame, detections, rules, violation)
                boxes = [list(d.box) for d in violation.detections]
                self.client.send_event(self.camera["id"], violation.rule_id, violation.message, to_jpeg(img), boxes)
            self._accumulate(rules, detections, wall)
            health = self.health.update(frame, now)

            if now - last_live >= self.live_interval:
                last_live = now
                self.client.send_frame(self.camera["id"], to_jpeg(draw(frame, detections, rules), 960, 70), health)
            if now - last_stats >= self.stats_interval:
                last_stats = now
                self._flush_stats()

    def _accumulate(self, rules: list[dict], detections: list[Detection], wall: datetime) -> None:
        """Soma pessoas observadas x sem EPI (base do índice de conformidade)."""
        for rule in rules:
            if not in_schedule(rule, wall):
                continue
            counts = observe(rule, detections)
            if counts and counts[0]:
                totals = self.stats.setdefault(rule["id"], [0, 0])
                totals[0] += counts[0]
                totals[1] += counts[1]

    def _flush_stats(self) -> None:
        if self.stats:
            items = [{"rule_id": rid, "observed": o, "violations": v} for rid, (o, v) in self.stats.items()]
            self.stats = {}
            self.client.send_stats(self.camera["id"], items)
