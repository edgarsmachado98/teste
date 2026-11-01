// Formulários de ação (criar/editar e concluir), usados na ocorrência e no plano de ação.

import { $, api, can, esc, fmtDateTime, session, toast, userOptions, withToken } from "./core.js";

let usersCache = null;
export async function getUsers(force = false) {
  if (!usersCache || force) usersCache = await api("/api/users");
  return usersCache;
}

function waitDialog(dialog, form, submit) {
  return new Promise((resolve) => {
    const onSubmit = async (e) => {
      e.preventDefault();
      try {
        const result = await submit();
        cleanup();
        dialog.close();
        resolve(result);
      } catch (err) { toast(esc(err.message), "danger"); }
    };
    const onClose = () => { cleanup(); resolve(null); };
    const cleanup = () => {
      form.removeEventListener("submit", onSubmit);
      dialog.removeEventListener("close", onClose);
    };
    form.addEventListener("submit", onSubmit);
    dialog.addEventListener("close", onClose);
    dialog.showModal();
  });
}

/** Abre o formulário de ação. Resolve com a ação salva, ou null se cancelado. */
export async function openActionForm({ eventId = null, eventMessage = "", action = null } = {}) {
  const dialog = $("#action-dialog");
  const f = $("#action-form");
  f.reset();
  const users = await getUsers();
  f.id.value = action?.id ?? "";
  f.event_id.value = action?.event_id ?? eventId ?? "";
  $("#action-form-title").textContent = action ? "Editar ação" : "Nova ação";
  $("#action-event").textContent = (action?.event_message || eventMessage)
    ? `Ocorrência: ${action?.event_message || eventMessage}` : "Ação avulsa (sem ocorrência vinculada)";
  f.title.value = action?.title ?? "";
  f.description.value = action?.description ?? "";
  f.responsible_id.innerHTML = userOptions(users, action?.responsible_id ?? null);
  f.due_date.value = action?.due_date ?? "";

  return waitDialog(dialog, f, () => {
    const body = {
      title: f.title.value,
      description: f.description.value,
      responsible_id: f.responsible_id.value ? Number(f.responsible_id.value) : null,
      due_date: f.due_date.value || null,
    };
    if (f.id.value) return api(`/api/actions/${f.id.value}`, { method: "PATCH", body });
    return api("/api/actions", { method: "POST", body: { ...body, event_id: f.event_id.value ? Number(f.event_id.value) : null } });
  });
}

// ---------- Anexos (comprovantes da medida tomada) ----------
const MAX_MB = 10;

/** Sugere o tipo de documento pelo título da ação. */
function guessKind(action) {
  const t = `${action.title} ${action.description || ""}`.toLowerCase();
  if (/advert[eê]ncia/.test(t)) return "advertencia_assinada";
  if (/\bdds\b|di[aá]logo/.test(t)) return "dds";
  if (/treinamento|reciclagem|capacita/.test(t)) return "ata_treinamento";
  return "outro";
}

async function uploadFiles(actionId, files, kind) {
  const list = [...files];
  const big = list.find((f) => f.size > MAX_MB * 1024 * 1024);
  if (big) throw new Error(`"${big.name}" tem mais de ${MAX_MB} MB.`);
  for (const file of list) {
    const body = new FormData();
    body.append("file", file);
    body.append("kind", kind);
    await api(`/api/actions/${actionId}/attachments`, { method: "POST", body });
  }
  return list.length;
}

const canAttach = (a) => a.status !== "cancelada" && (can("tecnico") || a.responsible_id === session.user.id);
const canDetach = (a, att) => (a.status === "concluida" ? can("gestor")
  : can("tecnico") || (a.status === "aberta" && att.uploaded_by_id === session.user.id));
const fmtSize = (n) => (n >= 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`);

/** Lista de anexos da ação + botão "Anexar documento" (usada na ocorrência e no plano de ação). */
export function attachmentsHtml(a) {
  const items = (a.attachments || []).map((att) => {
    const icon = att.content_type === "application/pdf" ? "PDF" : "IMG";
    const link = can("tecnico") || a.responsible_id === session.user.id
      ? `<a href="${esc(withToken(`/api/attachments/${att.id}`))}" target="_blank" rel="noopener">${esc(att.filename)}</a>`
      : esc(att.filename);
    return `<li><span class="file-ico">${icon}</span>
      <span class="att-info">${link}<small>${esc(att.kind_label)} · ${fmtSize(att.size)} · ${esc(att.uploaded_by || "–")}, ${fmtDateTime(att.created_at)}</small></span>
      ${canDetach(a, att) ? `<button class="small danger" data-act="detach" data-id="${a.id}" data-att="${att.id}" title="Remover anexo">Remover</button>` : ""}</li>`;
  }).join("");
  const add = canAttach(a) ? `<button class="small secondary" data-act="attach" data-id="${a.id}">📎 Anexar documento</button>` : "";
  if (!items && !add) return "";
  return `<div class="attachments">${items ? `<ul>${items}</ul>` : ""}${add}</div>`;
}

/** Anexa documentos a uma ação (aberta ou já concluída, ex.: a via assinada chegou depois). */
export function openAttachForm(action) {
  const dialog = $("#attach-dialog");
  const f = $("#attach-form");
  f.reset();
  f.kind.value = guessKind(action);
  $("#attach-title").textContent = action.title;
  return waitDialog(dialog, f, async () => {
    const n = await uploadFiles(action.id, f.files.files, f.kind.value);
    toast(n === 1 ? "Documento anexado." : `${n} documentos anexados.`, "ok", 2500);
    return true;
  });
}

export async function removeAttachment(action, btn) {
  const att = action.attachments.find((x) => x.id === Number(btn.dataset.att));
  if (!att || !confirm(`Remover o anexo "${att.filename}"? A remoção fica registrada na auditoria.`)) return null;
  await api(`/api/attachments/${att.id}`, { method: "DELETE" });
  return true;
}

/** Pede a evidência do que foi feito (e, opcionalmente, o comprovante assinado) e conclui a ação. */
export function openCompleteForm(action) {
  const dialog = $("#complete-dialog");
  const f = $("#complete-form");
  f.reset();
  f.id.value = action.id;
  f.kind.value = guessKind(action);
  $("#complete-title").textContent = action.title;
  return waitDialog(dialog, f, async () => {
    // Anexa primeiro: se o envio falhar, a ação continua aberta e nada se perde.
    if (f.files.files.length) await uploadFiles(action.id, f.files.files, f.kind.value);
    return api(`/api/actions/${action.id}`, {
      method: "PATCH", body: { status: "concluida", completion_notes: f.completion_notes.value },
    });
  });
}

/** Ações dos botões de uma ação (mesmo mapa na ocorrência e no plano de ação). */
export function runActionButton(btn, action) {
  const fn = { complete: openCompleteForm, cancel: cancelAction, edit: (a) => openActionForm({ action: a }),
    attach: openAttachForm, detach: removeAttachment }[btn.dataset.act];
  return fn ? fn(action, btn) : null;
}

export async function cancelAction(action) {
  if (!confirm(`Cancelar a ação "${action.title}"?`)) return null;
  return api(`/api/actions/${action.id}`, { method: "PATCH", body: { status: "cancelada" } });
}
