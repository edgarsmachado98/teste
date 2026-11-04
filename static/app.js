"use strict";

const brl = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
const num = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 8 });
const pct = (v, casas = 2) => v == null ? "—" : `${(v).toFixed(casas).replace(".", ",")}%`;
const pctFrac = v => v == null ? "—" : pct(v * 100);
const classeSinal = v => v > 0 ? "pos" : v < 0 ? "neg" : "";
const fmtData = s => s.split("-").reverse().join("/");
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const $ = sel => document.querySelector(sel);
const PALETA = ["#2457c5", "#e07b39", "#3a9d5d", "#c8312f", "#8457c5", "#1aa3b8", "#c59b24", "#d0558f", "#5f6b7a", "#7fb03a"];
const graficos = {};

function toast(msg, erro = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "mostrar" + (erro ? " erro" : "");
  clearTimeout(t._timer);
  t._timer = setTimeout(() => (t.className = ""), 3500);
}

async function api(url, opts = {}) {
  const r = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
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
  document.querySelectorAll(".tab").forEach(t => t.classList.toggle("visivel", t.id === "tab-" + b.dataset.tab));
  ({ carteira: carregarCarteira, aportes: carregarAportes, ativos: carregarAtivos, proventos: carregarProventos }[b.dataset.tab] || (() => {}))();
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
        <td><button class="link" data-remover-aporte="${a.id}">excluir</button></td></tr>`).join("")
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
      <td><button class="link editar" data-editar="${esc(a.ticker)}">editar</button><button class="link" data-remover-ativo="${esc(a.ticker)}">excluir</button></td>
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
      <td><button class="link" data-remover-provento="${p.id}">excluir</button></td></tr>`).join("")
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
    (estimados.length ? `<div class="acoes-import">
        <button type="button" id="btn-importar" class="btn">Importar selecionados</button>
        <span class="dica" id="total-selecionado"></span></div>
      <div class="rolagem"><table id="tabela-estimados"><tr><th></th><th>Ativo</th><th>Tipo</th><th>Data com</th><th>Pagamento</th><th>Qtd.</th><th>Valor/cota</th><th>Total</th><th>Status</th><th>Fonte</th></tr>
      ${estimados.map((i, n) => `<tr class="${i.ja_registrado ? "desativado" : ""}">
        <td><input type="checkbox" data-idx="${n}" ${i.ja_registrado ? "disabled" : i.status === "recebido" ? "checked" : ""}></td>
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

// ---------------- Início ----------------
$("#form-aporte").data.value = new Date().toISOString().slice(0, 10);
carregarCarteira();
carregarAportes();
