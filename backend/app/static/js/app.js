import {
  $, $$, ROLE_LABELS, api, applyRoleVisibility, beep, esc, fmtDateTime, getToken, session, setToken,
  setUnauthorizedHandler, toast, withToken,
} from "./core.js";
import { openEvent, refreshIfOpen } from "./event-detail.js";
import * as acoes from "./views/acoes.js";
import * as aovivo from "./views/aovivo.js";
import * as auditoria from "./views/auditoria.js";
import * as cameras from "./views/cameras.js";
import * as indicadores from "./views/indicadores.js";
import * as ocorrencias from "./views/ocorrencias.js";
import * as painel from "./views/painel.js";
import * as regras from "./views/regras.js";
import * as sistema from "./views/sistema.js";
import * as usuarios from "./views/usuarios.js";

const VIEWS = { painel, ocorrencias, acoes, indicadores, aovivo, cameras, regras, usuarios, auditoria, sistema };
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
  $("#user-menu").textContent = `${session.user.name} · ${ROLE_LABELS[session.user.role]}`;
  applyRoleVisibility();
  connectWs();
  route();
}

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
  const img = e.target.closest("img[data-full]");
  if (img) {
    $("#viewer-img").src = img.dataset.full;
    $("#viewer").showModal();
  }
});

// ---------- Navegação (pelo endereço: #painel, #ocorrencia-12, ...) ----------
function route() {
  if (!session.user) return;
  const hash = location.hash.slice(1) || "painel";
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
