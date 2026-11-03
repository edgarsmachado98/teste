// Guia DDS (Diálogo Diário de Segurança): plano mensal, registro com presença e biblioteca de temas.

import { $, $$, api, badge, can, esc, fmtDate, fmtPct, isoDate, session, toast } from "../core.js";

let el;
let tab = "plano";
let month = firstOfMonth(new Date());
let sectorFilter = "";
let units = [];
let sectors = [];
let themes = [];
let categories = [];
let meta = { shifts: [], company_name: "" };
let data = null;
let themeFilter = { category: "", q: "" };

const WEEKDAYS = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"];
const STATUS = { planejado: ["Planejado", ""], realizado: ["Realizado", "good"], cancelado: ["Cancelado", "muted"] };

function firstOfMonth(d) { return new Date(d.getFullYear(), d.getMonth(), 1); }
function lastOfMonth(d) { return new Date(d.getFullYear(), d.getMonth() + 1, 0); }
const monthLabel = (d) => { const t = d.toLocaleDateString("pt-BR", { month: "long", year: "numeric" }); return t[0].toUpperCase() + t.slice(1); };
const dayLabel = (iso) => new Date(`${iso}T12:00:00`).toLocaleDateString("pt-BR", { weekday: "short", day: "2-digit", month: "2-digit" });
const unitId = () => session.unitId || (units.length === 1 ? units[0].id : null);
const sectorsOf = (uid) => sectors.filter((s) => !uid || s.unit_id === uid);

/** Diálogo criado na hora (removido ao fechar). */
function makeDialog(html, cls = "form-dialog") {
  const d = document.createElement("dialog");
  d.className = cls;
  d.innerHTML = html;
  document.body.append(d);
  d.addEventListener("close", () => d.remove());
  d.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", () => d.close()));
  d.showModal();
  return d;
}

function themeOptions(selected, suggested = []) {
  const sug = suggested.length ? `<optgroup label="Sugeridos pelas ocorrências">${suggested.map((s) =>
    `<option value="${s.theme_id}" ${s.theme_id === selected ? "selected" : ""}>★ ${esc(s.title)}</option>`).join("")}</optgroup>` : "";
  return sug + categories.map((c) => {
    const list = themes.filter((t) => t.category === c);
    return list.length ? `<optgroup label="${esc(c)}">${list.map((t) =>
      `<option value="${t.id}" ${t.id === selected && !suggested.some((s) => s.theme_id === t.id) ? "selected" : ""}>${esc(t.title)}</option>`).join("")}</optgroup>` : "";
  }).join("");
}

const unitOptions = (sel) => units.map((u) => `<option value="${u.id}" ${u.id === sel ? "selected" : ""}>${esc(u.name)}</option>`).join("");
const sectorOptions = (uid, sel, empty = "Todos os setores / geral") => `<option value="">${empty}</option>` +
  sectorsOf(uid).map((s) => `<option value="${s.id}" ${s.id === sel ? "selected" : ""}>${esc(s.name)}</option>`).join("");
const shiftOptions = (sel) => `<option value="">Todos os turnos</option>` +
  (meta.shifts || []).map((s) => `<option ${s.name === sel ? "selected" : ""}>${esc(s.name)}</option>`).join("");

// ---------- Plano ----------

async function loadPlan() {
  const params = new URLSearchParams({ start: isoDate(month), end: isoDate(lastOfMonth(month)) });
  if (sectorFilter) params.set("sector_id", sectorFilter);
  const sugParams = new URLSearchParams();
  if (sectorFilter) sugParams.set("sector_id", sectorFilter); else if (unitId()) sugParams.set("unit_id", unitId());
  const [plan, sug] = await Promise.all([api(`/api/dds/sessions?${params}`), api(`/api/dds/suggestions?${sugParams}`)]);
  data = { ...plan, suggestions: sug };
  renderPlan();
}

