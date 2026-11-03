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

// ---------- VigIA Edge (planta ligada à nuvem) ----------

async function renderEdges() {
  const box = $("#cfg-edge", el);
  if (!box) return;
  let edges = [];
  let units = [];
  try { [edges, units] = await Promise.all([api("/api/edge/edges"), api("/api/units")]); }
  catch (err) { box.innerHTML = `<p class="bad-text">${esc(err.message)}</p>`; return; }
  const active = edges.filter((e) => !e.revoked);
  const state = (e) => {
    if (e.revoked) return badge("Revogado", "muted");
    if (e.online) return badge("Conectado", "good");
    return badge(e.last_seen_at ? `Desconectado · visto ${fmtDateTime(e.last_seen_at)}` : "Aguardando 1ª conexão", "bad");
  };
  const storage = (s) => (s.media_ok == null ? "–" : s.media_ok
    ? `${badge("ok", "good")} <span class="hint">${s.disk_free_gb ?? "?"} GB livres de ${s.disk_total_gb ?? "?"}</span>`
    : badge("inacessível", "bad"));
  box.innerHTML = `
    <p class="hint">Cada planta roda o <b>VigIA Edge</b>: o detector e as imagens ficam no storage do cliente; aqui chegam os dados
      da ocorrência e uma miniatura. A imagem completa, o clipe e o ao vivo vêm pela conexão segura de saída do Edge
      (porta 443) só quando alguém abre — o cliente não abre portas nem precisa de VPN.</p>
    ${edges.length ? `<div class="table-wrap"><table class="compact">
      <tr><th>Edge</th><th>Unidade</th><th>Situação</th><th>Storage do cliente</th><th>Fila</th><th>Câmeras</th><th>Versão</th><th></th></tr>
      ${edges.map((e) => `<tr class="${e.revoked ? "muted-row" : ""}">
        <td><b>${esc(e.name)}</b><div class="hint mono">${esc(e.status.media_dir || "")}</div></td>
        <td>${esc(e.unit || "–")}</td><td>${state(e)}</td><td>${e.revoked ? "–" : storage(e.status)}</td>
        <td>${e.status.queue ? badge(`${e.status.queue} na fila`, "warn") : e.revoked ? "–" : "0"}</td>
        <td>${e.status.cameras ?? "–"}</td><td class="mono">${esc(e.version || "–")}</td>
        <td>${e.revoked ? "" : `<button class="small danger" data-revoke="${e.id}">Revogar</button>`}</td></tr>`).join("")}
    </table></div>` : `<p class="hint">Nenhum Edge cadastrado: as câmeras são atendidas pelo detector desta instalação.</p>`}
    <div class="actions" style="margin-top:12px"><button id="edge-new">+ Gerar código de instalação</button>
      ${active.length ? `<span class="hint">${active.filter((e) => e.online).length} de ${active.length} conectado(s)</span>` : ""}</div>`;

  box.querySelectorAll("[data-revoke]").forEach((b) => b.addEventListener("click", async () => {
    const e = edges.find((x) => x.id === Number(b.dataset.revoke));
    if (!confirm(`Revogar o Edge "${e.name}"? A conexão cai na hora e ele precisará de um novo código para voltar.`)) return;
    try { await api(`/api/edge/edges/${e.id}`, { method: "DELETE" }); renderEdges(); }
    catch (err) { toast(esc(err.message), "danger"); }
  }));
  $("#edge-new", box).addEventListener("click", () => {
    const d = document.createElement("dialog");
    d.className = "form-dialog";
    d.innerHTML = `<form class="form" method="dialog">
      <h2>Código de instalação do Edge</h2>
      <label class="wide">Nome do Edge <input name="name" required minlength="2" maxlength="120" placeholder="ex.: Edge Joinville – galpão A"></label>
      <label class="wide">Unidade atendida <select name="unit_id">${units.map((u) => `<option value="${u.id}">${esc(u.name)}</option>`).join("")}</select></label>
      <div class="wide" id="edge-code"></div>
      <div class="actions wide"><button type="submit">Gerar código</button><button type="button" class="secondary" data-x>Fechar</button></div>
    </form>`;
    document.body.append(d);
    d.addEventListener("close", () => { d.remove(); renderEdges(); });
    d.querySelector("[data-x]").addEventListener("click", () => d.close());
    const f = d.querySelector("form");
    f.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      try {
        const r = await api("/api/edge/enrollments", { method: "POST", body: { name: f.name.value, unit_id: Number(f.unit_id.value) } });
        const cmd = `python -m vigia_edge enroll --cloud ${location.origin} --code ${r.code} --media-dir "D:\\vigia"`;
        $("#edge-code", d).innerHTML = `<div class="edge-code">${esc(r.code)}</div>
          <p class="hint">Vale até ${fmtDateTime(r.expires_at)} e só pode ser usado uma vez. Na máquina do Edge, na pasta <code>edge</code>:</p>
          <pre class="edge-cmd">${esc(cmd)}</pre>
          <p class="hint">Troque <code>D:\\vigia</code> pela pasta do storage do cliente (pode ser um compartilhamento de rede).
            Depois rode <code>python -m vigia_edge run</code> e aponte o detector para o Edge com o
            <code>BACKEND_URL</code> e a <code>DETECTOR_API_KEY</code> que o comando mostrar.</p>`;
        f.querySelector("button[type=submit]").hidden = true;
      } catch (err) { toast(esc(err.message), "danger"); }
    });
    d.showModal();
  });
}

export async function show(element) {
  el = element;
  el.innerHTML = `
    <h2>Configurações</h2>
    <p class="hint">Somente administradores. Os valores salvos aqui têm prioridade sobre o arquivo <code>.env</code>.</p>
    <div class="card"><h3>VigIA Edge – plantas conectadas à nuvem</h3><div id="cfg-edge"></div></div>
    <div class="card"><h3>Conexão com storage de rede (NAS)</h3><div id="cfg-nas"></div></div>
    <div class="card"><h3>Backup do sistema</h3><div id="cfg-backup"></div></div>
    <div class="card"><h3>Restauração</h3><div id="cfg-restore"></div></div>
    <div class="card"><h3>Instalação</h3>
      <ul class="plain">
        <li>Iniciar com o computador: <code>instalar_servico.bat</code> (como administrador)</li>
        <li>HTTPS: <code>python vigia.py --gerar-certificado</code> e reinicie</li>
        <li>Log do serviço: <code>logs/vigia.log</code></li>
      </ul>
    </div>`;
  await Promise.all([reload(), renderEdges()]);
}

export function onRealtime(data) {
  if (data.kind === "storage_health") reload();
  if (data.kind === "edge_status") renderEdges();
}
