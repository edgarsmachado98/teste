// Guia EPI: entregas com ficha assinada, estoque por unidade (com mínimo), uniformes, plano de substituição
// por setor, vencimento de CA e catálogo.

import { $, $$, api, badge, can, esc, fmtDate, fmtDateTime, isoDate, session, toast, withToken } from "../core.js";
import { CATEGORY, makeDialog, openDelivery, openSign, REASONS, SIZE_LABELS } from "../epi-ui.js";

let el;
let tab = "entregas";
let units = [];
let sectors = [];
let summary = null;

const PPE_TYPES = { "": "– (só controle de entrega)", helmet: "Capacete", vest: "Colete", glasses: "Óculos", gloves: "Luvas",
  mask: "Máscara", harness: "Cinto paraquedista", boots: "Botina", ear_protection: "Protetor auricular", face_shield: "Protetor facial" };
const CA_STATUS = {
  vencido: ["CA vencido", "bad"], vence: ["Vence em breve", "warn"], sem_ca: ["Sem CA", "bad"],
  sem_validade: ["Sem validade", "warn"], ok: ["Válido", "good"], nao_se_aplica: ["–", "muted"],
};
const CA_LINK = "https://caepi.mte.gov.br/internet/ConsultaCAInternet.aspx";

const unitId = () => session.unitId || (units.length === 1 ? units[0].id : null);
const unitOptions = (sel, empty = "") => (empty ? `<option value="">${empty}</option>` : "")
  + units.map((u) => `<option value="${u.id}" ${u.id === sel ? "selected" : ""}>${esc(u.name)}</option>`).join("");
const sectorOptions = (sel) => `<option value="">Todos os setores</option>` + sectors.filter((s) => !unitId() || s.unit_id === unitId())
  .map((s) => `<option value="${s.id}" ${String(s.id) === String(sel) ? "selected" : ""}>${esc(s.name)}</option>`).join("");
const caBadge = (st, days) => {
  const [label, kind] = CA_STATUS[st] || [st, ""];
  return badge(st === "vence" && days != null ? `Vence em ${days} dia(s)` : label, kind);
};

// ---------- Resumo ----------

async function loadSummary() {
  summary = await api(`/api/ppe/summary${unitId() ? `?unit_id=${unitId()}` : ""}`);
  $("#epi-stats", el).innerHTML = `
    <button class="stat ${summary.stock_low ? "stat-bad" : ""}" data-go="estoque"><b>${summary.stock_low}</b><span>Itens no estoque mínimo ou abaixo</span></button>
    <button class="stat ${summary.ca_expired || summary.ca_missing ? "stat-bad" : ""}" data-go="ca"><b>${summary.ca_expired + summary.ca_missing}</b>
      <span>CA vencido ou sem CA${summary.ca_expiring ? ` · ${summary.ca_expiring} vencendo em 60 dias` : ""}</span></button>
    <button class="stat ${summary.replacements_overdue ? "stat-bad" : ""}" data-go="plano"><b>${summary.replacements_overdue}</b>
      <span>Trocas vencidas${summary.replacements_due ? ` · ${summary.replacements_due} nos próximos 30 dias` : ""}</span></button>
    <button class="stat ${summary.missing ? "stat-bad" : ""}" data-go="plano"><b>${summary.missing}</b><span>EPI exigido pelo setor e não entregue</span></button>
    <button class="stat ${summary.unsigned ? "stat-bad" : ""}" data-go="entregas" data-pending="1"><b>${summary.unsigned}</b><span>Entregas sem assinatura</span></button>`;
  $$("#epi-stats [data-go]", el).forEach((b) => b.addEventListener("click", () => {
    if (b.dataset.pending) pendingOnly = true;
    tab = b.dataset.go;
    open();
  }));
}

// ---------- Entregas ----------

let pendingOnly = false;

