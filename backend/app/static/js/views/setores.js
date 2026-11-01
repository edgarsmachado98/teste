// Cadastros › Setores e padrões: EPI obrigatório e regras de comportamento por setor.

import { $, $$, PPE_LABELS, api, badge, can, esc, fmtDateTime, toast } from "../core.js";

const PPE = ["helmet", "vest", "glasses", "gloves", "mask"];
const SEVERITIES = [["baixa", "Baixa"], ["media", "Média"], ["alta", "Alta"], ["critica", "Crítica"]];
const BEHAVIORS = [
  ["restricted_zone", "Zona restrita", "Ninguém dentro da área demarcada (a zona é desenhada em cada câmera)"],
  ["max_people", "Excesso de pessoas", "Limite de pessoas ao mesmo tempo na área"],
  ["fire_smoke", "Fogo e fumaça", "Princípio de incêndio na imagem"],
];

let root;
let units = [];
let sectors = [];
let templates = [];
let cameras = [];
let rules = [];
let unitId = null;
let current = null; // setor em edição (objeto) ou {} para novo
let previewTimer = null;

const cap = (s) => s[0].toUpperCase() + s.slice(1);
const sevOptions = (value) => SEVERITIES.map(([v, l]) => `<option value="${v}" ${v === value ? "selected" : ""}>${l}</option>`).join("");

function blank() {
  return { unit_id: unitId, name: "", required_ppe: [], delivery_ppe: [], ppe_severity: "alta", reference: "",
    behaviors: {}, start_hour: null, end_hour: null };
}

function readForm() {
  const f = $("#sector-form", root);
  const behaviors = {};
  for (const [key] of BEHAVIORS) {
    behaviors[key] = { enabled: f[`b_${key}`].checked, severity: f[`s_${key}`].value };
    if (key === "max_people") behaviors[key].max = Number(f.max_people.value || 2);
  }
  const num = (v) => (v === "" ? null : Number(v));
  return {
    unit_id: Number(f.unit_id.value), name: f.name.value.trim(), reference: f.reference.value,
    required_ppe: PPE.filter((p) => f[`ppe_${p}`].checked),
    delivery_ppe: f.delivery_ppe.value.split(",").map((s) => s.trim()).filter(Boolean),
    ppe_severity: f.ppe_severity.value, behaviors,
    start_hour: num(f.start_hour.value), end_hour: num(f.end_hour.value),
  };
}

function renderList() {
  const list = sectors.filter((s) => s.unit_id === unitId);
  $("#sector-list", root).innerHTML = list.map((s) => `
    <button type="button" class="sector-item ${current && current.id === s.id ? "active" : ""}" data-id="${s.id}">
      <span><b>${esc(s.name)}</b><small>${s.cameras} câmera(s) · ${s.rules} regra(s)</small></span>
      <span class="mono">v${s.version}</span>
    </button>`).join("") || `<p class="hint">Nenhum setor nesta unidade.</p>`;
}

async function refreshPreview() {
  if (!current || !can("tecnico")) return;
  const box = $("#sector-preview", root);
  const data = readForm();
  if (!data.name) { box.innerHTML = `<p class="hint">Dê um nome ao setor para ver a prévia.</p>`; return; }
  try {
    const url = current.id ? `/api/sectors/${current.id}/preview` : "/api/sectors/preview";
    const p = await api(url, { method: "POST", body: data });
    box.innerHTML = `
      <div class="preview-big">${current.id && p.cameras ? `${p.total} regra(s)` : `${p.per_camera} regra(s) por câmera`}</div>
      <div class="hint">${current.id && p.cameras ? `serão criadas ou atualizadas em ${p.cameras} câmera(s) · ${p.per_camera} por câmera`
        : "serão geradas em cada câmera associada ao setor"}</div>
      <ul class="plain">
        ${p.created.length ? `<li>+ ${p.created.length} nova(s)</li>` : ""}
        ${p.updated.length ? `<li>~ ${p.updated.length} atualizada(s)</li>` : ""}
        ${p.removed.length ? `<li>− ${p.removed.length} removida(s): ${esc(p.removed.join("; "))}</li>` : ""}
      </ul>
      ${p.pending_zone.length ? `<p class="warn-text">▲ Sem zona desenhada (a regra de zona restrita fica desativada até o desenho):
        ${esc([...new Set(p.pending_zone)].join(", "))}</p>` : ""}`;
  } catch (err) { box.innerHTML = `<p class="warn-text">${esc(err.message)}</p>`; }
}

