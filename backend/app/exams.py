"""Exames ocupacionais (PCMSO – NR-7): catálogo, periodicidade sugerida e situação por colaborador.

Dado de saúde é dado pessoal sensível (LGPD, art. 11). O VigIA guarda só o necessário para o
controle do SESMT: tipo de exame, datas, aptidão e restrições funcionais. Diagnósticos e
resultados clínicos ficam com o médico do trabalho / clínica, não aqui.

A periodicidade abaixo é um ponto de partida comum; quem define é o PCMSO de cada empresa,
elaborado pelo médico responsável. Por isso a validade é sempre editável no registro.
"""

from calendar import monthrange
from datetime import date

# código: (nome, meses de validade sugeridos, quando costuma ser exigido)
CATALOG: dict[str, dict] = {
    "aso": {
        "label": "ASO – Atestado de Saúde Ocupacional",
        "months": 12,
        "basis": "NR-7 · obrigatório para todos. Periódico: anual (ou menos) para expostos a riscos; "
                 "a cada 2 anos para os demais, conforme o PCMSO.",
    },
    "audiometria": {
        "label": "Audiometria tonal",
        "months": 12,
        "basis": "NR-7 Anexo II · ruído acima do nível de ação: admissional, 6 meses após a admissão e depois anual.",
    },
    "espirometria": {
        "label": "Espirometria",
        "months": 24,
        "basis": "NR-7 · exposição a poeiras, fumos e névoas (ex.: soldagem, sílica, madeira), conforme o PCMSO.",
    },
    "raio_x_torax": {
        "label": "Raio-X de tórax (padrão OIT)",
        "months": 12,
        "basis": "NR-7 Anexo · poeiras minerais (sílica, asbesto, carvão); intervalo conforme o tempo de exposição.",
    },
    "acuidade_visual": {
        "label": "Acuidade visual",
        "months": 12,
        "basis": "Operadores de empilhadeira, ponte rolante e máquinas (NR-11/NR-12), motoristas e trabalho em altura.",
    },
    "ecg": {
        "label": "Eletrocardiograma (ECG)",
        "months": 12,
        "basis": "Trabalho em altura (NR-35), espaço confinado (NR-33) e eletricidade (NR-10), a critério do PCMSO.",
    },
    "eeg": {
        "label": "Eletroencefalograma (EEG)",
        "months": 24,
        "basis": "Trabalho em altura, eletricidade e operação de máquinas, a critério do médico coordenador.",
    },
    "glicemia": {
        "label": "Glicemia",
        "months": 12,
        "basis": "Trabalho em altura, espaço confinado e operação de equipamentos (risco de mal súbito).",
    },
    "hemograma": {
        "label": "Hemograma completo",
        "months": 6,
        "basis": "Exposição a benzeno e radiações ionizantes: semestral (NR-7 / NR-15 Anexo 13-A).",
    },
    "indicador_biologico": {
        "label": "Indicador biológico (agentes químicos)",
        "months": 6,
        "basis": "NR-7 Anexo I · chumbo, solventes (tolueno, xileno), metais etc.: em geral semestral.",
    },
    "toxicologico": {
        "label": "Exame toxicológico",
        "months": 30,
        "basis": "Motoristas profissionais com CNH C, D ou E: admissão e desligamento (CLT art. 168) "
                 "e renovação a cada 2 anos e 6 meses.",
    },
    "psicossocial": {
        "label": "Avaliação psicossocial",
        "months": 12,
        "basis": "Aptidão para trabalho em altura (NR-35) e espaço confinado (NR-33), conforme o PCMSO.",
    },
    "outro": {"label": "Outro exame", "months": 12, "basis": "Exame previsto no PCMSO da empresa."},
}

ASO_TYPES = {
    "admissional": "Admissional",
    "periodico": "Periódico",
    "retorno": "Retorno ao trabalho",
    "mudanca_risco": "Mudança de risco ocupacional",
    "demissional": "Demissional",
}

RESULTS = {"apto": "Apto", "apto_restricao": "Apto com restrição", "inapto": "Inapto"}

# Aptidões que a NR pede explícitas no ASO
APTITUDES = {
    "altura": "Trabalho em altura (NR-35)",
    "espaco_confinado": "Espaço confinado (NR-33)",
    "eletricidade": "Serviços com eletricidade (NR-10)",
    "maquinas": "Operação de máquinas e equipamentos (NR-12)",
    "empilhadeira": "Empilhadeira / ponte rolante (NR-11)",
    "direcao": "Direção de veículos",
}

SOON_DAYS = 30


def add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    return date(year, month, min(d.day, monthrange(year, month)[1]))


def default_valid_until(exam: str, performed_on: date, aso_type: str | None = None) -> date | None:
    if exam == "aso" and aso_type == "demissional":
        return None  # encerra o vínculo; não há próximo
    return add_months(performed_on, CATALOG.get(exam, CATALOG["outro"])["months"])


def label(exam: str) -> str:
    return CATALOG.get(exam, CATALOG["outro"])["label"]


def status_of(valid_until: date | None, today: date | None = None) -> tuple[str, int | None]:
    """("em_dia" | "vence" | "vencido" | "sem_validade", dias até vencer)."""
    if valid_until is None:
        return "sem_validade", None
    days = (valid_until - (today or date.today())).days
    return ("vencido" if days < 0 else "vence" if days <= SOON_DAYS else "em_dia"), days


def compliance(records, required: list[str], today: date | None = None) -> list[dict]:
    """Situação de cada exame relevante para a pessoa: os exigidos pelo setor (mesmo nunca feitos)
    e os já registrados. Vale o registro mais recente de cada tipo."""
    today = today or date.today()
    latest: dict[str, object] = {}
    for r in sorted(records, key=lambda r: r.performed_on):
        latest[r.exam] = r
    codes = list(dict.fromkeys(["aso", *required, *latest.keys()]))
    out = []
    for code in codes:
        r = latest.get(code)
        if r is None:
            out.append({"exam": code, "label": label(code), "required": code in required or code == "aso",
                        "status": "pendente", "days": None, "performed_on": None, "valid_until": None})
            continue
        st, days = status_of(r.valid_until, today)
        if code == "aso" and r.aso_type == "demissional":
            st = "encerrado"
        if code == "aso" and r.result == "inapto" and st not in ("vencido", "encerrado"):
            st = "inapto"
        out.append({"exam": code, "label": label(code), "required": code in required or code == "aso",
                    "status": st, "days": days, "performed_on": r.performed_on, "valid_until": r.valid_until})
    return out


def alert(records, required: list[str], today: date | None = None) -> str | None:
    """Pior situação, em uma frase curta para a lista de pessoas."""
    items = compliance(records, required, today)
    short = lambda i: i["label"].split(" – ")[0].split(" (")[0]  # noqa: E731
    for st in ("inapto", "vencido", "pendente", "vence"):
        hit = [i for i in items if i["status"] == st and (i["required"] or st != "pendente")]
        if not hit:
            continue
        first = min(hit, key=lambda i: i["days"] if i["days"] is not None else -10_000)
        if st == "inapto":
            return "ASO: inapto"
        if st == "vencido":
            return f"{short(first)} vencido"
        if st == "pendente":
            return f"{short(first)} pendente"
        return f"{short(first)} vence em {first['days']} dia(s)"
    return None
