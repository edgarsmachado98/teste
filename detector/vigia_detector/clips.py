"""Clipes das ocorrências: alguns segundos antes e depois de cada desvio.

Guarda os últimos quadros analisados (já em JPEG, com as marcações) num buffer circular.
Quando um desvio é detectado, o clipe começa com o buffer e continua por `after` segundos.
Não depende de codecs de vídeo: o painel exibe a sequência de quadros."""

from __future__ import annotations

import uuid
from collections import deque
from dataclasses import dataclass, field


@dataclass
class _Pending:
    clip_id: str
    start: float
    until: float
    frames: list[bytes] = field(default_factory=list)


class ClipRecorder:
    def __init__(self, before: float = 5.0, after: float = 5.0, max_frames: int = 90):
        self.before = before
        self.after = after
        self.max_frames = max_frames
        self._buffer: deque[tuple[float, bytes]] = deque()
        self._pending: list[_Pending] = []

    def add(self, ts: float, jpeg: bytes) -> list[tuple[str, list[bytes], float]]:
        """Acrescenta um quadro. Devolve os clipes concluídos: (clip_id, quadros, duração)."""
        self._buffer.append((ts, jpeg))
        while self._buffer and self._buffer[0][0] < ts - self.before:
            self._buffer.popleft()

        finished = []
        for clip in list(self._pending):
            if len(clip.frames) < self.max_frames:
                clip.frames.append(jpeg)
            if ts >= clip.until:
                self._pending.remove(clip)
                finished.append((clip.clip_id, clip.frames, max(ts - clip.start, 0.1)))
        return finished

    def start(self, ts: float) -> str:
        """Inicia um clipe com os quadros do buffer (inclui o quadro atual, se já adicionado)."""
        frames = [jpeg for t, jpeg in self._buffer if t >= ts - self.before]
        start = next((t for t, _ in self._buffer if t >= ts - self.before), ts)
        clip = _Pending(uuid.uuid4().hex, start, ts + self.after, frames[-self.max_frames:])
        self._pending.append(clip)
        return clip.clip_id

    def flush(self) -> list[tuple[str, list[bytes], float]]:
        """Encerra os clipes em andamento (ex.: câmera desconectada)."""
        done = [(c.clip_id, c.frames, max(self._buffer[-1][0] - c.start, 0.1) if self._buffer else 0.1)
                for c in self._pending if c.frames]
        self._pending.clear()
        return done