function renderEditor() {
  const box = $("#sector-editor", root);
  if (!current) {
    box.innerHTML = `<div class="card"><p class="hint">Escolha um setor ou crie um novo. Cada setor define o EPI obrigatório e as regras
      de comportamento; as regras de detecção das câmeras do setor são geradas automaticamente.</p></div>`;
    return;
  }
  const s = { ...blank(), ...current };
  const b = (key) => ({ enabled: false, severity: "alta", max: 2, ...(s.behaviors[key] || {}) });
  const ro = can("tecnico") ? "" : "disabled";
  const secCams = current.id ? cameras.filter((c) => c.sector_id === current.id) : [];
  box.innerHTML = `
    <form id="sector-form" class="card form">
      <div class="wide toolbar" style="margin:0">
        <div><h2 style="margin:0">${current.id ? esc(s.name) : "Novo setor"}</h2>
          ${current.id ? `<div class="hint">versão ${s.version} · alterado em ${fmtDateTime(s.updated_at)} por ${esc(s.updated_by || "—")}</div>` : ""}</div>
        <div class="actions">
          ${current.id && can("gestor") ? `<button type="button" class="danger small" id="sector-delete">Excluir</button>` : ""}
          ${can("tecnico") ? `<button type="submit">${current.id ? "Salvar e aplicar" : "Criar setor"}</button>` : ""}
        </div>
      </div>
      <label>Nome do setor <input name="name" value="${esc(s.name)}" required ${ro}></label>
      <label>Unidade <select name="unit_id" ${ro}>${units.map((u) => `<option value="${u.id}" ${u.id === s.unit_id ? "selected" : ""}>${esc(u.name)}</option>`).join("")}</select></label>
      <label class="wide">Referência (ordem de serviço, NR) <input name="reference" value="${esc(s.reference)}" placeholder="ex.: OS-SOL-03 · NR-6" ${ro}></label>

      <fieldset class="wide">
        <legend>EPI obrigatório verificado pela câmera</legend>
        ${PPE.map((p) => `<label class="check"><input type="checkbox" name="ppe_${p}" ${s.required_ppe.includes(p) ? "checked" : ""} ${ro}> ${cap(PPE_LABELS[p])}</label>`).join("")}
        <label style="margin-left:auto">Severidade <select name="ppe_severity" ${ro}>${sevOptions(s.ppe_severity)}</select></label>
      </fieldset>
      <label class="wide">EPI só com controle de entrega (a câmera não identifica com segurança), separados por vírgula
        <input name="delivery_ppe" value="${esc(s.delivery_ppe.join(", "))}" placeholder="ex.: Botina de segurança, Protetor auricular" ${ro}></label>

      <div class="wide">
        <div class="label-strong">Regras de comportamento</div>
        ${BEHAVIORS.map(([key, label, desc]) => `
          <div class="behavior-row">
            <label class="check"><input type="checkbox" name="b_${key}" ${b(key).enabled ? "checked" : ""} ${ro}> <b>${label}</b></label>
            <span class="hint">${desc}</span>
            ${key === "max_people" ? `<label class="inline">máx. <input type="number" name="max_people" min="0" max="100" value="${b(key).max ?? 2}" ${ro}></label>` : "<span></span>"}
            <select name="s_${key}" aria-label="Severidade de ${label}" ${ro}>${sevOptions(b(key).severity)}</select>
          </div>`).join("")}
      </div>
      <label>Das (hora) <input type="number" name="start_hour" min="0" max="23" value="${s.start_hour ?? ""}" placeholder="sempre" ${ro}></label>
      <label>Até (hora) <input type="number" name="end_hour" min="0" max="24" value="${s.end_hour ?? ""}" placeholder="sempre" ${ro}></label>
    </form>

    <div class="grid-2">
      <div class="card">
        <h3>Câmeras do setor</h3>
        ${current.id ? (secCams.map((c) => {
          const zr = rules.find((r) => r.camera_id === c.id && r.sector_id === current.id && r.type === "restricted_zone");
          const zoneInfo = !zr ? "" : zr.zone.length ? badge("✓ zona desenhada", "good") : `<a href="#regras">${badge("▲ desenhar zona", "warn")}</a>`;
          return `<div class="cam-row"><span class="mono">${esc(c.name)}</span><span class="hint">${esc(c.location || "")}</span>${zoneInfo}</div>`;
        }).join("") || `<p class="hint">Nenhuma câmera. Associe câmeras a este setor em <a href="#cameras">Cadastros › Câmeras</a>.</p>`)
          : `<p class="hint">Salve o setor e associe as câmeras em Cadastros › Câmeras.</p>`}
      </div>
      <div class="card preview-card"><h3>Prévia ao salvar</h3><div id="sector-preview"></div></div>
    </div>`;

  const form = $("#sector-form", box);
  form.addEventListener("input", () => { clearTimeout(previewTimer); previewTimer = setTimeout(refreshPreview, 350); });
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const data = readForm();
    if ((data.start_hour == null) !== (data.end_hour == null)) return toast("Informe as duas horas ou nenhuma.", "warn");
    try {
      const r = current.id
        ? await api(`/api/sectors/${current.id}`, { method: "PUT", body: data })
        : await api("/api/sectors", { method: "POST", body: data });
      const a = r.applied;
      toast(current.id ? `Padrão salvo (v${r.sector.version}): ${a.created.length} regra(s) criada(s), ${a.updated.length} atualizada(s), ${a.removed.length} removida(s).`
        : "Setor criado. Associe as câmeras a ele em Cadastros › Câmeras.", "ok", 6000);
      current = r.sector;
      await load();
    } catch (err) { toast(esc(err.message), "danger"); }
  });
  $("#sector-delete", box)?.addEventListener("click", async () => {
    if (!confirm(`Excluir o setor ${s.name}? As regras geradas por ele serão removidas das câmeras.`)) return;
    try {
      await api(`/api/sectors/${current.id}`, { method: "DELETE" });
      current = null;
      await load();
    } catch (err) { toast(esc(err.message), "danger"); }
  });
  refreshPreview();
}

