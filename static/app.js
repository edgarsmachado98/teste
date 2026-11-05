"use strict";

const brl = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
const num = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 8 });
const pct = (v, casas = 2) => v == null ? "—" : `${(v).toFixed(casas).replace(".", ",")}%`;
const pctFrac = v => v == null ? "—" : pct(v * 100);
const classeSinal = v => v > 0 ? "pos" : v < 0 ? "neg" : "";
const fmtData = s => s.split("-").reverse().join("/");
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const $ = sel => document.querySelector(sel);
const PALETA = ["#2f5bea", "#e07b39", "#3a9d5d", "#c8312f", "#8457c5", "#1aa3b8", "#c59b24", "#d0558f", "#5f6b7a", "#7fb03a"];
const graficos = {};

function toast(msg, erro = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "mostrar" + (erro ? " erro" : "");
  clearTimeout(t._timer);
  t._timer = setTimeout(() => (t.className = ""), 3500);
}

// Carteira selecionada: enviada em todas as requisições pelo cabeçalho X-Carteira.
let carteiraAtual = null;
let carteiras = [];
const permissao = () => carteiras.find(c => c.id === carteiraAtual)?.permissoes || { ver: false, editar: false, gerenciar: false };

async function api(url, opts = {}) {
  const headers = { "Content-Type": "application/json", "X-Requested-With": "fetch" };
  if (carteiraAtual) headers["X-Carteira"] = String(carteiraAtual);
  const r = await fetch(url, { ...opts, headers, body: opts.body ? JSON.stringify(opts.body) : undefined });
  if (r.status === 401) { location.href = "/login"; throw new Error("Sessão expirada."); }
  const dados = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(dados.erro || `Erro ${r.status}`);
  return dados;
}

function grafico(id, config) {
  graficos[id]?.destroy();
  const cor = getComputedStyle(document.documentElement).getPropertyValue("--suave").trim();
  Chart.defaults.color = cor;
  Chart.defaults.borderColor = getComputedStyle(document.documentElement).getPropertyValue("--borda").trim();
  graficos[id] = new Chart(document.getElementById(id), config);
}

function formDados(form) {
  const d = Object.fromEntries(new FormData(form).entries());
  form.querySelectorAll("input[type=checkbox]").forEach(c => (d[c.name] = c.checked));
  return d;
}

// ---------------- Navegação ----------------
document.querySelectorAll("nav button").forEach(b => b.addEventListener("click", () => {
  document.querySelectorAll("nav button").forEach(x => x.classList.toggle("ativo", x === b));
  $("#titulo-pagina").textContent = b.dataset.titulo;
  $("#sub-pagina").textContent = b.dataset.sub;
  document.title = `${b.dataset.titulo} · Carteira de Aportes`;
  document.body.classList.remove("menu-aberto");
  window.scrollTo({ top: 0 });
  document.querySelectorAll(".tab").forEach(t => t.classList.toggle("visivel", t.id === "tab-" + b.dataset.tab));
  ({ carteira: carregarCarteira, aportes: carregarAportes, ativos: carregarAtivos, proventos: carregarProventos, acessos: carregarAcessos, fluxo: carregarFluxo }[b.dataset.tab] || (() => {}))();
}));

// ---------------- Carteira ----------------
async function carregarCarteira() {
  let c;
  try { c = await api("/api/carteira"); } catch (e) { return toast(e.message, true); }
  $("#cards-resumo").innerHTML = [
    ["Patrimônio", brl.format(c.total_valor)],
    ["Total investido (custo)", brl.format(c.total_custo)],
    ["Resultado não realizado", `<span class="${classeSinal(c.lucro)}">${brl.format(c.lucro)} (${pct(c.lucro_pct)})</span>`],
    ["Resultado realizado", `<span class="${classeSinal(c.realizado)}">${brl.format(c.realizado)}</span>`],
    ["Proventos (12 meses)", `<span class="pos">${brl.format(c.proventos.ult_12m)}</span>`],
    ["Yield on cost (12 meses)", pct(c.proventos.yoc_pct)],
  ].map(([r, v]) => `<div class="card"><div class="rotulo">${r}</div><div class="valor">${v}</div></div>`).join("");

  const comPosicao = c.ativos.filter(a => a.quantidade > 0);
  $("#tabela-posicoes").innerHTML = `<tr><th>Ativo</th><th>Classe</th><th>Qtd.</th><th>Preço médio</th><th>Preço atual</th>
    <th>Valor</th><th>Resultado</th><th>Proventos 12m</th><th>YoC</th><th>Peso</th><th>Meta</th><th>Desvio</th></tr>` +
    (comPosicao.length ? comPosicao.map(a => `<tr>
      <td><strong>${esc(a.ticker)}</strong> <small>${esc(a.nome)}</small></td>
      <td>${esc(CLASSES[a.classe] || a.classe)}</td>
      <td>${num.format(a.quantidade)}</td>
      <td>${brl.format(a.preco_medio)}</td>
      <td title="Fonte: ${esc(a.fonte_preco || "indisponível — usando custo")}">${a.preco_atual == null ? "—" : brl.format(a.preco_atual)}${a.fonte_preco && a.fonte_preco !== "yahoo" ? ` <span class="selo">${esc(a.fonte_preco)}</span>` : ""}</td>
      <td>${brl.format(a.valor)}</td>
      <td class="${classeSinal(a.lucro)}">${brl.format(a.lucro)} (${pct(a.lucro_pct)})</td>
      <td>${a.proventos_12m ? brl.format(a.proventos_12m) : "—"}</td>
      <td>${pct(a.yoc_pct)}</td>
      <td>${pct(a.peso_pct)}</td>
      <td>${pct(a.meta_norm_pct)}</td>
      <td>${a.desvio_pct > 0 ? "+" : ""}${pct(a.desvio_pct)}</td>
    </tr>`).join("") : `<tr><td colspan="12">Nenhuma posição. Registre seu primeiro aporte na aba “Aportes”.</td></tr>`);

  grafico("graf-alocacao", {
    type: "bar",
    data: {
      labels: comPosicao.map(a => a.ticker),
      datasets: [
        { label: "Atual (%)", data: comPosicao.map(a => a.peso_pct), backgroundColor: PALETA[0] },
        { label: "Meta (%)", data: comPosicao.map(a => a.meta_norm_pct), backgroundColor: PALETA[1] },
      ],
    },
    options: { aspectRatio: 1.8, plugins: { tooltip: { callbacks: { label: x => `${x.dataset.label}: ${pct(x.raw)}` } } } },
  });
  grafico("graf-classe", {
    type: "doughnut",
    data: { labels: c.por_classe.map(x => x.rotulo), datasets: [{ data: c.por_classe.map(x => x.valor), backgroundColor: PALETA }] },
    options: { aspectRatio: 1.8, plugins: { legend: { position: "right" }, tooltip: { callbacks: { label: x => `${x.label}: ${brl.format(x.raw)} (${pct(c.por_classe[x.dataIndex].pct)})` } } } },
  });
  grafico("graf-evolucao", {
    data: {
      labels: c.evolucao_aportes.map(x => x.mes),
      datasets: [
        { type: "bar", label: "Aporte líquido no mês", data: c.evolucao_aportes.map(x => x.aporte), backgroundColor: PALETA[0], yAxisID: "y" },
        { type: "line", label: "Investido acumulado", data: c.evolucao_aportes.map(x => x.acumulado), borderColor: PALETA[1], backgroundColor: PALETA[1], yAxisID: "y" },
      ],
    },
    options: { scales: { y: { ticks: { callback: v => brl.format(v) } } }, plugins: { tooltip: { callbacks: { label: x => `${x.dataset.label}: ${brl.format(x.raw)}` } } } },
  });
}

