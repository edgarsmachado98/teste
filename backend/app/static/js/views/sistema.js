import { $, api, can, esc, fmtDate, isoDate, toast, withToken } from "../core.js";

let el;

const FREQ = { mensal: "Mensal (dia 1, referente ao mês anterior)", semanal: "Semanal (segunda-feira, semana anterior)",
  desligado: "Desligado" };

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
}

export async function show(element) {
  el = element;
  el.innerHTML = `
    <h2>Sistema</h2>
    <div class="grid-2">
      <div class="card"><h3>Relatório automático por e-mail</h3><div id="sys-report"></div></div>
      <div class="card"><h3>Retenção de dados (LGPD)</h3><div id="sys-retention"></div></div>
      <div class="card"><h3>Instalação</h3>
        <ul class="plain">
          <li>Iniciar com o computador: <code>instalar_servico.bat</code> (como administrador)</li>
          <li>HTTPS: <code>python vigia.py --gerar-certificado</code> e reinicie</li>
          <li>Log do serviço: <code>logs/vigia.log</code></li>
        </ul>
        <p class="hint">${can("admin") ? `Backup, restauração, storage de rede e parâmetros (retenção, alertas, e-mail,
          WhatsApp) ficam nas guias <a href="#configuracoes">Configurações</a> e <a href="#parametros">Parâmetros</a>.`
          : "Backup, restauração e parâmetros do sistema são gerenciados pelos administradores."}</p>
      </div>
    </div>`;
  await load();
}
