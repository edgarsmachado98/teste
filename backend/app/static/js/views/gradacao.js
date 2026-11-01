// Cadastros › Regras de gradação: escada de medidas sugeridas, exceções e garantias.

import { $, api, can, esc, toast } from "../core.js";

const TYPES = [["orientacao", "Orientação registrada"], ["treinamento", "Encaminhar para treinamento"],
  ["advertencia", "Advertência escrita"], ["rh", "Encaminhar ao RH"]];
const SEVERITIES = [["baixa", "Baixa"], ["media", "Média"], ["alta", "Alta"], ["critica", "Crítica"]];
const EVENT_TYPES = [["ppe_missing", "EPI ausente"], ["restricted_zone", "Zona restrita"], ["max_people", "Excesso de pessoas"],
  ["fire_smoke", "Fogo / fumaça"]];

export async function render(container) {
  const cfg = await api("/api/grading");
  const ro = can("admin") ? "" : "disabled";
  const stepSelect = (value, name) => `<select name="${name}" ${ro}><option value="">–</option>
    ${cfg.steps.map((_, i) => `<option value="${i + 1}" ${Number(value) === i + 1 ? "selected" : ""}>${i + 1}º degrau</option>`).join("")}</select>`;
  container.innerHTML = `
    <form id="grading-form" class="card form">
      <div class="wide toolbar" style="margin:0">
        <div><h2 style="margin:0">Regras de gradação</h2>
          <p class="hint" style="margin:4px 0 0">Definem a medida <b>sugerida</b> pelo histórico da pessoa. A decisão é sempre de quem aplica,
            e escolher outra medida exige justificativa.</p></div>
        ${can("admin") ? `<button type="submit">Salvar regras</button>` : `<span class="hint">Somente administradores alteram.</span>`}
      </div>
      <label>Contar ocorrências dos últimos (dias) <input type="number" name="window_days" min="7" max="730" value="${cfg.window_days}" ${ro}>
        <small class="hint">Por tipo de desvio. Sem novas ocorrências na janela, a contagem recomeça.</small></label>
      <div class="wide">
        <div class="label-strong">Escada de medidas</div>
        <div class="ladder">${[0, 1, 2, 3].map((i) => `
          <label class="ladder-step"><span class="mono">${i + 1}ª ocorrência${i === 3 ? " ou mais" : ""}</span>
            <select name="step_${i}" ${ro}><option value="">— (fim da escada)</option>
              ${TYPES.map(([v, l]) => `<option value="${v}" ${cfg.steps[i] === v ? "selected" : ""}>${l}</option>`).join("")}</select></label>`).join("")}
        </div>
      </div>
      <fieldset class="wide"><legend>Exceções por gravidade: começar em degrau acima já na primeira vez</legend>
        ${SEVERITIES.map(([v, l]) => `<label>Severidade ${l} ${stepSelect(cfg.severity_start[v], `sev_${v}`)}</label>`).join("")}
        ${EVENT_TYPES.map(([v, l]) => `<label>${l} ${stepSelect(cfg.type_start[v], `type_${v}`)}</label>`).join("")}
      </fieldset>
      <div class="wide">
        <div class="label-strong">Garantias</div>
        <label class="check"><input type="checkbox" checked disabled> Nenhuma medida é aplicada automaticamente (fixo)</label>
        <label class="check"><input type="checkbox" checked disabled> Advertência registrada por técnico precisa de aprovação de gestor ou administrador (fixo)</label>
        <label class="check"><input type="checkbox" name="require_evidence_for_warning" ${cfg.require_evidence_for_warning ? "checked" : ""} ${ro}> Advertência exige evidência (foto ou clipe)</label>
        <label class="check"><input type="checkbox" name="require_witnesses_on_refusal" ${cfg.require_witnesses_on_refusal ? "checked" : ""} ${ro}> Exigir testemunhas quando o colaborador se recusar a assinar</label>
      </div>
      <label class="wide">Treinamentos sugeridos (um por linha)
        <textarea name="default_trainings" rows="3" ${ro}>${esc(cfg.default_trainings.join("\n"))}</textarea></label>
      <label class="wide">Texto de transparência (integração, ordem de serviço, regulamento)
        <textarea name="transparency_text" rows="4" ${ro}>${esc(cfg.transparency_text)}</textarea></label>
    </form>`;
  $("#grading-form", container).addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = e.target;
    const steps = [0, 1, 2, 3].map((i) => f[`step_${i}`].value).filter(Boolean);
    const pick = (prefix, list) => Object.fromEntries(list.map(([v]) => [v, f[`${prefix}_${v}`].value]).filter(([, v]) => v).map(([k, v]) => [k, Number(v)]));
    try {
      await api("/api/grading", { method: "PUT", body: {
        window_days: Number(f.window_days.value), steps, severity_start: pick("sev", SEVERITIES), type_start: pick("type", EVENT_TYPES),
        require_evidence_for_warning: f.require_evidence_for_warning.checked, require_witnesses_on_refusal: f.require_witnesses_on_refusal.checked,
        default_trainings: f.default_trainings.value.split("\n"), transparency_text: f.transparency_text.value } });
      toast("Regras de gradação salvas.", "ok", 2500);
      render(container);
    } catch (err) { toast(esc(err.message), "danger"); }
  });
}