// ---------------- Aportes ----------------
async function carregarAportes() {
  try {
    const [aportes, ativos] = await Promise.all([api("/api/aportes"), api("/api/ativos")]);
    $("#lista-tickers").innerHTML = ativos.map(a => `<option value="${esc(a.ticker)}">${esc(a.nome)}</option>`).join("");
    $("#tabela-aportes").innerHTML = `<tr><th>Data</th><th>Ativo</th><th>Tipo</th><th>Qtd.</th><th>Preço</th><th>Taxas</th><th>Total</th><th>Obs.</th><th></th></tr>` +
      (aportes.length ? aportes.map(a => `<tr>
        <td>${fmtData(a.data)}</td><td><strong>${esc(a.ticker)}</strong></td>
        <td class="${a.tipo === "compra" ? "pos" : "neg"}">${a.tipo === "compra" ? "Compra" : "Venda"}</td>
        <td>${num.format(a.quantidade)}</td><td>${brl.format(a.preco)}</td><td>${brl.format(a.taxas)}</td>
        <td>${brl.format(a.quantidade * a.preco + (a.tipo === "compra" ? a.taxas : -a.taxas))}</td>
        <td>${esc(a.obs)}</td>
        <td><button class="link requer-edicao" data-remover-aporte="${a.id}">excluir</button></td></tr>`).join("")
        : `<tr><td colspan="9">Nenhum aporte registrado.</td></tr>`);
  } catch (e) { toast(e.message, true); }
}

$("#form-aporte").addEventListener("submit", async ev => {
  ev.preventDefault();
  try {
    await api("/api/aportes", { method: "POST", body: formDados(ev.target) });
    toast("Operação registrada.");
    const data = ev.target.data.value;
    ev.target.reset();
    ev.target.data.value = data;
    carregarAportes();
  } catch (e) { toast(e.message, true); }
});

$("#tabela-aportes").addEventListener("click", async ev => {
  const id = ev.target.dataset.removerAporte;
  if (!id || !confirm("Excluir este aporte?")) return;
  try { await api(`/api/aportes/${id}`, { method: "DELETE" }); toast("Aporte excluído."); carregarAportes(); }
  catch (e) { toast(e.message, true); }
});

// ---------------- Fluxo financeiro ----------------
let fluxoAtual = null;
const isoData = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

function periodoFluxo() {
  const f = $("#form-fluxo"), hoje = new Date(), ano = hoje.getFullYear();
  const p = f.periodo.value;
  if (p === "12m") { const i = new Date(hoje); i.setFullYear(ano - 1); i.setDate(i.getDate() + 1); return [isoData(i), isoData(hoje)]; }
  if (p === "ano") return [`${ano}-01-01`, isoData(hoje)];
  if (p === "ano_anterior") return [`${ano - 1}-01-01`, `${ano - 1}-12-31`];
  if (p === "tudo") return ["", isoData(hoje)];
  return [f.inicio.value, f.fim.value || isoData(hoje)];
}

$("#form-fluxo").periodo.addEventListener("change", ev => {
  const [i, f] = periodoFluxo();
  if (ev.target.value !== "personalizado") { $("#form-fluxo").inicio.value = i; $("#form-fluxo").fim.value = f; carregarFluxo(); }
});
$("#form-fluxo").addEventListener("submit", ev => { ev.preventDefault(); carregarFluxo(); });
["inicio", "fim"].forEach(n => $("#form-fluxo")[n].addEventListener("change", () => ($("#form-fluxo").periodo.value = "personalizado")));
$("#filtro-fluxo").addEventListener("change", renderExtratoFluxo);

async function carregarFluxo() {
  const f = $("#form-fluxo");
  let [inicio, fim] = periodoFluxo();
  if (f.periodo.value !== "personalizado") { f.inicio.value = inicio; f.fim.value = fim; }
  try { fluxoAtual = await api(`/api/fluxo?${new URLSearchParams({ inicio, fim })}`); }
  catch (e) { return toast(e.message, true); }
  const t = fluxoAtual.totais;
  $("#cards-fluxo").innerHTML = [
    ["Compras", brl.format(t.compras), ""],
    ["Vendas", brl.format(t.vendas), ""],
    ["Aporte líquido", brl.format(t.aporte_liquido), classeSinal(t.aporte_liquido)],
    ["Proventos recebidos", brl.format(t.proventos), "pos"],
    ["Lucro realizado nas vendas", brl.format(t.lucro_realizado), classeSinal(t.lucro_realizado)],
  ].map(([r, v, c]) => `<div class="card"><div class="rotulo">${r}</div><div class="valor ${c}">${v}</div></div>`).join("") +
    `<p class="dica" style="grid-column:1/-1;margin:0">${t.operacoes} operação(ões) e ${t.recebimentos} recebimento(s) no período.
     Aporte líquido = compras − vendas. O lucro realizado usa o preço médio de cada ativo no momento da venda.</p>`;

  grafico("graf-fluxo", {
    type: "bar",
    data: { labels: fluxoAtual.por_mes.map(m => m.mes), datasets: [
      { label: "Compras", data: fluxoAtual.por_mes.map(m => m.compras), backgroundColor: PALETA[0] },
      { label: "Vendas", data: fluxoAtual.por_mes.map(m => m.vendas), backgroundColor: PALETA[3] },
      { label: "Proventos recebidos", data: fluxoAtual.por_mes.map(m => m.proventos), backgroundColor: PALETA[2] },
    ] },
    options: { interaction: { mode: "index", intersect: false }, scales: { y: { ticks: { callback: v => brl.format(v) } } },
      plugins: { tooltip: { callbacks: { label: x => `${x.dataset.label}: ${brl.format(x.raw)}` } } } },
  });

  $("#tabela-fluxo-ativo").innerHTML = `<tr><th>Ativo</th><th>Compras</th><th>Vendas</th><th>Proventos</th><th>Lucro realizado</th></tr>` +
    (fluxoAtual.por_ativo.length ? fluxoAtual.por_ativo.map(a => `<tr><td><strong>${esc(a.ticker)}</strong></td>
      <td>${a.compras ? brl.format(a.compras) : "—"}</td><td>${a.vendas ? brl.format(a.vendas) : "—"}</td>
      <td class="pos">${a.proventos ? brl.format(a.proventos) : "—"}</td>
      <td class="${classeSinal(a.lucro_realizado)}">${a.vendas ? brl.format(a.lucro_realizado) : "—"}</td></tr>`).join("") +
      `<tr><td><strong>Total</strong></td><td><strong>${brl.format(t.compras)}</strong></td><td><strong>${brl.format(t.vendas)}</strong></td>
       <td class="pos"><strong>${brl.format(t.proventos)}</strong></td><td class="${classeSinal(t.lucro_realizado)}"><strong>${brl.format(t.lucro_realizado)}</strong></td></tr>`
      : `<tr><td colspan="5">Nenhuma movimentação no período.</td></tr>`);
  renderExtratoFluxo();
}

