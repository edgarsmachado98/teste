// Dimensionamento e capacidade: situação atual (dados reais) e planejamento de implantação.

import { fmtBytes } from "./config-form.js";
import { $, api, badge, esc, fmtPct, toast } from "./core.js";

const FIELDS = [
  // [nome, rótulo, tipo, opções/limites, dica]
  ["cameras", "Câmeras", "number", { min: 1, max: 2000 }],
  ["events_per_camera_day", "Ocorrências por câmera/dia", "number", { min: 0, step: 0.5 },
    "Típico: 5 a 40. Use o valor medido no piloto."],
  ["retention_days", "Retenção de fotos e clipes", "number", { min: 1, max: 3650, suffix: "dias" }],
  ["event_retention_days", "Retenção dos registros", "number", { min: 1, max: 7300, suffix: "dias" }],
  ["storage_mode", "Armazenamento", "select", [["sem_nas", "Só disco local"], ["espelho", "Local + NAS (espelho)"],
    ["principal", "NAS principal + cache local"]]],
  ["local_days", "Cache local (modo principal)", "number", { min: 1, max: 3650, suffix: "dias" }],
  ["raid", "RAID do NAS", "select", [["raid1", "RAID 1 (2 discos, espelhamento)"], ["raid5", "RAID 5 (tolera 1 falha)"],
    ["raid6", "RAID 6 (tolera 2 falhas) – recomendado"], ["raid10", "RAID 10 (desempenho)"]]],
  ["headroom", "Folga desejada", "select", [["0.2", "20% livre"], ["0.3", "30% livre (recomendado)"], ["0.4", "40% livre"]]],
  ["clip_before", "Clipe: segundos antes", "number", { min: 0, max: 30, suffix: "s" }],
  ["clip_after", "Clipe: segundos depois", "number", { min: 0, max: 30, suffix: "s" }],
  ["analysis_fps", "Análise da IA", "number", { min: 0.5, max: 30, step: 0.5, suffix: "quadros/s" }],
  ["models", "Modelos de IA simultâneos", "number", { min: 1, max: 5 }, "Ex.: 2 = pessoas + EPI."],
  ["model_size", "Tamanho do modelo", "select", [["n", "Nano (mais rápido)"], ["s", "Small (mais preciso)"], ["m", "Medium"]]],
  ["stream_mbps", "Fluxo por câmera para a IA", "number", { min: 0.1, max: 50, step: 0.5, suffix: "Mbps" },
    "Use o sub-stream (720p, 1–2 Mbps)."],
  ["frame_kb", "Tamanho médio de um quadro do clipe", "number", { min: 1, max: 2000, suffix: "KB" }],
  ["snapshot_kb", "Tamanho médio da foto", "number", { min: 1, max: 5000, suffix: "KB" }],
  ["backup_keep", "Backups locais guardados", "number", { min: 1, max: 365 }],
  ["nas_backup_keep", "Backups guardados no NAS", "number", { min: 1, max: 1000 }],
  ["continuous", "Dimensionar também gravação contínua (NVR)", "checkbox"],
  ["continuous_mbps", "Gravação contínua por câmera", "number", { min: 0.5, max: 50, step: 0.5, suffix: "Mbps" }],
  ["continuous_days", "Dias de gravação contínua", "number", { min: 1, max: 3650, suffix: "dias" }],
  ["continuous_codec", "Codec", "select", [["h265", "H.265"], ["h264", "H.264"]]],
];

const num = (v, d) => v.toLocaleString("pt-BR", { minimumFractionDigits: d, maximumFractionDigits: d });
const days = (n) => (n > 3650 ? "mais de 10 anos" : `${n.toLocaleString("pt-BR")} dias`);

let root;
let state;
let lastPlan = null;

