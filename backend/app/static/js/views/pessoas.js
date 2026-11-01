// Cadastros › Pessoas: lista, cadastro com foto de identificação, EPIs entregues, treinamentos e importação.

import { $, api, badge, can, esc, fmtDate, toast, withToken } from "../core.js";

const EMPLOYMENT = { clt: "CLT", terceiro: "Terceiro", temporario: "Temporário", estagiario: "Estagiário" };
const STATUS = { ativo: ["Ativo", "good"], afastado: ["Afastado", "warn"], desligado: ["Desligado", "muted"] };
const TRAINING = { agendado: ["Agendado", "warn"], concluido: ["Concluído", "good"], cancelado: ["Cancelado", "muted"] };

let root;
let units = [];
let sectors = [];
let filters = { q: "", unit_id: "", sector_id: "", status: "ativo,afastado", offset: 0 };
let editing = null; // id da pessoa aberta, "new" ou null (lista)
let onOpenHistory = null;

export function setHistoryHandler(fn) { onOpenHistory = fn; }

const initials = (name) => name.split(" ").filter((w) => w.length > 2).slice(0, 2).map((w) => w[0]).join("").toUpperCase();
const shifts = () => [...new Set(["Turno A", "Turno B", "Turno C"])];

function avatar(p, size = 40) {
  return p.has_photo
    ? `<img class="avatar" style="width:${size}px;height:${size}px" src="${esc(withToken(`/api/people/${p.id}/photo?v=${p.id}`))}" alt="">`
    : `<span class="avatar" style="width:${size}px;height:${size}px">${esc(initials(p.name))}</span>`;
}

// ---------- Lista ----------

async function loadList() {
  const params = new URLSearchParams({ limit: 50, offset: filters.offset });
  for (const k of ["q", "unit_id", "sector_id", "status"]) if (filters[k]) params.set(k, filters[k]);
  const [data, summary] = await Promise.all([api(`/api/people?${params}`), api("/api/people/summary")]);
  $("#people-count", root).textContent = `${data.total} pessoa(s)`;
  $("#people-table", root).innerHTML = data.items.length ? `
    <tr><th>Pessoa</th><th>CPF</th><th>Setor · função</th><th>Unidade</th><th>Turno</th><th>EPI e treinamento</th><th>Situação</th></tr>
    ${data.items.map((p) => `
      <tr class="clickable" data-id="${p.id}">
        <td><div class="person-cell">${avatar(p)}<div><b>${esc(p.name)}</b><div class="hint mono">${p.registration ? `Mat. ${esc(p.registration)}` : ""}${p.badge_code ? ` · colete ${esc(p.badge_code)}` : ""}</div></div></div></td>
        <td class="mono">${esc(p.cpf)}</td>
        <td>${esc(p.sector || "–")}<div class="hint">${esc(p.role)}</div></td>
        <td>${esc(p.unit)}</td><td>${esc(p.shift || "–")}</td>
        <td>${p.ppe_alert ? badge(p.ppe_alert, p.ppe_alert.includes("vencido") ? "bad" : "warn") : badge("Em dia", "good")}
          ${p.open_trainings ? badge(`${p.open_trainings} treinamento(s)`, "") : ""}</td>
        <td>${badge(STATUS[p.status][0], STATUS[p.status][1])}${p.employment === "terceiro" ? ` ${badge("terceiro", "")}` : ""}</td>
      </tr>`).join("")}`
    : `<tr><td class="hint">Nenhuma pessoa encontrada.</td></tr>`;
  const pages = Math.ceil(data.total / 50);
  const page = Math.floor(filters.offset / 50) + 1;
  $("#people-pages", root).innerHTML = pages > 1 ? `
    <button class="secondary small" data-page="${page - 1}" ${page <= 1 ? "disabled" : ""}>Anterior</button>
    <span class="hint">página ${page} de ${pages}</span>
    <button class="secondary small" data-page="${page + 1}" ${page >= pages ? "disabled" : ""}>Próxima</button>` : "";
  $("#people-summary", root).innerHTML = `
    <div class="kv-list">
      <div><span>Ativos</span><b>${summary.active}</b></div>
      <div><span>Terceiros</span><b>${summary.third_party}</b></div>
      <div><span>EPI vencendo em 30 dias</span><b>${summary.ppe_expiring}</b></div>
      <div><span>EPI vencido</span><b class="${summary.ppe_expired ? "bad-text" : ""}">${summary.ppe_expired}</b></div>
      <div><span>Sem foto</span><b>${summary.without_photo}</b></div>
      <div><span>Treinamentos agendados</span><b>${summary.trainings_scheduled}</b></div>
    </div>
    <div class="label-strong" style="margin-top:14px">Por setor</div>
    ${summary.by_sector.map((s) => `<div class="kv-row"><span>${esc(s.sector)}</span><b>${s.count}</b></div>`).join("")}`;
}

