// Guia Configurações (administradores): armazenamento de rede, backup e restauração.

import { collect, field, fmtBytes, saveConfig } from "../config-form.js";
import { $, api, badge, esc, fmtDateTime, toast, withToken } from "../core.js";

let el;
let cfg;

const NAS_FIELDS = ["storage_nas_path", "storage_nas_user", "storage_nas_password", "storage_mode",
  "storage_local_days", "storage_sync_interval", "storage_offline_alert_minutes", "storage_backup_keep"];
const BACKUP_FIELDS = ["backup_hour", "backup_keep", "backup_copy_dir"];
const KIND = { banco: "Banco de dados", completo: "Completo (com evidências)", seguranca: "Segurança (antes de restaurar)",
  importado: "Enviado" };

function nasStatus(n) {
  if (!n.enabled) return badge("Não configurado", "muted");
  if (n.online) return badge("● Conectado", "good");
  if (!n.activated && (n.error || "").includes("ativado")) return badge("Aguardando ativação", "warn");
  return badge("▲ Inacessível", "bad");
}

function renderNas() {
  const v = cfg.values;
  const n = cfg.storage;
  const used = n.total_bytes ? (1 - n.free_bytes / n.total_bytes) * 100 : null;
  $("#cfg-nas", el).innerHTML = `
    <div class="status-line">${nasStatus(n)}
      ${n.enabled && n.online ? `<span>${fmtBytes(n.free_bytes)} livres de ${fmtBytes(n.total_bytes)}</span>
        <div class="bartrack space"><div class="barfill" style="width:${used.toFixed(1)}%"></div></div>` : ""}
      ${n.enabled && !n.online && n.error ? `<span class="hint">${esc(n.error)}</span>` : ""}
    </div>
    ${n.enabled ? `<p class="hint">Aguardando envio: ${n.pending_events} ocorrência(s)${n.pending_deletions
      ? ` · ${n.pending_deletions} exclusão(ões) pendente(s)` : ""} · última sincronização:
      ${n.last_sync ? fmtDateTime(n.last_sync) : "–"}</p>` : ""}
    <form id="nas-form" class="form">
      ${field(v, "storage_nas_path", "Caminho da pasta de rede", { wide: true, placeholder: "\\\\192.168.0.20\\vigia",
        hint: "Windows: \\\\servidor\\pasta. Linux: ponto de montagem (ex.: /mnt/nas/vigia). Vazio = desligado." })}
      ${field(v, "storage_nas_user", "Usuário do NAS", { hint: "Usuário próprio do VigIA, com acesso só a esta pasta." })}
      ${field(v, "storage_nas_password", "Senha do NAS", { type: "secret" })}
      ${field(v, "storage_mode", "Modo", { choices: [["espelho", "Espelho – cópia de segurança de tudo"],
        ["principal", "Principal – NAS guarda tudo, este computador só os últimos dias"]] })}
      ${field(v, "storage_local_days", "Dias no disco local (modo principal)", { type: "number", min: 1, max: 3650, suffix: "dias" })}
      ${field(v, "storage_sync_interval", "Intervalo de envio", { type: "number", min: 10, max: 3600, suffix: "s" })}
      ${field(v, "storage_offline_alert_minutes", "Alertar se inacessível por", { type: "number", min: 1, max: 1440, suffix: "min" })}
      ${field(v, "storage_backup_keep", "Backups guardados no NAS", { type: "number", min: 1, max: 1000 })}
      <div class="actions">
        <button type="button" id="nas-test" class="secondary">Testar conexão</button>
        <button type="submit">Salvar</button>
        ${n.enabled && !n.activated ? `<button type="button" id="nas-activate">Ativar pasta</button>` : ""}
        ${n.enabled && n.activated ? `<button type="button" id="nas-sync" class="secondary">Sincronizar agora</button>` : ""}
      </div>
      <p id="nas-test-result" class="wide"></p>
    </form>`;

  const form = $("#nas-form", el);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const saved = await saveConfig(collect(form, NAS_FIELDS));
    if (saved) { cfg = saved; renderNas(); }
  });
  $("#nas-test", el).addEventListener("click", async (e) => {
    e.target.disabled = true;
    const out = $("#nas-test-result", el);
    out.textContent = "Testando…";
    try {
      const r = await api("/api/config/storage/test", { method: "POST", body: {
        path: form.storage_nas_path.value, user: form.storage_nas_user.value, password: form.storage_nas_password.value || null } });
      out.innerHTML = r.ok
        ? `${badge("✔ OK", "good")} ${esc(r.message)} · ${fmtBytes(r.free_bytes)} livres de ${fmtBytes(r.total_bytes)}`
        : `${badge("✖ Falhou", "bad")} ${esc(r.message)}`;
    } catch (err) { out.innerHTML = `${badge("✖ Falhou", "bad")} ${esc(err.message)}`; }
    e.target.disabled = false;
  });
  $("#nas-activate", el)?.addEventListener("click", async () => {
    if (!confirm(`Confirma que ${n.path} é a pasta do storage de rede reservada para o VigIA?`)) return;
    try {
      await api("/api/config/storage/activate", { method: "POST" });
      toast("Armazenamento de rede ativado. As evidências começam a ser enviadas.", "ok");
      await reload();
    } catch (err) { toast(esc(err.message), "danger"); }
  });
  $("#nas-sync", el)?.addEventListener("click", async (e) => {
    e.target.disabled = true;
    try {
      const r = await api("/api/config/storage/sync", { method: "POST" });
      toast(`${r.synced_events} ocorrência(s) enviadas (${r.copied_files} arquivos).`, "ok");
      await reload();
    } catch (err) { toast(esc(err.message), "danger"); e.target.disabled = false; }
  });
}