function input([name, label, type, opts = {}, hint = ""], values) {
  const v = values[name];
  if (type === "checkbox") {
    return `<label class="check wide"><input type="checkbox" name="${name}" ${v ? "checked" : ""}> ${esc(label)}</label>`;
  }
  const control = type === "select"
    ? `<select name="${name}">${opts.map(([k, l]) => `<option value="${k}" ${String(v) === k ? "selected" : ""}>${esc(l)}</option>`).join("")}</select>`
    : `<input type="number" name="${name}" value="${esc(v)}" ${opts.min != null ? `min="${opts.min}"` : ""}
        ${opts.max != null ? `max="${opts.max}"` : ""} step="${opts.step || 1}">`;
  const dataCont = name.startsWith("continuous_") ? "data-cont" : "";
  return `<label ${dataCont}>${esc(label)}${opts.suffix ? `<span class="with-suffix">${control}<span>${esc(opts.suffix)}</span></span>` : control}
    ${hint ? `<small class="hint">${esc(hint)}</small>` : ""}</label>`;
}

function readForm(form) {
  const out = {};
  for (const [name, , type] of FIELDS) {
    const el = form.elements[name];
    out[name] = type === "checkbox" ? el.checked : type === "number" ? Number(el.value) : el.value;
  }
  out.headroom = Number(out.headroom);
  return out;
}

function itemsTable(items, total, rec, kind) {
  const recText = kind === "local"
    ? (rec.size_gb ? `SSD de <b>${rec.size_gb >= 1024 ? `${rec.size_gb / 1024} TB` : `${rec.size_gb} GB`}</b>` : esc(rec.note || ""))
    : (rec.bays ? `NAS de <b>${rec.bays} baias</b> com <b>${rec.disks} discos de ${rec.disk_tb} TB</b> em ${rec.raid.toUpperCase()}
        (${fmtBytes(rec.usable_bytes)} úteis)` : esc(rec.note || ""));
  return `<table class="compact">
    ${items.map((i) => `<tr><td>${esc(i.label)}${i.note ? ` <span class="hint">(${esc(i.note)})</span>` : ""}</td>
      <td class="num">${fmtBytes(i.bytes)}</td></tr>`).join("")}
    <tr class="total"><td>Total previsto</td><td class="num">${fmtBytes(total)}</td></tr>
  </table><p class="rec">Recomendado: ${recText}</p>`;
}

function renderPlan(res) {
  const c = res.compute;
  $("#cap-result", root).innerHTML = `
    <div class="cap-summary">
      <div class="stat"><b>${fmtBytes(res.per_event_bytes)}</b><span>por ocorrência (foto + clipe)</span></div>
      <div class="stat"><b>${Math.round(res.events_per_day).toLocaleString("pt-BR")}</b><span>ocorrências por dia</span></div>
      <div class="stat"><b>${fmtBytes(res.daily_bytes)}</b><span>de evidências por dia</span></div>
      <div class="stat"><b>${Math.round(c.inferences_per_second)}</b><span>inferências de IA por segundo</span></div>
    </div>
    ${res.warnings.map((w) => `<div class="warn-box">▲ ${esc(w)}</div>`).join("")}
    <div class="grid-2">
      <div><h4>Computador do VigIA (disco local)</h4>${itemsTable(res.local_items, res.local_total, res.local_recommended, "local")}</div>
      ${res.nas_items.length ? `<div><h4>Storage de rede (NAS)</h4>${itemsTable(res.nas_items, res.nas_total, res.nas_recommended, "nas")}</div>` : ""}
      <div><h4>Processamento</h4>
        <table class="compact">
          ${c.options.map((o) => `<tr><td>${esc(o.label)}</td><td class="num">${o.usage > 5 ? "acima de 500%" : fmtPct(o.usage)} da capacidade</td>
            <td>${o.ok ? badge("atende", "good") : badge("insuficiente", "bad")}</td></tr>`).join("")}
        </table>
        <p class="rec">Recomendado: <b>${esc(c.suggested || `${c.servers_needed} servidores com GPU alta`)}</b>,
          ${c.cpu_cores} núcleos de CPU e <b>${c.ram_gb} GB</b> de memória.</p>
        <p class="hint">"Atende" = até 70% da capacidade estimada, deixando margem. Confirme no piloto.</p>
      </div>
      <div><h4>Rede</h4>
        <table class="compact">
          <tr><td>Câmeras → computador do VigIA</td><td class="num">${num(res.network.inbound_mbps, 0)} Mbps</td></tr>
          <tr><td>VigIA → NAS (pico estimado)</td><td class="num">${num(res.network.nas_mbps, 1)} Mbps</td></tr>
        </table>
        <p class="rec">Recomendado: interface de <b>${esc(res.network.recommendation)}</b>; câmeras em VLAN separada.</p>
        ${res.continuous ? `<p class="hint"><b>Gravação contínua:</b> ${fmtBytes(res.continuous.per_camera_day_bytes)} por câmera/dia,
          ${fmtBytes(res.continuous.total_bytes)} no total. ${esc(res.continuous.note)}</p>` : ""}
      </div>
    </div>
    <div class="actions"><button type="button" id="cap-print" class="secondary">Imprimir dimensionamento</button></div>`;
  $("#cap-print", root).addEventListener("click", printPlan);
}

