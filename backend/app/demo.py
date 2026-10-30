"""Gera dados de demonstração (câmeras, ocorrências, ações e conformidade) para apresentações.

Uso (de preferência com um banco separado, para não misturar com dados reais):

    cd backend
    python -m app.demo --dias 60

O comando se recusa a rodar em um banco que já tenha ocorrências, a menos que se use --forcar.
"""

import argparse
import random
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select

from .database import SessionLocal
from .migrate import migrate
from .models import ActionItem, AuditLog, Camera, Event, Rule, RuleStat, User
from .security import hash_password
from .timeutil import local_tz

CAMERAS = [
    ("Prensa 1", "Galpão A – Prensas", [("Capacete e óculos – prensas", "ppe_missing", {"required": ["helmet", "glasses"]}),
                                         ("Zona da prensa", "restricted_zone", {})]),
    ("Solda robotizada", "Galpão B – Solda", [("Célula de solda", "restricted_zone", {}),
                                              ("EPI soldagem", "ppe_missing", {"required": ["helmet", "gloves"]})]),
    ("Doca 2", "Expedição", [("Colete na doca", "ppe_missing", {"required": ["vest"]}),
                             ("Excesso de pessoas na doca", "max_people", {"max_people": 3})]),
    ("Almoxarifado", "Almoxarifado", [("Fogo e fumaça", "fire_smoke", {})]),
]
HOTSPOTS = {"Prensa 1": (0.55, 0.75), "Solda robotizada": (0.4, 0.8), "Doca 2": (0.65, 0.85), "Almoxarifado": (0.3, 0.5)}
MESSAGES = {
    "ppe_missing": "1 pessoa(s) sem {item}",
    "restricted_zone": "1 pessoa(s) em zona restrita",
    "fire_smoke": "Fumaça detectado",
    "max_people": "5 pessoas na zona (máx. 3)",
}
ITEM_PT = {"helmet": "capacete", "glasses": "óculos", "gloves": "luvas", "vest": "colete"}
ACTIONS = [
    "Reforçar DDS sobre uso de EPI no turno",
    "Instalar sinalização de área restrita",
    "Adequar barreira física na célula",
    "Reposição de EPI no posto de trabalho",
    "Revisar procedimento operacional da doca",
    "Treinamento de reciclagem NR-12",
]


