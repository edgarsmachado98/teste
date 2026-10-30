import { getUsers } from "../actions-ui.js";
import { $, ROLE_LABELS, api, badge, esc, fmtDateTime, toast } from "../core.js";

let el;
let users = [];

async function load() {
  users = await getUsers(true);
  $("#users-table", el).innerHTML = `
    <tr><th>Nome</th><th>E-mail</th><th>Perfil</th><th>Situação</th><th>Último acesso</th><th></th></tr>
    ${users.map((u) => `
      <tr>
        <td>${esc(u.name)}</td><td>${esc(u.email)}</td><td>${esc(ROLE_LABELS[u.role])}</td>
        <td>${u.active ? badge("Ativo", "good") : badge("Inativo", "muted")}</td>
        <td>${u.last_login_at ? fmtDateTime(u.last_login_at) : "–"}</td>
        <td><button class="small secondary" data-edit="${u.id}">Editar</button></td>
      </tr>`).join("")}`;
}

function openForm(user = null) {
  const f = $("#user-form");
  f.reset();
  $("#user-form-title").textContent = user ? "Editar usuário" : "Novo usuário";
  f.id.value = user?.id ?? "";
  f.name.value = user?.name ?? "";
  f.email.value = user?.email ?? "";
  f.role.value = user?.role ?? "operador";
  f.active.checked = user?.active ?? true;
  f.password.required = !user;
  f.password.placeholder = user ? "deixe em branco para manter" : "mín. 8 caracteres";
  $("#user-dialog").showModal();
}

export async function show(element) {
  el = element;
  el.innerHTML = `
    <div class="toolbar"><h2>Usuários</h2><button id="user-new">+ Novo usuário</button></div>
    <p class="hint">Desative usuários que saíram da empresa em vez de excluí-los: o histórico das
      ocorrências continua mostrando quem fez cada ação.</p>
    <div class="table-wrap"><table id="users-table"></table></div>`;
  $("#user-new", el).addEventListener("click", () => openForm());
  $("#users-table", el).addEventListener("click", (e) => {
    const id = e.target.dataset.edit;
    if (id) openForm(users.find((u) => u.id === Number(id)));
  });
  await load();
}

$("#user-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  const body = { name: f.name.value, email: f.email.value, role: f.role.value, active: f.active.checked,
    password: f.password.value || null };
  try {
    await api(f.id.value ? `/api/users/${f.id.value}` : "/api/users", { method: f.id.value ? "PUT" : "POST", body });
    $("#user-dialog").close();
    toast("Usuário salvo.", "ok", 2500);
    load();
  } catch (err) { toast(esc(err.message), "danger"); }
});
