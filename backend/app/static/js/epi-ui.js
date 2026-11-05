// EPI: janelas compartilhadas (guia EPI e cadastro de pessoas): nova entrega e assinatura da ficha.

import { api, esc, fmtDate, isoDate, toast } from "./core.js";

export const REASONS = {
  primeira: "Primeira entrega / admissão", troca: "Troca periódica", desgaste: "Desgaste ou dano",
  perda: "Perda ou extravio", tamanho: "Troca de tamanho", outro: "Outro",
};
export const CATEGORY = { epi: "EPI", uniforme: "Uniforme" };
export const SIZE_LABELS = { camisa: "Camisa", calca: "Calça", jaleco: "Jaleco/macacão", calcado: "Calçado", luva: "Luva" };
/** "Camisa M · Calça 42 · Calçado 40" */
export const sizesText = (sizes) => Object.entries(sizes || {}).map(([k, v]) => `${SIZE_LABELS[k] || k} ${v}`).join(" · ");

export function makeDialog(html, cls = "form-dialog") {
  const d = document.createElement("dialog");
  d.className = cls;
  d.innerHTML = html;
  document.body.append(d);
  d.addEventListener("close", () => d.remove());
  d.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", () => d.close()));
  d.showModal();
  return d;
}

/** Texto da declaração (NR-6, 6.6.1 e 6.7.1): o mesmo na tela e na ficha impressa. */
export const DECLARATION = "Declaro que recebi gratuitamente os equipamentos e peças abaixo, em perfeito estado, e que fui "
  + "orientado(a) sobre o uso correto, a guarda e a conservação. Comprometo-me a usá-los apenas para a finalidade a que se "
  + "destinam, a comunicar qualquer dano ou alteração que os torne impróprios e a devolvê-los quando solicitado. Estou "
  + "ciente de que a recusa injustificada ao uso do EPI fornecido constitui ato faltoso (art. 158 da CLT; NR-6).";

async function searchPeople(q) {
  const params = new URLSearchParams({ q, status: "ativo", limit: "12" });
  return (await api(`/api/people?${params}`)).items;
}

/**
 * Nova entrega. `person` (opcional) já escolhe o colaborador; `lines` (opcional) pré-preenche itens
 * (ex.: vindo do plano de substituição). Ao salvar, abre a assinatura. Resolve com o comprovante ou null.
 */
