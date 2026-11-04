"""Falsos alarmes de EPI: sem modelo de capacete, pessoa longe demais, objeto que não é pessoa em pé,
capacete fora da cabeça; e a segunda olhada recortando cada pessoa."""

import numpy as np
import pytest

from vigia_detector.engine import Engine
from vigia_detector.rules import Detection, evaluate_frame, observe, unverifiable

WORKER = Detection("person", 0.9, (0.40, 0.30, 0.46, 0.80))      # alta e estreita: pessoa em pé
HELMET_ON_HEAD = Detection("helmet", 0.8, (0.41, 0.28, 0.45, 0.34))
HELMET_ON_GROUND = Detection("helmet", 0.8, (0.41, 0.74, 0.45, 0.80))
NO_HELMET = Detection("no_helmet", 0.8, (0.41, 0.29, 0.45, 0.35))
PPE_MODEL = {"person", "helmet", "no_helmet", "vest"}
COCO_ONLY = {"person", "car", "truck"}


def rule(detectable, **params):
    return {"id": 1, "type": "ppe_missing", "zone": [], "min_confidence": 0.5, "min_duration": 0, "cooldown": 0,
            "params": {"required": ["helmet"], **params}, "_detectable": detectable, "_aspect": 16 / 9}


def test_without_helmet_model_nobody_is_accused():
    r = rule(COCO_ONLY)
    assert evaluate_frame(r, [WORKER]) is None          # antes: "1 pessoa(s) sem capacete" para todo mundo
    assert unverifiable(r) == ["helmet"]
    assert observe(r, [WORKER]) is None                 # nem entra no índice de conformidade


def test_white_helmet_on_head_ok_and_on_ground_missing():
    assert evaluate_frame(rule(PPE_MODEL), [WORKER, HELMET_ON_HEAD]) is None
    v = evaluate_frame(rule(PPE_MODEL), [WORKER, HELMET_ON_GROUND])
    assert v and "capacete" in v.message
    assert evaluate_frame(rule(PPE_MODEL), [WORKER, HELMET_ON_HEAD, NO_HELMET]) is not None


def test_far_or_odd_shapes_are_not_judged():
    far = Detection("person", 0.9, (0.10, 0.40, 0.12, 0.46))       # 6% da altura da imagem
    mixer = Detection("person", 0.55, (0.20, 0.50, 0.32, 0.62))   # quase quadrado: betoneira, não pessoa em pé
    r = rule(PPE_MODEL)
    assert evaluate_frame(r, [far]) is None and evaluate_frame(r, [mixer]) is None
    assert observe(r, [far, mixer]) == (0, 0)
    assert observe(r, [WORKER, HELMET_ON_HEAD, far]) == (1, 0)
    # o cliente pode aceitar pessoas menores (câmera boa, cena aberta)
    assert evaluate_frame(rule(PPE_MODEL, min_person_height=0.05), [far]) is not None


class FakeModel:
    """Modelo de EPI que só encontra o capacete quando recebe o recorte ampliado da pessoa."""
    names = ["Hardhat", "NO-Hardhat"]
    path, license = "falso.onnx", "teste"

    def __init__(self):
        self.calls = []

    def predict(self, img, imgsz, conf):
        self.calls.append(img.shape)
        return [("Hardhat", 0.8, (0.3, 0.05, 0.7, 0.25))]


def test_second_look_maps_crop_back_to_frame():
    eng = object.__new__(Engine)
    eng.aliases = {"hardhat": "helmet", "no_hardhat": "no_helmet", "person": "person"}
    eng.conf, eng.device, eng.crop_imgsz, eng.max_crops = 0.25, None, 320, 8
    model = FakeModel()
    eng.ppe_models = [model]
    frame = np.zeros((720, 1280, 3), np.uint8)
    found = eng._ppe_on_people(frame, [WORKER, Detection("car", 0.9, (0.0, 0.0, 0.1, 0.1))])
    assert len(model.calls) == 1                      # só a pessoa, não o carro
    (helmet,) = found
    assert helmet.label == "helmet"
    x1, y1, x2, y2 = helmet.box
    assert WORKER.box[0] - 0.02 <= x1 < x2 <= WORKER.box[2] + 0.02 and y1 < WORKER.box[1] + 0.1  # na cabeça
    assert evaluate_frame(rule(PPE_MODEL), [WORKER, helmet]) is None


class TileModel:
    """Só "enxerga" a pessoa quando ela ocupa bastante da imagem recebida (como um modelo real com gente pequena)."""
    names = ["person"]
    path, license = "falso.onnx", "teste"

    def predict(self, img, imgsz, conf):
        h, w = img.shape[:2]
        # pessoa fixa no quadro 1000x1000: x 600-640, y 600-700 → só aparece em pedaços menores que 700 px
        if w > 700:
            return []
        return self._find(img)

    def _find(self, img):
        ys, xs = np.where(img[:, :, 0] > 0)
        if not len(xs):
            return []
        h, w = img.shape[:2]
        return [("person", 0.8, (xs.min() / w, ys.min() / h, (xs.max() + 1) / w, (ys.max() + 1) / h))]


def test_tiles_find_small_people_once():
    frame = np.zeros((1000, 1000, 3), np.uint8)
    frame[600:700, 600:640] = 255
    eng = object.__new__(Engine)
    eng.aliases, eng.conf, eng.imgsz, eng.ppe_models = {"person": "person"}, 0.25, 640, []
    eng.models, eng.tile_overlap, eng.tile_conf = [TileModel()], 0.2, 0.55
    eng.tiles = (1, 1)
    assert eng.detect(frame) == []                    # imagem inteira: pessoa pequena demais
    eng.tiles = (2, 2)
    found = eng.detect(frame)
    assert len(found) == 1                            # vista em 2 blocos sobrepostos → uma pessoa só
    assert found[0].box == pytest.approx((0.6, 0.6, 0.64, 0.7), abs=0.01)


class BrickModel(TileModel):
    """Pilha de tijolos que, ampliada num bloco, parece gente com confiança baixa (caso real de obra)."""

    def _find(self, img):
        found = super()._find(img)
        return [(n, 0.45, b) for n, _, b in found]


def test_tile_only_detection_needs_higher_confidence():
    frame = np.zeros((1000, 1000, 3), np.uint8)
    frame[600:700, 600:640] = 255
    eng = object.__new__(Engine)
    eng.aliases, eng.conf, eng.imgsz, eng.ppe_models = {"person": "person"}, 0.25, 640, []
    eng.models, eng.tile_overlap, eng.tiles, eng.tile_conf = [BrickModel()], 0.2, (2, 2), 0.55
    assert eng.detect(frame) == []          # só nos blocos e com 0.45: descartada
    eng.tile_conf = 0.4
    assert len(eng.detect(frame)) == 1
