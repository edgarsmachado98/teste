import { $, api, can, esc, fmtDateTime, healthBadge, toast } from "../core.js";

let el;
let cameras = [];

async function load() {
  cameras = await api("/api/cameras");
  $("#cameras-table", el).innerHTML = `
    <tr><th>Nome</th><th>Local / área</th><th>Fonte</th><th>Saúde da imagem</th><th>Última imagem</th><th>Ativa</th><th></th></tr>
    ${cameras.map((c) => `
      <tr>
        <td>${esc(c.name)}</td><td>${esc(c.location)}</td>
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
  el.innerHTML = `
    <h2>Câmeras</h2>
    ${can("tecnico") ? `
    <form id="camera-form" class="card form">
      <input type="hidden" name="id">
      <label>Nome <input name="name" required placeholder="Linha de produção 1"></label>
      <label>Local / área <input name="location" placeholder="Galpão A – Prensas"></label>
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
    <p class="hint">Use o campo <b>Local / área</b> de forma padronizada: os indicadores são agrupados por ele.
      A saúde indica se a câmera está sem sinal, escura, obstruída ou congelada.</p>
    <div class="table-wrap"><table id="cameras-table"></table></div>`;

  const f = $("#camera-form", el);
  if (f) {
    f.addEventListener("submit", async (e) => {
      e.preventDefault();
      const body = { name: f.name.value, location: f.location.value, source: f.source.value, enabled: f.enabled.checked };
      try {
        await api(f.id.value ? `/api/cameras/${f.id.value}` : "/api/cameras",
          { method: f.id.value ? "PUT" : "POST", body });
        f.reset();
        f.id.value = "";
        toast("Câmera salva. O detector a inicia em até 15 segundos.", "ok", 4000);
        load();
      } catch (err) { toast(esc(err.message), "danger"); }
    });
    f.addEventListener("reset", () => { f.id.value = ""; });
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
      f.source.value = c.source; f.enabled.checked = c.enabled;
      f.scrollIntoView({ behavior: "smooth" });
    }
    if (del && confirm("Excluir a câmera, suas regras e todas as ocorrências dela?")) {
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