async function renderDeliveries(box) {
  const today = new Date();
  const from = new Date(today.getFullYear(), today.getMonth() - 2, 1);
  box.innerHTML = `
    <div class="toolbar">
      <form class="filters" id="epi-del-f" style="margin:0">
        <label>De <input type="date" name="start" value="${isoDate(from)}"></label>
        <label>Até <input type="date" name="end" value="${isoDate(today)}"></label>
        <label>Tipo <select name="category"><option value="">EPI e uniforme</option><option value="epi">EPI</option>
          <option value="uniforme">Uniforme</option></select></label>
        <label class="check" style="align-self:flex-end"><input type="checkbox" name="pending" ${pendingOnly ? "checked" : ""}> Só sem assinatura</label>
      </form>
      ${can("tecnico") ? `<div class="actions"><button id="epi-new">+ Nova entrega</button></div>` : ""}
    </div>
    <div class="table-wrap"><table id="epi-del-table"><tr><td class="hint">Carregando…</td></tr></table></div>`;
  const f = $("#epi-del-f", box);
  const load = async () => {
    const params = new URLSearchParams({ start: f.start.value, end: f.end.value });
    if (f.category.value) params.set("category", f.category.value);
    if (f.pending.checked) params.set("pending", "true");
    const rows = await api(`/api/ppe/receipts?${params}`);
    $("#epi-del-table", box).innerHTML = rows.length ? `
      <tr><th>Comprovante</th><th>Data</th><th>Colaborador</th><th>Itens</th><th>Assinatura</th><th></th></tr>
      ${rows.map((r) => `<tr class="${r.signed ? "" : "row-bad"}">
        <td class="mono">${esc(r.number)}</td><td>${fmtDate(r.delivered_on)}</td>
        <td><b>${esc(r.person)}</b><div class="hint">${esc(r.sector || "")}${r.registration ? ` · ${esc(r.registration)}` : ""}</div></td>
        <td>${r.items.map((i) => `${i.quantity}× ${esc(i.item)}${i.size ? ` (${esc(i.size)})` : ""}
          <span class="hint">${esc(REASONS[i.reason] || "")}</span>`).join("<br>")}</td>
        <td>${r.signed ? `${badge(r.method_label, "good")}<div class="hint">${fmtDateTime(r.signed_at)}</div>` : badge("Pendente", "warn")}</td>
        <td><div class="actions row-actions">
          ${!r.signed && can("tecnico") ? `<button class="small" data-sign="${r.id}">Assinar</button>` : ""}
          <a class="small-link" href="ficha-epi.html?person=${r.person_id}" target="_blank">Ficha</a>
          ${!r.signed && can("tecnico") ? `<button class="small secondary" data-undo="${r.id}" title="Lançada por engano: devolve ao estoque">Estornar</button>` : ""}
        </div></td></tr>`).join("")}`
      : `<tr><td class="hint">Nenhuma entrega no período.</td></tr>`;
    $$("[data-sign]", box).forEach((b) => b.addEventListener("click", async () => {
      const r = rows.find((x) => x.id === Number(b.dataset.sign));
      if (await openSign(r)) { await load(); loadSummary(); }
    }));
    $$("[data-undo]", box).forEach((b) => b.addEventListener("click", async () => {
      const r = rows.find((x) => x.id === Number(b.dataset.undo));
      if (!confirm(`Estornar a entrega ${r.number} de ${r.person}? Os itens voltam ao estoque.`)) return;
      try { await api(`/api/ppe/receipts/${r.id}`, { method: "DELETE" }); await load(); loadSummary(); }
      catch (err) { toast(esc(err.message), "danger"); }
    }));
  };
  f.addEventListener("change", () => { pendingOnly = f.pending.checked; load(); });
  $("#epi-new", box)?.addEventListener("click", async () => { if (await openDelivery()) { await load(); loadSummary(); } });
  await load();
}

// ---------- Estoque ----------

let stockUnit = null;
let stockCat = "";