async function calculate() {
  const form = $("#cap-form", root);
  form.querySelectorAll("[data-cont]").forEach((l) => { l.hidden = !form.continuous.checked; });
  try {
    lastPlan = { inputs: readForm(form), result: await api("/api/config/capacity/plan", { method: "POST", body: readForm(form) }) };
    renderPlan(lastPlan.result);
  } catch (err) {
    $("#cap-result", root).innerHTML = `<div class="warn-box">${esc(err.message)}</div>`;
  }
}

function renderCurrent() {
  const { measured: m, projection: p, usage: u, nas } = state;
  const fits = (ok) => (ok ? badge("✔ cabe", "good") : badge("▲ não cabe", "bad"));
  $("#cap-current", root).innerHTML = p.message ? `<p class="hint">${esc(p.message)}</p>` : `
    <div class="cap-summary">
      <div class="stat"><b>${m.events_per_day}</b><span>ocorrências/dia (últimos ${m.days_observed} dias)</span></div>
      <div class="stat"><b>${fmtBytes(m.avg_event_bytes)}</b><span>por ocorrência (média real)</span></div>
      <div class="stat"><b>${fmtBytes(p.daily_bytes)}</b><span>de evidências por dia</span></div>
      <div class="stat"><b>${p.days_until_alert == null ? "estável" : days(p.days_until_alert)}</b>
        <span>${p.days_until_alert == null ? "o uso já atingiu o regime da retenção" : `até o disco local passar de ${u.limits.disk}%`}</span></div>
    </div>
    <table class="compact">
      <tr><th></th><th>Uso previsto com a retenção atual</th><th>Capacidade</th><th></th><th>Retenção máxima que cabe</th></tr>
      <tr><td>Disco local (${p.mode === "principal" ? `cache de ${p.local_days} dias` : `${p.retention_days} dias`})</td>
        <td class="num">${fmtBytes(p.steady_local_bytes)}</td><td class="num">${fmtBytes(u.disk_total)}</td>
        <td>${fits(p.local_fits)}</td><td class="num">${days(p.local_max_days)}</td></tr>
      ${p.steady_nas_bytes != null ? `<tr><td>NAS (${p.retention_days} dias)</td><td class="num">${fmtBytes(p.steady_nas_bytes)}</td>
        <td class="num">${fmtBytes(nas.total_bytes)}</td><td>${fits(p.nas_fits)}</td>
        <td class="num">${days(p.nas_max_days)}</td></tr>` : ""}
    </table>
    <p class="hint">Considera o limite de alerta de disco (${u.limits.disk}%) e o espaço já ocupado por outros arquivos.
      Amostra: ${m.sampled_events} ocorrências${m.avg_frame_kb ? `; quadro médio ${m.avg_frame_kb} KB, foto média ${m.avg_snapshot_kb} KB` : ""}.</p>`;
}