function renderExtratoFluxo() {
  if (!fluxoAtual) return;
  const filtro = $("#filtro-fluxo").value;
  const itens = fluxoAtual.lancamentos.filter(l => !filtro || (filtro === "provento" ? !["compra", "venda"].includes(l.tipo) : l.tipo === filtro));
  const rotulo = t => t === "compra" ? "Compra" : t === "venda" ? "Venda" : nomeTipo(t);
  const cor = t => t === "compra" ? "" : t === "venda" ? "neg" : "pos";
  $("#tabela-fluxo").innerHTML = `<tr><th>Data</th><th>Ativo</th><th>Tipo</th><th>Qtd.</th><th>Preço</th><th>Valor</th><th>Lucro na venda</th><th>Obs.</th></tr>` +
    (itens.length ? itens.slice(0, 500).map(l => `<tr><td>${fmtData(l.data)}</td><td><strong>${esc(l.ticker)}</strong></td>
      <td class="${cor(l.tipo)}">${esc(rotulo(l.tipo))}</td><td>${l.quantidade == null ? "—" : num.format(l.quantidade)}</td>
      <td>${l.preco == null ? "—" : brl.format(l.preco)}</td><td class="${cor(l.tipo)}">${brl.format(l.valor)}</td>
      <td class="${classeSinal(l.lucro)}">${l.lucro == null ? "" : brl.format(l.lucro)}</td><td>${esc(l.obs)}</td></tr>`).join("")
      : `<tr><td colspan="8">Nenhum lançamento.</td></tr>`);
}

// ---------------- Importação B3 ----------------
let previaB3 = null;

$("#form-importar-b3").addEventListener("submit", async ev => {
  ev.preventDefault();
  const alvo = $("#resultado-importar-b3");
  const fd = new FormData(ev.target);
  alvo.innerHTML = `<p class="dica">Lendo arquivo…</p>`;
  try {
    const r = await fetch("/api/importar/b3/previa", { method: "POST", body: fd,
      headers: { "X-Requested-With": "fetch", "X-Carteira": String(carteiraAtual) } });
    if (r.status === 401) { location.href = "/login"; return; }
    previaB3 = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(previaB3.erro || `Erro ${r.status}`);
  } catch (e) { alvo.innerHTML = ""; return toast(e.message, true); }
  renderPreviaB3();
});

const ROTULO_ARQ = { negociacao: "Negociação", movimentacao: "Movimentação", eventos: "Eventos", posicao: "Posição / relatório" };

function renderPreviaB3() {
  const p = previaB3, alvo = $("#resultado-importar-b3");
  const marca = (lista, i, item) => `<input type="checkbox" data-lista="${lista}" data-idx="${i}" ${item.ja_registrado ? "disabled" : "checked"}>`;
  const status = item => item.ja_registrado ? `<span class="selo">já lançado</span>` : "novo";
  const conc = p.conciliacao;
  const iniciais = conc ? conc.posicoes_iniciais : [];
  const novos = p.aportes.filter(a => !a.ja_registrado).length + p.proventos.filter(x => !x.ja_registrado).length + iniciais.length;
  let html = `<div class="resumo-importacao">
      ${p.arquivos.map(a => `<span class="selo">${esc(ROTULO_ARQ[a.tipo] || a.tipo)}: ${esc(a.nome)}</span>`).join(" ")}
      <p class="dica">${p.posicao.length} ativo(s) na posição · ${p.aportes.length} operação(ões) · ${p.proventos.length} provento(s) ·
      ${p.ignorados.length} linha(s) ignorada(s) · <strong>${novos} item(ns) novo(s)</strong></p></div>`;
  if (p.aviso) html += `<div class="aviso" style="margin:10px 0">${esc(p.aviso)}</div>`;

  if (conc) {
    html += `<h3 style="margin-top:16px">Posição inicial</h3>
      <p class="dica">O que você já tinha antes da primeira operação dos extratos (data de abertura: <strong>${fmtData(conc.data_abertura)}</strong>),
      calculado pela diferença entre a posição informada no relatório e as operações. <strong>Informe o preço médio</strong> de cada ativo
      (está no app da corretora ou na declaração de IR); os preços sugeridos pela cotação são apenas estimativas.</p>`;
    html += iniciais.length ? `<div class="rolagem"><table><tr><th></th><th>Ativo</th><th>Classe</th><th>Qtd. inicial</th><th>Qtd. no relatório</th><th>Preço médio (R$)</th><th>Origem do preço</th></tr>
      ${iniciais.map((x, i) => `<tr><td><input type="checkbox" data-lista="iniciais" data-idx="${i}" checked></td>
        <td><strong>${esc(x.ticker)}</strong></td><td>${esc(CLASSES[x.classe] || x.classe)}</td>
        <td><input type="number" step="any" min="0" class="qtd-inicial" data-idx="${i}" value="${x.quantidade}" style="width:100px">
          ${x.quantidade_estimada ? `<br><small class="neg">estimada pela cotação: confira</small>` : ""}</td><td>${num.format(x.qtd_b3)}</td>
        <td><input type="number" step="any" min="0" class="preco-inicial" data-idx="${i}" value="${x.preco == null ? "" : Number(x.preco.toFixed(4))}" placeholder="obrigatório" style="width:120px"></td>
        <td>${x.preco_origem ? esc(x.preco_origem) : `<span class="neg">informe o preço</span>`}</td></tr>`).join("")}</table></div>`
      : `<p class="dica">As operações dos extratos já explicam toda a posição da B3. Nenhuma posição inicial necessária.</p>`;
    if (conc.divergencias.length) html += `<details class="dica" open style="margin-top:10px"><summary>${conc.divergencias.length} divergência(s) para conferir</summary>
      <div class="rolagem"><table><tr><th>Ativo</th><th>Na B3</th><th>No sistema</th><th>O que verificar</th></tr>
      ${conc.divergencias.map(d => `<tr><td><strong>${esc(d.ticker)}</strong></td><td>${num.format(d.qtd_b3)}</td><td>${num.format(d.qtd_sistema)}</td><td style="white-space:normal">${esc(d.motivo)}</td></tr>`).join("")}</table></div></details>`;
    const mudancas = p.ajustes_ativos.filter(a => a.classe !== a.classe_atual || a.preco_manual != null);
    if (mudancas.length) html += `<label class="check" style="margin-top:10px;display:flex;gap:6px;align-items:center">
      <input type="checkbox" id="aplicar-ajustes" checked> Atualizar classe de ${p.ajustes_ativos.length} ativo(s) e o valor atual de renda fixa, Tesouro e fundos conforme o relatório (${mudancas.length} alteração(ões))</label>`;
  }

  if (p.aportes.length) html += `<h3 style="margin-top:16px">Operações</h3><div class="rolagem"><table><tr><th></th><th>Data</th><th>Ativo</th><th>Classe</th><th>Tipo</th><th>Qtd.</th><th>Preço</th><th>Total</th><th>Situação</th></tr>
    ${p.aportes.map((a, i) => `<tr class="${a.ja_registrado ? "desativado" : ""}"><td>${marca("aportes", i, a)}</td><td>${fmtData(a.data)}</td>
      <td><strong>${esc(a.ticker)}</strong></td><td>${esc(CLASSES[a.classe] || a.classe)}</td>
      <td class="${a.tipo === "compra" ? "pos" : "neg"}">${a.tipo === "compra" ? "Compra" : "Venda"}</td>
      <td>${num.format(a.quantidade)}</td><td>${brl.format(a.preco)}</td><td>${brl.format(a.quantidade * a.preco)}</td><td>${status(a)}</td></tr>`).join("")}</table></div>`;
  if (p.proventos.length) html += `<h3 style="margin-top:16px">Proventos</h3><div class="rolagem"><table><tr><th></th><th>Pagamento</th><th>Ativo</th><th>Tipo</th><th>Qtd.</th><th>Valor/cota</th><th>Total</th><th>Situação</th></tr>
    ${p.proventos.map((x, i) => `<tr class="${x.ja_registrado ? "desativado" : ""}"><td>${marca("proventos", i, x)}</td><td>${fmtData(x.data_pagamento)}</td>
      <td><strong>${esc(x.ticker)}</strong></td><td>${esc(nomeTipo(x.tipo))}</td><td>${x.quantidade == null ? "—" : num.format(x.quantidade)}</td>
      <td>${x.valor_unitario == null ? "—" : brl.format(x.valor_unitario)}</td><td class="pos">${brl.format(x.valor_total)}</td><td>${status(x)}</td></tr>`).join("")}</table></div>`;
  if (p.ignorados.length) html += `<details class="dica" style="margin-top:12px"><summary>${p.ignorados.length} linha(s) não importada(s)</summary>
    <div class="rolagem"><table><tr><th>Arquivo</th><th>Linha</th><th>Descrição</th><th>Motivo</th></tr>${p.ignorados.map(g => `<tr><td>${esc(g.arquivo || "")}</td><td>${g.linha}</td><td>${esc(g.descricao)}</td><td>${esc(g.motivo)}</td></tr>`).join("")}</table></div></details>`;
  if (novos || (conc && p.ajustes_ativos.length)) html += `<div class="acoes-import"><button type="button" class="btn" id="btn-confirmar-b3">Importar selecionados</button>
    <span class="dica">Confira as classes depois em “Ativos e metas” (tickers terminados em 11 podem ser FII, ETF ou unit).</span></div>`;
  alvo.innerHTML = html;
}

