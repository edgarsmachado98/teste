// Identificação assistida, medidas educativas/disciplinares e ciência do colaborador.

import { api, badge, can, esc, fmtDate, fmtDateTime, isoDate, toast, withToken } from "./core.js";

const initials = (name) => name.split(" ").filter((w) => w.length > 2).slice(0, 2).map((w) => w[0]).join("").toUpperCase();
const photo = (p, size = 44) => (p.has_photo
  ? `<img class="avatar" style="width:${size}px;height:${size}px" src="${esc(withToken(`/api/people/${p.id}/photo`))}" alt="">`
  : `<span class="avatar" style="width:${size}px;height:${size}px">${esc(initials(p.name))}</span>`);

function dialog(html, cls = "form-dialog") {
  const d = document.createElement("dialog");
  d.className = cls;
  d.innerHTML = html;
  document.body.append(d);
  d.addEventListener("close", () => d.remove());
  d.showModal();
  return d;
}

// ---------- Identificar pessoa ----------

export function openIdentify(ev) {
  return new Promise((resolve) => {
    const d = dialog(`
      <div class="identify">
        <div class="identify-head">
          <div><h2>Quem é a pessoa?</h2>
            <p class="hint">${esc(ev.message)} · ${esc(ev.camera_name)} · ${fmtDateTime(ev.created_at)}</p></div>
          <button type="button" class="secondary small" data-close aria-label="Fechar">✕</button>
        </div>
        <div class="identify-body">
          <div class="compare">
            <figure>${ev.image_url ? `<img src="${esc(withToken(ev.image_url))}" alt="Evidência">` : `<div class="noimg">sem imagem</div>`}
              <figcaption>No momento do desvio</figcaption></figure>
            <figure class="cand-photo"><div class="noimg">escolha um candidato</div><figcaption>Foto do cadastro</figcaption></figure>
          </div>
          <div class="cand-side">
            <label>Buscar em toda a unidade <input name="q" placeholder="Nome, matrícula, CPF ou nº do colete"></label>
            <p class="hint cand-context"></p>
            <div class="cand-list" role="radiogroup" aria-label="Candidatos"></div>
          </div>
        </div>
        <p class="notice"><b>A identificação é feita por você.</b> O sistema só ordena os candidatos pelo setor da câmera, pelo turno
          e pelo número do colete. Não há reconhecimento facial e nenhuma medida é aplicada sem confirmação.</p>
        <div class="actions" style="justify-content:space-between">
          <button type="button" class="secondary" data-none>Não foi possível identificar</button>
          <button type="button" data-confirm disabled>Confirmar identificação</button>
        </div>
      </div>`, "panel-dialog");
    let selected = null;
    let method = "lista";
    const list = d.querySelector(".cand-list");
    const load = async (q = "") => {
      const r = await api(`/api/events/${ev.id}/candidates${q ? `?q=${encodeURIComponent(q)}` : ""}`);
      method = q ? (/^\w{2,8}$/.test(q) && r.candidates.some((c) => c.badge_code === q.toUpperCase()) ? "numero" : "busca") : "lista";
      d.querySelector(".cand-context").textContent = q ? `${r.candidates.length} resultado(s) para “${q}”`
        : r.has_sector ? `Setor ${r.sector} · ${r.shift} primeiro · ${r.candidates.length} pessoa(s) ativa(s)`
          : "Esta câmera não tem setor: use a busca.";
      list.innerHTML = r.candidates.map((c) => `
        <label class="cand ${c.id === r.current_person_id ? "current" : ""}">
          <input type="radio" name="cand" value="${c.id}" ${c.id === r.current_person_id ? "checked" : ""}>
          ${photo(c)}
          <span class="cand-info"><b>${esc(c.name)}</b>
            <small>${esc(c.role || "–")} · ${esc(c.shift || "sem turno")}${c.badge_code ? ` · colete <span class="mono">${esc(c.badge_code)}</span>` : ""}</small></span>
          ${c.same_shift ? badge("no turno", "good") : ""}
          ${c.recent ? badge(`${c.recent} em ${r.window_days} dias`, "warn") : ""}
        </label>`).join("") || `<p class="hint">Ninguém encontrado.</p>`;
      list.querySelectorAll("input").forEach((i) => i.addEventListener("change", () => pick(r.candidates.find((c) => c.id === Number(i.value)))));
      const current = r.candidates.find((c) => c.id === r.current_person_id);
      if (current) pick(current);
    };
    const pick = (c) => {
      selected = c;
      d.querySelector(".cand-photo").innerHTML = `${c.has_photo ? `<img src="${esc(withToken(`/api/people/${c.id}/photo`))}" alt="">`
        : `<div class="noimg">sem foto no cadastro</div>`}<figcaption>${esc(c.name)} · ${esc(c.cpf)}</figcaption>`;
      d.querySelector("[data-confirm]").disabled = false;
    };
    let timer;
    d.querySelector("[name=q]").addEventListener("input", (e) => { clearTimeout(timer); timer = setTimeout(() => load(e.target.value.trim()), 250); });
    const send = async (personId) => {
      try {
        await api(`/api/events/${ev.id}/identify`, { method: "POST", body: { person_id: personId, method } });
        d.close();
        resolve(true);
      } catch (err) { toast(esc(err.message), "danger"); }
    };
    d.querySelector("[data-confirm]").addEventListener("click", () => selected && send(selected.id));
    d.querySelector("[data-none]").addEventListener("click", () => send(null));
    d.addEventListener("close", () => resolve(false));
    load().catch((err) => toast(esc(err.message), "danger"));
  });
}