function statusCell(s) {
  if (s.status === "realizado") return `${badge("Realizado", "good")}<div class="hint">${s.participants} participante(s)</div>`;
  if (s.late) return badge("Atrasado", "bad");
  return badge(...STATUS[s.status]);
}

function renderPlan() {
  const box = $("#dds-body", el);
  const sm = data.summary;
  const weeks = {};
  for (const s of data.sessions) {
    const d = new Date(`${s.day}T12:00:00`);
    const monday = new Date(d); monday.setDate(d.getDate() - ((d.getDay() + 6) % 7));
    (weeks[isoDate(monday)] ||= []).push(s);
  }
  const editor = can("tecnico");
  box.innerHTML = `
    <div class="toolbar">
      <div class="actions month-nav">
        <button class="secondary small" data-month="-1" aria-label="Mês anterior">‹</button>
        <h3 style="margin:0;min-width:170px;text-align:center">${esc(monthLabel(month))}</h3>
        <button class="secondary small" data-month="1" aria-label="Próximo mês">›</button>
        <select id="dds-sector" style="width:auto;margin:0">${sectorOptions(unitId(), Number(sectorFilter) || null)}</select>
      </div>
      ${editor ? `<div class="actions"><button class="secondary" id="dds-new">+ DDS avulso</button>
        <button id="dds-generate">Gerar plano do mês</button></div>` : ""}
    </div>
    <div class="stats">
      <div class="stat"><b>${sm.planned}</b><span>DDS programados no mês</span></div>
      <div class="stat"><b>${sm.done}</b><span>Realizados</span></div>
      <div class="stat ${sm.adherence != null && sm.adherence < 0.8 ? "stat-bad" : ""}"><b>${fmtPct(sm.adherence)}</b>
        <span>Aderência (realizados ÷ previstos até hoje)</span></div>
      <div class="stat"><b>${sm.participants}</b><span>Participações registradas</span></div>
      <div class="stat ${sm.late ? "stat-bad" : ""}"><b>${sm.late}</b><span>Atrasados (não registrados)</span></div>
    </div>
    ${data.suggestions.length ? `<div class="card dds-suggest">
      <div class="label-strong">Temas sugeridos pelas ocorrências das câmeras (últimos 30 dias)</div>
      <div class="dds-chips">${data.suggestions.slice(0, 5).map((s) => `<div class="dds-chip">
        <b>${esc(s.title)}</b><small>${esc(s.reason)}</small>
        ${editor ? `<button class="small secondary" data-schedule-theme="${s.theme_id}">Programar</button>` : ""}</div>`).join("")}</div>
    </div>` : ""}
    ${data.sessions.length ? Object.entries(weeks).map(([wk, list]) => `
      <h4 class="dds-week">Semana de ${fmtDate(wk)}</h4>
      <div class="table-wrap"><table class="dds-table">
        <tr><th>Data</th><th>Setor · turno</th><th>Tema</th><th>Conduz</th><th>Situação</th><th></th></tr>
        ${list.map((s) => `<tr class="${s.late ? "row-bad" : ""}">
          <td class="nowrap"><b>${esc(dayLabel(s.day))}</b></td>
          <td>${esc(s.sector || "Geral")}${units.length > 1 && !session.unitId ? `<div class="hint">${esc(s.unit)}</div>` : ""}
            <div class="hint">${esc(s.shift || "todos os turnos")}</div></td>
          <td><b>${esc(s.title)}</b><div class="hint">${esc(s.category || "")}${s.reference ? ` · ${esc(s.reference)}` : ""}</div>
            ${s.reason && s.reason !== "rotação de temas" ? `<div class="dds-reason">★ ${esc(s.reason)}</div>` : ""}</td>
          <td>${esc(s.facilitator || "–")}</td>
          <td>${statusCell(s)}</td>
          <td><div class="actions row-actions">
            <button class="small secondary" data-act="script" data-id="${s.id}">Roteiro</button>
            <button class="small secondary" data-act="print" data-id="${s.id}" title="Lista de presença para assinatura">Lista</button>
            ${editor && s.status !== "cancelado" && s.day <= isoDate(new Date())
              ? `<button class="small" data-act="record" data-id="${s.id}">${s.status === "realizado" ? "Presença" : "Registrar"}</button>` : ""}
            ${editor && s.status !== "realizado" ? `<button class="small secondary" data-act="edit" data-id="${s.id}">Editar</button>
              <button class="small danger" data-act="delete" data-id="${s.id}" title="Excluir">×</button>` : ""}
          </div></td></tr>`).join("")}
      </table></div>`).join("") : `<div class="card"><p class="hint" style="margin:0">Nenhum DDS programado neste mês.
        ${editor ? "Use <b>Gerar plano do mês</b>: o VigIA escolhe os temas pelas ocorrências do setor e alterna os assuntos." : ""}</p></div>`}`;

  $$("[data-month]", box).forEach((b) => b.addEventListener("click", () => {
    month = new Date(month.getFullYear(), month.getMonth() + Number(b.dataset.month), 1);
    loadPlan().catch((err) => toast(esc(err.message), "danger"));
  }));
  $("#dds-sector", box).addEventListener("change", (e) => { sectorFilter = e.target.value; loadPlan(); });
  $("#dds-generate", box)?.addEventListener("click", openGenerate);
  $("#dds-new", box)?.addEventListener("click", () => openSessionForm());
  $$("[data-schedule-theme]", box).forEach((b) => b.addEventListener("click",
    () => openSessionForm(null, Number(b.dataset.scheduleTheme))));
  $$("[data-act]", box).forEach((b) => b.addEventListener("click", async () => {
    const s = data.sessions.find((x) => x.id === Number(b.dataset.id));
    try {
      if (b.dataset.act === "script") openScript(s);
      if (b.dataset.act === "print") await printAttendance(s);
      if (b.dataset.act === "record") await openRecord(s);
      if (b.dataset.act === "edit") openSessionForm(s);
      if (b.dataset.act === "delete" && confirm(`Excluir o DDS de ${fmtDate(s.day)} (${s.title})?`)) {
        await api(`/api/dds/sessions/${s.id}`, { method: "DELETE" });
        loadPlan();
      }
    } catch (err) { toast(esc(err.message), "danger"); }
  }));
}