export async function openDelivery({ person = null, lines = [] } = {}) {
  const items = await api("/api/ppe/items");
  if (!items.length) {
    toast("Cadastre os EPIs e uniformes no Catálogo antes de registrar entregas.", "warn");
    return null;
  }
  const byId = Object.fromEntries(items.map((i) => [i.id, i]));
  if (person && !person.sizes) person = await api(`/api/people/${person.id}`);
  const itemOptions = (sel) => ["epi", "uniforme"].map((c) => {
    const list = items.filter((i) => i.category === c);
    return list.length ? `<optgroup label="${CATEGORY[c]}">${list.map((i) =>
      `<option value="${i.id}" ${i.id === sel ? "selected" : ""}>${esc(i.name)}${i.ca ? ` · CA ${esc(i.ca)}` : ""}</option>`).join("")}</optgroup>` : "";
  }).join("");

  return new Promise((resolve) => {
    let chosen = person;
    let saved = null;
    const d = makeDialog(`<form class="form epi-delivery" method="dialog">
      <h2 class="wide">Entrega de EPI / uniforme</h2>
      <div class="wide epi-person">
        <label>Colaborador <input name="q" placeholder="Nome, matrícula, CPF ou nº do colete" autocomplete="off"
          ${chosen ? `value="${esc(chosen.name)}"` : ""}></label>
        <div class="epi-results"></div>
        <div class="epi-chosen hint">${chosen ? personLine(chosen) : "Escolha o colaborador."}</div>
      </div>
      <label>Data da entrega <input type="date" name="delivered_on" required value="${isoDate(new Date())}" max="${isoDate(new Date())}"></label>
      <div class="wide"><table class="epi-lines"><thead><tr><th>Item</th><th>Tam.</th><th>Qtd.</th><th>Motivo</th>
        <th title="Baixar do estoque da unidade">Estoque</th><th></th></tr></thead><tbody></tbody></table>
        <button type="button" class="secondary small" data-add>+ Item</button></div>
      <label class="wide">Observações <input name="notes" maxlength="500" placeholder="opcional"></label>
      <p class="hint wide">A troca prevista é calculada pelo catálogo (troca a cada N dias). Itens com "Estoque" marcado
        saem do saldo da unidade do colaborador.</p>
      <div class="actions wide"><button type="submit">Registrar e colher assinatura</button>
        <button type="button" class="secondary" data-close>Cancelar</button></div>
    </form>`, "form-dialog wide-dialog");
    const f = d.querySelector("form");
    const body = d.querySelector(".epi-lines tbody");

    function personLine(p) {
      const sizes = sizesText(p.sizes);
      return `<b>${esc(p.name)}</b> · ${esc(p.sector || "sem setor")} · ${esc(p.role || "")}${sizes ? ` · tamanhos: ${esc(sizes)}` : ""}`;
    }

    function addLine(line = {}) {
      const tr = document.createElement("tr");
      tr.innerHTML = `<td><select name="item">${itemOptions(line.item_id)}</select></td>
        <td><select name="size"></select></td>
        <td><input type="number" name="qty" min="1" max="100" value="${line.quantity || 1}" style="width:64px"></td>
        <td><select name="reason">${Object.entries(REASONS).map(([k, v]) =>
          `<option value="${k}" ${k === (line.reason || "primeira") ? "selected" : ""}>${v}</option>`).join("")}</select></td>
        <td style="text-align:center"><input type="checkbox" name="stock" checked></td>
        <td><button type="button" class="secondary small" aria-label="Remover">×</button></td>`;
      const sel = tr.querySelector("[name=item]");
      const size = tr.querySelector("[name=size]");
      const fillSizes = () => {
        const it = byId[sel.value];
        const sizes = it?.sizes || [];
        size.innerHTML = sizes.length ? sizes.map((s) => `<option ${s === line.size ? "selected" : ""}>${esc(s)}</option>`).join("")
          : `<option value="">único</option>`;
        size.disabled = !sizes.length;
        // sugere o tamanho cadastrado do colaborador (camisa, calça, calçado...)
        const known = Object.values(chosen?.sizes || {});
        if (!line.size && sizes.length) { const m = sizes.find((s) => known.includes(s)); if (m) size.value = m; }
      };
      sel.addEventListener("change", () => { line = {}; fillSizes(); });
      fillSizes();
      tr.querySelector("button").addEventListener("click", () => { tr.remove(); if (!body.children.length) addLine(); });
      body.append(tr);
    }
    (lines.length ? lines : [{}]).forEach(addLine);
    d.querySelector("[data-add]").addEventListener("click", () => addLine());

    let timer;
    f.q.addEventListener("input", () => {
      clearTimeout(timer);
      const q = f.q.value.trim();
      const box = d.querySelector(".epi-results");
      if (q.length < 2) { box.innerHTML = ""; return; }
      timer = setTimeout(async () => {
        const found = await searchPeople(q).catch(() => []);
        box.innerHTML = found.map((p) => `<button type="button" class="secondary small" data-pick="${p.id}">${esc(p.name)}
          <span class="hint">${esc(p.sector || "")}${p.registration ? ` · ${esc(p.registration)}` : ""}</span></button>`).join("")
          || `<span class="hint">Ninguém encontrado.</span>`;
        box.querySelectorAll("[data-pick]").forEach((b) => b.addEventListener("click", async () => {
          chosen = await api(`/api/people/${b.dataset.pick}`);
          f.q.value = chosen.name;
          box.innerHTML = "";
          d.querySelector(".epi-chosen").innerHTML = personLine(chosen);
          body.querySelectorAll("[name=item]").forEach((s) => s.dispatchEvent(new Event("change")));
        }));
      }, 250);
    });

    f.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (!chosen) return toast("Escolha o colaborador.", "warn");
      const rows = [...body.children].map((tr) => ({
        item_id: Number(tr.querySelector("[name=item]").value), size: tr.querySelector("[name=size]").value,
        quantity: Number(tr.querySelector("[name=qty]").value) || 1, reason: tr.querySelector("[name=reason]").value,
        from_stock: tr.querySelector("[name=stock]").checked }));
      try {
        saved = await api("/api/ppe/receipts", { method: "POST", body: {
          person_id: chosen.id, delivered_on: f.delivered_on.value, items: rows, notes: f.notes.value } });
        d.close();
        (saved.warnings || []).forEach((w) => toast(`Atenção: ${esc(w)}`, "warn", 9000));
        toast(`Entrega ${esc(saved.number)} registrada.`, "ok", 3000);
        resolve(await openSign(saved) || saved);
      } catch (err) { toast(esc(err.message), "danger", 8000); }
    });
    d.addEventListener("close", () => { if (!saved) resolve(null); });
  });
}

