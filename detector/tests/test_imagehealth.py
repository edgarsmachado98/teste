import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("cv2")

from vigia_detector.imagehealth import FROZEN_SECONDS, PERSIST_SECONDS, ImageHealth  # noqa: E402

rng = np.random.default_rng(0)


def scene():
    return rng.integers(40, 220, (360, 640, 3), dtype=np.uint8)


def test_normal_scene_is_ok():
    health = ImageHealth()
    for t in range(0, 300, 5):
        assert health.update(scene(), t) == "ok"


def test_dark_only_after_persisting():
    health = ImageHealth()
    dark = np.full((360, 640, 3), 5, np.uint8)
    assert health.update(dark, 0) == "ok"
    assert health.update(dark, PERSIST_SECONDS - 1) == "ok"
    assert health.update(dark, PERSIST_SECONDS + 1) == "escura"
    assert health.update(scene(), PERSIST_SECONDS + 2) == "ok"


def test_covered_lens_is_obstructed():
    health = ImageHealth()
    covered = np.full((360, 640, 3), 120, np.uint8)
    covered[0, 0] = 121  # evita ser tratado como congelado antes
    health.update(covered, 0)
    assert health.update(covered, PERSIST_SECONDS + 1) == "obstruida"


def test_identical_frames_are_frozen():
    health = ImageHealth()
    frame = scene()
    for t in range(0, FROZEN_SECONDS, 10):
        assert health.update(frame, t) == "ok"
    # contagem começa no primeiro quadro repetido (t=10)
    assert health.update(frame, FROZEN_SECONDS + 9) == "ok"
    assert health.update(frame, FROZEN_SECONDS + 11) == "congelada"
    assert health.update(scene(), FROZEN_SECONDS + 12) == "ok"