function scriptHtml(t) {
  return `<div class="dds-script">
    <div class="hint">${esc(t.category || "")}${t.reference ? ` · ${esc(t.reference)}` : ""} · cerca de ${t.minutes || 10} minutos</div>
    <ol>${(t.points || []).map((p) => `<li>${esc(p)}</li>`).join("")}</ol>
    ${t.question ? `<p class="dds-question"><b>Pergunta para a equipe:</b> ${esc(t.question)}</p>` : ""}
  </div>`;
}

function openScript(s) {
  makeDialog(`<h2 style="margin-bottom:4px">${esc(s.title)}</h2>
    <p class="hint">${fmtDate(s.day)} · ${esc(s.sector || "Geral")} · ${esc(s.shift || "todos os turnos")}${s.facilitator ? ` · conduz: ${esc(s.facilitator)}` : ""}</p>
    ${scriptHtml(s)}
    <p class="hint">Dica: comece por uma situação real do setor e termine combinando uma ação concreta com a equipe.</p>
    <div class="actions"><button type="button" class="secondary" data-close>Fechar</button></div>`);
}

function openSessionForm(s = null, themeId = null) {
  const uid = s?.unit_id ?? unitId() ?? units[0]?.id;
  const d = makeDialog(`<form class="form" method="dialog">
    <h2>${s ? "Editar DDS" : "Programar DDS"}</h2>
    ${units.length > 1 ? `<label>Unidade <select name="unit_id">${unitOptions(uid)}</select></label>` : ""}
    <label>Setor <select name="sector_id">${sectorOptions(uid, s?.sector_id ?? (Number(sectorFilter) || null))}</select></label>
    <label>Turno <select name="shift">${shiftOptions(s?.shift ?? "")}</select></label>
    <label>Data <input type="date" name="day" required value="${esc(s?.day || isoDate(new Date()))}"></label>
    <label class="wide">Tema <select name="theme_id" required>${themeOptions(s?.theme_id ?? themeId, data?.suggestions || [])}</select></label>
    <label>Quem conduz <input name="facilitator" maxlength="120" value="${esc(s?.facilitator || "")}" placeholder="ex.: líder do turno"></label>
    ${s ? `<label>Situação <select name="status"><option value="planejado">Planejado</option>
      <option value="cancelado" ${s.status === "cancelado" ? "selected" : ""}>Cancelado</option></select></label>` : ""}
    <label class="wide">Observações <input name="notes" maxlength="2000" value="${esc(s?.notes || "")}"></label>
    <div class="actions wide"><button type="submit">Salvar</button><button type="button" class="secondary" data-close>Cancelar</button></div>
  </form>`);
  const f = d.querySelector("form");
  f.unit_id?.addEventListener("change", () => { f.sector_id.innerHTML = sectorOptions(Number(f.unit_id.value), null); });
  f.addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = {
      unit_id: Number(f.unit_id?.value || uid), sector_id: f.sector_id.value ? Number(f.sector_id.value) : null,
      shift: f.shift.value, day: f.day.value, theme_id: Number(f.theme_id.value), facilitator: f.facilitator.value,
      notes: f.notes.value, status: f.status?.value || "planejado",
    };
    try {
      await api(s ? `/api/dds/sessions/${s.id}` : "/api/dds/sessions", { method: s ? "PUT" : "POST", body });
      d.close();
      toast("DDS salvo.", "ok", 2500);
      loadPlan();
    } catch (err) { toast(esc(err.message), "danger"); }
  });
}

