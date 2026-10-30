// Guia Parâmetros (administradores): retenção, uso do sistema e alertas.

import { collect, field, fmtBytes, saveConfig } from "../config-form.js";
import { $, api, badge, esc, toast } from "../core.js";

let el;
let cfg;
let usageTimer = null;

const RETENTION = ["retention_days", "event_retention_days", "audit_retention_days", "session_hours"];
const USAGE = ["usage_alert_cpu", "usage_alert_memory", "usage_alert_disk", "usage_alert_minutes"];
const ALERTS = ["alert_emails", "report_emails", "alert_min_severity_email", "alert_min_severity_whatsapp",
  "camera_offline_after", "public_url"];
const SMTP = ["smtp_host", "smtp_port", "smtp_user", "smtp_password", "smtp_from", "smtp_tls"];
const WHATSAPP = ["whatsapp_token", "whatsapp_phone_id", "whatsapp_to", "whatsapp_template", "whatsapp_template_lang"];
const SEVERITY = [["baixa", "Todas (baixa ou maior)"], ["media", "Média ou maior"], ["alta", "Alta ou crítica"],
  ["critica", "Somente crítica"]];

function formCard(id, html, names, after) {
  const box = $(id, el);
  box.innerHTML = `<form class="form">${html}<div class="actions"><button type="submit">Salvar</button>${after || ""}</div></form>`;
  box.querySelector("form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const saved = await saveConfig(collect(e.target, names));
    if (saved) { cfg = saved; render(); }
  });
  return box;
}

function meter(label, value, limit, detail) {
  if (value == null) return `<div class="meter"><div class="meter-head"><b>${esc(label)}</b><span class="hint">indisponível</span></div></div>`;
  const over = value >= limit;
  return `
    <div class="meter">
      <div class="meter-head"><b>${esc(label)}</b>
        <span>${over ? badge(`▲ ${value.toFixed(0)}%`, "bad") : `${value.toFixed(0)}%`}</span></div>
      <div class="meter-track" role="meter" aria-valuenow="${value}" aria-valuemin="0" aria-valuemax="100"
        aria-label="${esc(label)}">
        <div class="meter-fill ${over ? "over" : ""}" style="width:${Math.min(value, 100)}%"></div>
        <div class="meter-limit" style="left:${limit}%" title="limite de alerta: ${limit}%"></div>
      </div>
      <div class="hint">${detail} · alerta acima de ${limit}%</div>
    </div>`;
}

async function refreshUsage() {
  const box = $("#par-usage-now", el);
  if (!box) return;
  try {
    const u = await api("/api/config/usage");
    box.innerHTML = `
      <div class="meters">
        ${meter("CPU", u.cpu_percent, u.limits.cpu, `${u.cpu_count} núcleos`)}
        ${meter("Memória", u.memory_percent, u.limits.memory,
          `${fmtBytes(u.memory_total)} no total · VigIA usando ${fmtBytes(u.process_memory)}`)}
        ${meter("Disco (evidências)", u.disk_percent, u.limits.disk,
          `${fmtBytes(u.disk_free)} livres de ${fmtBytes(u.disk_total)}`)}
        ${u.nas_percent != null ? meter("Storage de rede (NAS)", u.nas_percent, u.limits.disk, "uso do NAS") : ""}
      </div>
      <p class="hint">Espaço ocupado pelo VigIA: evidências ${fmtBytes(u.evidence_bytes)} · banco de dados
        ${fmtBytes(u.database_bytes)} <small>(medido a cada 10 min)</small>. Atualiza a cada 5 s.</p>`;
  } catch (err) {
    box.innerHTML = `<p class="hint">${esc(err.message)}</p>`;
  }
}

