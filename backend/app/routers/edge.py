"""VigIA Edge: cadastro por código, credencial por Edge, rotas do detector via Edge e túnel."""

import json
from typing import Literal
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import (APIRouter, BackgroundTasks, Depends, File, Form, Header, HTTPException, Request, UploadFile,
                     WebSocket, WebSocketDisconnect)
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import audit
from ..auth import require_role
from ..common import EVIDENCE_DIR, get_or_404
from ..config import settings
from ..database import SessionLocal, get_db
from ..edge_ca import ca_paths, normalize, sign_csr, sign_server_csr
from ..edge_tunnel import hub as edge_hub
from ..health import set_camera_health
from ..models import Camera, Edge, EdgeEnrollment, EdgeMediaKey, Event, Rule, Unit, User
from ..schemas import DetectorCamera, RuleOut, StatsIn
from ..security import token_hash
from ..timeutil import as_utc
from ..ws import hub
from .detector import _parse_boxes, record_stats, register_event

router = APIRouter(prefix="/api/edge")
admin = require_role("admin")

CODE_HOURS = 24
ONLINE_GRACE = timedelta(seconds=90)
_enroll_failures: dict[str, list[float]] = {}  # tentativas erradas por IP (contra força bruta)


# ---------- Autenticação do Edge ----------

def _edge_from_headers(db: Session, edge_id: str | None, key: str | None, cert_sha256: str | None = None) -> Edge | None:
    if not edge_id or not key or not edge_id.isdigit():
        return None
    edge = db.get(Edge, int(edge_id))
    if edge is None or edge.revoked_at is not None or not secrets.compare_digest(edge.key_hash, token_hash(key)):
        return None
    if settings.edge_require_mtls:
        # o proxy HTTPS validou o certificado contra a CA desta instância e repassou a impressão digital
        given = normalize(cert_sha256)
        if not edge.cert_fingerprint or not given or not secrets.compare_digest(given, edge.cert_fingerprint):
            return None
    return edge


def require_edge(x_edge_id: str | None = Header(None), x_edge_key: str | None = Header(None),
                 x_client_cert_sha256: str | None = Header(None), db: Session = Depends(get_db)) -> Edge:
    edge = _edge_from_headers(db, x_edge_id, x_edge_key, x_client_cert_sha256)
    if edge is None:
        raise HTTPException(401, "credencial do Edge inválida ou revogada")
    edge.last_seen_at = datetime.now(timezone.utc)
    return edge


def _camera_of(db: Session, edge: Edge, camera_id: int) -> Camera:
    camera = get_or_404(db, Camera, camera_id)
    if camera.unit_id != edge.unit_id:
        raise HTTPException(403, "câmera de outra unidade")
    return camera


# ---------- Administração (guia Configurações) ----------

def edge_out(e: Edge) -> dict:
    seen = as_utc(e.last_seen_at) if e.last_seen_at else None
    online = edge_hub.online(e.id)
    return {"id": e.id, "name": e.name, "unit_id": e.unit_id, "unit": e.unit.name if e.unit else None,
            "enrolled_at": e.enrolled_at, "revoked": e.revoked_at is not None, "last_seen_at": e.last_seen_at,
            "online": online, "recent": bool(seen and datetime.now(timezone.utc) - seen < ONLINE_GRACE),
            "version": e.version, "status": e.status or {}, "mtls": bool(e.cert_fingerprint),
            "mtls_required": settings.edge_require_mtls}


class EnrollmentIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    unit_id: int


@router.get("/edges")
def list_edges(_: User = Depends(admin), db: Session = Depends(get_db)):
    return [edge_out(e) for e in db.scalars(select(Edge).order_by(Edge.revoked_at.is_not(None), Edge.name))]


