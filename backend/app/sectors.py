"""Padrões de segurança por setor e geração automática das regras de detecção.

Cada setor define EPI obrigatório e regras de comportamento. Ao aplicar, o VigIA cria ou
atualiza as regras de todas as câmeras do setor. Regras criadas à mão não são tocadas; nas
geradas, a zona desenhada e os ajustes finos (confiança, duração, intervalo) são preservados."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import Camera, Rule, Sector, Unit

PPE_LABELS = {"helmet": "capacete", "vest": "colete", "glasses": "óculos", "gloves": "luvas", "mask": "máscara"}
BEHAVIOR_TYPES = ("restricted_zone", "max_people", "fire_smoke")

# Modelos de referência por atividade (ponto de partida; o cliente ajusta à sua realidade)
TEMPLATES = {
    "soldagem": {
        "label": "Soldagem",
        "required_ppe": ["helmet", "gloves", "mask"],
        "delivery_ppe": ["Avental de raspa", "Botina de segurança", "Protetor auricular"],
        "behaviors": {"restricted_zone": {"enabled": True, "severity": "critica"},
                      "max_people": {"enabled": True, "max": 2, "severity": "alta"},
                      "fire_smoke": {"enabled": True, "severity": "critica"}},
        "required_exams": ["aso", "audiometria", "espirometria", "acuidade_visual"],
        "reference": "NR-6 · NR-12",
    },
    "prensas": {
        "label": "Prensas e estampagem",
        "required_ppe": ["helmet", "glasses", "gloves"],
        "delivery_ppe": ["Protetor auricular", "Botina de segurança"],
        "behaviors": {"restricted_zone": {"enabled": True, "severity": "critica"},
                      "max_people": {"enabled": False, "max": 2, "severity": "alta"},
                      "fire_smoke": {"enabled": False, "severity": "critica"}},
        "required_exams": ["aso", "audiometria", "acuidade_visual"],
        "reference": "NR-6 · NR-12",
    },
    "docas": {
        "label": "Docas e logística",
        "required_ppe": ["vest", "helmet"],
        "delivery_ppe": ["Botina de segurança"],
        "behaviors": {"restricted_zone": {"enabled": True, "severity": "alta"},
                      "max_people": {"enabled": True, "max": 3, "severity": "media"},
                      "fire_smoke": {"enabled": False, "severity": "critica"}},
        "required_exams": ["aso", "acuidade_visual", "ecg", "glicemia"],
        "reference": "NR-6 · NR-11",
    },
    "laboratorio": {
        "label": "Laboratório químico",
        "required_ppe": ["glasses", "gloves", "mask"],
        "delivery_ppe": ["Jaleco", "Calçado fechado"],
        "behaviors": {"restricted_zone": {"enabled": False, "severity": "alta"},
                      "max_people": {"enabled": False, "max": 4, "severity": "media"},
                      "fire_smoke": {"enabled": True, "severity": "critica"}},
        "required_exams": ["aso", "espirometria", "hemograma", "indicador_biologico"],
        "reference": "NR-6 · NR-32",
    },
    "alimentos": {
        "label": "Indústria de alimentos",
        "required_ppe": ["mask", "gloves"],
        "delivery_ppe": ["Touca", "Bota de PVC", "Avental"],
        "behaviors": {"restricted_zone": {"enabled": True, "severity": "alta"},
                      "max_people": {"enabled": False, "max": 4, "severity": "media"},
                      "fire_smoke": {"enabled": False, "severity": "critica"}},
        "required_exams": ["aso"],
        "reference": "NR-6 · NR-36",
    },
}


def ensure_default_unit(db: Session) -> Unit:
    """Instalações antigas não tinham unidades: cria uma para começar."""
    unit = db.scalar(select(Unit).order_by(Unit.id))
    if unit is None:
        unit = Unit(name=settings.company_name or "Unidade principal")
        db.add(unit)
        db.commit()
    return unit


def behavior(sector: Sector, kind: str) -> dict:
    return {"enabled": False, "severity": "alta", **(sector.behaviors or {}).get(kind, {})}


@dataclass
class DesiredRule:
    type: str
    name: str
    params: dict
    severity: str
    needs_zone: bool = False


def desired_rules(sector: Sector) -> list[DesiredRule]:
    rules = []
    if sector.required_ppe:
        names = ", ".join(PPE_LABELS.get(p, p) for p in sector.required_ppe)
        rules.append(DesiredRule("ppe_missing", f"{sector.name}: EPI ({names})",
                                 {"required": list(sector.required_ppe)}, sector.ppe_severity))
    zone = behavior(sector, "restricted_zone")
    if zone["enabled"]:
        rules.append(DesiredRule("restricted_zone", f"{sector.name}: zona restrita", {}, zone["severity"], True))
    crowd = behavior(sector, "max_people")
    if crowd["enabled"]:
        limit = int(crowd.get("max", 2))
        rules.append(DesiredRule("max_people", f"{sector.name}: máximo de {limit} pessoas", {"max_people": limit},
                                 crowd["severity"]))
    fire = behavior(sector, "fire_smoke")
    if fire["enabled"]:
        rules.append(DesiredRule("fire_smoke", f"{sector.name}: fogo e fumaça", {}, fire["severity"]))
    return rules


@dataclass
class ApplyResult:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    pending_zone: list[str] = field(default_factory=list)
    cameras: int = 0
    per_camera: int = 0

    def as_dict(self) -> dict:
        return {"created": self.created, "updated": self.updated, "removed": self.removed,
                "pending_zone": self.pending_zone, "cameras": self.cameras, "per_camera": self.per_camera,
                "total": len(self.created) + len(self.updated)}


def apply_sector(db: Session, sector: Sector, dry_run: bool = False) -> ApplyResult:
    """Cria/atualiza as regras geradas nas câmeras do setor e remove as que não valem mais.
    Com dry_run, só calcula a prévia (nada é gravado)."""
    result = ApplyResult()
    cameras = db.scalars(select(Camera).where(Camera.sector_id == sector.id).order_by(Camera.name)).all()
    result.cameras = len(cameras)
    wanted = desired_rules(sector)
    result.per_camera = len(wanted)
    camera_ids = {c.id for c in cameras}

    # Câmeras que saíram do setor: remove as regras geradas por ele
    stale = db.scalars(select(Rule).where(Rule.sector_id == sector.id)).all()
    for rule in stale:
        if rule.camera_id not in camera_ids:
            result.removed.append(f"{rule.camera.name if rule.camera else rule.camera_id}: {rule.name}")
            if not dry_run:
                db.delete(rule)

    for camera in cameras:
        existing = {r.type: r for r in camera.rules if r.sector_id == sector.id}
        for want in wanted:
            rule = existing.pop(want.type, None)
            zone = rule.zone if rule else []
            enabled = bool(zone) if want.needs_zone else True
            label = f"{camera.name}: {want.name}"
            if want.needs_zone and not zone:
                result.pending_zone.append(camera.name)
            if rule is None:
                result.created.append(label)
                if not dry_run:
                    db.add(Rule(camera_id=camera.id, sector_id=sector.id, type=want.type, name=want.name,
                                params=want.params, severity=want.severity, zone=[], enabled=enabled,
                                start_hour=sector.start_hour, end_hour=sector.end_hour))
            else:
                changed = (rule.name, rule.params, rule.severity, rule.start_hour, rule.end_hour) != \
                    (want.name, want.params, want.severity, sector.start_hour, sector.end_hour)
                if changed:
                    result.updated.append(label)
                if not dry_run:
                    rule.name, rule.params, rule.severity = want.name, want.params, want.severity
                    rule.start_hour, rule.end_hour = sector.start_hour, sector.end_hour
                    if want.needs_zone and not zone:
                        rule.enabled = False  # zona restrita sem zona desenhada pegaria a imagem toda
        for rule in existing.values():  # tipos desativados no padrão
            result.removed.append(f"{camera.name}: {rule.name}")
            if not dry_run:
                db.delete(rule)
    return result