export async function mountCapacity(container) {
  root = container;
  state = await api("/api/config/capacity");
  const values = { ...state.defaults, headroom: String(state.defaults.headroom) };
  const hasMeasured = Object.keys(state.measured_inputs).length > 0;
  root.innerHTML = `
    <div class="tabs">
      <button type="button" class="small" data-cap="current">Situação atual (dados reais)</button>
      <button type="button" class="small secondary" data-cap="plan">Planejar implantação</button>
    </div>
    <div data-pane="current"><div id="cap-current"></div></div>
    <div data-pane="plan" hidden>
      <p class="hint">Estimativa para a proposta de cada cliente. As premissas de tamanho de imagem e de desempenho da
        IA são médias: depois do piloto, use os valores medidos.</p>
      ${hasMeasured ? `<button type="button" id="cap-use-measured" class="small secondary">Usar os valores medidos nesta instalação</button>` : ""}
      <form id="cap-form" class="form cap-form">${FIELDS.map((f) => input(f, values)).join("")}</form>
      <div id="cap-result"></div>
    </div>`;
  root.querySelectorAll("[data-cap]").forEach((btn) => btn.addEventListener("click", () => {
    root.querySelectorAll("[data-cap]").forEach((b) => b.classList.toggle("secondary", b !== btn));
    root.querySelectorAll("[data-pane]").forEach((p) => { p.hidden = p.dataset.pane !== btn.dataset.cap; });
  }));
  const form = $("#cap-form", root);
  let timer;
  form.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(calculate, 300); });
  $("#cap-use-measured", root)?.addEventListener("click", () => {
    for (const [k, v] of Object.entries(state.measured_inputs)) form.elements[k].value = v;
    toast("Premissas substituídas pelos valores medidos.", "ok", 2500);
    calculate();
  });
  renderCurrent();
  await calculate();
}

function printPlan() {
  if (!lastPlan) return;
  const { inputs, result } = lastPlan;
  const labels = Object.fromEntries(FIELDS.map(([n, l, , opts]) => [n, [l, opts]]));
  const show = (name, value) => {
    const [label, opts] = labels[name];
    const text = Array.isArray(opts) ? (opts.find(([k]) => String(k) === String(value))?.[1] ?? value)
      : typeof value === "boolean" ? (value ? "sim" : "não") : `${value}${opts?.suffix ? ` ${opts.suffix}` : ""}`;
    return `<tr><td>${esc(label)}</td><td>${esc(text)}</td></tr>`;
  };
  const shown = Object.entries(inputs).filter(([k]) => (inputs.continuous || !k.startsWith("continuous_"))
    && (k !== "local_days" || inputs.storage_mode === "principal")
    && (!["raid", "nas_backup_keep"].includes(k) || inputs.storage_mode !== "sem_nas"));
  const w = window.open("", "_blank");
  w.document.write(`<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>Dimensionamento – VigIA</title>
    <style>
      body{font-family:system-ui,sans-serif;color:#16191d;margin:24px;font-size:13px}
      h1{font-size:20px;margin:0 0 4px} h2{font-size:15px;border-bottom:1px solid #dde1e6;padding-bottom:4px;margin-top:22px}
      h4{margin:12px 0 6px} table{border-collapse:collapse;width:100%} td,th{border-bottom:1px solid #eee;padding:4px 6px;text-align:left}
      .num{text-align:right} .total td{font-weight:700} .hint{color:#5b636e} .rec{margin:6px 0 0}
      .badge{font-weight:600} .grid-2{display:grid;grid-template-columns:1fr 1fr;gap:18px}
      .cap-summary{display:grid;grid-template-columns:repeat(4,1fr);gap:8px} .stat{border:1px solid #dde1e6;border-radius:6px;padding:8px}
      .stat b{display:block;font-size:17px} .warn-box{border:1px solid #d97706;background:#fff8eb;padding:8px;border-radius:6px;margin:8px 0}
      .actions{display:none}
    </style></head><body>
    <h1>Dimensionamento de recursos – VigIA</h1>
    <p class="hint">Emitido em ${new Date().toLocaleString("pt-BR")}. Estimativa para orientar a compra; valide com o piloto.</p>
    <p contenteditable="true" style="border:1px dashed #f0b45a;padding:4px">Cliente / unidade: (clique para preencher)</p>
    <h2>Premissas</h2><table>${shown.map(([k, v]) => show(k, v)).join("")}</table>
    <h2>Resultado</h2>${$("#cap-result", root).innerHTML}
    <script>setTimeout(() => print(), 300)<\/script></body></html>`);
  w.document.close();
}