def run(days: int, force: bool) -> None:
    migrate()
    rnd = random.Random(42)
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        if db.scalar(select(func.count()).select_from(Event)) and not force:
            raise SystemExit("O banco já tem ocorrências. Use um banco separado ou --forcar.")

        users = {}
        for name, email, role in [("Carla Técnica", "tecnico@demo.com", "tecnico"),
                                  ("Marcos Gestor", "gestor@demo.com", "gestor"),
                                  ("Paulo Operador", "operador@demo.com", "operador"),
                                  ("Rita Manutenção", "manutencao@demo.com", "operador")]:
            user = db.scalar(select(User).where(User.email == email))
            if user is None:
                user = User(name=name, email=email, role=role, password_hash=hash_password("demo12345"))
                db.add(user)
            users[role if role != "operador" or "Paulo" in name else "manutencao"] = user
        if not db.scalar(select(User).where(User.role == "admin")):
            db.add(User(name="Admin Demo", email="admin@demo.com", role="admin", password_hash=hash_password("demo12345")))
        db.flush()
        tecnico, operador, manutencao = users["tecnico"], users["operador"], users["manutencao"]

        rules = []
        for cam_name, location, cam_rules in CAMERAS:
            cam = Camera(name=cam_name, location=location, source=f"demo://{cam_name}", enabled=False)
            db.add(cam)
            db.flush()
            for rule_name, rtype, params in cam_rules:
                rule = Rule(camera_id=cam.id, name=rule_name, type=rtype, params=params,
                            severity="critica" if rtype == "fire_smoke" else "alta", enabled=True)
                db.add(rule)
                rules.append((cam, rule))
        db.flush()

        tz = local_tz()
        for day in range(days, -1, -1):
            # A conformidade melhora ao longo do período (efeito do tratamento dos desvios)
            progress = 1 - day / max(days, 1)
            for cam, rule in rules:
                weight = {"Prensa 1": 1.4, "Doca 2": 1.1}.get(cam.name, 0.7)
                if rule.type == "fire_smoke":
                    weight = 0.05
                n_events = sum(rnd.random() < weight * (0.9 - 0.5 * progress) for _ in range(3))
                for _ in range(n_events):
                    hour = rnd.choices(range(24), weights=[3 if h >= 22 or h < 6 else 2 if 14 <= h < 22 else 1
                                                           for h in range(24)])[0]
                    local = datetime.combine(date.today() - timedelta(days=day), datetime.min.time(), tz).replace(
                        hour=hour, minute=rnd.randint(0, 59))
                    created = local.astimezone(timezone.utc)
                    if created > now:
                        continue
                    item = ITEM_PT[rnd.choice(rule.params.get("required", ["helmet"]))] if rule.type == "ppe_missing" else ""
                    hx, hy = HOTSPOTS[cam.name]
                    fx, fy = min(max(rnd.gauss(hx, 0.08), 0.05), 0.95), min(max(rnd.gauss(hy, 0.05), 0.2), 0.98)
                    event = Event(camera_id=cam.id, rule_id=rule.id, type=rule.type, severity=rule.severity,
                                  message=MESSAGES[rule.type].format(item=item), created_at=created,
                                  boxes=[[fx - 0.05, fy - 0.35, fx + 0.05, fy]])
                    age_days = (now - created).days
                    if age_days >= 2 or rnd.random() < 0.6:
                        reviewer = rnd.choice([tecnico, operador])
                        event.reviewed_by_id = reviewer.id
                        event.reviewed_at = created + timedelta(minutes=rnd.randint(2, 90))
                        if rnd.random() < 0.12:
                            event.status = "descartada"
                        else:
                            event.classification = rnd.choices(
                                ["ato_inseguro", "condicao_insegura", "quase_acidente"], [7, 2, 1])[0]
                            event.status = "encerrada" if age_days > 7 else "confirmada"
                            if event.status == "encerrada":
                                event.closed_at = event.reviewed_at + timedelta(days=rnd.randint(1, 5))
                    db.add(event)
                    db.flush()
                    if event.status != "nova":
                        db.add(AuditLog(user_id=event.reviewed_by_id, user_name=tecnico.name, action="ocorrencia_atualizada",
                                        entity="ocorrencia", entity_id=event.id, created_at=event.reviewed_at,
                                        details=f"status: nova → {event.status}"))

                if rule.type == "ppe_missing":
                    for hour in range(24):
                        ts = datetime.combine(date.today() - timedelta(days=day), datetime.min.time(), tz).replace(hour=hour)
                        ts = ts.astimezone(timezone.utc)
                        if ts > now:
                            break
                        night = hour >= 22 or hour < 6
                        observed = rnd.randint(150, 400) if 6 <= hour < 22 else rnd.randint(40, 120)
                        rate = 0.80 + 0.13 * progress - (0.05 if night else 0) + rnd.uniform(-0.02, 0.02)
                        db.add(RuleStat(rule_id=rule.id, camera_id=cam.id, hour=ts, observed=observed,
                                        violations=int(observed * (1 - min(rate, 0.99)))))

        # Plano de ação ligado a algumas ocorrências confirmadas
        confirmed = db.scalars(select(Event).where(Event.status.in_(["confirmada", "encerrada"]))
                               .order_by(Event.created_at)).all()
        for event in rnd.sample(confirmed, min(len(confirmed), 14)):
            done = event.status == "encerrada"
            created = event.reviewed_at or event.created_at
            due = (created + timedelta(days=rnd.randint(3, 15))).date()
            action = ActionItem(event_id=event.id, title=rnd.choice(ACTIONS), created_by_id=tecnico.id,
                                responsible_id=rnd.choice([manutencao.id, tecnico.id]), due_date=due,
                                created_at=created, status="concluida" if done else "aberta")
            if done:
                action.completed_at = event.closed_at or created + timedelta(days=2)
                action.completion_notes = "Realizado e registrado em ata."
            db.add(action)
        db.commit()
    print("Dados de demonstração criados.")
    print("Usuários (senha demo12345): tecnico@demo.com, gestor@demo.com, operador@demo.com, admin@demo.com")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dias", type=int, default=60)
    parser.add_argument("--forcar", action="store_true", help="roda mesmo se o banco já tiver ocorrências")
    args = parser.parse_args()
    run(args.dias, args.forcar)
