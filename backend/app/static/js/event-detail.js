// Detalhe da ocorrência: evidência, triagem, classificação, plano de ação e histórico.

import { attachmentsHtml, openActionForm, runActionButton } from "./actions-ui.js";
import { mountClipPlayer } from "./clip-player.js";
import { decideMeasure, openAck, openIdentify, openMeasure } from "./measures-ui.js";
import {
  $, ACTION_STATUS, CLASS_LABELS, TYPE_LABELS, api, badge, can, esc, fmtDate, fmtDateTime, session,
  statusBadge, toast, withToken,
} from "./core.js";

const dialog = () => $("#event-dialog");
let currentId = null;
let stopClip = () => {};
let onChange = () => {};

export function setEventChangeHandler(fn) { onChange = fn; }

export async function openEvent(id) {
  currentId = id;
  let ev;
  try {
    ev = await api(`/api/events/${id}`);
  } catch (err) {
    toast(esc(err.message), "danger");
    return;
  }
  render(ev);
  if (!dialog().open) dialog().showModal();
}

export function refreshIfOpen(id) {
  // Não atrapalha quem está digitando no detalhe
  const editing = dialog().contains(document.activeElement) && document.activeElement.matches("textarea, input, select");
  if (dialog().open && currentId === id && !editing) openEvent(id);
}

function actionRow(a) {
  const mine = a.responsible_id === session.user.id;
  const buttons = a.status !== "aberta" ? "" : `
    ${can("tecnico") || mine ? `<button class="small" data-act="complete" data-id="${a.id}">Concluir</button>` : ""}
    ${can("tecnico") ? `<button class="small secondary" data-act="edit" data-id="${a.id}">Editar</button>
      <button class="small danger" data-act="cancel" data-id="${a.id}">Cancelar</button>` : ""}`;
  return `
    <li class="action-item ${a.overdue ? "overdue" : ""}">
      <div>
        <b>${esc(a.title)}</b> ${badge(ACTION_STATUS[a.status], `ac-${a.status}`)}
        ${a.overdue ? badge("▲ Atrasada", "bad") : ""}
        <div class="hint">${esc(a.responsible_name || "Sem responsável")} · prazo ${fmtDate(a.due_date)}</div>
        ${a.description ? `<div>${esc(a.description)}</div>` : ""}
        ${a.completion_notes ? `<div class="evidence">✔ ${esc(a.completion_notes)}</div>` : ""}
        ${attachmentsHtml(a)}
      </div>
      <div class="actions">${buttons}</div>
    </li>`;
}

const MEASURE_STATUS = { pendente_aprovacao: ["aguardando aprovação", "warn"], aplicada: ["aplicada", "good"], cancelada: ["cancelada", "muted"] };
const ACK_KIND = { pendente: "warn", assinada: "good", impressa: "good", recusada: "bad" };

function personSection(ev) {
  if (!can("tecnico") || ev.status === "nova" || ev.status === "descartada") return "";
  const who = ev.person_id
    ? `<a href="#cadastros" data-history="${ev.person_id}"><b>${esc(ev.person_name)}</b></a>
       <span class="hint">identificada por ${esc(ev.identified_by || "–")} em ${fmtDateTime(ev.identified_at)}</span>`
    : ev.identification === "nao_identificado" ? `<span class="hint">Não foi possível identificar (${esc(ev.identified_by || "–")})</span>`
      : `<span class="hint">Pessoa ainda não identificada.</span>`;
  const measures = (ev.measures || []).map((m) => `
    <li class="action-item">
      <div><b>${esc(m.label)}</b> <span class="mono hint">${esc(m.number)}</span>
        ${badge(MEASURE_STATUS[m.status][0], MEASURE_STATUS[m.status][1])} ${m.status === "aplicada" ? badge(`ciência: ${m.ack_label}`, ACK_KIND[m.ack]) : ""}
        <div class="hint">${esc(m.created_by || "")} · ${fmtDateTime(m.created_at)}${m.training_name ? ` · ${esc(m.training_name)}` : ""}${m.justification ? ` · justificativa: ${esc(m.justification)}` : ""}</div>
        ${m.statement ? `<div class="evidence">Versão do colaborador: ${esc(m.statement)}</div>` : ""}</div>
      <div class="actions">
        <a class="small-link" href="termo.html?id=${m.id}" target="_blank">Termo</a>
        ${m.status === "pendente_aprovacao" && can("gestor") ? `<button class="small" data-decide="1" data-id="${m.id}">Aprovar</button>
          <button class="small danger" data-decide="0" data-id="${m.id}">Recusar</button>` : ""}
        ${m.status === "aplicada" && m.ack === "pendente" ? `<button class="small" data-ack="${m.id}">Colher ciência</button>` : ""}
      </div>
    </li>`).join("");
  return `
    <h3 id="person-section">Pessoa envolvida e medidas</h3>
    ${!ev.person_id && ev.identification !== "nao_identificado" ? `
      <div class="identify-callout">
        <span class="identify-ico" aria-hidden="true">👤</span>
        <div><b>Quem é a pessoa nesta ocorrência?</b>
          <p>Identifique o colaborador para registrar orientação, treinamento ou advertência no histórico dele.
            A escolha é feita por você (sem reconhecimento facial).</p></div>
        <button id="identify-btn" class="identify-main">Identificar pessoa</button>
      </div>` : `
    <div class="person-line">${who}
      <span class="actions">
        <button class="small secondary" id="identify-btn">${ev.person_id ? "Alterar" : "Tentar novamente"}</button>
        ${ev.person_id ? `<button class="small" id="measure-btn">Aplicar medida</button>` : ""}
      </span>
    </div>`}
    ${measures ? `<ul class="action-list">${measures}</ul>` : ""}`;
}

