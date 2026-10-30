import { $$, api, esc, healthBadge, withToken } from "../core.js";

let el;
let timer = null;

function refreshFrames() {
  $$("img[data-cam]", el).forEach((img) => {
    img.src = withToken(`/api/cameras/${img.dataset.cam}/frame?t=${Date.now()}`);
  });
}

export async function show(element) {
  el = element;
  const cameras = (await api("/api/cameras")).filter((c) => c.enabled);
  el.innerHTML = `
    <h2>Câmeras ao vivo</h2>
    <p class="hint">Último quadro analisado pelo detector (atualiza a cada 2 s). Caixas verdes: pessoas e EPIs
      detectados; contornos amarelos: zonas das regras.</p>
    <div class="live">${cameras.map((c) => `
      <figure>
        <img data-cam="${c.id}" alt="${esc(c.name)}" onerror="this.removeAttribute('src')">
        <figcaption><span>${esc(c.name)} <small>${esc(c.location)}</small></span>
          <span data-health="${c.id}">${healthBadge(c.health)}</span></figcaption>
      </figure>`).join("") || `<p class="hint">Cadastre câmeras na aba Câmeras.</p>`}</div>`;
  refreshFrames();
  clearInterval(timer);
  timer = setInterval(refreshFrames, 2000);
}

export function leave() {
  clearInterval(timer);
}

export function onRealtime(data) {
  if (data.kind === "camera_health") {
    const slot = el.querySelector(`[data-health="${data.camera_id}"]`);
    if (slot) slot.innerHTML = healthBadge(data.health);
  }
}