async function renderStock(box) {
  stockUnit = stockUnit || unitId();
  box.innerHTML = `
    <div class="toolbar">
      <div class="filters" style="margin:0">
        <label>Unidade <select id="st-unit">${unitOptions(stockUnit, units.length > 1 ? "Todas as unidades" : "")}</select></label>
        <label>Tipo <select id="st-cat"><option value="">EPI e uniforme</option><option value="epi" ${stockCat === "epi" ? "selected" : ""}>EPI</option>
          <option value="uniforme" ${stockCat === "uniforme" ? "selected" : ""}>Uniforme</option></select></label>
      </div>
      <div class="actions"><a class="button secondary" id="st-csv">Planilha (CSV)</a>
        <button class="secondary" id="st-moves">Movimentações</button></div>
    </div>
    <p class="hint">Entregas registradas baixam o saldo da unidade do colaborador. Defina o <b>mínimo</b> de cada item:
      quando o saldo chega nele, o item aparece em vermelho e no resumo.</p>
    <div class="table-wrap"><table id="st-table"></table></div>`;
  const draw = async () => {
    const params = new URLSearchParams();
    if (stockUnit) params.set("unit_id", stockUnit);
    if (stockCat) params.set("category", stockCat);
    $("#st-csv", box).href = withToken(`/api/ppe/stock.csv${stockUnit ? `?unit_id=${stockUnit}` : ""}`);
    const data = await api(`/api/ppe/stock?${params}`);
    const multi = !stockUnit;
    $("#st-table", box).innerHTML = data.rows.length ? `
      <tr>${multi ? "<th>Unidade</th>" : ""}<th>Item</th><th>Tam.</th><th class="num">Saldo</th><th class="num">Mínimo</th><th>Local</th><th>Situação</th><th></th></tr>
      ${data.rows.map((r, i) => `<tr class="${r.low ? "row-bad" : ""}">
        ${multi ? `<td>${esc(r.unit)}</td>` : ""}
        <td><b>${esc(r.item)}</b> <span class="hint">${CATEGORY[r.category]}</span></td><td>${esc(r.size || "único")}</td>
        <td class="num"><b>${r.quantity}</b> <span class="hint">${esc(r.unit_label)}</span></td><td class="num">${r.min_quantity || "–"}</td>
        <td>${esc(r.location || "")}</td>
        <td>${r.low ? badge(r.quantity <= 0 ? "Zerado" : "Abaixo do mínimo", "bad") : (r.min_quantity ? badge("Ok", "good") : badge("Sem mínimo", "muted"))}
          ${r.ca_status === "vencido" ? badge("CA vencido", "bad") : ""}</td>
        <td>${can("tecnico") ? `<div class="actions row-actions">
          <button class="small" data-st="entrada" data-i="${i}">Entrada</button>
          <button class="small secondary" data-st="ajuste" data-i="${i}">Contagem</button>
          <button class="small secondary" data-st="min" data-i="${i}">Mínimo</button></div>` : ""}</td></tr>`).join("")}`
      : `<tr><td class="hint">Nenhum item no catálogo. Cadastre os EPIs e uniformes na aba Catálogo.</td></tr>`;
    $$("[data-st]", box).forEach((b) => b.addEventListener("click", () => stockDialog(b.dataset.st, data.rows[Number(b.dataset.i)], draw)));
  };
  $("#st-unit", box).addEventListener("change", (e) => { stockUnit = Number(e.target.value) || null; draw(); });
  $("#st-cat", box).addEventListener("change", (e) => { stockCat = e.target.value; draw(); });
  $("#st-moves", box).addEventListener("click", () => movementsDialog());
  await draw();
}

function stockDialog(kind, r, after) {
  const title = { entrada: "Entrada no estoque", ajuste: "Contagem (inventário)", min: "Estoque mínimo" }[kind];
  const label = `${r.item}${r.size ? ` · ${r.size}` : ""} · ${r.unit}`;
  const d = makeDialog(`<form class="form" method="dialog">
    <h2 class="wide">${title}</h2><p class="hint wide">${esc(label)} · saldo atual <b>${r.quantity}</b></p>
    ${kind === "entrada" ? `<label>Quantidade recebida <input type="number" name="quantity" min="1" required autofocus></label>
      <label>Nota fiscal / fornecedor <input name="note" maxlength="300"></label>` : ""}
    ${kind === "ajuste" ? `<label>Quantidade contada <input type="number" name="quantity" min="0" required value="${r.quantity}" autofocus></label>
      <label>Motivo <input name="note" maxlength="300" placeholder="inventário mensal, avaria..."></label>` : ""}
    ${kind === "min" ? `<label>Estoque mínimo <input type="number" name="min" min="0" required value="${r.min_quantity}" autofocus></label>
      <label>Local (almoxarifado, armário) <input name="location" maxlength="80" value="${esc(r.location || "")}"></label>
      <p class="hint wide">Dica: mínimo ≈ consumo médio do mês × prazo de compra (em meses) + uma margem de segurança.</p>` : ""}
    <div class="actions wide"><button type="submit">Salvar</button><button type="button" class="secondary" data-close>Cancelar</button></div>
  </form>`);
  const f = d.querySelector("form");
  f.addEventListener("submit", async (e) => {
    e.preventDefault();
    const base = { unit_id: r.unit_id, item_id: r.item_id, size: r.size };
    try {
      if (kind === "min") await api("/api/ppe/stock/min", { method: "PUT", body: { ...base, min_quantity: Number(f.min.value), location: f.location.value } });
      else await api("/api/ppe/stock/move", { method: "POST", body: { ...base, type: kind, quantity: Number(f.quantity.value), note: f.note.value } });
      d.close();
      toast("Estoque atualizado.", "ok", 2500);
      await after();
      loadSummary();
    } catch (err) { toast(esc(err.message), "danger"); }
  });
}