function render() {
  const v = cfg.values;

  formCard("#par-retention", `
    ${field(v, "retention_days", "Fotos e clipes das ocorrências", { type: "number", min: 1, max: 3650, suffix: "dias",
      hint: "Dados pessoais (LGPD): apagados também do NAS após o prazo." })}
    ${field(v, "event_retention_days", "Registros das ocorrências (sem imagens)", { type: "number", min: 1, max: 7300,
      suffix: "dias", hint: "Base dos indicadores históricos." })}
    ${field(v, "audit_retention_days", "Logs de auditoria", { type: "number", min: 0, max: 7300, suffix: "dias",
      hint: "Acessos e alterações. 0 = guardar para sempre." })}
    ${field(v, "session_hours", "Duração da sessão de login", { type: "number", min: 1, max: 720, suffix: "horas" })}
  `, RETENTION);

  formCard("#par-usage-form", `
    ${field(v, "usage_alert_cpu", "Alerta de CPU acima de", { type: "number", min: 10, max: 100, suffix: "%" })}
    ${field(v, "usage_alert_memory", "Alerta de memória acima de", { type: "number", min: 10, max: 100, suffix: "%" })}
    ${field(v, "usage_alert_disk", "Alerta de disco acima de", { type: "number", min: 10, max: 100, suffix: "%" })}
    ${field(v, "usage_alert_minutes", "Por pelo menos", { type: "number", min: 1, max: 1440, suffix: "min",
      hint: "Evita alertas por picos curtos." })}
  `, USAGE);

  formCard("#par-alerts", `
    ${field(v, "alert_emails", "E-mails que recebem os alertas", { wide: true, placeholder: "seguranca@empresa.com, supervisor@empresa.com",
      hint: "Separe por vírgula. Recebem desvios, câmeras com problema, NAS e uso do sistema." })}
    ${field(v, "report_emails", "E-mails que recebem o relatório periódico", { wide: true,
      hint: "Vazio = os mesmos dos alertas." })}
    ${field(v, "alert_min_severity_email", "E-mail para desvios de severidade", { choices: SEVERITY })}
    ${field(v, "alert_min_severity_whatsapp", "WhatsApp para desvios de severidade", { choices: SEVERITY })}
    ${field(v, "camera_offline_after", "Câmera sem imagem é considerada offline após", { type: "number", min: 10, max: 86400, suffix: "s" })}
    ${field(v, "public_url", "Endereço do painel (links nas mensagens)", { placeholder: "https://vigia.empresa.local:8000" })}
  `, ALERTS);

  const smtp = formCard("#par-smtp", `
    ${field(v, "smtp_host", "Servidor SMTP", { placeholder: "smtp.gmail.com" })}
    ${field(v, "smtp_port", "Porta", { type: "number", min: 1, max: 65535 })}
    ${field(v, "smtp_user", "Usuário")}
    ${field(v, "smtp_password", "Senha", { type: "secret", hint: "No Gmail, use uma senha de app." })}
    ${field(v, "smtp_from", "Remetente", { placeholder: "vigia@empresa.com" })}
    ${field(v, "smtp_tls", "Usar TLS (STARTTLS)", { type: "bool" })}
    <label class="wide">Testar envio para (opcional) <input name="test_to" placeholder="vazio = e-mails dos alertas"></label>
  `, SMTP, `<button type="button" class="secondary" data-test="email">Enviar e-mail de teste</button>`);

  const wa = formCard("#par-whatsapp", `
    ${field(v, "whatsapp_token", "Token de acesso (Meta)", { type: "secret", wide: true })}
    ${field(v, "whatsapp_phone_id", "ID do número (Phone number ID)")}
    ${field(v, "whatsapp_to", "Números que recebem", { placeholder: "5511999999999, 5511988888888",
      hint: "Com DDI e DDD, separados por vírgula." })}
    ${field(v, "whatsapp_template", "Template aprovado (recomendado)", { hint: "Necessário para enviar fora da janela de 24 h. Corpo com 3 variáveis: desvio, câmera, data/hora." })}
    ${field(v, "whatsapp_template_lang", "Idioma do template", { placeholder: "pt_BR" })}
    <label class="wide">Testar envio para (opcional) <input name="test_to" placeholder="vazio = números configurados"></label>
  `, WHATSAPP, `<button type="button" class="secondary" data-test="whatsapp">Enviar WhatsApp de teste</button>`);

  for (const box of [smtp, wa]) {
    const btn = box.querySelector("[data-test]");
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      try {
        const r = await api("/api/config/alerts/test", { method: "POST",
          body: { channel: btn.dataset.test, to: box.querySelector("[name=test_to]").value } });
        toast(`Mensagem de teste enviada para ${esc(r.to.join(", "))}.`, "ok");
      } catch (err) { toast(esc(err.message), "danger", 10000); }
      btn.disabled = false;
    });
  }
}

export async function show(element) {
  el = element;
  el.innerHTML = `
    <h2>Parâmetros do sistema</h2>
    <p class="hint">Somente administradores. Salve cada seção separadamente. Os valores salvos aqui têm prioridade
      sobre o arquivo <code>.env</code>; senhas e tokens ficam criptografados.</p>
    <div class="grid-2">
      <div class="card"><h3>Retenção de imagens e logs</h3><div id="par-retention"></div></div>
      <div class="card"><h3>Uso do sistema</h3><div id="par-usage-now"></div><div id="par-usage-form"></div></div>
      <div class="card wide"><h3>Alertas</h3><div id="par-alerts"></div></div>
      <div class="card"><h3>E-mail (SMTP)</h3><div id="par-smtp"></div></div>
      <div class="card"><h3>WhatsApp Business (Meta Cloud API)</h3><div id="par-whatsapp"></div></div>
    </div>`;
  cfg = await api("/api/config");
  render();
  await refreshUsage();
  clearInterval(usageTimer);
  usageTimer = setInterval(refreshUsage, 5000);
}

export function leave() {
  clearInterval(usageTimer);
}
