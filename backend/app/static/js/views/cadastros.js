// Guia Cadastros: subguias de pessoas, setores e padrões, e regras de gradação.

import { $, $$, can, esc, toast } from "../core.js";
import * as cameras from "./cameras.js";
import * as gradacao from "./gradacao.js";
import * as historico from "./historico.js";
import * as pessoas from "./pessoas.js";
import * as setores from "./setores.js";
import * as usuarios from "./usuarios.js";

const TABS = [
  { id: "setores", label: "Setores e padrões", module: setores, role: "tecnico" },
  { id: "cameras", label: "Câmeras", module: cameras, role: "tecnico" },
  { id: "pessoas", label: "Pessoas", module: pessoas, role: "tecnico" },
  { id: "gradacao", label: "Regras de gradação", module: gradacao, role: "tecnico" },
  { id: "usuarios", label: "Usuários do sistema", module: usuarios, role: "admin" },
];

let pendingHistory = null;

/** Abre o histórico de uma pessoa (a partir da ocorrência ou do cadastro). */
export function openHistory(personId) {
  pendingHistory = personId;
  if (el && el.classList.contains("active")) showHistory();
}

async function showHistory() {
  const id = pendingHistory;
  pendingHistory = null;
  active = "pessoas";
  $$(".subtabs button", el).forEach((b) => b.classList.toggle("active", b.dataset.tab === "pessoas"));
  try {
    await historico.render($("#cad-body", el), id, () => pessoas.render($("#cad-body", el), id));
  } catch (err) { toast(esc(err.message), "danger"); }
}

let el;
let active = null;

async function open(id) {
  active = id;
  $$(".subtabs button", el).forEach((b) => b.classList.toggle("active", b.dataset.tab === id));
  const tab = TABS.find((t) => t.id === id);
  try {
    await tab.module.render($("#cad-body", el));
  } catch (err) { toast(esc(err.message), "danger"); }
}

export async function show(element) {
  el = element;
  const tabs = TABS.filter((t) => can(t.role));
  el.innerHTML = `
    <h2>Cadastros</h2>
    <div class="subtabs" role="tablist">${tabs.map((t) => `<button type="button" role="tab" data-tab="${t.id}">${t.label}</button>`).join("")}</div>
    <div id="cad-body"></div>`;
  $$(".subtabs button", el).forEach((b) => b.addEventListener("click", () => open(b.dataset.tab)));
  pessoas.setHistoryHandler(openHistory);
  if (pendingHistory) return showHistory();
  await open(tabs.some((t) => t.id === active) ? active : tabs[0].id);
}

export function openTab(id) {
  active = id;
  if (el && el.classList.contains("active")) open(id);
}

export function onRealtime(data) {
  if (active === "cameras") cameras.onRealtime?.(data);
}
