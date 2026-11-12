// Módulo adicional: Planejamento financeiro (carregado só quando o módulo está ativo na licença).
// Usa as funções do app base (api, brl, esc, grafico, toast...).
(function () {
  const hojeLocal = () => new Date().toLocaleDateString("sv-SE");
  let mesPlan = hojeLocal().slice(0, 7);
  let categoriasPlan = [], formasPlan = {}, dadosLanc = null, tipoForm = "despesa", cartoesPlan = [], previaFatura = null;
  let pessoasPlan = [];  // titulares possíveis (carteiras visíveis; "editar" = pode lançar para ela)

  const somarMes = (m, n) => {
    const d = new Date(+m.slice(0, 4), +m.slice(5, 7) - 1 + n, 1);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
  };
  const nomeMes = m => {
    const t = new Date(+m.slice(0, 4), +m.slice(5, 7) - 1, 1).toLocaleDateString("pt-BR", { month: "long", year: "numeric" });
    return t.charAt(0).toUpperCase() + t.slice(1);
  };
  const catPorId = id => categoriasPlan.find(c => c.id === id);
  const nomeCat = id => { const c = catPorId(id); return c ? c.nome : "Sem categoria"; };

  function atualizarSeletoresMes() {
    document.querySelectorAll("[data-mes-nav] .rotulo-mes").forEach(e => (e.textContent = nomeMes(mesPlan)));
  }
  document.addEventListener("click", ev => {
    const b = ev.target.closest("[data-mes-delta]");
    if (b) {
      mesPlan = somarMes(mesPlan, +b.dataset.mesDelta);
      recarregar();
    }
    const ir = ev.target.closest("[data-ir-aba]");
    if (ir) document.querySelector(`nav button[data-tab="${ir.dataset.irAba}"]`).click();
  });

  function recarregar() {
    const aba = document.querySelector("nav button.ativo")?.dataset.tab;
    ({ "plan-resumo": carregarResumo, "plan-lancamentos": carregarLancamentos, "plan-orcamento": carregarOrcamento,
       "plan-familia": carregarFamilia }[aba] || (() => {}))();
  }

  async function garantirCategorias() {
    if (categoriasPlan.length) return;
    const r = await api("/api/plan/categorias");
    categoriasPlan = r.categorias;
    formasPlan = r.formas;
    const ordem = ["pix", "debito", "credito", "dinheiro", "boleto", "debito_automatico", "transferencia"];
    $("#pilulas-forma").innerHTML = ordem.filter(v => formasPlan[v]).map(v =>
      `<label><input type="radio" name="forma" value="${v}"><span>${esc(formasPlan[v])}</span></label>`).join("");
    preencherCategorias();
  }

  function preencherCategorias(selecionada) {
    const grupos = {};
    categoriasPlan.filter(c => c.tipo === tipoForm).forEach(c => (grupos[c.grupo] ||= []).push(c));
    $("#form-plan").categoria_id.innerHTML = `<option value="">Selecione a categoria</option>` + Object.entries(grupos).map(([g, cs]) =>
      `<optgroup label="${esc(g)}">${cs.map(c => `<option value="${c.id}" ${c.id === selecionada ? "selected" : ""}>${esc(c.nome)}</option>`).join("")}</optgroup>`).join("");
    $("#plan-grupos").innerHTML = [...new Set(categoriasPlan.map(c => c.grupo))].map(g => `<option value="${esc(g)}">`).join("");
  }

  // ---------------- Resumo do mês ----------------
  async function carregarResumo() {
    atualizarSeletoresMes();
    let r;
    try { r = await api(`/api/plan/resumo?mes=${mesPlan}`); } catch (e) { return toast(e.message, true); }
    $("#plan-boas-vindas").classList.toggle("oculto", !r.vazio);
    const futuro = r.mes > r.mes_atual;
    const variacao = (v, a) => a ? `<small class="var-sub">${v >= a ? "+" : ""}${pct((v / a - 1) * 100, 0)} vs. mês anterior</small>` : "";
    $("#plan-cards").innerHTML = [
      ["Receitas", brl.format(r.receitas), r.descontos > 0.005 ? `<small class="var-sub">Bruto ${brl.format(r.receita_bruta)} · descontos ${brl.format(r.descontos)}</small>` : variacao(r.receitas, r.anterior.receitas)],
      ["Despesas", brl.format(r.despesas), variacao(r.despesas, r.anterior.despesas)],
      ["Investido", brl.format(r.investido), `<small class="var-sub">${r.taxa_poupanca == null ? "aportes do mês na carteira" : `${pct(r.taxa_poupanca, 1)} da renda`}</small>`],
      [futuro ? "Sobra prevista" : "Sobra do mês", `<span class="${r.sobra >= 0 ? "pos" : "neg"}">${brl.format(r.sobra)}</span>`,
        `<small class="var-sub">${r.sobra >= 0 ? "disponível para investir ou guardar" : "gastos acima da renda"}</small>`],
    ].map(([rot, val, sub]) => `<div class="card"><div class="rotulo">${rot}</div><div class="valor">${val}</div>${sub}</div>`).join("");

    const grupos = r.despesas_por_grupo;
    // sem despesas: esconde a pizza vazia (fica só a mensagem)
    $("#graf-plan-despesas").closest(".plan-pizza").classList.toggle("oculto", !grupos.length);
    grafico("graf-plan-despesas", {
      type: "doughnut",
      data: { labels: grupos.map(g => g.grupo), datasets: [{ data: grupos.map(g => g.valor), backgroundColor: grupos.map((_, i) => PALETA[i % PALETA.length]), borderWidth: 0 }] },
      options: { cutout: "68%", maintainAspectRatio: false, plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => ` ${c.label}: ${brl.format(c.raw)}` } } } },
    });
    $("#plan-despesas-grupo").innerHTML = grupos.length ? `<ul class="plan-lista">${grupos.map((g, i) => `<li>
        <span class="bolinha" style="background:${PALETA[i % PALETA.length]}"></span>
        <span class="plan-nome">${esc(g.grupo)}<small>${pct(g.pct, 0)}${g.anterior ? ` · mês anterior ${brl.format(g.anterior)}` : ""}</small></span>
        <strong>${brl.format(g.valor)}</strong></li>`).join("")}</ul>`
      : `<p class="dica">Nenhuma despesa neste mês.</p>`;

    $("#plan-receitas").innerHTML = r.receitas_por_categoria.length ? `<ul class="plan-lista">${r.receitas_por_categoria.map(x => `<li>
        <span class="plan-nome">${esc(x.categoria)}<small>${esc(x.grupo)}</small></span><strong class="pos">${brl.format(x.valor)}</strong></li>`).join("")}</ul>`
      : `<p class="dica">Nenhuma receita neste mês.</p>`;

    const contas = [...r.a_receber.map(x => ({ ...x, receita: true })), ...r.a_pagar];
    $("#plan-a-pagar").innerHTML = contas.length ? `<ul class="plan-lista plan-contas">${contas.map(x => `<li>
        ${x.projetado || !x.id ? `<span class="plan-check vazio" title="Previsto"></span>`
          : `<button type="button" class="plan-check requer-edicao" data-pagar="${x.id}" title="Marcar como ${x.receita ? "recebido" : "pago"}" aria-label="Marcar como ${x.receita ? "recebido" : "pago"}"></button>`}
        <span class="plan-nome">${esc(x.descricao)}<small>${x.receita ? "a receber" : "a pagar"} em ${fmtData(x.data)}${x.projetado ? " · previsto" : ""}</small></span>
        <strong class="${x.receita ? "pos" : ""}">${brl.format(x.valor)}</strong></li>`).join("")}</ul>`
      : `<p class="dica">${futuro ? "Nenhuma conta prevista." : "Tudo pago e recebido neste mês."}</p>`;

    $("#plan-cartoes").innerHTML = r.cartoes.length ? `<h3 style="margin-top:20px">Cartões no mês</h3><ul class="plan-lista">${r.cartoes.map(c => `<li>
        <span class="plan-nome">${esc(c.nome)}<small>${c.compras} compra(s)${c.dia_vencimento ? ` · vence dia ${c.dia_vencimento}` : ""}</small></span>
        <strong>${brl.format(c.total)}</strong></li>`).join("")}</ul>` : "";

    const ind = [
      ["Taxa de poupança", r.taxa_poupanca == null ? "—" : pct(r.taxa_poupanca, 1), "Quanto da renda foi investido. Uma boa referência é 20% ou mais."],
      ["Custo de vida médio", r.custo_de_vida == null ? "—" : brl.format(r.custo_de_vida), "Média das despesas dos últimos 12 meses fechados. Base da reserva de emergência."],
      ["Reserva de emergência ideal", r.custo_de_vida == null ? "—" : `${brl.format(r.custo_de_vida * 6)} a ${brl.format(r.custo_de_vida * 12)}`, "De 6 a 12 meses do custo de vida."],
      ["Proventos pagam", r.cobertura_proventos == null ? "—" : `${pct(r.cobertura_proventos, 1)} das despesas`, "Quanto da sua vida a renda dos investimentos já sustenta."],
    ];
    $("#plan-indicadores").innerHTML = ind.map(([n, v, d]) => `<div><span>${n}</span><strong>${v}</strong><small>${d}</small></div>`).join("");

    const serieVazia = r.serie.every(x => !x.receitas && !x.despesas && !x.investido);
    $("#graf-plan-serie").classList.toggle("oculto", serieVazia);
    $("#plan-serie-vazia").classList.toggle("oculto", !serieVazia);
    grafico("graf-plan-serie", {
      type: "bar",
      data: {
        labels: r.serie.map(s => nomeMes(s.mes).slice(0, 3) + "/" + s.mes.slice(2, 4)),
        datasets: [
          { label: "Receitas", data: r.serie.map(s => s.receitas), backgroundColor: PALETA[0] },
          { label: "Despesas", data: r.serie.map(s => s.despesas), backgroundColor: PALETA[3] },
          { label: "Investido", data: r.serie.map(s => s.investido), backgroundColor: PALETA[2] },
        ],
      },
      options: { plugins: { tooltip: { callbacks: { label: c => ` ${c.dataset.label}: ${brl.format(c.raw)}` } } },
        scales: { y: { ticks: { callback: v => brl.format(v).replace(",00", "") } } } },
    });
  }

  document.addEventListener("click", async ev => {
    const b = ev.target.closest("[data-pagar]");
    if (!b) return;
    try {
      await api(`/api/plan/lancamentos/${b.dataset.pagar}`, { method: "PUT", body: { pago: true } });
      recarregar();
    } catch (e) { toast(e.message, true); }
  });

  // ---------------- Receitas e despesas ----------------
  const FREQUENTES_PADRAO = {
    despesa: ["Mercado", "Restaurante", "Delivery", "Combustível", "Farmácia", "Streaming / assinaturas"],
    receita: ["Salário", "Freelance / autônomo", "13º salário", "Aluguel recebido", "Estornos e reembolsos"],
  };

  function categoriasFrequentes() {
    // as mais usadas nos lançamentos do mês; completa com sugestões comuns
    const cont = {};
    (dadosLanc?.lancamentos || []).filter(l => l.tipo === tipoForm && l.categoria_id)
      .forEach(l => (cont[l.categoria_id] = (cont[l.categoria_id] || 0) + 1));
    const usadas = Object.entries(cont).sort((a, b) => b[1] - a[1]).map(([id]) => +id);
    const padrao = FREQUENTES_PADRAO[tipoForm].map(n => categoriasPlan.find(c => c.tipo === tipoForm && c.nome === n)?.id).filter(Boolean);
    return [...new Set([...usadas, ...padrao])].slice(0, 6).map(catPorId).filter(Boolean);
  }

  function renderPilulasCategoria() {
    const sel = +$("#form-plan").categoria_id.value || null, caixa = $("#cat-frequentes");
    const cats = categoriasFrequentes(), ids = cats.map(c => c.id).join(",");
    // mesma lista: só atualiza a marcação (recriar os botões no meio de um clique faria o clique se perder)
    if (caixa.dataset.ids !== ids) {
      caixa.dataset.ids = ids;
      caixa.innerHTML = cats.map(c => `<button type="button" data-cat="${c.id}">${esc(c.nome)}</button>`).join("");
    }
    caixa.querySelectorAll("[data-cat]").forEach(b => b.classList.toggle("ativo", +b.dataset.cat === sel));
  }

  function renderTitulares(selecionado, familia) {
    const ed = pessoasPlan.filter(p => p.editar);
    const receita = tipoForm === "receita";
    const padrao = selecionado || (ed.find(p => p.id === carteiraAtual) || ed.find(p => p.minha) || ed[0])?.id;
    let html = ed.map(p => `<label><input type="radio" name="titular" value="${p.id}" ${p.id === padrao && !(receita && familia) ? "checked" : ""}>
      <span>${esc(p.nome)}</span></label>`).join("");
    if (receita && pessoasPlan.length > 1) html += `<label><input type="radio" name="titular" value="grupo" ${familia ? "checked" : ""}>
      <span>Grupo familiar</span></label>`;
    $("#pilulas-titular").innerHTML = html;
    // com uma pessoa só e sem família, não há o que escolher
    $("#bloco-titular").classList.toggle("so-uma-pessoa", ed.length < 2 && pessoasPlan.length < 2);
  }

  function valorRadio(nome) {
    return $("#form-plan").querySelector(`input[name="${nome}"]:checked`)?.value || "";
  }

  function ajustarForm() {
    const f = $("#form-plan"), receita = tipoForm === "receita", editando = !!f.id.value;
    document.querySelectorAll("[data-plan-tipo]").forEach(b => b.classList.toggle("ativo", b.dataset.planTipo === tipoForm));
    $("#painel-plan-form").classList.toggle("eh-receita", receita);
    document.querySelectorAll("#form-plan .so-receita").forEach(e => e.classList.toggle("oculto", !receita));
    document.querySelectorAll("#form-plan .so-despesa").forEach(e => e.classList.toggle("oculto", receita));
    document.querySelectorAll("#form-plan .so-novo").forEach(e => e.classList.toggle("oculto", editando));
    if (receita && valorRadio("repetir") === "parcelado") f.querySelector('input[name="repetir"][value="nao"]').checked = true;
    const forma = valorRadio("forma"), rep = editando ? "nao" : valorRadio("repetir");
    f.querySelector(".campo-cartao").classList.toggle("oculto", receita || forma !== "credito" || !cartoesPlan.length);
    f.cartao_id.required = !receita && forma === "credito" && cartoesPlan.length > 0;
    $("#aviso-credito").classList.toggle("oculto", receita || forma !== "credito");
    $("#aviso-credito").innerHTML = !cartoesPlan.length
      ? `Cadastre o cartão em “Importar fatura do cartão” para que esta compra seja conferida com a fatura e não fique em duplicidade.`
      : `A compra fica como <strong>aguardando fatura</strong>. Ao importar a fatura, o sistema a reconhece e não lança de novo.`;
    f.querySelector(".campo-parcelas").classList.toggle("oculto", rep !== "parcelado");
    f.querySelector(".campo-fim").classList.toggle("oculto", rep !== "mensal");
    f.querySelector(".campo-bruto").classList.toggle("oculto", !receita || (!f.valor_bruto.value && !f.dataset.bruto));
    $("#btn-mostrar-bruto").classList.toggle("oculto", !receita || !!f.valor_bruto.value || !!f.dataset.bruto);
    f.querySelector("[data-rotulo-valor]").textContent = rep === "parcelado" ? "Valor total da compra" : receita ? "Valor líquido recebido" : "Valor";
    f.querySelector("[data-rotulo-data]").textContent = rep === "parcelado" ? "Data da 1ª parcela" : receita ? "Data do recebimento" : "Data";
    f.querySelector("[data-rotulo-pago]").textContent = receita ? "Recebido" : "Pago";
    f.querySelector("[data-rotulo-titular]").textContent = receita ? "Titular da receita" : "Pago por";
    f.descricao.placeholder = receita ? "Ex.: Salário — Empresa X" : "Ex.: Supermercado";
    $("#btn-plan-salvar").textContent = editando ? "Salvar alterações" : receita ? "Salvar receita" : "Salvar despesa";
    renderPilulasCategoria();
    atualizarResumoForm();
  }

  function atualizarResumoForm() {
    const f = $("#form-plan"), receita = tipoForm === "receita";
    const valor = +f.valor.value || 0, cat = catPorId(+f.categoria_id.value);
    const tit = valorRadio("titular"), pessoa = pessoasPlan.find(p => String(p.id) === tit);
    const rep = f.id.value ? "nao" : valorRadio("repetir"), n = +f.parcelas.value || 2;
    const data = f.data.value ? fmtData(f.data.value) : "";
    if (!valor) { $("#lanc-resumo").textContent = ""; return; }
    let txt = receita
      ? `Receita de ${brl.format(valor)}${cat ? ` (${cat.nome})` : ""} ${tit === "grupo" ? "do grupo familiar" : pessoa ? `de ${pessoa.nome}` : ""}`
      : `Despesa de ${brl.format(valor)}${cat ? ` em ${cat.nome}` : ""}${pessoa ? `, paga por ${pessoa.nome}` : ""}${valorRadio("conta") === "familia" ? ", compartilhada na família" : ", individual"}`;
    txt += rep === "mensal" ? `, mensal a partir de ${data}` : rep === "parcelado" ? `, em ${n}x de ${brl.format(valor / n)} a partir de ${data}` : data ? `, em ${data}` : "";
    $("#lanc-resumo").textContent = txt + ".";
  }

  document.querySelectorAll("[data-plan-tipo]").forEach(b => b.addEventListener("click", () => {
    if ($("#form-plan").id.value) return;  // na edição o tipo não muda
    tipoForm = b.dataset.planTipo;
    preencherCategorias();
    renderTitulares();
    ajustarForm();
  }));
  $("#form-plan").addEventListener("change", ev => {
    if (ev.target.name === "categoria_id") renderPilulasCategoria();
    ajustarForm();
  });
  $("#form-plan").addEventListener("input", atualizarResumoForm);
  $("#form-plan").addEventListener("click", ev => {
    const c = ev.target.closest("[data-cat]"), dd = ev.target.closest("[data-data]");
    if (c) { $("#form-plan").categoria_id.value = c.dataset.cat; ajustarForm(); }
    if (dd) {
      const d = new Date(); d.setDate(d.getDate() + +dd.dataset.data);
      $("#form-plan").data.value = d.toLocaleDateString("sv-SE");
      atualizarResumoForm();
    }
  });
  $("#btn-mostrar-bruto").addEventListener("click", () => {
    $("#form-plan").dataset.bruto = "1"; ajustarForm(); $("#form-plan").valor_bruto.focus();
  });
  $("#btn-abrir-categoria").addEventListener("click", () => {
    const det = $("#detalhe-categoria"); det.open = true;
    det.querySelector("select[name=tipo]").value = tipoForm;
    det.querySelector("input[name=grupo]").focus();
  });

  function limparForm() {
    const f = $("#form-plan");
    f.reset();
    f.id.value = "";
    delete f.dataset.bruto;
    delete f.dataset.carteiraOriginal;
    f.data.value = mesPlan === hojeLocal().slice(0, 7) ? hojeLocal() : `${mesPlan}-01`;
    $("#plan-form-titulo").textContent = "Novo lançamento";
    $("#btn-plan-cancelar").classList.add("oculto");
    f.querySelector(".campo-proximos").classList.add("oculto");
    preencherCategorias();
    renderTitulares();
    ajustarForm();
  }
  $("#btn-plan-cancelar").addEventListener("click", limparForm);

  $("#form-plan").addEventListener("submit", async ev => {
    ev.preventDefault();
    const f = ev.target, d = formDados(f), id = d.id;
    const tit = valorRadio("titular"), grupo = tit === "grupo";
    const titular = grupo ? (f.dataset.carteiraOriginal || (pessoasPlan.find(p => p.editar && p.id === carteiraAtual) ||
      pessoasPlan.find(p => p.editar && p.minha) || pessoasPlan.find(p => p.editar))?.id) : tit;
    const forma = tipoForm === "despesa" ? valorRadio("forma") : "";
    const body = { tipo: tipoForm, data: d.data, descricao: d.descricao, categoria_id: d.categoria_id, valor: d.valor,
      valor_bruto: tipoForm === "receita" ? d.valor_bruto : "", forma, pago: d.pago,
      repetir: valorRadio("repetir"), parcelas: d.parcelas, fim: d.fim, atualizar_proximos: d.atualizar_proximos,
      cartao_id: forma === "credito" ? d.cartao_id : "", carteira_id: titular || "",
      compartilhado: tipoForm === "receita" ? grupo : valorRadio("conta") === "familia" };
    try {
      if (id) await api(`/api/plan/lancamentos/${id}`, { method: "PUT", body });
      else await api("/api/plan/lancamentos", { method: "POST", body });
      const p = pessoasPlan.find(x => String(x.id) === String(titular));
      const fora = carteiraAtual !== FAMILIA && titular && +titular !== carteiraAtual;
      toast((id ? "Lançamento atualizado" : body.repetir === "mensal" ? "Lançamento mensal criado" :
        body.repetir === "parcelado" ? `Compra lançada em ${d.parcelas} parcelas` : "Lançamento salvo") +
        (fora && p ? `, na carteira de ${p.nome} (selecione “Visão da família” para ver tudo junto).` : "."));
      const manterData = f.data.value;
      limparForm();
      if (!id) { f.data.value = manterData; atualizarResumoForm(); }
      carregarLancamentos();
    } catch (e) { toast(e.message, true); }
  });

  $("#form-plan-categoria").addEventListener("submit", async ev => {
    ev.preventDefault();
    try {
      const r = await api("/api/plan/categorias", { method: "POST", body: formDados(ev.target) });
      categoriasPlan = [];
      await garantirCategorias();
      if (ev.target.tipo.value === tipoForm) preencherCategorias(r.id);
      ev.target.reset();
      toast("Categoria criada.");
    } catch (e) { toast(e.message, true); }
  });

  async function carregarLancamentos() {
    atualizarSeletoresMes();
    try {
      await garantirCategorias();
      [dadosLanc] = await Promise.all([api(`/api/plan/lancamentos?mes=${mesPlan}`), carregarCartoes()]);
    } catch (e) { return toast(e.message, true); }
    pessoasPlan = dadosLanc.pessoas || [];
    document.body.classList.toggle("plan-sem-edicao", !pessoasPlan.some(p => p.editar));
    // primeiro acesso do administrador: convida a cadastrar os membros da família
    $("#aviso-membros").classList.toggle("oculto", !USUARIO.admin || pessoasPlan.some(p => p.cadastrado));
    if (!$("#form-plan").id.value) limparForm();
    renderLancamentos();
  }

  function renderLancamentos() {
    const filtro = $("#plan-filtro").value, todos = dadosLanc.lancamentos;
    const lista = todos.filter(l => !filtro || (filtro === "pendente" ? !l.pago : l.tipo === filtro));
    const soma = t => todos.filter(l => l.tipo === t).reduce((a, l) => a + l.valor, 0);
    const rec = soma("receita"), desp = soma("despesa");
    $("#plan-totais").innerHTML = `<span>Receitas <strong class="pos">${brl.format(rec)}</strong></span>
      <span>Despesas <strong>${brl.format(desp)}</strong></span>
      <span>Saldo <strong class="${rec - desp >= 0 ? "pos" : "neg"}">${brl.format(rec - desp)}</strong></span>
      <small class="dica">Proventos e aportes da carteira aparecem no Resumo do mês.</small>`;
    const varias = new Set(todos.map(l => l.carteira_id)).size > 1 || carteiraAtual === FAMILIA;
    const nomePessoa = cid => pessoasPlan.find(p => p.id === cid)?.nome || "";
    const podeEditar = cid => pessoasPlan.some(p => p.id === cid && p.editar);
    $("#tabela-plan").innerHTML = lista.length ? `<tr><th>Data</th><th>Descrição</th>${varias ? "<th>Titular</th>" : ""}<th>Pagamento</th><th>Valor</th><th>Situação</th><th></th></tr>` +
      lista.map(l => {
        const aguardando = l.tipo === "despesa" && l.cartao_id && !l.chave_import && !l.projetado;
        const selos = [aguardando ? "aguardando fatura" : "", l.conferido_em ? "✓ conferido com a fatura" : "",
          l.recorrencia_id ? "mensal" : "", l.parcela_total ? `${l.parcela_num}/${l.parcela_total}` : "",
          l.compartilhado ? (l.tipo === "receita" ? "grupo familiar" : "compartilhada") : "", l.projetado ? "previsto" : ""]
          .filter(Boolean).map(s => `<span class="selo">${s}</span>`).join(" ");
        const situacao = l.projetado ? `<span class="dica">previsto</span>`
          : l.pago ? `<span class="pos">${l.tipo === "receita" ? "recebido" : "pago"}</span>`
          : podeEditar(l.carteira_id) ? `<button type="button" class="link acao" data-pagar="${l.id}">marcar ${l.tipo === "receita" ? "recebido" : "pago"}</button>`
          : `<span class="dica">${l.tipo === "receita" ? "a receber" : "a pagar"}</span>`;
        return `<tr class="${l.projetado ? "desativado" : ""}">
          <td>${fmtData(l.data)}</td>
          <td><strong>${esc(l.descricao)}</strong> ${selos}<small class="var-sub">${esc(nomeCat(l.categoria_id))}${l.valor_bruto ? ` · bruto ${brl.format(l.valor_bruto)}` : ""}</small></td>
          ${varias ? `<td>${l.tipo === "receita" && l.compartilhado ? "Grupo familiar" : esc(nomePessoa(l.carteira_id))}</td>` : ""}
          <td>${l.cartao_id && cartoesPlan.find(c => c.id === l.cartao_id) ? esc(cartoesPlan.find(c => c.id === l.cartao_id).nome) : esc(formasPlan[l.forma] || "—")}</td>
          <td class="${l.tipo === "receita" ? "pos" : ""}">${l.tipo === "receita" ? "+" : "−"}${brl.format(l.valor)}</td>
          <td>${situacao}</td>
          <td>${l.projetado || !podeEditar(l.carteira_id) ? "" : `<span><button class="link editar" data-plan-editar="${l.id}">editar</button><button class="link" data-plan-excluir="${l.id}">excluir</button>${
            l.conferido_em ? `<button class="link acao" data-desfazer-conf="${l.id}" title="Separa esta compra da linha da fatura">desfazer conferência</button>` : ""}</span>`}</td></tr>`;
      }).join("")
      : `<tr><td>${todos.length ? "Nenhum lançamento com este filtro." : "Nenhum lançamento neste mês."}</td></tr>`;

    const recs = dadosLanc.recorrencias;
    $("#tabela-plan-fixas").innerHTML = recs.length ? `<tr><th>Descrição</th><th>Dia</th><th>Valor</th><th>Período</th><th></th></tr>` +
      recs.map(r => `<tr><td><strong>${esc(r.descricao)}</strong><small class="var-sub">${r.tipo === "receita" ? "Receita" : "Despesa"} · ${esc(nomeCat(r.categoria_id))}</small></td>
        <td>${r.dia}</td><td class="${r.tipo === "receita" ? "pos" : ""}">${brl.format(r.valor)}</td>
        <td>desde ${fmtData(r.inicio + "-01").slice(3)}${r.fim ? ` até ${fmtData(r.fim + "-01").slice(3)}` : ""}</td>
        <td>${r.fim && r.fim < dadosLanc.mes_atual ? `<span class="dica">encerrada</span>` : podeEditar(r.carteira_id) ? `<button class="link" data-plan-encerrar="${r.id}">encerrar</button>` : ""}</td></tr>`).join("")
      : `<tr><td>Nenhuma receita ou conta fixa. Ao lançar, escolha “Todo mês”.</td></tr>`;
  }
  $("#plan-filtro").addEventListener("change", renderLancamentos);

  document.addEventListener("click", async ev => {
    const dc = ev.target.closest("[data-desfazer-conf]");
    if (dc) {
      if (!confirm("Desfazer a conferência? A compra continua lançada; ao importar a fatura de novo, a linha dela poderá ser conferida ou lançada.")) return;
      try { await api(`/api/plan/lancamentos/${dc.dataset.desfazerConf}/desfazer-conferencia`, { method: "POST" }); toast("Conferência desfeita."); carregarLancamentos(); }
      catch (e) { toast(e.message, true); }
      return;
    }
    const ed = ev.target.closest("[data-plan-editar]"), ex = ev.target.closest("[data-plan-excluir]"),
      enc = ev.target.closest("[data-plan-encerrar]");
    if (ed) {
      const l = dadosLanc.lancamentos.find(x => x.id === +ed.dataset.planEditar), f = $("#form-plan");
      tipoForm = l.tipo;
      preencherCategorias(l.categoria_id);
      f.id.value = l.id; f.data.value = l.data; f.descricao.value = l.descricao; f.valor.value = l.valor;
      f.dataset.carteiraOriginal = l.carteira_id;
      f.valor_bruto.value = l.valor_bruto || ""; f.pago.checked = !!l.pago;
      f.querySelectorAll('input[name="forma"]').forEach(r => (r.checked = r.value === (l.forma || "")));
      f.cartao_id.value = l.cartao_id || "";
      renderTitulares(l.carteira_id, l.tipo === "receita" && !!l.compartilhado);
      f.querySelector(`input[name="conta"][value="${l.compartilhado ? "familia" : "pessoal"}"]`).checked = true;
      f.atualizar_proximos.checked = false;
      f.querySelector(".campo-proximos").classList.toggle("oculto", !l.recorrencia_id);
      $("#plan-form-titulo").textContent = "Editar lançamento";
      $("#btn-plan-cancelar").classList.remove("oculto");
      ajustarForm();
      $("#painel-plan-form").scrollIntoView({ behavior: "smooth", block: "start" });
    }
    if (ex) {
      const l = dadosLanc.lancamentos.find(x => x.id === +ex.dataset.planExcluir);
      let escopo = "este";
      if (l.recorrencia_id || l.parcela_grupo) {
        const dlg = $("#dialogo-plan-excluir");
        $("#dialogo-plan-texto").textContent = l.recorrencia_id
          ? `“${l.descricao}” se repete todo mês. Excluir só este mês ou este e os próximos (encerra a repetição)?`
          : `“${l.descricao}” é a parcela ${l.parcela_num} de ${l.parcela_total}. Excluir só esta ou esta e as seguintes?`;
        dlg.showModal();
        escopo = await new Promise(res => dlg.addEventListener("close", () => res(dlg.returnValue), { once: true }));
        if (!escopo || escopo === "cancelar") return;
      } else if (!confirm(`Excluir “${l.descricao}”?`)) return;
      try {
        await api(`/api/plan/lancamentos/${l.id}?escopo=${escopo}`, { method: "DELETE" });
        toast("Lançamento excluído.");
        carregarLancamentos();
      } catch (e) { toast(e.message, true); }
    }
    if (enc) {
      if (!confirm("Encerrar esta repetição? Os meses já lançados continuam; os próximos deixam de ser lançados.")) return;
      try {
        await api(`/api/plan/recorrencias/${enc.dataset.planEncerrar}`, { method: "DELETE" });
        toast("Repetição encerrada.");
        carregarLancamentos();
      } catch (e) { toast(e.message, true); }
    }
  });

  // ---------------- Cartões e importação de fatura ----------------
  async function carregarCartoes() {
    cartoesPlan = await api("/api/plan/cartoes");
    const opcoes = cartoesPlan.map(c => `<option value="${c.id}">${esc(c.nome)}</option>`).join("");
    const sel = $("#sel-cartao-fatura"), atual = sel.value;
    sel.innerHTML = cartoesPlan.length ? opcoes : `<option value="">Cadastre um cartão abaixo</option>`;
    if (atual) sel.value = atual;
    $("#form-plan").cartao_id.innerHTML = `<option value="">Selecione o cartão</option>` + opcoes;
    $("#lista-cartoes").innerHTML = cartoesPlan.length ? `<ul class="plan-lista">${cartoesPlan.map(c => `<li>
        <span class="plan-nome">${esc(c.nome)}<small>${c.dia_vencimento ? `vence dia ${c.dia_vencimento}` : "sem dia de vencimento"}</small></span>
        <button type="button" class="link" data-remover-cartao="${c.id}">remover</button></li>`).join("")}</ul>` : "";
    $("#novo-cartao").open = !cartoesPlan.length;
    ajustarForm();
  }

  $("#form-cartao").addEventListener("submit", async ev => {
    ev.preventDefault();
    try {
      const r = await api("/api/plan/cartoes", { method: "POST", body: formDados(ev.target) });
      ev.target.reset();
      await carregarCartoes();
      $("#sel-cartao-fatura").value = r.id;
      toast("Cartão cadastrado.");
    } catch (e) { toast(e.message, true); }
  });

  // seleção do arquivo da fatura (botão próprio, sem o campo nativo do navegador)
  let arquivoFatura = null;
  function escolherArquivoFatura(f) {
    arquivoFatura = f || null;
    $("#nome-arquivo-fatura").textContent = f ? f.name : "ou arraste a fatura para cá";
    $("#nome-arquivo-fatura").classList.toggle("escolhido", !!f);
    $("#btn-arquivo-fatura span").textContent = f ? "Trocar arquivo" : "Escolher arquivo";
    // PDF: mostra o campo de senha (faturas por e-mail costumam ser protegidas)
    $("#form-fatura .campo-senha-pdf").classList.toggle("oculto", !(f && /\.pdf$/i.test(f.name)));
    $("#form-fatura").senha.value = "";
    $("#previa-fatura").innerHTML = "";
  }
  $("#btn-arquivo-fatura").addEventListener("click", () => $("#arquivo-fatura").click());
  $("#arquivo-fatura").addEventListener("change", ev => { escolherArquivoFatura(ev.target.files[0]); ev.target.value = ""; });
  const zonaFatura = $("#zona-fatura");
  ["dragenter", "dragover"].forEach(t => zonaFatura.addEventListener(t, ev => { ev.preventDefault(); zonaFatura.classList.add("arrastando"); }));
  ["dragleave", "drop"].forEach(t => zonaFatura.addEventListener(t, () => zonaFatura.classList.remove("arrastando")));
  zonaFatura.addEventListener("drop", ev => { ev.preventDefault(); escolherArquivoFatura(ev.dataTransfer.files[0]); });

  $("#form-fatura").addEventListener("submit", async ev => {
    ev.preventDefault();
    if (!arquivoFatura) return toast("Escolha o arquivo da fatura.", true);
    const fd = new FormData();
    fd.append("arquivo", arquivoFatura, arquivoFatura.name);
    fd.append("cartao_id", ev.target.cartao_id.value);
    if (ev.target.senha.value) fd.append("senha", ev.target.senha.value);
    if (!fd.get("cartao_id")) return toast("Cadastre ou escolha o cartão desta fatura.", true);
    $("#previa-fatura").innerHTML = `<p class="dica">Lendo a fatura…</p>`;
    try {
      const r = await fetch("/api/plan/fatura/previa", { method: "POST", body: fd,
        headers: { "X-Requested-With": "fetch", "X-Carteira": String(carteiraAtual) } });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) {
        if (/senha/i.test(j.erro || "")) {
          $("#form-fatura .campo-senha-pdf").classList.remove("oculto");
          ev.target.senha.focus();
        }
        throw new Error(j.erro || `Erro ${r.status}`);
      }
      previaFatura = j;
      renderPreviaFatura();
    } catch (e) { $("#previa-fatura").innerHTML = ""; toast(e.message, true); }
  });

  const SELO_TIPO = { estorno: "estorno", tarifa: "tarifa", pagamento: "pagamento da fatura" };

  function opcoesCategoria(tipo, selecionada) {
    const grupos = {};
    categoriasPlan.filter(c => c.tipo === tipo).forEach(c => (grupos[c.grupo] ||= []).push(c));
    return `<option value="">Sem categoria</option>` + Object.entries(grupos).map(([g, cs]) =>
      `<optgroup label="${esc(g)}">${cs.map(c => `<option value="${c.id}" ${c.id === selecionada ? "selected" : ""}>${esc(c.nome)}</option>`).join("")}</optgroup>`).join("");
  }

  function renderPreviaFatura() {
    const p = previaFatura, r = p.resumo;
    const semCat = p.itens.filter(i => i.marcado && !i.categoria_id && i.tipo !== "pagamento").length;
    const fimFatura = p.itens.reduce((m, i) => (i.data > m ? i.data : m), "");
    const cartao = cartoesPlan.find(c => c.id === p.cartao_id);
    const venc = cartao?.dia_vencimento && fimFatura
      ? `${somarMes(fimFatura.slice(0, 7), 1)}-${String(cartao.dia_vencimento).padStart(2, "0")}` : "";
    $("#previa-fatura").innerHTML = `
      <div class="fatura-resumo">
        <div><span>Compras</span><strong>${r.compras}</strong></div>
        <div><span>Total</span><strong>${brl.format(r.total)}</strong></div>
        <div><span>Categorizadas</span><strong>${r.categorizados} de ${r.compras}</strong></div>
        <div><span>Já importadas</span><strong>${r.ja_importados}</strong></div>
      </div>
      ${r.conciliadas || r.possiveis ? `<div class="fatura-conciliacao">
          ${r.conciliadas ? `<span class="ok">✓ ${r.conciliadas} compra(s) que você já tinha lançado serão conferidas, sem duplicar</span>` : ""}
          ${r.possiveis ? `<span class="atencao">${r.possiveis} possível(is) correspondência(s): confirme na coluna Situação</span>` : ""}
        </div>` : ""}
      ${semCat ? `<p class="aviso" style="margin:10px 0">${semCat} compra(s) sem categoria: escolha abaixo. O sistema lembra da escolha para as próximas faturas.</p>` : ""}
      <div class="rolagem"><table class="tabela-fatura"><tr><th><input type="checkbox" id="fatura-todos" checked aria-label="Marcar todos"></th>
        <th>Data</th><th>Descrição</th><th>Valor</th><th>Categoria</th><th>Situação</th></tr>
        ${p.itens.map((i, n) => `<tr class="${i.ja_importado || i.tipo === "pagamento" ? "desativado" : ""}">
          <td><input type="checkbox" data-fatura-item="${n}" ${i.marcado ? "checked" : ""} ${i.ja_importado || i.tipo === "pagamento" ? "disabled" : ""}></td>
          <td>${fmtData(i.data)}</td>
          <td><strong>${esc(i.descricao)}</strong>
            ${i.parcela_total ? `<span class="selo">parcela ${i.parcela_num}/${i.parcela_total}</span>` : ""}
            ${SELO_TIPO[i.tipo] ? `<span class="selo">${SELO_TIPO[i.tipo]}</span>` : ""}
            ${i.ja_importado ? `<span class="selo">já importado</span>` : ""}</td>
          <td class="${i.tipo === "estorno" ? "pos" : ""}">${i.tipo === "estorno" ? "+" : ""}${brl.format(i.valor)}</td>
          <td>${i.tipo === "pagamento" ? `<span class="dica">ignorado</span>` : `<select data-fatura-cat="${n}" class="${i.categoria_id ? "" : "sem-categoria"}">
              ${opcoesCategoria(i.tipo === "estorno" ? "receita" : "despesa", i.categoria_id)}</select>
            ${i.origem_categoria ? `<small class="var-sub">${{ aprendida: "como da última vez", sua: "a que você escolheu", padrao: "sugestão automática" }[i.origem_categoria] || ""}</small>` : ""}`}</td>
          <td class="situacao-fatura">${situacaoFatura(i, n)}</td></tr>`).join("")}
      </table></div>
      <div class="form-linha fatura-opcoes">
        <label>Lançar na data <select id="fatura-data-modo"><option value="compra">de cada compra</option>
          <option value="vencimento">de vencimento da fatura</option></select></label>
        <label class="oculto" id="campo-vencimento">Vencimento <input type="date" id="fatura-vencimento" value="${venc}"></label>
        <label class="check"><input type="checkbox" id="fatura-futuras" checked> Lançar as parcelas futuras das compras parceladas</label>
        <button type="button" class="btn" id="btn-importar-fatura"></button>
      </div>`;
    atualizarBotaoFatura();
  }

  function situacaoFatura(i, n) {
    if (i.ja_importado) return `<span class="dica">já importada</span>`;
    if (i.tipo === "pagamento") return "";
    const c = i.conciliacao;
    if (!c) return `<span class="dica">nova</span>`;
    const m = c.lancamento, ref = `${fmtData(m.data)} · ${esc(m.descricao)} · ${brl.format(m.valor)}`;
    if (c.tipo === "exato") return `<span class="sit-ok">✓ Já lançada por você</span><small class="var-sub">${ref}</small>`;
    return `<span class="sit-atencao">Possível correspondência</span><small class="var-sub">${ref}</small>
      <select data-fatura-acao="${n}"><option value="unir" ${i.acao === "unir" ? "selected" : ""}>É a mesma compra</option>
        <option value="nova" ${i.acao === "nova" ? "selected" : ""}>É outra compra (lançar)</option></select>`;
  }

  function atualizarBotaoFatura() {
    const n = document.querySelectorAll("[data-fatura-item]:checked").length;
    const b = $("#btn-importar-fatura");
    if (b) { b.textContent = `Importar ${n} lançamento(s)`; b.disabled = !n; }
  }

  $("#previa-fatura").addEventListener("change", ev => {
    const t = ev.target;
    if (t.id === "fatura-todos") document.querySelectorAll("[data-fatura-item]:not(:disabled)").forEach(c => (c.checked = t.checked));
    if (t.dataset.faturaCat !== undefined) {
      const item = previaFatura.itens[+t.dataset.faturaCat];
      item.categoria_id = t.value ? +t.value : null;
      t.classList.toggle("sem-categoria", !t.value);
      // a mesma escolha vale para as outras compras do mesmo estabelecimento ainda sem categoria
      previaFatura.itens.forEach((o, n) => {
        if (o !== item && !o.categoria_id && o.estabelecimento === item.estabelecimento && o.tipo === item.tipo) {
          o.categoria_id = item.categoria_id;
          const s = document.querySelector(`[data-fatura-cat="${n}"]`);
          if (s) { s.value = t.value; s.classList.toggle("sem-categoria", !t.value); }
        }
      });
    }
    if (t.dataset.faturaAcao !== undefined) previaFatura.itens[+t.dataset.faturaAcao].acao = t.value;
    if (t.id === "fatura-data-modo") $("#campo-vencimento").classList.toggle("oculto", t.value !== "vencimento");
    atualizarBotaoFatura();
  });

  $("#previa-fatura").addEventListener("click", async ev => {
    if (ev.target.id !== "btn-importar-fatura") return;
    const itens = [...document.querySelectorAll("[data-fatura-item]:checked")].map(c => {
      const i = previaFatura.itens[+c.dataset.faturaItem];
      return i.conciliacao ? { ...i, lancamento_id: i.conciliacao.lancamento.id, acao: i.acao || "unir" } : i;
    });
    try {
      const r = await api("/api/plan/fatura/confirmar", { method: "POST", body: {
        cartao_id: previaFatura.cartao_id, itens, data_modo: $("#fatura-data-modo").value,
        vencimento: $("#fatura-vencimento").value, parcelas_futuras: $("#fatura-futuras").checked } });
      toast(`Fatura importada: ${r.lancamentos} lançamento(s) novo(s)` + (r.conferidos ? `, ${r.conferidos} conferido(s) com o que você já tinha lançado` : "") +
        (r.parcelas_futuras ? `, ${r.parcelas_futuras} parcela(s) futura(s)` : "") +
        (r.regras_aprendidas ? `. ${r.regras_aprendidas} categoria(s) aprendida(s) para as próximas faturas.` : "."));
      previaFatura = null;
      $("#previa-fatura").innerHTML = "";
      escolherArquivoFatura(null);
      carregarLancamentos();
    } catch (e) { toast(e.message, true); }
  });

  document.addEventListener("click", async ev => {
    const b = ev.target.closest("[data-remover-cartao]");
    if (!b || !confirm("Remover este cartão? Os lançamentos já feitos continuam.")) return;
    try { await api(`/api/plan/cartoes/${b.dataset.removerCartao}`, { method: "DELETE" }); carregarCartoes(); }
    catch (e) { toast(e.message, true); }
  });

  // ================= Orçamento, projeção e IR =================
  let dadosOrc = null;
  async function carregarOrcamento() {
    atualizarSeletoresMes();
    try {
      [dadosOrc] = await Promise.all([api(`/api/plan/orcamento?mes=${mesPlan}`), carregarProjecao(), carregarIrPlan()]);
    } catch (e) { return toast(e.message, true); }
    renderOrcamento();
  }

  function renderOrcamento() {
    const o = dadosOrc;
    const restante = o.total_limite - o.total_gasto;
    $("#orc-resumo").innerHTML = o.total_limite ? `<span>Orçado <strong>${brl.format(o.total_limite)}</strong></span>
      <span>Gasto <strong>${brl.format(o.total_gasto)}</strong></span>
      <span>${restante >= 0 ? "Disponível" : "Acima do orçado"} <strong class="${restante >= 0 ? "pos" : "neg"}">${brl.format(Math.abs(restante))}</strong></span>
      ${o.fracao_mes ? `<small class="dica">${Math.round(o.fracao_mes * 100)}% do mês já passou</small>` : ""}`
      : `<span class="dica">Nenhum limite definido. Preencha os valores abaixo ou use a média dos últimos 3 meses.</span>`;
    const itens = o.itens.filter(i => i.limite || i.gasto || i.media_3m);
    const resto = o.itens.filter(i => !(i.limite || i.gasto || i.media_3m));
    const linha = i => {
      const pct = i.pct == null ? 0 : Math.min(i.pct, 100);
      return `<div class="orc-item ${i.estado}">
        <div class="orc-topo"><strong>${esc(i.grupo)}</strong>${i.pct != null ? `<span class="orc-pct">${Math.round(i.pct)}%</span>` : ""}</div>
        <div class="orc-valores">${brl.format(i.gasto)}${i.limite ? ` <span>de ${brl.format(i.limite)}</span>` : ""}</div>
        <div class="progresso"><span style="width:${pct}%"></span></div>
        <div class="orc-rodape"><small>${i.limite ? (i.gasto <= i.limite ? `restam ${brl.format(i.limite - i.gasto)}` : `<span class="neg">${brl.format(i.gasto - i.limite)} acima</span>`) : "sem limite"}${
          i.media_3m ? ` · média ${brl.format(i.media_3m)}` : ""}</small>
          <label class="requer-edicao">Limite <input type="number" min="0" step="10" data-orc-grupo="${esc(i.grupo)}" value="${i.limite || ""}" placeholder="—"></label></div>
      </div>`;
    };
    $("#orc-lista").innerHTML = itens.map(linha).join("") +
      (resto.length ? `<details class="conf-mais"><summary>Outros grupos (${resto.length})</summary>${resto.map(linha).join("")}</details>` : "");
  }

  $("#btn-orc-media").addEventListener("click", () => {
    document.querySelectorAll("[data-orc-grupo]").forEach(inp => {
      const i = dadosOrc.itens.find(x => x.grupo === inp.dataset.orcGrupo);
      if (i && i.media_3m) inp.value = Math.ceil(i.media_3m / 10) * 10;
    });
    toast("Limites preenchidos pela média. Ajuste e clique em Salvar limites.");
  });
  $("#btn-orc-salvar").addEventListener("click", async () => {
    const limites = {};
    document.querySelectorAll("[data-orc-grupo]").forEach(inp => { if (inp.value) limites[inp.dataset.orcGrupo] = inp.value; });
    try { await api("/api/plan/orcamento", { method: "PUT", body: { limites } }); toast("Orçamento salvo."); carregarOrcamento(); }
    catch (e) { toast(e.message, true); }
  });

  async function carregarProjecao() {
    const p = await api("/api/plan/projecao");
    grafico("graf-plan-projecao", {
      data: {
        labels: p.meses.map(m => nomeMes(m.mes).slice(0, 3) + "/" + m.mes.slice(2, 4)),
        datasets: [
          { type: "bar", label: "Receitas previstas", data: p.meses.map(m => m.receitas), backgroundColor: PALETA[0] },
          { type: "bar", label: "Despesas previstas", data: p.meses.map(m => m.despesas), backgroundColor: PALETA[3] },
          { type: "line", label: "Saldo acumulado", data: p.meses.map(m => m.acumulado), borderColor: PALETA[2], backgroundColor: PALETA[2], tension: .25, pointRadius: 2 },
        ],
      },
      options: { plugins: { tooltip: { callbacks: { label: c => ` ${c.dataset.label}: ${brl.format(c.raw)}` } } },
        scales: { y: { ticks: { callback: v => brl.format(v).replace(",00", "") } } } },
    });
    const negativo = p.meses.find(m => m.acumulado < 0);
    $("#aviso-projecao").innerHTML = !negativo ? "" : p.aporte_objetivos && p.meses.every(m => m.saldo + m.aporte_objetivos >= 0)
      ? `<p class="aviso">Sem os aportes planejados nos objetivos (${brl.format(p.aporte_objetivos)} por mês), as contas fecham.
          Com eles, falta dinheiro a partir de ${nomeMes(negativo.mes)}: reveja os valores ou os prazos em “Objetivos”.</p>`
      : `<p class="aviso">As despesas previstas passam da renda: o saldo fica negativo a partir de ${nomeMes(negativo.mes)}.</p>`;
    $("#tabela-projecao").innerHTML = `<tr><th>Mês</th><th>Receitas</th><th>Despesas</th><th>Parcelas</th><th>Objetivos</th><th>Saldo</th><th>Acumulado</th></tr>` +
      p.meses.map(m => `<tr><td>${nomeMes(m.mes)}</td><td class="pos">${brl.format(m.receitas)}</td><td>${brl.format(m.despesas)}</td>
        <td>${m.parcelas ? brl.format(m.parcelas) : "—"}</td><td>${m.aporte_objetivos ? brl.format(m.aporte_objetivos) : "—"}</td>
        <td class="${m.saldo >= 0 ? "pos" : "neg"}">${brl.format(m.saldo)}</td><td class="${m.acumulado >= 0 ? "" : "neg"}">${brl.format(m.acumulado)}</td></tr>`).join("");
  }

  async function carregarIrPlan() {
    const sel = $("#ir-plan-ano");
    if (!sel.options.length) {
      const a = +hojeLocal().slice(0, 4);
      sel.innerHTML = [a, a - 1, a - 2].map(x => `<option value="${x}">${x}</option>`).join("");
    }
    const r = await api(`/api/plan/ir?ano=${sel.value}`);
    const ded = r.dedutiveis;
    $("#ir-plan").innerHTML = `<div class="plan-indicadores">
        <div><span>Rendimentos do trabalho (bruto)</span><strong>${brl.format(r.rendimentos_brutos)}</strong><small>Salários, 13º, férias, PLR lançados com o valor bruto.</small></div>
        <div><span>Descontos na fonte</span><strong>${brl.format(r.descontos)}</strong><small>Bruto menos líquido: INSS, IR retido e outros descontos.</small></div>
      </div>
      <h4 style="margin:16px 0 6px">Despesas que costumam ser dedutíveis (declaração completa)</h4>
      ${ded.length ? `<ul class="plan-lista">${ded.map(d => `<li><span class="plan-nome">${esc(d.categoria)}<small>${esc(d.grupo)}</small></span><strong>${brl.format(d.valor)}</strong></li>`).join("")}</ul>`
        : `<p class="dica">Nenhuma despesa de saúde (plano, consultas, exames) ou educação (escola, faculdade) lançada em ${r.ano}.</p>`}
      <p class="dica">Saúde não tem limite de dedução; educação tem limite anual por pessoa. Guarde os recibos com CPF/CNPJ.</p>`;
  }
  $("#ir-plan-ano").addEventListener("change", () => carregarIrPlan().catch(e => toast(e.message, true)));

  // ================= Objetivos =================
  let dadosObj = null;
  const SIT_OBJ = { atingido: ["Atingido", "ok"], no_ritmo: ["No ritmo", "ok"], atrasado: ["Atrasado", "atencao"],
    em_risco: ["Precisa de mais aporte", "risco"], incompleto: ["Faltam dados", "atencao"] };
  const mesAno = d => d ? nomeMes(d.slice(0, 7)).replace(" de ", "/") : "—";
  const anosMeses = n => n == null ? "mais de 100 anos" : n < 12 ? `${n} ${n === 1 ? "mês" : "meses"}` :
    `${Math.floor(n / 12)} ano${n >= 24 ? "s" : ""}${n % 12 ? ` e ${n % 12} ${n % 12 === 1 ? "mês" : "meses"}` : ""}`;

  function mesesParaAtingir(alvo, atual, aporte, r) {
    let v = atual, m = 0;
    while (v < alvo) { if (m >= 1200) return null; v = v * (1 + r) + aporte; m++; }
    return m;
  }
  function aporteNecessario(alvo, atual, meses, r) {
    if (atual >= alvo) return 0;
    if (meses <= 0) return alvo - atual;
    const c = Math.pow(1 + r, meses);
    return r === 0 ? (alvo - atual) / meses : Math.max((alvo - atual * c) * r / (c - 1), 0);
  }

  async function carregarObjetivos() {
    try { dadosObj = await api("/api/plan/objetivos"); } catch (e) { return toast(e.message, true); }
    const d = dadosObj;
    const semObjetivos = !d.objetivos.length;
    $("#obj-cards").innerHTML = [
      ["Aporte necessário / mês", semObjetivos ? "—" : brl.format(d.total_necessario),
        semObjetivos ? "crie um objetivo para calcular" : "soma dos objetivos ainda não atingidos"],
      ["Você planeja guardar", semObjetivos ? "—" : brl.format(d.total_planejado),
        semObjetivos ? "informado em cada objetivo" : d.total_planejado >= d.total_necessario - 0.01
          ? "suficiente para todos os prazos" : `faltam ${brl.format(d.total_necessario - d.total_planejado)} por mês`],
      ["Sobra média antes de investir", d.sobra_media == null ? "—" : brl.format(d.sobra_media), "últimos 3 meses lançados no planejamento"],
      ["Custo de vida médio", d.custo_de_vida == null ? "—" : brl.format(d.custo_de_vida), "base da reserva de emergência"],
    ].map(([r, v, sub]) => `<div class="card"><div class="rotulo">${r}</div><div class="valor">${v}</div><small class="var-sub">${sub}</small></div>`).join("");
    $("#obj-lista").innerHTML = d.objetivos.length ? d.objetivos.map((o, i) => {
      const [sit, cls] = SIT_OBJ[o.situacao];
      return `<div class="obj-cartao">
        <div class="obj-cab"><div><span class="selo">${esc(o.rotulo_tipo)}</span><h4>${esc(o.nome)}</h4></div><span class="obj-sit ${cls}">${sit}</span></div>
        <div class="obj-valores"><strong>${brl.format(o.valor_atual)}</strong><span>${o.valor_alvo_calc ? `de ${brl.format(o.valor_alvo_calc)}` : "guardado"}</span></div>
        ${o.situacao === "incompleto" ? `<p class="dica" style="margin:0">Para calcular o valor da reserva, lance suas despesas do mês em “Receitas e despesas” ou informe o valor do objetivo.</p>` : ""}
        <div class="progresso"><span style="width:${o.progresso}%"></span></div>
        <small class="var-sub">${Math.round(o.progresso)}% · prazo ${mesAno(o.data_alvo_calc)}${o.explicacao ? ` · ${esc(o.explicacao)}` : ""}</small>
        <dl class="obj-numeros">
          <div><dt>Necessário por mês</dt><dd>${o.aporte_necessario == null ? "—" : brl.format(o.aporte_necessario)}</dd></div>
          <div><dt>Planejado por mês</dt><dd>${brl.format(o.aporte_planejado)}</dd></div>
          <div><dt>No ritmo planejado</dt><dd>${o.situacao === "atingido" ? "já atingido" : !o.valor_alvo_calc ? "—" : o.data_prevista ? `chega em ${mesAno(o.data_prevista)}` : "não chega"}</dd></div>
        </dl>
        ${o.tickers.length ? `<div class="chips">${o.tickers.map(t => `<span class="chip">${esc(t)}</span>`).join("")}</div>` : ""}
        <details class="obj-simular"><summary>Simular “e se…”</summary>
          <div class="form-linha">
            <label>Guardar por mês <input type="number" min="0" step="50" data-sim="aporte" data-obj="${i}" value="${Math.round(o.aporte_planejado)}"></label>
            <label>Rentabilidade real (% a.a.) <input type="number" min="0" max="30" step="0.5" data-sim="taxa" data-obj="${i}" value="${o.rentabilidade}"></label>
          </div>
          <p class="sim-resultado" data-sim-res="${i}"></p>
        </details>
        <div class="obj-acoes requer-edicao"><button class="link editar" data-obj-editar="${o.id}">editar</button><button class="link" data-obj-excluir="${o.id}">excluir</button></div>
      </div>`;
    }).join("") : `<div class="painel plan-boas-vindas"><h3>Defina seus objetivos</h3>
        <p class="dica">Comece pela <strong>reserva de emergência</strong> e depois a <strong>aposentadoria</strong>. Para cada objetivo, o sistema calcula quanto guardar por mês e acompanha o progresso, inclusive com os ativos da carteira que você reservar para ele.</p>
        <button type="button" class="btn requer-edicao" data-novo-objetivo>Criar o primeiro objetivo</button></div>`;
    document.querySelectorAll("[data-sim-res]").forEach(e => simular(+e.dataset.simRes));
  }

  function simular(i) {
    const o = dadosObj.objetivos[i];
    const aporte = +document.querySelector(`[data-sim="aporte"][data-obj="${i}"]`).value || 0;
    const taxa = +document.querySelector(`[data-sim="taxa"][data-obj="${i}"]`).value || 0;
    const r = Math.pow(1 + taxa / 100, 1 / 12) - 1;
    const m = mesesParaAtingir(o.valor_alvo_calc, o.valor_atual, aporte, r);
    const nec = aporteNecessario(o.valor_alvo_calc, o.valor_atual, o.meses, r);
    const res = document.querySelector(`[data-sim-res="${i}"]`);
    res.innerHTML = !o.valor_alvo_calc ? "" : o.valor_atual >= o.valor_alvo_calc ? "Objetivo já atingido."
      : `Guardando <strong>${brl.format(aporte)}</strong> por mês a ${pct(taxa, 1)} ao ano, chega lá em <strong>${anosMeses(m)}</strong>${m != null ? ` (${mesAno(somarMes(hojeLocal().slice(0, 7), m) + "-01")})` : ""}.
         Para o prazo de ${mesAno(o.data_alvo_calc)}, seriam ${brl.format(nec)} por mês.`;
  }
  $("#obj-lista").addEventListener("input", ev => { if (ev.target.dataset.sim) simular(+ev.target.dataset.obj); });

  const CAMPOS_TIPO = {
    reserva: ["meses_reserva", "valor_alvo", "data_alvo"], aposentadoria: ["renda_desejada", "idade_atual", "idade_alvo"],
    renda_passiva: ["renda_desejada", "data_alvo"],
  };
  const DICAS_TIPO = {
    reserva: "Deixe o valor vazio para usar 6 meses (ou os meses informados) do seu custo de vida médio. Guarde em algo de liquidez diária, como Tesouro Selic ou CDB com liquidez.",
    aposentadoria: "O valor necessário é 25 vezes a renda anual desejada (regra dos 4%): com ele, retirar 4% ao ano tende a durar a vida toda. Valores em reais de hoje.",
    renda_passiva: "Patrimônio que, rendendo 6% ao ano em proventos (dividendos, FIIs), paga a renda desejada.",
    divida: "Informe o saldo devedor. Quitar dívidas caras costuma render mais que qualquer investimento.",
  };
  function ajustarFormObjetivo() {
    const f = $("#form-objetivo"), tipo = f.tipo.value, campos = CAMPOS_TIPO[tipo] || ["valor_alvo", "data_alvo"];
    document.querySelectorAll("[data-obj-campo]").forEach(l => l.classList.toggle("oculto", !campos.includes(l.dataset.objCampo)));
    $("#obj-dica-tipo").textContent = DICAS_TIPO[tipo] || "";
  }

  function abrirObjetivo(o) {
    const f = $("#form-objetivo");
    f.reset();
    f.tipo.innerHTML = Object.entries(dadosObj.tipos).map(([v, n]) => `<option value="${v}">${esc(n)}</option>`).join("");
    f.id.value = o?.id || "";
    if (o) ["tipo", "nome", "valor_alvo", "valor_guardado", "aporte_mensal", "rentabilidade", "renda_desejada", "idade_atual",
      "idade_alvo", "meses_reserva", "prioridade"].forEach(k => { f[k].value = o[k] ?? ""; });
    if (o?.data_alvo) f.data_alvo.value = o.data_alvo.slice(0, 7);
    const marcados = new Set(o?.tickers || []);
    $("#obj-ativos-lista").innerHTML = dadosObj.ativos.length ? dadosObj.ativos.map(a => `<label class="chip-check">
        <input type="checkbox" value="${esc(a.ticker)}" ${marcados.has(a.ticker) ? "checked" : ""}> ${esc(a.ticker)} <small>${brl.format(a.valor)}</small></label>`).join("")
      : `<span class="dica">Nenhum ativo na carteira.</span>`;
    $("#obj-form-titulo").textContent = o ? "Editar objetivo" : "Novo objetivo";
    ajustarFormObjetivo();
    $("#dialogo-objetivo").showModal();
  }
  $("#form-objetivo").tipo.addEventListener("change", ajustarFormObjetivo);
  $("#btn-obj-cancelar").addEventListener("click", () => $("#dialogo-objetivo").close());
  $("#btn-novo-objetivo").addEventListener("click", () => abrirObjetivo(null));
  $("#form-objetivo").addEventListener("submit", async ev => {
    ev.preventDefault();
    const f = ev.target, d = formDados(f);
    d.tickers = [...document.querySelectorAll("#obj-ativos-lista input:checked")].map(c => c.value);
    try {
      if (d.id) await api(`/api/plan/objetivos/${d.id}`, { method: "PUT", body: d });
      else await api("/api/plan/objetivos", { method: "POST", body: d });
      $("#dialogo-objetivo").close();
      toast("Objetivo salvo.");
      carregarObjetivos();
    } catch (e) { toast(e.message, true); }
  });
  document.addEventListener("click", async ev => {
    if (ev.target.closest("[data-novo-objetivo]")) abrirObjetivo(null);
    const ed = ev.target.closest("[data-obj-editar]"), ex = ev.target.closest("[data-obj-excluir]");
    if (ed) abrirObjetivo(dadosObj.objetivos.find(o => o.id === +ed.dataset.objEditar));
    if (ex && confirm("Excluir este objetivo?")) {
      try { await api(`/api/plan/objetivos/${ex.dataset.objExcluir}`, { method: "DELETE" }); carregarObjetivos(); }
      catch (e) { toast(e.message, true); }
    }
  });

  // ================= Família =================
  let dadosMembros = null;
  async function carregarMembros() {
    dadosMembros = await api("/api/plan/membros");
    const m = dadosMembros, pode = m.pode_configurar;
    const opcoes = sel => Object.entries(m.parentescos).map(([v, n]) => `<option value="${v}" ${v === sel ? "selected" : ""}>${esc(n)}</option>`).join("");
    $("#tabela-membros").innerHTML = `<tr><th>Nome</th><th>Parentesco</th><th>Divide as contas</th><th>Acesso ao sistema</th></tr>` +
      m.membros.map(p => `<tr data-membro="${p.id}">
        <td><input name="nome" value="${esc(p.nome)}" maxlength="60" ${pode ? "" : "disabled"}></td>
        <td><select name="parentesco" ${pode ? "" : "disabled"}>${opcoes(p.parentesco)}</select></td>
        <td><label class="interruptor"><input type="checkbox" name="divide" ${p.divide ? "checked" : ""} ${pode ? "" : "disabled"}><span></span></label></td>
        <td>${p.tem_login ? `<span class="selo">com login</span>` : `<span class="dica">sem login</span>`}<small class="var-sub">${esc(p.carteira)}</small></td></tr>`).join("");
    $("#form-membro").parentesco.innerHTML = opcoes("filho");
    document.querySelectorAll(".plan-admin").forEach(e => e.classList.toggle("oculto", !pode));
    $("#dica-membros").textContent = pode ? (m.configurado ? "" :
      "Confira os nomes e o parentesco e clique em Salvar membros. Para dar acesso a alguém, use Acessos e conta → Usuários.")
      : "Só o administrador altera os membros da família.";
  }
  $("#btn-salvar-membros").addEventListener("click", async () => {
    const membros = [...document.querySelectorAll("[data-membro]")].map(tr => ({ id: +tr.dataset.membro,
      nome: tr.querySelector("[name=nome]").value, parentesco: tr.querySelector("[name=parentesco]").value,
      divide: tr.querySelector("[name=divide]").checked }));
    try { await api("/api/plan/membros", { method: "PUT", body: { membros } }); toast("Membros da família salvos."); carregarFamilia(); }
    catch (e) { toast(e.message, true); }
  });
  $("#form-membro").addEventListener("submit", async ev => {
    ev.preventDefault();
    try {
      await api("/api/plan/membros", { method: "POST", body: formDados(ev.target) });
      ev.target.reset(); $("#novo-membro").open = false;
      toast("Membro adicionado. Ele já pode ser escolhido como titular nos lançamentos.");
      await carregarCarteiras?.(carteiraAtual);
      carregarFamilia();
    } catch (e) { toast(e.message, true); }
  });

  let dadosFam = null;
  async function carregarFamilia() {
    atualizarSeletoresMes();
    carregarMembros().catch(e => toast(e.message, true));
    try { dadosFam = await api(`/api/plan/familia?mes=${mesPlan}`); } catch (e) { return toast(e.message, true); }
    const f = dadosFam, t = f.totais;
    $("#fam-cards").innerHTML = [
      ["Renda da família", brl.format(t.receitas + (t.receitas_grupo || 0) + t.proventos),
        [t.receitas_grupo ? `${brl.format(t.receitas_grupo)} do grupo familiar` : "", t.proventos ? `${brl.format(t.proventos)} de proventos` : ""]
          .filter(Boolean).join(" · ") || "soma da renda líquida de todos"],
      ["Despesas", brl.format(t.despesas), `${brl.format(t.compartilhadas)} em contas da família`],
      ["Investido", brl.format(t.investido), "aportes nas carteiras"],
      ["Sobra da família", `<span class="${t.sobra >= 0 ? "pos" : "neg"}">${brl.format(t.sobra)}</span>`, "renda − despesas − investido"],
    ].map(([r, v, sub]) => `<div class="card"><div class="rotulo">${r}</div><div class="valor">${v}</div><small class="var-sub">${sub}</small></div>`).join("");
    const junto = f.modo === "junto";
    $("#fam-acerto").innerHTML = f.pessoas.length < 2 ? `<p class="dica">A divisão aparece quando há duas ou mais pessoas com carteira e acesso a elas.</p>` :
      `<div class="rolagem"><table class="tabela-familia"><tr><th>Pessoa</th><th>Renda</th><th>Pagou</th>${junto ? "" : "<th>Parte</th><th>Saldo</th>"}</tr>
        ${f.pessoas.map(p => `<tr><td><strong>${esc(p.nome)}</strong>${junto ? "" : `<small class="var-sub">${pct(p.peso, 0)} das contas</small>`}</td>
          <td>${brl.format(p.renda)}</td><td>${brl.format(p.pagou)}</td>
          ${junto ? "" : `<td>${brl.format(p.cota)}</td><td class="${p.saldo >= 0 ? "pos" : "neg"}">${brlSinal(p.saldo) || brl.format(0)}</td>`}</tr>`).join("")}
        <tr class="linha-total"><td>Total</td><td>${brl.format(f.pessoas.reduce((a, p) => a + p.renda, 0))}</td><td>${brl.format(f.total)}</td>${junto ? "" : "<td></td><td></td>"}</tr></table></div>
      <div class="fam-acerto">${junto ? `<p>No modo <strong>tudo junto</strong> não há acerto: as contas saem do caixa comum.</p>`
        : f.transferencias.length ? f.transferencias.map(x => `<p><strong>${esc(x.de)}</strong> transfere <strong>${brl.format(x.valor)}</strong> para <strong>${esc(x.para)}</strong> para acertar o mês.</p>`).join("")
        : `<p>Contas do mês já divididas certinho: ninguém deve nada.</p>`}
        ${(f.fora_da_divisao || []).filter(p => p.pagou).map(p => `<p class="dica">${esc(p.nome)} pagou ${brl.format(p.pagou)} em contas compartilhadas, mas não participa da divisão.</p>`).join("")}</div>`;
    $("#fam-modos").innerHTML = Object.entries(f.modos).map(([v, txt]) => {
      const [titulo, desc] = txt.split(": ");
      return `<label class="fam-modo"><input type="radio" name="modo" value="${v}" ${v === f.modo ? "checked" : ""} ${f.pode_configurar ? "" : "disabled"}>
        <span><strong>${esc(titulo)}</strong><small>${esc(desc || "")}</small></span></label>`;
    }).join("");
    $("#fam-pesos").innerHTML = f.pessoas.map(p => `<label>${esc(p.nome)} (%) <input type="number" min="0" max="100" step="1"
      data-peso="${p.id}" value="${f.pesos[p.id] ?? Math.round(100 / f.pessoas.length)}" ${f.pode_configurar ? "" : "disabled"}></label>`).join("");
    $("#fam-pesos").classList.toggle("oculto", f.modo !== "personalizado");
    $("#btn-fam-salvar").classList.toggle("oculto", !f.pode_configurar);
    $("#fam-dica-config").textContent = f.pode_configurar ? "" : "Só o administrador muda a forma de dividir.";
  }
  $("#form-familia").addEventListener("change", ev => {
    if (ev.target.name === "modo") $("#fam-pesos").classList.toggle("oculto", ev.target.value !== "personalizado");
  });
  $("#form-familia").addEventListener("submit", async ev => {
    ev.preventDefault();
    const modo = ev.target.querySelector("input[name=modo]:checked")?.value;
    const pesos = {};
    document.querySelectorAll("[data-peso]").forEach(i => (pesos[i.dataset.peso] = i.value));
    try { await api("/api/plan/familia", { method: "PUT", body: { modo, pesos } }); toast("Forma de dividir salva."); carregarFamilia(); }
    catch (e) { toast(e.message, true); }
  });

  window.ABAS_MODULOS = { ...(window.ABAS_MODULOS || {}), "plan-resumo": carregarResumo, "plan-lancamentos": carregarLancamentos,
    "plan-orcamento": carregarOrcamento, "plan-objetivos": carregarObjetivos, "plan-familia": carregarFamilia };
})();