$("#resultado-importar-b3").addEventListener("click", async ev => {
  if (ev.target.id !== "btn-confirmar-b3") return;
  const sel = lista => [...document.querySelectorAll(`#resultado-importar-b3 input[data-lista="${lista}"]:checked`)].map(c => Number(c.dataset.idx));
  const iniciais = [];
  for (const i of sel("iniciais")) {
    const x = previaB3.conciliacao.posicoes_iniciais[i];
    const preco = parseFloat(document.querySelector(`.preco-inicial[data-idx="${i}"]`).value);
    const quantidade = parseFloat(document.querySelector(`.qtd-inicial[data-idx="${i}"]`).value);
    if (!(quantidade > 0)) return toast(`Informe a quantidade de ${x.ticker} (ou desmarque a linha).`, true);
    if (!(preco >= 0)) return toast(`Informe o preço médio de ${x.ticker} (ou desmarque a linha).`, true);
    iniciais.push({ data: x.data, ticker: x.ticker, tipo: "compra", quantidade, preco, classe: x.classe, obs: "posição inicial (importação)" });
  }
  const body = {
    aportes: [...iniciais, ...sel("aportes").map(i => previaB3.aportes[i])],
    proventos: sel("proventos").map(i => previaB3.proventos[i]),
    ativos: $("#aplicar-ajustes")?.checked ? previaB3.ajustes_ativos : [],
  };
  if (!body.aportes.length && !body.proventos.length && !body.ativos.length) return toast("Nenhum item selecionado.", true);
  try {
    const r = await api("/api/importar/b3/confirmar", { method: "POST", body });
    toast(`Importados: ${r.aportes} operação(ões), ${r.proventos} provento(s)${r.ativos ? `, ${r.ativos} ativo(s) atualizados` : ""}.`);
    $("#resultado-importar-b3").innerHTML = "";
    $("#form-importar-b3").reset();
    carregarAportes();
  } catch (e) { toast(e.message, true); }
});

// ---------------- Ativos ----------------
let ativosCache = [];
async function carregarAtivos() {
  try { ativosCache = await api("/api/ativos"); } catch (e) { return toast(e.message, true); }
  const soma = ativosCache.reduce((s, a) => s + a.meta_pct, 0);
  $("#soma-metas").textContent = `soma das metas: ${pct(soma)}`;
  $("#tabela-ativos").innerHTML = `<tr><th>Ticker</th><th>Nome</th><th>Classe</th><th>Meta</th><th>Meta normalizada</th><th>Preço manual</th><th></th></tr>` +
    (ativosCache.length ? ativosCache.map(a => `<tr>
      <td><strong>${esc(a.ticker)}</strong></td><td>${esc(a.nome)}</td><td>${esc(CLASSES[a.classe] || a.classe)}</td>
      <td>${pct(a.meta_pct)}</td>
      <td><div class="barra" title="${pct(soma ? a.meta_pct / soma * 100 : 0)}"><span style="width:${soma ? a.meta_pct / soma * 100 : 0}%"></span></div></td>
      <td>${a.preco_manual == null ? "—" : brl.format(a.preco_manual)}</td>
      <td><span class="requer-edicao"><button class="link editar" data-editar="${esc(a.ticker)}">editar</button><button class="link" data-remover-ativo="${esc(a.ticker)}">excluir</button></span></td>
    </tr>`).join("") : `<tr><td colspan="7">Nenhum ativo cadastrado.</td></tr>`);
}

$("#form-ativo").addEventListener("submit", async ev => {
  ev.preventDefault();
  try { await api("/api/ativos", { method: "POST", body: formDados(ev.target) }); toast("Ativo salvo."); ev.target.reset(); carregarAtivos(); }
  catch (e) { toast(e.message, true); }
});

$("#tabela-ativos").addEventListener("click", async ev => {
  const editar = ev.target.dataset.editar, remover = ev.target.dataset.removerAtivo;
  if (editar) {
    const a = ativosCache.find(x => x.ticker === editar), f = $("#form-ativo");
    for (const k of ["ticker", "nome", "classe", "meta_pct", "preco_manual"]) f[k].value = a[k] ?? "";
    f.scrollIntoView({ behavior: "smooth" });
  } else if (remover && confirm(`Excluir ${remover}?`)) {
    try { await api(`/api/ativos/${encodeURIComponent(remover)}`, { method: "DELETE" }); toast("Ativo excluído."); carregarAtivos(); }
    catch (e) { toast(e.message, true); }
  }
});

// ---------------- Sugestão de aporte ----------------
$("#form-sugestao").addEventListener("submit", async ev => {
  ev.preventDefault();
  const alvo = $("#resultado-sugestao");
  try {
    const s = await api("/api/sugestao", { method: "POST", body: { valor: ev.target.valor.value } });
    alvo.innerHTML = `<div class="cards" style="margin-top:16px">
        <div class="card"><div class="rotulo">Valor do aporte</div><div class="valor">${brl.format(s.valor_aporte)}</div></div>
        <div class="card"><div class="rotulo">Utilizado</div><div class="valor">${brl.format(s.valor_utilizado)}</div></div>
        <div class="card"><div class="rotulo">Sobra</div><div class="valor">${brl.format(s.sobra)}</div></div>
      </div>
      <div class="rolagem"><table><tr><th>Ativo</th><th>Comprar</th><th>Preço</th><th>Valor</th><th>Peso atual</th><th>Peso após</th><th>Meta</th></tr>
      ${s.sugestoes.length ? s.sugestoes.map(x => `<tr><td><strong>${esc(x.ticker)}</strong></td><td>${num.format(x.quantidade)}</td>
        <td>${brl.format(x.preco)}</td><td>${brl.format(x.valor)}</td><td>${pct(x.peso_atual_pct)}</td>
        <td>${pct(x.peso_apos_pct)}</td><td>${pct(x.meta_pct)}</td></tr>`).join("")
        : `<tr><td colspan="7">O valor não é suficiente para comprar nenhuma unidade.</td></tr>`}</table></div>`;
  } catch (e) { alvo.innerHTML = ""; toast(e.message, true); }
});