async function movementsDialog() {
  const rows = await api(`/api/ppe/movements${stockUnit ? `?unit_id=${stockUnit}` : ""}`);
  makeDialog(`<div class="identify-head"><h2 style="margin:0">Movimentações do estoque</h2>
      <button type="button" class="secondary small" data-close aria-label="Fechar">✕</button></div>
    <div class="table-wrap" style="max-height:65vh;overflow:auto"><table>
      <tr><th>Data</th><th>Item</th><th>Movimento</th><th class="num">Qtd.</th><th class="num">Saldo</th><th>Detalhe</th><th>Por</th></tr>
      ${rows.map((m) => `<tr><td class="nowrap">${fmtDateTime(m.created_at)}</td>
        <td>${esc(m.item)}${m.size ? ` (${esc(m.size)})` : ""}${units.length > 1 && !stockUnit ? `<div class="hint">${esc(m.unit)}</div>` : ""}</td>
        <td>${esc(m.type_label)}</td><td class="num ${m.quantity < 0 ? "bad-text" : ""}">${m.quantity > 0 ? "+" : ""}${m.quantity}</td>
        <td class="num">${m.balance}</td><td>${esc(m.person || "")}${m.person && m.note ? " · " : ""}${esc(m.note)}</td>
        <td>${esc(m.user)}</td></tr>`).join("") || `<tr><td class="hint">Nenhuma movimentação.</td></tr>`}
    </table></div>`, "form-dialog wide-dialog");
}

// ---------- Uniformes ----------

let uniSector = "";

async function renderUniforms(box) {
  box.innerHTML = `
    <div class="toolbar"><div class="filters" style="margin:0">
      <label>Setor <select id="uni-sector">${sectorOptions(uniSector)}</select></label>
      <label>Buscar <input id="uni-q" placeholder="Nome"></label></div>
      ${can("tecnico") ? `<div class="actions"><button id="uni-new">+ Entregar uniforme</button></div>` : ""}</div>
    <p class="hint">Peças de uniforme com cada colaborador, tamanhos cadastrados e a próxima troca prevista.</p>
    <div class="table-wrap"><table id="uni-table"></table></div>`;
  let rows = [];
  const draw = () => {
    const q = $("#uni-q", box).value.trim().toLowerCase();
    const list = rows.filter((p) => !q || p.name.toLowerCase().includes(q));
    $("#uni-table", box).innerHTML = list.length ? `
      <tr><th>Colaborador</th><th>Tamanhos</th><th>Peças em uso</th><th>Próxima troca</th><th></th></tr>
      ${list.map((p) => `<tr class="${p.overdue ? "row-bad" : ""}">
        <td><b>${esc(p.name)}</b><div class="hint">${esc(p.sector || "sem setor")} · ${esc(p.role || "")}</div></td>
        <td>${Object.entries(p.sizes).map(([k, v]) => `<span class="hint">${esc(SIZE_LABELS[k] || k)}</span> ${esc(v)}`).join(" · ") || `<span class="hint">não informados</span>`}</td>
        <td>${p.pieces.map((d) => `${d.quantity}× ${esc(d.item)}${d.size ? ` (${esc(d.size)})` : ""}`).join("<br>") || `<span class="hint">nenhuma</span>`}</td>
        <td>${p.next_change ? (p.overdue ? badge(`vencida ${fmtDate(p.next_change)}`, "bad") : fmtDate(p.next_change)) : "–"}</td>
        <td>${can("tecnico") ? `<div class="actions row-actions"><button class="small" data-give="${p.id}">Entregar</button>
          <button class="small secondary" data-sizes="${p.id}">Tamanhos</button></div>` : ""}</td></tr>`).join("")}`
      : `<tr><td class="hint">Nenhum colaborador ativo.</td></tr>`;
    $$("[data-give]", box).forEach((b) => b.addEventListener("click", async () => {
      const p = rows.find((x) => x.id === Number(b.dataset.give));
      if (await openDelivery({ person: p })) load();
    }));
    $$("[data-sizes]", box).forEach((b) => b.addEventListener("click", () => sizesDialog(rows.find((x) => x.id === Number(b.dataset.sizes)), load)));
  };
  const load = async () => {
    const params = new URLSearchParams();
    if (unitId()) params.set("unit_id", unitId());
    if (uniSector) params.set("sector_id", uniSector);
    rows = await api(`/api/ppe/uniforms?${params}`);
    draw();
  };
  $("#uni-sector", box).addEventListener("change", (e) => { uniSector = e.target.value; load(); });
  $("#uni-q", box).addEventListener("input", draw);
  $("#uni-new", box)?.addEventListener("click", async () => { if (await openDelivery()) load(); });
  await load();
}

