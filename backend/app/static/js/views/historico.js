// Histórico de segurança da pessoa: ocorrências, medidas e treinamentos (acesso restrito e auditado).

import { api, badge, esc, fmtDate, fmtDateTime, withToken } from "../core.js";

const KIND = {
  ocorrencia: ["Ocorrência", "!", "bad"],
  medida: ["Medida", "✓", ""],
  treinamento: ["Treinamento", "T", "good"],
};

export async function render(container, personId, onBack) {
  const h = await api(`/api/people/${personId}/history`);
  const p = h.person;
  const s = h.summary;
  container.innerHTML = `
    <div class="toolbar" style="margin-top:0">
      <button type="button" class="secondary" data-back>← Voltar</button>
    </div>
    <div class="person-head">
      ${p.has_photo ? `<img class="avatar" style="width:72px;height:72px" src="${esc(withToken(`/api/people/${p.id}/photo`))}" alt="">`
        : `<span class="avatar" style="width:72px;height:72px;font-size:22px">${esc(p.name.split(" ").filter((w) => w.length > 2).slice(0, 2).map((w) => w[0]).join(""))}</span>`}
      <div><div class="hint">Histórico de segurança</div><h2 style="margin:2px 0">${esc(p.name)}</h2>
        <div class="hint">${esc(p.role || "")} · ${esc(p.sector || "sem setor")} · ${esc(p.shift || "")}${p.registration ? ` · matrícula ${esc(p.registration)}` : ""}</div></div>
    </div>
    <div class="notice"><b>Acesso restrito:</b> visível para técnicos de segurança, gestores e administradores. Cada consulta é registrada
      na auditoria. Os indicadores gerais da unidade não mostram nomes.</div>
    <div class="stats">
      <div class="stat"><b>${s.events_12m}</b><span>Ocorrências em 12 meses</span><small class="delta">${s.events_window} nos últimos ${s.window_days} dias</small></div>
      <div class="stat"><b>${s.orientations}</b><span>Orientações</span></div>
      <div class="stat"><b>${s.trainings}</b><span>Encaminhamentos a treinamento</span></div>
      <div class="stat ${s.warnings ? "stat-bad" : ""}"><b>${s.warnings}</b><span>Advertências</span>
        ${s.pending ? `<small class="delta">${s.pending} aguardando aprovação</small>` : ""}</div>
    </div>
    <div class="split">
      <div class="split-main card">
        <h3>Linha do tempo</h3>
        <ol class="timeline big">${h.timeline.map((t) => `
          <li><span>${fmtDate(t.at)}</span> ${badge(KIND[t.kind][0], KIND[t.kind][2])}
            ${t.event_id ? `<a href="#ocorrencia-${t.event_id}">${esc(t.title)}</a>` : `<b>${esc(t.title)}</b>`}
            ${t.measure_id ? ` · <a href="termo.html?id=${t.measure_id}" target="_blank">termo</a>` : ""}
            <div class="hint">${esc(t.detail)}${t.kind === "ocorrencia" && t.status === "descartada" ? " · falso alarme" : ""}</div></li>`).join("")
          || `<li class="hint">Sem registros.</li>`}</ol>
      </div>
      <aside class="split-side card">
        <div class="label-strong">Se houver nova ocorrência</div>
        ${h.next ? `<div class="preview-big" style="font-size:22px">${esc(h.next.label)}</div>
          <p class="hint">${h.next.until ? `Válido até ${fmtDate(h.next.until)}. Sem novas ocorrências até lá, a contagem recomeça.`
            : "A contagem já recomeçou."}</p>` : `<p class="hint">Nenhuma ocorrência registrada.</p>`}
        <p class="hint">A medida é só uma sugestão da regra de gradação: quem decide é o técnico, o gestor ou o RH.</p>
      </aside>
    </div>`;
  container.querySelector("[data-back]").addEventListener("click", onBack);
}
