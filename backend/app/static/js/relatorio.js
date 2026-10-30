import {
  ACTION_STATUS, TYPE_LABELS, $, api, badge, esc, fmtDate, fmtDateTime, isoDate, session, withToken,
} from "./core.js";
import { kpis, renderCharts } from "./indicators-render.js";

const params = new URLSearchParams(location.search);
const SEVERITY_ORDER = { critica: 0, alta: 1, media: 2, baixa: 3 };

function actionsTable(actions, done) {
  if (!actions.length) return `<p class="hint">Nenhuma.</p>`;
  return `<table>
    <tr><th>Ação</th><th>Responsável</th><th>Prazo</th><th>${done ? "Concluída em" : "Situação"}</th>
      ${done ? "<th>Evidência</th>" : ""}</tr>
    ${actions.map((a) => `<tr>
      <td>${esc(a.title)}${a.event_id ? `<div class="hint">Ocorrência #${a.event_id}</div>` : ""}</td>
      <td>${esc(a.responsible_name || "–")}</td><td>${fmtDate(a.due_date)}</td>
      <td>${done ? fmtDate(a.completed_at) : `${ACTION_STATUS[a.status]}${a.overdue ? " – <b>atrasada</b>" : ""}`}</td>
      ${done ? `<td>${esc(a.completion_notes)}</td>` : ""}</tr>`).join("")}</table>`;
}

(async () => {
  try {
    session.user = await api("/api/auth/me");
  } catch {
    document.body.innerHTML = `<p style="padding:24px">Sessão expirada. Entre no VigIA e gere o relatório novamente.</p>`;
    return;
  }
  const s = await api(`/api/reports/summary?${params}`);
  const { start, end } = s.period;
  const camParam = params.get("camera_id");
  const cameras = await api("/api/cameras");
  const camName = camParam ? cameras.find((c) => c.id === Number(camParam))?.name : null;

  $("#period").textContent = `Período: ${fmtDate(start)} a ${fmtDate(end)}${camName ? ` · Câmera: ${camName}` : ""}`;
  $("#meta").innerHTML = `
    <dt>Emitido em</dt><dd>${fmtDateTime(new Date().toISOString())}</dd>
    <dt>Emitido por</dt><dd>${esc(session.user.name)}</dd>
    <dt>Câmeras monitoradas</dt><dd>${cameras.filter((c) => c.enabled).length}</dd>
    <dt>Comparação</dt><dd>${fmtDate(s.period.previous_start)} a ${fmtDate(s.period.previous_end)}</dd>`;
  $("#kpis").innerHTML = kpis(s);
  renderCharts(document, s);

  const cam = camParam ? `&camera_id=${camParam}` : "";
  const [open, done, events] = await Promise.all([
    api("/api/actions?status=aberta"),
    api("/api/actions?status=concluida"),
    api(`/api/events?status=confirmada,encerrada&start=${start}&end=${end}&limit=500${cam}`),
  ]);
  const inPeriod = (iso) => iso && isoDate(new Date(iso)) >= start && isoDate(new Date(iso)) <= end;
  $("#open-actions").innerHTML = actionsTable(open, false);
  $("#done-actions").innerHTML = actionsTable(done.filter((a) => inPeriod(a.completed_at)), true);

  const top = events.sort((a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity]
    || b.created_at.localeCompare(a.created_at)).slice(0, 12);
  $("#events").innerHTML = top.map((ev) => `
    <figure>
      ${ev.image_url ? `<img src="${esc(withToken(ev.image_url))}" alt="">` : ""}
      <figcaption><b>#${ev.id} ${esc(ev.message)}</b><br>
        ${esc(ev.camera_name)} · ${fmtDateTime(ev.created_at)}<br>
        ${esc(TYPE_LABELS[ev.type] || ev.type)} · ${badge(ev.severity)} · ${ev.status === "encerrada" ? "encerrada" : "em tratamento"}
      </figcaption>
    </figure>`).join("") || `<p class="hint">Nenhuma ocorrência confirmada no período.</p>`;

  api(`/api/reports/export-log?start=${start}&end=${end}`, { method: "POST" }).catch(() => {});
})();

$("#print").addEventListener("click", () => window.print());
