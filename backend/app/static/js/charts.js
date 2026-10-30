// Gráficos leves (SVG/HTML), sem bibliotecas externas: o sistema roda offline na planta.
// Uma série por gráfico → cor única (--series-1); o título nomeia a série, sem legenda.

import { esc } from "./core.js";

const SVGNS = "http://www.w3.org/2000/svg";

function niceMax(v) {
  if (v <= 0) return 1;
  const pow = 10 ** Math.floor(Math.log10(v));
  const n = v / pow;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * pow;
}

function svg(width, height) {
  const el = document.createElementNS(SVGNS, "svg");
  el.setAttribute("viewBox", `0 0 ${width} ${height}`);
  el.setAttribute("width", width);
  el.setAttribute("height", height);
  el.classList.add("chart-svg");
  return el;
}

function add(parent, tag, attrs, text) {
  const el = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  if (text != null) el.textContent = text;
  parent.append(el);
  return el;
}

// Barra vertical com topo arredondado (4px) apoiada na linha de base
function columnPath(x, y, w, h, r = 4) {
  r = Math.min(r, w / 2, h);
  return `M${x},${y + h} V${y + r} Q${x},${y} ${x + r},${y} H${x + w - r} Q${x + w},${y} ${x + w},${y + r} V${y + h} Z`;
}

/**
 * Colunas (séries temporais de contagem).
 * data: [{label, value, tip}] ; opts: {height, every (rótulo a cada N), format}
 */
export function columnChart(el, data, opts = {}) {
  const width = Math.max(el.clientWidth, 280);
  const height = opts.height || 200;
  const m = { top: 12, right: 8, bottom: 24, left: 34 };
  const iw = width - m.left - m.right;
  const ih = height - m.top - m.bottom;
  const max = niceMax(Math.max(...data.map((d) => d.value), 0));
  const s = svg(width, height);

  for (let i = 0; i <= 4; i++) {
    const v = (max / 4) * i;
    const y = m.top + ih - (v / max) * ih;
    add(s, "line", { x1: m.left, x2: width - m.right, y1: y, y2: y, class: i ? "grid" : "baseline" });
    if (Number.isInteger(v)) add(s, "text", { x: m.left - 6, y: y + 4, class: "axis", "text-anchor": "end" }, v);
  }

  const step = iw / data.length;
  const bw = Math.max(Math.min(step - 2, 28), 1);
  const every = opts.every || Math.ceil(data.length / 10);
  data.forEach((d, i) => {
    const x = m.left + i * step + (step - bw) / 2;
    const h = (d.value / max) * ih;
    if (h > 0) add(s, "path", { d: columnPath(x, m.top + ih - h, bw, h), class: "mark" });
    if (i % every === 0) {
      add(s, "text", { x: x + bw / 2, y: height - 6, class: "axis", "text-anchor": "middle" }, d.label);
    }
    // área de interação maior que a marca
    add(s, "rect", { x: m.left + i * step, y: m.top, width: step, height: ih, class: "hit", "data-tip": d.tip });
  });
  el.replaceChildren(s);
}

/**
 * Linha de percentual (0..1) com lacunas onde não há dado.
 * data: [{label, value|null, tip}]
 */