// ---------------- Análise de mercado ----------------
$("#form-mercado").addEventListener("submit", async ev => {
  ev.preventDefault();
  const d = formDados(ev.target);
  const q = new URLSearchParams({ dias: d.dias, rf: d.rf || 10, atualizar: d.atualizar ? "1" : "0" });
  let r;
  try { r = await api(`/api/mercado/${encodeURIComponent(d.ticker.trim())}?${q}`); }
  catch (e) { $("#resultado-mercado").classList.add("oculto"); return toast(e.message, true); }
  $("#resultado-mercado").classList.remove("oculto");
  const e = r.estatisticas;
  $("#titulo-preco").innerHTML = `${esc(r.ticker)} — preço, médias móveis e bandas de Bollinger <span class="selo">fonte: ${esc(r.fonte)}</span>`;
  $("#cards-mercado").innerHTML = [
    ["Último preço", brl.format(e.preco)],
    ["1 mês", pctFrac(e.retorno_1m), e.retorno_1m],
    ["3 meses", pctFrac(e.retorno_3m), e.retorno_3m],
    ["12 meses", pctFrac(e.retorno_12m), e.retorno_12m],
    ["Volatilidade anual", pctFrac(e.volatilidade)],
    ["Drawdown máximo", pctFrac(e.max_drawdown), e.max_drawdown],
    ["Índice de Sharpe", e.sharpe == null ? "—" : e.sharpe.toFixed(2).replace(".", ","), e.sharpe],
  ].map(([rot, v, s]) => `<div class="card"><div class="rotulo">${rot}</div><div class="valor ${s == null ? "" : classeSinal(s)}">${v}</div></div>`).join("");

  const linha = (label, data, cor, extra = {}) => ({ type: "line", label, data, borderColor: cor, backgroundColor: cor, pointRadius: 0, borderWidth: 1.5, spanGaps: true, ...extra });
  const opcoesTempo = { interaction: { mode: "index", intersect: false }, scales: { x: { ticks: { maxTicksLimit: 10 } } } };
  grafico("graf-preco", {
    data: { labels: r.datas, datasets: [
      linha("Fechamento", r.fechamento, PALETA[0], { borderWidth: 2 }),
      linha("MM20", r.mm20, PALETA[6]),
      linha("MM50", r.mm50, PALETA[1]),
      linha("MM200", r.mm200, PALETA[3]),
      linha("Bollinger sup.", r.bollinger_sup, "rgba(127,127,127,.5)", { borderDash: [4, 4], borderWidth: 1 }),
      linha("Bollinger inf.", r.bollinger_inf, "rgba(127,127,127,.5)", { borderDash: [4, 4], borderWidth: 1 }),
    ] },
    options: { ...opcoesTempo, scales: { ...opcoesTempo.scales, y: { ticks: { callback: v => brl.format(v) } } } },
  });
  grafico("graf-rsi", {
    data: { labels: r.datas, datasets: [
      linha("RSI", r.rsi, PALETA[4]),
      linha("70", r.datas.map(() => 70), "rgba(200,49,47,.5)", { borderDash: [4, 4], borderWidth: 1 }),
      linha("30", r.datas.map(() => 30), "rgba(19,138,75,.5)", { borderDash: [4, 4], borderWidth: 1 }),
    ] },
    options: { ...opcoesTempo, plugins: { legend: { display: false } }, scales: { ...opcoesTempo.scales, y: { min: 0, max: 100 } } },
  });
  grafico("graf-macd", {
    data: { labels: r.datas, datasets: [
      { type: "bar", label: "Histograma", data: r.macd_hist, backgroundColor: r.macd_hist.map(v => v >= 0 ? "rgba(19,138,75,.6)" : "rgba(200,49,47,.6)") },
      linha("MACD", r.macd, PALETA[0]),
      linha("Sinal", r.macd_sinal, PALETA[1]),
    ] },
    options: opcoesTempo,
  });
  carregarFundamentos(r.ticker, d.atualizar);
  $("#lista-sinais").innerHTML = r.sinais.map(s => `<li class="${s.tipo}">${esc(s.texto)}</li>`).join("") || "<li>Histórico insuficiente para gerar leituras.</li>";
});

async function carregarFontes() {
  try {
    const r = await api("/api/fontes");
    $("#tabela-fontes").innerHTML = `<tr><th>#</th><th>Fonte</th><th>Status</th><th>Descrição</th></tr>` +
      (r.demo ? `<tr><td colspan="4">Modo demonstração ativo: todas as cotações são simuladas.</td></tr>` : "") +
      r.fontes.map((f, i) => `<tr><td>${i + 1}</td><td><a href="${esc(f.site || "#")}" target="_blank" rel="noopener">${esc(f.nome)}</a></td>
        <td class="${f.configurada ? "pos" : "neg"}">${f.configurada ? "ativa" : "sem token"}</td><td>${esc(f.descricao || "")}</td></tr>`).join("");
  } catch (e) { toast(e.message, true); }
}
carregarFontes();

// ---------------- Fundamentos ----------------
const compacto = new Intl.NumberFormat("pt-BR", { notation: "compact", maximumFractionDigits: 1 });
const dec = v => v == null ? "—" : v.toFixed(2).replace(".", ",");
const FORMATO_FUND = {
  pl: dec, pvp: dec, ev_ebitda: dec, liquidez_corrente: dec, divida_pl: dec,
  lpa: v => v == null ? "—" : brl.format(v), vpa: v => v == null ? "—" : brl.format(v),
  roe: pctFrac, margem_liquida: pctFrac,
  valor_mercado: v => v == null ? "—" : "R$ " + compacto.format(v),
};

async function carregarFundamentos(ticker, atualizar) {
  let f;
  try { f = await api(`/api/fundamentos/${encodeURIComponent(ticker)}?atualizar=${atualizar ? 1 : 0}`); }
  catch (e) { $("#sem-fundamentos").textContent = e.message; return; }
  const ind = f.indicadores || {};
  const cards = [["Dividend yield (12m)", pctFrac(f.dividend_yield)]];
  if (f.indicadores) for (const [k, rot] of f.campos) cards.push([rot, FORMATO_FUND[k](ind[k])]);
  $("#cards-fundamentos").innerHTML = cards.map(([r, v]) => `<div class="card"><div class="rotulo">${esc(r)}</div><div class="valor">${v}</div></div>`).join("");
  const fontes = [f.fonte_indicadores && `indicadores: ${f.fonte_indicadores}`, f.fonte_proventos && `proventos: ${f.fonte_proventos}`].filter(Boolean);
  $("#fonte-fundamentos").textContent = fontes.length ? fontes.join(" · ") : "sem dados";
  $("#sem-fundamentos").textContent = [f.erro_indicadores, f.erro_proventos].filter(Boolean).join(" ");
  grafico("graf-proventos-ano", {
    type: "bar",
    data: { labels: f.proventos_por_ano.map(x => x.ano), datasets: [{ label: "Proventos por ação/cota (por ano da data com)", data: f.proventos_por_ano.map(x => x.valor), backgroundColor: PALETA[2] }] },
    options: { aspectRatio: 4, scales: { y: { ticks: { callback: v => brl.format(v) } } }, plugins: { tooltip: { callbacks: { label: x => brl.format(x.raw) } } } },
  });
}

// ---------------- Proventos ----------------
const nomeTipo = t => TIPOS_PROVENTO[t] || t;
const COR_TIPO = { dividendo: PALETA[0], jcp: PALETA[1], rendimento: PALETA[2], amortizacao: PALETA[4], outro: PALETA[8] };

