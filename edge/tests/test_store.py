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


def test_clip_video(tmp_path):
    import io
    from PIL import Image
    store = MediaStore(tmp_path / "m", tmp_path / "l")
    frames = []
    for i in range(10):
        buf = io.BytesIO()
        Image.new("RGB", (1280, 720), (i * 20, 50, 90)).save(buf, "JPEG")
        frames.append(buf.getvalue())
    rel = store.save_clip_video("abc", frames, 2.0)
    assert rel and rel.endswith("abc.webm")
    data = store.read(rel)
    assert data[:4] == b"\x1a\x45\xdf\xa3" and len(data) < sum(map(len, frames))
    assert store.save_clip_video("vazio", [b"nao-e-imagem"], 1.0) is None  # cai para os quadros JPEG


def test_encrypted_storage(tmp_path):
    import base64
    import os as _os
    from vigia_edge.crypto import MediaCipher
    k1, k2 = base64.b64encode(_os.urandom(32)).decode(), base64.b64encode(_os.urandom(32)).decode()
    old = MediaStore(tmp_path / "m", tmp_path / "l", MediaCipher({"aaaa0001": k1}, "aaaa0001"))
    rel_old = old.save_event_image(b"\xff\xd8 imagem antiga")
    assert (tmp_path / "m" / rel_old).read_bytes().startswith(b"VGE1")
    # máquina trocada: Edge novo com chave nova + a antiga (vinda da nuvem) lê tudo
    new = MediaStore(tmp_path / "m", tmp_path / "l", MediaCipher({"aaaa0001": k1, "bbbb0002": k2}, "bbbb0002"))
    rel_new = new.save_event_image(b"\xff\xd8 imagem nova")
    assert new.read(rel_old) == b"\xff\xd8 imagem antiga" and new.read(rel_new) == b"\xff\xd8 imagem nova"
    # sem a chave: nada sai do storage
    assert MediaStore(tmp_path / "m", tmp_path / "l").read(rel_new) is None
    assert old.read(rel_new) is None  # chave desconhecida
    # adulteração detectada
    p = tmp_path / "m" / rel_new
    blob = bytearray(p.read_bytes()); blob[-1] ^= 1; p.write_bytes(bytes(blob))
    assert new.read(rel_new) is None
    # arquivos gravados antes da criptografia continuam legíveis
    (tmp_path / "m" / "antigo.jpg").write_bytes(b"\xff\xd8 sem cifra")
    assert new.read("antigo.jpg") == b"\xff\xd8 sem cifra"