@router.post("/enrollments", status_code=201)
def create_enrollment(data: EnrollmentIn, request: Request, user: User = Depends(admin), db: Session = Depends(get_db)):
    """Código de instalação: digitado uma vez no Edge do cliente; vale 24 h e só pode ser usado uma vez."""
    get_or_404(db, Unit, data.unit_id)
    raw = secrets.token_hex(4).upper()
    code = f"{raw[:4]}-{raw[4:]}"
    expires = datetime.now(timezone.utc) + timedelta(hours=CODE_HOURS)
    db.add(EdgeEnrollment(code_hash=token_hash(code), name=data.name, unit_id=data.unit_id, expires_at=expires,
                          created_by_id=user.id))
    audit.record(db, user, "edge_codigo_gerado", "edge", None, f"{data.name} (válido até {expires:%d/%m %H:%M} UTC)", request)
    db.commit()
    return {"code": code, "expires_at": expires}


@router.delete("/edges/{edge_id}", status_code=204)
async def revoke_edge(edge_id: int, request: Request, user: User = Depends(admin), db: Session = Depends(get_db)):
    edge = get_or_404(db, Edge, edge_id)
    if edge.revoked_at is None:
        edge.revoked_at = datetime.now(timezone.utc)
        audit.record(db, user, "edge_revogado", "edge", edge.id, edge.name, request)
        db.commit()
    await edge_hub.disconnect(edge.id)


class EnrollIn(BaseModel):
    code: str = Field(min_length=4, max_length=20)
    version: str = Field("", max_length=40)
    csr: str | None = Field(None, max_length=4000)  # pedido de certificado do Edge (mTLS)


@router.post("/enroll")
def enroll(data: EnrollIn, request: Request, db: Session = Depends(get_db)):
    """Chamado pelo Edge na instalação: troca o código por uma credencial própria (mostrada só agora)."""
    import time
    ip = request.client.host if request.client else "?"
    recent = [t for t in _enroll_failures.get(ip, []) if time.monotonic() - t < 600]
    if len(recent) >= 10:
        raise HTTPException(429, "muitas tentativas – aguarde 10 minutos")
    code = data.code.strip().upper()
    enr = db.scalar(select(EdgeEnrollment).where(EdgeEnrollment.code_hash == token_hash(code)))
    now = datetime.now(timezone.utc)
    if enr is None or enr.used_at is not None or as_utc(enr.expires_at) < now:
        _enroll_failures[ip] = [*recent, time.monotonic()]
        raise HTTPException(400, "código inválido, já usado ou vencido – gere outro em Configurações")
    key = secrets.token_urlsafe(32)
    edge = Edge(name=enr.name, unit_id=enr.unit_id, key_hash=token_hash(key), version=data.version, last_seen_at=now)
    enr.used_at = now
    db.add(edge)
    db.flush()
    client_cert = ca_pem = None
    if data.csr:
        try:
            client_cert, ca_pem, edge.cert_fingerprint = sign_csr(data.csr, edge.id, edge.name)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
    elif settings.edge_require_mtls:
        raise HTTPException(400, "esta instância exige mTLS: atualize o VigIA Edge e cadastre de novo")
    # Criptografia das imagens: chave nova para este Edge + chaves anteriores da unidade (troca de máquina)
    import base64
    import os

    from ..settings_store import decrypt, encrypt
    kid = secrets.token_hex(4)
    db.add(EdgeMediaKey(unit_id=edge.unit_id, kid=kid, key_enc=encrypt(base64.b64encode(os.urandom(32)).decode()),
                        edge_id=edge.id))
    db.flush()
    keys = [{"kid": k.kid, "key": decrypt(k.key_enc)} for k in
            db.scalars(select(EdgeMediaKey).where(EdgeMediaKey.unit_id == edge.unit_id).order_by(EdgeMediaKey.id))]
    audit.record(db, None, "edge_cadastrado", "edge", edge.id,
                 f"{edge.name} – {request.client.host if request.client else ''}", request)
    db.commit()
    return {"edge_id": edge.id, "key": key, "name": edge.name, "unit_id": edge.unit_id,
            "retention_days": settings.retention_days, "media_keys": [k for k in keys if k["key"]], "active_kid": kid,
            "client_cert": client_cert, "ca_cert": ca_pem}


# ---------- Rotas do detector, vindas pelo Edge ----------

