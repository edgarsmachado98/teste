// Leitor de QR Code compartilhado pelos módulos (câmera ao vivo, foto e arquivos).
// A câmera ao vivo só é liberada em conexão segura (https ou o próprio computador); pelo endereço http
// da rede, "escanear" abre a câmera do celular para fotografar o cupom.
window.LeitorQR = (function () {
  let promessaJsQR = null, sessao = null;

  function carregarJsQR() {
    return (promessaJsQR ||= new Promise((ok, falha) => {
      if (window.jsQR) return ok(window.jsQR);
      const s = document.createElement("script");
      s.src = "/static/vendor/jsQR.js";
      s.onload = () => ok(window.jsQR);
      s.onerror = () => { promessaJsQR = null; falha(new Error("jsQR")); };
      document.head.appendChild(s);
    }));
  }

  // procura o QR Code numa foto, no próprio aparelho; null se não achar (aí a foto vai para o servidor)
  async function lerArquivo(arquivo) {
    let bmp;
    try { bmp = await createImageBitmap(arquivo, { imageOrientation: "from-image" }); } catch { return null; }
    if ("BarcodeDetector" in window) {
      try {
        const r = await new BarcodeDetector({ formats: ["qr_code"] }).detect(bmp);
        if (r[0]?.rawValue) return r[0].rawValue;
      } catch { /* sem suporte */ }
    }
    let jsQR;
    try { jsQR = await carregarJsQR(); } catch { return null; }
    const tela = document.createElement("canvas"), g = tela.getContext("2d", { willReadFrequently: true });
    for (const [fx, fy, fw, fh, alvo] of [[0, 0, 1, 1, 1200], [0, 0.45, 1, 0.55, 1500], [0, 0, 1, 1, 2000], [0, 0, 1, 1, 800]]) {
      const sw = bmp.width * fw, sh = bmp.height * fh, f = Math.min(1, alvo / Math.max(sw, sh));
      tela.width = Math.round(sw * f); tela.height = Math.round(sh * f);
      g.drawImage(bmp, bmp.width * fx, bmp.height * fy, sw, sh, 0, 0, tela.width, tela.height);
      const img = g.getImageData(0, 0, tela.width, tela.height);
      const r = jsQR(img.data, img.width, img.height, { inversionAttempts: "attemptBoth" });
      if (r?.data) return r.data;
    }
    return null;
  }

  async function reduzir(arquivo) {
    try {
      const bmp = await createImageBitmap(arquivo, { imageOrientation: "from-image" });
      const f = Math.min(1, 2600 / Math.max(bmp.width, bmp.height));
      const tela = document.createElement("canvas");
      tela.width = Math.round(bmp.width * f); tela.height = Math.round(bmp.height * f);
      tela.getContext("2d").drawImage(bmp, 0, 0, tela.width, tela.height);
      return (await new Promise(ok => tela.toBlob(ok, "image/jpeg", 0.9))) || arquivo;
    } catch { return arquivo; }
  }

  function montar() {
    if (document.getElementById("lqr")) return;
    document.body.insertAdjacentHTML("beforeend", `<div class="escaner oculto" id="lqr" role="dialog" aria-label="Escanear QR Code">
      <video id="lqr-video" playsinline muted></video>
      <div class="escaner-moldura"><span></span></div>
      <p class="escaner-texto">Aponte para o QR Code do cupom</p>
      <div class="escaner-acoes"><button type="button" class="secundario" id="lqr-foto">Tirar foto</button>
        <button type="button" class="btn" id="lqr-fechar">Fechar</button></div></div>
      <input type="file" id="lqr-camera" accept="image/*" capture="environment" hidden>`);
    document.getElementById("lqr-fechar").addEventListener("click", fechar);
    document.getElementById("lqr-foto").addEventListener("click", () => { fechar(); document.getElementById("lqr-camera").click(); });
    document.getElementById("lqr-camera").addEventListener("change", ev => {
      const f = ev.target.files[0]; ev.target.value = "";
      if (f && sessao?.aoFotografar) sessao.aoFotografar([f]);
    });
    document.addEventListener("keydown", ev => { if (ev.key === "Escape" && sessao?.stream) fechar(); });
  }

  function fechar() {
    if (sessao?.stream) sessao.stream.getTracks().forEach(t => t.stop());
    if (sessao) { sessao.ativo = false; sessao.stream = null; }
    const v = document.getElementById("lqr-video");
    if (v) v.srcObject = null;
    document.getElementById("lqr")?.classList.add("oculto");
    document.body.classList.remove("escaneando");
  }

  // aoLer(texto): QR lido ao vivo; aoFotografar([arquivo]): foto tirada (quando não há câmera ao vivo)
  async function escanear(aoLer, aoFotografar) {
    montar();
    sessao = { ativo: true, aoFotografar };
    if (!(window.isSecureContext && navigator.mediaDevices?.getUserMedia)) return document.getElementById("lqr-camera").click();
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: "environment" }, width: { ideal: 1280 } }, audio: false });
    } catch {
      return document.getElementById("lqr-camera").click();
    }
    sessao.stream = stream;
    const video = document.getElementById("lqr-video");
    video.srcObject = stream;
    await video.play().catch(() => {});
    document.getElementById("lqr").classList.remove("oculto");
    document.body.classList.add("escaneando");
    let detector = null;
    if ("BarcodeDetector" in window) { try { detector = new BarcodeDetector({ formats: ["qr_code"] }); } catch { detector = null; } }
    const jsQR = detector ? null : await carregarJsQR().catch(() => null);
    const tela = document.createElement("canvas"), g = tela.getContext("2d", { willReadFrequently: true });
    const atual = sessao;
    const ler = async () => {
      if (!atual.ativo) return;
      let texto = null;
      if (video.readyState >= 2) {
        if (detector) {
          try { texto = (await detector.detect(video))[0]?.rawValue || null; } catch { texto = null; }
        } else if (jsQR) {
          const f = Math.min(1, 900 / Math.max(video.videoWidth, video.videoHeight));
          tela.width = Math.round(video.videoWidth * f); tela.height = Math.round(video.videoHeight * f);
          g.drawImage(video, 0, 0, tela.width, tela.height);
          const img = g.getImageData(0, 0, tela.width, tela.height);
          texto = jsQR(img.data, img.width, img.height, { inversionAttempts: "dontInvert" })?.data || null;
        }
      }
      if (texto) { navigator.vibrate?.(80); fechar(); aoLer(texto); return; }
      setTimeout(ler, 180);
    };
    ler();
  }

  return { escanear, lerArquivo, reduzir, fechar };
})();