function openGenerate() {
  const uid = unitId() ?? units[0]?.id;
  const today = isoDate(new Date());
  const start = isoDate(month) < today && isoDate(lastOfMonth(month)) >= today ? today : isoDate(month);
  const d = makeDialog(`<form class="form" method="dialog">
    <h2>Gerar plano de DDS</h2>
    <p class="hint wide">Primeiro entram os temas das ocorrências recentes do setor; depois os temas menos usados,
      alternando os assuntos. Nenhum tema se repete no plano e dias que já têm DDS são mantidos.</p>
    ${units.length > 1 ? `<label>Unidade <select name="unit_id">${unitOptions(uid)}</select></label>` : ""}
    <label>Setor <select name="sector_id">${sectorOptions(uid, Number(sectorFilter) || null)}</select></label>
    <label>Turno <select name="shift">${shiftOptions("")}</select></label>
    <label>Quem conduz <input name="facilitator" maxlength="120" placeholder="ex.: líder do turno"></label>
    <label>De <input type="date" name="start" required value="${start}"></label>
    <label>Até <input type="date" name="end" required value="${isoDate(lastOfMonth(month))}"></label>
    <fieldset class="wide"><legend>Dias da semana</legend>
      ${WEEKDAYS.map((w, i) => `<label class="check"><input type="checkbox" name="wd${i}" ${i < 5 ? "checked" : ""}> ${w}</label>`).join("")}
    </fieldset>
    <div class="wide" id="plan-preview"></div>
    <div class="actions wide"><button type="button" class="secondary" id="plan-preview-btn">Ver prévia</button>
      <button type="submit" id="plan-save" disabled>Gravar plano</button>
      <button type="button" class="secondary" data-close>Cancelar</button></div>
  </form>`);
  const f = d.querySelector("form");
  const body = (dry) => ({
    unit_id: Number(f.unit_id?.value || uid), sector_id: f.sector_id.value ? Number(f.sector_id.value) : null,
    shift: f.shift.value, facilitator: f.facilitator.value, start: f.start.value, end: f.end.value,
    weekdays: WEEKDAYS.map((_, i) => i).filter((i) => f[`wd${i}`].checked), dry_run: dry,
  });
  f.unit_id?.addEventListener("change", () => { f.sector_id.innerHTML = sectorOptions(Number(f.unit_id.value), null); });
  f.addEventListener("input", () => { $("#plan-save", d).disabled = true; });
  $("#plan-preview-btn", d).addEventListener("click", async () => {
    try {
      const r = await api("/api/dds/plan", { method: "POST", body: body(true) });
      $("#plan-preview", d).innerHTML = r.items.length ? `<div class="label-strong">${r.items.length} DDS</div>
        <div class="table-wrap plan-preview"><table class="compact"><tr><th>Data</th><th>Tema</th><th>Por quê</th></tr>
        ${r.items.map((i) => `<tr><td class="nowrap">${esc(dayLabel(i.date))}</td><td>${esc(i.title)}<div class="hint">${esc(i.category)}</div></td>
          <td class="hint">${i.reason !== "rotação de temas" ? "★ " : ""}${esc(i.reason)}</td></tr>`).join("")}</table></div>`
        : `<p class="hint">Nenhum dia livre no período escolhido (os dias já programados são mantidos).</p>`;
      $("#plan-save", d).disabled = !r.items.length;
      $("#plan-save", d).textContent = r.items.length ? `Gravar plano (${r.items.length} DDS)` : "Gravar plano";
    } catch (err) { toast(esc(err.message), "danger"); }
  });
  f.addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const r = await api("/api/dds/plan", { method: "POST", body: body(false) });
      d.close();
      toast(`${r.created} DDS programados.`, "ok", 3000);
      const first = r.items[0]?.date;
      if (first) month = firstOfMonth(new Date(`${first}T12:00:00`));
      loadPlan();
    } catch (err) { toast(esc(err.message), "danger"); }
  });
}