const SIZE_FIELDS = [["camisa", "Camisa"], ["calca", "Calça"], ["jaleco", "Jaleco / macacão"], ["calcado", "Calçado"], ["luva", "Luva"]];

export function sizesDialog(p, after) {
  const d = makeDialog(`<form class="form" method="dialog"><h2 class="wide">Tamanhos – ${esc(p.name)}</h2>
    ${SIZE_FIELDS.map(([k, l]) => `<label>${l} <input name="${k}" maxlength="10" value="${esc(p.sizes?.[k] || "")}"
      placeholder="${k === "calcado" ? "40" : k === "calca" ? "42" : k === "luva" ? "9" : "M"}"></label>`).join("")}
    <div class="actions wide"><button type="submit">Salvar</button><button type="button" class="secondary" data-close>Cancelar</button></div></form>`);
  const f = d.querySelector("form");
  f.addEventListener("submit", async (e) => {
    e.preventDefault();
    const sizes = Object.fromEntries(SIZE_FIELDS.map(([k]) => [k, f[k].value.trim()]).filter(([, v]) => v));
    try { await api(`/api/ppe/people/${p.id}/sizes`, { method: "PUT", body: { sizes } }); d.close(); after?.(); }
    catch (err) { toast(esc(err.message), "danger"); }
  });
}

// ---------- Plano de substituição ----------

let planDays = 30;
let planSector = "";

async function renderPlan(box) {
  const params = new URLSearchParams({ days: planDays });
  if (unitId()) params.set("unit_id", unitId());
  if (planSector) params.set("sector_id", planSector);
  const plan = await api(`/api/ppe/replacement-plan?${params}`);
  box.innerHTML = `
    <div class="toolbar"><div class="filters" style="margin:0">
      <label>Horizonte <select id="pl-days">${[15, 30, 60, 90].map((n) => `<option value="${n}" ${n === planDays ? "selected" : ""}>Próximos ${n} dias</option>`).join("")}</select></label>
      <label>Setor <select id="pl-sector">${sectorOptions(planSector)}</select></label></div>
      <div class="actions"><button class="secondary" id="pl-print">Imprimir plano</button></div></div>
    <p class="hint">Trocas vencidas ou previstas até ${fmtDate(plan.until)} e EPIs exigidos pelo padrão do setor que o colaborador
      ainda não recebeu. A troca prevista vem do catálogo (troca a cada N dias) ou da data informada na entrega.</p>
    <div id="pl-print-area">
    ${plan.needs.length ? `<div class="card"><h3>Necessidade de itens (lista de compras)</h3>
      <div class="table-wrap"><table>
        <tr>${units.length > 1 && !unitId() ? "<th>Unidade</th>" : ""}<th>Item</th><th>Tam.</th><th class="num">Necessário</th><th class="num">Em estoque</th><th class="num">Comprar</th></tr>
        ${plan.needs.map((n) => `<tr class="${n.shortage ? "row-bad" : ""}">${units.length > 1 && !unitId() ? `<td>${esc(n.unit)}</td>` : ""}
          <td>${esc(n.item)}${n.item_id ? "" : ` <span class="hint">(não está no catálogo)</span>`}</td><td>${esc(n.size || "–")}</td>
          <td class="num">${n.quantity}</td><td class="num">${n.stock}</td><td class="num"><b>${n.shortage || "–"}</b></td></tr>`).join("")}
      </table></div></div>` : ""}
    ${plan.sectors.length ? plan.sectors.map((s) => `<div class="card epi-plan-sector">
      <h3>${esc(s.sector)}${units.length > 1 && !unitId() ? ` <span class="hint">${esc(s.unit)}</span>` : ""}
        <span class="hint">· ${s.overdue} vencida(s) · ${s.due} a vencer · ${s.missing} faltando</span></h3>
      <div class="table-wrap"><table>
        <tr><th>Colaborador</th><th>Troca</th><th>Faltando (padrão do setor)</th><th class="no-print"></th></tr>
        ${s.people.map((p) => `<tr class="${p.due.some((d) => d.overdue) ? "row-bad" : ""}">
          <td><b>${esc(p.name)}</b><div class="hint">${esc(p.role || "")}${p.shift ? ` · ${esc(p.shift)}` : ""}</div></td>
          <td>${p.due.map((d) => `${esc(d.item)}${d.size ? ` (${esc(d.size)})` : ""} ·
            ${d.overdue ? badge(`vencida ${fmtDate(d.valid_until)}`, "bad") : `<span class="hint">${fmtDate(d.valid_until)}</span>`}`).join("<br>") || "–"}</td>
          <td>${p.missing.map((m) => `${esc(m.requirement)}${m.item ? ` <span class="hint">→ ${esc(m.item)}</span>` : ` <span class="hint">(sem item no catálogo)</span>`}`).join("<br>") || "–"}</td>
          <td class="no-print">${can("tecnico") ? `<button class="small" data-plan-give="${p.id}">Entregar</button>` : ""}</td></tr>`).join("")}
      </table></div></div>`).join("") : `<div class="card"><p class="hint" style="margin:0">Nenhuma troca prevista nem EPI faltando neste período. ✓</p></div>`}
    </div>`;
  $("#pl-days", box).addEventListener("change", (e) => { planDays = Number(e.target.value); renderPlan(box); });
  $("#pl-sector", box).addEventListener("change", (e) => { planSector = e.target.value; renderPlan(box); });
  $("#pl-print", box).addEventListener("click", () => printArea(`Plano de substituição de EPI – até ${fmtDate(plan.until)}`, $("#pl-print-area", box).innerHTML));
  $$("[data-plan-give]", box).forEach((b) => b.addEventListener("click", async () => {
    const p = plan.sectors.flatMap((s) => s.people).find((x) => x.id === Number(b.dataset.planGive));
    const lines = [...p.due.filter((d) => d.item_id).map((d) => ({ item_id: d.item_id, size: d.size, reason: "troca" })),
      ...p.missing.filter((m) => m.item_id).map((m) => ({ item_id: m.item_id, reason: "primeira" }))];
    if (await openDelivery({ person: { id: p.id }, lines })) { renderPlan(box); loadSummary(); }
  }));
}

