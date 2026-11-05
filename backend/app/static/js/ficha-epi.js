// Ficha de EPI (NR-6, 6.6.1 "h"): entregas de EPI e uniforme do colaborador, com as assinaturas eletrônicas
// e a conferência de integridade (hash SHA-256 de cada comprovante).
import { $, api, esc, fmtDate, fmtDateTime, session, withToken } from "./core.js";
import { DECLARATION, REASONS, sizesText } from "./epi-ui.js";

const EMPLOYMENT = { clt: "CLT", terceiro: "Terceiro", temporario: "Temporário", estagiario: "Estagiário" };

function signCell(r) {
  if (!r) return `<td class="sig rec">registro manual</td>`;
  if (!r.signed) return `<td class="sig"></td>`;
  if (r.has_signature) return `<td class="sig"><img src="${esc(withToken(`/api/ppe/receipts/${r.id}/signature`))}" alt="assinatura"></td>`;
  return `<td class="sig rec">${esc(r.method_label)}</td>`;
}

(async () => {
  try {
    session.user = await api("/api/auth/me");
  } catch {
    document.body.innerHTML = `<p style="padding:24px">Sessão expirada. Entre no VigIA e abra a ficha novamente.</p>`;
    return;
  }
  const id = new URLSearchParams(location.search).get("person");
  const [f, meta] = await Promise.all([api(`/api/ppe/fichas/${id}`), api("/api/meta").catch(() => ({}))]);
  const p = f.person;
  const rows = [
    ...f.receipts.flatMap((r) => r.items.map((i, n) => ({ ...i, receipt: r, first: n === 0, span: r.items.length }))),
    ...f.manual.map((i) => ({ ...i, receipt: null, first: true, span: 1 })),
  ].sort((a, b) => String(a.delivered_on).localeCompare(String(b.delivered_on)) || (a.receipt?.id || 0) - (b.receipt?.id || 0));
  const sizes = sizesText(p.sizes);
  const render = (blank) => {
    $("#report").innerHTML = `
      <div class="doc-head"><div><div class="hint">${esc([meta.company_name, p.unit].filter(Boolean).join(" · "))}</div>
        <h1>Ficha de controle de EPI e uniformes</h1><div class="hint">NR-6 · art. 158 e 166 da CLT</div></div>
        <div class="brand">Vig<span>IA</span></div></div>
      <div class="grid">
        <div><span>Colaborador</span><b>${esc(p.name)}</b></div>
        <div><span>CPF</span>${esc(p.cpf)}</div>
        <div><span>Matrícula</span>${esc(p.registration || "–")}</div>
        <div><span>Função</span>${esc(p.role || "–")}</div>
        <div><span>Setor</span>${esc(p.sector || "–")}</div>
        <div><span>Turno</span>${esc(p.shift || "–")}</div>
        <div><span>Vínculo</span>${esc(EMPLOYMENT[p.employment] || p.employment)}${p.company ? ` · ${esc(p.company)}` : ""}</div>
        <div><span>Tamanhos</span>${esc(sizes || "–")}</div>
        <div><span>EPI exigido no setor</span>${esc(f.requirements.join(", ") || "–")}</div>
      </div>
      <div class="decl"><b>Termo de responsabilidade.</b> ${esc(DECLARATION)}</div>
      <table>
        <tr><th>Data</th><th>Item</th><th>CA</th><th>Tam.</th><th>Qtd.</th><th>Motivo</th><th>Troca prevista</th><th>Devolvido / substituído</th><th>Assinatura</th></tr>
        ${rows.map((i) => `<tr>
          <td>${fmtDate(i.delivered_on)}${i.first && i.receipt ? `<div class="rec">${esc(i.receipt.number)}</div>` : ""}</td>
          <td>${esc(i.item)}</td><td>${esc(i.ca || "–")}</td><td>${esc(i.size || "–")}</td><td>${i.quantity}</td>
          <td>${esc(REASONS[i.reason] || "")}</td><td>${fmtDate(i.valid_until)}</td><td>${i.replaced_on ? fmtDate(i.replaced_on) : ""}</td>
          ${i.first ? signCell(i.receipt).replace("<td", `<td rowspan="${i.span}"`) : ""}</tr>`).join("")}
        ${blank ? Array.from({ length: 8 }, () => `<tr class="blank">${"<td></td>".repeat(9)}</tr>`).join("") : ""}
        ${!rows.length && !blank ? `<tr><td colspan="9" class="hint">Nenhuma entrega registrada.</td></tr>` : ""}
      </table>
      ${f.receipts.some((r) => r.signed) ? `<div class="proof"><b>Comprovação das assinaturas eletrônicas</b> (Lei 14.063/2020).
        Cada comprovante guarda a data e hora, o IP, a conferência do CPF digitado pelo colaborador e o hash SHA-256 do conteúdo
        assinado; qualquer alteração posterior aparece como "alterado".
        <table style="margin-top:6px"><tr><th>Comprovante</th><th>Forma</th><th>Assinado em</th><th>Identificação</th><th>Hash SHA-256</th><th>Integridade</th></tr>
        ${f.receipts.filter((r) => r.signed).map((r) => `<tr><td>${esc(r.number)}</td><td>${esc(r.method_label)}${r.has_photo ? " + foto" : ""}</td>
          <td>${fmtDateTime(r.signed_at)}${r.ip ? `<div class="rec">IP ${esc(r.ip)}</div>` : ""}</td><td>${esc(r.identity_check || "–")}</td>
          <td class="mono">${esc(r.content_hash)}</td>
          <td>${r.intact ? `<span class="ok">íntegro</span>` : `<span class="bad">ALTERADO</span>`}</td></tr>`).join("")}</table></div>` : ""}
      <div class="sign-grid"><div>${esc(p.name)} · colaborador(a)</div><div>Responsável pela entrega (SESMT / almoxarifado)</div></div>
      <p class="hint" style="margin-top:14px">Emitida por ${esc(session.user.name)} em ${fmtDateTime(new Date().toISOString())}.</p>`;
  };
  render(false);
  $("#blank-rows").addEventListener("change", (e) => render(e.target.checked));
})();

$("#print").addEventListener("click", () => window.print());
