// Guia Relatórios e auditoria: relatórios de segurança, medidas/termos e auditoria.

import { $, $$, api, badge, can, esc, fmtDate, fmtDateTime, isoDate, scoped, toast, withToken } from "../core.js";
import * as auditoria from "./auditoria.js";

const FREQ = { mensal: "Mensal (dia 1, referente ao mês anterior)", semanal: "Semanal (segunda-feira, semana anterior)",
  desligado: "Desligado" };
const MEASURE_STATUS = { pendente_aprovacao: ["aguardando aprovação", "warn"], aplicada: ["aplicada", "good"], cancelada: ["cancelada", "muted"] };
const ACK_KIND = { pendente: "warn", assinada: "good", impressa: "good", recusada: "bad" };

let el;
let active = null;

function presets() {
  const today = new Date();
  const firstThis = new Date(today.getFullYear(), today.getMonth(), 1);
  const lastPrev = new Date(firstThis - 86400000);
  const firstPrev = new Date(lastPrev.getFullYear(), lastPrev.getMonth(), 1);
  const ago30 = new Date(today - 29 * 86400000);
  return {
    mes_anterior: ["Mês anterior", isoDate(firstPrev), isoDate(lastPrev)],
    mes_atual: ["Mês atual", isoDate(firstThis), isoDate(today)],
    ultimos_30: ["Últimos 30 dias", isoDate(ago30), isoDate(today)],
  };
}

// ---------- Relatórios ----------

async function renderReports(box) {
  const cameras = await api("/api/cameras");
  const p = presets();
  box.innerHTML = `
    <div class="card">
      <h3>Período</h3>
      <form id="rep-period" class="filters" style="margin:0;align-items:flex-end">
        <div class="tabs" style="margin:0">${Object.entries(p).map(([k, [l]], i) =>
          `<button type="button" class="small ${i ? "secondary" : ""}" data-preset="${k}">${l}</button>`).join("")}</div>
        <label>De <input type="date" name="start" value="${p.mes_anterior[1]}"></label>
        <label>Até <input type="date" name="end" value="${p.mes_anterior[2]}"></label>
        <label>Câmera <select name="camera_id"><option value="">Todas</option>
          ${cameras.map((c) => `<option value="${c.id}">${esc(c.name)}</option>`).join("")}</select></label>
      </form>
    </div>
    <div class="report-cards">
      <div class="card"><h3>Relatório completo</h3>
        <p class="hint">Indicadores, gráficos, plano de ação e ocorrências relevantes, com campos para a análise do SESMT e assinaturas.
          Abre para revisão e impressão ou PDF.</p>
        <button type="button" data-act="full">Gerar relatório completo</button></div>
      <div class="card"><h3>PDF rápido</h3>
        <p class="hint">O mesmo PDF enviado automaticamente por e-mail: pronto para baixar e anexar.</p>
        <button type="button" class="secondary" data-act="pdf">Baixar PDF</button></div>
      <div class="card"><h3>Planilha de ocorrências</h3>
        <p class="hint">Todas as ocorrências do período em CSV (abre no Excel): data, turno, câmera, área, tipo, situação,
          classificação, pessoa identificada e ações.</p>
        <button type="button" class="secondary" data-act="csv">Baixar planilha (CSV)</button></div>
      ${can("gestor") ? `<div class="card"><h3>Enviar por e-mail</h3><div id="rep-email"><p class="hint">Carregando…</p></div></div>` : ""}
    </div>`;

  const f = $("#rep-period", box);
  const query = () => {
    const params = new URLSearchParams({ start: f.start.value, end: f.end.value });
    if (f.camera_id.value) params.set("camera_id", f.camera_id.value);
    return params;
  };
  $$("[data-preset]", box).forEach((b) => b.addEventListener("click", () => {
    const [, start, end] = p[b.dataset.preset];
    f.start.value = start;
    f.end.value = end;
    $$("[data-preset]", box).forEach((x) => x.classList.toggle("secondary", x !== b));
  }));
  box.querySelector("[data-act=full]").addEventListener("click", () => window.open(`relatorio.html?${query()}`, "_blank"));
  box.querySelector("[data-act=pdf]").addEventListener("click", () => { location.href = withToken(scoped(`/api/reports/pdf?${query()}`)); });
  box.querySelector("[data-act=csv]").addEventListener("click", () => { location.href = withToken(scoped(`/api/reports/events.csv?${query()}`)); });

  if (!can("gestor")) return;
  const s = await api("/api/system/status");
  $("#rep-email", box).innerHTML = `
    <dl class="kv">
      <dt>Envio automático</dt><dd>${esc(FREQ[s.report_frequency] || s.report_frequency)}, às ${s.report_hour}h</dd>
      <dt>Destinatários</dt><dd>${s.report_recipients.length ? esc(s.report_recipients.join(", "))
        : "<span class='bad-text'>nenhum – configure em Parâmetros › Alertas</span>"}</dd>
      <dt>E-mail (SMTP)</dt><dd>${s.email_configured ? "configurado" : "<span class='bad-text'>não configurado – Parâmetros › E-mail</span>"}</dd>
      <dt>Último período enviado</dt><dd>${s.report_last ? s.report_last.split(":").map(fmtDate).join(" a ") : "–"}</dd>
    </dl>
    <label>Para (opcional) <input name="to" id="rep-to" placeholder="vazio = destinatários configurados"></label>
    <div class="actions" style="margin-top:10px"><button type="button" id="rep-send" ${s.email_configured ? "" : "disabled"}>Enviar relatório do período</button></div>`;
  $("#rep-send", box).addEventListener("click", async (e) => {
    e.target.disabled = true;
    try {
      const recipients = $("#rep-to", box).value.split(",").map((x) => x.trim()).filter(Boolean);
      await api("/api/system/report-email", { method: "POST",
        body: { start: f.start.value || null, end: f.end.value || null, recipients: recipients.length ? recipients : null } });
      toast("Relatório enviado por e-mail.", "ok");
    } catch (err) { toast(esc(err.message), "danger"); }
    e.target.disabled = false;
  });
}

