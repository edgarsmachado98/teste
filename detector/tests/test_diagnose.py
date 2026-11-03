"""Diagnóstico de conexão RTSP contra uma câmera falsa (autenticação Digest, como Intelbras/Dahua/Hikvision)."""

import hashlib
import re
import socket
import threading

from vigia_detector.diagnose import diagnose, mask

REALM, NONCE, USER, PASS, PATH = "Login to VIGIA", "abc123", "admin", "s3nh@forte", "/cam/realmonitor"


def fake_camera():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(8)

    def handle(conn):
        with conn:
            req = conn.recv(4096).decode()
            uri = req.split(" ")[1]
            auth = re.search(r"Authorization: Digest (.*)", req)
            if not auth:
                code = f'401 Unauthorized\r\nWWW-Authenticate: Digest realm="{REALM}", nonce="{NONCE}"'
            else:
                f = dict(re.findall(r'(\w+)="([^"]*)"', auth.group(1)))
                ha1 = hashlib.md5(f"{USER}:{REALM}:{PASS}".encode()).hexdigest()
                ha2 = hashlib.md5(f"DESCRIBE:{f['uri']}".encode()).hexdigest()
                good = f.get("response") == hashlib.md5(f"{ha1}:{NONCE}:{ha2}".encode()).hexdigest()
                if not good:
                    code = f'401 Unauthorized\r\nWWW-Authenticate: Digest realm="{REALM}", nonce="{NONCE}"'
                elif not uri.split(":", 2)[-1].split("/", 1)[-1].startswith(PATH[1:]):
                    code = "404 Not Found"
                else:
                    code = "200 OK\r\nContent-Type: application/sdp"
            conn.sendall(f"RTSP/1.0 {code}\r\nCSeq: 2\r\n\r\n".encode())

    def loop():
        while True:
            try:
                c, _ = srv.accept()
            except OSError:
                return
            threading.Thread(target=handle, args=(c,), daemon=True).start()
    threading.Thread(target=loop, daemon=True).start()
    return srv.getsockname()[1], srv


def test_diagnose_messages():
    port, srv = fake_camera()
    base = f"127.0.0.1:{port}"
    pw = "s3nh%40forte"  # '@' na senha precisa ir codificado no endereço
    assert "usuário ou senha recusados" in diagnose(f"rtsp://admin:errada@{base}{PATH}?channel=1&subtype=1")
    assert "exige usuário e senha" in diagnose(f"rtsp://{base}{PATH}")
    assert "caminho do stream não existe" in diagnose(f"rtsp://admin:{pw}@{base}/stream1")
    assert "Intelbras/Dahua: /cam/realmonitor" in diagnose(f"rtsp://admin:{pw}@{base}/stream1")
    assert "use H.264" in diagnose(f"rtsp://admin:{pw}@{base}{PATH}?channel=1&subtype=1")
    srv.close()
    free = socket.socket(); free.bind(("127.0.0.1", 0)); closed = free.getsockname()[1]; free.close()
    assert "conexão recusada" in diagnose(f"rtsp://admin:x@127.0.0.1:{closed}/")


def test_password_never_in_logs():
    assert mask("rtsp://admin:senha-exemplo@192.168.0.50/stream1") == "rtsp://admin:***@192.168.0.50/stream1"
    assert mask("rtsp://192.168.0.5/x") == "rtsp://192.168.0.5/x"
