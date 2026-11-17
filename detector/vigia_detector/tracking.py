"""Rastreamento de pessoas entre quadros (no estilo ByteTrack, sem dependências além do numpy).

Cada pessoa recebe um número (track_id) que se mantém enquanto ela está na cena. Isso permite:

- **Confirmação:** uma "pessoa" que aparece num quadro só e some (sombra, reflexo, pilha de tijolos vista
  de relance) não chega às regras; é preciso aparecer em `min_hits` análises seguidas.
- **Objeto parado:** algo que fica *exatamente* no mesmo lugar por `static_seconds` (pessoa de verdade
  sempre se mexe um pouco) é marcado como objeto fixo e ignorado; o local fica memorizado, então o
  mesmo objeto não volta a ser "pessoa" se o rastro for perdido e recriado.
- **Um alerta por pessoa:** as regras sabem quem já gerou alerta (ver rules.RuleTracker).

Associação em duas etapas, como no ByteTrack: primeiro as detecções de confiança alta, depois as de
confiança baixa (só para continuar rastros que já existem – detecção fraca não cria pessoa nova)."""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field, replace

from .rules import Detection

log = logging.getLogger("vigia.tracking")


def iou(a: tuple, b: tuple) -> float:
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def _center(box: tuple) -> tuple[float, float]:
    return (box[0] + box[2]) / 2, (box[1] + box[3]) / 2


def _affinity(track_box: tuple, det_box: tuple) -> float:
    """IoU; com pouca sobreposição (pessoa andando rápido em poucas análises por segundo), aceita
    se o centro andou menos que ~meia altura da pessoa."""
    v = iou(track_box, det_box)
    if v >= 0.2:
        return v
    (tx, ty), (dx, dy) = _center(track_box), _center(det_box)
    size = max(track_box[3] - track_box[1], det_box[3] - det_box[1], 1e-6)
    dist = ((tx - dx) ** 2 + (ty - dy) ** 2) ** 0.5 / size
    return 0.19 * (1 - dist / 0.6) if dist < 0.6 else 0.0


@dataclass
class Track:
    id: int
    label: str
    box: tuple
    confidence: float
    first_ts: float
    last_ts: float
    hits: int = 1
    static: bool = False
    history: deque = field(default_factory=lambda: deque(maxlen=600))  # (ts, cx, cy, altura)

    def add(self, det: Detection, now: float) -> None:
        self.box, self.confidence, self.last_ts = det.box, det.confidence, now
        self.hits += 1
        cx, cy = _center(det.box)
        self.history.append((now, cx, cy, det.box[3] - det.box[1]))


class Tracker:
    def __init__(self, labels: tuple[str, ...] = ("person",), min_hits: int = 2, max_age: float = 2.0,
                 high_conf: float = 0.45, static_seconds: float = 300.0, static_move: float = 0.006,
                 static_memory: float = 3600.0):
        self.labels = set(labels)
        self.min_hits = max(1, min_hits)
        self.max_age = max_age
        self.high_conf = high_conf
        self.static_seconds = static_seconds  # 0 desliga o filtro de objeto parado
        self.static_move = static_move  # deslocamento máximo (fração do quadro) para contar como parado
        self.static_memory = static_memory
        self.tracks: list[Track] = []
        self.static_spots: list[tuple[tuple, float]] = []  # (caixa, último momento visto)
        self._next_id = 1

    # ---------- associação ----------
    def _match(self, tracks: list[Track], dets: list[Detection]) -> tuple[list[tuple[Track, Detection]], list[Track], list[Detection]]:
        pairs = sorted(((_affinity(t.box, d.box), ti, di) for ti, t in enumerate(tracks) for di, d in enumerate(dets)),
                       reverse=True)
        used_t, used_d, matched = set(), set(), []
        for score, ti, di in pairs:
            if score <= 0:
                break
            if ti in used_t or di in used_d:
                continue
            used_t.add(ti)
            used_d.add(di)
            matched.append((tracks[ti], dets[di]))
        return (matched, [t for i, t in enumerate(tracks) if i not in used_t],
                [d for i, d in enumerate(dets) if i not in used_d])

    # ---------- objeto parado ----------
    def _is_static(self, t: Track, now: float) -> bool:
        if not self.static_seconds or now - t.first_ts < self.static_seconds:
            return False
        window = [h for h in t.history if now - h[0] <= self.static_seconds]
        if len(window) < 5:
            return False
        xs, ys, hs = [h[1] for h in window], [h[2] for h in window], [h[3] for h in window]
        moved = max(max(xs) - min(xs), max(ys) - min(ys))
        size_change = (max(hs) - min(hs)) / max(max(hs), 1e-6)
        return moved <= self.static_move and size_change <= 0.06

    def _at_static_spot(self, box: tuple, now: float) -> bool:
        for i, (spot, _) in enumerate(self.static_spots):
            if iou(spot, box) >= 0.7:
                self.static_spots[i] = (spot, now)
                return True
        return False

    # ---------- quadro ----------
    def update(self, detections: list[Detection], now: float) -> list[Detection]:
        """Devolve as detecções com track_id nas pessoas confirmadas; pessoas não confirmadas e objetos
        parados saem da lista. Os demais rótulos (capacete, fogo...) passam sem mudança."""
        others = [d for d in detections if d.label not in self.labels]
        out: list[Detection] = []
        for label in self.labels:
            dets = [d for d in detections if d.label == label]
            tracks = [t for t in self.tracks if t.label == label]
            high = [d for d in dets if d.confidence >= self.high_conf]
            low = [d for d in dets if d.confidence < self.high_conf]
            m1, rest, new = self._match(tracks, high)
            m2, _, _ = self._match(rest, low)
            for t, d in m1 + m2:
                t.add(d, now)
            for d in new:
                t = Track(self._next_id, label, d.box, d.confidence, now, now)
                t.history.append((now, *_center(d.box), d.box[3] - d.box[1]))
                t.static = self._at_static_spot(d.box, now)
                self._next_id += 1
                self.tracks.append(t)
                m1.append((t, d))
            for t, d in m1 + m2:
                if not t.static and self._is_static(t, now):
                    t.static = True
                    self.static_spots.append((t.box, now))
                    log.info("objeto parado reconhecido como %s (rastro #%d) passa a ser ignorado", label, t.id)
                elif t.static and t.history and self._moved_recently(t, now):
                    t.static = False  # voltou a se mexer: era gente parada mesmo
                if t.hits >= self.min_hits and not t.static:
                    out.append(replace(d, track_id=t.id))
        self.tracks = [t for t in self.tracks if now - t.last_ts <= self.max_age]
        self.static_spots = [(b, ts) for b, ts in self.static_spots if now - ts <= self.static_memory]
        return out + others

    def _moved_recently(self, t: Track, now: float) -> bool:
        recent = [h for h in t.history if now - h[0] <= 10]
        if len(recent) < 2:
            return False
        xs, ys = [h[1] for h in recent], [h[2] for h in recent]
        return max(max(xs) - min(xs), max(ys) - min(ys)) > self.static_move * 4

    @property
    def active(self) -> int:
        return sum(1 for t in self.tracks if t.hits >= self.min_hits and not t.static)
