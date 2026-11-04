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
# Novas classes entram SEMPRE no fim: os números das antigas não mudam (rótulos já feitos continuam valendo)
CLASSES = ["person", "helmet", "no_helmet", "vest", "no_vest", "glasses", "no_glasses",
           "gloves", "no_gloves", "mask", "no_mask", "fire", "smoke",
           "harness", "no_harness", "boots", "no_boots", "ear_protection", "no_ear_protection",
           "face_shield", "no_face_shield"]
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


IMAGE_TYPES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def import_images(source: Path, target: Path, model_paths: list[str] | None = None, prefix: str = "ref") -> dict:
    """Traz imagens de fora das câmeras (fotos de referência, bancos públicos, fotos tiradas na obra) para a
    pasta de coleta, no mesmo formato YOLO. Com modelos, cada imagem já vai PRÉ-ROTULADA pela IA atual
    (só corrigir no Label Studio); sem modelos, vai sem rótulo (marcar do zero)."""
    import cv2

    files = sorted(p for p in Path(source).rglob("*") if p.suffix.lower() in IMAGE_TYPES)
    if not files:
        raise SystemExit(f"Nenhuma imagem ({', '.join(sorted(IMAGE_TYPES))}) em {source}.")
    images, labels = Path(target) / "images", Path(target) / "labels"
    images.mkdir(parents=True, exist_ok=True)
    labels.mkdir(parents=True, exist_ok=True)
    (Path(target) / "classes.txt").write_text("\n".join(CLASSES) + "\n", encoding="utf-8")
    engine = None
    if model_paths:
        from .engine import Engine
        engine = Engine(model_paths)
    result = {"imported": 0, "prelabeled": 0, "skipped": 0}
    for path in files:
        frame = cv2.imread(str(path))
        if frame is None:  # arquivo corrompido ou formato que o OpenCV não lê
            result["skipped"] += 1
            continue
        name = f"{prefix}-{slug(path.stem)}"
        n = 1
        while (images / f"{name}.jpg").exists():
            n += 1
            name = f"{prefix}-{slug(path.stem)}-{n}"
        cv2.imwrite(str(images / f"{name}.jpg"), frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
        result["imported"] += 1
        if engine is not None:
            (labels / f"{name}.txt").write_text("\n".join(yolo_lines(engine.detect(frame))), encoding="utf-8")
            result["prelabeled"] += 1
    print(f"{result['imported']} imagem(ns) importada(s) para {target}"
          + (f", {result['prelabeled']} pré-rotulada(s) pela IA" if engine else " (sem rótulo: marque no Label Studio)")
          + (f"; {result['skipped']} ignorada(s)" if result["skipped"] else "") + ".")
    print("Corrija/marque no Label Studio (formato YOLO, classes em classes.txt) e depois rode 'preparar'.")
    return result


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


COCO80 = ["person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat", "traffic light",
          "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat", "dog", "horse", "sheep", "cow",
          "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella", "handbag", "tie", "suitcase", "frisbee",
          "skis", "snowboard", "sports ball", "kite", "baseball bat", "baseball glove", "skateboard", "surfboard",
          "tennis racket", "bottle", "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple",
          "sandwich", "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch",
          "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse", "remote", "keyboard",
          "cell phone", "microwave", "oven", "toaster", "sink", "refrigerator", "book", "clock", "vase",
          "scissors", "teddy bear", "hair drier", "toothbrush"]


def export_coco(data_dir: Path, output: Path) -> dict:
    """Converte o conjunto preparado (YOLO) para o formato COCO usado pelo YOLOX e pelo D-FINE:
    saida/train2017, saida/val2017 e saida/annotations/instances_{train,val}2017.json.
    Treinar nessas ferramentas (Apache-2.0) gera modelos sem a restrição AGPL da Ultralytics."""
    import json

    import cv2

    names = CLASSES
    yaml_file = data_dir / "data.yaml"
    if yaml_file.exists():
        found = re.findall(r"^\s+(\d+):\s*(.+)$", yaml_file.read_text(encoding="utf-8"), re.M)
        if found:
            names = [n.strip() for _, n in sorted(found, key=lambda x: int(x[0]))]
    (output / "annotations").mkdir(parents=True, exist_ok=True)
    counts = {}
    for part in ("train", "val"):
        images = sorted((data_dir / "images" / part).glob("*.jpg"))
        target = output / f"{part}2017"
        target.mkdir(parents=True, exist_ok=True)
        coco = {"images": [], "annotations": [],
                "categories": [{"id": i, "name": n} for i, n in enumerate(names)]}
        ann_id = 1
        for img_id, img in enumerate(images, start=1):
            frame = cv2.imread(str(img))
            if frame is None:
                continue
            h, w = frame.shape[:2]
            shutil.copy2(img, target / img.name)
            coco["images"].append({"id": img_id, "file_name": img.name, "width": w, "height": h})
            label = data_dir / "labels" / part / f"{img.stem}.txt"
            for line in (label.read_text(encoding="utf-8").splitlines() if label.exists() else []):
                parts = line.split()
                if len(parts) != 5:
                    continue
                c, cx, cy, bw, bh = int(parts[0]), *map(float, parts[1:])
                box = [(cx - bw / 2) * w, (cy - bh / 2) * h, bw * w, bh * h]
                coco["annotations"].append({"id": ann_id, "image_id": img_id, "category_id": c, "bbox": box,
                                            "area": box[2] * box[3], "iscrowd": 0})
                ann_id += 1
        (output / "annotations" / f"instances_{part}2017.json").write_text(json.dumps(coco), encoding="utf-8")
        counts[part] = len(coco["images"])
    (output / "classes.json").write_text(json.dumps(names, ensure_ascii=False), encoding="utf-8")
    print(f"COCO em {output}: {counts.get('train', 0)} imagens de treino, {counts.get('val', 0)} de validação, "
          f"{len(names)} classes (num_classes={len(names)} no YOLOX/D-FINE).")
    return counts


def write_meta(model: Path, fmt: str, classes: str, input_size: int, license_: str, source: str,
               decoded: bool = False) -> Path:
    """Cria o .json que acompanha um modelo .onnx (formato, classes, tamanho de entrada e licença)."""
    import json

    if classes == "coco":
        names = COCO80
    elif Path(classes).exists():
        text = Path(classes).read_text(encoding="utf-8")
        names = json.loads(text) if text.lstrip().startswith("[") else [c.strip() for c in text.splitlines() if c.strip()]
    else:
        names = [c.strip() for c in classes.split(",") if c.strip()]
    meta = {"format": fmt, "classes": names, "input_size": input_size, "decoded": decoded,
            "license": license_, "source": source}
    target = model.with_suffix(".json")
    target.write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{target} criado: formato {fmt}, {len(names)} classes, entrada {input_size}px, licença {license_ or '?'}.")
    return target


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
    i = sub.add_parser("importar", help="traz fotos de fora (referência, bancos públicos) para a pasta de coleta")
    i.add_argument("--origem", required=True, type=Path, help="pasta com as imagens (jpg, png, webp...)")
    i.add_argument("--destino", required=True, type=Path, help="pasta de coleta (a mesma do DATASET_DIR)")
    i.add_argument("--modelos", default="", help="modelos para pré-rotular, ex.: yolov8n.pt,../modelos/epi.pt")
    i.add_argument("--prefixo", default="ref", help="início do nome dos arquivos (separa estas imagens das câmeras)")
    c = sub.add_parser("exportar-coco", help="converte o conjunto preparado para COCO (treino no YOLOX/D-FINE, Apache-2.0)")
    c.add_argument("--dados", required=True, type=Path, help="pasta gerada pelo 'preparar' (com data.yaml)")
    c.add_argument("--saida", required=True, type=Path)
    m = sub.add_parser("criar-meta", help="cria o .json que acompanha um modelo .onnx")
    m.add_argument("--modelo", required=True, type=Path, help="arquivo .onnx")
    m.add_argument("--formato", choices=["yolox", "detr"], required=True)
    m.add_argument("--classes", required=True, help="'coco', arquivo (classes.json/classes.txt) ou lista separada por vírgula")
    m.add_argument("--entrada", type=int, default=640, help="tamanho da entrada do modelo (640)")
    m.add_argument("--licenca", default="", help="ex.: Apache-2.0")
    m.add_argument("--origem", default="", help="de onde veio o modelo (para auditoria de licenças)")
    m.add_argument("--decodificado", action="store_true", help="YOLOX exportado com a decodificação na rede")
    t = sub.add_parser("treinar", help="treina com Ultralytics (AGPL-3.0: uso comercial exige Enterprise License)")
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
    elif args.cmd == "exportar-coco":
        export_coco(args.dados, args.saida)
    elif args.cmd == "criar-meta":
        write_meta(args.modelo, args.formato, args.classes, args.entrada, args.licenca, args.origem, args.decodificado)
    elif args.cmd == "importar":
        import_images(args.origem, args.destino, [m.strip() for m in args.modelos.split(",") if m.strip()], args.prefixo)
    elif args.cmd == "treinar":
        train(args.dados, args.base, args.epocas, args.img, args.device, args.modelos)
    else:
        evaluate(args.modelo, args.dados, args.img, args.device)


if __name__ == "__main__":
    main()
