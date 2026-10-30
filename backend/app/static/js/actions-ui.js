// Formulários de ação (criar/editar e concluir), usados na ocorrência e no plano de ação.

import { $, api, esc, toast, userOptions } from "./core.js";

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

/** Pede a evidência do que foi feito e conclui a ação. */
export function openCompleteForm(action) {
  const dialog = $("#complete-dialog");
  const f = $("#complete-form");
  f.reset();
  f.id.value = action.id;
  $("#complete-title").textContent = action.title;
  return waitDialog(dialog, f, () => api(`/api/actions/${action.id}`, {
    method: "PATCH", body: { status: "concluida", completion_notes: f.completion_notes.value },
  }));
}

export async function cancelAction(action) {
  if (!confirm(`Cancelar a ação "${action.title}"?`)) return null;
  return api(`/api/actions/${action.id}`, { method: "PATCH", body: { status: "cancelada" } });
}
