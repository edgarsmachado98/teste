// Campos das guias Configurações e Parâmetros, ligados a /api/config.

import { api, esc, toast } from "./core.js";

const SOURCE = { painel: "definido no painel", env: "valor do .env", padrao: "padrão" };

export function sourceTag(meta) {
  return meta ? `<span class="src src-${meta.source}" title="${SOURCE[meta.source]}">${SOURCE[meta.source]}</span>` : "";
}

/** Campo de formulário. opts: {type, min, max, choices: [[valor, rótulo]], hint, placeholder, wide, suffix} */
export function field(values, name, label, opts = {}) {
  const meta = values[name];
  const value = meta?.value ?? "";
  let input;
  if (opts.type === "secret") {
    input = `<input type="password" name="${name}" autocomplete="new-password"
      placeholder="${meta?.set ? "•••••••• (definida – deixe vazio para manter)" : "não definida"}">`;
  } else if (opts.choices) {
    input = `<select name="${name}">${opts.choices.map(([v, l]) =>
      `<option value="${esc(v)}" ${String(value) === String(v) ? "selected" : ""}>${esc(l)}</option>`).join("")}</select>`;
  } else if (opts.type === "bool") {
    return `<label class="check ${opts.wide ? "wide" : ""}"><input type="checkbox" name="${name}" ${value ? "checked" : ""}>
      ${esc(label)} ${sourceTag(meta)}</label>`;
  } else {
    input = `<input type="${opts.type || "text"}" name="${name}" value="${esc(value)}"
      ${opts.min != null ? `min="${opts.min}"` : ""} ${opts.max != null ? `max="${opts.max}"` : ""}
      ${opts.placeholder ? `placeholder="${esc(opts.placeholder)}"` : ""}>`;
  }
  return `<label class="${opts.wide ? "wide" : ""}">${esc(label)} ${sourceTag(meta)}
    ${opts.suffix ? `<span class="with-suffix">${input}<span>${esc(opts.suffix)}</span></span>` : input}
    ${opts.hint ? `<small class="hint">${opts.hint}</small>` : ""}</label>`;
}

/** Lê os campos do formulário (somente os nomes informados). */
export function collect(form, names) {
  const values = {};
  for (const name of names) {
    const el = form.elements[name];
    if (!el) continue;
    if (el.type === "checkbox") values[name] = el.checked;
    else if (el.type === "number") values[name] = el.value === "" ? null : Number(el.value);
    else values[name] = el.value;
  }
  return values;
}

/** Salva; devolve a configuração atualizada ou null em caso de erro. */
export async function saveConfig(values, reset = []) {
  try {
    const cfg = await api("/api/config", { method: "PUT", body: { values, reset } });
    toast("Configuração salva.", "ok", 2500);
    return cfg;
  } catch (err) {
    toast(esc(err.message), "danger");
    return null;
  }
}

export const fmtBytes = (b) => {
  if (b == null) return "–";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (b >= 1024 && i < units.length - 1) { b /= 1024; i++; }
  return `${b.toFixed(i >= 3 ? 1 : 0).replace(".", ",")} ${units[i]}`;
};
