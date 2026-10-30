"use strict";

const TYPE_LABELS = {
  ppe_missing: "EPI ausente",
  restricted_zone: "Zona restrita",
  fire_smoke: "Fogo / fumaça",
  max_people: "Excesso de pessoas",
};
const PPE_ITEMS = ["helmet", "vest", "glasses", "gloves", "mask"];
const PPE_LABELS = { helmet: "capacete", vest: "colete", glasses: "óculos", gloves: "luvas", mask: "máscara" };

const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

// ---------- Autenticação simples por token ----------
function getToken() {
  try { return localStorage.getItem("vigia_token") || ""; } catch { return ""; }
}
function setToken(t) {
  try { localStorage.setItem("vigia_token", t); } catch { /* sem storage */ }
}
// O iniciador (vigia.py) abre o painel com ?token=... – guardamos e limpamos a URL.
(() => {
  const params = new URLSearchParams(location.search);
  if (params.has("token")) {
    setToken(params.get("token"));
    history.replaceState(null, "", location.pathname + location.hash);
  }
})();

const withToken = (url) => {
  const t = getToken();
  return t ? `${url}${url.includes("?") ? "&" : "?"}token=${encodeURIComponent(t)}` : url;
};

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (getToken()) headers.Authorization = `Bearer ${getToken()}`;
  if (options.body && !(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(options.body);
  }
  const resp = await fetch(path, { ...options, headers });
  if (resp.status === 401) {
    const t = prompt("Informe o token de acesso do VigIA:");
    if (t) { setToken(t); return api(path, options); }
    throw new Error("não autorizado");
  }
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    const detail = Array.isArray(err.detail) ? err.detail.map((d) => d.msg).join("; ") : err.detail;
    throw new Error(detail || `Erro ${resp.status}`);
  }
  return resp.status === 204 ? null : resp.json();
}

function toast(html, kind = "info", ms = 6000) {
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.innerHTML = html;
  $("#toasts").append(el);
  setTimeout(() => el.remove(), ms);
}

function beep() {
  try {
    const ctx = new AudioContext();
    const osc = ctx.createOscillator();
    osc.frequency.value = 880;
    osc.connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + 0.25);
  } catch { /* navegador sem áudio */ }
}

// ---------- Abas ----------
let currentTab = "painel";
$$("nav button").forEach((btn) =>
  btn.addEventListener("click", () => {
    currentTab = btn.dataset.tab;
    $$("nav button").forEach((b) => b.classList.toggle("active", b === btn));
    $$(".tab").forEach((t) => t.classList.toggle("active", t.id === `tab-${currentTab}`));
    refreshTab();
  })
);

function refreshTab() {
  if (currentTab === "painel") { loadEvents(); loadStats(); }
  if (currentTab === "aovivo") renderLive();
  if (currentTab === "cameras") loadCameras();
  if (currentTab === "regras") loadRules();
}

// ---------- Painel ----------
const fmtDate = (iso) => new Date(iso).toLocaleString("pt-BR");

function eventCard(ev) {
  return `
    <article class="event sev-${esc(ev.severity)} st-${esc(ev.status)}" id="evento-${ev.id}">
      ${ev.image_url
        ? `<img src="${esc(withToken(ev.image_url))}" alt="Evidência" data-full="${esc(withToken(ev.image_url))}">`
        : `<div class="noimg">sem imagem</div>`}
      <div class="info">
        <strong>${esc(ev.message)}</strong>
        <span>${esc(ev.camera_name)} · ${esc(TYPE_LABELS[ev.type] || ev.type)}</span>
        <span>${fmtDate(ev.created_at)} · severidade <b>${esc(ev.severity)}</b></span>
        <div class="actions">
          ${ev.status === "nova"
            ? `<button data-status="confirmada" data-id="${ev.id}">Confirmar</button>
               <button data-status="descartada" data-id="${ev.id}" class="secondary">Falso alarme</button>`
            : `<em>${esc(ev.status)}</em>`}
        </div>
      </div>
    </article>`;
}

async function loadEvents() {
  const status = $("#filter-status").value;
  const events = await api(`/api/events?limit=100${status ? `&status=${status}` : ""}`);
  $("#events").innerHTML = events.length ? events.map(eventCard).join("") : `<p class="hint">Nenhuma ocorrência.</p>`;
}

async function loadStats() {
  const s = await api("/api/stats");
  $("#onboarding").hidden = s.cameras > 0;
  $("#st-pending").textContent = s.pending;
  $("#st-ppe").textContent = s.last_24h.ppe_missing || 0;
  $("#st-zone").textContent = s.last_24h.restricted_zone || 0;
  $("#st-fire").textContent = s.last_24h.fire_smoke || 0;
}

$("#filter-status").addEventListener("change", loadEvents);
$("#events").addEventListener("click", async (e) => {
  const btn = e.target.closest("button[data-status]");
  if (btn) {
    await api(`/api/events/${btn.dataset.id}`, { method: "PATCH", body: { status: btn.dataset.status } });
    loadEvents(); loadStats();
    return;
  }
  const img = e.target.closest("img[data-full]");
  if (img) {
    $("#viewer-img").src = img.dataset.full;
    $("#viewer").showModal();
  }
});