// ---------- Medidas e termos ----------

async function renderMeasures(box) {
  box.innerHTML = `
    <form id="mea-filters" class="filters">
      <label>Situação <select name="status"><option value="">Todas</option><option value="aplicada">Aplicadas</option>
        <option value="pendente_aprovacao">Aguardando aprovação</option><option value="cancelada">Canceladas</option></select></label>
      <label>Medida <select name="type"><option value="">Todas</option><option value="orientacao">Orientação</option>
        <option value="treinamento">Treinamento</option><option value="advertencia">Advertência</option><option value="rh">RH</option></select></label>
      <label>Ciência <select name="ack"><option value="">Todas</option><option value="pendente">Pendente</option>
        <option value="assinada">Assinada</option><option value="impressa">Termo impresso</option><option value="recusada">Recusou</option></select></label>
      <label>Buscar <input name="q" placeholder="Nome ou nº do termo"></label>
    </form>
    <p class="hint">Medidas aplicadas a partir das ocorrências. Acesso registrado na auditoria ao abrir o histórico de cada pessoa.</p>
    <div class="table-wrap"><table id="mea-table"></table></div>`;
  const all = await api("/api/measures");
  const f = $("#mea-filters", box);
  const draw = () => {
    const q = f.q.value.trim().toLowerCase();
    const rows = all.filter((m) => (!f.status.value || m.status === f.status.value) && (!f.type.value || m.type === f.type.value)
      && (!f.ack.value || m.ack === f.ack.value)
      && (!q || m.number.toLowerCase().includes(q) || (m.person_name || "").toLowerCase().includes(q)));
    $("#mea-table", box).innerHTML = rows.length ? `
      <tr><th>Termo</th><th>Data</th><th>Pessoa</th><th>Medida</th><th>Situação</th><th>Ciência</th><th>Ocorrência</th><th></th></tr>
      ${rows.map((m) => `<tr>
        <td class="mono">${esc(m.number)}</td><td>${fmtDateTime(m.created_at)}</td>
        <td><a href="#cadastros" data-history="${m.person_id}">${esc(m.person_name || "–")}</a></td>
        <td>${esc(m.label)}${m.training_name ? `<div class="hint">${esc(m.training_name)}</div>` : ""}</td>
        <td>${badge(MEASURE_STATUS[m.status][0], MEASURE_STATUS[m.status][1])}</td>
        <td>${m.status === "aplicada" ? badge(m.ack_label, ACK_KIND[m.ack]) : "–"}</td>
        <td>${m.event_id ? `<a href="#ocorrencia-${m.event_id}">#${m.event_id}</a>` : "–"}</td>
        <td><a class="small-link" href="termo.html?id=${m.id}" target="_blank">Termo</a></td></tr>`).join("")}`
      : `<tr><td class="hint">Nenhuma medida com esses filtros.</td></tr>`;
  };
  f.addEventListener("input", draw);
  f.addEventListener("submit", (e) => e.preventDefault());
  draw();
}

// ---------- Container ----------

const TABS = [
  { id: "relatorios", label: "Relatórios", role: "tecnico", render: renderReports },
  { id: "medidas", label: "Medidas e termos", role: "tecnico", render: renderMeasures },
  { id: "auditoria", label: "Auditoria", role: "admin", render: (box) => auditoria.show(box) },
];

async function open(id) {
  active = id;
  $$(".subtabs button", el).forEach((b) => b.classList.toggle("active", b.dataset.tab === id));
  try {
    await TABS.find((t) => t.id === id).render($("#rel-body", el));
  } catch (err) { toast(esc(err.message), "danger"); }
}

export async function show(element) {
  el = element;
  const tabs = TABS.filter((t) => can(t.role));
  el.innerHTML = `
    <h2>Relatórios e auditoria</h2>
    <div class="subtabs" role="tablist">${tabs.map((t) => `<button type="button" role="tab" data-tab="${t.id}">${t.label}</button>`).join("")}</div>
    <div id="rel-body"></div>`;
  $$(".subtabs button", el).forEach((b) => b.addEventListener("click", () => open(b.dataset.tab)));
  await open(tabs.some((t) => t.id === active) ? active : tabs[0].id);
}

export function openTab(id) {
  active = id;
  if (el && el.classList.contains("active")) open(id);
}
