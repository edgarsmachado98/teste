"""Testa modelos no motor do VigIA antes de colocar em produção.

  python -m vigia_detector.testar_modelo --modelos ..\\modelos\\yolox_s.onnx --fonte foto.jpg
  python -m vigia_detector.testar_modelo --modelos ..\\modelos\\yolox_s.onnx --fonte C:\\fotos
  python -m vigia_detector.testar_modelo --modelos ..\\modelos\\yolox_s.onnx --fonte "rtsp://admin:SENHA@192.168.0.10:554/cam/realmonitor?channel=1&subtype=0" --quadros 10
  (com SENHA escrito assim no endereço, o teste pergunta a senha sem mostrá-la)

Para cada imagem: grava uma cópia marcada (pasta --saida), lista o que foi detectado e o tempo de análise.
Use --comparar com um modelo .pt para ver lado a lado o motor livre (ONNX) e o da Ultralytics.
"""

from __future__ import annotations

import argparse
import os
import statistics
import time
from collections import Counter
from pathlib import Path

os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

import cv2  # noqa: E402

from .diagnose import mask  # noqa: E402
from .engine import Engine  # noqa: E402

IMAGE_TYPES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
COLORS = {"person": (60, 200, 60)}


def frames_from(source: str, count: int, every: float):
    """(nome, quadro) de uma foto, de uma pasta de fotos, de uma câmera RTSP ou da webcam."""
    path = Path(source)
    if path.is_dir():
        for p in sorted(x for x in path.iterdir() if x.suffix.lower() in IMAGE_TYPES):
            img = cv2.imread(str(p))
            if img is not None:
                yield p.stem, img
        return
    if path.is_file() and path.suffix.lower() in IMAGE_TYPES:
        img = cv2.imread(str(path))
        if img is None:
            raise SystemExit(f"Não foi possível ler {path}.")
        yield path.stem, img
        return
    cap = cv2.VideoCapture(int(source) if source.isdigit() else source)
    if not cap.isOpened():
        from .diagnose import diagnose
        raise SystemExit(f"Não foi possível abrir {mask(source)}: {diagnose(source)}")
    got, last = 0, 0.0
    while got < count:
        ok = cap.grab()
        if not ok:
            break
        if time.monotonic() - last < every:
            continue
        ok, img = cap.retrieve()
        if ok:
            last = time.monotonic()
            got += 1
            yield f"quadro-{got:02d}", img
    cap.release()


def ask_password(source: str) -> str:
    """Endereço com a palavra SENHA no lugar da senha: pergunta sem mostrar o que é digitado
    (a senha não fica no histórico do PowerShell nem em prints). Caracteres especiais são codificados."""
    if not source.lower().startswith("rtsp://") or ":SENHA@" not in source:
        return source
    import getpass
    from urllib.parse import quote
    password = getpass.getpass("Senha da câmera (não aparece ao digitar): ")
    return source.replace(":SENHA@", f":{quote(password, safe='')}@", 1)


def draw(img, detections):
    out = img.copy()
    h, w = out.shape[:2]
    thick = max(2, w // 640)
    for d in detections:
        x1, y1, x2, y2 = int(d.box[0] * w), int(d.box[1] * h), int(d.box[2] * w), int(d.box[3] * h)
        color = COLORS.get(d.label, (0, 165, 255) if d.label.startswith("no_") else (230, 160, 40))
        cv2.rectangle(out, (x1, y1), (x2, y2), color, thick)
        cv2.putText(out, f"{d.label} {d.confidence:.2f}", (x1, max(14, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX,
                    0.45 * thick, color, max(1, thick - 1), cv2.LINE_AA)
    return out


def run(models: list[str], source: str, out_dir: Path, conf: float, count: int, every: float, tag: str,
        tiles: tuple[int, int] = (1, 1)) -> dict:
    engine = Engine(models, conf=conf, ppe_crops=True, tiles=tiles)
    print(f"\n== {tag}: {', '.join(Path(m).name for m in models)}")
    for m in engine.models:
        print(f"   {Path(m.path).name}: {len(m.names)} classes · licença: {m.license or 'não informada'}")
    out_dir.mkdir(parents=True, exist_ok=True)
    times, totals = [], Counter()
    for name, img in frames_from(source, count, every):
        engine.detect(img)  # aquecimento (a primeira análise é sempre mais lenta)
        t0 = time.perf_counter()
        dets = engine.detect(img)
        times.append((time.perf_counter() - t0) * 1000)
        counts = Counter(d.label for d in dets if d.confidence >= conf)
        totals.update(counts)
        cv2.imwrite(str(out_dir / f"{name}-{tag}.jpg"), draw(img, [d for d in dets if d.confidence >= conf]))
        desc = ", ".join(f"{n} {lbl}" for lbl, n in counts.most_common()) or "nada"
        print(f"   {name}: {desc}  ({times[-1]:.0f} ms)")
    if not times:
        raise SystemExit("Nenhuma imagem analisada.")
    ms = statistics.median(times)
    print(f"   → total: {dict(totals)} · mediana {ms:.0f} ms por imagem (~{1000 / ms:.1f} análises/s neste computador)")
    print(f"   imagens marcadas em {out_dir}")
    return {"ms": ms, "totals": dict(totals)}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--modelos", required=True, help="modelos separados por vírgula (.onnx e/ou .pt)")
    p.add_argument("--fonte", required=True, help="foto, pasta de fotos, endereço rtsp:// ou 0 (webcam)")
    p.add_argument("--saida", default="teste-modelo", type=Path, help="pasta das imagens marcadas")
    p.add_argument("--confianca", default=0.4, type=float)
    p.add_argument("--quadros", default=5, type=int, help="quantos quadros pegar da câmera")
    p.add_argument("--intervalo", default=2.0, type=float, help="segundos entre quadros da câmera")
    p.add_argument("--comparar", default="", help="outros modelos para comparar (ex.: yolov8n.pt)")
    p.add_argument("--blocos", default="1x1", help="analisar em blocos, ex.: 2x2 (cenas abertas, pessoas pequenas)")
    a = p.parse_args()
    a.fonte = ask_password(a.fonte)
    models = [m.strip() for m in a.modelos.split(",") if m.strip()]
    from .main import parse_tiles
    tiles = parse_tiles(a.blocos)
    run(models, a.fonte, a.saida, a.confianca, a.quadros, a.intervalo, "teste", tiles)
    if a.comparar:
        others = [m.strip() for m in a.comparar.split(",") if m.strip()]
        run(others, a.fonte, a.saida, a.confianca, a.quadros, a.intervalo, "comparacao", tiles)


if __name__ == "__main__":
    main()
