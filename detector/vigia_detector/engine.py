"""Executa um ou mais modelos de detecção e devolve detecções normalizadas.

Combinar modelos é comum: um modelo COCO (pessoas), um de EPI e um de fogo/fumaça. Os modelos podem ser
ONNX (motor livre, MIT) ou Ultralytics .pt (AGPL-3.0) – ver backends.py."""

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


PPE_ITEMS_ALL = ("helmet", "vest", "glasses", "gloves", "mask", "harness", "boots", "ear_protection", "face_shield")
PPE_LABELS = set(PPE_ITEMS_ALL) | {f"no_{i}" for i in PPE_ITEMS_ALL}


class Engine:
    """Roda os modelos configurados (ONNX ou Ultralytics) e devolve detecções com rótulos canônicos."""

    def __init__(self, model_paths: list[str], device: str | None = None, conf: float = 0.25, imgsz: int = 640,
                 ppe_crops: bool = True, crop_imgsz: int = 320, max_crops: int = 8, backends: list | None = None):
        from .backends import load_backend

        self.models = backends if backends is not None else [load_backend(p, device) for p in model_paths]
        self.aliases = load_aliases()
        self.device = device
        self.conf = conf
        self.imgsz = imgsz
        self.crop_imgsz, self.max_crops = crop_imgsz, max_crops
        # Rótulos (canônicos) que cada modelo sabe reconhecer: as regras não cobram EPI que nenhum modelo vê
        self.model_labels = [{canonical(n, self.aliases) for n in m.names} for m in self.models]
        self.labels: set[str] = set().union(*self.model_labels) if self.models else set()
        # Modelos de EPI (os que conhecem capacete, colete...) ganham uma segunda olhada em cada pessoa
        self.ppe_models = [m for m, labels in zip(self.models, self.model_labels) if labels & PPE_LABELS] \
            if ppe_crops else []
        for model in self.models:
            log.info("modelo %s carregado (%s) – classes: %s", model.path, model.license or "licença não informada",
                     model.names)
        if not self.labels & PPE_LABELS:
            log.warning("nenhum modelo de EPI carregado: regras de EPI ficam pausadas (veja modelos/ e MODEL_PATHS)")

    def detect(self, frame) -> list[Detection]:
        detections = []
        for model in self.models:
            for name, conf, box in model.predict(frame, self.imgsz, self.conf):
                detections.append(Detection(canonical(name, self.aliases), conf, box))
        if self.ppe_models:
            detections += self._ppe_on_people(frame, detections)
        return merge(detections)

    def _ppe_on_people(self, frame, detections: list[Detection]) -> list[Detection]:
        """Segunda olhada: recorta cada pessoa (com folga), amplia e roda o modelo de EPI só nela.
        Capacete de quem está longe ocupa poucos pixels no quadro inteiro e passa despercebido."""
        h, w = frame.shape[:2]
        people = sorted((d for d in detections if d.label == "person" and d.confidence >= 0.35),
                        key=lambda d: (d.box[3] - d.box[1]), reverse=True)[: self.max_crops]
        found = []
        for p in people:
            x1, y1, x2, y2 = p.box
            pw, ph = x2 - x1, y2 - y1
            if ph < 0.04:
                continue
            cx1, cy1 = max(0.0, x1 - pw * 0.25), max(0.0, y1 - ph * 0.15)
            cx2, cy2 = min(1.0, x2 + pw * 0.25), min(1.0, y2 + ph * 0.05)
            crop = frame[int(cy1 * h):int(cy2 * h), int(cx1 * w):int(cx2 * w)]
            if crop.size == 0 or min(crop.shape[:2]) < 12:
                continue
            for model in self.ppe_models:
                for name, conf, (bx1, by1, bx2, by2) in model.predict(crop, self.crop_imgsz, self.conf):
                    label = canonical(name, self.aliases)
                    if label == "person":
                        continue
                    # coordenadas do recorte → do quadro inteiro
                    found.append(Detection(label, float(conf), (cx1 + bx1 * (cx2 - cx1), cy1 + by1 * (cy2 - cy1),
                                                                cx1 + bx2 * (cx2 - cx1), cy1 + by2 * (cy2 - cy1))))
        return found