export function percentLine(el, data, opts = {}) {
  const width = Math.max(el.clientWidth, 280);
  const height = opts.height || 200;
  const m = { top: 12, right: 12, bottom: 24, left: 40 };
  const iw = width - m.left - m.right;
  const ih = height - m.top - m.bottom;
  const values = data.map((d) => d.value).filter((v) => v != null);
  const lo = values.length ? Math.max(0, Math.floor((Math.min(...values) - 0.05) * 10) / 10) : 0;
  const s = svg(width, height);
  const y = (v) => m.top + ih - ((v - lo) / (1 - lo)) * ih;
  const x = (i) => m.left + (data.length === 1 ? iw / 2 : (i / (data.length - 1)) * iw);

  for (let i = 0; i <= 4; i++) {
    const v = lo + ((1 - lo) / 4) * i;
    add(s, "line", { x1: m.left, x2: width - m.right, y1: y(v), y2: y(v), class: i ? "grid" : "baseline" });
    add(s, "text", { x: m.left - 6, y: y(v) + 4, class: "axis", "text-anchor": "end" }, `${Math.round(v * 100)}%`);
  }

  let path = "";
  let pen = false;
  data.forEach((d, i) => {
    if (d.value == null) { pen = false; return; }
    path += `${pen ? "L" : "M"}${x(i)},${y(d.value)} `;
    pen = true;
  });
  if (path) add(s, "path", { d: path, class: "line" });
  data.forEach((d, i) => {
    if (d.value != null && (values.length < 40)) add(s, "circle", { cx: x(i), cy: y(d.value), r: 4, class: "dot" });
  });

  const every = opts.every || Math.ceil(data.length / 8);
  const step = data.length > 1 ? iw / (data.length - 1) : iw;
  data.forEach((d, i) => {
    if (i % every === 0) add(s, "text", { x: x(i), y: height - 6, class: "axis", "text-anchor": "middle" }, d.label);
    add(s, "rect", { x: x(i) - step / 2, y: m.top, width: step, height: ih, class: "hit", "data-tip": d.tip });
  });
  if (!values.length) {
    add(s, "text", { x: width / 2, y: height / 2, class: "empty", "text-anchor": "middle" }, opts.empty || "Sem dados no período");
  }
  el.replaceChildren(s);
}

/**
 * Barras horizontais em HTML (categorias: câmeras, áreas, turnos, tipos).
 * rows: [{label, sub, value, display, tip}] ; opts: {max}
 */
export function barList(el, rows, opts = {}) {
  if (!rows.length) {
    el.innerHTML = `<p class="hint">${esc(opts.empty || "Sem dados no período.")}</p>`;
    return;
  }
  const max = opts.max ?? Math.max(...rows.map((r) => r.value), 1);
  el.innerHTML = `<div class="barlist">${rows.map((r) => `
    <div class="barrow" data-tip="${esc(r.tip || `${r.label}: ${r.display ?? r.value}`)}">
      <div class="barlabel">${esc(r.label)}${r.sub ? `<small>${esc(r.sub)}</small>` : ""}</div>
      <div class="bartrack"><div class="barfill" style="width:${Math.max((r.value / max) * 100, r.value ? 1.5 : 0)}%"></div></div>
      <div class="barvalue">${esc(r.display ?? r.value)}</div>
    </div>`).join("")}</div>`;
}

/**
 * Mapa de calor sobre a imagem da câmera: um só tom, do transparente ao intenso.
 */
export function drawHeatmap(canvas, points) {
  const w = (canvas.width = canvas.clientWidth || 640);
  const h = (canvas.height = canvas.clientHeight || 360);
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, w, h);
  if (!points.length) return;

  // 1) acumula intensidade em tons de cinza
  const acc = document.createElement("canvas");
  acc.width = w; acc.height = h;
  const actx = acc.getContext("2d");
  const radius = Math.max(w, h) * 0.06;
  const alpha = Math.min(0.35, 4 / Math.sqrt(points.length + 1));
  for (const [px, py] of points) {
    const g = actx.createRadialGradient(px * w, py * h, 0, px * w, py * h, radius);
    g.addColorStop(0, `rgba(0,0,0,${alpha})`);
    g.addColorStop(1, "rgba(0,0,0,0)");
    actx.fillStyle = g;
    actx.fillRect(px * w - radius, py * h - radius, radius * 2, radius * 2);
  }
  // 2) colore: um só matiz (laranja), opacidade proporcional à intensidade
  const img = actx.getImageData(0, 0, w, h);
  const d = img.data;
  for (let i = 0; i < d.length; i += 4) {
    const a = d[i + 3];
    if (!a) continue;
    const t = a / 255;
    d[i] = 255; d[i + 1] = Math.round(170 - 110 * t); d[i + 2] = Math.round(60 - 40 * t);
    d[i + 3] = Math.round(40 + 190 * t);
  }
  ctx.putImageData(img, 0, 0);
}
