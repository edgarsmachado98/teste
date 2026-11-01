// Guia Cadastros: subguias de pessoas, setores e padrões, e regras de gradação.

import { $, $$, can, esc, toast } from "../core.js";
import * as setores from "./setores.js";

const TABS = [
  { id: "setores", label: "Setores e padrões", module: setores, role: "tecnico" },
];

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
  await open(tabs.some((t) => t.id === active) ? active : tabs[0].id);
}

export function openTab(id) {
  active = id;
}
