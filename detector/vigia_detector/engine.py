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


PPE_LABELS = {"helmet", "vest", "glasses", "gloves", "mask", "no_helmet", "no_vest", "no_glasses", "no_gloves",
              "no_mask"}


class Engine:
    def __init__(self, model_paths: list[str], device: str | None = None, conf: float = 0.25, imgsz: int = 640,
                 ppe_crops: bool = True, crop_imgsz: int = 320, max_crops: int = 8):
        from ultralytics import YOLO  # importado aqui para os testes não exigirem a biblioteca

        self.models = [YOLO(path) for path in model_paths]
        self.aliases = load_aliases()
        self.device = device
        self.conf = conf
        self.imgsz = imgsz
        self.crop_imgsz, self.max_crops = crop_imgsz, max_crops
        # Rótulos (canônicos) que cada modelo sabe reconhecer: as regras não cobram EPI que nenhum modelo vê
        self.model_labels = [{canonical(n, self.aliases) for n in m.names.values()} for m in self.models]
        self.labels: set[str] = set().union(*self.model_labels) if self.models else set()
        # Modelos de EPI (os que conhecem capacete, colete...) ganham uma segunda olhada em cada pessoa
        self.ppe_models = [m for m, labels in zip(self.models, self.model_labels) if labels & PPE_LABELS] \
            if ppe_crops else []
        for path, model in zip(model_paths, self.models):
            log.info("modelo %s carregado – classes: %s", path, list(model.names.values()))
        if not self.labels & PPE_LABELS:
            log.warning("nenhum modelo de EPI carregado: regras de EPI ficam pausadas (veja modelos/ e MODEL_PATHS)")

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
                result = model.predict(crop, conf=self.conf, imgsz=self.crop_imgsz, device=self.device, verbose=False)[0]
                for box, conf, cls in zip(result.boxes.xyxyn.tolist(), result.boxes.conf.tolist(),
                                          result.boxes.cls.tolist()):
                    label = canonical(result.names[int(cls)], self.aliases)
                    if label == "person":
                        continue
                    bx1, by1, bx2, by2 = box  # coordenadas do recorte → do quadro inteiro
                    found.append(Detection(label, float(conf), (cx1 + bx1 * (cx2 - cx1), cy1 + by1 * (cy2 - cy1),
                                                                cx1 + bx2 * (cx2 - cx1), cy1 + by2 * (cy2 - cy1))))
        return found