function renderList() {
  root.innerHTML = `
    <div class="toolbar" style="margin-top:0">
      <span id="people-count" class="hint"></span>
      <div class="actions">
        ${can("gestor") ? `<button type="button" class="secondary" id="people-import">Importar planilha</button>
          <button type="button" id="people-new">+ Nova pessoa</button>` : ""}
      </div>
    </div>
    <div class="notice">
      <b>Dados pessoais protegidos (LGPD).</b> CPF mascarado para técnicos; completo só para gestores e administradores, com registro
      em auditoria. A foto serve para identificação visual pela equipe de segurança — <b>não</b> há reconhecimento facial.
    </div>
    <form id="people-filters" class="filters" role="search">
      <label>Buscar <input name="q" placeholder="Nome, matrícula, CPF ou nº do colete" value="${esc(filters.q)}"></label>
      <label>Unidade <select name="unit_id"><option value="">Todas</option>${units.map((u) => `<option value="${u.id}">${esc(u.name)}</option>`).join("")}</select></label>
      <label>Setor <select name="sector_id"><option value="">Todos</option>${sectors.map((s) => `<option value="${s.id}">${esc(s.name)}</option>`).join("")}</select></label>
      <label>Situação <select name="status">
        <option value="ativo,afastado">Ativos e afastados</option><option value="ativo">Ativos</option>
        <option value="afastado">Afastados</option><option value="desligado">Desligados</option><option value="">Todos</option></select></label>
    </form>
    <div class="split">
      <div class="split-main"><div class="table-wrap"><table id="people-table"></table></div><div id="people-pages" class="actions" style="margin-top:10px"></div></div>
      <aside class="split-side card" id="people-summary"></aside>
    </div>`;
  const f = $("#people-filters", root);
  f.unit_id.value = filters.unit_id;
  f.sector_id.value = filters.sector_id;
  f.status.value = filters.status;
  let timer;
  f.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      Object.assign(filters, { q: f.q.value, unit_id: f.unit_id.value, sector_id: f.sector_id.value, status: f.status.value, offset: 0 });
      loadList().catch((err) => toast(esc(err.message), "danger"));
    }, 250);
  });
  f.addEventListener("submit", (e) => e.preventDefault());
  $("#people-table", root).addEventListener("click", (e) => {
    const row = e.target.closest("tr[data-id]");
    if (row) openPerson(Number(row.dataset.id));
  });
  $("#people-pages", root).addEventListener("click", (e) => {
    const btn = e.target.closest("[data-page]");
    if (btn) { filters.offset = (Number(btn.dataset.page) - 1) * 50; loadList(); }
  });
  $("#people-new", root)?.addEventListener("click", () => openPerson("new"));
  $("#people-import", root)?.addEventListener("click", openImport);
  loadList().catch((err) => toast(esc(err.message), "danger"));
}

// ---------- Cadastro ----------

function sectorOptions(unitId, selected) {
  return `<option value="">Sem setor</option>` + sectors.filter((s) => s.unit_id === unitId)
    .map((s) => `<option value="${s.id}" ${s.id === selected ? "selected" : ""}>${esc(s.name)}</option>`).join("");
}