// ---------- Aplicar medida ----------

const TYPES = [
  ["orientacao", "Orientação registrada", "Conversa no posto de trabalho, registrada com a evidência."],
  ["treinamento", "Encaminhar para treinamento", "Registra o treinamento agendado no cadastro da pessoa."],
  ["advertencia", "Advertência escrita", "Técnicos registram; gestores ou administradores aprovam antes de emitir (CLT art. 158)."],
  ["rh", "Encaminhar ao RH", "Para outras medidas, a critério do RH."],
];

export async function openMeasure(ev) {
  const s = await api(`/api/events/${ev.id}/suggestion`);
  return new Promise((resolve) => {
    const d = dialog(`
      <form class="measure-form">
        <div class="identify-head">
          <div style="display:flex;gap:12px;align-items:center">${photo(s.person, 52)}
            <div><h2 style="margin:0">${esc(s.person.name)}</h2><div class="hint">${esc(s.person.role || "")} · ${esc(s.person.sector || "")} · ${esc(s.person.shift || "")}</div></div></div>
          <button type="button" class="secondary small" data-close aria-label="Fechar">✕</button>
        </div>
        <div class="suggest-box"><span class="pill">SUGERIDO</span> <b>${esc(s.label)}</b> — ${esc(s.reason)}.
          Se houver nova ocorrência até ${fmtDate(s.reset_on)}: ${esc(s.next_label.toLowerCase())}.</div>
        <fieldset class="measure-options"><legend class="label-strong">Medida</legend>
          ${TYPES.map(([v, l, h]) => `<label class="opt-card"><input type="radio" name="type" value="${v}" ${v === s.type ? "checked" : ""}>
            <span><b>${l}</b>${v === s.type ? ` ${badge("sugerida", "good")}` : ""}<small>${h}</small></span></label>`).join("")}
        </fieldset>
        <div class="training-fields form" hidden>
          <label>Treinamento <input name="training_name" list="trainings" value="${esc(s.trainings[0] || "")}"></label>
          <datalist id="trainings">${s.trainings.map((t) => `<option value="${esc(t)}">`).join("")}</datalist>
          <label>Data <input name="training_date" type="date" value="${isoDate(new Date(Date.now() + 7 * 86400000))}"></label>
        </div>
        <label>Descrição dos fatos
          <textarea name="description" rows="3">Em ${fmtDateTime(ev.created_at)}, ${esc(ev.camera_name)}: ${esc(ev.message.toLowerCase())}.</textarea></label>
        <label class="justify" hidden>Justificativa (a medida é diferente da sugerida)
          <textarea name="justification" rows="2" placeholder="Por que outra medida? (mín. 10 caracteres)"></textarea></label>
        <p class="hint">Evidência: ${s.has_evidence ? "foto/clipe da ocorrência anexados ao termo." : "<span class='warn-text'>esta ocorrência não tem foto nem clipe.</span>"}</p>
        <div class="actions" style="justify-content:flex-end">
          <button type="button" class="secondary" data-close>Cancelar</button>
          <button type="submit">Registrar medida</button>
        </div>
      </form>`);
    const form = d.querySelector("form");
    const sync = () => {
      const type = form.type.value;
      d.querySelector(".training-fields").hidden = type !== "treinamento";
      d.querySelector(".justify").hidden = type === s.type;
    };
    form.querySelectorAll("[name=type]").forEach((r) => r.addEventListener("change", sync));
    sync();
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      try {
        const m = await api("/api/measures", { method: "POST", body: {
          event_id: ev.id, type: form.type.value, description: form.description.value, justification: form.justification.value,
          training_name: form.type.value === "treinamento" ? form.training_name.value : "",
          training_date: form.type.value === "treinamento" ? (form.training_date.value || null) : null } });
        d.close();
        toast(m.status === "pendente_aprovacao" ? `Medida ${m.number} registrada; aguardando aprovação de um gestor.`
          : `Medida ${m.number} registrada.`, "ok", 5000);
        resolve(m);
      } catch (err) { toast(esc(err.message), "danger", 8000); }
    });
    d.addEventListener("close", () => resolve(null));
  });
}

// ---------- Ciência do colaborador ----------