function printArea(title, html) {
  const w = window.open("", "_blank");
  if (!w) return toast("Permita pop-ups para imprimir.", "warn");
  w.document.write(`<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>${esc(title)}</title>
    <style>body{font:12px system-ui,sans-serif;color:#16191d;margin:16mm}h1{font-size:18px}h3{font-size:14px;margin:16px 0 6px}
    table{width:100%;border-collapse:collapse;margin-bottom:8px}th,td{border-bottom:1px solid #ccc;padding:4px 6px;text-align:left;vertical-align:top}
    .num{text-align:right}.hint{color:#5E6368}.no-print,button{display:none}.badge{font-weight:600}.card{break-inside:avoid}</style></head>
    <body><h1>${esc(title)}</h1><div class="hint">${esc(units.find((u) => u.id === unitId())?.name || "Todas as unidades")} · emitido em ${fmtDateTime(new Date().toISOString())}</div>
    ${html}<script>window.onload=()=>window.print()<\/script></body></html>`);
  w.document.close();
}

// ---------- Vencimento de CA ----------

let caDays = 60;

async function renderCA(box) {
  const r = await api(`/api/ppe/ca-report?days=${caDays}${unitId() ? `&unit_id=${unitId()}` : ""}`);
  box.innerHTML = `
    <div class="toolbar"><div class="filters" style="margin:0">
      <label>Avisar com <select id="ca-days">${[30, 60, 90, 180].map((n) => `<option value="${n}" ${n === caDays ? "selected" : ""}>${n} dias de antecedência</option>`).join("")}</select></label></div>
      <div class="actions"><a class="button secondary" href="${CA_LINK}" target="_blank" rel="noopener">Consultar CA no site do MTE</a>
        <button class="secondary" id="ca-print">Imprimir</button></div></div>
    <div class="stats">
      <div class="stat ${r.counts.vencido ? "stat-bad" : ""}"><b>${r.counts.vencido}</b><span>CA vencido</span></div>
      <div class="stat"><b>${r.counts.vence}</b><span>Vencendo em ${caDays} dias</span></div>
      <div class="stat ${r.counts.sem_ca ? "stat-bad" : ""}"><b>${r.counts.sem_ca}</b><span>EPI sem CA cadastrado</span></div>
      <div class="stat"><b>${r.counts.sem_validade}</b><span>Sem validade informada</span></div>
    </div>
    <p class="hint">NR-6: só pode ser comercializado e entregue EPI com CA válido. EPI comprado dentro da validade do CA pode ser usado
      até o fim da vida útil do lote; ao renovar a compra, confira o CA novo no site do MTE e atualize o Catálogo.</p>
    <div class="table-wrap" id="ca-area"><table>
      <tr><th>EPI</th><th>CA</th><th>Validade do CA</th><th>Situação</th><th class="num">Em estoque</th><th class="num">Em uso</th></tr>
      ${r.rows.map((i) => `<tr class="${["vencido", "sem_ca"].includes(i.ca_status) ? "row-bad" : ""}">
        <td><b>${esc(i.name)}</b>${i.manufacturer ? `<div class="hint">${esc(i.manufacturer)}</div>` : ""}</td>
        <td class="mono">${esc(i.ca || "–")}</td><td>${fmtDate(i.ca_valid_until)}</td><td>${caBadge(i.ca_status, i.ca_days)}</td>
        <td class="num">${i.stock}</td><td class="num">${i.in_use}</td></tr>`).join("") || `<tr><td class="hint">Nenhum EPI no catálogo.</td></tr>`}
    </table></div>`;
  $("#ca-days", box).addEventListener("change", (e) => { caDays = Number(e.target.value); renderCA(box); });
  $("#ca-print", box).addEventListener("click", () => printArea("Relatório de vencimento de CA", $("#ca-area", box).innerHTML));
}

