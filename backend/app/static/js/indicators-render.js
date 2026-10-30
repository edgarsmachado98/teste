// Monta os indicadores a partir de /api/reports/summary. Usado na tela e no relatório.

import { barList, columnChart, percentLine } from "./charts.js";
import { CLASS_LABELS, esc, fmtDate, fmtPct } from "./core.js";

const shortDate = (iso) => { const [, m, d] = String(iso).split("-"); return `${d}/${m}`; };

export function delta(current, previous, { lowerIsBetter = true, pct = false } = {}) {
  if (current == null || previous == null || (!pct && previous === 0)) return `<small class="delta">sem base de comparação</small>`;
  const diff = pct ? (current - previous) * 100 : ((current - previous) / previous) * 100;
  if (Math.abs(diff) < 0.5) return `<small class="delta">estável vs. período anterior</small>`;
  const better = lowerIsBetter ? diff < 0 : diff > 0;
  const text = pct ? `${Math.abs(diff).toFixed(1).replace(".", ",")} p.p.` : `${Math.abs(Math.round(diff))}%`;
  return `<small class="delta ${better ? "good" : "bad"}">${diff < 0 ? "▼" : "▲"} ${text} vs. período anterior</small>`;
}

const fmtMinutes = (m) => (m == null ? "–" : m < 60 ? `${Math.round(m)} min` : `${(m / 60).toFixed(1).replace(".", ",")} h`);

export function kpis(s) {
  const t = s.totals;
  const c = s.compliance;
  const a = s.actions;
  return `
    <div class="stat"><b>${fmtPct(c.rate, 1)}</b><span>Conformidade de EPI</span>
      ${delta(c.rate, c.previous_rate, { lowerIsBetter: false, pct: true })}</div>
    <div class="stat"><b>${t.deviations}</b><span>Desvios (exclui falsos alarmes)</span>
      ${delta(t.deviations, t.previous_deviations)}</div>
    <div class="stat"><b>${fmtPct(t.false_alarm_rate)}</b><span>Taxa de falso alarme</span>
      <small class="delta">${t.discarded} de ${t.confirmed + t.discarded + t.closed} triados</small></div>
    <div class="stat"><b>${fmtMinutes(t.mean_triage_minutes)}</b><span>Tempo médio até a triagem</span>
      <small class="delta">${t.pending} aguardando triagem</small></div>
    <div class="stat"><b>${fmtPct(a.on_time_rate)}</b><span>Ações concluídas no prazo</span>
      <small class="delta">${a.completed_in_period} concluídas no período</small></div>
    <div class="stat ${a.overdue ? "stat-bad" : ""}"><b>${a.open}</b><span>Ações abertas</span>
      <small class="delta ${a.overdue ? "bad" : ""}">${a.overdue ? `▲ ${a.overdue} atrasada(s)` : "nenhuma atrasada"}</small></div>`;
}

function table(headers, rows) {
  return `<details class="data-table"><summary>Ver dados em tabela</summary>
    <table><tr>${headers.map((h) => `<th>${esc(h)}</th>`).join("")}</tr>
    ${rows.map((r) => `<tr>${r.map((v) => `<td>${esc(v)}</td>`).join("")}</tr>`).join("")}</table></details>`;
}

/** Preenche os elementos [data-chart=...] dentro de root. */
export function renderCharts(root, s) {
  const slot = (name) => root.querySelector(`[data-chart="${name}"]`);
  const pctRow = (label, sub, rate, observed) => ({
    label, sub, value: rate == null ? 0 : rate * 100, display: fmtPct(rate, 1),
    tip: `${label}: ${fmtPct(rate, 1)} de conformidade<br>${observed.toLocaleString("pt-BR")} pessoas observadas`,
  });

  const daily = s.by_day.map((d) => ({ label: shortDate(d.date), value: d.count,
    tip: `${fmtDate(d.date)}: <b>${d.count}</b> desvio(s)` }));
  if (slot("by_day")) {
    columnChart(slot("by_day"), daily);
    slot("by_day").insertAdjacentHTML("beforeend",
      table(["Dia", "Desvios"], s.by_day.map((d) => [fmtDate(d.date), d.count])));
  }

  if (slot("compliance_day")) {
    percentLine(slot("compliance_day"), s.compliance.by_day.map((d) => ({
      label: shortDate(d.date), value: d.rate,
      tip: `${fmtDate(d.date)}: ${d.rate == null ? "sem observações" : `<b>${fmtPct(d.rate, 1)}</b>`}`,
    })), { empty: "Sem regras de EPI ativas no período" });
    slot("compliance_day").insertAdjacentHTML("beforeend",
      table(["Dia", "Conformidade"], s.compliance.by_day.map((d) => [fmtDate(d.date), fmtPct(d.rate, 1)])));
  }

  if (slot("by_hour")) {
    columnChart(slot("by_hour"), s.by_hour.map((n, h) => ({ label: `${h}h`, value: n,
      tip: `${h}h–${h + 1}h: <b>${n}</b> desvio(s)` })), { every: 3, height: 160 });
  }

  slot("by_shift") && barList(slot("by_shift"), s.by_shift.map((x) => ({ label: x.shift, value: x.count })));
  slot("compliance_shift") && barList(slot("compliance_shift"),
    s.compliance.by_shift.map((x) => pctRow(x.shift, "", x.rate, x.observed)),
    { max: 100, empty: "Sem regras de EPI ativas no período." });
  slot("by_location") && barList(slot("by_location"), s.by_location.map((x) => ({ label: x.location, value: x.count })));
  slot("by_camera") && barList(slot("by_camera"), s.by_camera.map((x) => ({ label: x.camera, sub: x.location, value: x.count })));
  slot("compliance_camera") && barList(slot("compliance_camera"),
    s.compliance.by_camera.map((x) => pctRow(x.camera, x.location, x.rate, x.observed)),
    { max: 100, empty: "Sem regras de EPI ativas no período." });
  slot("by_type") && barList(slot("by_type"), s.by_type.map((x) => ({ label: x.label, value: x.count })));
  slot("by_class") && barList(slot("by_class"), Object.entries(s.by_classification)
    .sort((a, b) => b[1] - a[1]).map(([k, n]) => ({ label: CLASS_LABELS[k] || k, value: n })));
}
