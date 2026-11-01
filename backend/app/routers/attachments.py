"""Anexos do plano de ação: o documento que comprova a medida tomada (advertência assinada,
lista de presença do DDS, ata da reciclagem assinada pelo colaborador...)."""

import re
import secrets
from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .. import audit
from ..auth import current_user, has_role
from ..common import EVIDENCE_DIR, attachment_out, get_or_404
from ..database import get_db
from ..models import ATTACHMENT_KINDS, ActionItem, Attachment, User
from ..ws import hub

router = APIRouter(prefix="/api")

MAX_BYTES = 10 * 1024 * 1024
MAX_PER_ACTION = 20
FOLDER = "anexos"


def sniff(data: bytes) -> tuple[str, str] | None:
    """Tipo pelo conteúdo (não pela extensão): PDF ou foto/escaneamento."""
    if data.startswith(b"%PDF-"):
        return "application/pdf", "pdf"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", "jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", "webp"
    return None


def _can_use(user: User, action: ActionItem) -> bool:
    return has_role(user, "tecnico") or action.responsible_id == user.id


def _safe_name(name: str, ext: str) -> str:
    base = re.sub(r"[^\w\s.\-()]", "", (name or "").strip(), flags=re.UNICODE)[:150].strip() or "documento"
    if base.lower().endswith(".jpeg") and ext == "jpg":
        return base
    return base if base.lower().endswith(f".{ext}") else f"{base}.{ext}"


@router.post("/actions/{action_id}/attachments", status_code=201)
async def upload(action_id: int, request: Request, file: UploadFile = File(...), kind: str = Form("outro"),
                 user: User = Depends(current_user), db: Session = Depends(get_db)):
    action = get_or_404(db, ActionItem, action_id)
    if not _can_use(user, action):
        raise HTTPException(403, "somente o responsável pela ação ou a equipe de segurança pode anexar documentos")
    if action.status == "cancelada":
        raise HTTPException(400, "ação cancelada não recebe anexos")
    if kind not in ATTACHMENT_KINDS:
        raise HTTPException(400, "tipo de documento inválido")
    if len(action.attachments) >= MAX_PER_ACTION:
        raise HTTPException(400, f"limite de {MAX_PER_ACTION} anexos por ação")
    data = await file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "arquivo maior que 10 MB – reduza a resolução do escaneamento ou da foto")
    detected = sniff(data)
    if detected is None:
        raise HTTPException(400, "envie um PDF ou uma foto (JPG, PNG ou WEBP) do documento")
    content_type, ext = detected
    now = datetime.now(timezone.utc)
    rel = f"{FOLDER}/{now:%Y/%m}/acao{action.id}-{secrets.token_hex(8)}.{ext}"
    path = EVIDENCE_DIR / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    att = Attachment(action_id=action.id, kind=kind, filename=_safe_name(file.filename, ext), file=rel,
                     content_type=content_type, size=len(data), uploaded_by_id=user.id)
    db.add(att)
    detail = f"ação #{action.id}: anexo \"{att.filename}\" ({ATTACHMENT_KINDS[kind]})"
    audit.record(db, user, "anexo_incluido", "acao", action.id, detail, request)
    if action.event_id:
        audit.record(db, user, "anexo_incluido", "ocorrencia", action.event_id, detail, request)
    db.commit()
    db.refresh(att)
    if action.event_id:
        await hub.broadcast({"kind": "event_updated", "id": action.event_id})
    return attachment_out(att).model_dump()


@router.get("/attachments/{attachment_id}")
def download(attachment_id: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    att = get_or_404(db, Attachment, attachment_id)
    if not _can_use(user, att.action):
        raise HTTPException(403, "sem permissão para ver este documento")
    path = EVIDENCE_DIR / att.file
    if not path.exists():
        raise HTTPException(404, "arquivo não encontrado no disco (restaure um backup completo)")
    # Documento com dados pessoais (assinatura, medida disciplinar): todo acesso fica registrado.
    audit.record(db, user, "anexo_visualizado", "acao", att.action_id, f"anexo \"{att.filename}\"", request)
    db.commit()
    disposition = f"inline; filename*=UTF-8''{quote(att.filename)}"
    return FileResponse(path, media_type=att.content_type,
                        headers={"Content-Disposition": disposition, "Cache-Control": "private, no-store",
                                 "X-Content-Type-Options": "nosniff"})


@router.delete("/attachments/{attachment_id}", status_code=204)
async def remove(attachment_id: int, request: Request, user: User = Depends(current_user),
                 db: Session = Depends(get_db)):
    att = get_or_404(db, Attachment, attachment_id)
    action = att.action
    # Depois de concluída, a ação é registro de segurança: só gestor remove o comprovante.
    needed = "gestor" if action.status == "concluida" else "tecnico"
    if not (has_role(user, needed) or (action.status == "aberta" and att.uploaded_by_id == user.id)):
        raise HTTPException(403, "ação concluída: somente gestores podem remover comprovantes"
                            if needed == "gestor" else "sem permissão para remover este anexo")
    detail = f"ação #{action.id}: anexo \"{att.filename}\" removido"
    audit.record(db, user, "anexo_removido", "acao", action.id, detail, request)
    if action.event_id:
        audit.record(db, user, "anexo_removido", "ocorrencia", action.event_id, detail, request)
    (EVIDENCE_DIR / att.file).unlink(missing_ok=True)
    db.delete(att)
    db.commit()
    if action.event_id:
        await hub.broadcast({"kind": "event_updated", "id": action.event_id})