function renderBackup() {
  const v = cfg.values;
  const sqlite = cfg.database === "sqlite";
  $("#cfg-backup", el).innerHTML = !sqlite
    ? `<p class="hint">Banco PostgreSQL: o backup e a restauração devem ser feitos com <code>pg_dump</code>/<code>pg_restore</code>
        no servidor do banco.</p>`
    : `
    <form id="backup-form" class="form">
      ${field(v, "backup_hour", "Backup automático diário às", { type: "number", min: 0, max: 23, suffix: "h" })}
      ${field(v, "backup_keep", "Quantidade de backups guardados", { type: "number", min: 1, max: 365 })}
      ${field(v, "backup_copy_dir", "Cópia extra em outra pasta (opcional)", { wide: true,
        placeholder: "ex.: D:\\backups\\vigia", hint: `Os backups ficam em <code>${esc(cfg.backup_dir)}</code>.
        Com o NAS configurado, também vão para a pasta <code>backups/</code> dele.` })}
      <div class="actions"><button type="submit" class="secondary">Salvar agendamento</button></div>
    </form>
    <div class="backup-now">
      <label class="check"><input type="checkbox" id="bk-evidence"> Incluir fotos e clipes (arquivo bem maior)</label>
      <button id="bk-now">Fazer backup agora</button>
    </div>
    <div class="table-wrap"><table class="compact">
      <tr><th>Arquivo</th><th>Tipo</th><th>Data</th><th>Tamanho</th><th>Conteúdo</th><th></th></tr>
      ${cfg.backups.map((b) => `<tr>
        <td class="mono">${esc(b.name)}</td><td>${esc(KIND[b.kind] || b.kind)}${b.invalid ? ` ${badge("inválido", "bad")}` : ""}</td>
        <td>${fmtDateTime(b.created_at)}</td><td>${fmtBytes(b.size)}</td>
        <td class="hint">${b.counts ? `${b.counts.events ?? 0} ocorrências · ${b.counts.users ?? 0} usuários`
          + (b.evidence_files ? ` · ${b.evidence_files} arquivos de evidência` : "") : "–"}</td>
        <td class="actions">
          <a class="small-link" href="${esc(withToken(`/api/config/backups/${b.name}`))}">baixar</a>
          <button class="small secondary" data-restore="${esc(b.name)}">restaurar</button>
          <button class="small danger" data-delete="${esc(b.name)}">excluir</button>
        </td></tr>`).join("") || `<tr><td class="hint">Nenhum backup ainda.</td></tr>`}
    </table></div>`;
  if (!sqlite) return;

  const form = $("#backup-form", el);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const saved = await saveConfig(collect(form, BACKUP_FIELDS));
    if (saved) { cfg = saved; renderBackup(); renderRestore(); }
  });
  $("#bk-now", el).addEventListener("click", async (e) => {
    e.target.disabled = true;
    e.target.textContent = "Gerando backup…";
    try {
      const r = await api("/api/config/backups", { method: "POST", body: { include_evidence: $("#bk-evidence", el).checked } });
      toast(`Backup criado: ${esc(r.name)} (${fmtBytes(r.size)})`, "ok");
      await reload();
    } catch (err) {
      toast(esc(err.message), "danger");
      e.target.disabled = false;
      e.target.textContent = "Fazer backup agora";
    }
  });
  $("#cfg-backup", el).querySelectorAll("[data-delete]").forEach((btn) => btn.addEventListener("click", async () => {
    if (!confirm(`Excluir o backup ${btn.dataset.delete}?`)) return;
    try {
      await api(`/api/config/backups/${btn.dataset.delete}`, { method: "DELETE" });
      await reload();
    } catch (err) { toast(esc(err.message), "danger"); }
  }));
  $("#cfg-backup", el).querySelectorAll("[data-restore]").forEach((btn) => btn.addEventListener("click", () => {
    const form = $("#restore-form", el);
    form.source.value = "list";
    form.name.value = btn.dataset.restore;
    toggleSource();
    form.scrollIntoView({ behavior: "smooth" });
    form.confirm.focus();
  }));
}

