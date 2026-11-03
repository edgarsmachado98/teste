import { $$, api, cameraBadge, cameraHint, esc, healthBadge, withToken } from "../core.js";

let el;
let timer = null;

function refreshFrames() {
  $$("img[data-cam]", el).forEach((img) => {
    // troca só quando o quadro novo carregar (sem piscar nem ícone de imagem quebrada)
    const next = new Image();
    next.onload = () => { img.src = next.src; img.hidden = false; img.nextElementSibling.hidden = true; };
    next.onerror = () => { if (!img.getAttribute("src")) { img.hidden = true; img.nextElementSibling.hidden = false; } };
    next.src = withToken(`/api/cameras/${img.dataset.cam}/frame?t=${Date.now()}`);
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
        <img data-cam="${c.id}" alt="${esc(c.name)}" hidden>
        <div class="live-msg" data-msg="${c.id}"><b>Sem imagem</b><span>${esc(cameraHint(c) || "Aguardando o primeiro quadro do detector.")}</span></div>
        <figcaption><span>${esc(c.name)} <small>${esc(c.location)}</small></span>
          <span data-health="${c.id}">${cameraBadge(c)}</span></figcaption>
      </figure>`).join("") || `<p class="hint">Cadastre câmeras na aba Câmeras.</p>`}</div>`;
  refreshFrames();
  clearInterval(timer);
  timer = setInterval(refreshFrames, 2000);
}

export function leave() {
  clearInterval(timer);
}

export function onRealtime(data) {
  if (data.kind === "camera_status") {
    const slot = el.querySelector(`[data-health="${data.camera_id}"]`);
    const msg = el.querySelector(`[data-msg="${data.camera_id}"] span`);
    if (slot && data.error) slot.innerHTML = cameraBadge({ connect_error: data.error });
    if (msg) msg.textContent = data.error || "Conectada – aguardando o primeiro quadro.";
  }
  if (data.kind === "camera_health") {
    const slot = el.querySelector(`[data-health="${data.camera_id}"]`);
    if (slot) slot.innerHTML = healthBadge(data.health);
  }
}
