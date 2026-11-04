"""Motores de inferência do detector.

- ``.onnx`` → ONNX Runtime (licença MIT). Aceita modelos exportados do YOLOX ou do D-FINE/RT-DETR, que podem
  ser treinados com ferramentas de licença permissiva (Apache-2.0). É o caminho para vender o VigIA sem
  depender da licença AGPL-3.0 da Ultralytics.
- ``.pt`` → Ultralytics YOLO (AGPL-3.0: uso comercial exige a Enterprise License da Ultralytics).

Cada modelo ONNX acompanha um arquivo .json com o formato e as classes, por exemplo ``modelos/epi.json``::

    {"format": "yolox", "classes": ["person", "helmet", "no_helmet"], "input_size": 640,
     "license": "Apache-2.0", "source": "treinado com YOLOX sobre imagens do cliente"}

Formatos: ``yolox`` (saída [1, N, 5+C]; com ou sem decodificação na exportação, ``"decoded": true/false``) e
``detr`` (D-FINE / RT-DETR: entradas imagem + tamanho original; saídas labels, boxes, scores).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np

log = logging.getLogger("vigia.backends")

# Uma detecção crua do modelo: (nome da classe no modelo, confiança, caixa normalizada x1, y1, x2, y2)
Raw = tuple[str, float, tuple[float, float, float, float]]


class Backend:
    path: str
    names: list[str]
    license: str = ""

    def predict(self, image: np.ndarray, imgsz: int, conf: float) -> list[Raw]:
        raise NotImplementedError


class UltralyticsBackend(Backend):
    license = "AGPL-3.0 (Ultralytics) – uso comercial exige Enterprise License"

    def __init__(self, path: str, device: str | None = None):
        from ultralytics import YOLO  # opcional: só para modelos .pt

        self.path, self.device = path, device
        self.model = YOLO(path)
        self.names = list(self.model.names.values())

    def predict(self, image, imgsz, conf):
        result = self.model.predict(image, conf=conf, imgsz=imgsz, device=self.device, verbose=False)[0]
        return [(result.names[int(c)], float(s), tuple(b)) for b, s, c in
                zip(result.boxes.xyxyn.tolist(), result.boxes.conf.tolist(), result.boxes.cls.tolist())]


def _nms(boxes: np.ndarray, scores: np.ndarray, iou: float = 0.45) -> list[int]:
    """Supressão de caixas sobrepostas (por classe é feito por quem chama)."""
    order = scores.argsort()[::-1]
    keep = []
    while order.size:
        i = order[0]
        keep.append(int(i))
        if order.size == 1:
            break
        xx1 = np.maximum(boxes[i, 0], boxes[order[1:], 0])
        yy1 = np.maximum(boxes[i, 1], boxes[order[1:], 1])
        xx2 = np.minimum(boxes[i, 2], boxes[order[1:], 2])
        yy2 = np.minimum(boxes[i, 3], boxes[order[1:], 3])
        inter = np.clip(xx2 - xx1, 0, None) * np.clip(yy2 - yy1, 0, None)
        area = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
        ovr = inter / (area[i] + area[order[1:]] - inter + 1e-9)
        order = order[1:][ovr <= iou]
    return keep


class OnnxBackend(Backend):
    def __init__(self, path: str, device: str | None = None):
        import onnxruntime as ort

        meta_path = Path(path).with_suffix(".json")
        if not meta_path.exists():
            raise ValueError(f"falta {meta_path.name} ao lado de {Path(path).name} (formato e classes do modelo)")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        self.path = path
        self.format = meta.get("format", "yolox")
        if self.format not in ("yolox", "detr"):
            raise ValueError(f"formato de modelo desconhecido: {self.format} (use yolox ou detr)")
        self.names = list(meta["classes"])
        self.input_size = int(meta.get("input_size", 640))
        self.decoded = bool(meta.get("decoded", False))
        self.license = meta.get("license", "")
        providers = ort.get_available_providers()
        if device in (None, "", "cpu") or "CUDAExecutionProvider" not in providers:
            providers = ["CPUExecutionProvider"]
        self.session = ort.InferenceSession(path, providers=providers)
        self.inputs = [i.name for i in self.session.get_inputs()]

    # ---------- YOLOX ----------
    def _yolox(self, image: np.ndarray, conf: float) -> list[Raw]:
        import cv2

        s = self.input_size
        h, w = image.shape[:2]
        ratio = min(s / h, s / w)
        padded = np.full((s, s, 3), 114, dtype=np.uint8)  # letterbox, como no treino do YOLOX
        resized = cv2.resize(image, (int(w * ratio), int(h * ratio)), interpolation=cv2.INTER_LINEAR)
        padded[: resized.shape[0], : resized.shape[1]] = resized
        blob = padded.transpose(2, 0, 1)[None].astype(np.float32)
        out = self.session.run(None, {self.inputs[0]: blob})[0][0]
        if not self.decoded:  # decodificação das grades (strides 8, 16, 32)
            grids, strides = [], []
            for stride in (8, 16, 32):
                hs, ws = s // stride, s // stride
                xv, yv = np.meshgrid(np.arange(ws), np.arange(hs))
                grids.append(np.stack((xv, yv), 2).reshape(-1, 2))
                strides.append(np.full((hs * ws, 1), stride))
            grids, strides = np.concatenate(grids), np.concatenate(strides)
            out = out.copy()
            out[:, :2] = (out[:, :2] + grids) * strides
            out[:, 2:4] = np.exp(out[:, 2:4]) * strides
        scores_all = out[:, 4:5] * out[:, 5:]
        cls = scores_all.argmax(1)
        score = scores_all[np.arange(len(cls)), cls]
        sel = score >= conf
        if not sel.any():
            return []
        boxes = out[sel, :4]
        xyxy = np.stack([boxes[:, 0] - boxes[:, 2] / 2, boxes[:, 1] - boxes[:, 3] / 2,
                         boxes[:, 0] + boxes[:, 2] / 2, boxes[:, 1] + boxes[:, 3] / 2], 1) / ratio
        return self._finish(xyxy, score[sel], cls[sel], w, h, nms=True)

    # ---------- D-FINE / RT-DETR ----------
    def _detr(self, image: np.ndarray, conf: float) -> list[Raw]:
        import cv2

        s = self.input_size
        h, w = image.shape[:2]
        rgb = cv2.cvtColor(cv2.resize(image, (s, s)), cv2.COLOR_BGR2RGB)
        blob = (rgb.transpose(2, 0, 1)[None] / 255.0).astype(np.float32)
        feeds = {self.inputs[0]: blob}
        if len(self.inputs) > 1:
            feeds[self.inputs[1]] = np.array([[w, h]], dtype=np.int64)  # caixas voltam no tamanho original
        outs = {o.name: v for o, v in zip(self.session.get_outputs(), self.session.run(None, feeds))}
        labels = outs.get("labels", list(outs.values())[0])[0]
        boxes = outs.get("boxes", list(outs.values())[1])[0]
        scores = outs.get("scores", list(outs.values())[2])[0]
        sel = scores >= conf
        if len(self.inputs) == 1:  # exportado sem o tamanho original: caixas na escala da entrada
            boxes = boxes * np.array([w / s, h / s, w / s, h / s])
        return self._finish(boxes[sel], scores[sel], labels[sel].astype(int), w, h, nms=False)

    def _finish(self, xyxy, scores, cls, w, h, nms: bool) -> list[Raw]:
        keep = range(len(scores))
        if nms:
            keep = [i for c in np.unique(cls) for i in np.where(cls == c)[0][_nms(xyxy[cls == c], scores[cls == c])]]
        result = []
        for i in keep:
            c = int(cls[i])
            if not 0 <= c < len(self.names):
                continue
            x1, y1, x2, y2 = (float(v) for v in xyxy[i])
            box = (max(0.0, x1 / w), max(0.0, y1 / h), min(1.0, x2 / w), min(1.0, y2 / h))
            if box[2] > box[0] and box[3] > box[1]:
                result.append((self.names[c], float(scores[i]), box))
        return result

    def predict(self, image, imgsz, conf):
        return self._yolox(image, conf) if self.format == "yolox" else self._detr(image, conf)


def load_backend(path: str, device: str | None = None) -> Backend:
    if path.lower().endswith(".onnx"):
        return OnnxBackend(path, device)
    return UltralyticsBackend(path, device)