async function peopleFor(s) {
  const params = new URLSearchParams({ status: "ativo", limit: 500, unit_id: s.unit_id });
  if (s.sector_id) params.set("sector_id", s.sector_id);
  return (await api(`/api/people?${params}`)).items;
}

async function openRecord(s) {
  const people = await peopleFor(s);
  const present = new Set(s.person_ids);
  const d = makeDialog(`<form class="form" method="dialog">
    <h2 style="margin-bottom:0">${s.status === "realizado" ? "Presença do DDS" : "Registrar DDS realizado"}</h2>
    <p class="hint wide">${fmtDate(s.day)} · ${esc(s.sector || "Geral")} · ${esc(s.shift || "todos os turnos")}</p>
    <details class="wide"><summary><b>${esc(s.title)}</b> – ver roteiro</summary>${scriptHtml(s)}</details>
    <label>Quem conduziu <input name="facilitator" required minlength="2" maxlength="120" value="${esc(s.facilitator || session.user.name)}"></label>
    <label>Participantes sem cadastro (terceiros, visitantes) <input type="number" name="extra" min="0" max="500" value="${s.extra_participants || 0}"></label>
    <div class="wide">
      <div class="toolbar" style="margin:4px 0"><span class="label-strong" style="margin:0">Presentes (${people.length} no cadastro)</span>
        <span class="actions"><input type="search" id="att-q" placeholder="Buscar nome ou matrícula" style="width:200px;margin:0">
          ${s.shift ? `<button type="button" class="small secondary" id="att-shift">Marcar ${esc(s.shift)}</button>` : ""}
          <button type="button" class="small secondary" id="att-all">Marcar todos</button>
          <button type="button" class="small secondary" id="att-none">Limpar</button></span></div>
      <div class="att-list">${people.map((p) => `<label class="check att" data-name="${esc(`${p.name} ${p.registration}`.toLowerCase())}" data-shift="${esc(p.shift)}">
        <input type="checkbox" name="p" value="${p.id}" ${present.has(p.id) ? "checked" : ""}> ${esc(p.name)}
        <small>${esc(p.registration || "")}${p.shift ? ` · ${esc(p.shift)}` : ""}</small></label>`).join("")
        || `<p class="hint">Nenhuma pessoa ativa cadastrada ${s.sector ? "neste setor" : "nesta unidade"}. Informe os participantes sem cadastro.</p>`}</div>
      <p class="hint" id="att-count"></p>
    </div>
    <label class="wide">Observações (dúvidas, combinados, condições inseguras relatadas) <textarea name="notes" rows="2" maxlength="2000">${esc(s.notes || "")}</textarea></label>
    <div class="actions wide"><button type="submit">Salvar registro</button><button type="button" class="secondary" data-close>Cancelar</button></div>
  </form>`);
  const f = d.querySelector("form");
  const boxes = () => $$("input[name=p]", d);
  const count = () => { $("#att-count", d).textContent = `${boxes().filter((b) => b.checked).length} marcado(s) + ${Number(f.extra.value) || 0} sem cadastro`; };
  f.addEventListener("change", count);
  f.extra.addEventListener("input", count);
  count();
  $("#att-q", d).addEventListener("input", (e) => {
    const q = e.target.value.trim().toLowerCase();
    $$(".att", d).forEach((l) => { l.hidden = q && !l.dataset.name.includes(q); });
  });
  const mark = (fn) => { $$(".att", d).forEach((l) => { if (!l.hidden) l.querySelector("input").checked = fn(l); }); count(); };
  $("#att-all", d).addEventListener("click", () => mark(() => true));
  $("#att-none", d).addEventListener("click", () => mark(() => false));
  $("#att-shift", d)?.addEventListener("click", () => mark((l) => l.dataset.shift === s.shift || l.querySelector("input").checked));
  f.addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await api(`/api/dds/sessions/${s.id}/record`, { method: "POST", body: {
        person_ids: boxes().filter((b) => b.checked).map((b) => Number(b.value)),
        extra_participants: Number(f.extra.value) || 0, facilitator: f.facilitator.value, notes: f.notes.value } });
      d.close();
      toast("DDS registrado.", "ok", 2500);
      loadPlan();
    } catch (err) { toast(esc(err.message), "danger"); }
  });
}

