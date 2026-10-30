import { $, $$, PPE_ITEMS, PPE_LABELS, TYPE_LABELS, api, can, esc, toast, withToken } from "../core.js";

let el;
let cameras = [];
let rules = [];
let zone = [];

const form = () => $("#rule-form", el);

function toggleParams() {
  const type = form().type.value;
  $$(".param", el).forEach((p) => { p.hidden = p.dataset.for !== type; });
}

function loadZoneImage() {
  const id = form().camera_id.value;
  const img = $("#zone-img", el);
  if (!id) return;
  img.onerror = () => { img.hidden = true; drawZone(); };
  img.onload = () => { img.hidden = false; drawZone(); };
  img.src = withToken(`/api/cameras/${id}/frame?t=${Date.now()}`);
}

function drawZone() {
  const canvas = $("#zone-canvas", el);
  if (!canvas) return;
  canvas.width = canvas.clientWidth || 640;
  canvas.height = canvas.clientHeight || 360;
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (!zone.length) return;
  ctx.beginPath();
  zone.forEach(([x, y], i) => (i ? ctx.lineTo : ctx.moveTo).call(ctx, x * canvas.width, y * canvas.height));
  ctx.closePath();
  ctx.fillStyle = "rgba(239, 68, 68, 0.25)";
  ctx.strokeStyle = "#ef4444";
  ctx.lineWidth = 2;
  ctx.fill();
  ctx.stroke();
  zone.forEach(([x, y]) => {
    ctx.beginPath();
    ctx.arc(x * canvas.width, y * canvas.height, 4, 0, Math.PI * 2);
    ctx.fillStyle = "#ef4444";
    ctx.fill();
  });
}

async function load() {
  [cameras, rules] = await Promise.all([api("/api/cameras"), api("/api/rules")]);
  const f = form();
  if (f) {
    const prev = f.camera_id.value;
    f.camera_id.innerHTML = cameras.map((c) => `<option value="${c.id}">${esc(c.name)}</option>`).join("");
    if (prev) f.camera_id.value = prev;
    loadZoneImage();
  }
  const camName = (id) => cameras.find((c) => c.id === id)?.name || id;
  $("#rules-table", el).innerHTML = `
    <tr><th>Regra</th><th>Câmera</th><th>Tipo</th><th>Horário</th><th>Severidade</th><th>Ativa</th><th></th></tr>
    ${rules.map((r) => `
      <tr>
        <td>${esc(r.name)}</td><td>${esc(camName(r.camera_id))}</td>
        <td>${esc(TYPE_LABELS[r.type])}${r.type === "ppe_missing"
          ? ` (${esc((r.params.required || []).map((i) => PPE_LABELS[i] || i).join(", "))})` : ""}</td>
        <td>${r.start_hour == null ? "sempre" : `${r.start_hour}h–${r.end_hour}h`}</td>
        <td>${esc(r.severity)}</td><td>${r.enabled ? "sim" : "não"}</td>
        <td class="actions">${can("tecnico") ? `<button data-edit="${r.id}" class="small secondary">Editar</button>
            <button data-del="${r.id}" class="small danger">Excluir</button>` : ""}</td>
      </tr>`).join("") || `<tr><td class="hint">Nenhuma regra cadastrada.</td></tr>`}`;
}

const FORM_HTML = `
  <form id="rule-form" class="card form">
    <input type="hidden" name="id">
    <label>Câmera <select name="camera_id" required></select></label>
    <label>Nome <input name="name" required placeholder="Capacete obrigatório – Prensa"></label>
    <label>Tipo
      <select name="type">
        ${Object.entries(TYPE_LABELS).map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}
      </select>
    </label>
    <label>Severidade
      <select name="severity">
        <option value="baixa">Baixa</option><option value="media">Média</option>
        <option value="alta" selected>Alta</option><option value="critica">Crítica</option>
      </select>
    </label>
    <fieldset class="wide param" data-for="ppe_missing">
      <legend>EPIs obrigatórios</legend>
      ${PPE_ITEMS.map((i) => `<label class="check"><input type="checkbox" name="req_${i}" ${i === "helmet" ? "checked" : ""}>
        ${PPE_LABELS[i][0].toUpperCase() + PPE_LABELS[i].slice(1)}</label>`).join("")}
    </fieldset>
    <label class="param" data-for="max_people">Máx. de pessoas na zona
      <input type="number" name="max_people" min="0" value="2">
    </label>
    <label>Confiança mínima <input type="number" name="min_confidence" min="0" max="1" step="0.05" value="0.5"></label>
    <label>Duração mínima (s) <input type="number" name="min_duration" min="0" step="0.5" value="2"></label>
    <label>Intervalo entre alertas (s) <input type="number" name="cooldown" min="0" value="300"></label>
    <label>Das (hora) <input type="number" name="start_hour" min="0" max="23" placeholder="sempre"></label>
    <label>Até (hora) <input type="number" name="end_hour" min="0" max="24" placeholder="sempre"></label>
    <label class="check"><input type="checkbox" name="enabled" checked> Ativa</label>

    <div class="wide zone-editor">
      <p class="hint">Zona de monitoramento: clique na imagem para marcar os pontos do polígono.
        Sem pontos = imagem inteira. Para pessoas, vale a posição dos pés.</p>
      <div class="zone-wrap">
        <img id="zone-img" alt="" hidden>
        <canvas id="zone-canvas"></canvas>
      </div>
      <button type="button" id="zone-clear" class="secondary">Limpar zona</button>
    </div>

    <div class="actions">
      <button type="submit">Salvar regra</button>
      <button type="reset" class="secondary">Limpar</button>
    </div>
  </form>`;

