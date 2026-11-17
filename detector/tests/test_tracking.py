"""Rastreamento de pessoas: confirmação, número estável, objeto parado e um alerta por pessoa."""

from datetime import datetime

from vigia_detector.rules import Detection, RuleTracker
from vigia_detector.tracking import Tracker

NOW = datetime(2026, 11, 17, 10, 0)


def person(x, y=0.3, conf=0.8, w=0.08, h=0.3):
    return Detection("person", conf, (x, y, x + w, y + h))


def test_ghost_of_one_frame_is_dropped_and_ids_are_stable():
    tr = Tracker(min_hits=2)
    assert tr.update([person(0.1)], 0.0) == []                 # 1ª aparição: ainda não confirmada
    out = tr.update([person(0.11)], 0.33)
    assert len(out) == 1 and out[0].track_id == 1
    tr.update([person(0.12), person(0.7)], 0.66)               # chega uma segunda pessoa
    out = tr.update([person(0.7), person(0.13)], 1.0)          # ordem trocada: o número acompanha a pessoa
    ids = {round(d.box[0], 2): d.track_id for d in out}
    assert ids == {0.13: 1, 0.7: 2}
    # "pessoa" de um quadro só (reflexo) não chega às regras
    assert all(d.box[0] != 0.4 for d in tr.update([person(0.14), person(0.7), person(0.4)], 1.33))


def test_fast_walk_keeps_same_id_and_other_labels_pass():
    tr = Tracker(min_hits=1)
    helmet = Detection("helmet", 0.9, (0.1, 0.3, 0.15, 0.35))
    out = tr.update([person(0.1), helmet], 0.0)
    assert helmet in out
    # andou mais que a largura da caixa entre duas análises (sem sobreposição)
    out = tr.update([person(0.2)], 0.5)
    assert out[0].track_id == 1


def test_low_confidence_continues_but_does_not_create():
    tr = Tracker(min_hits=1, high_conf=0.45)
    assert tr.update([person(0.1, conf=0.3)], 0.0) == []        # fraca e nova: ignora
    tr.update([person(0.1, conf=0.8)], 0.3)
    out = tr.update([person(0.11, conf=0.3)], 0.6)              # fraca, mas continua um rastro: mantém
    assert out and out[0].track_id == 1  # a detecção fraca de antes não criou rastro


def test_static_object_is_ignored_and_remembered():
    tr = Tracker(min_hits=2, static_seconds=60, max_age=2)
    t = 0.0
    while t < 59:
        out = tr.update([person(0.9, conf=0.5)], t)
        if t > 0:
            assert out[0].track_id == 1                         # antes de 60 s ainda conta como pessoa
        t += 1
    for _ in range(3):
        t += 1
        out = tr.update([person(0.9, conf=0.5)], t)
    assert out == []                                            # parado há 60 s: tijolo, não gente
    # some e volta no mesmo lugar: continua ignorado
    t += 10
    tr.update([], t)
    for _ in range(3):
        t += 1
        assert tr.update([person(0.9, conf=0.5)], t) == []
    # gente de verdade se mexe: uma pessoa parada que se movimenta não é ignorada
    tr2 = Tracker(min_hits=1, static_seconds=60)
    for i in range(80):
        out = tr2.update([person(0.3 + (0.01 if i % 2 else 0))], float(i))
    assert out


def test_one_alert_per_person():
    rule = {"id": 1, "type": "restricted_zone", "zone": [], "min_duration": 0, "cooldown": 30}
    rt = RuleTracker(realert=600)
    a = Detection("person", 0.9, (0.1, 0.3, 0.2, 0.9), track_id=7)
    assert len(rt.update([rule], [a], 0, NOW)) == 1
    # a mesma pessoa continua na zona: passou o cooldown, mas não repete o alerta
    assert rt.update([rule], [a], 40, NOW) == []
    assert rt.update([rule], [a], 200, NOW) == []
    # outra pessoa entra: novo alerta
    b = Detection("person", 0.9, (0.5, 0.3, 0.6, 0.9), track_id=8)
    assert len(rt.update([rule], [a, b], 240, NOW)) == 1
    # lembrete depois de `realert` segundos
    assert len(rt.update([rule], [a, b], 900, NOW)) == 1
    # sem rastreamento (track_id None) vale o comportamento antigo: alerta a cada cooldown
    rt2 = RuleTracker()
    c = Detection("person", 0.9, (0.1, 0.3, 0.2, 0.9))
    assert len(rt2.update([rule], [c], 0, NOW)) == 1 and len(rt2.update([rule], [c], 40, NOW)) == 1