async function load() {
  [units, sectors, cameras, rules] = await Promise.all([
    api("/api/units"), api("/api/sectors"), api("/api/cameras"), api("/api/rules")]);
  if (!unitId || !units.some((u) => u.id === unitId)) unitId = units[0]?.id ?? null;
  if (current?.id) current = sectors.find((s) => s.id === current.id) || null;
  $("#unit-select", root).innerHTML = units.map((u) => `<option value="${u.id}" ${u.id === unitId ? "selected" : ""}>${esc(u.name)}</option>`).join("");
  renderList();
  renderEditor();
}

export async function render(container) {
  root = container;
  templates = await api("/api/sectors/templates");
  root.innerHTML = `
    <div class="split">
      <aside class="split-side">
        <div class="card">
          <div class="toolbar" style="margin-top:0">
            <label style="flex:1">Unidade <select id="unit-select"></select></label>
            ${can("admin") ? `<button type="button" class="secondary small" id="unit-new" title="Nova unidade">+ Unidade</button>` : ""}
          </div>
          <div id="sector-list"></div>
          ${can("tecnico") ? `<button type="button" id="sector-new" style="width:100%;margin-top:10px">+ Novo setor</button>` : ""}
        </div>
        ${can("tecnico") ? `<div class="card">
          <div class="label-strong">Começar de um modelo</div>
          <p class="hint">Padrões de referência por atividade. Ajuste à realidade da unidade antes de salvar.</p>
          <div class="actions">${templates.map((t) => `<button type="button" class="secondary small" data-tpl="${t.id}">${esc(t.label)}</button>`).join("")}</div>
        </div>` : ""}
      </aside>
      <div class="split-main" id="sector-editor"></div>
    </div>`;

  $("#unit-select", root).addEventListener("change", (e) => { unitId = Number(e.target.value); current = null; renderList(); renderEditor(); });
  $("#sector-list", root).addEventListener("click", (e) => {
    const btn = e.target.closest("[data-id]");
    if (!btn) return;
    current = sectors.find((s) => s.id === Number(btn.dataset.id));
    renderList();
    renderEditor();
  });
  $("#sector-new", root)?.addEventListener("click", () => { current = blank(); renderList(); renderEditor(); });
  $$("[data-tpl]", root).forEach((btn) => btn.addEventListener("click", () => {
    const t = templates.find((x) => x.id === btn.dataset.tpl);
    const base = current && current.id ? current : blank();
    current = { ...base, required_ppe: t.required_ppe, delivery_ppe: t.delivery_ppe, behaviors: t.behaviors,
      reference: t.reference, name: base.name || t.label };
    renderEditor();
    toast(`Modelo "${esc(t.label)}" carregado. Revise e salve para aplicar.`, "ok", 4000);
  }));
  $("#unit-new", root)?.addEventListener("click", async () => {
    const name = prompt("Nome da nova unidade:");
    if (!name) return;
    try {
      const u = await api("/api/units", { method: "POST", body: { name } });
      unitId = u.id;
      current = null;
      await load();
    } catch (err) { toast(esc(err.message), "danger"); }
  });
  await load();
}
