"""Motor ONNX (livre): modelos sintéticos no formato do YOLOX e do D-FINE/RT-DETR."""

import json
import math

import numpy as np
import pytest

onnx = pytest.importorskip("onnx")
pytest.importorskip("onnxruntime")
from onnx import TensorProto, helper, numpy_helper  # noqa: E402

from vigia_detector.backends import OnnxBackend  # noqa: E402
from vigia_detector.engine import Engine  # noqa: E402


def save_model(path, inputs, outputs: dict):
    nodes = [helper.make_node("Constant", [], [name], value=numpy_helper.from_array(arr, name + "_v"))
             for name, arr in outputs.items()]
    graph = helper.make_graph(
        nodes, "falso",
        [helper.make_tensor_value_info(n, t, s) for n, t, s in inputs],
        [helper.make_tensor_value_info(n, helper.np_dtype_to_tensor_dtype(a.dtype), list(a.shape))
         for n, a in outputs.items()])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    model.ir_version = 8
    onnx.save(model, str(path))


def yolox_model(tmp_path, decoded=False):
    s = 64
    rows = (s // 8) ** 2 + (s // 16) ** 2 + (s // 32) ** 2
    out = np.zeros((1, rows, 7), np.float32)
    out[0, :, 2:4] = -10  # caixas minúsculas e sem confiança
    # célula (x=2, y=3) do stride 8: capacete 16x32 px centrado em (20, 28)
    i = 3 * 8 + 2
    out[0, i] = [0.5, 0.5, math.log(2), math.log(4), 0.9, 0.1, 0.95]
    j = 3 * 8 + 3  # vizinha quase igual, mais fraca: a supressão de sobrepostas deve removê-la
    out[0, j] = [-0.5, 0.5, math.log(2), math.log(4), 0.8, 0.1, 0.9]
    if decoded:
        out[0, i, :4] = [20, 28, 16, 32]
        out[0, j, :4] = [20, 28, 16, 32]
    path = tmp_path / "epi.onnx"
    save_model(path, [("images", TensorProto.FLOAT, [1, 3, s, s])], {"output": out})
    (tmp_path / "epi.json").write_text(json.dumps({"format": "yolox", "classes": ["person", "Hardhat"],
                                                   "input_size": s, "decoded": decoded, "license": "Apache-2.0"}))
    return str(path)


@pytest.mark.parametrize("decoded", [False, True])
def test_yolox_decode_and_nms(tmp_path, decoded):
    backend = OnnxBackend(yolox_model(tmp_path, decoded))
    found = backend.predict(np.zeros((64, 64, 3), np.uint8), 640, 0.5)
    assert len(found) == 1
    name, conf, box = found[0]
    assert name == "Hardhat" and conf == pytest.approx(0.855, abs=1e-3)
    assert box == pytest.approx((12 / 64, 12 / 64, 28 / 64, 44 / 64), abs=1e-4)
    # imagem maior que a entrada: letterbox e volta para a escala original
    found = backend.predict(np.zeros((128, 256, 3), np.uint8), 640, 0.5)
    (_, _, box), = found
    # escala 0,25 (256x128 → 64x16 + faixa cinza); caixa (12,12,28,44) volta para (48,48,112,176) e é cortada na borda
    assert box == pytest.approx((48 / 256, 48 / 128, 112 / 256, 1.0), abs=1e-4)


def test_detr_format(tmp_path):
    path = tmp_path / "dfine.onnx"
    save_model(path, [("images", TensorProto.FLOAT, [1, 3, 32, 32]), ("orig_target_sizes", TensorProto.INT64, [1, 2])],
               {"labels": np.array([[0, 1, 1]], np.int64),
                "boxes": np.array([[[10, 5, 30, 45], [12, 6, 20, 14], [0, 0, 5, 5]]], np.float32),
                "scores": np.array([[0.9, 0.7, 0.1]], np.float32)})
    (tmp_path / "dfine.json").write_text(json.dumps({"format": "detr", "classes": ["person", "helmet"],
                                                     "input_size": 32}))
    found = OnnxBackend(str(path)).predict(np.zeros((50, 100, 3), np.uint8), 640, 0.3)
    assert [f[0] for f in found] == ["person", "helmet"]
    assert found[0][2] == pytest.approx((0.10, 0.10, 0.30, 0.90))


def test_engine_with_onnx_knows_labels(tmp_path):
    eng = Engine([yolox_model(tmp_path)], ppe_crops=False)
    assert {"person", "helmet"} <= eng.labels
    dets = eng.detect(np.zeros((64, 64, 3), np.uint8))
    assert [d.label for d in dets] == ["helmet"]


def test_onnx_needs_metadata(tmp_path):
    path = tmp_path / "sem.onnx"
    save_model(path, [("images", TensorProto.FLOAT, [1, 3, 8, 8])], {"output": np.zeros((1, 1, 6), np.float32)})
    with pytest.raises(ValueError, match="sem.json"):
        OnnxBackend(str(path))


def test_export_coco_and_meta(tmp_path):
    import cv2
    from vigia_detector.dataset import COCO80, export_coco, prepare, write_meta
    src = tmp_path / "coleta"
    (src / "images").mkdir(parents=True)
    (src / "labels").mkdir()
    for i in range(4):
        cv2.imwrite(str(src / "images" / f"cam-a-2026110{i}-101010-000001.jpg"), np.zeros((100, 200, 3), np.uint8))
        (src / "labels" / f"cam-a-2026110{i}-101010-000001.txt").write_text("1 0.5 0.5 0.2 0.4\n0 0.25 0.5 0.1 0.2")
    prepare(src, tmp_path / "conjunto")
    counts = export_coco(tmp_path / "conjunto", tmp_path / "coco")
    assert counts["train"] + counts["val"] == 4
    ann = json.loads((tmp_path / "coco" / "annotations" / "instances_train2017.json").read_text())
    helmet = next(a for a in ann["annotations"] if a["category_id"] == 1)
    assert helmet["bbox"] == pytest.approx([80, 30, 40, 40])  # x, y, largura, altura em pixels
    assert ann["categories"][1]["name"] == "helmet"
    meta = json.loads(write_meta(tmp_path / "yolox_s.onnx", "yolox", "coco", 640, "Apache-2.0", "YOLOX").read_text())
    assert meta["classes"] == COCO80 and len(COCO80) == 80 and meta["license"] == "Apache-2.0"
    meta = json.loads(write_meta(tmp_path / "epi.onnx", "detr", str(tmp_path / "coco" / "classes.json"), 640, "", "").read_text())
    assert meta["classes"][:3] == ["person", "helmet", "no_helmet"]