async function openPerson(id) {
  editing = id;
  const p = id === "new"
    ? { unit_id: units[0]?.id, sector_id: null, name: "", cpf: "", registration: "", role: "", shift: "", employment: "clt",
      company: "", manager: "", badge_code: "", photo_consent: false, status: "ativo", deliveries: [], trainings: [],
      required_ppe: [], delivery_ppe: [], has_photo: false }
    : await api(`/api/people/${id}`);
  const ro = can("gestor") ? "" : "disabled";
  root.innerHTML = `
    <div class="toolbar" style="margin-top:0">
      <button type="button" class="secondary" id="person-back">← Pessoas</button>
      <div class="actions">
        ${id !== "new" ? `<button type="button" class="secondary" id="person-history">Histórico de segurança</button>` : ""}
        ${can("gestor") ? `<button type="submit" form="person-form">${id === "new" ? "Cadastrar" : "Salvar cadastro"}</button>` : ""}
      </div>
    </div>
    <div class="split">
      <aside class="split-side card photo-card">
        <div class="label-strong">Foto de identificação</div>
        <div class="photo-frame">${p.has_photo ? `<img src="${esc(withToken(`/api/people/${p.id}/photo?t=${Date.now()}`))}" alt="Foto de ${esc(p.name)}">`
          : `<span class="hint">Sem foto</span>`}</div>
        ${can("gestor") ? `
          <div class="actions photo-actions">
            <label class="button secondary small file-btn">📎 Anexar foto
              <input type="file" id="photo-file" accept="image/jpeg,image/png" hidden></label>
            <button type="button" class="secondary small" id="photo-camera">📷 Tirar foto</button>
            ${p.has_photo ? `<button type="button" class="danger small" id="photo-remove">Remover</button>` : ""}
          </div>
          <p class="hint" id="photo-pending" hidden></p>` : ""}
        <ul class="hint tight"><li>Rosto inteiro, de frente, fundo neutro</li><li>Sem óculos escuros, boné ou capacete</li><li>JPG ou PNG, até 5 MB</li></ul>
      </aside>

      <form id="person-form" class="split-main card form">
        <h2>${id === "new" ? "Nova pessoa" : esc(p.name)}</h2>
        <label class="wide">Nome completo <input name="name" value="${esc(p.name)}" required minlength="3" ${ro}></label>
        <label>CPF <input name="cpf" class="mono" value="${esc(p.cpf)}" required inputmode="numeric" placeholder="000.000.000-00" ${id !== "new" && !can("gestor") ? "disabled" : ro}>
          <small class="hint" id="cpf-hint"></small></label>
        <label>Matrícula <input name="registration" value="${esc(p.registration || "")}" ${ro}></label>
        <label>Vínculo <select name="employment" ${ro}>${Object.entries(EMPLOYMENT).map(([k, v]) => `<option value="${k}" ${p.employment === k ? "selected" : ""}>${v}</option>`).join("")}</select></label>
        <label>Empresa (terceiros) <input name="company" value="${esc(p.company)}" ${ro}></label>
        <label>Unidade <select name="unit_id" ${ro}>${units.map((u) => `<option value="${u.id}" ${u.id === p.unit_id ? "selected" : ""}>${esc(u.name)}</option>`).join("")}</select></label>
        <label>Setor <select name="sector_id" ${ro}>${sectorOptions(p.unit_id, p.sector_id)}</select></label>
        <label>Função <input name="role" value="${esc(p.role)}" ${ro}></label>
        <label>Turno <select name="shift" ${ro}><option value="">–</option>${shifts().map((s) => `<option ${s === p.shift ? "selected" : ""}>${s}</option>`).join("")}</select></label>
        <label>Gestor imediato <input name="manager" value="${esc(p.manager)}" ${ro}></label>
        <label>Nº do colete / crachá <input name="badge_code" class="mono" value="${esc(p.badge_code || "")}" placeholder="ex.: 0417" ${ro}>
          <small class="hint">Ajuda a identificar sem biometria</small></label>
        <label>Situação <select name="status" ${ro}>${Object.entries(STATUS).map(([k, v]) => `<option value="${k}" ${p.status === k ? "selected" : ""}>${v[0]}</option>`).join("")}</select></label>
        <label class="check wide consent"><input type="checkbox" name="photo_consent" ${p.photo_consent ? "checked" : ""} ${ro}>
          Colaborador ciente do uso da foto para identificação visual (termo assinado)${p.photo_consent_on ? ` em ${fmtDate(p.photo_consent_on)}` : ""}</label>
        ${p.required_ppe.length || p.delivery_ppe.length ? `<div class="wide standard-box"><b>Padrão do setor ${esc(p.sector || "")}:</b>
          ${[...p.required_ppe, ...p.delivery_ppe].map((i) => badge(i, "")).join(" ")}</div>` : ""}
      </form>
    </div>

    ${id !== "new" ? `
    <div class="grid-2" style="margin-top:16px">
      <div class="card">
        <h3>EPIs entregues</h3>
        <table class="compact">
          <tr><th>EPI</th><th>CA</th><th>Entrega</th><th>Validade</th><th></th></tr>
          ${p.deliveries.map((d) => `<tr><td>${esc(d.item)}</td><td class="mono">${esc(d.ca)}</td><td>${fmtDate(d.delivered_on)}</td>
            <td>${fmtDate(d.valid_until)}</td><td>${can("tecnico") ? `<button class="danger small" data-del-delivery="${d.id}">×</button>` : ""}</td></tr>`).join("")
            || `<tr><td class="hint" colspan="5">Nenhuma entrega registrada.</td></tr>`}
        </table>
        ${can("tecnico") ? `<form id="delivery-form" class="form" style="margin-top:12px">
          <label>EPI <input name="item" required list="ppe-items"></label>
          <datalist id="ppe-items">${[...p.required_ppe, ...p.delivery_ppe].map((i) => `<option value="${esc(i[0].toUpperCase() + i.slice(1))}">`).join("")}</datalist>
          <label>CA <input name="ca" class="mono"></label>
          <label>Entrega <input name="delivered_on" type="date" required></label>
          <label>Validade <input name="valid_until" type="date"></label>
          <div class="actions"><button type="submit" class="secondary">Registrar entrega</button></div>
        </form>` : ""}
      </div>
      <div class="card">
        <h3>Treinamentos</h3>
        <table class="compact">
          <tr><th>Treinamento</th><th>Data</th><th>Validade</th><th>Situação</th></tr>
          ${p.trainings.map((t) => `<tr><td>${esc(t.name)}${t.measure_id ? ` ${badge("por medida", "")}` : ""}</td><td>${fmtDate(t.scheduled_on)}</td>
            <td>${fmtDate(t.valid_until)}</td><td>${can("tecnico") && t.status === "agendado"
              ? `<button class="small" data-done-training="${t.id}">Concluir</button>` : badge(TRAINING[t.status][0], TRAINING[t.status][1])}</td></tr>`).join("")
            || `<tr><td class="hint" colspan="4">Nenhum treinamento registrado.</td></tr>`}
        </table>
        ${can("tecnico") ? `<form id="training-form" class="form" style="margin-top:12px">
          <label class="wide">Treinamento <input name="name" required placeholder="ex.: NR-12 · segurança em máquinas"></label>
          <label>Data <input name="scheduled_on" type="date"></label>
          <label>Validade <input name="valid_until" type="date"></label>
          <label>Situação <select name="status"><option value="concluido">Concluído</option><option value="agendado">Agendado</option></select></label>
          <div class="actions"><button type="submit" class="secondary">Registrar</button></div>
        </form>` : ""}
      </div>
    </div>` : ""}`;

  const f = $("#person-form", root);
  $("#person-back", root).addEventListener("click", () => { editing = null; renderList(); });
  $("#person-history", root)?.addEventListener("click", () => onOpenHistory?.(p.id));
  f.unit_id.addEventListener("change", () => { f.sector_id.innerHTML = sectorOptions(Number(f.unit_id.value), null); });
  f.cpf.addEventListener("input", () => {
    const ok = validCpf(f.cpf.value);
    $("#cpf-hint", root).textContent = f.cpf.value.replace(/\D/g, "").length < 11 ? "" : ok ? "✓ CPF válido" : "✗ CPF inválido";
    $("#cpf-hint", root).className = ok ? "hint good-text" : "hint bad-text";
  });
  // Foto escolhida antes de salvar (pessoa nova, ou ciência marcada agora): fica em espera e
  // é enviada junto com o cadastro, depois que a ciência estiver gravada.
  let pendingPhoto = null;
  const consentNow = () => f.photo_consent.checked;
  const requireConsent = () => {
    if (consentNow()) return true;
    toast("Marque a ciência do colaborador sobre o uso da foto (termo assinado) antes de anexar ou tirar a foto.", "warn", 5000);
    f.photo_consent.closest("label").scrollIntoView({ behavior: "smooth", block: "center" });
    f.photo_consent.focus();
    return false;
  };

  f.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!validCpf(f.cpf.value)) return toast("CPF inválido.", "warn");
    if (pendingPhoto && !consentNow()) return requireConsent();
    const body = {
      unit_id: Number(f.unit_id.value), sector_id: f.sector_id.value ? Number(f.sector_id.value) : null,
      name: f.name.value, cpf: f.cpf.value, registration: f.registration.value, role: f.role.value, shift: f.shift.value,
      employment: f.employment.value, company: f.company.value, manager: f.manager.value, badge_code: f.badge_code.value,
      photo_consent: f.photo_consent.checked, status: f.status.value,
    };
    if (body.status === "desligado" && p.has_photo && !confirm("Ao desligar, a foto de identificação é apagada. Continuar?")) return;
    try {
      const saved = id === "new" ? await api("/api/people", { method: "POST", body })
        : await api(`/api/people/${id}`, { method: "PUT", body });
      if (pendingPhoto) {
        const data = new FormData();
        data.append("photo", pendingPhoto, "foto.jpg");
        try {
          await api(`/api/people/${saved.id}/photo`, { method: "POST", body: data });
        } catch (err) { toast(`Cadastro salvo, mas a foto não foi enviada: ${esc(err.message)}`, "danger"); }
      }
      toast(id === "new" ? "Pessoa cadastrada." : "Cadastro salvo.", "ok", 3000);
      openPerson(saved.id);
    } catch (err) { toast(esc(err.message), "danger"); }
  });

  const usePhoto = (blob) => {
    if (!/^image\/(jpeg|png)$/.test(blob.type)) return toast("Use uma foto JPG ou PNG.", "warn");
    if (blob.size > 5 * 1024 * 1024) return toast("A foto tem mais de 5 MB.", "warn");
    if (id !== "new" && p.photo_consent) return uploadPhoto(blob); // ciência já gravada: envia na hora
    pendingPhoto = blob;
    const frame = $(".photo-frame", root);
    frame.innerHTML = `<img src="${URL.createObjectURL(blob)}" alt="Prévia da foto">`;
    const note = $("#photo-pending", root);
    note.hidden = false;
    note.textContent = `Prévia – a foto será enviada ao clicar em "${id === "new" ? "Cadastrar" : "Salvar cadastro"}".`;
  };
  const uploadPhoto = async (blob) => {
    const data = new FormData();
    data.append("photo", blob, "foto.jpg");
    try {
      await api(`/api/people/${p.id}/photo`, { method: "POST", body: data });
      toast("Foto atualizada.", "ok", 2500);
      openPerson(p.id);
    } catch (err) { toast(esc(err.message), "danger"); }
  };
  $("#photo-file", root)?.addEventListener("click", (e) => { if (!requireConsent()) e.preventDefault(); });
  $("#photo-file", root)?.addEventListener("change", (e) => { if (e.target.files[0]) usePhoto(e.target.files[0]); e.target.value = ""; });
  $("#photo-camera", root)?.addEventListener("click", () => { if (requireConsent()) captureFromCamera(usePhoto); });
  $("#photo-remove", root)?.addEventListener("click", async () => {
    if (!confirm("Remover a foto?")) return;
    await api(`/api/people/${p.id}/photo`, { method: "DELETE" });
    openPerson(p.id);
  });
  $("#delivery-form", root)?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const d = e.target;
    try {
      await api(`/api/people/${p.id}/deliveries`, { method: "POST", body: {
        item: d.item.value, ca: d.ca.value, delivered_on: d.delivered_on.value, valid_until: d.valid_until.value || null } });
      openPerson(p.id);
    } catch (err) { toast(esc(err.message), "danger"); }
  });
  root.querySelectorAll("[data-del-delivery]").forEach((b) => b.addEventListener("click", async () => {
    if (!confirm("Excluir este registro de entrega?")) return;
    await api(`/api/people/${p.id}/deliveries/${b.dataset.delDelivery}`, { method: "DELETE" });
    openPerson(p.id);
  }));
  $("#training-form", root)?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const t = e.target;
    try {
      await api(`/api/people/${p.id}/trainings`, { method: "POST", body: {
        name: t.name.value, scheduled_on: t.scheduled_on.value || null, valid_until: t.valid_until.value || null, status: t.status.value } });
      openPerson(p.id);
    } catch (err) { toast(esc(err.message), "danger"); }
  });
  root.querySelectorAll("[data-done-training]").forEach((b) => b.addEventListener("click", async () => {
    const t = p.trainings.find((x) => x.id === Number(b.dataset.doneTraining));
    await api(`/api/people/${p.id}/trainings/${t.id}`, { method: "PATCH", body: { ...t, status: "concluido" } });
    openPerson(p.id);
  }));
}

