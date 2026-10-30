import { drawHeatmap } from "../charts.js";
import { $, api, bindTooltip, can, esc, isoDate, toast, withToken } from "../core.js";
import { kpis, renderCharts } from "../indicators-render.js";

let el;
let cameras = [];
const state = { days: "30", start: "", end: "", camera_id: "" };

function period() {
  if (state.days === "custom") return { start: state.start, end: state.end };
  const end = new Date();
  const start = new Date();
  start.setDate(end.getDate() - Number(state.days) + 1);
  return { start: isoDate(start), end: isoDate(end) };
}

function query() {
  const { start, end } = period();
  const params = new URLSearchParams();
  if (start) params.set("start", start);
  if (end) params.set("end", end);
  if (state.camera_id) params.set("camera_id", state.camera_id);
  return params;
}

async function loadHeatmap() {
  const camId = $("#heat-camera", el).value;
  const canvas = $("#heat-canvas", el);
  const img = $("#heat-img", el);
  if (!camId) return;
  const params = query();
  params.set("camera_id", camId);
  const { points } = await api(`/api/reports/heatmap?${params}`);
  $("#heat-count", el).textContent = `${points.length} registro(s) de desvio nesta câmera`;
  img.onload = () => { img.hidden = false; drawHeatmap(canvas, points); };
  img.onerror = () => { img.hidden = true; drawHeatmap(canvas, points); };
  img.src = withToken(`/api/cameras/${camId}/frame?t=${Date.now()}`);
}

async function load() {
  const s = await api(`/api/reports/summary?${query()}`);
  const heatSelect = $("#heat-camera", el);
  if (!heatSelect.dataset.chosen && s.by_camera.length) heatSelect.value = s.by_camera[0].camera_id;
  $("#kpis", el).innerHTML = kpis(s);
  renderCharts(el, s);
  await loadHeatmap();
}

export async function show(element) {
  el = element;
  cameras = await api("/api/cameras");
  el.innerHTML = `
    <div class="toolbar">
      <h2>Indicadores de segurança</h2>
      ${can("tecnico") ? `<button id="report-btn">Gerar relatório (PDF)</button>` : ""}
    </div>
    <form id="ind-filters" class="filters">
      <label>Período
        <select name="days">
          <option value="7">Últimos 7 dias</option>
          <option value="30" selected>Últimos 30 dias</option>
          <option value="90">Últimos 90 dias</option>
          <option value="custom">Personalizado</option>
        </select>
      </label>
      <label data-custom hidden>De <input type="date" name="start"></label>
      <label data-custom hidden>Até <input type="date" name="end"></label>
      <label>Câmera
        <select name="camera_id"><option value="">Todas</option>
          ${cameras.map((c) => `<option value="${c.id}">${esc(c.name)}</option>`).join("")}</select>
      </label>
    </form>

    <div id="kpis" class="stats stats-6"></div>

    <div class="grid-2">
      <div class="card"><h3>Desvios por dia</h3><div data-chart="by_day" class="chart"></div></div>
      <div class="card"><h3>Conformidade de EPI por dia</h3><div data-chart="compliance_day" class="chart"></div></div>
      <div class="card"><h3>Desvios por turno</h3><div data-chart="by_shift"></div></div>
      <div class="card"><h3>Conformidade de EPI por turno</h3><div data-chart="compliance_shift"></div></div>
      <div class="card"><h3>Desvios por área</h3><div data-chart="by_location"></div></div>
      <div class="card"><h3>Conformidade de EPI por câmera <small class="hint">(piores primeiro)</small></h3>
        <div data-chart="compliance_camera"></div></div>
      <div class="card"><h3>Desvios por tipo</h3><div data-chart="by_type"></div></div>
      <div class="card"><h3>Desvios por classificação</h3><div data-chart="by_class"></div></div>
      <div class="card wide"><h3>Desvios por hora do dia</h3><div data-chart="by_hour" class="chart"></div></div>
      <div class="card wide">
        <div class="toolbar"><h3>Mapa de calor dos desvios</h3>
          <select id="heat-camera">${cameras.map((c) => `<option value="${c.id}">${esc(c.name)}</option>`).join("")}</select>
        </div>
        <p class="hint">Onde os desvios acontecem na imagem (posição dos pés das pessoas). Áreas mais
          intensas indicam onde reforçar sinalização, barreiras ou treinamento. <span id="heat-count"></span></p>
        <div class="zone-wrap heat-wrap"><img id="heat-img" alt="" hidden><canvas id="heat-canvas"></canvas></div>
      </div>
    </div>`;

  bindTooltip(el);
  const f = $("#ind-filters", el);
  f.days.value = state.days;
  f.camera_id.value = state.camera_id;
  f.addEventListener("change", () => {
    Object.assign(state, { days: f.days.value, start: f.start.value, end: f.end.value, camera_id: f.camera_id.value });
    el.querySelectorAll("[data-custom]").forEach((l) => { l.hidden = state.days !== "custom"; });
    if (state.camera_id) $("#heat-camera", el).value = state.camera_id;
    if (state.days !== "custom" || (state.start && state.end)) load().catch((err) => toast(esc(err.message), "danger"));
  });
  $("#heat-camera", el).addEventListener("change", (e) => {
    e.target.dataset.chosen = "1";
    loadHeatmap();
  });
  $("#report-btn", el)?.addEventListener("click", () => {
    window.open(`relatorio.html?${query()}`, "_blank");
  });
  await load();
}

let resizeTimer;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => { if (el?.classList.contains("active")) load(); }, 300);
});