function render(ev) {
  const open = ev.status === "nova" || ev.status === "confirmada";
  const statusButtons = [];
  if (ev.status === "nova") {
    statusButtons.push(`<button data-status="confirmada">Confirmar desvio</button>`,
      `<button class="secondary" data-status="descartada">Falso alarme</button>`);
  }
  if (ev.status === "confirmada" && can("tecnico")) {
    statusButtons.push(`<button data-status="encerrada" ${ev.open_actions ? "disabled title='Conclua as ações abertas'" : ""}>Encerrar ocorrência</button>`);
  }
  if (ev.status === "confirmada" && can("tecnico") && !ev.person_id && ev.identification !== "nao_identificado") {
    statusButtons.push(`<button class="secondary" data-jump-identify>👤 Identificar pessoa</button>`);
  }
  if ((ev.status === "descartada" || ev.status === "encerrada") && can("tecnico")) {
    statusButtons.push(`<button class="secondary" data-status="confirmada">Reabrir</button>`);
  }

  dialog().innerHTML = `
    <div class="detail">
      <div class="detail-head">
        <div>
          <h2>#${ev.id} · ${esc(ev.message)}</h2>
          <div class="hint">${esc(ev.camera_name)}${ev.location ? ` · ${esc(ev.location)}` : ""} ·
            ${esc(TYPE_LABELS[ev.type] || ev.type)} · ${fmtDateTime(ev.created_at)}</div>
        </div>
        <div>${statusBadge(ev.status)} ${badge(`severidade ${ev.severity}`, `sev-${ev.severity}`)}</div>
        <button class="secondary small" data-close aria-label="Fechar">✕</button>
      </div>

      <div class="detail-body">
        <div>
          ${ev.clip_frames ? `<div class="tabs media-tabs">
              <button type="button" class="small" data-media="clip">Vídeo</button>
              <button type="button" class="small secondary" data-media="photo">Foto do momento</button></div>` : ""}
          <div id="media"></div>
          ${ev.reviewed_by ? `<p class="hint">Triagem por ${esc(ev.reviewed_by)} em ${fmtDateTime(ev.reviewed_at)}</p>` : ""}
        </div>

        <div class="detail-side">
          <form id="triage-form" class="stack">
            <label>Classificação
              <select name="classification" ${ev.status === "encerrada" && !can("tecnico") ? "disabled" : ""}>
                <option value="">Selecione…</option>
                ${Object.entries(CLASS_LABELS).filter(([k]) => k !== "nao_classificada").map(([k, v]) =>
                  `<option value="${k}" ${ev.classification === k ? "selected" : ""}>${v}</option>`).join("")}
              </select>
            </label>
            <label>Observações
              <textarea name="notes" rows="3" placeholder="Contexto, pessoas envolvidas (sem nomes, se possível), causas…">${esc(ev.notes || "")}</textarea>
            </label>
            <button type="submit" class="secondary">Salvar classificação</button>
          </form>
          <div class="actions">${statusButtons.join("")}</div>
        </div>
      </div>

      ${personSection(ev)}

      <h3>Plano de ação ${ev.open_actions ? badge(`${ev.open_actions} aberta(s)`, "warn") : ""}</h3>
      <ul class="action-list">${ev.actions.map(actionRow).join("") || `<li class="hint">Nenhuma ação registrada.</li>`}</ul>
      ${can("tecnico") && open ? `<button id="add-action">+ Adicionar ação</button>` : ""}

      <h3>Histórico</h3>
      <ol class="timeline">
        <li><span>${fmtDateTime(ev.created_at)}</span> Detectado automaticamente pela câmera ${esc(ev.camera_name)}</li>
        ${ev.history.map((h) => `<li><span>${fmtDateTime(h.created_at)}</span> <b>${esc(h.user_name)}</b> – ${esc(h.details)}</li>`).join("")}
      </ol>
    </div>`;

  const d = dialog();
  const media = d.querySelector("#media");
  const showPhoto = () => {
    stopClip();
    media.innerHTML = ev.image_url
      ? `<img class="evidence-img" src="${esc(withToken(ev.image_url))}" data-full="${esc(withToken(ev.image_url))}" alt="Evidência">
         ${ev.media_at_edge ? `<p class="hint edge-note">📍 Imagem guardada no storage da planta (VigIA Edge)</p>` : ""}`
      : `<div class="noimg">${ev.clip_frames ? "sem foto" : "sem imagem (apagada pela política de retenção ou não enviada)"}</div>`;
    const img = media.querySelector(".evidence-img");
    // Edge desconectado: mostra a miniatura que fica na nuvem
    if (img && ev.thumb_url) {
      img.addEventListener("error", () => {
        if (img.dataset.fallback) return;
        img.dataset.fallback = "1";
        img.src = withToken(ev.thumb_url);
        media.querySelector(".edge-note")?.remove();
        img.insertAdjacentHTML("afterend", `<p class="hint warn-text">A imagem completa está no storage da planta e o VigIA Edge
          está desconectado agora. Mostrando a miniatura.</p>`);
      }, { once: false });
    }
  };
  const showClip = () => { stopClip(); stopClip = mountClipPlayer(media, ev.id, ev.clip_frames, ev.clip_duration); };
  ev.clip_frames ? showClip() : showPhoto();
  d.querySelectorAll("[data-media]").forEach((btn) => btn.addEventListener("click", () => {
    d.querySelectorAll("[data-media]").forEach((b) => b.classList.toggle("secondary", b !== btn));
    btn.dataset.media === "clip" ? showClip() : showPhoto();
  }));

  const reload = async () => { await openEvent(ev.id); onChange(); };

  d.querySelector("#identify-btn")?.addEventListener("click", async () => { if (await openIdentify(ev)) reload(); });
  d.querySelector("[data-jump-identify]")?.addEventListener("click", async () => { if (await openIdentify(ev)) reload(); });
  d.querySelector("#measure-btn")?.addEventListener("click", async () => {
    try {
      const m = await openMeasure(ev);
      if (!m) return;
      await reload();
      if (m.status === "aplicada" && confirm("Colher a ciência do colaborador agora?")) { await openAck(m); reload(); }
    } catch (err) { toast(esc(err.message), "danger"); }
  });
  d.querySelectorAll("[data-ack]").forEach((b) => b.addEventListener("click", async () => {
    if (await openAck(ev.measures.find((m) => m.id === Number(b.dataset.ack)))) reload();
  }));
  d.querySelectorAll("[data-decide]").forEach((b) => b.addEventListener("click", async () => {
    try {
      await decideMeasure(ev.measures.find((m) => m.id === Number(b.dataset.id)), b.dataset.decide === "1");
      reload();
    } catch (err) { toast(esc(err.message), "danger"); }
  }));

  d.querySelector("#triage-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = e.target;
    const body = { notes: f.notes.value };
    if (f.classification.value) body.classification = f.classification.value;
    try {
      await api(`/api/events/${ev.id}`, { method: "PATCH", body });
      toast("Classificação salva.", "ok", 2000);
      reload();
    } catch (err) { toast(esc(err.message), "danger"); }
  });

  d.querySelectorAll("[data-status]").forEach((btn) => btn.addEventListener("click", async () => {
    const body = { status: btn.dataset.status };
    const cls = d.querySelector("[name=classification]").value;
    if (cls) body.classification = cls;
    try {
      await api(`/api/events/${ev.id}`, { method: "PATCH", body });
      reload();
    } catch (err) { toast(esc(err.message), "danger"); }
  }));

  d.querySelector("#add-action")?.addEventListener("click", async () => {
    if (await openActionForm({ eventId: ev.id, eventMessage: ev.message })) reload();
  });

  d.querySelectorAll("[data-act]").forEach((btn) => btn.addEventListener("click", async () => {
    const action = ev.actions.find((a) => a.id === Number(btn.dataset.id));
    try {
      if (await runActionButton(btn, action)) reload();
    } catch (err) { toast(esc(err.message), "danger"); }
  }));
}

// Ao fechar, limpa o endereço #ocorrencia-N
dialog().addEventListener("close", () => {
  currentId = null;
  stopClip();
  if (location.hash.startsWith("#ocorrencia-")) {
    history.replaceState(null, "", $("#nav a.active")?.getAttribute("href") || "#ocorrencias");
  }
});
