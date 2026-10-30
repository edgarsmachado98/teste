import { cancelAction, getUsers, openActionForm, openCompleteForm } from "../actions-ui.js";
import { $, ACTION_STATUS, api, badge, can, esc, fmtDate, session, toast } from "../core.js";

let el;
let filter = "aberta";
let actions = [];

const FILTERS = {
  minhas: { label: "Minhas", query: "mine=true&status=aberta" },
  aberta: { label: "Abertas", query: "status=aberta" },
  atrasadas: { label: "Atrasadas", query: "overdue=true" },
  concluida: { label: "Concluídas", query: "status=concluida" },
  todas: { label: "Todas", query: "" },
};

async function load() {
  actions = await api(`/api/actions?${FILTERS[filter].query}`);
  $("#ac-tabs", el).innerHTML = Object.entries(FILTERS).map(([k, f]) =>
    `<button class="${k === filter ? "" : "secondary"} small" data-filter="${k}">${f.label}</button>`).join("");
  $("#ac-table", el).innerHTML = actions.length ? `
    <tr><th>Ação</th><th>Responsável</th><th>Prazo</th><th>Situação</th><th>Ocorrência</th><th></th></tr>
    ${actions.map((a) => {
      const mine = a.responsible_id === session.user.id;
      const buttons = a.status !== "aberta" ? "" : `
        ${can("tecnico") || mine ? `<button class="small" data-act="complete" data-id="${a.id}">Concluir</button>` : ""}
        ${can("tecnico") ? `<button class="small secondary" data-act="edit" data-id="${a.id}">Editar</button>
          <button class="small danger" data-act="cancel" data-id="${a.id}">Cancelar</button>` : ""}`;
      return `
        <tr class="${a.overdue ? "row-bad" : ""}">
          <td><b>${esc(a.title)}</b>${a.description ? `<div class="hint">${esc(a.description)}</div>` : ""}
            ${a.completion_notes ? `<div class="evidence">✔ ${esc(a.completion_notes)}</div>` : ""}</td>
          <td>${esc(a.responsible_name || "–")}</td>
          <td>${fmtDate(a.due_date)} ${a.overdue ? badge("▲ Atrasada", "bad") : ""}</td>
          <td>${badge(ACTION_STATUS[a.status], `ac-${a.status}`)}</td>
          <td>${a.event_id ? `<a href="#ocorrencia-${a.event_id}">#${a.event_id} ${esc(a.event_message || "")}</a>` : `<span class="hint">avulsa</span>`}</td>
          <td class="actions">${buttons}</td>
        </tr>`;
    }).join("")}`
    : `<tr><td class="hint">Nenhuma ação neste filtro.</td></tr>`;
}

export async function show(element) {
  el = element;
  el.innerHTML = `
    <div class="toolbar">
      <h2>Plano de ação</h2>
      ${can("tecnico") ? `<button id="ac-new">+ Nova ação avulsa</button>` : ""}
    </div>
    <p class="hint">Ações corretivas e preventivas. O responsável recebe um e-mail ao ser designado
      e registra a evidência ao concluir.</p>
    <div id="ac-tabs" class="tabs"></div>
    <div class="table-wrap"><table id="ac-table"></table></div>`;

  $("#ac-tabs", el).addEventListener("click", (e) => {
    const btn = e.target.closest("[data-filter]");
    if (btn) { filter = btn.dataset.filter; load(); }
  });
  $("#ac-new", el)?.addEventListener("click", async () => {
    if (await openActionForm()) load();
  });
  $("#ac-table", el).addEventListener("click", async (e) => {
    const btn = e.target.closest("[data-act]");
    if (!btn) return;
    const action = actions.find((a) => a.id === Number(btn.dataset.id));
    try {
      const fn = { complete: openCompleteForm, cancel: cancelAction,
        edit: (a) => openActionForm({ action: a }) }[btn.dataset.act];
      if (await fn(action)) load();
    } catch (err) { toast(esc(err.message), "danger"); }
  });
  await getUsers(true);
  await load();
}

export function onRealtime(data) {
  if (data.kind === "event_updated") load();
}
