import { $, api, esc, fmtDate, fmtDateTime, session, withToken } from "./core.js";

const TITLES = {
  orientacao: "Termo de orientação de segurança",
  treinamento: "Termo de orientação e encaminhamento para treinamento",
  advertencia: "Advertência por descumprimento de norma de segurança",
  rh: "Registro de ocorrência de segurança – encaminhamento ao RH",
};
const ACTION = {
  orientacao: "recebeu orientação sobre o uso correto e obrigatório do equipamento de proteção e as regras da área",
  treinamento: "fica encaminhado(a) ao treinamento indicado abaixo",
  advertencia: "fica advertido(a) por escrito, nos termos do art. 158, parágrafo único, da CLT, que considera ato faltoso a recusa injustificada ao uso do EPI fornecido",
  rh: "tem a ocorrência encaminhada ao RH para as providências cabíveis",
};

(async () => {
  try {
    session.user = await api("/api/auth/me");
  } catch {
    document.body.innerHTML = `<p style="padding:24px">Sessão expirada. Entre no VigIA e abra o termo novamente.</p>`;
    return;
  }
  const id = new URLSearchParams(location.search).get("id");
  const m = await api(`/api/measures/${id}`);
  const p = m.person;
  $("#report").innerHTML = `
    <div class="doc-head"><span>${esc(p.unit)} · Segurança do Trabalho</span><span class="mono">${esc(m.number)}</span></div>
    <h1>${TITLES[m.type]}</h1>
    <p>Colaborador(a) <b>${esc(p.name)}</b>${p.registration ? `, matrícula ${esc(p.registration)}` : ""}, ${esc(p.role || "função não informada")},
      setor ${esc(p.sector || "–")}.</p>
    <p><b>Fatos:</b> ${m.description ? esc(m.description)
      : `${esc(m.event_message || "")}${m.event_at ? `, em ${fmtDateTime(m.event_at)}, câmera ${esc(m.camera_name || "–")}` : ""}.`}</p>
    <p>Conforme o art. 158 da CLT e a NR-6, o uso do EPI fornecido pela empresa e o respeito às áreas de risco são obrigatórios.
      Em razão dos fatos, o(a) colaborador(a) ${ACTION[m.type]}.</p>
    ${m.type === "treinamento" ? `<div class="box"><b>Treinamento:</b> ${esc(m.training_name)}${m.training_date ? ` · ${fmtDate(m.training_date)}` : ""}</div>` : ""}
    ${m.status === "pendente_aprovacao" ? `<div class="box"><b>Atenção:</b> esta advertência ainda aguarda aprovação e não deve ser emitida.</div>` : ""}
    ${m.status === "cancelada" ? `<div class="box"><b>Medida cancelada.</b></div>` : ""}
    <p style="font-size:13px">Evidências arquivadas no sistema: ${m.event_id ? `foto e clipe da ocorrência nº ${m.event_id}` : "–"}.</p>
    ${m.statement ? `<div class="box"><b>Versão do(a) colaborador(a):</b> ${esc(m.statement)}</div>` : ""}
    ${m.ack === "recusada" ? `<div class="box"><b>Recusou-se a assinar.</b> Testemunhas: ${esc(m.witnesses || "–")}</div>` : ""}
    <div class="sign-grid">
      <div>${m.has_signature ? `<img src="${esc(withToken(`/api/measures/${m.id}/signature`))}" alt="Assinatura">` : ""}
        ${esc(p.name)} · ciente${m.ack_at ? ` em ${fmtDateTime(m.ack_at)}` : ""}</div>
      <div>${esc(m.created_by || "")} · responsável</div>
    </div>
    <p style="font-size:12px;color:var(--muted);margin-top:14px">A assinatura indica ciência, não concordância.</p>
    <div class="meta">Registrado por ${esc(m.created_by || "–")} em ${fmtDateTime(m.created_at)}${m.approved_by ? ` · aprovado por ${esc(m.approved_by)} em ${fmtDateTime(m.approved_at)}` : ""}
      · emitido por ${esc(session.user.name)} em ${fmtDateTime(new Date().toISOString())}</div>`;
})();

$("#print").addEventListener("click", () => window.print());
