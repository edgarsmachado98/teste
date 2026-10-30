"""Executa um ou mais modelos YOLO e devolve detecções normalizadas.

Combinar modelos é comum: um modelo COCO (pessoas), um de EPI e um de fogo/fumaça."""

from __future__ import annotations

import logging

from .labels import canonical, load_aliases
from .rules import Detection

log = logging.getLogger("vigia.engine")


def iou(a: tuple, b: tuple) -> float:
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def merge(detections: list[Detection], threshold: float = 0.5) -> list[Detection]:
    """Remove duplicatas do mesmo rótulo vindas de modelos diferentes (ex.: 'person' duas vezes)."""
    kept: list[Detection] = []
    for det in sorted(detections, key=lambda d: d.confidence, reverse=True):
        if not any(k.label == det.label and iou(k.box, det.box) > threshold for k in kept):
            kept.append(det)
    return kept


class Engine:
    def __init__(self, model_paths: list[str], device: str | None = None, conf: float = 0.25, imgsz: int = 640):
        from ultralytics import YOLO  # importado aqui para os testes não exigirem a biblioteca

        self.models = [YOLO(path) for path in model_paths]
        self.aliases = load_aliases()
        self.device = device
        self.conf = conf
        self.imgsz = imgsz
        for path, model in zip(model_paths, self.models):
            log.info("modelo %s carregado – classes: %s", path, list(model.names.values()))

    def detect(self, frame) -> list[Detection]:
        detections = []
        for model in self.models:
            result = model.predict(frame, conf=self.conf, imgsz=self.imgsz, device=self.device, verbose=False)[0]
            names = result.names
            for box, conf, cls in zip(
                result.boxes.xyxyn.tolist(), result.boxes.conf.tolist(), result.boxes.cls.tolist()
            ):
                label = canonical(names[int(cls)], self.aliases)
                detections.append(Detection(label, float(conf), tuple(box)))
        return merge(detections)