/** Assinatura do comprovante: na tela (com conferência do CPF e foto opcional) ou ficha impressa. */
export function openSign(receipt) {
  return new Promise((resolve) => {
    const d = makeDialog(`<form class="sign-form" method="dialog">
      <div class="identify-head"><div><h2 style="margin:0">Assinatura do colaborador</h2>
        <div class="hint mono">${esc(receipt.number)} · ${fmtDate(receipt.delivered_on)}</div></div>
        <button type="button" class="secondary small" data-close aria-label="Fechar">✕</button></div>
      <p><b>${esc(receipt.person)}</b></p>
      <ul class="epi-sign-items">${receipt.items.map((i) => `<li>${i.quantity}× ${esc(i.item)}${i.size ? ` (${esc(i.size)})` : ""}
        ${i.ca ? `<span class="hint">CA ${esc(i.ca)}</span>` : ""}${i.valid_until ? ` <span class="hint">· troca prevista ${fmtDate(i.valid_until)}</span>` : ""}</li>`).join("")}</ul>
      <p class="ack-text" style="font-size:13px">${esc(DECLARATION)}</p>
      <div class="tabs ack-tabs">
        <button type="button" class="small" data-mode="tela">Assinar na tela</button>
        <button type="button" class="small secondary" data-mode="impressa">Ficha impressa</button>
      </div>
      <div data-pane="tela">
        <div class="sign-wrap"><canvas class="sign"></canvas><button type="button" class="secondary small sign-clear">Limpar</button></div>
        <div class="epi-sign-row">
          <label>3 primeiros dígitos do CPF (o colaborador digita)
            <input name="cpf_check" inputmode="numeric" maxlength="3" autocomplete="off" pattern="[0-9]{3}"></label>
          <div class="epi-photo"><button type="button" class="secondary small" data-photo>📷 Foto do momento (opcional)</button>
            <img alt="" hidden></div>
        </div>
        <label class="check"><input type="checkbox" name="aware"> Li a declaração e recebi os itens acima.</label>
      </div>
      <div data-pane="impressa" hidden><p class="hint">Imprima a ficha, colha a assinatura no papel e arquive.
        <a href="ficha-epi.html?person=${receipt.person_id}" target="_blank">Abrir ficha de EPI</a></p></div>
      <div class="actions" style="justify-content:flex-end">
        <button type="button" class="secondary" data-close>Assinar depois</button>
        <button type="submit">Confirmar</button></div>
    </form>`, "form-dialog ack-dialog");
    const form = d.querySelector("form");
    let mode = "tela";
    let photo = null;
    let done = null;
    d.querySelectorAll("[data-mode]").forEach((b) => b.addEventListener("click", () => {
      mode = b.dataset.mode;
      d.querySelectorAll("[data-mode]").forEach((x) => x.classList.toggle("secondary", x !== b));
      d.querySelectorAll("[data-pane]").forEach((p) => { p.hidden = p.dataset.pane !== mode; });
    }));
    const canvas = d.querySelector("canvas.sign");
    const ctx = canvas.getContext("2d");
    let drawing = false;
    let signed = false;
    requestAnimationFrame(() => {
      canvas.width = canvas.clientWidth * devicePixelRatio;
      canvas.height = canvas.clientHeight * devicePixelRatio;
      ctx.scale(devicePixelRatio, devicePixelRatio);
      ctx.lineWidth = 2.4; ctx.lineCap = "round"; ctx.strokeStyle = "#111";
    });
    const pos = (e) => { const r = canvas.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
    canvas.addEventListener("pointerdown", (e) => { drawing = true; signed = true; canvas.setPointerCapture(e.pointerId); ctx.beginPath(); ctx.moveTo(...pos(e)); });
    canvas.addEventListener("pointermove", (e) => { if (drawing) { ctx.lineTo(...pos(e)); ctx.stroke(); } });
    canvas.addEventListener("pointerup", () => { drawing = false; });
    d.querySelector(".sign-clear").addEventListener("click", () => { ctx.clearRect(0, 0, canvas.width, canvas.height); signed = false; });
    d.querySelector("[data-photo]").addEventListener("click", () => takePhoto((url) => {
      photo = url;
      const img = d.querySelector(".epi-photo img");
      img.src = url; img.hidden = false;
    }));

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const body = { method: mode, photo };
      if (mode === "tela") {
        if (!signed) return toast("Peça ao colaborador para assinar no quadro.", "warn");
        if (!/^\d{3}$/.test(form.cpf_check.value)) return toast("O colaborador deve digitar os 3 primeiros dígitos do CPF.", "warn");
        if (!form.aware.checked) return toast("Marque a confirmação da declaração.", "warn");
        const out = document.createElement("canvas");
        out.width = canvas.width; out.height = canvas.height;
        const o = out.getContext("2d");
        o.fillStyle = "#fff"; o.fillRect(0, 0, out.width, out.height); o.drawImage(canvas, 0, 0);
        Object.assign(body, { signature: out.toDataURL("image/png"), cpf_check: form.cpf_check.value, aware: true });
      } else if (!confirm("Confirma que a ficha impressa foi assinada pelo colaborador e arquivada?")) return;
      try {
        done = await api(`/api/ppe/receipts/${receipt.id}/sign`, { method: "POST", body });
        d.close();
        toast("Entrega assinada.", "ok", 3000);
        resolve(done);
      } catch (err) { toast(esc(err.message), "danger", 8000); }
    });
    d.addEventListener("close", () => { if (!done) resolve(null); });
  });
}

