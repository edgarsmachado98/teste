"""Relatório de segurança em PDF gerado no servidor (para envio automático por e-mail).

Usa os mesmos dados da tela de Indicadores (build_summary). Gráficos desenhados com
primitivas do PDF, em uma única cor de série."""

from datetime import date, datetime

from fpdf import FPDF
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .common import CLASS_LABELS_PT, is_overdue
from .config import settings
from .models import ActionItem, Camera
from .routers.reports import build_summary
from .timeutil import local_tz, to_local

SERIES = (42, 120, 214)       # azul da série (mesmo do relatório no navegador)
TRACK = (238, 241, 244)
TEXT = (22, 25, 29)
MUTED = (91, 99, 110)
LINE = (221, 225, 230)
ACCENT = (217, 119, 6)
GOOD = (21, 128, 61)
BAD = (185, 28, 28)

_REPLACE = {"–": "-", "—": "-", "→": "->", "▲": "+", "▼": "-", "•": "-", "“": '"', "”": '"', "‘": "'", "’": "'",
            "…": "...", "✔": "", "×": "x"}


def t(text) -> str:
    """As fontes padrão do PDF usam Latin-1: troca símbolos que não existem nela."""
    s = str(text if text is not None else "")
    for a, b in _REPLACE.items():
        s = s.replace(a, b)
    return s.encode("latin-1", "replace").decode("latin-1")


def pct(v, digits=1) -> str:
    return "-" if v is None else f"{v * 100:.{digits}f}%".replace(".", ",")


def br(d) -> str:
    return d.strftime("%d/%m/%Y") if d else "-"


