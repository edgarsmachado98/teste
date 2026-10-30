"""Verifica se a imagem da câmera está útil: escura, obstruída/desfocada ou congelada.

Um problema só é reportado depois de persistir por algum tempo, para não alarmar por
um vulto passando na frente da lente ou uma troca rápida de iluminação."""

from __future__ import annotations

import cv2
import numpy as np

DARK_MEAN = 25          # brilho médio (0-255) abaixo disso = imagem escura
UNIFORM_STD = 8         # imagem quase uniforme = lente tampada
BLUR_LAPLACIAN = 4      # pouquíssimo detalhe = lente suja/desfocada
FROZEN_DIFF = 0.05      # quadros idênticos (câmeras reais sempre têm ruído ou relógio na tela)
PERSIST_SECONDS = 30
FROZEN_SECONDS = 120


def classify(gray: np.ndarray) -> str:
    if gray.mean() < DARK_MEAN:
        return "escura"
    if gray.std() < UNIFORM_STD or cv2.Laplacian(gray, cv2.CV_64F).var() < BLUR_LAPLACIAN:
        return "obstruida"
    return "ok"


class ImageHealth:
    def __init__(self) -> None:
        self.state = "ok"
        self._candidate = "ok"
        self._since = 0.0
        self._prev: np.ndarray | None = None
        self._frozen_since: float | None = None

    def update(self, frame: np.ndarray, now: float) -> str:
        gray = cv2.cvtColor(cv2.resize(frame, (160, 90)), cv2.COLOR_BGR2GRAY)

        if self._prev is not None and cv2.absdiff(gray, self._prev).mean() < FROZEN_DIFF:
            self._frozen_since = self._frozen_since or now
        else:
            self._frozen_since = None
        self._prev = gray

        if self._frozen_since is not None and now - self._frozen_since >= FROZEN_SECONDS:
            self.state = "congelada"
            return self.state

        current = classify(gray)
        if current != self._candidate:
            self._candidate, self._since = current, now
        if current == "ok":
            self.state = "ok"
        elif now - self._since >= PERSIST_SECONDS:
            self.state = current
        return self.state