function validCpf(value) {
  const cpf = value.replace(/\D/g, "");
  if (cpf.length !== 11 || /^(\d)\1+$/.test(cpf)) return false;
  for (const size of [9, 10]) {
    let total = 0;
    for (let i = 0; i < size; i++) total += Number(cpf[i]) * (size + 1 - i);
    if (((total * 10) % 11) % 10 !== Number(cpf[size])) return false;
  }
  return true;
}

// Captura pela webcam (requer HTTPS ou localhost)
function captureFromCamera(onBlob) {
  const dialog = document.createElement("dialog");
  dialog.className = "form-dialog";
  dialog.innerHTML = `
    <h2>Tirar foto</h2>
    <p class="hint">Enquadre o rosto no centro. A foto sai no formato 3×4, como na prévia.</p>
    <video autoplay playsinline muted style="display:block;height:min(60vh,520px);max-width:100%;aspect-ratio:3/4;object-fit:cover;margin:0 auto;border-radius:8px;background:#000"></video>
    <div class="actions" style="margin-top:12px">
      <button type="button" data-shot>Capturar</button><button type="button" class="secondary" data-cancel>Cancelar</button>
    </div>`;
  document.body.append(dialog);
  const video = dialog.querySelector("video");
  let stream;
  const close = () => { stream?.getTracks().forEach((t) => t.stop()); dialog.close(); dialog.remove(); };
  navigator.mediaDevices?.getUserMedia({ video: { width: 960, height: 1280 } })
    .then((s) => { stream = s; video.srcObject = s; })
    .catch(() => { toast("Não foi possível acessar a câmera. Use 'Anexar foto' (a câmera exige HTTPS ou acesso local, e permissão no navegador).", "warn"); close(); });
  dialog.querySelector("[data-cancel]").addEventListener("click", close);
  dialog.querySelector("[data-shot]").addEventListener("click", () => {
    const canvas = document.createElement("canvas");
    const h = video.videoHeight;
    const w = Math.round(h * 3 / 4); // recorte 3×4 centralizado
    canvas.width = w; canvas.height = h;
    canvas.getContext("2d").drawImage(video, (video.videoWidth - w) / 2, 0, w, h, 0, 0, w, h);
    canvas.toBlob((blob) => { close(); onBlob(blob); }, "image/jpeg", 0.9);
  });
  dialog.showModal();
}

