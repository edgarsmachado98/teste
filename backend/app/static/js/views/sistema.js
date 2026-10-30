import { $, api, can, esc, fmtDate, fmtDateTime, isoDate, toast, withToken } from "../core.js";

let el;

const FREQ = { mensal: "Mensal (dia 1, referente ao mês anterior)", semanal: "Semanal (segunda-feira, semana anterior)",
  desligado: "Desligado" };
const fmtSize = (b) => (b > 1048576 ? `${(b / 1048576).toFixed(1)} MB` : `${Math.ceil(b / 1024)} KB`).replace(".", ",");

async function load() {
  const s = await api("/api/system/status");
  const lastPeriod = s.report_last_period;
  $("#sys-report", el).innerHTML = `
    <dl class="kv">
      <dt>Envio automático</dt><dd>${esc(FREQ[s.report_frequency] || s.report_frequency)}, às ${s.report_hour}h</dd>
      <dt>Destinatários</dt><dd>${s.report_recipients.length ? esc(s.report_recipients.join(", ")) : "<span class='bad-text'>nenhum (configure REPORT_EMAILS ou ALERT_EMAILS)</span>"}</dd>
      <dt>E-mail (SMTP)</dt><dd>${s.email_configured ? "configurado" : "<span class='bad-text'>não configurado (SMTP_HOST no .env)</span>"}</dd>
      <dt>Último período processado</dt><dd>${s.report_last ? s.report_last.split(":").map(fmtDate).join(" a ") : "–"}</dd>
    </dl>
    <form id="sys-send" class="filters">
      <label>De <input type="date" name="start" value="${lastPeriod ? lastPeriod.start : ""}"></label>
      <label>Até <input type="date" name="end" value="${lastPeriod ? lastPeriod.end : isoDate(new Date())}"></label>
      <label>Para (opcional) <input name="to" placeholder="e-mails separados por vírgula"></label>
    </form>
    <div class="actions">
      <button id="sys-send-btn" ${s.email_configured ? "" : "disabled"}>Enviar relatório agora</button>
      <button id="sys-pdf" class="secondary">Baixar PDF deste período</button>
    </div>`;

  $("#sys-backup", el).innerHTML = s.database !== "sqlite"
    ? `<p class="hint">Banco PostgreSQL: faça o backup com <code>pg_dump</code> agendado no servidor.</p>`
    : `
    <dl class="kv">
      <dt>Backup automático</dt><dd>diário, às ${s.backup_hour}h · guarda os ${s.backup_keep} mais recentes</dd>
      <dt>Último backup</dt><dd>${s.backup_last ? fmtDate(s.backup_last) : "–"}</dd>
      <dt>Cópia extra</dt><dd>${s.backup_copy_dir ? esc(s.backup_copy_dir) : "<span class='hint'>não configurada (BACKUP_COPY_DIR, ex.: pasta de rede)</span>"}</dd>
    </dl>
    ${can("admin") ? `<button id="sys-backup-btn">Fazer backup agora</button>` : ""}
    <table class="compact">
      <tr><th>Arquivo</th><th>Data</th><th>Tamanho</th><th></th></tr>
      ${s.backups.map((b) => `<tr><td class="mono">${esc(b.name)}</td><td>${fmtDateTime(b.created_at)}</td>
        <td>${fmtSize(b.size)}</td><td>${can("admin") ? `<a href="${esc(withToken(`/api/system/backups/${b.name}`))}">baixar</a>` : ""}</td></tr>`).join("")
        || `<tr><td class="hint">Nenhum backup ainda.</td></tr>`}
    </table>`;

  $("#sys-retention", el).innerHTML = `
    <dl class="kv">
      <dt>Fotos e clipes</dt><dd>apagados após ${s.retention_days} dias (RETENTION_DAYS)</dd>
      <dt>Registros das ocorrências</dt><dd>mantidos por ${s.event_retention_days} dias, sem imagens, para os indicadores (EVENT_RETENTION_DAYS)</dd>
    </dl>`;

  const form = $("#sys-send", el);
  const period = () => `start=${form.start.value}&end=${form.end.value}`;
  $("#sys-pdf", el).addEventListener("click", () => { window.location.href = withToken(`/api/reports/pdf?${period()}`); });
  $("#sys-send-btn", el).addEventListener("click", async (e) => {
    e.target.disabled = true;
    try {
      const recipients = form.to.value.split(",").map((x) => x.trim()).filter(Boolean);
      await api("/api/system/report-email", { method: "POST",
        body: { start: form.start.value || null, end: form.end.value || null, recipients: recipients.length ? recipients : null } });
      toast("Relatório enviado por e-mail.", "ok");
    } catch (err) { toast(esc(err.message), "danger"); }
    e.target.disabled = false;
  });
  $("#sys-backup-btn", el)?.addEventListener("click", async (e) => {
    e.target.disabled = true;
    try {
      const r = await api("/api/system/backups", { method: "POST" });
      toast(`Backup criado: ${esc(r.name)}`, "ok");
      load();
    } catch (err) { toast(esc(err.message), "danger"); e.target.disabled = false; }
  });
}

export async function show(element) {
  el = element;
  el.innerHTML = `
    <h2>Sistema</h2>
    <div class="grid-2">
      <div class="card"><h3>Relatório automático por e-mail</h3><div id="sys-report"></div></div>
      <div class="card"><h3>Backup do banco de dados</h3><div id="sys-backup"></div></div>
      <div class="card"><h3>Retenção de dados (LGPD)</h3><div id="sys-retention"></div></div>
      <div class="card"><h3>Instalação</h3>
        <ul class="plain">
          <li>Iniciar com o computador: <code>instalar_servico.bat</code> (como administrador)</li>
          <li>HTTPS: <code>python vigia.py --gerar-certificado</code> e reinicie</li>
          <li>Log do serviço: <code>logs/vigia.log</code></li>
        </ul>
        <p class="hint">Configurações como horários, destinatários e retenção ficam no arquivo <code>.env</code>.</p>
      </div>
    </div>`;
  await load();
}