// ---------- Catálogo ----------

async function renderCatalog(box) {
  const items = await api("/api/ppe/items?all=true");
  box.innerHTML = `
    <div class="toolbar"><p class="hint" style="margin:0">EPIs e uniformes fornecidos pela empresa, com o CA, a validade do CA
      e o prazo de troca.</p>${can("tecnico") ? `<div class="actions"><button id="cat-new">+ Novo item</button></div>` : ""}</div>
    <div class="table-wrap"><table>
      <tr><th>Item</th><th>Tipo</th><th>CA</th><th>Validade CA</th><th>Tamanhos</th><th>Troca</th><th></th></tr>
      ${items.map((i) => `<tr class="${i.active ? "" : "muted-row"}">
        <td><b>${esc(i.name)}</b>${i.manufacturer ? `<div class="hint">${esc(i.manufacturer)}</div>` : ""}${i.active ? "" : ` ${badge("desativado", "muted")}`}</td>
        <td>${CATEGORY[i.category]}${i.ppe_type ? `<div class="hint">câmera: ${esc(PPE_TYPES[i.ppe_type] || i.ppe_type)}</div>` : ""}</td>
        <td class="mono">${esc(i.ca || "–")}</td><td>${i.category === "epi" ? caBadge(i.ca_status, i.ca_days) : "–"}
          ${i.ca_valid_until ? `<div class="hint">${fmtDate(i.ca_valid_until)}</div>` : ""}</td>
        <td>${esc((i.sizes || []).join(", ") || "único")}</td>
        <td>${i.replacement_days ? `a cada ${i.replacement_days} dias` : "quando danificar"}</td>
        <td>${can("tecnico") ? `<div class="actions row-actions"><button class="small secondary" data-edit="${i.id}">Editar</button>
          ${i.active ? `<button class="small danger" data-del="${i.id}" title="Itens com entregas são só desativados">×</button>` : ""}</div>` : ""}</td></tr>`).join("")
        || `<tr><td class="hint">Nenhum item. Comece cadastrando os EPIs do padrão dos setores (capacete, óculos, botina...).</td></tr>`}
    </table></div>`;
  $("#cat-new", box)?.addEventListener("click", () => itemDialog(null, () => renderCatalog(box)));
  $$("[data-edit]", box).forEach((b) => b.addEventListener("click", () => itemDialog(items.find((i) => i.id === Number(b.dataset.edit)), () => renderCatalog(box))));
  $$("[data-del]", box).forEach((b) => b.addEventListener("click", async () => {
    const it = items.find((i) => i.id === Number(b.dataset.del));
    if (!confirm(`Remover "${it.name}" do catálogo? Se já tiver entregas, ele só é desativado (o histórico continua).`)) return;
    try { await api(`/api/ppe/items/${it.id}`, { method: "DELETE" }); renderCatalog(box); }
    catch (err) { toast(esc(err.message), "danger"); }
  }));
}

