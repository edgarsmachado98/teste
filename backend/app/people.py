"""Pessoas: validação de CPF, máscara, fotos e importação de planilha."""

from __future__ import annotations

import csv
import io
import re
import uuid
from pathlib import Path

from .config import settings


def only_digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def valid_cpf(value: str) -> bool:
    cpf = only_digits(value)
    if len(cpf) != 11 or cpf == cpf[0] * 11:
        return False
    for size in (9, 10):
        total = sum(int(cpf[i]) * (size + 1 - i) for i in range(size))
        digit = (total * 10) % 11 % 10
        if digit != int(cpf[size]):
            return False
    return True


def format_cpf(cpf: str) -> str:
    return f"{cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:]}" if len(cpf) == 11 else cpf


def mask_cpf(cpf: str) -> str:
    """Exibição em listas: ***.093.554-** (padrão usado por órgãos públicos)."""
    return f"***.{cpf[3:6]}.{cpf[6:9]}-**" if len(cpf) == 11 else "***"


def people_dir() -> Path:
    path = Path(settings.people_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


IMAGE_SIGNATURES = {b"\xff\xd8\xff": ".jpg", b"\x89PNG\r\n\x1a\n": ".png"}


def save_photo(person_id: int, data: bytes) -> str:
    ext = next((e for sig, e in IMAGE_SIGNATURES.items() if data.startswith(sig)), None)
    if ext is None:
        raise ValueError("envie uma imagem JPG ou PNG")
    if len(data) > 5 * 1024 * 1024:
        raise ValueError("a foto deve ter até 5 MB")
    name = f"{person_id}-{uuid.uuid4().hex[:12]}{ext}"
    (people_dir() / name).write_bytes(data)
    return name


def delete_photo(name: str | None) -> None:
    if name:
        (people_dir() / name).unlink(missing_ok=True)


# ---------- Importação de planilha (CSV exportado do RH/Excel) ----------

COLUMNS = {
    "nome": "name", "cpf": "cpf", "matricula": "registration", "matrícula": "registration",
    "setor": "sector", "funcao": "role", "função": "role", "cargo": "role", "turno": "shift",
    "unidade": "unit", "vinculo": "employment", "vínculo": "employment", "empresa": "company",
    "gestor": "manager", "colete": "badge_code", "numero": "badge_code", "número": "badge_code", "cracha": "badge_code",
}
EMPLOYMENT_ALIASES = {"clt": "clt", "efetivo": "clt", "terceiro": "terceiro", "terceirizado": "terceiro",
                      "temporario": "temporario", "temporário": "temporario", "estagiario": "estagiario",
                      "estagiário": "estagiario"}
TEMPLATE_CSV = ("nome;cpf;matricula;unidade;setor;funcao;turno;vinculo;empresa;gestor;colete\n"
                "Nome Sobrenome (exemplo);123.456.789-09;000001;Unidade Joinville;Prensas;Operadora de prensa;"
                "Turno B;CLT;;Elaine Prado;0417\n")


def parse_csv(raw: bytes) -> list[dict]:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    sample = text[:2000]
    delimiter = ";" if sample.count(";") >= sample.count(",") else ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = list(reader)
    if not rows:
        return []
    header = [COLUMNS.get(h.strip().lower()) for h in rows[0]]
    if "name" not in header or "cpf" not in header:
        raise ValueError("a planilha precisa das colunas 'nome' e 'cpf' (baixe o modelo)")
    out = []
    for line_no, row in enumerate(rows[1:], start=2):
        if not any(cell.strip() for cell in row):
            continue
        record = {key: (row[i].strip() if i < len(row) else "") for i, key in enumerate(header) if key}
        record["_line"] = line_no
        out.append(record)
    return out