async function printAttendance(s) {
  // sem permissão para o cadastro de pessoas: a lista sai com linhas em branco
  const all = can("tecnico") ? await peopleFor(s).catch(() => []) : [];
  const people = all.filter((p) => !s.shift || !p.shift || p.shift === s.shift);
  const rows = [...people.map((p) => [p.name, p.registration || ""]), ...Array(8).fill(["", ""])];
  const w = window.open("", "_blank");
  if (!w) return toast("Permita pop-ups para imprimir a lista.", "warn");
  w.document.write(`<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>Lista de presença – DDS ${fmtDate(s.day)}</title>
    <link rel="stylesheet" href="${location.origin}/fonts/fonts.css">
    <style>body{font:12px "IBM Plex Sans",Arial,sans-serif;color:#1B1D1F;margin:18mm 14mm}h1{font:700 18px Archivo,Arial;margin:0 0 2px}
    .bar{height:6px;background:repeating-linear-gradient(135deg,#F2B705 0 8px,#1B1D1F 8px 12px);margin-bottom:10px}
    .meta{display:grid;grid-template-columns:repeat(3,1fr);gap:4px 16px;margin:8px 0 10px}.meta div{border-bottom:1px solid #ccc;padding:3px 0}
    .meta span{color:#5E6368;font-size:10px;display:block}ol{margin:4px 0 8px 18px;padding:0}li{margin:2px 0}
    table{width:100%;border-collapse:collapse;margin-top:8px}th,td{border:1px solid #999;padding:6px;text-align:left;height:18px}
    th{background:#F1EEE8;font-size:11px}td.n{width:24px;text-align:center}td.sig{width:38%}.foot{margin-top:24px;display:flex;gap:40px}
    .foot div{flex:1;border-top:1px solid #333;padding-top:4px;text-align:center}@media print{body{margin:10mm}}</style></head><body>
    <div class="bar"></div><h1>Lista de presença – DDS</h1><div>${esc(meta.company_name || "")}</div>
    <div class="meta"><div><span>Data</span>${fmtDate(s.day)}</div><div><span>Unidade</span>${esc(s.unit || "")}</div>
      <div><span>Setor · turno</span>${esc(s.sector || "Geral")} · ${esc(s.shift || "todos")}</div>
      <div style="grid-column:span 2"><span>Tema</span><b>${esc(s.title)}</b></div><div><span>Referência</span>${esc(s.reference || "–")}</div>
      <div style="grid-column:span 3"><span>Quem conduz</span>${esc(s.facilitator || "")}&nbsp;</div></div>
    <b>Pontos abordados</b><ol>${(s.points || []).map((p) => `<li>${esc(p)}</li>`).join("")}</ol>
    <table><tr><th>#</th><th>Nome</th><th>Matrícula</th><th>Assinatura</th></tr>
    ${rows.map(([n, r], i) => `<tr><td class="n">${i + 1}</td><td>${esc(n)}</td><td>${esc(r)}</td><td class="sig"></td></tr>`).join("")}</table>
    <div class="foot"><div>Quem conduziu</div><div>Técnico de segurança</div></div>
    <script>window.onload=()=>window.print()<\/script></body></html>`);
  w.document.close();
}

