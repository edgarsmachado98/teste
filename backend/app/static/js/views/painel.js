import { delta } from "../indicators-render.js";
import { HEALTH_LABELS, TYPE_LABELS, api, can, esc, fmtDateTime, fmtPct, healthBadge, session, toast, withToken } from "../core.js";

let el;

function greeting(t, overdueCount, problems) {
  const h = new Date().getHours();
  const hello = h < 5 ? "Boa noite" : h < 12 ? "Bom dia" : h < 18 ? "Boa tarde" : "Boa noite";
  const first = (session.user?.name || "").split(" ")[0];
  const parts = [];
  parts.push(t.pending ? `${t.pending} ${t.pending === 1 ? "alerta aguarda" : "alertas aguardam"} triagem` : "nenhum alerta aguardando triagem");
  if (overdueCount) parts.push(`${overdueCount} ${overdueCount === 1 ? "ação atrasada" : "ações atrasadas"}`);
  if (problems) parts.push(`${problems} ${problems === 1 ? "câmera com problema" : "câmeras com problema"}`);
  const line = parts.join(" · ");
  const today = new Date().toLocaleDateString("pt-BR", { weekday: "long", day: "2-digit", month: "long", year: "numeric" });
  return `<div class="greeting">
      <div><h2>${hello}${first ? `, ${esc(first)}` : ""}.</h2>
        <p>${esc(line.charAt(0).toUpperCase() + line.slice(1))}.</p></div>
      <span class="when">${esc(today)}${session.meta?.shift ? ` · ${esc(session.meta.shift)}` : ""}</span>
    </div>`;
}

function card(ev) {
  return `
    <article class="event sev-${esc(ev.severity)}">
      ${ev.image_url ? `<img src="${esc(withToken(ev.image_url))}" alt="Evidência" data-full="${esc(withToken(ev.image_url))}">`
        : `<div class="noimg">sem imagem</div>`}
      <div class="info">
        <a href="#ocorrencia-${ev.id}"><strong>${esc(ev.message)}</strong></a>
        <span>${esc(ev.camera_name)} · ${esc(TYPE_LABELS[ev.type] || ev.type)}</span>
        <span>${fmtDateTime(ev.created_at)} · severidade <b>${esc(ev.severity)}</b></span>
        <div class="actions">
          <button class="small" data-status="confirmada" data-id="${ev.id}">Confirmar</button>
          <button class="small secondary" data-status="descartada" data-id="${ev.id}">Falso alarme</button>
          <a class="small-link" href="#ocorrencia-${ev.id}">Tratar →</a>
        </div>
      </div>
    </article>`;
}

async function load() {
  const [summary, pending, cameras, overdue, approvals] = await Promise.all([
    api("/api/reports/summary"),
    api("/api/events?status=nova&limit=24"),
    api("/api/cameras"),
    api("/api/actions?overdue=true"),
    can("gestor") ? api("/api/measures?status=pendente_aprovacao") : Promise.resolve([]),
  ]);
  const t = summary.totals;
  const c = summary.compliance;
  const problems = cameras.filter((cam) => cam.enabled && cam.health && cam.health !== "ok");

  el.innerHTML = `
    ${greeting(t, summary.actions.overdue, problems.length)}
    ${cameras.length ? "" : `
      <div class="card onboarding">
        <h2>Primeiros passos</h2>
        <ol>
          <li>Cadastre uma câmera (pode ser a webcam deste computador).</li>
          <li>Crie uma regra – por exemplo, <b>Zona restrita</b> ou <b>EPI ausente</b>.</li>
          <li>Cadastre os usuários: técnicos de segurança, gestores e operadores.</li>
          <li>Pronto: os desvios aparecem aqui em tempo real, com som e foto.</li>
        </ol>
        ${can("tecnico") ? `<a class="button" href="#cameras">Adicionar câmera</a>` : ""}
      </div>`}

    ${problems.length ? `
      <div class="card alert-strip">
        <b>▲ ${problems.length} câmera(s) com problema – o monitoramento dessas áreas está comprometido:</b>
        ${problems.map((cam) => `<span>${esc(cam.name)}: ${esc(HEALTH_LABELS[cam.health])}</span>`).join(" · ")}
      </div>` : ""}

    <div class="stats">
      <div class="stat"><b>${t.pending}</b><span>Aguardando triagem</span></div>
      <div class="stat"><b>${fmtPct(c.rate, 1)}</b><span>Conformidade de EPI (30 dias)</span>
        ${delta(c.rate, c.previous_rate, { lowerIsBetter: false, pct: true })}</div>
      <div class="stat"><b>${t.deviations}</b><span>Desvios confirmados ou em análise (30 dias)</span>
        ${delta(t.deviations, t.previous_deviations)}</div>
      <div class="stat ${summary.actions.overdue ? "stat-bad" : ""}"><b>${summary.actions.overdue}</b>
        <span>Ações atrasadas · ${summary.actions.open} abertas</span></div>
    </div>

    ${approvals.length ? `
      <div class="card alert-strip approvals">
        <b>${approvals.length} advertência(s) aguardando sua aprovação:</b>
        ${approvals.slice(0, 5).map((m) => `<a href="#ocorrencia-${m.event_id}">${esc(m.person_name)} (${esc(m.number)})</a>`).join(" · ")}
      </div>` : ""}

    ${overdue.length ? `
      <div class="card">
        <h2>Ações atrasadas</h2>
        <ul class="plain">${overdue.slice(0, 5).map((a) => `
          <li>▲ <b>${esc(a.title)}</b> – ${esc(a.responsible_name || "sem responsável")}
            ${a.event_id ? `· <a href="#ocorrencia-${a.event_id}">ocorrência #${a.event_id}</a>` : ""}</li>`).join("")}
        </ul>
        <a href="#acoes">Ver plano de ação →</a>
      </div>` : ""}

    <div class="toolbar"><h2>Aguardando triagem</h2><a href="#ocorrencias">Ver todas as ocorrências →</a></div>
    <div class="events">${pending.length ? pending.map(card).join("") : `<p class="hint">Nenhum alerta pendente. 👍</p>`}</div>`;

  el.querySelectorAll("button[data-status]").forEach((btn) => btn.addEventListener("click", async () => {
    try {
      await api(`/api/events/${btn.dataset.id}`, { method: "PATCH", body: { status: btn.dataset.status } });
      load();
    } catch (err) { toast(esc(err.message), "danger"); }
  }));
}

export async function show(element) {
  el = element;
  await load();
}

export function onRealtime(data) {
  if (["event", "event_updated", "camera_health"].includes(data.kind)) load();
}
