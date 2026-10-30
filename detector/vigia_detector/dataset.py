"""Treinamento do modelo com imagens das câmeras do cliente.

1. COLETAR  – com DATASET_DIR no .env, o detector salva imagens reais das câmeras (periódicas
               quando há pessoas e sempre que há desvio) já com PRÉ-RÓTULOS da IA atual.
2. CORRIGIR – abra a pasta numa ferramenta de rotulagem (ex.: Label Studio ou CVAT, formato YOLO)
               e corrija as caixas. Corrigir é muito mais rápido do que rotular do zero.
3. PREPARAR – python -m vigia_detector.dataset preparar --origem <DATASET_DIR> --saida treino
4. TREINAR  – python -m vigia_detector.dataset treinar --dados treino/data.yaml
5. COMPARAR – python -m vigia_detector.dataset avaliar --modelo modelos/epi.pt --dados treino/data.yaml
               (use o novo modelo só se a nota mAP50 for melhor que a do atual)

As imagens mostram trabalhadores: restrinja o acesso à pasta e apague-a após o treinamento (LGPD).
"""

from __future__ import annotations

import argparse
import random
import re
import shutil
import threading
import unicodedata
from datetime import datetime
from pathlib import Path

from .rules import Detection

# Classes canônicas (mesmos nomes usados pelas regras; ver labels.py)
CLASSES = ["person", "helmet", "no_helmet", "vest", "no_vest", "glasses", "no_glasses",
           "gloves", "no_gloves", "mask", "no_mask", "fire", "smoke"]
CLASS_INDEX = {name: i for i, name in enumerate(CLASSES)}