// ---------- Temas ----------

function renderThemes() {
  const box = $("#dds-body", el);
  const q = themeFilter.q.toLowerCase();
  const list = themes.filter((t) => (!themeFilter.category || t.category === themeFilter.category)
    && (!q || `${t.title} ${t.points.join(" ")} ${t.reference}`.toLowerCase().includes(q)));
  box.innerHTML = `
    <div class="toolbar">
      <div class="actions"><input type="search" id="th-q" placeholder="Buscar tema, assunto ou NR" value="${esc(themeFilter.q)}" style="width:260px;margin:0">
        <span class="hint">${list.length} tema(s)</span></div>
      ${can("tecnico") ? `<button id="th-new">+ Tema próprio</button>` : ""}
    </div>
    <div class="dds-cats"><button class="small ${themeFilter.category ? "secondary" : ""}" data-cat="">Todos</button>
      ${categories.map((c) => `<button class="small ${themeFilter.category === c ? "" : "secondary"}" data-cat="${esc(c)}">${esc(c)}</button>`).join("")}</div>
    <div class="dds-themes">${list.map((t) => `<article class="card dds-theme">
      <div class="hint">${esc(t.category)}${t.reference ? ` · ${esc(t.reference)}` : ""}${t.builtin ? "" : ` · ${badge("tema próprio", "")}`}</div>
      <h3>${esc(t.title)}</h3>
      <ol>${t.points.map((p) => `<li>${esc(p)}</li>`).join("")}</ol>
      ${t.question ? `<p class="dds-question">${esc(t.question)}</p>` : ""}
      <div class="dds-theme-foot"><span class="hint">${t.uses ? `Realizado ${t.uses}× · último em ${fmtDate(t.last_used)}` : "Ainda não realizado"}</span>
        ${can("tecnico") ? `<span class="actions"><button class="small" data-th-schedule="${t.id}">Programar</button>
          <button class="small secondary" data-th-copy="${t.id}">${t.builtin ? "Copiar e adaptar" : "Editar"}</button>
          ${t.builtin ? "" : `<button class="small danger" data-th-del="${t.id}">×</button>`}</span>` : ""}</div>
    </article>`).join("")}</div>`;
  let timer;
  $("#th-q", box).addEventListener("input", (e) => {
    clearTimeout(timer);
    timer = setTimeout(() => { themeFilter.q = e.target.value; renderThemes(); $("#th-q", el).focus(); }, 250);
  });
  $$("[data-cat]", box).forEach((b) => b.addEventListener("click", () => { themeFilter.category = b.dataset.cat; renderThemes(); }));
  $("#th-new", box)?.addEventListener("click", () => openThemeForm());
  $$("[data-th-schedule]", box).forEach((b) => b.addEventListener("click", () => openSessionForm(null, Number(b.dataset.thSchedule))));
  $$("[data-th-copy]", box).forEach((b) => b.addEventListener("click", () => {
    const t = themes.find((x) => x.id === Number(b.dataset.thCopy));
    openThemeForm(t.builtin ? { ...t, id: null, title: `${t.title} (adaptado)` } : t);
  }));
  $$("[data-th-del]", box).forEach((b) => b.addEventListener("click", async () => {
    const t = themes.find((x) => x.id === Number(b.dataset.thDel));
    if (!confirm(`Excluir o tema "${t.title}"? Os DDS já realizados continuam no histórico.`)) return;
    try { await api(`/api/dds/themes/${t.id}`, { method: "DELETE" }); await loadThemes(); renderThemes(); }
    catch (err) { toast(esc(err.message), "danger"); }
  }));
}

