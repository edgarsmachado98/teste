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
                 ppe_crops: bool = True, crop_imgsz: int = 320, max_crops: int = 8, backends: list | None = None,
                 tiles: tuple[int, int] = (1, 1), tile_overlap: float = 0.2):
        from .backends import load_backend

        self.models = backends if backends is not None else [load_backend(p, device) for p in model_paths]
        self.aliases = load_aliases()
        self.device = device
        self.conf = conf
        self.imgsz = imgsz
        self.crop_imgsz, self.max_crops = crop_imgsz, max_crops
        # Cenas abertas (obra, pátio): pessoas pequenas somem quando o quadro inteiro é reduzido para o modelo.
        # Com blocos (ex.: 2x2), cada pedaço é analisado separado e as pessoas "crescem" para o modelo.
        self.tiles, self.tile_overlap = tiles, tile_overlap
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

    def _regions(self) -> list[tuple[float, float, float, float]]:
        rows, cols = self.tiles
        regions = [(0.0, 0.0, 1.0, 1.0)]  # o quadro inteiro sempre (pessoas grandes cortadas pelos blocos)
        if rows * cols > 1:
            ov = self.tile_overlap
            tw, th = (1 + ov * (cols - 1)) / cols, (1 + ov * (rows - 1)) / rows
            for r in range(rows):
                for c in range(cols):
                    x1, y1 = c * (tw - ov), r * (th - ov)
                    regions.append((x1, y1, min(1.0, x1 + tw), min(1.0, y1 + th)))
        return regions

    def detect(self, frame) -> list[Detection]:
        detections = []
        h, w = frame.shape[:2]
        for rx1, ry1, rx2, ry2 in self._regions():
            part = frame[int(ry1 * h):int(ry2 * h), int(rx1 * w):int(rx2 * w)]
            for model in self.models:
                for name, conf, (bx1, by1, bx2, by2) in model.predict(part, self.imgsz, self.conf):
                    box = (rx1 + bx1 * (rx2 - rx1), ry1 + by1 * (ry2 - ry1),
                           rx1 + bx2 * (rx2 - rx1), ry1 + by2 * (ry2 - ry1))
                    detections.append(Detection(canonical(name, self.aliases), conf, box))
        if len(self._regions()) > 1:
            detections = merge(detections, threshold=0.4)  # a mesma pessoa vista em dois blocos vira uma
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