@router.get("/detector/config", response_model=list[DetectorCamera])
def edge_config(edge: Edge = Depends(require_edge), db: Session = Depends(get_db)):
    """Câmeras e regras da unidade do Edge (o Edge entrega ao detector local)."""
    db.commit()  # last_seen_at
    cameras = db.scalars(select(Camera).where(Camera.enabled, Camera.unit_id == edge.unit_id)
                         .options(selectinload(Camera.rules))).all()
    return [DetectorCamera(id=c.id, name=c.name, source=c.source,
                           rules=[RuleOut.model_validate(r) for r in c.rules if r.enabled]) for c in cameras]


@router.get("/settings")
def edge_settings(edge: Edge = Depends(require_edge), db: Session = Depends(get_db)):
    db.commit()
    return {"retention_days": settings.retention_days, "edge_id": edge.id, "name": edge.name,
            "auto_update": settings.edge_auto_update}


def _parse_when(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        when = datetime.fromisoformat(value)
    except ValueError:
        return None
    when = when if when.tzinfo else when.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    return when if now - timedelta(days=30) < when <= now + timedelta(minutes=5) else None


@router.post("/events", status_code=201)
async def edge_event(
    background: BackgroundTasks,
    camera_id: int = Form(...), rule_id: int = Form(...), message: str = Form(..., max_length=500),
    boxes: str | None = Form(None), clip_id: str | None = Form(None, max_length=40),
    media_ref: str | None = Form(None, max_length=255), edge_ref: str = Form(..., max_length=40),
    captured_at: str | None = Form(None), thumb: UploadFile | None = File(None),
    edge: Edge = Depends(require_edge), db: Session = Depends(get_db),
):
    """Ocorrência registrada no Edge: a imagem completa fica no storage do cliente (media_ref);
    aqui chegam os dados e a miniatura. edge_ref torna o reenvio seguro (não duplica)."""
    existing = db.scalar(select(Event).where(Event.edge_ref == edge_ref, Event.media_edge_id == edge.id))
    if existing is not None:
        db.commit()
        return {"id": existing.id, "duplicate": True}
    camera = _camera_of(db, edge, camera_id)
    rule = get_or_404(db, Rule, rule_id)
    if rule.camera_id != camera.id:
        raise HTTPException(400, "regra não pertence à câmera")
    if media_ref and (media_ref.startswith(("/", "\\")) or ".." in media_ref):
        raise HTTPException(400, "referência de mídia inválida")
    thumb_file = None
    if thumb is not None:
        data = await thumb.read(512 * 1024 + 1)
        if len(data) > 512 * 1024 or not data.startswith(b"\xff\xd8"):
            raise HTTPException(400, "miniatura inválida (JPEG até 512 KB)")
        now = datetime.now(timezone.utc)
        thumb_file = f"miniaturas/{now:%Y/%m/%d}/{uuid.uuid4().hex}.jpg"
        (EVIDENCE_DIR / thumb_file).parent.mkdir(parents=True, exist_ok=True)
        (EVIDENCE_DIR / thumb_file).write_bytes(data)
    extra = {"media_edge_id": edge.id, "thumb_file": thumb_file, "edge_ref": edge_ref,
             "media_synced_at": datetime.now(timezone.utc)}  # não vai para o NAS da nuvem
    when = _parse_when(captured_at)
    if when:
        extra["created_at"] = when
    return await register_event(db, background, camera, rule, message, _parse_boxes(boxes), clip_id, media_ref, **extra)


class EdgeClipIn(BaseModel):
    folder: str = Field(max_length=255)
    frames: int = Field(ge=1, le=300)
    duration: float = Field(gt=0, le=600)
    format: Literal["jpg", "webm"] = "jpg"


@router.post("/clips/{clip_id}", status_code=204)
async def edge_clip(clip_id: str, data: EdgeClipIn, edge: Edge = Depends(require_edge), db: Session = Depends(get_db)):
    event = db.scalar(select(Event).where(Event.clip_id == clip_id, Event.media_edge_id == edge.id))
    if event is None:
        raise HTTPException(404, "ocorrência do clipe não encontrada")
    if data.folder.startswith(("/", "\\")) or ".." in data.folder:
        raise HTTPException(400, "pasta inválida")
    event.clip_dir, event.clip_frames, event.clip_duration = data.folder, data.frames, data.duration
    event.clip_format = data.format
    db.commit()
    await hub.broadcast({"kind": "event_updated", "id": event.id})


class HealthIn(BaseModel):
    health: str = "ok"


@router.post("/cameras/{camera_id}/health", status_code=204)
async def edge_health(camera_id: int, data: HealthIn, background: BackgroundTasks,
                      edge: Edge = Depends(require_edge), db: Session = Depends(get_db)):
    """O quadro ao vivo fica no Edge; aqui só a saúde da imagem e o horário do último quadro."""
    camera = _camera_of(db, edge, camera_id)
    camera.last_frame_at = datetime.now(timezone.utc)
    await set_camera_health(db, camera, data.health if data.health in ("ok", "escura", "obstruida", "congelada")
                            else "ok", background)
    db.commit()


class EdgeStatsIn(StatsIn):
    observed_at: str | None = None


@router.post("/stats", status_code=204)
def edge_stats(data: EdgeStatsIn, edge: Edge = Depends(require_edge), db: Session = Depends(get_db)):
    _camera_of(db, edge, data.camera_id)
    record_stats(db, data, _parse_when(data.observed_at))


# ---------- Atualização remota ----------

def _packages() -> list[tuple[tuple, str]]:
    """Versões publicadas (zip + assinatura), da mais nova para a mais antiga."""
    import re
    from pathlib import Path
    folder = Path(settings.edge_packages_dir)
    found = []
    for z in folder.glob("vigia-edge-*.zip") if folder.exists() else []:
        m = re.fullmatch(r"vigia-edge-(\d+\.\d+\.\d+)\.zip", z.name)
        if m and z.with_suffix(".sig").exists():
            found.append((tuple(int(x) for x in m.group(1).split(".")), m.group(1)))
    return sorted(found, reverse=True)


@router.get("/update/latest")
def update_latest(edge: Edge = Depends(require_edge), db: Session = Depends(get_db)):
    db.commit()
    pkgs = _packages()
    return {"version": pkgs[0][1] if pkgs else None}


@router.get("/update/{version}.{ext}")
def update_file(version: str, ext: str, edge: Edge = Depends(require_edge)):
    from pathlib import Path

    from fastapi.responses import FileResponse
    if ext not in ("zip", "sig") or version not in {v for _, v in _packages()}:
        raise HTTPException(404, "pacote não encontrado")
    path = Path(settings.edge_packages_dir) / f"vigia-edge-{version}.{ext}"
    return FileResponse(path, media_type="application/zip" if ext == "zip" else "text/plain")


@router.get("/packages")
def list_packages(_: User = Depends(admin)):
    pkgs = _packages()
    return {"latest": pkgs[0][1] if pkgs else None, "versions": [v for _, v in pkgs],
            "auto_update": settings.edge_auto_update}


@router.post("/edges/{edge_id}/update", status_code=202)
async def request_update(edge_id: int, request: Request, user: User = Depends(admin), db: Session = Depends(get_db)):
    """Pede ao Edge que baixe e instale a versão mais nova agora (ele confere a assinatura do fornecedor)."""
    edge = get_or_404(db, Edge, edge_id)
    if edge.revoked_at is not None:
        raise HTTPException(400, "Edge revogado")
    if not _packages():
        raise HTTPException(400, "nenhuma versão publicada nesta instância (deploy/nuvem/clientes.sh publicar-edge)")
    ws = edge_hub.sockets.get(edge.id)
    if ws is None:
        raise HTTPException(409, "Edge desconectado – ele atualiza ao reconectar, se a atualização automática estiver ligada")
    await ws.send_json({"op": "update"})
    audit.record(db, user, "edge_atualizacao_pedida", "edge", edge.id, f"{edge.name}: {edge.version} → {_packages()[0][1]}",
                 request)
    db.commit()


# ---------- Acesso direto pela rede da fábrica ----------

class LanIn(BaseModel):
    csr: str = Field(max_length=4000)
    ips: list[str] = Field(max_length=8)
    hostname: str = Field("", max_length=63)


@router.post("/lan")
def edge_lan(data: LanIn, request: Request, edge: Edge = Depends(require_edge), db: Session = Depends(get_db)):
    """Certificado de servidor do Edge para os IPs da rede local + chave que assina os links diretos."""
    from ..settings_store import decrypt, encrypt
    try:
        cert = sign_server_csr(data.csr, data.ips, data.hostname)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    key = decrypt(edge.lan_key_enc) if edge.lan_key_enc else None
    if not key:
        key = secrets.token_hex(32)
        edge.lan_key_enc = encrypt(key)
    audit.record(db, None, "edge_certificado_lan", "edge", edge.id, f"{edge.name}: {', '.join(data.ips)}", request)
    db.commit()
    return {"cert": cert, "lan_key": key}


@router.get("/ca.crt")
def download_ca(_: User = Depends(admin)):
    """CA do cliente, para a TI instalar nos computadores da empresa (acesso direto pela rede da fábrica)."""
    from fastapi.responses import Response as RawResponse
    crt, _key = ca_paths()
    return RawResponse(crt.read_bytes(), media_type="application/x-x509-ca-cert",
                       headers={"Content-Disposition": 'attachment; filename="vigia-ca-cliente.crt"'})


def direct_links(db: Session, event: Event) -> dict | None:
    """Links assinados (10 min) para o navegador buscar a mídia direto no Edge, na rede da fábrica."""
    import hashlib
    import hmac
    import time
    if not settings.edge_lan_direct or not event.media_edge_id:
        return None
    edge = db.get(Edge, event.media_edge_id)
    lan = (edge.status or {}).get("lan") if edge else None
    if not edge or edge.revoked_at or not edge.lan_key_enc or not lan or not lan.get("ready") or not lan.get("ips"):
        return None
    from ..settings_store import decrypt
    key = bytes.fromhex(decrypt(edge.lan_key_enc) or "")
    if not key:
        return None
    exp = int(time.time()) + 600
    bases = [f"https://{ip}:{lan.get('port', 8443)}" for ip in lan["ips"][:3]]

    def link(rel):
        sig = hmac.new(key, f"{edge.id}|{rel}|{exp}".encode(), hashlib.sha256).hexdigest()
        return f"/m/{rel}?e={exp}&s={sig}"
    return {"edge_id": edge.id, "bases": bases,
            "image": link(event.image_file) if event.image_file else None,
            "clip": link(event.clip_dir) if event.clip_dir and event.clip_format == "webm" else None}


# ---------- Túnel ----------

@router.websocket("/tunnel")
async def tunnel(ws: WebSocket):
    with SessionLocal() as db:
        edge = _edge_from_headers(db, ws.headers.get("x-edge-id"), ws.headers.get("x-edge-key"),
                                  ws.headers.get("x-client-cert-sha256"))
        if edge is None:
            await ws.close(code=4001)
            return
        edge_id = edge.id
        edge.last_seen_at = datetime.now(timezone.utc)
        db.commit()
    await ws.accept()
    await edge_hub.attach(edge_id, ws)
    await hub.broadcast({"kind": "edge_status", "edge_id": edge_id, "online": True})
    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if msg.get("bytes") is not None:
                edge_hub.handle_binary(msg["bytes"])
                continue
            try:
                data = json.loads(msg.get("text") or "{}")
            except ValueError:
                continue
            if data.get("type") == "status":
                _save_status(edge_id, data)
            elif "id" in data and data.get("ok") is False:
                edge_hub.handle_error(data)
    except WebSocketDisconnect:
        pass
    finally:
        edge_hub.detach(edge_id, ws)
        await hub.broadcast({"kind": "edge_status", "edge_id": edge_id, "online": False})


def _save_status(edge_id: int, data: dict) -> None:
    allowed = {"disk_free_gb", "disk_total_gb", "media_ok", "media_dir", "queue", "cameras", "retention_days", "encrypted", "lan",
               "update",
               "detector_seen_at", "uptime_s", "media_files"}
    with SessionLocal() as db:
        edge = db.get(Edge, edge_id)
        if edge is None or edge.revoked_at is not None:
            return
        edge.status = {k: v for k, v in data.items() if k in allowed}
        edge.version = str(data.get("version", ""))[:40]
        edge.last_seen_at = datetime.now(timezone.utc)
        db.commit()
