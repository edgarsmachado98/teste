// Player de clipe: exibe a sequência de quadros JPEG como vídeo (sem depender de codecs).

import { withToken } from "./core.js";

export function mountClipPlayer(root, eventId, frames, duration) {
  const fps = Math.min(Math.max(frames / duration, 1), 15);
  const urls = Array.from({ length: frames }, (_, i) => withToken(`/api/events/${eventId}/clip/${i}`));
  root.innerHTML = `
    <div class="clip">
      <img class="evidence-img" alt="Clipe da ocorrência">
      <div class="clip-controls">
        <button type="button" class="small" data-play>▶ Reproduzir</button>
        <input type="range" min="0" max="${frames - 1}" value="0" aria-label="Posição no clipe">
        <span class="hint" data-time></span>
        <select aria-label="Velocidade"><option value="0.5">0,5×</option><option value="1" selected>1×</option>
          <option value="2">2×</option></select>
      </div>
    </div>`;
  const img = root.querySelector("img");
  const slider = root.querySelector("input");
  const btn = root.querySelector("[data-play]");
  const time = root.querySelector("[data-time]");
  const speed = root.querySelector("select");
  // pré-carrega os quadros para a reprodução ficar fluida
  const cache = urls.map((u) => { const im = new Image(); im.src = u; return im; });
  let index = 0;
  let timer = null;

  const show = (i) => {
    index = i;
    img.src = cache[i].src;
    slider.value = i;
    const t = (i / Math.max(frames - 1, 1)) * duration;
    time.textContent = `${t.toFixed(1).replace(".", ",")}s / ${duration.toFixed(1).replace(".", ",")}s`;
  };
  const stop = () => { clearInterval(timer); timer = null; btn.textContent = "▶ Reproduzir"; };
  const play = () => {
    if (index >= frames - 1) show(0);
    btn.textContent = "❚❚ Pausar";
    timer = setInterval(() => {
      if (index >= frames - 1) return stop();
      show(index + 1);
    }, 1000 / (fps * Number(speed.value)));
  };
  btn.addEventListener("click", () => (timer ? stop() : play()));
  slider.addEventListener("input", () => { stop(); show(Number(slider.value)); });
  speed.addEventListener("change", () => { if (timer) { stop(); play(); } });
  show(0);
  play();
  return stop;
}