def slug(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-") or "camera"


def yolo_lines(detections: list[Detection]) -> list[str]:
    lines = []
    for d in detections:
        if d.label not in CLASS_INDEX:
            continue
        x1, y1, x2, y2 = (min(max(v, 0.0), 1.0) for v in d.box)
        if x2 <= x1 or y2 <= y1:
            continue
        lines.append(f"{CLASS_INDEX[d.label]} {(x1 + x2) / 2:.6f} {(y1 + y2) / 2:.6f} {x2 - x1:.6f} {y2 - y1:.6f}")
    return lines


class Collector:
    """Salva imagens para treinamento (chamado pelas threads das câmeras)."""

    def __init__(self, root: str | Path, interval: float = 60.0, max_images: int = 5000, important_interval: float = 5.0):
        self.root = Path(root)
        self.images = self.root / "images"
        self.labels = self.root / "labels"
        self.images.mkdir(parents=True, exist_ok=True)
        self.labels.mkdir(parents=True, exist_ok=True)
        (self.root / "classes.txt").write_text("\n".join(CLASSES) + "\n", encoding="utf-8")
        self.interval = interval
        self.important_interval = important_interval
        self.max_images = max_images
        self.count = sum(1 for _ in self.images.glob("*.jpg"))
        self._last: dict[int, float] = {}
        self._lock = threading.Lock()

    def offer(self, camera: dict, frame, detections: list[Detection], now: float, important: bool = False) -> bool:
        has_person = any(d.label == "person" for d in detections)
        if not (important or has_person):
            return False
        with self._lock:
            wait = self.important_interval if important else self.interval
            if self.count >= self.max_images or now - self._last.get(camera["id"], float("-inf")) < wait:
                return False
            self._last[camera["id"]] = now
            self.count += 1
        import cv2

        name = f"{slug(camera['name'])}-{datetime.now():%Y%m%d-%H%M%S-%f}"
        cv2.imwrite(str(self.images / f"{name}.jpg"), frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
        (self.labels / f"{name}.txt").write_text("\n".join(yolo_lines(detections)), encoding="utf-8")
        return True


def prepare(source: Path, output: Path, val_fraction: float = 0.2, seed: int = 7) -> dict:
    """Separa treino/validação (por câmera, de forma estável) e gera o data.yaml do YOLO."""
    images = sorted(p for p in (source / "images").glob("*.jpg") if (source / "labels" / f"{p.stem}.txt").exists())
    if not images:
        raise SystemExit(f"Nenhuma imagem com rótulo em {source}/images (e {source}/labels).")
    names = CLASSES
    classes_file = source / "classes.txt"
    if classes_file.exists():  # a ferramenta de rotulagem pode ter acrescentado classes
        names = [c.strip() for c in classes_file.read_text(encoding="utf-8").splitlines() if c.strip()]

    rnd = random.Random(seed)
    by_camera: dict[str, list[Path]] = {}
    for img in images:
        by_camera.setdefault(img.stem.rsplit("-", 4)[0], []).append(img)
    split = {"train": [], "val": []}
    for files in by_camera.values():
        rnd.shuffle(files)
        n_val = max(1, round(len(files) * val_fraction)) if len(files) > 1 else 0
        split["val"] += files[:n_val]
        split["train"] += files[n_val:]

    if output.exists():
        shutil.rmtree(output)
    for part, files in split.items():
        (output / "images" / part).mkdir(parents=True)
        (output / "labels" / part).mkdir(parents=True)
        for img in files:
            shutil.copy2(img, output / "images" / part / img.name)
            shutil.copy2(source / "labels" / f"{img.stem}.txt", output / "labels" / part / f"{img.stem}.txt")

    yaml = [f"path: {output.resolve().as_posix()}", "train: images/train", "val: images/val", "names:"]
    yaml += [f"  {i}: {name}" for i, name in enumerate(names)]
    (output / "data.yaml").write_text("\n".join(yaml) + "\n", encoding="utf-8")
    counts = {part: len(files) for part, files in split.items()}
    print(f"Conjunto preparado em {output}: {counts['train']} imagens de treino, {counts['val']} de validação.")
    if counts["train"] < 200:
        print("Atenção: poucas imagens. Para um bom resultado, colete e corrija algumas centenas por câmera.")
    return counts


def train(data: Path, base: str, epochs: int, imgsz: int, device: str | None, models_dir: Path) -> Path:
    from ultralytics import YOLO

    model = YOLO(base)
    model.train(data=str(data), epochs=epochs, imgsz=imgsz, device=device, project=str(data.parent / "execucoes"),
                name=f"treino-{datetime.now():%Y%m%d-%H%M}", patience=20)
    best = Path(model.trainer.best)
    models_dir.mkdir(parents=True, exist_ok=True)
    target = models_dir / f"epi-{datetime.now():%Y%m%d-%H%M}.pt"
    shutil.copy2(best, target)
    metrics = YOLO(str(target)).val(data=str(data), imgsz=imgsz, device=device, verbose=False)
    print(f"\nModelo salvo em {target}  –  mAP50 na validação: {metrics.box.map50:.3f}")
    print("Compare com o modelo atual (comando 'avaliar') e, se for melhor, ajuste no .env:")
    print(f"  MODEL_PATHS=yolov8n.pt,{target.relative_to(models_dir.parent).as_posix()}")
    return target


def evaluate(model_path: str, data: Path, imgsz: int, device: str | None) -> None:
    from ultralytics import YOLO

    metrics = YOLO(model_path).val(data=str(data), imgsz=imgsz, device=device, verbose=False)
    print(f"{model_path}: mAP50 = {metrics.box.map50:.3f}  |  mAP50-95 = {metrics.box.map:.3f}")
    for i, ap in zip(metrics.box.ap_class_index, metrics.box.ap50):
        print(f"  {metrics.names[int(i)]:<12} AP50 = {ap:.3f}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("preparar", help="separa treino/validação e gera o data.yaml")
    p.add_argument("--origem", required=True, type=Path, help="pasta da coleta (DATASET_DIR)")
    p.add_argument("--saida", default=Path("treino"), type=Path)
    p.add_argument("--validacao", default=0.2, type=float, help="fração para validação (padrão 0.2)")
    t = sub.add_parser("treinar", help="treina um modelo a partir do data.yaml")
    t.add_argument("--dados", required=True, type=Path)
    t.add_argument("--base", default="yolov8s.pt", help="modelo inicial (padrão yolov8s.pt)")
    t.add_argument("--epocas", default=100, type=int)
    t.add_argument("--img", default=640, type=int)
    t.add_argument("--device", default=None, help="0 para a primeira GPU; vazio = automático")
    t.add_argument("--modelos", default=Path(__file__).resolve().parents[2] / "modelos", type=Path)
    a = sub.add_parser("avaliar", help="mede a precisão de um modelo no conjunto de validação")
    a.add_argument("--modelo", required=True)
    a.add_argument("--dados", required=True, type=Path)
    a.add_argument("--img", default=640, type=int)
    a.add_argument("--device", default=None)
    args = parser.parse_args()

    if args.cmd == "preparar":
        prepare(args.origem, args.saida, args.validacao)
    elif args.cmd == "treinar":
        train(args.dados, args.base, args.epocas, args.img, args.device, args.modelos)
    else:
        evaluate(args.modelo, args.dados, args.img, args.device)


if __name__ == "__main__":
    main()
