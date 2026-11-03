import {
  $, $$, ROLE_LABELS, api, can, setUnit, applyRoleVisibility, beep, esc, fmtDateTime, getToken, session, setToken,
  setUnauthorizedHandler, toast, withToken,
} from "./core.js";
import { openEvent, refreshIfOpen } from "./event-detail.js";
import * as acoes from "./views/acoes.js";
import * as aovivo from "./views/aovivo.js";
import * as cadastros from "./views/cadastros.js";
import * as indicadores from "./views/indicadores.js";
import * as ocorrencias from "./views/ocorrencias.js";
import * as painel from "./views/painel.js";
import * as regras from "./views/regras.js";
import * as configuracoes from "./views/configuracoes.js";
import * as parametros from "./views/parametros.js";
import * as relatorios from "./views/relatorios.js";

const VIEWS = { cadastros, painel, ocorrencias, acoes, indicadores, aovivo, regras, relatorios,
  parametros, configuracoes };
let current = null;

// ---------- Acesso ----------
async function showAuth() {
  $("#app").hidden = true;
  $("#auth").hidden = false;
  const { needs_setup } = await fetch("/api/setup").then((r) => r.json());
  $("#setup-form").hidden = !needs_setup;
  $("#login-form").hidden = needs_setup;
  $(needs_setup ? "#setup-form input" : "#login-form input").focus();
}

async function startSession(data) {
  setToken(data.token);
  session.user = data.user;
  await showApp();
}

$("#setup-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  try {
    await startSession(await api("/api/setup", {
      method: "POST", body: { name: f.name.value, email: f.email.value, password: f.password.value },
    }));
    toast("Administrador criado. Comece cadastrando uma câmera.", "ok");
  } catch (err) { toast(esc(err.message), "danger"); }
});

$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  try {
    await startSession(await api("/api/auth/login", {
      method: "POST", body: { email: f.email.value, password: f.password.value },
    }));
    f.reset();
  } catch (err) { toast(esc(err.message), "danger"); }
});

setUnauthorizedHandler(() => {
  session.user = null;
  showAuth();
});

async function showApp() {
  $("#auth").hidden = true;
  $("#app").hidden = false;
  renderUserButton();
  loadMeta();
  applyRoleVisibility();
  connectWs();
  route();
}

// ---------- Cabeçalho: usuário, cliente/unidade e turno ----------
function initials(name) {
  const parts = (name || "?").trim().split(/\s+/);
  return ((parts[0]?.[0] || "") + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase();
}

function renderUserButton() {
  const u = session.user;
  $("#user-menu").innerHTML = `<span class="initials" aria-hidden="true">${esc(initials(u.name))}</span>
    <span class="who">${esc(u.name.split(" ")[0])}<small>${esc(ROLE_LABELS[u.role])}</small></span>`;
  $("#user-menu").setAttribute("aria-label", `Minha conta – ${u.name}`);
}

let meta = null;
// O turno vem do servidor (fuso da planta), não do relógio deste computador.
function currentShift() {
  const s = (meta?.shifts || []).find((x) => x.name === meta.shift);
  return s ? `${s.name} · ${String(s.start).padStart(2, "0")}h–${String(s.end).padStart(2, "0")}h` : meta?.shift || "";
}
function renderMeta() {
  if (!meta) return;
  const units = meta.units || [];
  // Unidade guardada que não existe mais (ou não há escolha a fazer): volta para todas
  if (session.unitId && (units.length < 2 || !units.some((u) => u.id === session.unitId))) setUnit(null);
  $("#company-name").hidden = !meta.company_name;
  $("#company-name").textContent = meta.company_name || "";
  const sel = $("#header-unit");
  sel.innerHTML = (units.length > 1 ? `<option value="">Todas as unidades</option>` : "")
    + units.map((u) => `<option value="${u.id}">${esc(u.name)}</option>`).join("")
    + (can("tecnico") ? `<option value="__new">＋ Cadastrar unidade…</option>` : "");
  sel.value = session.unitId ? String(session.unitId) : (units.length > 1 ? "" : String(units[0]?.id ?? ""));
  $("#site-pill").classList.toggle("filtering", !!session.unitId);
  $("#shift-chip").textContent = currentShift();
}

/** Troca a unidade exibida e recarrega a tela atual já filtrada. */
$("#header-unit").addEventListener("change", (e) => {
  const value = e.target.value;
  if (value === "__new") {
    renderMeta(); // desfaz a escolha na caixa
    cadastros.openTab("setores");
    location.hash = "#cadastros";
    toast("Cadastre a nova unidade em <b>Setores e padrões → + Unidade</b>.", "info", 6000);
    return;
  }
  setUnit(value && (meta.units || []).length > 1 ? Number(value) : null);
  renderMeta();
  const name = (meta.units || []).find((u) => u.id === session.unitId)?.name;
  toast(name ? `Mostrando a unidade <b>${esc(name)}</b>.` : "Mostrando todas as unidades.", "ok", 2500);
  rerender();
});

window.addEventListener("units-changed", () => loadMeta());

function rerender() {
  if (!current || !VIEWS[current]) return;
  VIEWS[current].leave?.();
  VIEWS[current].show($(`#view-${current}`)).catch((err) => toast(esc(err.message), "danger"));
}
async function loadMeta() {
  try { meta = await api("/api/meta"); session.meta = meta; renderMeta(); } catch { /* cabeçalho é opcional */ }
}
setInterval(() => { if (session.user) loadMeta(); }, 5 * 60000);

// ---------- Tema ----------
function applyTheme(theme) {
  if (theme === "dark") document.documentElement.dataset.theme = "dark";
  else delete document.documentElement.dataset.theme;
  try { localStorage.setItem("vigia-theme", theme); } catch { /* navegador sem armazenamento */ }
  $$("[data-theme-set]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.themeSet === theme)));
  window.dispatchEvent(new Event("themechange"));
}
$$("[data-theme-set]").forEach((b) => b.addEventListener("click", () => applyTheme(b.dataset.themeSet)));
$$("[data-theme-set]").forEach((b) => b.setAttribute("aria-pressed",
  String(b.dataset.themeSet === (document.documentElement.dataset.theme === "dark" ? "dark" : "light"))));

// ---------- Conta ----------
$("#user-menu").addEventListener("click", () => {
  $("#account-name").textContent = session.user.name;
  $("#account-role").textContent = `${session.user.email} · ${ROLE_LABELS[session.user.role]}`;
  $("#account-dialog").showModal();
});
$("#password-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  try {
    await api("/api/auth/password", {
      method: "PUT", body: { current_password: f.current_password.value, new_password: f.new_password.value },
    });
    f.reset();
    $("#account-dialog").close();
    toast("Senha alterada.", "ok", 2500);
  } catch (err) { toast(esc(err.message), "danger"); }
});
$("#logout").addEventListener("click", async () => {
  try { await api("/api/auth/logout", { method: "POST" }); } catch { /* já expirada */ }
  setToken("");
  session.user = null;
  ws?.close();
  $("#account-dialog").close();
  showAuth();
});