class Report(FPDF):
    def header(self):
        if self.page_no() == 1:
            return
        self.set_font("helvetica", "", 8)
        self.set_text_color(*MUTED)
        self.cell(0, 6, t(f"VigIA - Relatório de Segurança e Comportamento · {self.period_label}"), align="L")
        self.ln(8)

    def footer(self):
        self.set_y(-12)
        self.set_font("helvetica", "", 8)
        self.set_text_color(*MUTED)
        self.cell(0, 6, t(f"Página {self.page_no()}/{{nb}}"), align="R")

    # ---------- blocos ----------
    def ensure(self, height):
        """Começa nova página se o bloco não couber na atual."""
        if self.get_y() + height > self.page_break_trigger:
            self.add_page()

    def _no_break(self, draw):
        self.set_auto_page_break(False)
        try:
            draw()
        finally:
            self.set_auto_page_break(True, margin=16)
    def h2(self, text):
        if self.get_y() > 250:
            self.add_page()
        self.ln(3)
        self.set_font("helvetica", "B", 12)
        self.set_text_color(*TEXT)
        self.cell(0, 7, t(text), new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*LINE)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(3)

    def h3(self, text):
        self.set_font("helvetica", "B", 9)
        self.set_text_color(*MUTED)
        self.cell(0, 6, t(text), new_x="LMARGIN", new_y="NEXT")

    def kpi(self, x, y, w, h, value, label, note="", note_color=MUTED):
        self.set_draw_color(*LINE)
        self.rect(x, y, w, h)
        self.set_xy(x + 3, y + 2)
        self.set_font("helvetica", "B", 15)
        self.set_text_color(*TEXT)
        self.cell(w - 6, 8, t(value))
        self.set_xy(x + 3, y + 10)
        self.set_font("helvetica", "", 8)
        self.set_text_color(*MUTED)
        self.cell(w - 6, 4, t(label))
        if note:
            self.set_xy(x + 3, y + 14.5)
            self.set_text_color(*note_color)
            self.cell(w - 6, 4, t(note))

    def bar_rows(self, rows, x, width, max_value=None, value_fmt=str, empty="Sem dados no período."):
        """Linhas 'rótulo | barra | valor'."""
        if not rows:
            self.set_x(x)
            self.set_font("helvetica", "I", 8)
            self.set_text_color(*MUTED)
            self.cell(width, 5, t(empty), new_x="LMARGIN", new_y="NEXT")
            return
        max_value = max_value or max((r[1] for r in rows), default=1) or 1
        label_w, value_w = width * 0.38, 16
        bar_w = width - label_w - value_w - 4
        for label, value in rows:
            y = self.get_y()
            self.set_xy(x, y)
            self.set_font("helvetica", "", 8)
            self.set_text_color(*TEXT)
            self.cell(label_w, 5, t(label)[:42])
            self.set_fill_color(*TRACK)
            self.rect(x + label_w + 2, y + 1.2, bar_w, 2.8, style="F")
            if value:
                self.set_fill_color(*SERIES)
                self.rect(x + label_w + 2, y + 1.2, max(bar_w * value / max_value, 0.6), 2.8, style="F")
            self.set_xy(x + width - value_w, y)
            self.cell(value_w, 5, t(value_fmt(value)), align="R")
            self.set_y(y + 5.5)

    def columns(self, values, labels, x, y, w, h, every=5):
        self._no_break(lambda: self._columns(values, labels, x, y, w, h, every))

    def percent_line(self, values, labels, x, y, w, h, every=5):
        self._no_break(lambda: self._percent_line(values, labels, x, y, w, h, every))

    def _columns(self, values, labels, x, y, w, h, every=5):
        top = max(values, default=0) or 1
        n = max(len(values), 1)
        step = w / n
        bw = max(min(step - 0.8, 6), 0.4)
        self.set_draw_color(*LINE)
        for i in range(5):
            gy = y + h - h * i / 4
            self.line(x, gy, x + w, gy)
        self.set_font("helvetica", "", 6.5)
        self.set_text_color(*MUTED)
        for i in (0, 2, 4):
            self.set_xy(x - 9, y + h - h * i / 4 - 2)
            self.cell(8, 4, t(round(top * i / 4)), align="R")
        self.set_fill_color(*SERIES)
        for i, v in enumerate(values):
            bh = h * v / top
            if bh > 0:
                self.rect(x + i * step + (step - bw) / 2, y + h - bh, bw, bh, style="F")
            if i % every == 0:
                self.set_xy(x + i * step - 4, y + h + 1)
                self.cell(step + 8, 4, t(labels[i]), align="C")

    def _percent_line(self, values, labels, x, y, w, h, every=5):
        present = [v for v in values if v is not None]
        if not present:
            self.set_xy(x, y + h / 2 - 2)
            self.set_font("helvetica", "I", 8)
            self.set_text_color(*MUTED)
            self.cell(w, 4, t("Sem regras de EPI ativas no período"), align="C")
            return
        lo = max(0.0, int((min(present) - 0.05) * 10) / 10)
        n = len(values)
        px = (lambda i: x + (w / 2 if n == 1 else i * w / (n - 1)))
        py = (lambda v: y + h - (v - lo) / (1 - lo) * h)
        self.set_draw_color(*LINE)
        self.set_font("helvetica", "", 6.5)
        self.set_text_color(*MUTED)
        for i in range(5):
            v = lo + (1 - lo) * i / 4
            self.line(x, py(v), x + w, py(v))
            if i % 2 == 0:
                self.set_xy(x - 10, py(v) - 2)
                self.cell(9, 4, t(f"{round(v * 100)}%"), align="R")
        self.set_draw_color(*SERIES)
        self.set_line_width(0.5)
        prev = None
        for i, v in enumerate(values):
            if v is None:
                prev = None
                continue
            if prev:
                self.line(prev[0], prev[1], px(i), py(v))
            prev = (px(i), py(v))
        self.set_line_width(0.2)
        for i, label in enumerate(labels):
            if i % every == 0:
                self.set_xy(px(i) - 6, y + h + 1)
                self.cell(12, 4, t(label), align="C")

    def table(self, headers, rows, widths):
        self.set_font("helvetica", "B", 7.5)
        self.set_text_color(*MUTED)
        for head, w in zip(headers, widths):
            self.cell(w, 5, t(head))
        self.ln(5)
        self.set_draw_color(*LINE)
        self.set_font("helvetica", "", 7.5)
        self.set_text_color(*TEXT)
        for row in rows:
            if self.get_y() > 270:
                self.add_page()
            y = self.get_y()
            heights = []
            x = self.l_margin
            for value, w in zip(row, widths):
                self.set_xy(x, y)
                self.multi_cell(w - 1, 4, t(value))
                heights.append(self.get_y() - y)
                x += w
            self.set_y(y + max(heights) + 1)
            self.line(self.l_margin, self.get_y(), self.l_margin + sum(widths), self.get_y())
            self.ln(1)