function toggleSource() {
  const form = $("#restore-form", el);
  if (!form) return;
  const upload = form.source.value === "upload";
  form.querySelector("[data-src=list]").hidden = upload;
  form.querySelector("[data-src=upload]").hidden = !upload;
}

function renderRestore() {
  if (cfg.database !== "sqlite") {
    $("#cfg-restore", el).innerHTML = `<p class="hint">Disponível apenas com o banco SQLite.</p>`;
    return;
  }
  const valid = cfg.backups.filter((b) => !b.invalid);
  $("#cfg-restore", el).innerHTML = `
    <div class="warn-box">
      <b>▲ Atenção:</b> a restauração substitui <b>todos os dados atuais</b> (ocorrências, ações, usuários, câmeras,
      regras e configurações) pelos do backup. Antes, o sistema faz automaticamente um <b>backup de segurança</b>
      do estado atual, que aparece na lista e permite desfazer. Os usuários podem precisar entrar novamente.
    </div>
    <form id="restore-form" class="form">
      <label>Origem
        <select name="source">
          <option value="list">Backup da lista</option>
          <option value="upload">Enviar arquivo (.zip ou .db)</option>
        </select>
      </label>
      <label data-src="list">Backup
        <select name="name">${valid.map((b) => `<option value="${esc(b.name)}">${esc(b.name)} – ${fmtDateTime(b.created_at)}</option>`).join("")
          || `<option value="">nenhum backup disponível</option>`}</select>
      </label>
      <label data-src="upload" hidden>Arquivo de backup <input type="file" name="file" accept=".zip,.db"></label>
      <label>Digite <b>RESTAURAR</b> para confirmar <input name="confirm" autocomplete="off"></label>
      <div class="actions"><button type="submit" class="danger-solid">Restaurar sistema</button></div>
      <p id="restore-result" class="wide"></p>
    </form>`;

  const form = $("#restore-form", el);
  form.source.addEventListener("change", toggleSource);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (form.confirm.value.trim().toUpperCase() !== "RESTAURAR") {
      toast("Digite RESTAURAR para confirmar.", "warn");
      return;
    }
    const btn = form.querySelector("button[type=submit]");
    btn.disabled = true;
    btn.textContent = "Restaurando… não feche esta página";
    const out = $("#restore-result", el);
    try {
      let result;
      if (form.source.value === "upload") {
        if (!form.file.files.length) throw new Error("escolha o arquivo de backup");
        const data = new FormData();
        data.append("file", form.file.files[0]);
        result = await api(`/api/config/restore/upload?confirm=RESTAURAR`, { method: "POST", body: data });
      } else {
        if (!form.name.value) throw new Error("escolha um backup");
        result = await api("/api/config/restore", { method: "POST", body: { name: form.name.value, confirm: "RESTAURAR" } });
      }
      out.innerHTML = `${badge("✔ Restaurado", "good")} a partir de <b>${esc(result.restored_from)}</b>:
        ${result.counts.events ?? 0} ocorrências, ${result.counts.users ?? 0} usuários
        ${result.evidence_files ? `, ${result.evidence_files} arquivos de evidência` : ""}.
        Backup de segurança do estado anterior: <code>${esc(result.safety_backup)}</code>.
        ${result.warnings.length ? `<br>${result.warnings.map(esc).join("<br>")}` : ""}`;
      toast("Sistema restaurado. A página será recarregada.", "ok", 8000);
      setTimeout(() => location.reload(), 4000);
    } catch (err) {
      out.innerHTML = `${badge("✖ Não restaurado", "bad")} ${esc(err.message)}`;
      btn.disabled = false;
      btn.textContent = "Restaurar sistema";
    }
  });
}

async function reload() {
  cfg = await api("/api/config");
  renderNas();
  renderBackup();
  renderRestore();
}

export async function show(element) {
  el = element;
  el.innerHTML = `
    <h2>Configurações</h2>
    <p class="hint">Somente administradores. Os valores salvos aqui têm prioridade sobre o arquivo <code>.env</code>.</p>
    <div class="card"><h3>Conexão com storage de rede (NAS)</h3><div id="cfg-nas"></div></div>
    <div class="card"><h3>Backup do sistema</h3><div id="cfg-backup"></div></div>
    <div class="card"><h3>Restauração</h3><div id="cfg-restore"></div></div>`;
  await reload();
}

export function onRealtime(data) {
  if (data.kind === "storage_health") reload();
}