export async function show(element) {
  el = element;
  el.innerHTML = `
    <h2>Regras de detecção</h2>
    ${can("tecnico") ? FORM_HTML : `<p class="hint">Somente técnicos de segurança, gestores e administradores alteram regras.</p>`}
    <div class="table-wrap"><table id="rules-table"></table></div>`;

  const f = form();
  if (f) {
    zone = [];
    toggleParams();
    f.type.addEventListener("change", toggleParams);
    f.camera_id.addEventListener("change", loadZoneImage);
    $("#zone-canvas", el).addEventListener("click", (e) => {
      const rect = e.target.getBoundingClientRect();
      const r = (v) => Math.round(Math.min(1, Math.max(0, v)) * 1000) / 1000;
      zone.push([r((e.clientX - rect.left) / rect.width), r((e.clientY - rect.top) / rect.height)]);
      drawZone();
    });
    $("#zone-clear", el).addEventListener("click", () => { zone = []; drawZone(); });
    window.addEventListener("resize", drawZone);

    f.addEventListener("submit", async (e) => {
      e.preventDefault();
      const num = (v) => (v === "" ? null : Number(v));
      const params = {};
      if (f.type.value === "ppe_missing") params.required = PPE_ITEMS.filter((i) => f[`req_${i}`].checked);
      if (f.type.value === "max_people") params.max_people = Number(f.max_people.value);
      const body = {
        camera_id: Number(f.camera_id.value), name: f.name.value, type: f.type.value, severity: f.severity.value,
        zone, params, min_confidence: Number(f.min_confidence.value), min_duration: Number(f.min_duration.value),
        cooldown: Number(f.cooldown.value), start_hour: num(f.start_hour.value), end_hour: num(f.end_hour.value),
        enabled: f.enabled.checked,
      };
      if (body.type === "ppe_missing" && !params.required.length) return toast("Selecione ao menos um EPI.", "warn");
      if ((body.start_hour == null) !== (body.end_hour == null)) return toast("Informe as duas horas ou nenhuma.", "warn");
      try {
        await api(f.id.value ? `/api/rules/${f.id.value}` : "/api/rules", { method: f.id.value ? "PUT" : "POST", body });
        f.reset();
        zone = [];
        drawZone();
        toast("Regra salva.", "ok", 2500);
        load();
      } catch (err) { toast(esc(err.message), "danger"); }
    });
    f.addEventListener("reset", () => {
      f.id.value = "";
      zone = [];
      setTimeout(() => { toggleParams(); drawZone(); });
    });
  }

  $("#rules-table", el).addEventListener("click", async (e) => {
    const edit = e.target.dataset.edit;
    const del = e.target.dataset.del;
    if (edit) {
      const r = rules.find((x) => x.id === Number(edit));
      f.id.value = r.id; f.camera_id.value = r.camera_id; f.name.value = r.name; f.type.value = r.type;
      f.severity.value = r.severity; f.min_confidence.value = r.min_confidence;
      f.min_duration.value = r.min_duration; f.cooldown.value = r.cooldown;
      f.start_hour.value = r.start_hour ?? ""; f.end_hour.value = r.end_hour ?? "";
      f.enabled.checked = r.enabled;
      PPE_ITEMS.forEach((i) => { f[`req_${i}`].checked = (r.params.required || []).includes(i); });
      f.max_people.value = r.params.max_people ?? 2;
      zone = r.zone.map((p) => [...p]);
      toggleParams();
      loadZoneImage();
      f.scrollIntoView({ behavior: "smooth" });
    }
    if (del && confirm("Excluir regra?")) {
      try {
        await api(`/api/rules/${del}`, { method: "DELETE" });
        load();
      } catch (err) { toast(esc(err.message), "danger"); }
    }
  });
  await load();
}

export function leave() {
  window.removeEventListener("resize", drawZone);
}