async function carregarProventos() {
  let r;
  try { r = await api("/api/proventos"); } catch (e) { return toast(e.message, true); }
  const s = r.resumo;
  $("#cards-proventos").innerHTML = [
    ["Total recebido", brl.format(s.total)],
    ["Últimos 12 meses", brl.format(s.ult_12m)],
    ["Média mensal (12m)", brl.format(s.media_mensal_12m)],
    ["Yield on cost (12m)", pct(s.yoc_pct)],
    ["Dividend yield da carteira", pct(s.dy_pct)],
    ["A receber (lançados)", brl.format(s.a_receber)],
  ].map(([rot, v]) => `<div class="card"><div class="rotulo">${rot}</div><div class="valor">${v}</div></div>`).join("");

  grafico("graf-proventos", {
    type: "bar",
    data: { labels: s.por_mes.map(x => x.mes), datasets: Object.keys(TIPOS_PROVENTO)
      .filter(t => s.por_mes.some(m => m[t] > 0))
      .map(t => ({ label: nomeTipo(t), data: s.por_mes.map(m => m[t]), backgroundColor: COR_TIPO[t], stack: "p" })) },
    options: { scales: { x: { stacked: true }, y: { stacked: true, ticks: { callback: v => brl.format(v) } } },
      plugins: { tooltip: { callbacks: { label: x => `${x.dataset.label}: ${brl.format(x.raw)}` } } } },
  });

  $("#tabela-proventos-ativo").innerHTML = `<tr><th>Ativo</th><th>Total</th><th>12 meses</th><th>Yield on cost</th><th>DY atual</th></tr>` +
    (s.por_ativo.length ? s.por_ativo.map(a => `<tr><td><strong>${esc(a.ticker)}</strong></td><td>${brl.format(a.total)}</td>
      <td>${brl.format(a.ult_12m)}</td><td>${pct(a.yoc_pct)}</td><td>${pct(a.dy_pct)}</td></tr>`).join("")
      : `<tr><td colspan="5">Nenhum provento recebido.</td></tr>`);

  $("#tabela-proventos").innerHTML = `<tr><th>Pagamento</th><th>Ativo</th><th>Tipo</th><th>Data com</th><th>Qtd.</th><th>Valor/cota</th><th>Total</th><th>Obs.</th><th></th></tr>` +
    (r.itens.length ? r.itens.map(p => `<tr><td>${fmtData(p.data_pagamento)}</td><td><strong>${esc(p.ticker)}</strong></td>
      <td>${esc(nomeTipo(p.tipo))}</td><td>${p.data_com ? fmtData(p.data_com) : "—"}</td>
      <td>${p.quantidade == null ? "—" : num.format(p.quantidade)}</td><td>${p.valor_unitario == null ? "—" : brl.format(p.valor_unitario)}</td>
      <td class="pos">${brl.format(p.valor_total)}</td><td>${esc(p.obs)}</td>
      <td><button class="link requer-edicao" data-remover-provento="${p.id}">excluir</button></td></tr>`).join("")
      : `<tr><td colspan="9">Nenhum provento lançado. Use “Buscar proventos da carteira” ou lance manualmente.</td></tr>`);
}

let estimados = [];
$("#btn-estimar").addEventListener("click", async () => {
  const alvo = $("#resultado-estimar");
  alvo.innerHTML = `<p class="dica">Consultando fontes…</p>`;
  let r;
  try { r = await api(`/api/proventos/estimar?atualizar=${$("#estimar-atualizar").checked ? 1 : 0}`); }
  catch (e) { alvo.innerHTML = ""; return toast(e.message, true); }
  const jaLancados = r.itens.filter(i => i.ja_registrado).length;
  estimados = r.itens.filter(i => !i.ja_registrado);
  const falhas = Object.entries(r.falhas).map(([t, m]) => `<li><strong>${esc(t)}</strong>: ${esc(m)}</li>`).join("");
  alvo.innerHTML = (falhas ? `<details class="dica"><summary>Sem dados de proventos para ${Object.keys(r.falhas).length} ativo(s)</summary><ul>${falhas}</ul></details>` : "") +
    (estimados.length ? `<div class="acoes-import requer-edicao">
        <button type="button" id="btn-importar" class="btn">Importar selecionados</button>
        <span class="dica" id="total-selecionado"></span></div>
      <div class="rolagem"><table id="tabela-estimados"><tr><th class="requer-edicao"></th><th>Ativo</th><th>Tipo</th><th>Data com</th><th>Pagamento</th><th>Qtd.</th><th>Valor/cota</th><th>Total</th><th>Status</th><th>Fonte</th></tr>
      ${estimados.map((i, n) => `<tr class="${i.ja_registrado ? "desativado" : ""}">
        <td class="requer-edicao"><input type="checkbox" data-idx="${n}" ${i.ja_registrado ? "disabled" : i.status === "recebido" ? "checked" : ""}></td>
        <td><strong>${esc(i.ticker)}</strong></td><td>${esc(nomeTipo(i.tipo))}</td><td>${fmtData(i.data_com)}</td>
        <td>${fmtData(i.data_pagamento)}${i.pagamento_estimado ? ` <span class="selo">estimada</span>` : ""}</td>
        <td>${num.format(i.quantidade)}</td><td>${brl.format(i.valor_unitario)}</td><td>${brl.format(i.valor_total)}</td>
        <td>${i.ja_registrado ? "já lançado" : i.status === "recebido" ? "recebido" : "a receber"}</td>
        <td>${esc(r.fontes[i.ticker] || "")}</td></tr>`).join("")}</table></div>`
      : `<p class="dica">${jaLancados ? "Todos os proventos encontrados já estão lançados." : "Nenhum provento encontrado no período em que você teve os ativos."}</p>`) +
    (estimados.length && jaLancados ? `<p class="dica">${jaLancados} provento(s) já lançado(s) não exibido(s).</p>` : "");
  atualizarTotalSelecionado();
});

function atualizarTotalSelecionado() {
  const marcados = [...document.querySelectorAll("#tabela-estimados input:checked")].map(c => estimados[c.dataset.idx]);
  const el = $("#total-selecionado");
  if (el) el.textContent = `${marcados.length} selecionado(s): ${brl.format(marcados.reduce((s, i) => s + i.valor_total, 0))}`;
}

$("#resultado-estimar").addEventListener("change", atualizarTotalSelecionado);
$("#resultado-estimar").addEventListener("click", async ev => {
  if (ev.target.id !== "btn-importar") return;
  const itens = [...document.querySelectorAll("#tabela-estimados input:checked")].map(c => estimados[c.dataset.idx]);
  if (!itens.length) return toast("Nenhum provento selecionado.", true);
  try {
    const r = await api("/api/proventos/importar", { method: "POST", body: { itens } });
    toast(`${r.importados} provento(s) importado(s).`);
    $("#resultado-estimar").innerHTML = "";
    carregarProventos();
  } catch (e) { toast(e.message, true); }
});

$("#form-provento").addEventListener("submit", async ev => {
  ev.preventDefault();
  try { await api("/api/proventos", { method: "POST", body: formDados(ev.target) }); toast("Provento salvo."); ev.target.reset(); carregarProventos(); }
  catch (e) { toast(e.message, true); }
});

$("#tabela-proventos").addEventListener("click", async ev => {
  const id = ev.target.dataset.removerProvento;
  if (!id || !confirm("Excluir este provento?")) return;
  try { await api(`/api/proventos/${id}`, { method: "DELETE" }); toast("Provento excluído."); carregarProventos(); }
  catch (e) { toast(e.message, true); }
});

