"""Novos EPIs: cinto paraquedista, botina, protetor auricular e protetor facial; importação de fotos para treino."""

from pathlib import Path

import pytest

from vigia_detector.dataset import CLASSES, import_images
from vigia_detector.labels import ALIASES, canonical
from vigia_detector.rules import Detection, evaluate_frame, unverifiable

WORKER = Detection("person", 0.9, (0.40, 0.20, 0.46, 0.90))
HARNESS = Detection("harness", 0.8, (0.40, 0.35, 0.46, 0.60))
BOOTS = Detection("boots", 0.8, (0.40, 0.84, 0.46, 0.91))
EAR = Detection("ear_protection", 0.7, (0.42, 0.24, 0.44, 0.28))
PPE_MODEL = {"person", "helmet", "harness", "no_harness", "boots", "ear_protection", "face_shield"}


def rule(required, detectable=PPE_MODEL):
    return {"id": 1, "type": "ppe_missing", "zone": [], "min_confidence": 0.5, "min_duration": 0, "cooldown": 0,
            "params": {"required": required}, "_detectable": detectable, "_aspect": 16 / 9}


def test_new_items_checked_in_the_right_body_region():
    assert evaluate_frame(rule(["harness", "boots", "ear_protection"]), [WORKER, HARNESS, BOOTS, EAR]) is None
    v = evaluate_frame(rule(["harness", "boots"]), [WORKER, HARNESS])
    assert v and "botina" in v.message and "cinto" not in v.message
    boots_at_head = Detection("boots", 0.8, (0.41, 0.20, 0.45, 0.26))  # caixa no lugar errado não vale
    assert "botina" in evaluate_frame(rule(["boots"]), [WORKER, boots_at_head]).message


def test_new_items_without_model_are_not_charged():
    r = rule(["helmet", "harness", "face_shield"], detectable={"person", "helmet"})
    assert unverifiable(r) == ["harness", "face_shield"]
    helmet = Detection("helmet", 0.9, (0.41, 0.18, 0.45, 0.24))
    assert evaluate_frame(r, [WORKER, helmet]) is None


def test_public_dataset_names_map_to_our_items():
    a = dict(ALIASES)
    assert canonical("Ear-mufs", a) == "ear_protection" and canonical("face-guard", a) == "face_shield"
    assert canonical("shoes", a) == "boots" and canonical("Safety Harness", a) == "harness"
    assert canonical("safety-vest", a) == "vest"


def test_old_class_numbers_unchanged():
    assert CLASSES[:13] == ["person", "helmet", "no_helmet", "vest", "no_vest", "glasses", "no_glasses",
                            "gloves", "no_gloves", "mask", "no_mask", "fire", "smoke"]
    assert {"harness", "boots", "ear_protection", "face_shield"} <= set(CLASSES)


def test_import_reference_photos(tmp_path):
    cv2 = pytest.importorskip("cv2")
    import numpy as np
    src = tmp_path / "fotos"
    src.mkdir()
    cv2.imwrite(str(src / "Trabalhador obra 1.webp"), np.full((360, 640, 3), 120, np.uint8))
    cv2.imwrite(str(src / "galpao.png"), np.full((360, 640, 3), 90, np.uint8))
    (src / "leia-me.txt").write_text("não é imagem")
    (src / "quebrada.jpg").write_bytes(b"nada")
    out = tmp_path / "coleta"
    r = import_images(src, out)
    assert r == {"imported": 2, "prelabeled": 0, "skipped": 1}
    names = sorted(p.name for p in (out / "images").glob("*.jpg"))
    assert names == ["ref-galpao.jpg", "ref-trabalhador-obra-1.jpg"]
    assert "face_shield" in (out / "classes.txt").read_text()
    import_images(src, out)  # importar de novo não sobrescreve
    assert len(list((out / "images").glob("*.jpg"))) == 4