function itemDialog(it, after) {
  const d = makeDialog(`<form class="form" method="dialog">
    <h2 class="wide">${it ? "Editar item" : "Novo item"}</h2>
    <label class="wide">Nome <input name="name" required minlength="2" maxlength="120" value="${esc(it?.name || "")}"
      placeholder="Ex.: Capacete aba frontal classe B"></label>
    <label>Tipo <select name="category"><option value="epi">EPI</option><option value="uniforme" ${it?.category === "uniforme" ? "selected" : ""}>Uniforme</option></select></label>
    <label>Corresponde ao EPI da câmera <select name="ppe_type">${Object.entries(PPE_TYPES).map(([k, v]) =>
      `<option value="${k}" ${k === (it?.ppe_type || "") ? "selected" : ""}>${v}</option>`).join("")}</select></label>
    <label data-epi>Nº do CA <input name="ca" maxlength="20" value="${esc(it?.ca || "")}" placeholder="Ex.: 31469"></label>
    <label data-epi>Validade do CA <input type="date" name="ca_valid_until" value="${it?.ca_valid_until || ""}"></label>
    <label>Fabricante / modelo <input name="manufacturer" maxlength="120" value="${esc(it?.manufacturer || "")}"></label>
    <label>Tamanhos (separados por vírgula) <input name="sizes" value="${esc((it?.sizes || []).join(", "))}" placeholder="P, M, G, GG ou 38, 39, 40"></label>
    <label>Troca a cada (dias) <input type="number" name="replacement_days" min="1" max="3650" value="${it?.replacement_days || ""}"
      placeholder="vazio = quando danificar"></label>
    <label>Unidade de medida <select name="unit_label">${["un", "par", "cx", "kit"].map((u) => `<option ${u === (it?.unit_label || "un") ? "selected" : ""}>${u}</option>`).join("")}</select></label>
    <label>Custo unitário (R$) <input type="number" name="unit_cost" min="0" step="0.01" value="${it?.unit_cost ?? ""}"></label>
    ${it ? `<label class="check wide"><input type="checkbox" name="active" ${it.active ? "checked" : ""}> Ativo (aparece nas entregas e no estoque)</label>` : ""}
    <p class="hint wide">O CA e a validade estão no próprio EPI e no site do MTE (Consulta CA). Uniforme não tem CA.</p>
    <div class="actions wide"><button type="submit">Salvar</button><button type="button" class="secondary" data-close>Cancelar</button></div>
  </form>`);
  const f = d.querySelector("form");
  const toggle = () => $$("[data-epi]", d).forEach((x) => { x.hidden = f.category.value !== "epi"; });
  f.category.addEventListener("change", toggle);
  toggle();
  f.addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = { name: f.name.value, category: f.category.value, ppe_type: f.ppe_type.value,
      ca: f.category.value === "epi" ? f.ca.value : "", ca_valid_until: f.category.value === "epi" ? f.ca_valid_until.value || null : null,
      manufacturer: f.manufacturer.value, sizes: f.sizes.value.split(","), replacement_days: Number(f.replacement_days.value) || null,
      unit_label: f.unit_label.value, unit_cost: f.unit_cost.value === "" ? null : Number(f.unit_cost.value),
      active: it ? f.active.checked : true };
    try {
      await api(it ? `/api/ppe/items/${it.id}` : "/api/ppe/items", { method: it ? "PUT" : "POST", body });
      d.close();
      toast("Item salvo.", "ok", 2500);
      after();
      loadSummary();
    } catch (err) { toast(esc(err.message), "danger"); }
  });
}

// ---------- Guia ----------

const TABS = [
  ["entregas", "Entregas e fichas", renderDeliveries],
  ["estoque", "Estoque", renderStock],
  ["uniformes", "Uniformes", renderUniforms],
  ["plano", "Plano de substituição", renderPlan],
  ["ca", "Vencimento de CA", renderCA],
  ["catalogo", "Catálogo", renderCatalog],
];

async function open() {
  $$("#epi-tabs [data-tab]", el).forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  try {
    await TABS.find((t) => t[0] === tab)[2]($("#epi-body", el));
  } catch (err) { toast(esc(err.message), "danger"); }
}

export async function show(element) {
  el = element;
  el.innerHTML = `<h2>EPI e uniformes</h2><div class="stats epi-stats" id="epi-stats"></div>
    <div class="subtabs" id="epi-tabs">${TABS.map(([id, label]) => `<button data-tab="${id}">${label}</button>`).join("")}</div>
    <div id="epi-body"></div>`;
  $$("#epi-tabs [data-tab]", el).forEach((b) => b.addEventListener("click", () => { tab = b.dataset.tab; open(); }));
  [units, sectors] = await Promise.all([api("/api/units"), api("/api/sectors")]);
  if (stockUnit && session.unitId && stockUnit !== session.unitId) stockUnit = session.unitId;
  await Promise.all([loadSummary(), open()]);
}

export function openTab(id) {
  tab = id;
  if (el && el.classList.contains("active")) open();
}