// ---------------- Comparar ----------------
$("#btn-comparar-carteira").addEventListener("click", async () => {
  const ativos = await api("/api/ativos").catch(() => []);
  $("#form-comparar").tickers.value = ativos.filter(a => a.classe !== "renda_fixa").map(a => a.ticker).slice(0, 8).join(", ");
});

$("#form-comparar").addEventListener("submit", async ev => {
  ev.preventDefault();
  const d = formDados(ev.target);
  let r;
  try { r = await api(`/api/comparar?${new URLSearchParams({ tickers: d.tickers, dias: d.dias })}`); }
  catch (e) { $("#resultado-comparar").classList.add("oculto"); return toast(e.message, true); }
  $("#resultado-comparar").classList.remove("oculto");
  if (Object.keys(r.falhas).length) toast("Sem dados para: " + Object.keys(r.falhas).join(", "), true);
  grafico("graf-comparar", {
    type: "line",
    data: { labels: r.datas, datasets: r.tickers.map((t, i) => ({ label: t, data: r.base100[t], borderColor: PALETA[i % PALETA.length], backgroundColor: PALETA[i % PALETA.length], pointRadius: 0, borderWidth: 1.8 })) },
    options: { interaction: { mode: "index", intersect: false }, scales: { x: { ticks: { maxTicksLimit: 10 } } } },
  });
  $("#tabela-comparar").innerHTML = `<tr><th>Ativo</th><th>Retorno</th><th>Volatilidade</th><th>Drawdown máx.</th></tr>` +
    r.tickers.map(t => { const s = r.estatisticas[t]; return `<tr><td><strong>${esc(t)}</strong></td>
      <td class="${classeSinal(s.retorno)}">${pctFrac(s.retorno)}</td><td>${pctFrac(s.volatilidade)}</td>
      <td class="neg">${pctFrac(s.max_drawdown)}</td></tr>`; }).join("");
  $("#tabela-correlacao").innerHTML = `<tr><th></th>${r.tickers.map(t => `<th>${esc(t)}</th>`).join("")}</tr>` +
    r.correlacao.map((linha, i) => `<tr><th>${esc(r.tickers[i])}</th>${linha.map(v => {
      const a = v == null ? 0 : Math.abs(v), cor = v >= 0 ? `rgba(36,87,197,${a * 0.6})` : `rgba(200,49,47,${a * 0.6})`;
      return `<td style="background:${cor}">${v == null ? "—" : v.toFixed(2).replace(".", ",")}</td>`; }).join("")}</tr>`).join("");
});

// ---------------- Carteiras e permissões ----------------
const ROTULO_PERM = p => p.gerenciar && p.editar ? "acesso total" : p.editar ? "controle" : "somente leitura";

function aplicarPermissoes() {
  const p = permissao();
  document.body.classList.toggle("somente-leitura", !p.editar);
  document.body.classList.toggle("admin", !!USUARIO.admin);
  $("#aviso-leitura").classList.toggle("oculto", !carteiraAtual || p.editar);
  $("#selo-permissao").textContent = carteiraAtual ? ROTULO_PERM(p) : "";
}

async function carregarCarteiras(preferida) {
  const r = await api("/api/eu");
  carteiras = r.carteiras;
  let salva = null;
  try { salva = Number(localStorage.getItem("carteira")); } catch (e) { /* armazenamento indisponível */ }
  const ids = carteiras.map(c => c.id);
  carteiraAtual = [preferida, carteiraAtual, salva].find(id => ids.includes(id)) ?? ids[0] ?? null;
  $("#sel-carteira").innerHTML = carteiras.length
    ? carteiras.map(c => `<option value="${c.id}">${esc(c.nome)}${c.sou_dono ? "" : ` (${esc(c.dono_nome || "sem dono")})`}</option>`).join("")
    : `<option value="">Nenhuma carteira disponível</option>`;
  if (carteiraAtual) $("#sel-carteira").value = carteiraAtual;
  aplicarPermissoes();
}

function recarregarAbaAtual() {
  $("#resultado-sugestao").innerHTML = "";
  $("#resultado-estimar").innerHTML = "";
  const aba = document.querySelector("nav button.ativo")?.dataset.tab;
  ({ carteira: carregarCarteira, aportes: carregarAportes, ativos: carregarAtivos, proventos: carregarProventos, acessos: carregarAcessos, fluxo: carregarFluxo }[aba] || (() => {}))();
}

$("#sel-carteira").addEventListener("change", ev => {
  carteiraAtual = Number(ev.target.value) || null;
  try { localStorage.setItem("carteira", carteiraAtual); } catch (e) { /* ignora */ }
  aplicarPermissoes();
  recarregarAbaAtual();
});

$("#btn-sair").addEventListener("click", async () => {
  await api("/auth/logout", { method: "POST" }).catch(() => {});
  location.href = "/login";
});

// ---------------- Acessos e conta ----------------
let usuariosCache = [];
let carteiraAcessos = null;

async function carregarAcessos() {
  await carregarCarteiras();
  const gerenciaveis = carteiras.filter(c => c.permissoes.gerenciar);
  if (USUARIO.admin) {
    try { usuariosCache = await api("/api/usuarios"); } catch (e) { toast(e.message, true); }
    $("#sel-dono").innerHTML = usuariosCache.filter(u => u.ativo)
      .map(u => `<option value="${u.id}" ${u.id === USUARIO.id ? "selected" : ""}>${esc(u.nome)}</option>`).join("");
    $("#lista-emails").innerHTML = usuariosCache.map(u => `<option value="${esc(u.email)}">${esc(u.nome)}</option>`).join("");
    renderUsuarios();
  }
  $("#tabela-carteiras").innerHTML = `<tr><th>Carteira</th><th>Dono</th><th>Seu acesso</th><th></th></tr>` +
    carteiras.map(c => `<tr><td><strong>${esc(c.nome)}</strong></td><td>${esc(c.dono_nome || "—")}</td>
      <td>${c.sou_dono ? "dono" : ROTULO_PERM(c.permissoes)}</td>
      <td>${c.permissoes.gerenciar ? `<button class="link acao" data-acessos="${c.id}">acessos</button><button class="link acao" data-renomear="${c.id}">renomear</button>` : ""}
          <button class="link acao" data-abrir="${c.id}">abrir</button>
          ${c.sou_dono || USUARIO.admin ? `<button class="link" data-excluir-carteira="${c.id}">excluir</button>` : ""}</td></tr>`).join("");
  if (carteiraAcessos && !gerenciaveis.some(c => c.id === carteiraAcessos)) carteiraAcessos = null;
  carteiraAcessos = carteiraAcessos || (permissao().gerenciar ? carteiraAtual : gerenciaveis[0]?.id);
  if (carteiraAcessos) mostrarAcessos(carteiraAcessos); else $("#painel-acessos").classList.add("oculto");
}

async function mostrarAcessos(cid) {
  carteiraAcessos = cid;
  let r;
  try { r = await api(`/api/carteiras/${cid}/acessos`); } catch (e) { return toast(e.message, true); }
  $("#painel-acessos").classList.remove("oculto");
  $("#nome-carteira-acessos").textContent = r.carteira.nome;
  $("#dono-carteira-acessos").textContent = r.dono ? `Dono: ${r.dono.nome} (${r.dono.email}) — acesso total.` : "Carteira sem dono definido.";
  const marca = (a, k) => `<input type="checkbox" class="check-acesso" data-perm="${k}" data-email="${esc(a.email)}" ${a[k] ? "checked" : ""} ${k === "ver" && (a.editar || a.gerenciar) ? "disabled" : ""}>`;
  $("#tabela-acessos").innerHTML = `<tr><th>Usuário</th><th>E-mail</th><th>Visualizar</th><th>Controlar</th><th>Gerenciar acessos</th><th></th></tr>` +
    (r.acessos.length ? r.acessos.map(a => `<tr><td>${esc(a.nome)}</td><td>${esc(a.email)}</td>
      <td>${marca(a, "ver")}</td><td>${marca(a, "editar")}</td><td>${marca(a, "gerenciar")}</td>
      <td><button class="link" data-revogar="${a.usuario_id}">revogar</button></td></tr>`).join("")
      : `<tr><td colspan="6">Ninguém além do dono e dos administradores tem acesso a esta carteira.</td></tr>`);
}

