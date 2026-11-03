"""Falsos alarmes de EPI: sem modelo de capacete, pessoa longe demais, objeto que não é pessoa em pé,
capacete fora da cabeça; e a segunda olhada recortando cada pessoa."""

from types import SimpleNamespace

import numpy as np

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
    names = {0: "Hardhat", 1: "NO-Hardhat"}

    def __init__(self):
        self.calls = []

    def predict(self, img, **kw):
        self.calls.append(img.shape)
        boxes = SimpleNamespace(xyxyn=_T([[0.3, 0.05, 0.7, 0.25]]), conf=_T([0.8]), cls=_T([0]))
        return [SimpleNamespace(names=self.names, boxes=boxes)]


class _T(list):
    def tolist(self):
        return list(self)


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
