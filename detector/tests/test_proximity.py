"""Regra "pessoa perto de máquina/veículo": distância, máquina em movimento, operador na cabine e zona."""

from vigia_detector.rules import Detection, distance_m, evaluate_frame, unverifiable
from vigia_detector.tracking import Tracker

ASPECT = 16 / 9


def rule(**params):
    return {"id": 9, "type": "machine_proximity", "zone": [], "min_confidence": 0.4, "_aspect": ASPECT,
            "params": {"distance_m": 2.0, **params}}


def person(x, bottom=0.8, h=0.3):
    return Detection("person", 0.9, (x, bottom - h, x + 0.05, bottom), track_id=1)


def forklift(x, bottom=0.8, moving=True):
    return Detection("forklift", 0.9, (x, bottom - 0.3, x + 0.2, bottom), track_id=2, moving=moving)


def test_distance_uses_person_height_as_ruler():
    # pessoa de 1,7 m ocupa 0,3 da altura; folga lateral de 0,05 da largura ≈ 0,05·16/9/0,3·1,7 ≈ 0,5 m
    assert abs(distance_m(person(0.3), forklift(0.4), ASPECT) - 0.5) < 0.05
    # base da pessoa bem acima da base da máquina = pessoa mais ao fundo da cena: longe
    assert distance_m(person(0.62, bottom=0.45), forklift(0.4), ASPECT) > 2


def test_alerts_person_near_moving_machine():
    v = evaluate_frame(rule(), [person(0.3), forklift(0.4)])
    assert v and v.message == "1 pessoa(s) a ~0,5 m de empilhadeira em movimento"
    assert {d.label for d in v.detections} == {"person", "forklift"}
    assert evaluate_frame(rule(), [person(0.05), forklift(0.4)]) is None     # longe (~3 m)
    assert evaluate_frame(rule(distance_m=5), [person(0.05), forklift(0.4)])  # distância configurável


def test_parked_machine_and_operator_do_not_alert():
    assert evaluate_frame(rule(), [person(0.3), forklift(0.4, moving=False)]) is None
    assert evaluate_frame(rule(only_moving=False), [person(0.3), forklift(0.4, moving=False)])
    # operador dentro da máquina
    operator = Detection("person", 0.9, (0.45, 0.55, 0.5, 0.78), track_id=3)
    assert evaluate_frame(rule(), [operator, forklift(0.4)]) is None


def test_machine_filter_and_zone():
    truck = Detection("truck", 0.9, (0.4, 0.5, 0.6, 0.8), track_id=4, moving=True)
    assert evaluate_frame(rule(machines=["forklift"]), [person(0.3), truck]) is None
    assert "caminhão" in evaluate_frame(rule(), [person(0.3), truck]).message
    # carro passando na rua, fora da zona da obra (zona = metade de baixo da imagem)
    zoned = {**rule(), "zone": [[0, 0.85], [1, 0.85], [1, 1], [0, 1]]}
    assert evaluate_frame(zoned, [person(0.3, bottom=0.9), truck]) is None


def test_unverifiable_when_no_model_knows_the_machine():
    r = {**rule(machines=["forklift"]), "_detectable": {"person", "car", "truck"}}
    assert unverifiable(r) == ["forklift"]
    r = {**rule(), "_detectable": {"person", "car", "truck"}}
    assert unverifiable(r) == []


def test_tracker_marks_moving_machines():
    tr = Tracker(min_hits=2)
    parked = lambda: Detection("truck", 0.9, (0.1, 0.5, 0.3, 0.8))  # noqa: E731
    out = []
    for i in range(6):
        t = i * 0.5
        out = tr.update([parked(), Detection("forklift", 0.9, (0.5 + 0.03 * i, 0.5, 0.7 + 0.03 * i, 0.8))], t)
    moving = {d.label: d.moving for d in out}
    assert moving == {"truck": False, "forklift": True}
    # máquina parada por muito tempo continua sendo máquina (o filtro de objeto parado é só para pessoas)
    tr2 = Tracker(min_hits=1, static_seconds=10)
    for i in range(30):
        out = tr2.update([parked()], float(i))
    assert out and out[0].label == "truck"
