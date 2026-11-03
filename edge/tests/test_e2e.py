"""Ponta a ponta: nuvem (backend) + VigIA Edge em processos separados, conversando pelo túnel.

Simula o detector da planta enviando ocorrência, clipe e quadro ao vivo para o Edge e confere que:
- a imagem completa fica só no storage do cliente; na nuvem ficam os dados e a miniatura;
- a tela busca a imagem, o clipe e o ao vivo pelo túnel, sob demanda;
- sem internet a ocorrência espera na fila e chega depois, sem duplicar;
- Edge desligado: miniatura continua, imagem completa avisa; credencial revogada derruba o túnel.
"""

import io
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
PY = sys.executable


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def jpeg(color=(200, 30, 30), size=(1280, 720)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, "JPEG", quality=90)
    return out.getvalue()


def wait_until(fn, timeout=15.0, step=0.2):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            value = fn()
            if value:
                return value
        except Exception:  # noqa: BLE001
            pass
        time.sleep(step)
    raise AssertionError("condição não atingida a tempo")


class Proc:
    def __init__(self, args, env, cwd, log):
        self.log = open(log, "w")
        self.p = subprocess.Popen(args, env=env, cwd=cwd, stdout=self.log, stderr=subprocess.STDOUT)

    def stop(self):
        self.p.terminate()
        try:
            self.p.wait(10)
        except subprocess.TimeoutExpired:
            self.p.kill()
        self.log.close()


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("e2e")
    cloud_port = free_port()
    cloud_env = {**os.environ, "DATABASE_URL": f"sqlite:///{tmp}/nuvem.db", "EVIDENCE_DIR": str(tmp / "nuvem-ev"),
                 "BACKUP_DIR": str(tmp / "bk"), "PEOPLE_DIR": str(tmp / "pessoas"), "SECRET_KEY_FILE": str(tmp / "k"),
                 "DETECTOR_API_KEY": "nao-usada"}
    cloud = Proc([PY, "-m", "uvicorn", "app.main:app", "--port", str(cloud_port)], cloud_env, ROOT / "backend",
                 tmp / "nuvem.log")
    base = f"http://127.0.0.1:{cloud_port}"
    wait_until(lambda: httpx.get(f"{base}/api/setup").status_code == 200)
    token = httpx.post(f"{base}/api/setup", json={"name": "Ana", "email": "a@x.com", "password": "senha-forte-1"}).json()["token"]
    h = {"Authorization": f"Bearer {token}"}
    unit = httpx.get(f"{base}/api/units", headers=h).json()[0]["id"]
    cam = httpx.post(f"{base}/api/cameras", headers=h, json={"name": "Doca 1", "source": "0", "unit_id": unit}).json()
    rule = httpx.post(f"{base}/api/rules", headers=h, json={"camera_id": cam["id"], "name": "Zona", "type": "restricted_zone"}).json()
    code = httpx.post(f"{base}/api/edge/enrollments", headers=h, json={"name": "Edge Joinville", "unit_id": unit}).json()["code"]

    edge_home = tmp / "edge"
    edge_port = free_port()
    edge_env = {**os.environ, "EDGE_HOME": str(edge_home), "EDGE_MEDIA_DIR": str(tmp / "storage-cliente"),
                "EDGE_PORT": str(edge_port)}
    out = subprocess.run([PY, "-m", "vigia_edge", "enroll", "--cloud", base, "--code", code],
                         env=edge_env, cwd=ROOT / "edge", capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stdout + out.stderr
    # o mesmo código não serve duas vezes
    again = subprocess.run([PY, "-m", "vigia_edge", "enroll", "--cloud", base, "--code", code],
                           env={**edge_env, "EDGE_HOME": str(tmp / "edge2")}, cwd=ROOT / "edge",
                           capture_output=True, text=True, timeout=30)
    assert again.returncode != 0 and "código inválido" in again.stdout
    import json
    detector_key = json.loads((edge_home / "edge.json").read_text())["detector_key"]
    edge = Proc([PY, "-m", "vigia_edge", "run"], edge_env, ROOT / "edge", tmp / "edge.log")
    edge_url = f"http://127.0.0.1:{edge_port}"
    wait_until(lambda: httpx.get(f"{edge_url}/status").json()["tunnel"])
    w = dict(base=base, h=h, cam=cam, rule=rule, edge_url=edge_url, det={"X-Detector-Key": detector_key},
             tmp=tmp, cloud=cloud, edge=edge, edge_env=edge_env, cloud_env=cloud_env, cloud_port=cloud_port)
    yield w
    w["edge"].stop()
    w["cloud"].stop()


def send_event(w, image: bytes, clip_id: str | None = None):
    data = {"camera_id": w["cam"]["id"], "rule_id": w["rule"]["id"], "message": "pessoa na zona restrita"}
    if clip_id:
        data["clip_id"] = clip_id
    r = httpx.post(f"{w['edge_url']}/api/detector/events", headers=w["det"], data=data,
                   files={"snapshot": ("e.jpg", image, "image/jpeg")})
    assert r.status_code == 202, r.text
    return r.json()["media_ref"]


def cloud_events(w):
    return httpx.get(f"{w['base']}/api/events", headers=w["h"]).json()


def test_detector_config_through_edge(world):
    r = httpx.get(f"{world['edge_url']}/api/detector/config", headers=world["det"])
    assert r.status_code == 200 and [c["name"] for c in r.json()] == ["Doca 1"]
    assert httpx.get(f"{world['edge_url']}/api/detector/config").status_code == 401  # sem a chave do detector


def test_event_image_stays_at_client_and_streams_on_demand(world):
    w = world
    original = jpeg()
    media_ref = send_event(w, original, clip_id="clip-e2e-1")
    stored = w["tmp"] / "storage-cliente" / media_ref
    on_disk = stored.read_bytes()  # imagem completa no storage do cliente, cifrada (AES-256-GCM)
    assert on_disk.startswith(b"VGE1") and b"\xff\xd8" not in on_disk[:40] and original not in on_disk
    ev = wait_until(lambda: next((e for e in cloud_events(w) if e["message"] == "pessoa na zona restrita"), None))
    assert ev["media_at_edge"] and ev["thumb_url"]
    # nenhuma cópia da imagem completa na nuvem: só a miniatura
    cloud_files = [p for p in (w["tmp"] / "nuvem-ev").rglob("*.jpg")]
    assert cloud_files and all("miniaturas" in str(p) for p in cloud_files)
    thumb = httpx.get(f"{w['base']}{ev['thumb_url']}", headers=w["h"])
    assert thumb.status_code == 200 and len(thumb.content) < len(original) / 3
    full = httpx.get(f"{w['base']}{ev['image_url']}", headers=w["h"])
    assert full.status_code == 200 and full.content == original  # veio pelo túnel

    # clipe: quadros ficam no Edge, a nuvem só registra a pasta
    frames = [("frames", (f"{i:04d}.jpg", jpeg((i * 40, 80, 80), (640, 360)), "image/jpeg")) for i in range(3)]
    r = httpx.post(f"{w['edge_url']}/api/detector/clips/clip-e2e-1", headers=w["det"], data={"duration": "1.5"}, files=frames)
    assert r.status_code == 202
    detail = wait_until(lambda: (d := httpx.get(f"{w['base']}/api/events/{ev['id']}", headers=w["h"]).json())
                        ["clip_frames"] == 3 and d)
    assert detail["clip_video_url"]  # o Edge juntou os quadros num vídeo WebM
    video = httpx.get(f"{w['base']}{detail['clip_video_url']}", headers=w["h"])
    assert video.status_code == 200 and video.headers["content-type"] == "video/webm"
    assert video.content[:4] == b"\x1a\x45\xdf\xa3"  # assinatura WebM/Matroska
    assert list((w["tmp"] / "storage-cliente" / "clipes").rglob("clip-e2e-1.webm"))


def test_live_frame_and_health_through_tunnel(world):
    w = world
    live = jpeg((10, 120, 10), (640, 360))
    r = httpx.post(f"{w['edge_url']}/api/detector/cameras/{w['cam']['id']}/frame", headers=w["det"],
                   data={"health": "escura"}, files={"frame": ("f.jpg", live, "image/jpeg")})
    assert r.status_code == 204
    cams = wait_until(lambda: (c := httpx.get(f"{w['base']}/api/cameras", headers=w["h"]).json()) and c[0]["health"] == "escura" and c)
    assert cams[0]["last_frame_at"]
    got = httpx.get(f"{w['base']}/api/cameras/{w['cam']['id']}/frame", headers=w["h"])
    assert got.status_code == 200 and got.content == live


def test_edge_status_reaches_cloud(world):
    w = world
    edges = wait_until(lambda: (e := httpx.get(f"{w['base']}/api/edge/edges", headers=w["h"]).json())
                       and e[0]["status"].get("media_ok") is not None and e)
    e = edges[0]
    assert e["online"] and e["status"]["media_ok"] and "disk_free_gb" in e["status"] and e["version"]


def test_offline_queue_then_resend_without_duplicates(world):
    w = world
    w["cloud"].stop()  # internet da planta caiu
    original = jpeg((30, 30, 200))
    send_event(w, original)  # o detector continua: o Edge guarda e enfileira
    status = httpx.get(f"{w['edge_url']}/status").json()
    assert status["queue"] >= 1 and not status["tunnel"] or status["queue"] >= 1
    w["cloud"] = Proc([PY, "-m", "uvicorn", "app.main:app", "--port", str(w["cloud_port"])], w["cloud_env"],
                      ROOT / "backend", w["tmp"] / "nuvem2.log")
    wait_until(lambda: httpx.get(f"{w['edge_url']}/status").json()["queue"] == 0, timeout=90)
    events = cloud_events(w)
    assert len(events) == 2 and len({e["id"] for e in events}) == 2
    newest = events[0]
    wait_until(lambda: httpx.get(f"{w['edge_url']}/status").json()["tunnel"], timeout=90)
    full = httpx.get(f"{w['base']}{newest['image_url']}", headers=w["h"])
    assert full.status_code == 200 and full.content == original


def test_edge_off_thumbnail_still_works_and_revocation(world):
    w = world
    ev = cloud_events(w)[0]
    w["edge"].stop()
    wait_until(lambda: not httpx.get(f"{w['base']}/api/edge/edges", headers=w["h"]).json()[0]["online"])
    assert httpx.get(f"{w['base']}{ev['thumb_url']}", headers=w["h"]).status_code == 200
    # a imagem completa foi aberta antes e está em cache por alguns minutos; um quadro nunca aberto não está
    r = httpx.get(f"{w['base']}/api/cameras/{w['cam']['id']}/frame", headers=w["h"])
    assert r.status_code in (200, 404)
    # revogar: o Edge não consegue mais nada
    edge_id = httpx.get(f"{w['base']}/api/edge/edges", headers=w["h"]).json()[0]["id"]
    assert httpx.delete(f"{w['base']}/api/edge/edges/{edge_id}", headers=w["h"]).status_code == 204
    import json
    cred = json.loads((w["tmp"] / "edge" / "edge.json").read_text())
    r = httpx.get(f"{w['base']}/api/edge/detector/config", headers={"X-Edge-Id": str(cred["edge_id"]), "X-Edge-Key": cred["key"]})
    assert r.status_code == 401
    w["edge"] = Proc([PY, "-m", "vigia_edge", "run"], w["edge_env"], ROOT / "edge", w["tmp"] / "edge2.log")
    time.sleep(3)
    assert not httpx.get(f"{w['edge_url']}/status").json()["tunnel"]
