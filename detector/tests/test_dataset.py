import pytest

from vigia_detector.dataset import CLASSES, Collector, prepare, slug, yolo_lines
from vigia_detector.rules import Detection

np = pytest.importorskip("numpy")
pytest.importorskip("cv2")

PERSON = Detection("person", 0.9, (0.4, 0.3, 0.6, 0.9))
HELMET = Detection("helmet", 0.8, (0.45, 0.28, 0.55, 0.38))
CAR = Detection("car", 0.9, (0.0, 0.0, 0.1, 0.1))


def test_yolo_lines_and_slug():
    lines = yolo_lines([PERSON, HELMET, CAR])
    assert lines[0] == "0 0.500000 0.600000 0.200000 0.600000"
    assert lines[1].startswith(f"{CLASSES.index('helmet')} ")
    assert len(lines) == 2  # 'car' não é uma classe do treinamento
    assert slug("Prensa 1 – Galpão A") == "prensa-1-galpao-a"


def test_collector_rate_limits(tmp_path):
    col = Collector(tmp_path, interval=60, important_interval=5, max_images=3)
    frame = np.zeros((90, 160, 3), np.uint8)
    cam = {"id": 1, "name": "Prensa 1"}
    assert not col.offer(cam, frame, [CAR], 0)            # sem pessoa: não guarda
    assert col.offer(cam, frame, [PERSON, HELMET], 0)
    assert not col.offer(cam, frame, [PERSON], 30)        # dentro do intervalo
    assert col.offer(cam, frame, [PERSON], 40, important=True)  # desvio: intervalo curto
    assert col.offer({"id": 2, "name": "Doca"}, frame, [PERSON], 41)
    assert not col.offer({"id": 3, "name": "X"}, frame, [PERSON], 42)  # limite atingido
    assert len(list((tmp_path / "images").glob("*.jpg"))) == 3
    assert (tmp_path / "classes.txt").read_text().split() == CLASSES


def test_prepare_split(tmp_path):
    src = tmp_path / "coleta"
    col = Collector(src, interval=0, important_interval=0, max_images=100)
    frame = np.zeros((90, 160, 3), np.uint8)
    for i in range(10):
        col.offer({"id": 1, "name": "Prensa 1"}, frame, [PERSON], i)
        col.offer({"id": 2, "name": "Doca 2"}, frame, [PERSON], i)
    counts = prepare(src, tmp_path / "treino")
    assert counts == {"train": 16, "val": 4}
    yaml = (tmp_path / "treino" / "data.yaml").read_text()
    assert "train: images/train" in yaml and "  0: person" in yaml
    assert len(list((tmp_path / "treino" / "labels" / "val").glob("*.txt"))) == 4
