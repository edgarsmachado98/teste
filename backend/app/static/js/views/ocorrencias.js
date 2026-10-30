import {
  $, CLASS_LABELS, TYPE_LABELS, api, badge, esc, fmtDateTime, statusBadge, toast, withToken,
} from "../core.js";
import { setEventChangeHandler } from "../event-detail.js";

let el;
const filters = { status: "nova,confirmada", camera_id: "", type: "", classification: "", start: "", end: "" };

async function loadList() {
  const params = new URLSearchParams({ limit: 300 });
  for (const [k, v] of Object.entries(filters)) if (v) params.set(k, v);
  const events = await api(`/api/events?${params}`);
  $("#occ-count", el).textContent = `${events.length}${events.length === 300 ? "+" : ""} ocorrência(s)`;
  $("#occ-table", el).innerHTML = events.length ? `
    <tr><th></th><th>#</th><th>Desvio</th><th>Câmera / área</th><th>Quando</th><th>Situação</th><th>Classificação</th><th>Ações</th></tr>
    ${events.map((ev) => `
      <tr class="clickable" data-id="${ev.id}">
        <td>${ev.image_url ? `<img class="thumb" src="${esc(withToken(ev.image_url))}" alt="">` : ""}</td>
        <td>${ev.id}</td>
        <td><b>${esc(ev.message)}</b><div class="hint">${esc(TYPE_LABELS[ev.type] || ev.type)} · ${badge(ev.severity, `sev-${ev.severity}`)}</div></td>
        <td>${esc(ev.camera_name)}<div class="hint">${esc(ev.location || "")}</div></td>
        <td>${fmtDateTime(ev.created_at)}</td>
        <td>${statusBadge(ev.status)}</td>
        <td>${ev.classification ? esc(CLASS_LABELS[ev.classification]) : `<span class="hint">–</span>`}</td>
        <td>${ev.open_actions ? badge(`${ev.open_actions} aberta(s)`, "warn") : ""}</td>
      </tr>`).join("")}`
    : `<tr><td class="hint">Nenhuma ocorrência com esses filtros.</td></tr>`;
}

export async function show(element) {
  el = element;
  const cameras = await api("/api/cameras");
  el.innerHTML = `
    <div class="toolbar"><h2>Ocorrências</h2><span id="occ-count" class="hint"></span></div>
    <form id="occ-filters" class="filters">
      <label>Situação
        <select name="status">
          <option value="nova,confirmada">Em aberto</option>
          <option value="nova">Aguardando triagem</option>
          <option value="confirmada">Em tratamento</option>
          <option value="encerrada">Encerradas</option>
          <option value="descartada">Falsos alarmes</option>
          <option value="">Todas</option>
        </select>
      </label>
      <label>Câmera
        <select name="camera_id"><option value="">Todas</option>
          ${cameras.map((c) => `<option value="${c.id}">${esc(c.name)}</option>`).join("")}</select>
      </label>
      <label>Tipo
        <select name="type"><option value="">Todos</option>
          ${Object.entries(TYPE_LABELS).map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}</select>
      </label>
      <label>Classificação
        <select name="classification"><option value="">Todas</option>
          ${Object.entries(CLASS_LABELS).filter(([k]) => k !== "nao_classificada")
            .map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}</select>
      </label>
      <label>De <input type="date" name="start"></label>
      <label>Até <input type="date" name="end"></label>
    </form>
    <div class="table-wrap"><table id="occ-table"></table></div>`;

  const form = $("#occ-filters", el);
  for (const [k, v] of Object.entries(filters)) form[k].value = v;
  form.addEventListener("change", () => {
    for (const k of Object.keys(filters)) filters[k] = form[k].value;
    loadList().catch((err) => toast(esc(err.message), "danger"));
  });
  $("#occ-table", el).addEventListener("click", (e) => {
    const row = e.target.closest("tr[data-id]");
    if (row) location.hash = `#ocorrencia-${row.dataset.id}`;
  });
  setEventChangeHandler(() => loadList());
  await loadList();
}

export function leave() {
  setEventChangeHandler(() => {});
}

export function onRealtime(data) {
  if (data.kind === "event" || data.kind === "event_updated") loadList();
}
