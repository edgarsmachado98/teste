import os
import time

from vigia_edge.store import MediaStore


def test_tunnel_cannot_read_outside_storage(tmp_path):
    media, live = tmp_path / "midia", tmp_path / "ao-vivo"
    store = MediaStore(media, live)
    rel = store.save_event_image(b"\xff\xd8 imagem")
    (tmp_path / "edge.json").write_text('{"key": "segredo"}')
    store.save_live(3, b"\xff\xd8 ao vivo")
    assert store.read(rel) == b"\xff\xd8 imagem"
    assert store.read("ao-vivo/3.jpg") == b"\xff\xd8 ao vivo"
    for evil in ("../edge.json", "/etc/passwd", "..\\edge.json", "C:/Windows/win.ini", "2026/../../edge.json",
                 "ao-vivo/../edge.json", ""):
        assert store.read(evil) is None, evil
    (media / "nota.txt").write_text("x")
    assert store.read("nota.txt") is None  # só imagens


def test_retention_and_thumbnail(tmp_path):
    from PIL import Image
    import io
    store = MediaStore(tmp_path / "m", tmp_path / "l")
    buf = io.BytesIO()
    Image.new("RGB", (1920, 1080), (90, 90, 90)).save(buf, "JPEG")
    thumb = store.thumbnail(buf.getvalue())
    assert thumb and Image.open(io.BytesIO(thumb)).size[0] == 320
    old = store.save_event_image(buf.getvalue())
    new = store.save_event_image(buf.getvalue())
    past = time.time() - 40 * 86400
    os.utime(tmp_path / "m" / old, (past, past))
    assert store.purge(30) == 1
    assert store.read(old) is None and store.read(new)
    assert store.ok() and "disk_free_gb" in store.usage()
