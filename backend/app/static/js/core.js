// Núcleo compartilhado: API, sessão, rótulos e utilitários de interface.

export const TYPE_LABELS = {
  ppe_missing: "EPI ausente",
  restricted_zone: "Zona restrita",
  fire_smoke: "Fogo / fumaça",
  max_people: "Excesso de pessoas",
};
export const PPE_ITEMS = ["helmet", "vest", "glasses", "gloves", "mask"];
export const PPE_LABELS = { helmet: "capacete", vest: "colete", glasses: "óculos", gloves: "luvas", mask: "máscara" };
export const STATUS_LABELS = { nova: "Nova", confirmada: "Em tratamento", descartada: "Falso alarme", encerrada: "Encerrada" };
export const CLASS_LABELS = {
  ato_inseguro: "Ato inseguro",
  condicao_insegura: "Condição insegura",
  quase_acidente: "Quase acidente",
  acidente: "Acidente",
  nao_classificada: "Não classificada",
};
export const ROLE_LABELS = { operador: "Operador", tecnico: "Técnico de segurança", gestor: "Gestor", admin: "Administrador" };
export const ROLES = ["operador", "tecnico", "gestor", "admin"];
export const HEALTH_LABELS = {
  ok: "Normal", offline: "Sem sinal", escura: "Imagem escura",
  obstruida: "Obstruída/desfocada", congelada: "Imagem congelada",
};
export const ACTION_STATUS = { aberta: "Aberta", concluida: "Concluída", cancelada: "Cancelada" };

export const $ = (sel, el = document) => el.querySelector(sel);
export const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

// ---------- Sessão ----------
export const session = { user: null };

export function getToken() {
  try { return localStorage.getItem("vigia_session") || ""; } catch { return ""; }
}
export function setToken(t) {
  try { t ? localStorage.setItem("vigia_session", t) : localStorage.removeItem("vigia_session"); } catch { /* sem storage */ }
}
export const withToken = (url) => {
  const t = getToken();
  return t ? `${url}${url.includes("?") ? "&" : "?"}token=${encodeURIComponent(t)}` : url;
};
export const can = (minRole) => !!session.user && ROLES.indexOf(session.user.role) >= ROLES.indexOf(minRole);

let onUnauthorized = () => {};
export function setUnauthorizedHandler(fn) { onUnauthorized = fn; }

export async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (getToken()) headers.Authorization = `Bearer ${getToken()}`;
  let body = options.body;
  if (body && !(body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(body);
  }
  const resp = await fetch(path, { ...options, headers, body });
  if (resp.status === 401 && !path.startsWith("/api/auth/login")) {
    setToken("");
    onUnauthorized();
    throw new Error("Sessão expirada. Entre novamente.");
  }
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    const detail = Array.isArray(err.detail) ? err.detail.map((d) => d.msg).join("; ") : err.detail;
    throw new Error(detail || `Erro ${resp.status}`);
  }
  return resp.status === 204 ? null : resp.json();
}

// ---------- Interface ----------
export function toast(html, kind = "info", ms = 6000) {
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.innerHTML = html;
  $("#toasts").append(el);
  setTimeout(() => el.remove(), ms);
}

export function beep() {
  try {
    const ctx = new AudioContext();
    const osc = ctx.createOscillator();
    osc.frequency.value = 880;
    osc.connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + 0.25);
  } catch { /* navegador sem áudio */ }
}

export const fmtDateTime = (iso) => new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
export const fmtDate = (iso) => (iso ? new Date(`${String(iso).slice(0, 10)}T12:00:00`).toLocaleDateString("pt-BR") : "–");
export const fmtPct = (v, digits = 0) => (v == null ? "–" : `${(v * 100).toFixed(digits).replace(".", ",")}%`);
export const isoDate = (d) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);

export function badge(text, kind = "") {
  return `<span class="badge ${esc(kind)}">${esc(text)}</span>`;
}

export function statusBadge(status) {
  return badge(STATUS_LABELS[status] || status, `st-${status}`);
}

export function healthBadge(health) {
  if (!health) return badge("Aguardando imagem", "muted");
  const icon = health === "ok" ? "●" : "▲";
  return badge(`${icon} ${HEALTH_LABELS[health] || health}`, health === "ok" ? "good" : "bad");
}

export function userOptions(users, selected, emptyLabel = "Sem responsável") {
  return `<option value="">${esc(emptyLabel)}</option>` + users.filter((u) => u.active || u.id === selected)
    .map((u) => `<option value="${u.id}" ${u.id === selected ? "selected" : ""}>${esc(u.name)}</option>`).join("");
}

export function applyRoleVisibility(root = document) {
  $$("[data-min-role]", root).forEach((el) => { el.hidden = !can(el.dataset.minRole); });
}

// Tooltip compartilhado pelos gráficos e pelo mapa de calor
export function bindTooltip(container) {
  let tip = $("#chart-tip");
  if (!tip) {
    tip = document.createElement("div");
    tip.id = "chart-tip";
    tip.className = "chart-tip";
    tip.hidden = true;
    document.body.append(tip);
  }
  container.addEventListener("pointermove", (e) => {
    const target = e.target.closest("[data-tip]");
    if (!target) { tip.hidden = true; return; }
    tip.innerHTML = target.dataset.tip;
    tip.hidden = false;
    const x = Math.min(e.clientX + 14, window.innerWidth - tip.offsetWidth - 8);
    tip.style.left = `${x}px`;
    tip.style.top = `${e.clientY + 14}px`;
  });
  container.addEventListener("pointerleave", () => { tip.hidden = true; });
}