export function openAck(m) {
  return new Promise((resolve) => {
    const d = dialog(`
      <form class="ack-form">
        <div class="identify-head"><div><h2 style="margin:0">Ciência do colaborador</h2><div class="hint mono">${esc(m.number)}</div></div>
          <button type="button" class="secondary small" data-close aria-label="Fechar">✕</button></div>
        <p class="ack-text">${esc(m.person_name)}: ${esc(m.description || m.event_message || "")}
          <br><b>Medida: ${esc(m.label)}</b>${m.training_name ? ` — ${esc(m.training_name)}${m.training_date ? ` em ${fmtDate(m.training_date)}` : ""}` : ""}.</p>
        <div class="tabs ack-tabs">
          <button type="button" class="small" data-mode="assinada">Assinar na tela</button>
          <button type="button" class="small secondary" data-mode="impressa">Termo impresso</button>
          <button type="button" class="small secondary" data-mode="recusada">Recusou assinar</button>
        </div>
        <div data-pane="assinada">
          <div class="sign-wrap"><canvas class="sign"></canvas><button type="button" class="secondary small sign-clear">Limpar</button></div>
          <label class="check"><input type="checkbox" name="aware"> Li o termo. Assinar indica que estou ciente, não que concordo.</label>
        </div>
        <div data-pane="impressa" hidden><p class="hint">Imprima o termo, colha a assinatura no papel e arquive. <a href="termo.html?id=${m.id}" target="_blank">Abrir termo para impressão</a></p></div>
        <div data-pane="recusada" hidden><label>Testemunhas (nome e função)<input name="witnesses" placeholder="ex.: Elaine Prado (líder), João Vieira (operador)"></label></div>
        <label>Versão do colaborador (opcional)<textarea name="statement" rows="2" placeholder="O que o colaborador quiser registrar sobre os fatos"></textarea></label>
        <div class="actions" style="justify-content:flex-end">
          <button type="button" class="secondary" data-close>Depois</button>
          <button type="submit">Registrar ciência</button>
        </div>
      </form>`, "form-dialog ack-dialog");
    const form = d.querySelector("form");
    let mode = "assinada";
    d.querySelectorAll("[data-mode]").forEach((b) => b.addEventListener("click", () => {
      mode = b.dataset.mode;
      d.querySelectorAll("[data-mode]").forEach((x) => x.classList.toggle("secondary", x !== b));
      d.querySelectorAll("[data-pane]").forEach((p) => { p.hidden = p.dataset.pane !== mode; });
    }));
    // assinatura com o dedo ou mouse
    const canvas = d.querySelector("canvas.sign");
    const ctx = canvas.getContext("2d");
    let drawing = false;
    let signed = false;
    const resize = () => {
      canvas.width = canvas.clientWidth * devicePixelRatio;
      canvas.height = canvas.clientHeight * devicePixelRatio;
      ctx.scale(devicePixelRatio, devicePixelRatio);
      ctx.lineWidth = 2.4; ctx.lineCap = "round"; ctx.strokeStyle = "#111";
    };
    requestAnimationFrame(resize);
    const pos = (e) => { const r = canvas.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
    canvas.addEventListener("pointerdown", (e) => { drawing = true; signed = true; canvas.setPointerCapture(e.pointerId); ctx.beginPath(); ctx.moveTo(...pos(e)); });
    canvas.addEventListener("pointermove", (e) => { if (drawing) { ctx.lineTo(...pos(e)); ctx.stroke(); } });
    canvas.addEventListener("pointerup", () => { drawing = false; });
    d.querySelector(".sign-clear").addEventListener("click", () => { ctx.clearRect(0, 0, canvas.width, canvas.height); signed = false; });
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const body = { ack: mode, statement: form.statement.value, witnesses: form.witnesses.value };
      if (mode === "assinada") {
        if (!signed) return toast("Peça ao colaborador para assinar no quadro.", "warn");
        if (!form.aware.checked) return toast("Marque a confirmação de leitura.", "warn");
        // fundo branco para a assinatura ficar legível no termo impresso
        const out = document.createElement("canvas");
        out.width = canvas.width; out.height = canvas.height;
        const o = out.getContext("2d");
        o.fillStyle = "#fff"; o.fillRect(0, 0, out.width, out.height); o.drawImage(canvas, 0, 0);
        body.signature = out.toDataURL("image/png");
      }
      try {
        const r = await api(`/api/measures/${m.id}/ack`, { method: "POST", body });
        d.close();
        toast("Ciência registrada.", "ok", 3000);
        resolve(r);
      } catch (err) { toast(esc(err.message), "danger"); }
    });
    d.addEventListener("close", () => resolve(null));
  });
}

export async function decideMeasure(m, approve) {
  const note = approve ? "" : (prompt("Motivo da recusa (opcional):") ?? "");
  return api(`/api/measures/${m.id}/decision`, { method: "POST", body: { approve, note } });
}

export const canManage = () => can("tecnico");