// ---------- Tempo real ----------
function connectWs() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(withToken(`${proto}://${location.host}/ws`));
  ws.onopen = () => $("#conn").className = "conn on";
  ws.onclose = () => {
    $("#conn").className = "conn off";
    setTimeout(connectWs, 3000);
  };
  ws.onmessage = (msg) => {
    const data = JSON.parse(msg.data);
    if (data.kind !== "event") return;
    const ev = data.event;
    beep();
    toast(`<b>🚨 ${esc(ev.message)}</b><br>${esc(ev.camera_name)} – ${fmtDate(ev.created_at)}`,
      ev.severity === "critica" || ev.severity === "alta" ? "danger" : "warn");
    if (currentTab === "painel") { loadEvents(); loadStats(); }
  };
}

// ---------- Ao vivo ----------
let cameras = [];
let liveTimer = null;

async function renderLive() {
  cameras = await api("/api/cameras");
  $("#live").innerHTML = cameras.filter((c) => c.enabled).map((c) => `
    <figure>
      <img data-cam="${c.id}" alt="${esc(c.name)}">
      <figcaption>${esc(c.name)} <small>${esc(c.location)}</small></figcaption>
    </figure>`).join("") || `<p class="hint">Cadastre câmeras na aba Câmeras.</p>`;
  updateLiveFrames();
}

function updateLiveFrames() {
  $$("#live img[data-cam]").forEach((img) => {
    img.src = withToken(`/api/cameras/${img.dataset.cam}/frame?t=${Date.now()}`);
  });
}

clearInterval(liveTimer);
liveTimer = setInterval(() => currentTab === "aovivo" && updateLiveFrames(), 2000);

// ---------- Câmeras ----------
async function loadCameras() {
  cameras = await api("/api/cameras");
  $("#cameras-table").innerHTML = `
    <tr><th>Nome</th><th>Local</th><th>Fonte</th><th>Ativa</th><th></th></tr>
    ${cameras.map((c) => `
      <tr>
        <td>${esc(c.name)}</td><td>${esc(c.location)}</td>
        <td class="mono">${esc(c.source.replace(/\/\/[^@/]*@/, "//***@"))}</td>
        <td>${c.enabled ? "sim" : "não"}</td>
        <td><button data-edit="${c.id}" class="secondary">Editar</button>
            <button data-del="${c.id}" class="danger">Excluir</button></td>
      </tr>`).join("")}`;
}

$("#cameras-table").addEventListener("click", async (e) => {
  const edit = e.target.dataset.edit, del = e.target.dataset.del;
  if (edit) {
    const c = cameras.find((x) => x.id == edit);
    const f = $("#camera-form");
    f.id.value = c.id; f.name.value = c.name; f.location.value = c.location;
    f.source.value = c.source; f.enabled.checked = c.enabled;
  }
  if (del && confirm("Excluir câmera, suas regras e ocorrências?")) {
    await api(`/api/cameras/${del}`, { method: "DELETE" });
    loadCameras();
  }
});

$("#camera-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  const body = { name: f.name.value, location: f.location.value, source: f.source.value, enabled: f.enabled.checked };
  try {
    await api(f.id.value ? `/api/cameras/${f.id.value}` : "/api/cameras",
      { method: f.id.value ? "PUT" : "POST", body });
    f.reset(); f.id.value = "";
    toast("Câmera salva.", "ok", 2500);
    loadCameras();
  } catch (err) { toast(esc(err.message), "danger"); }
});
$("#camera-form").addEventListener("reset", (e) => { e.target.id.value = ""; });
$("#use-webcam").addEventListener("click", () => {
  const f = $("#camera-form");
  if (!f.name.value) f.name.value = "Webcam";
  f.source.value = "0";
  f.requestSubmit();
});

function openTab(name) {
  $(`nav button[data-tab=${name}]`).click();
}
$("#go-cameras").addEventListener("click", () => openTab("cameras"));

// ---------- Regras ----------
let rules = [];
let zone = [];

async function loadRules() {
  [cameras, rules] = await Promise.all([api("/api/cameras"), api("/api/rules")]);
  const sel = $("#rule-form").camera_id;
  const prev = sel.value;
  sel.innerHTML = cameras.map((c) => `<option value="${c.id}">${esc(c.name)}</option>`).join("");
  if (prev) sel.value = prev;
  loadZoneImage();
  const camName = (id) => cameras.find((c) => c.id === id)?.name || id;
  $("#rules-table").innerHTML = `
    <tr><th>Regra</th><th>Câmera</th><th>Tipo</th><th>Horário</th><th>Severidade</th><th>Ativa</th><th></th></tr>
    ${rules.map((r) => `
      <tr>
        <td>${esc(r.name)}</td><td>${esc(camName(r.camera_id))}</td>
        <td>${esc(TYPE_LABELS[r.type])}${r.type === "ppe_missing" ? ` (${esc((r.params.required || []).map((i) => PPE_LABELS[i] || i).join(", "))})` : ""}</td>
        <td>${r.start_hour == null ? "sempre" : `${r.start_hour}h–${r.end_hour}h`}</td>
        <td>${esc(r.severity)}</td><td>${r.enabled ? "sim" : "não"}</td>
        <td><button data-edit="${r.id}" class="secondary">Editar</button>
            <button data-del="${r.id}" class="danger">Excluir</button></td>
      </tr>`).join("")}`;
}

