"""Motor de regras: transforma detecções da IA em violações, com filtro de zona, horário,
duração mínima e intervalo entre alertas. Não depende de OpenCV nem do modelo."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

# Rótulos canônicos usados pelas regras. Os modelos são mapeados para estes nomes em labels.py.
PERSON = "person"
PPE_ITEMS = ("helmet", "vest", "glasses", "gloves", "mask")
FIRE_LABELS = ("fire", "smoke")

PT_FIRE = {"fire": "fogo", "smoke": "fumaça"}
PPE_NAMES = {"helmet": "capacete", "vest": "colete", "glasses": "óculos", "gloves": "luvas", "mask": "máscara"}


@dataclass(frozen=True)
class Detection:
    label: str
    confidence: float
    # Caixa normalizada (0..1): x1, y1, x2, y2
    box: tuple[float, float, float, float]

    @property
    def center(self) -> tuple[float, float]:
        x1, y1, x2, y2 = self.box
        return (x1 + x2) / 2, (y1 + y2) / 2

    @property
    def foot(self) -> tuple[float, float]:
        """Ponto de apoio da pessoa (base da caixa), melhor referência para zonas no chão."""
        x1, _, x2, y2 = self.box
        return (x1 + x2) / 2, y2


@dataclass
class Violation:
    rule_id: int
    message: str
    detections: list[Detection]


def point_in_polygon(point: tuple[float, float], polygon: list[list[float]]) -> bool:
    if not polygon:
        return True
    x, y = point
    inside = False
    j = len(polygon) - 1
    for i in range(len(polygon)):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def contains(outer: tuple[float, float, float, float], point: tuple[float, float], margin: float = 0.1) -> bool:
    """Ponto dentro da caixa, com margem relativa ao tamanho da caixa (capacete pode sair um pouco)."""
    x1, y1, x2, y2 = outer
    mx, my = (x2 - x1) * margin, (y2 - y1) * margin
    return x1 - mx <= point[0] <= x2 + mx and y1 - my <= point[1] <= y2 + my


def in_schedule(rule: dict, now: datetime) -> bool:
    start, end = rule.get("start_hour"), rule.get("end_hour")
    if start is None or end is None:
        return True
    hour = now.hour
    if start <= end:
        return start <= hour < end
    return hour >= start or hour < end  # turno que atravessa a meia-noite


# Onde cada EPI fica no corpo, em fração da altura da caixa da pessoa (0 = topo da cabeça).
# Capacete no chão ou na mão perto da pessoa não conta; capacete de outra pessoa ao lado também não.
BODY_REGION = {"helmet": (-0.10, 0.35), "glasses": (0.0, 0.30), "mask": (0.0, 0.35), "vest": (0.12, 0.80),
               "gloves": (0.0, 1.0)}
DEFAULT_MIN_PERSON_HEIGHT = 0.10  # pessoa menor que 10% da altura da imagem: longe demais para avaliar EPI
MIN_STANDING_RATIO = 1.15  # altura/largura em pixels: abaixo disso não parece pessoa em pé (máquina, sombra...)


def in_region(person: Detection, item: Detection, region: tuple[float, float]) -> bool:
    x1, y1, x2, y2 = person.box
    h, w = y2 - y1, x2 - x1
    cx, cy = item.center
    top, bottom = region
    return x1 - w * 0.15 <= cx <= x2 + w * 0.15 and y1 + h * top <= cy <= y1 + h * bottom


def evaluable(person: Detection, rule: dict) -> bool:
    """A pessoa aparece grande e nítida o bastante para julgar o EPI?"""
    x1, y1, x2, y2 = person.box
    height = y2 - y1
    if height < float(rule.get("params", {}).get("min_person_height", DEFAULT_MIN_PERSON_HEIGHT)):
        return False
    aspect = rule.get("_aspect")  # largura/altura do quadro, informado pelo detector
    if aspect and (x2 - x1) > 0 and (height / (x2 - x1)) / aspect < MIN_STANDING_RATIO:
        return False
    return True


def missing_ppe(person: Detection, items: list[Detection], required: list[str],
                detectable: set[str] | None = None) -> list[str]:
    """EPIs ausentes para uma pessoa.

    Ausente quando o modelo vê 'no_<item>' na região do corpo, ou quando o modelo SABE reconhecer o item
    e não o encontrou ali. Item que nenhum modelo carregado reconhece não é julgado (sem modelo de
    capacete, ninguém pode ser acusado de estar sem capacete)."""
    missing = []
    for item in required:
        knows_item = detectable is None or item in detectable
        knows_absence = detectable is None or f"no_{item}" in detectable
        if not (knows_item or knows_absence):
            continue
        region = BODY_REGION.get(item, (0.0, 1.0))
        near = [d for d in items if in_region(person, d, region)] if detectable is not None else \
            [d for d in items if contains(person.box, d.center)]
        negative = any(d.label == f"no_{item}" for d in near)
        positive = any(d.label == item for d in near)
        if negative or (knows_item and not positive):
            missing.append(item)
    return missing


def unverifiable(rule: dict) -> list[str]:
    """EPIs exigidos pela regra que nenhum modelo carregado reconhece."""
    detectable = rule.get("_detectable")
    if rule.get("type") != "ppe_missing" or detectable is None:
        return []
    required = rule.get("params", {}).get("required") or ["helmet"]
    return [i for i in required if i not in detectable and f"no_{i}" not in detectable]


def _filter(rule: dict, detections: list[Detection]) -> tuple[list[Detection], list[Detection]]:
    """Detecções com confiança suficiente e as pessoas cujos pés estão na zona."""
    min_conf = rule.get("min_confidence", 0.5)
    zone = rule.get("zone") or []
    dets = [d for d in detections if d.confidence >= min_conf]
    people = [d for d in dets if d.label == PERSON and point_in_polygon(d.foot, zone)]
    return dets, people


def ppe_check(rule: dict, dets: list[Detection], people: list[Detection]) -> tuple[list[Detection], set[str]]:
    """Pessoas sem algum EPI obrigatório e o conjunto de itens faltantes.
    Pessoas longe demais ou que não parecem estar em pé ficam de fora (nem conformes, nem infratoras)."""
    required = rule.get("params", {}).get("required") or ["helmet"]
    detectable = rule.get("_detectable")
    items = [d for d in dets if d.label != PERSON]
    offenders, missing_all = [], set()
    for person in people:
        missing = missing_ppe(person, items, required, detectable)
        if missing:
            offenders.append(person)
            missing_all.update(missing)
    return offenders, missing_all


def ppe_people(rule: dict, people: list[Detection]) -> list[Detection]:
    if rule.get("_detectable") is None:
        return people  # chamada sem contexto do detector (testes antigos): comportamento original
    return [p for p in people if evaluable(p, rule)]


def observe(rule: dict, detections: list[Detection]) -> tuple[int, int] | None:
    """Para o índice de conformidade: (pessoas observadas na zona, pessoas sem EPI).
    Só se aplica a regras de EPI."""
    if rule["type"] != "ppe_missing":
        return None
    if unverifiable(rule) == (rule.get("params", {}).get("required") or ["helmet"]):
        return None  # nenhum EPI da regra pode ser verificado: não entra no índice
    dets, people = _filter(rule, detections)
    people = ppe_people(rule, people)
    offenders, _ = ppe_check(rule, dets, people)
    return len(people), len(offenders)


def evaluate_frame(rule: dict, detections: list[Detection]) -> Violation | None:
    """Avalia uma regra em um único quadro (sem considerar tempo)."""
    zone = rule.get("zone") or []
    dets, people = _filter(rule, detections)
    rtype = rule["type"]

    if rtype == "restricted_zone":
        if people:
            return Violation(rule["id"], f"{len(people)} pessoa(s) em zona restrita", people)

    elif rtype == "ppe_missing":
        required = rule.get("params", {}).get("required") or ["helmet"]
        offenders, missing_all = ppe_check(rule, dets, ppe_people(rule, people))
        if offenders:
            names = ", ".join(PPE_NAMES.get(m, m) for m in required if m in missing_all)
            return Violation(rule["id"], f"{len(offenders)} pessoa(s) sem {names}", offenders)

    elif rtype == "fire_smoke":
        hits = [d for d in dets if d.label in FIRE_LABELS and point_in_polygon(d.center, zone)]
        if hits:
            kinds = sorted({PT_FIRE[d.label] for d in hits})
            return Violation(rule["id"], f"{' e '.join(kinds).capitalize()} detectado", hits)

    elif rtype == "max_people":
        limit = int(rule.get("params", {}).get("max_people", 0))
        if len(people) > limit:
            return Violation(rule["id"], f"{len(people)} pessoas na zona (máx. {limit})", people)

    return None


@dataclass
class _RuleState:
    first_seen: float | None = None
    last_seen: float | None = None
    last_alert: float | None = None


@dataclass
class RuleTracker:
    """Aplica duração mínima e intervalo entre alertas para as regras de uma câmera.

    `grace` tolera falhas curtas de detecção (ex.: pessoa ocluída por 1 quadro) sem
    reiniciar a contagem da duração mínima."""

    grace: float = 1.5
    _states: dict[int, _RuleState] = field(default_factory=dict)

    def update(self, rules: list[dict], detections: list[Detection], now_ts: float, now: datetime) -> list[Violation]:
        fired = []
        active_ids = set()
        for rule in rules:
            active_ids.add(rule["id"])
            state = self._states.setdefault(rule["id"], _RuleState())
            violation = evaluate_frame(rule, detections) if in_schedule(rule, now) else None

            if violation is None:
                if state.last_seen is not None and now_ts - state.last_seen > self.grace:
                    state.first_seen = state.last_seen = None
                continue

            if state.first_seen is None:
                state.first_seen = now_ts
            state.last_seen = now_ts

            lasted = now_ts - state.first_seen >= rule.get("min_duration", 0)
            cooled = state.last_alert is None or now_ts - state.last_alert >= rule.get("cooldown", 0)
            if lasted and cooled:
                state.last_alert = now_ts
                fired.append(violation)

        for stale in set(self._states) - active_ids:
            del self._states[stale]
        return fired