def build_report_pdf(db: Session, start: date, end: date, camera_id: int | None = None) -> bytes:
    s = build_summary(db, start, end, camera_id)
    tot, comp, act = s["totals"], s["compliance"], s["actions"]

    pdf = Report(format="A4")
    pdf.period_label = f"{br(start)} a {br(end)}"
    pdf.set_auto_page_break(True, margin=16)
    pdf.set_margins(16, 14, 16)
    pdf.alias_nb_pages()
    pdf.add_page()
    full_w = pdf.w - pdf.l_margin - pdf.r_margin

    # Capa
    pdf.set_font("helvetica", "B", 16)
    pdf.set_text_color(*TEXT)
    pdf.cell(pdf.get_string_width("Vig"), 8, "Vig")
    pdf.set_text_color(*ACCENT)
    pdf.cell(0, 8, "IA", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(*TEXT)
    pdf.set_font("helvetica", "B", 15)
    pdf.cell(0, 8, t("Relatório de Segurança e Comportamento"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", "", 9)
    pdf.set_text_color(*MUTED)
    camera = db.get(Camera, camera_id) if camera_id else None
    lines = [settings.company_name, f"Período: {br(start)} a {br(end)}" + (f" · Câmera: {camera.name}" if camera else ""),
             f"Comparação: {br(s['period']['previous_start'])} a {br(s['period']['previous_end'])}",
             f"Emitido automaticamente em {datetime.now(local_tz()):%d/%m/%Y %H:%M}"]
    for line in filter(None, lines):
        pdf.cell(0, 5, t(line), new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(*ACCENT)
    pdf.set_line_width(0.8)
    pdf.line(pdf.l_margin, pdf.get_y() + 2, pdf.w - pdf.r_margin, pdf.get_y() + 2)
    pdf.set_line_width(0.2)
    pdf.ln(5)

    # 1. Resumo
    pdf.h2("1. Resumo do período")

    def delta(cur, prev, lower_better=True, is_pct=False):
        if cur is None or prev is None or (not is_pct and prev == 0):
            return "sem base de comparação", MUTED
        diff = (cur - prev) * 100 if is_pct else (cur - prev) / prev * 100
        if abs(diff) < 0.5:
            return "estável vs. período anterior", MUTED
        better = diff < 0 if lower_better else diff > 0
        txt = f"{abs(diff):.1f} p.p.".replace(".", ",") if is_pct else f"{abs(round(diff))}%"
        return f"{'+' if diff > 0 else '-'}{txt} vs. período anterior", GOOD if better else BAD

    triados = tot["confirmed"] + tot["discarded"] + tot["closed"]
    minutes = tot["mean_triage_minutes"]
    tiles = [
        (pct(comp["rate"]), "Conformidade de EPI", *delta(comp["rate"], comp["previous_rate"], False, True)),
        (str(tot["deviations"]), "Desvios (exclui falsos alarmes)", *delta(tot["deviations"], tot["previous_deviations"])),
        (pct(tot["false_alarm_rate"], 0), "Taxa de falso alarme", f"{tot['discarded']} de {triados} triados", MUTED),
        ("-" if minutes is None else (f"{round(minutes)} min" if minutes < 60 else f"{minutes / 60:.1f} h".replace(".", ",")),
         "Tempo médio até a triagem", f"{tot['pending']} aguardando triagem", MUTED),
        (pct(act["on_time_rate"], 0), "Ações concluídas no prazo", f"{act['completed_in_period']} concluídas no período", MUTED),
        (str(act["open"]), "Ações abertas", f"{act['overdue']} atrasada(s)" if act["overdue"] else "nenhuma atrasada",
         BAD if act["overdue"] else MUTED),
    ]
    tile_w, tile_h, gap = (full_w - 2 * 3) / 3, 20, 3
    y0 = pdf.get_y()
    for i, (value, label, note, color) in enumerate(tiles):
        pdf.kpi(pdf.l_margin + (i % 3) * (tile_w + gap), y0 + (i // 3) * (tile_h + gap), tile_w, tile_h,
                value, label, note, color)
    pdf.set_y(y0 + 2 * (tile_h + gap) + 2)

    # 2. Tendência
    pdf.h2("2. Tendência")
    labels = [f"{d['date']:%d/%m}" for d in s["by_day"]]
    every = max(1, len(labels) // 8)
    half = (full_w - 14) / 2
    pdf.ensure(56)
    pdf.h3("Desvios por dia")
    y = pdf.get_y() + 2
    pdf.columns([d["count"] for d in s["by_day"]], labels, pdf.l_margin + 10, y, half - 10, 38, every)
    pdf.set_font("helvetica", "B", 9)
    pdf.set_text_color(*MUTED)
    pdf.set_xy(pdf.l_margin + half + 14, y - 8)
    pdf.cell(half, 6, t("Conformidade de EPI por dia"))
    pdf.percent_line([d["rate"] for d in comp["by_day"]], labels, pdf.l_margin + half + 26, y, half - 12, 38, every)
    pdf.set_y(y + 46)

    # 3. Onde e quando
    pdf.h2("3. Onde e quando os desvios acontecem")
    col_w = (full_w - 10) / 2
    left, right = pdf.l_margin, pdf.l_margin + col_w + 10

    def two_columns(title_l, rows_l, title_r, rows_r, fmt_r=str, max_r=None, empty_r="Sem dados no período."):
        pdf.ensure(10 + 5.5 * max(len(rows_l), len(rows_r), 1))
        y = pdf.get_y()
        pdf.set_xy(left, y)
        pdf.h3(title_l)
        pdf.bar_rows(rows_l, left, col_w)
        end_l = pdf.get_y()
        pdf.set_xy(right, y)
        pdf.set_font("helvetica", "B", 9)
        pdf.set_text_color(*MUTED)
        pdf.cell(col_w, 6, t(title_r))
        pdf.set_xy(right, y + 6)
        pdf.bar_rows(rows_r, right, col_w, max_r, fmt_r, empty_r)
        pdf.set_y(max(end_l, pdf.get_y()) + 3)

    pct_fmt = lambda v: pct(v / 100)  # noqa: E731
    two_columns("Por área", [(x["location"], x["count"]) for x in s["by_location"]],
                "Conformidade de EPI por câmera",
                [(x["camera"], (x["rate"] or 0) * 100) for x in comp["by_camera"]], pct_fmt, 100,
                "Sem regras de EPI ativas no período.")
    two_columns("Por turno", [(x["shift"], x["count"]) for x in s["by_shift"]],
                "Conformidade de EPI por turno", [(x["shift"], (x["rate"] or 0) * 100) for x in comp["by_shift"]],
                pct_fmt, 100, "Sem regras de EPI ativas no período.")
    pdf.ensure(42)
    pdf.h3("Por hora do dia")
    y = pdf.get_y() + 2
    pdf.columns(s["by_hour"], [f"{h}h" for h in range(24)], pdf.l_margin + 10, y, full_w - 10, 26, 3)
    pdf.set_y(y + 34)

    # 4. Natureza
    pdf.h2("4. Natureza dos desvios")
    two_columns("Por tipo", [(x["label"], x["count"]) for x in s["by_type"]],
                "Por classificação", sorted(((CLASS_LABELS_PT.get(k, k), n) for k, n in s["by_classification"].items()),
                                            key=lambda r: -r[1]))

    # 5. Plano de ação
    pdf.h2("5. Plano de ação")
    actions = db.scalars(select(ActionItem).options(selectinload(ActionItem.responsible), selectinload(ActionItem.event))).all()
    if camera_id is not None:
        actions = [a for a in actions if a.event and a.event.camera_id == camera_id]
    open_actions = sorted((a for a in actions if a.status == "aberta"), key=lambda a: (a.due_date or date.max))
    done = [a for a in actions if a.completed_at and start <= to_local(a.completed_at).date() <= end]
    widths = [full_w * 0.42, full_w * 0.22, full_w * 0.14, full_w * 0.22]
    pdf.h3(f"Ações em aberto ({len(open_actions)})")
    if open_actions:
        pdf.table(["Ação", "Responsável", "Prazo", "Situação"],
                  [[a.title + (f" (ocorrência #{a.event_id})" if a.event_id else ""),
                    a.responsible.name if a.responsible else "-", br(a.due_date),
                    "ATRASADA" if is_overdue(a) else "aberta"] for a in open_actions[:40]], widths)
    pdf.ln(2)
    pdf.h3(f"Ações concluídas no período ({len(done)})")
    if done:
        pdf.table(["Ação", "Responsável", "Concluída em", "Evidência"],
                  [[a.title, a.responsible.name if a.responsible else "-", br(to_local(a.completed_at).date()),
                    a.completion_notes] for a in done[:40]], widths)

    pdf.ln(4)
    pdf.set_font("helvetica", "", 7.5)
    pdf.set_text_color(*MUTED)
    pdf.multi_cell(0, 4, t(
        "Indicadores gerados automaticamente a partir das câmeras monitoradas pelo VigIA. A conformidade de EPI "
        "considera as pessoas observadas nas zonas com regra de EPI ativa. O sistema é complementar e não substitui "
        "inspeções, dispositivos de segurança de máquinas (NR-12) nem a gestão de riscos do PGR (NR-1). "
        "Para fotos, clipes e o detalhe de cada ocorrência, acesse o painel."))
    return bytes(pdf.output())