// Botões "Cancelar/Fechar" de todos os diálogos
document.addEventListener("click", (e) => {
  if (e.target.matches("[data-close]")) e.target.closest("dialog").close();
  const hist = e.target.closest("[data-history]");
  if (hist) {
    e.preventDefault();
    hist.closest("dialog")?.close();
    cadastros.openHistory(Number(hist.dataset.history));
    location.hash = "#cadastros";
  }
  const img = e.target.closest("img[data-full]");
  if (img) {
    $("#viewer-img").src = img.dataset.full;
    $("#viewer").showModal();
  }
});

// ---------- Navegação (pelo endereço: #painel, #ocorrencia-12, ...) ----------
function route() {
  if (!session.user) return;
  let hash = location.hash.slice(1) || "painel";
  if (hash === "cameras" || hash === "usuarios") {
    // câmeras e usuários ficam em Cadastros (os endereços antigos continuam funcionando)
    cadastros.openTab(hash);
    history.replaceState(null, "", "#cadastros");
    hash = "cadastros";
  }
  if (hash === "auditoria" || hash === "sistema") {
    relatorios.openTab(hash === "auditoria" ? "auditoria" : "relatorios");
    history.replaceState(null, "", "#relatorios");
    hash = "relatorios";
  }
  const match = hash.match(/^ocorrencia-(\d+)$/);
  const name = match ? "ocorrencias" : (VIEWS[hash] ? hash : "painel");
  const link = $(`#nav a[href="#${name}"]`);
  if (link?.hidden) { location.hash = "#painel"; return; }

  if (current !== name) {
    VIEWS[current]?.leave?.();
    current = name;
    $$("#nav a").forEach((a) => a.classList.toggle("active", a.getAttribute("href") === `#${name}`));
    $$(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${name}`));
    const el = $(`#view-${name}`);
    VIEWS[name].show(el).catch((err) => toast(esc(err.message), "danger"));
  }
  if (match) openEvent(Number(match[1]));
}
window.addEventListener("hashchange", route);

// ---------- Tempo real ----------
let ws = null;
function connectWs() {
  if (ws && ws.readyState <= 1) return;
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(withToken(`${proto}://${location.host}/ws`));
  ws.onopen = () => { $("#conn").className = "conn on"; };
  ws.onclose = () => {
    $("#conn").className = "conn off";
    if (session.user) setTimeout(connectWs, 3000);
  };
  ws.onmessage = (msg) => {
    const data = JSON.parse(msg.data);
    // Alertas de outra unidade não interrompem quem está olhando uma unidade específica
    const otherUnit = session.unitId && ((data.kind === "event" && data.event.unit_id && data.event.unit_id !== session.unitId)
      || (data.kind === "camera_health" && data.unit_id && data.unit_id !== session.unitId));
    if (otherUnit) { VIEWS[current]?.onRealtime?.(data); return; }
    if (data.kind === "event") {
      const ev = data.event;
      beep();
      toast(`<a href="#ocorrencia-${ev.id}"><b>🚨 ${esc(ev.message)}</b><br>${esc(ev.camera_name)} – ${fmtDateTime(ev.created_at)}</a>`,
        ev.severity === "critica" || ev.severity === "alta" ? "danger" : "warn");
    }
    if (data.kind === "camera_health") {
      const ok = data.health === "ok";
      if (!ok) beep();
      toast(`<b>${ok ? "✅" : "⚠️"} Câmera ${esc(data.camera_name)}</b><br>${esc(data.label)}`, ok ? "ok" : "warn", 10000);
    }
    if (data.kind === "usage_alert") {
      toast(esc(data.text), data.alerting ? "warn" : "ok", 12000);
      if (data.alerting) beep();
    }
    if (data.kind === "storage_health") {
      toast(`<b>${data.online ? "✅" : "⚠️"} Armazenamento de rede</b><br>${esc(data.label)}`,
        data.online ? "ok" : "warn", 12000);
    }
    if (data.kind === "event_updated") refreshIfOpen(data.id);
    VIEWS[current]?.onRealtime?.(data);
  };
}

// ---------- Início ----------
(async () => {
  if (!getToken()) return showAuth();
  try {
    session.user = await api("/api/auth/me");
    await showApp();
  } catch { /* o handler de 401 já mostra o login */ }
})();
