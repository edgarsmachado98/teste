import { $, api, can, esc, fmtDateTime, healthBadge, session, toast } from "../core.js";

let el;
let cameras = [];
let sectors = [];
let units = [];

function sectorSelect() {
  if (!sectors.length) return `<option value="">Nenhum setor cadastrado – crie em Setores e padrões</option>`;
  const groups = units.map((u) => {
    const list = sectors.filter((s) => s.unit_id === u.id);
    return list.length ? `<optgroup label="${esc(u.name)}">${list.map((s) => `<option value="${s.id}">${esc(s.name)}</option>`).join("")}</optgroup>` : "";
  }).join("");
  return `<option value="">Sem setor – regras manuais</option>${groups}`;
}

const defaultUnit = () => String(units.some((u) => u.id === session.unitId) ? session.unitId : units[0]?.id ?? "");
/** O campo Unidade só aparece para câmera sem setor (com setor, vale a unidade do setor). */
function syncUnit() {
  const f = $("#camera-form", el);
  if (f) $("[data-unit]", el).hidden = !!f.sector_id.value || units.length < 2;
}

async function load() {
  cameras = await api("/api/cameras");
  $("#cameras-table", el).innerHTML = `
    <tr><th>Nome</th><th>Local / área</th>${units.length > 1 ? "<th>Unidade</th>" : ""}<th>Setor</th><th>Fonte</th><th>Saúde da imagem</th><th>Última imagem</th><th>Ativa</th><th></th></tr>
    ${cameras.map((c) => `
      <tr>
        <td>${esc(c.name)}</td><td>${esc(c.location)}</td>
        ${units.length > 1 ? `<td>${esc(units.find((u) => u.id === c.unit_id)?.name || "–")}</td>` : ""}
        <td>${esc(sectors.find((s) => s.id === c.sector_id)?.name || "–")}</td>
        <td class="mono">${esc(c.source.replace(/\/\/[^@/]*@/, "//***@"))}</td>
        <td>${c.enabled ? healthBadge(c.health) : "–"}</td>
        <td>${c.last_frame_at ? fmtDateTime(c.last_frame_at) : "–"}</td>
        <td>${c.enabled ? "sim" : "não"}</td>
        <td class="actions">
          ${can("tecnico") ? `<button data-edit="${c.id}" class="small secondary">Editar</button>` : ""}
          ${can("gestor") ? `<button data-del="${c.id}" class="small danger">Excluir</button>` : ""}
        </td>
      </tr>`).join("") || `<tr><td class="hint">Nenhuma câmera cadastrada.</td></tr>`}`;
}

export async function show(element) {
  el = element;
  [sectors, units] = await Promise.all([api("/api/sectors"), api("/api/units")]);
  el.innerHTML = `
    ${can("tecnico") ? `
    <form id="camera-form" class="card form">
      <h3 class="wide" id="camera-form-title" style="margin:0">Nova câmera</h3>
      <input type="hidden" name="id">
      <label>Nome da câmera <input name="name" required maxlength="120" placeholder="ex.: Prensa hidráulica 1">
        <small class="hint">Como a câmera aparece nos alertas, ocorrências e relatórios</small></label>
      <label>Setor <select name="sector_id">${sectorSelect()}</select>
        <small class="hint">O padrão do setor gera as regras de detecção desta câmera</small></label>
      <label data-unit>Unidade <select name="unit_id">${units.map((u) => `<option value="${u.id}">${esc(u.name)}</option>`).join("")}</select>
        <small class="hint">Câmera sem setor: escolha a unidade (com setor, vale a unidade do setor)</small></label>
      <label>Local / área <input name="location" placeholder="ex.: Galpão A – Prensas">
        <small class="hint">Use nomes padronizados: os indicadores agrupam por área</small></label>
      <label class="wide">Fonte (RTSP ou arquivo)
        <input name="source" required placeholder="rtsp://usuario:senha@192.168.0.10:554/stream1">
      </label>
      <label class="check"><input type="checkbox" name="enabled" checked> Ativa</label>
      <div class="actions">
        <button type="submit">Salvar câmera</button>
        <button type="button" id="use-webcam" class="secondary">Usar webcam deste computador</button>
        <button type="reset" class="secondary">Limpar</button>
      </div>
    </form>` : ""}
    <p class="hint">A saúde indica se a câmera está sem sinal, escura, obstruída ou congelada. Para ver as imagens, use a guia
      <a href="#aovivo">Ao vivo</a>.</p>
    <div class="table-wrap"><table id="cameras-table"></table></div>`;

  const f = $("#camera-form", el);
  if (f) {
    f.addEventListener("submit", async (e) => {
      e.preventDefault();
      const body = { name: f.name.value, location: f.location.value, source: f.source.value, enabled: f.enabled.checked,
        sector_id: f.sector_id.value ? Number(f.sector_id.value) : null,
        unit_id: f.sector_id.value ? null : Number(f.unit_id.value) || null };
      try {
        await api(f.id.value ? `/api/cameras/${f.id.value}` : "/api/cameras",
          { method: f.id.value ? "PUT" : "POST", body });
        f.reset();
        f.id.value = "";
        toast("Câmera salva. O detector a inicia em até 15 segundos.", "ok", 4000);
        load();
      } catch (err) { toast(esc(err.message), "danger"); }
    });
    f.unit_id.value = defaultUnit();
    f.sector_id.addEventListener("change", syncUnit);
    syncUnit();
    f.addEventListener("reset", () => {
      f.id.value = ""; $("#camera-form-title", el).textContent = "Nova câmera";
      setTimeout(() => { f.unit_id.value = defaultUnit(); syncUnit(); });
    });
    $("#use-webcam", el).addEventListener("click", () => {
      if (!f.name.value) f.name.value = "Webcam";
      f.source.value = "0";
      f.requestSubmit();
    });
  }

  $("#cameras-table", el).addEventListener("click", async (e) => {
    const edit = e.target.dataset.edit;
    const del = e.target.dataset.del;
    if (edit) {
      const c = cameras.find((x) => x.id === Number(edit));
      f.id.value = c.id; f.name.value = c.name; f.location.value = c.location;
      f.source.value = c.source; f.enabled.checked = c.enabled; f.sector_id.value = c.sector_id ?? "";
      f.unit_id.value = String(c.unit_id ?? units[0]?.id ?? ""); syncUnit();
      $("#camera-form-title", el).textContent = `Editar câmera: ${c.name}`;
      f.scrollIntoView({ behavior: "smooth" });
    }
    if (del && confirm("Excluir a câmera e suas regras? Câmeras com ocorrências no histórico não podem ser excluídas – desative-as.")) {
      try {
        await api(`/api/cameras/${del}`, { method: "DELETE" });
        load();
      } catch (err) { toast(esc(err.message), "danger"); }
    }
  });
  await load();
}

export function onRealtime(data) {
  if (data.kind === "camera_health") load();
}

// Usado como subguia de Cadastros
export const render = show;
