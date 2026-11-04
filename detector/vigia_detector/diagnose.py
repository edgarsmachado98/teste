"""Diagnóstico de conexão com a câmera, para dizer no painel POR QUE ela não abre.

O OpenCV só responde "não abriu". Aqui testamos por partes, como um técnico faria:
1. a câmera responde na rede (IP e porta)?
2. o servidor RTSP aceita o usuário e a senha (autenticação Digest ou Basic)?
3. o caminho do stream existe (cada fabricante tem o seu)?
Se tudo isso passa e o vídeo mesmo assim não abre, o problema é o formato do vídeo (codec)."""

from __future__ import annotations

import base64
import hashlib
import re
import socket
from urllib.parse import unquote, urlsplit, urlunsplit

TIMEOUT = 4.0

HINT_PATHS = ("Intelbras/Dahua: /cam/realmonitor?channel=1&subtype=1 · Hikvision: /Streaming/Channels/102 · "
              "TP-Link/Tapo: /stream2")


def mask(url: str) -> str:
    """Endereço sem a senha (para logs e para o painel)."""
    return re.sub(r"//([^:/@]+):[^@/]*@", r"//\1:***@", url)


def _rtsp_request(host: str, port: int, method: str, url: str, headers: dict) -> tuple[int, dict]:
    lines = [f"{method} {url} RTSP/1.0", "CSeq: 2", "User-Agent: VigIA"]
    lines += [f"{k}: {v}" for k, v in headers.items()]
    with socket.create_connection((host, port), timeout=TIMEOUT) as s:
        s.settimeout(TIMEOUT)
        s.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())
        data = b""
        while b"\r\n\r\n" not in data and len(data) < 65536:
            chunk = s.recv(4096)
            if not chunk:
                break
            data += chunk
    head = data.split(b"\r\n\r\n", 1)[0].decode("latin-1", "replace").split("\r\n")
    m = re.match(r"RTSP/1\.\d\s+(\d{3})", head[0] if head else "")
    if not m:
        raise ValueError("resposta não é RTSP")
    hdrs: dict[str, str] = {}
    for line in head[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            hdrs.setdefault(k.strip().lower(), v.strip())
    return int(m.group(1)), hdrs


def _digest(www: str, user: str, password: str, method: str, uri: str) -> str:
    fields = dict(re.findall(r'(\w+)="?([^",]*)"?', www))
    realm, nonce = fields.get("realm", ""), fields.get("nonce", "")
    ha1 = hashlib.md5(f"{user}:{realm}:{password}".encode()).hexdigest()
    ha2 = hashlib.md5(f"{method}:{uri}".encode()).hexdigest()
    resp = hashlib.md5(f"{ha1}:{nonce}:{ha2}".encode()).hexdigest()
    return f'Digest username="{user}", realm="{realm}", nonce="{nonce}", uri="{uri}", response="{resp}"'


def diagnose(source: str) -> str:
    """Motivo provável em português simples. Só para fontes rtsp://."""
    if not source.lower().startswith("rtsp://"):
        return "não foi possível abrir a fonte de vídeo"
    parts = urlsplit(source)
    host, port = parts.hostname or "", parts.port or 554
    user, password = unquote(parts.username or ""), unquote(parts.password or "")
    if not host:
        return "endereço RTSP inválido"
    clean = urlunsplit((parts.scheme, f"{host}:{port}", parts.path or "/", parts.query, ""))
    try:
        socket.create_connection((host, port), timeout=TIMEOUT).close()
    except socket.timeout:
        return f"a câmera não respondeu em {host}:{port} – confira o IP, se a câmera está ligada e na mesma rede"
    except OSError:
        return f"conexão recusada em {host}:{port} – confira a porta RTSP da câmera (padrão 554) e se o RTSP está habilitado"
    try:
        code, hdrs = _rtsp_request(host, port, "DESCRIBE", clean, {"Accept": "application/sdp"})
        if code == 401:
            www = hdrs.get("www-authenticate", "")
            if not user:
                return "a câmera exige usuário e senha – inclua no endereço (rtsp://usuario:senha@ip:554/...)"
            if www.lower().startswith("digest"):
                auth = _digest(www, user, password, "DESCRIBE", clean)
            else:
                auth = "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()
            code, _ = _rtsp_request(host, port, "DESCRIBE", clean, {"Accept": "application/sdp", "Authorization": auth})
    except (OSError, ValueError):
        return f"{host}:{port} respondeu, mas não como câmera RTSP – confira a porta"
    if code == 401 and parts.path in ("", "/"):
        return ("usuário ou senha recusados – e o endereço está sem o caminho do stream: complete-o antes de "
                f"tentar outra senha ({HINT_PATHS}). Atenção: muitas câmeras bloqueiam após várias tentativas erradas")
    if code == 401:
        return "usuário ou senha recusados pela câmera (atenção: muitas câmeras bloqueiam após várias tentativas erradas)"
    if code in (404, 400):
        return f"caminho do stream não existe nesta câmera – {HINT_PATHS}"
    if code == 403:
        return "a câmera recusou o acesso (403) – o usuário pode não ter permissão de visualização"
    if code >= 300:
        return f"a câmera respondeu com erro RTSP {code}"
    return "a câmera aceitou a conexão, mas o vídeo não abre – use H.264 no stream (desligue H.265, Smart Codec/H.264+)"