function takePhoto(onUrl) {
  const dialog = makeDialog(`<h2>Foto do momento da entrega</h2>
    <video autoplay playsinline muted style="width:100%;max-height:60vh;background:#000;border-radius:8px"></video>
    <div class="actions" style="margin-top:10px"><button type="button" data-shot>Capturar</button>
      <button type="button" class="secondary" data-close>Cancelar</button></div>`);
  const video = dialog.querySelector("video");
  let stream;
  dialog.addEventListener("close", () => stream?.getTracks().forEach((t) => t.stop()));
  navigator.mediaDevices?.getUserMedia({ video: { width: 960, height: 720 } })
    .then((s) => { stream = s; video.srcObject = s; })
    .catch(() => { toast("Não foi possível acessar a câmera (exige HTTPS ou acesso local, e permissão no navegador).", "warn"); dialog.close(); });
  dialog.querySelector("[data-shot]").addEventListener("click", () => {
    const c = document.createElement("canvas");
    const scale = Math.min(1, 800 / (video.videoWidth || 800));
    c.width = Math.round((video.videoWidth || 800) * scale);
    c.height = Math.round((video.videoHeight || 600) * scale);
    c.getContext("2d").drawImage(video, 0, 0, c.width, c.height);
    onUrl(c.toDataURL("image/jpeg", 0.85));
    dialog.close();
  });
}
