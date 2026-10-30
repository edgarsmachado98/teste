import { $, api, esc, fmtDateTime, toast } from "../core.js";

let el;

const ENTITY_LABELS = {
  "": "Tudo", ocorrencia: "Ocorrências", acao: "Ações", camera: "Câmeras", regra: "Regras",
  usuario: "Usuários e acessos", relatorio: "Relatórios",
};

async function load() {
  const f = $("#audit-filters", el);
  const params = new URLSearchParams({ limit: 500 });
  if (f.entity.value) params.set("entity", f.entity.value);
  if (f.user_name.value) params.set("user_name", f.user_name.value);
  const rows = await api(`/api/audit?${params}`);
  $("#audit-table", el).innerHTML = `
    <tr><th>Quando</th><th>Usuário</th><th>Ação</th><th>Detalhes</th><th>IP</th></tr>
    ${rows.map((r) => `
      <tr>
        <td>${fmtDateTime(r.created_at)}</td><td>${esc(r.user_name)}</td>
        <td>${esc(r.action.replaceAll("_", " "))}${r.entity === "ocorrencia" && r.entity_id
          ? ` <a href="#ocorrencia-${r.entity_id}">#${r.entity_id}</a>` : ""}</td>
        <td>${esc(r.details)}</td><td class="mono">${esc(r.ip)}</td>
      </tr>`).join("") || `<tr><td class="hint">Nenhum registro.</td></tr>`}`;
}

export async function show(element) {
  el = element;
  el.innerHTML = `
    <div class="toolbar"><h2>Auditoria</h2></div>
    <p class="hint">Registro de acessos e alterações (LGPD): quem fez o quê, quando e de onde.</p>
    <form id="audit-filters" class="filters">
      <label>Assunto <select name="entity">${Object.entries(ENTITY_LABELS)
        .map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}</select></label>
      <label>Usuário <input name="user_name" placeholder="nome"></label>
    </form>
    <div class="table-wrap"><table id="audit-table"></table></div>`;
  $("#audit-filters", el).addEventListener("change", () => load().catch((err) => toast(esc(err.message), "danger")));
  await load();
}