$("#tabela-carteiras").addEventListener("click", async ev => {
  const d = ev.target.dataset;
  if (d.acessos) mostrarAcessos(Number(d.acessos));
  if (d.abrir) {
    $("#sel-carteira").value = d.abrir;
    $("#sel-carteira").dispatchEvent(new Event("change"));
    document.querySelector('nav button[data-tab="carteira"]').click();
  }
  if (d.renomear) {
    const c = carteiras.find(x => x.id === Number(d.renomear));
    const nome = prompt("Novo nome da carteira:", c.nome);
    if (!nome) return;
    try { await api(`/api/carteiras/${c.id}`, { method: "PATCH", body: { nome } }); toast("Carteira renomeada."); carregarAcessos(); }
    catch (e) { toast(e.message, true); }
  }
  if (d.excluirCarteira) {
    const c = carteiras.find(x => x.id === Number(d.excluirCarteira));
    if (!confirm(`Excluir a carteira "${c.nome}"? Só é possível se ela não tiver aportes nem proventos.`)) return;
    try { await api(`/api/carteiras/${c.id}`, { method: "DELETE" }); toast("Carteira excluída."); carregarAcessos(); }
    catch (e) { toast(e.message, true); }
  }
});

$("#tabela-acessos").addEventListener("change", async ev => {
  const email = ev.target.dataset.email;
  if (!email) return;
  const linha = ev.target.closest("tr");
  const valor = k => linha.querySelector(`[data-perm="${k}"]`).checked;
  const body = { email, ver: valor("ver"), editar: valor("editar"), gerenciar: valor("gerenciar") };
  try { await api(`/api/carteiras/${carteiraAcessos}/acessos`, { method: "PUT", body }); toast("Permissões atualizadas."); }
  catch (e) { toast(e.message, true); }
  mostrarAcessos(carteiraAcessos);
});

$("#tabela-acessos").addEventListener("click", async ev => {
  const uid = ev.target.dataset.revogar;
  if (!uid || !confirm("Revogar o acesso deste usuário à carteira?")) return;
  try { await api(`/api/carteiras/${carteiraAcessos}/acessos/${uid}`, { method: "DELETE" }); toast("Acesso revogado."); mostrarAcessos(carteiraAcessos); }
  catch (e) { toast(e.message, true); }
});

$("#form-acesso").addEventListener("submit", async ev => {
  ev.preventDefault();
  const d = formDados(ev.target);
  try {
    await api(`/api/carteiras/${carteiraAcessos}/acessos`, { method: "PUT", body: { email: d.email, ver: true, editar: d.editar, gerenciar: d.gerenciar } });
    toast("Acesso concedido."); ev.target.reset(); mostrarAcessos(carteiraAcessos);
  } catch (e) { toast(e.message, true); }
});

$("#form-carteira").addEventListener("submit", async ev => {
  ev.preventDefault();
  const d = formDados(ev.target);
  try {
    const r = await api("/api/carteiras", { method: "POST", body: { nome: d.nome, dono_id: USUARIO.admin ? Number(d.dono_id) : undefined } });
    toast("Carteira criada."); ev.target.reset(); carteiraAcessos = r.id; carregarAcessos();
  } catch (e) { toast(e.message, true); }
});

function renderUsuarios() {
  $("#tabela-usuarios").innerHTML = `<tr><th>Nome</th><th>E-mail</th><th>Administrador</th><th>Ativo</th><th></th></tr>` +
    usuariosCache.map(u => `<tr><td>${esc(u.nome)}</td><td>${esc(u.email)}</td>
      <td><input type="checkbox" data-usuario="${u.id}" data-campo="admin" ${u.admin ? "checked" : ""}></td>
      <td><input type="checkbox" data-usuario="${u.id}" data-campo="ativo" ${u.ativo ? "checked" : ""} ${u.id === USUARIO.id ? "disabled" : ""}></td>
      <td><button class="link acao" data-redefinir="${u.id}">redefinir senha</button></td></tr>`).join("");
}

$("#tabela-usuarios").addEventListener("change", async ev => {
  const { usuario, campo } = ev.target.dataset;
  if (!usuario) return;
  try { await api(`/api/usuarios/${usuario}`, { method: "PATCH", body: { [campo]: ev.target.checked } }); toast("Usuário atualizado."); }
  catch (e) { toast(e.message, true); }
  carregarAcessos();
});

$("#tabela-usuarios").addEventListener("click", async ev => {
  const uid = ev.target.dataset.redefinir;
  if (!uid) return;
  const senha = prompt("Nova senha provisória (mínimo 8 caracteres):");
  if (!senha) return;
  try { await api(`/api/usuarios/${uid}`, { method: "PATCH", body: { senha } }); toast("Senha redefinida."); }
  catch (e) { toast(e.message, true); }
});

$("#form-usuario").addEventListener("submit", async ev => {
  ev.preventDefault();
  const d = formDados(ev.target);
  try {
    await api("/api/usuarios", { method: "POST", body: { ...d, nome_carteira: `Carteira ${d.nome.trim()}` } });
    toast(d.criar_carteira ? `Usuário e “Carteira ${d.nome.trim()}” criados.` : "Usuário criado.");
    ev.target.reset(); carregarAcessos();
  } catch (e) { toast(e.message, true); }
});

$("#form-senha").addEventListener("submit", async ev => {
  ev.preventDefault();
  try { await api("/api/eu/senha", { method: "POST", body: formDados(ev.target) }); toast("Senha alterada."); ev.target.reset(); }
  catch (e) { toast(e.message, true); }
});

// ---------------- Layout: menu lateral, saudação e avatar ----------------
$("#btn-menu").addEventListener("click", () => document.body.classList.add("menu-aberto"));
$("#sombra-menu").addEventListener("click", () => document.body.classList.remove("menu-aberto"));
document.addEventListener("keydown", ev => { if (ev.key === "Escape") document.body.classList.remove("menu-aberto"); });
(() => {
  const partes = USUARIO.nome.trim().split(/\s+/);
  $("#avatar").textContent = (partes[0][0] + (partes.length > 1 ? partes[partes.length - 1][0] : "")).toUpperCase();
  const h = new Date().getHours();
  $("#saudacao").textContent = `${h < 12 ? "Bom dia" : h < 18 ? "Boa tarde" : "Boa noite"}, ${partes[0]}`;
  const data = new Date().toLocaleDateString("pt-BR", { weekday: "long", day: "numeric", month: "long" });
  $("#data-hoje").textContent = data.charAt(0).toUpperCase() + data.slice(1);
})();

// ---------------- Início ----------------
$("#form-aporte").data.value = new Date().toISOString().slice(0, 10);
carregarCarteiras().then(() => {
  if (!carteiraAtual) {
    toast("Você ainda não tem acesso a nenhuma carteira. Peça ao administrador.", true);
    document.querySelector('nav button[data-tab="acessos"]').click();
    return;
  }
  carregarCarteira();
  carregarAportes();
}).catch(e => toast(e.message, true));