// ---------- Importação ----------

function openImport() {
  const dialog = document.createElement("dialog");
  dialog.className = "form-dialog";
  dialog.innerHTML = `
    <h2>Importar pessoas de planilha</h2>
    <p class="hint">Arquivo CSV (Excel: "Salvar como" → CSV). Colunas: nome, cpf, matricula, unidade, setor, funcao, turno, vinculo,
      empresa, gestor, colete. Pessoas já cadastradas (mesmo CPF) são atualizadas. <a href="${esc(withToken("/api/people/import/template"))}">Baixar modelo</a></p>
    <input type="file" accept=".csv,text/csv">
    <div class="import-result"></div>
    <div class="actions" style="margin-top:12px"><button type="button" data-go>Importar</button><button type="button" class="secondary" data-close>Fechar</button></div>`;
  document.body.append(dialog);
  dialog.addEventListener("close", () => { dialog.remove(); if (!editing) loadList(); });
  dialog.querySelector("[data-go]").addEventListener("click", async () => {
    const file = dialog.querySelector("input").files[0];
    if (!file) return toast("Escolha o arquivo.", "warn");
    const data = new FormData();
    data.append("file", file);
    try {
      const r = await api("/api/people/import", { method: "POST", body: data });
      dialog.querySelector(".import-result").innerHTML = `
        <p>${badge(`${r.created} nova(s)`, "good")} ${badge(`${r.updated} atualizada(s)`, "")} ${r.total_errors ? badge(`${r.total_errors} com erro`, "bad") : ""}</p>
        ${r.errors.length ? `<table class="compact"><tr><th>Linha</th><th>Problema</th></tr>
          ${r.errors.map((e) => `<tr><td class="mono">${e.line}</td><td>${esc(e.message)}</td></tr>`).join("")}</table>` : ""}`;
    } catch (err) { toast(esc(err.message), "danger"); }
  });
  dialog.showModal();
}

export async function render(container, openId = null) {
  root = container;
  [units, sectors] = await Promise.all([api("/api/units"), api("/api/sectors")]);
  if (openId) return openPerson(openId);
  editing = null;
  renderList();
}