function openThemeForm(t = null) {
  const d = makeDialog(`<form class="form" method="dialog">
    <h2>${t?.id ? "Editar tema" : "Novo tema de DDS"}</h2>
    <label class="wide">Título <input name="title" required minlength="3" maxlength="200" value="${esc(t?.title || "")}"></label>
    <label>Assunto <select name="category">${categories.map((c) => `<option ${c === t?.category ? "selected" : ""}>${esc(c)}</option>`).join("")}</select></label>
    <label>Referência (NR, procedimento) <input name="reference" maxlength="120" value="${esc(t?.reference || "")}"></label>
    <label>Duração (min) <input type="number" name="minutes" min="5" max="60" value="${t?.minutes || 10}"></label>
    <label class="wide">Roteiro – um ponto por linha <textarea name="points" rows="5">${esc((t?.points || []).join("\n"))}</textarea></label>
    <label class="wide">Pergunta para a equipe <input name="question" maxlength="300" value="${esc(t?.question || "")}"></label>
    <div class="actions wide"><button type="submit">Salvar tema</button><button type="button" class="secondary" data-close>Cancelar</button></div>
  </form>`);
  const f = d.querySelector("form");
  f.addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = { title: f.title.value, category: f.category.value, reference: f.reference.value,
      minutes: Number(f.minutes.value) || 10, points: f.points.value.split("\n"), question: f.question.value };
    try {
      await api(t?.id ? `/api/dds/themes/${t.id}` : "/api/dds/themes", { method: t?.id ? "PUT" : "POST", body });
      d.close();
      toast("Tema salvo.", "ok", 2500);
      await loadThemes();
      renderThemes();
    } catch (err) { toast(esc(err.message), "danger"); }
  });
}

async function loadThemes() {
  const r = await api(`/api/dds/themes${unitId() ? `?unit_id=${unitId()}` : ""}`);
  themes = r.themes;
  categories = r.categories.filter((c) => themes.some((t) => t.category === c));
}

// ---------- Guia ----------

function renderTabs() {
  $("#dds-tabs", el).innerHTML = [["plano", "Plano de DDS"], ["temas", "Temas"]]
    .map(([id, label]) => `<button class="${tab === id ? "active" : ""}" data-tab="${id}">${label}</button>`).join("");
  $$("#dds-tabs [data-tab]", el).forEach((b) => b.addEventListener("click", () => { tab = b.dataset.tab; open(); }));
}

async function open() {
  renderTabs();
  if (tab === "temas") renderThemes();
  else await loadPlan();
}

export async function show(element) {
  el = element;
  el.innerHTML = `<h2>DDS – Diálogo Diário de Segurança</h2><div class="subtabs" id="dds-tabs"></div><div id="dds-body"></div>`;
  [units, sectors, meta] = await Promise.all([api("/api/units"), api("/api/sectors"),
    api("/api/meta").catch(() => ({ shifts: [] })), loadThemes()]);
  if (sectorFilter && !sectorsOf(unitId()).some((s) => String(s.id) === sectorFilter)) sectorFilter = "";
  await open();
}

export function onRealtime(msg) {
  if (msg.kind === "event" && tab === "plano" && data) loadPlan().catch(() => {});
}