function toggleParams() {
  const type = $("#rule-form").type.value;
  $$("#rule-form .param").forEach((el) => el.hidden = el.dataset.for !== type);
}
$("#rule-form").type.addEventListener("change", toggleParams);
$("#rule-form").camera_id.addEventListener("change", loadZoneImage);

function loadZoneImage() {
  const id = $("#rule-form").camera_id.value;
  const img = $("#zone-img");
  if (!id) return;
  img.onerror = () => { img.hidden = true; drawZone(); };
  img.onload = () => { img.hidden = false; drawZone(); };
  img.src = withToken(`/api/cameras/${id}/frame?t=${Date.now()}`);
}

function drawZone() {
  const canvas = $("#zone-canvas");
  canvas.width = canvas.clientWidth || 640;
  canvas.height = canvas.clientHeight || 360;
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (!zone.length) return;
  ctx.beginPath();
  zone.forEach(([x, y], i) => (i ? ctx.lineTo : ctx.moveTo).call(ctx, x * canvas.width, y * canvas.height));
  ctx.closePath();
  ctx.fillStyle = "rgba(239, 68, 68, 0.25)";
  ctx.strokeStyle = "#ef4444";
  ctx.lineWidth = 2;
  ctx.fill(); ctx.stroke();
  zone.forEach(([x, y]) => {
    ctx.beginPath();
    ctx.arc(x * canvas.width, y * canvas.height, 4, 0, Math.PI * 2);
    ctx.fillStyle = "#ef4444"; ctx.fill();
  });
}

$("#zone-canvas").addEventListener("click", (e) => {
  const rect = e.target.getBoundingClientRect();
  const r = (v) => Math.round(Math.min(1, Math.max(0, v)) * 1000) / 1000;
  zone.push([r((e.clientX - rect.left) / rect.width), r((e.clientY - rect.top) / rect.height)]);
  drawZone();
});
$("#zone-clear").addEventListener("click", () => { zone = []; drawZone(); });
window.addEventListener("resize", drawZone);

$("#rules-table").addEventListener("click", async (e) => {
  const edit = e.target.dataset.edit, del = e.target.dataset.del;
  if (edit) {
    const r = rules.find((x) => x.id == edit);
    const f = $("#rule-form");
    f.id.value = r.id; f.camera_id.value = r.camera_id; f.name.value = r.name; f.type.value = r.type;
    f.severity.value = r.severity; f.min_confidence.value = r.min_confidence;
    f.min_duration.value = r.min_duration; f.cooldown.value = r.cooldown;
    f.start_hour.value = r.start_hour ?? ""; f.end_hour.value = r.end_hour ?? "";
    f.enabled.checked = r.enabled;
    PPE_ITEMS.forEach((item) => f[`req_${item}`].checked = (r.params.required || []).includes(item));
    f.max_people.value = r.params.max_people ?? 2;
    zone = r.zone.map((p) => [...p]);
    toggleParams(); loadZoneImage();
    f.scrollIntoView({ behavior: "smooth" });
  }
  if (del && confirm("Excluir regra?")) {
    await api(`/api/rules/${del}`, { method: "DELETE" });
    loadRules();
  }
});

$("#rule-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  const num = (v) => (v === "" ? null : Number(v));
  const params = {};
  if (f.type.value === "ppe_missing") params.required = PPE_ITEMS.filter((i) => f[`req_${i}`].checked);
  if (f.type.value === "max_people") params.max_people = Number(f.max_people.value);
  const body = {
    camera_id: Number(f.camera_id.value), name: f.name.value, type: f.type.value, severity: f.severity.value,
    zone, params, min_confidence: Number(f.min_confidence.value), min_duration: Number(f.min_duration.value),
    cooldown: Number(f.cooldown.value), start_hour: num(f.start_hour.value), end_hour: num(f.end_hour.value),
    enabled: f.enabled.checked,
  };
  if (body.type === "ppe_missing" && !params.required.length) return toast("Selecione ao menos um EPI.", "warn");
  if ((body.start_hour == null) !== (body.end_hour == null)) return toast("Informe as duas horas ou nenhuma.", "warn");
  try {
    await api(f.id.value ? `/api/rules/${f.id.value}` : "/api/rules",
      { method: f.id.value ? "PUT" : "POST", body });
    f.reset(); zone = []; drawZone();
    toast("Regra salva.", "ok", 2500);
    loadRules();
  } catch (err) { toast(esc(err.message), "danger"); }
});
$("#rule-form").addEventListener("reset", (e) => {
  e.target.id.value = ""; zone = [];
  setTimeout(() => { toggleParams(); drawZone(); });
});

// ---------- Início ----------
toggleParams();
connectWs();
refreshTab();
setInterval(() => currentTab === "painel" && loadStats(), 30000);
