from datetime import datetime

from vigia_detector.engine import merge
from vigia_detector.labels import ALIASES, canonical
from vigia_detector.rules import Detection, RuleTracker, evaluate_frame, in_schedule, point_in_polygon

PERSON = Detection("person", 0.9, (0.40, 0.30, 0.60, 0.90))
HELMET = Detection("helmet", 0.8, (0.45, 0.28, 0.55, 0.38))
NO_HELMET = Detection("no_helmet", 0.8, (0.45, 0.28, 0.55, 0.38))
VEST = Detection("vest", 0.8, (0.42, 0.45, 0.58, 0.65))
LEFT_ZONE = [[0, 0], [0.3, 0], [0.3, 1], [0, 1]]
NOON = datetime(2026, 1, 1, 12)


def rule(**kw):
    return {"id": 1, "type": "ppe_missing", "zone": [], "params": {}, "min_confidence": 0.5,
            "min_duration": 0, "cooldown": 0, **kw}


def test_point_in_polygon():
    square = [[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8]]
    assert point_in_polygon((0.5, 0.5), square)
    assert not point_in_polygon((0.1, 0.5), square)
    assert point_in_polygon((0.1, 0.5), [])  # sem zona = imagem inteira


def test_ppe_ok_with_helmet():
    assert evaluate_frame(rule(params={"required": ["helmet"]}), [PERSON, HELMET]) is None


def test_ppe_missing_without_helmet_detection():
    v = evaluate_frame(rule(params={"required": ["helmet"]}), [PERSON])
    assert v and "capacete" in v.message and v.detections == [PERSON]


def test_ppe_negative_label_wins():
    v = evaluate_frame(rule(params={"required": ["helmet"]}), [PERSON, HELMET, NO_HELMET])
    assert v is not None


def test_ppe_multiple_items():
    v = evaluate_frame(rule(params={"required": ["helmet", "vest"]}), [PERSON, HELMET])
    assert v and "colete" in v.message and "capacete" not in v.message
    assert evaluate_frame(rule(params={"required": ["helmet", "vest"]}), [PERSON, HELMET, VEST]) is None


def test_helmet_of_other_person_does_not_count():
    far_helmet = Detection("helmet", 0.9, (0.05, 0.05, 0.1, 0.1))
    assert evaluate_frame(rule(params={"required": ["helmet"]}), [PERSON, far_helmet]) is not None


def test_low_confidence_ignored():
    weak = Detection("person", 0.3, PERSON.box)
    assert evaluate_frame(rule(params={"required": ["helmet"]}), [weak]) is None


def test_restricted_zone_uses_feet():
    r = rule(type="restricted_zone", zone=LEFT_ZONE)
    assert evaluate_frame(r, [PERSON]) is None
    inside = Detection("person", 0.9, (0.05, 0.3, 0.2, 0.9))
    assert evaluate_frame(r, [inside]) is not None


def test_fire_smoke():
    v = evaluate_frame(rule(type="fire_smoke"), [Detection("smoke", 0.7, (0.1, 0.1, 0.3, 0.3))])
    assert v and "Fumaça" in v.message


def test_max_people():
    r = rule(type="max_people", params={"max_people": 1})
    other = Detection("person", 0.9, (0.0, 0.3, 0.2, 0.9))
    assert evaluate_frame(r, [PERSON]) is None
    assert evaluate_frame(r, [PERSON, other]) is not None


def test_schedule_including_overnight():
    assert in_schedule({"start_hour": 8, "end_hour": 18}, NOON)
    assert not in_schedule({"start_hour": 8, "end_hour": 18}, datetime(2026, 1, 1, 19))
    assert in_schedule({"start_hour": 22, "end_hour": 6}, datetime(2026, 1, 1, 2))
    assert not in_schedule({"start_hour": 22, "end_hour": 6}, NOON)
    assert in_schedule({}, NOON)


def test_tracker_min_duration_and_cooldown():
    tracker = RuleTracker(grace=1.0)
    rules = [rule(min_duration=2, cooldown=10)]
    assert tracker.update(rules, [PERSON], 0.0, NOON) == []
    assert tracker.update(rules, [PERSON], 1.0, NOON) == []
    assert len(tracker.update(rules, [PERSON], 2.0, NOON)) == 1
    assert tracker.update(rules, [PERSON], 3.0, NOON) == []  # em cooldown
    assert len(tracker.update(rules, [PERSON], 12.5, NOON)) == 1


def test_tracker_grace_and_reset():
    tracker = RuleTracker(grace=1.0)
    rules = [rule(min_duration=2, cooldown=0)]
    tracker.update(rules, [PERSON], 0.0, NOON)
    tracker.update(rules, [], 0.5, NOON)  # falha curta: mantém contagem
    assert len(tracker.update(rules, [PERSON], 2.0, NOON)) == 1

    tracker = RuleTracker(grace=1.0)
    tracker.update(rules, [PERSON], 0.0, NOON)
    tracker.update(rules, [], 2.0, NOON)  # ausência longa: reinicia
    assert tracker.update(rules, [PERSON], 3.0, NOON) == []


def test_tracker_respects_schedule():
    tracker = RuleTracker()
    rules = [rule(start_hour=22, end_hour=6)]
    assert tracker.update(rules, [PERSON], 0.0, NOON) == []


def test_label_aliases():
    assert canonical("NO-Hardhat", ALIASES) == "no_helmet"
    assert canonical("Safety Vest", ALIASES) == "vest"
    assert canonical("Person", ALIASES) == "person"
    assert canonical("forklift", ALIASES) == "forklift"


def test_merge_removes_duplicate_people():
    dup = Detection("person", 0.7, (0.41, 0.31, 0.61, 0.91))
    merged = merge([PERSON, dup, HELMET])
    assert PERSON in merged and dup not in merged and HELMET in merged
