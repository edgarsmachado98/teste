// Módulo adicional: Planejamento financeiro (carregado só quando o módulo está ativo na licença).
// Usa as funções do app base (api, brl, esc, grafico, toast...).
(function () {
  // a página veio de uma versão anterior do programa (servidor não reiniciado após a atualização)
  if (!document.getElementById("painel-nfce") || !document.getElementById("pilulas-forma")) {
    if (typeof avisoReiniciar === "function") avisoReiniciar();
    return;
  }
  const hojeLocal = () => new Date().toLocaleDateString("sv-SE");
  let mesPlan = hojeLocal().slice(0, 7);
  let categoriasPlan = [], formasPlan = {}, dadosLanc = null, tipoForm = "despesa", cartoesPlan = [], previaFatura = null;
  let membroRecemCadastrado = null;
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
       "plan-familia": carregarFamilia, "plan-cartao": carregarCartaoPagina, "plan-cartoes": carregarCartoesResumo }[aba] || (() => {}))();
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
    if (USUARIO.admin) html += `<button type="button" class="pilula-nova" data-novo-membro title="Cadastrar filhos, cônjuge, pais…">+ Cadastrar membro</button>`;
    $("#pilulas-titular").innerHTML = html;
    $("#ajuda-titular").textContent = receita
      ? (pessoasPlan.length > 1 ? "“Grupo familiar”: renda que é da família toda (ex.: aluguel recebido)." : "")
      : "Quem fez o pagamento. Despesas da casa podem ser marcadas como compartilhadas abaixo.";
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
    f.querySelector("[data-rotulo-titular]").textContent = receita ? "Para quem é esta receita" : "Quem pagou";
    f.descricao.placeholder = receita ? "Ex.: Salário — Empresa X" : "Ex.: Supermercado";
    $("#btn-plan-salvar").textContent = editando ? "Salvar alterações" : receita ? "Salvar receita" : "Salvar despesa";
    renderPilulasCategoria();
    atualizarResumoForm();
  }

  function atualizarResumoForm() {
    const f = $("#form-plan"), receita = tipoForm === "receita";
    const valor = lerMoeda(f.valor.value) || 0, cat = catPorId(+f.categoria_id.value);
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
  $("#btn-plan-cancelar").addEventListener("click", () => { limparForm(); fecharGaveta(); });

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
      else {
        try { await api("/api/plan/lancamentos", { method: "POST", body }); }
        catch (e) {
          if (!e.dados?.duplicado || !confirm(e.message + "\n\nLançar mesmo assim?")) throw e.dados?.duplicado ? new Error("Lançamento não repetido.") : e;
          await api("/api/plan/lancamentos", { method: "POST", body: { ...body, confirmar_duplicado: true } });
        }
      }
      const p = pessoasPlan.find(x => String(x.id) === String(titular));
      const praQuem = grupo ? " para o grupo familiar" : p && pessoasPlan.length > 1 ? ` para ${p.nome.split(" ")[0]}` : "";
      toast((id ? "Lançamento atualizado" : body.repetir === "mensal" ? `${tipoForm === "receita" ? "Receita" : "Conta"} fixa criada` :
        body.repetir === "parcelado" ? `Compra lançada em ${d.parcelas} parcelas` : `${tipoForm === "receita" ? "Receita" : "Despesa"} lançada`) + praQuem + ".");
      const filtroPessoa = $("#plan-pessoa").value;
      if (filtroPessoa && titular && String(titular) !== filtroPessoa) $("#plan-pessoa").value = "";  // não some da lista
      const manterData = f.data.value;
      limparForm();
      if (!id) { f.data.value = manterData; atualizarResumoForm(); }
      fecharGaveta();
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
    if ($("#painel-fatura").closest("#cartao-importar")) $("#plan-guardados").appendChild($("#painel-fatura"));
    try {
      await garantirCategorias();
      const pessoa = $("#plan-pessoa").value;
      [dadosLanc] = await Promise.all([api(`/api/plan/lancamentos?mes=${mesPlan}${pessoa ? `&pessoa=${pessoa}` : ""}`), carregarCartoes()]);
    } catch (e) { return toast(e.message, true); }
    pessoasPlan = dadosLanc.pessoas || [];
    const selP = $("#plan-pessoa"), atualP = selP.value;
    selP.innerHTML = `<option value="">Toda a família</option>` + pessoasPlan.map(p => `<option value="${p.id}">${esc(p.nome)}</option>`).join("");
    selP.value = pessoasPlan.some(p => String(p.id) === atualP) ? atualP : "";
    selP.classList.toggle("oculto", pessoasPlan.length < 2);
    document.body.classList.toggle("plan-sem-edicao", !pessoasPlan.some(p => p.editar));
    // primeiro acesso do administrador: convida a cadastrar os membros da família
    $("#aviso-membros").classList.toggle("oculto", !USUARIO.admin || pessoasPlan.some(p => p.cadastrado));
    if (membroRecemCadastrado) {  // cadastrou alguém no meio do lançamento: mantém o que foi digitado e já seleciona
      const sel = valorRadio("titular");
      renderTitulares(membroRecemCadastrado.id, false);
      if (sel === "grupo") renderTitulares(null, true);
      membroRecemCadastrado = null;
      atualizarResumoForm();
    } else if (!$("#form-plan").id.value) limparForm();
    renderLancamentos();
  }

  let filtroPlan = "";
  const DIAS_SEMANA = ["domingo", "segunda", "terça", "quarta", "quinta", "sexta", "sábado"];
  const CORES_CAT = ["#e7f3ec", "#fdf0dd", "#e8eefb", "#f1e8fb", "#fbe9ec", "#e6f4f7", "#f3f1e2"];
  function rotuloDia(iso) {
    const d = new Date(iso + "T12:00:00"), hoje = hojeLocal();
    const txt = `${DIAS_SEMANA[d.getDay()]}, ${d.getDate()} de ${d.toLocaleDateString("pt-BR", { month: "long" })}`;
    return iso === hoje ? `Hoje · ${txt}` : txt;
  }
  const iniciaisNome = n => (n || "?").trim().split(/\s+/).filter(p => p.length > 2).slice(0, 2).map(p => p[0]).join("").toUpperCase() || (n || "?")[0].toUpperCase();

  function renderLancamentos() {
    const todos = dadosLanc.lancamentos, busca = ($("#plan-busca").value || "").trim().toLowerCase();
    const nomePessoa = cid => pessoasPlan.find(p => p.id === cid)?.nome || "";
    const minhas = new Set(dadosLanc.minhas || []), junto = dadosLanc.modo_familia === "junto";
    const minhaParte = l => (l.partes || []).find(p => minhas.has(p.id))?.valor;
    const podeEditar = cid => pessoasPlan.some(p => p.id === cid && p.editar);
    const nomeCartao = id => cartoesPlan.find(c => c.id === id)?.nome;
    // números do mês (contas da família pagas por outro membro entram só pela sua parte)
    const meus = todos.filter(l => !l.alheio);
    const recs_ = meus.filter(l => l.tipo === "receita"), desps = meus.filter(l => l.tipo === "despesa");
    const rec = recs_.reduce((a, l) => a + l.valor, 0), desp = desps.reduce((a, l) => a + l.valor, 0);
    const recebido = recs_.filter(l => l.pago).reduce((a, l) => a + l.valor, 0);
    const aPagar = desps.filter(l => !l.pago).reduce((a, l) => a + l.valor, 0);
    const parte = todos.filter(l => l.partes).reduce((a, l) => a + (minhaParte(l) || 0), 0);
    const noCartao = desps.filter(l => l.cartao_id), qtdCartoes = new Set(noCartao.map(l => l.cartao_id)).size;
    const saldo = rec - desp;
    $("#plan-kpis").innerHTML = [
      ["Receitas", `<span class="pos">${brl.format(rec)}</span>`, `${recs_.length} entrada(s)${rec ? ` · ${Math.round(recebido / rec * 100)}% recebido` : ""}`],
      ["Despesas", brl.format(desp), `${desps.length} lançamento(s)${aPagar ? ` · ${brl.format(aPagar)} a pagar` : ""}`],
      ["Saldo do mês", `<span class="${saldo >= 0 ? "pos" : "neg"}">${brl.format(saldo)}</span>`, rec ? `${Math.round(saldo / rec * 100)}% da renda livre${parte ? ` · sua parte na família ${brl.format(parte)}` : ""}` : "sem receitas lançadas"],
      ["No cartão", brl.format(noCartao.reduce((a, l) => a + l.valor, 0)), qtdCartoes ? `${qtdCartoes} cartão(ões) no mês` : "nenhuma compra no crédito"],
    ].map(([r, v, sub]) => `<div class="card"><div class="rotulo">${r}</div><div class="valor">${v}</div><small class="var-sub">${sub}</small></div>`).join("");
    $("#plan-nota-modo").textContent = junto ? "Tudo junto: receitas, faturas e contas de quem divide as contas aparecem juntas." : "";

    const lista = todos.filter(l => {
      if (filtroPlan === "pendente" ? l.pago || l.projetado : filtroPlan === "cartao" ? !l.cartao_id : filtroPlan && l.tipo !== filtroPlan) return false;
      if (!busca) return true;
      return [l.descricao, nomeCat(l.categoria_id), nomePessoa(l.carteira_id), nomeCartao(l.cartao_id) || ""].join(" ").toLowerCase().includes(busca);
    });
    // agrupado por dia, do mais recente para o mais antigo
    const dias = {};
    lista.forEach(l => (dias[l.data] ||= []).push(l));
    const coresCat = {};
    let ci = 0;
    $("#lista-plan").innerHTML = lista.length ? Object.keys(dias).sort().reverse().map(dia => {
      const itens = dias[dia];
      const totalDia = itens.filter(l => !l.alheio).reduce((a, l) => a + (l.tipo === "receita" ? l.valor : -l.valor), 0);
      return `<div class="dia-cab"><span>${rotuloDia(dia)}</span><span class="${totalDia > 0 ? "pos" : ""}">${totalDia > 0 ? "+" : totalDia < 0 ? "−" : ""}${brl.format(Math.abs(totalDia))}</span></div>` +
        itens.map(l => {
          const cat = catPorId(l.categoria_id), nomeC = cat ? cat.nome : "Sem categoria";
          const cor = coresCat[nomeC] ||= CORES_CAT[ci++ % CORES_CAT.length];
          const aguardando = l.tipo === "despesa" && l.cartao_id && !l.chave_import && !l.projetado;
          const selos = [l.recorrencia_id ? "mensal" : "", l.parcela_total ? `${l.parcela_num}/${l.parcela_total}` : "",
            l.familia ? (junto ? "caixa comum" : "conta da família") : l.compartilhado ? (l.tipo === "receita" ? "grupo familiar" : "compartilhada") : "",
            aguardando ? "aguardando fatura" : "", l.conferido_em ? "✓ conferida" : "", l.projetado ? "previsto" : ""]
            .filter(Boolean).map(x => `<span class="selo">${x}</span>`).join("");
          const quem = l.tipo === "receita" && l.compartilhado ? "Grupo familiar" : nomePessoa(l.carteira_id);
          const pagamento = nomeCartao(l.cartao_id) || formasPlan[l.forma] || "";
          const situacao = l.projetado ? `<small>previsto</small>`
            : l.pago ? (l.tipo === "receita" ? `<small>recebido</small>` : "")
            : podeEditar(l.carteira_id) ? `<small class="neg">${l.tipo === "receita" ? "a receber" : "a pagar"} · <button type="button" class="link acao" data-pagar="${l.id}">marcar ${l.tipo === "receita" ? "recebido" : "pago"}</button></small>`
            : `<small class="neg">${l.tipo === "receita" ? "a receber" : "a pagar"}</small>`;
          const parteTxt = l.partes ? `<small class="parte-familia" title="${esc(l.partes.map(p => `${p.nome}: ${brl.format(p.valor)}`).join(" · "))}">${
            minhaParte(l) != null ? `sua parte ${brl.format(minhaParte(l))}` : l.partes.map(p => `${esc(p.nome.split(" ")[0])} ${brl.format(p.valor)}`).join(" · ")}</small>` : "";
          const menu = !l.projetado && podeEditar(l.carteira_id);
          return `<div class="lanc-item ${l.projetado ? "desativado" : ""}">
            <span class="lanc-ic" style="background:${cor}">${esc(nomeC[0] || "?")}</span>
            <div class="lanc-desc-item"><strong>${esc(l.descricao)}</strong>${selos}${l.nota_id ? `<button type="button" class="selo selo-nota" data-ver-nota="${l.nota_id}" title="Ver os itens da nota">🧾 nota</button>` : ""}
              <small>${esc(nomeC)}${pagamento ? ` · ${esc(pagamento)}` : ""}${l.valor_bruto ? ` · bruto ${brl.format(l.valor_bruto)}` : ""}</small></div>
            <span class="lanc-quem">${pessoasPlan.length > 1 ? `<span class="av-mini">${esc(iniciaisNome(quem))}</span>${esc((quem || "").split(" ")[0])}` : ""}</span>
            <span class="lanc-valor-item ${l.tipo === "receita" ? "pos" : ""}">${l.tipo === "receita" ? "+" : "−"}${brl.format(l.valor)}${situacao}${parteTxt}</span>
            ${menu ? `<button type="button" class="btn-mais" data-menu-lanc="${l.id}" aria-label="Ações">⋯</button>` : `<span></span>`}
          </div>`;
        }).join("");
    }).join("") : `<p class="dica lista-vazia">${todos.length ? "Nenhum lançamento com este filtro." : "Nenhum lançamento neste mês. Use + Receita ou − Despesa para começar."}</p>`;

    const recs = dadosLanc.recorrencias, nomesP = pessoasPlan.length > 1;
    const ativa = r => !(r.fim && r.fim < dadosLanc.mes_atual);
    const tabelaFixas = (tipo, vazio) => {
      const lista = recs.filter(r => r.tipo === tipo);
      if (!lista.length) return `<tr><td class="dica">${vazio}</td></tr>`;
      const total = lista.filter(r => ativa(r) && !r.alheio).reduce((s, r) => s + r.valor, 0);
      const comPartes = lista.filter(r => ativa(r) && r.partes);
      const suaParte = comPartes.reduce((s, r) => s + (minhaParte(r) || 0), 0);
      return `<tr><th>Descrição</th>${nomesP ? `<th class="col-quem">${tipo === "receita" ? "Para quem" : "Quem paga"}</th>` : ""}<th class="col-dia">Dia</th><th class="col-valor">Valor</th><th class="col-periodo">Período</th><th class="col-acoes"></th></tr>` +
        lista.map(r => `<tr class="${ativa(r) ? "" : "desativado"}"><td><strong>${esc(r.descricao)}</strong><small class="var-sub">${esc(nomeCat(r.categoria_id))}${r.compartilhado ? (tipo === "receita" ? " · grupo familiar" : " · conta da família") : ""}</small></td>
          ${nomesP ? `<td>${tipo === "receita" && r.compartilhado ? "Grupo familiar" : esc(nomePessoa(r.carteira_id))}</td>` : ""}
          <td>${r.dia}</td><td class="${tipo === "receita" ? "pos" : ""}">${brl.format(r.valor)}${r.partes ? `<small class="var-sub parte-familia" title="${esc(r.partes.map(p => `${p.nome}: ${brl.format(p.valor)}`).join(" · "))}">${
            minhaParte(r) != null ? `sua parte ${brl.format(minhaParte(r))}` : r.partes.map(p => `${esc(p.nome.split(" ")[0])} ${brl.format(p.valor)}`).join(" · ")}</small>` : ""}</td>
          <td class="col-periodo">desde ${fmtData(r.inicio + "-01").slice(3)}${r.fim ? ` até ${fmtData(r.fim + "-01").slice(3)}` : ""}</td>
          <td>${!podeEditar(r.carteira_id) ? "" : `<span>${ativa(r) ? `<button class="link editar" data-editar-rec="${r.id}">editar</button><button class="link acao" data-plan-encerrar="${r.id}">encerrar</button>` : `<span class="dica">encerrada</span> `}<button class="link" data-excluir-rec="${r.id}" title="Lançada por engano: apaga todos os meses">excluir</button></span>`}</td></tr>`).join("") +
        `<tr class="linha-total"><td>Total por mês${lista.some(r => r.alheio) ? ` <small class="dica">(pagas por você)</small>` : ""}</td>${nomesP ? "<td></td>" : ""}<td></td><td class="${tipo === "receita" ? "pos" : ""}">${brl.format(total)}</td><td class="col-periodo"></td><td></td></tr>` +
        (suaParte ? `<tr class="linha-total"><td>Sua parte nas contas da família</td>${nomesP ? "<td></td>" : ""}<td></td><td>${brl.format(suaParte)}</td><td class="col-periodo"></td><td></td></tr>` : "");
    };
    $("#tabela-fixas-receitas").innerHTML = tabelaFixas("receita", "Nenhuma receita fixa. Ao lançar um salário, escolha a recorrência “Mensal”.");
    $("#tabela-fixas-despesas").innerHTML = tabelaFixas("despesa", "Nenhuma conta fixa. Ao lançar aluguel, escola, internet…, escolha “Mensal”.");
    // resumo das fixas na coluna da direita
    const lado = tipo => {
      const ativas = recs.filter(r => r.tipo === tipo && ativa(r));
      if (!ativas.length) return `<p class="dica">${tipo === "receita" ? "Nenhuma receita fixa. Lance o salário como “Mensal”." : "Nenhuma conta fixa. Lance aluguel, escola, internet… como “Mensal”."}</p>`;
      const mostrar = [...ativas].sort((a, b) => b.valor - a.valor).slice(0, 6);
      const total = ativas.filter(r => !r.alheio).reduce((a, r) => a + r.valor, 0);
      const parteFam = ativas.filter(r => r.partes).reduce((a, r) => a + (minhaParte(r) || 0), 0);
      return mostrar.map(r => {
        const ocorr = dadosLanc.lancamentos.find(l => l.recorrencia_id === r.id && !l.projetado);
        const pendente = ocorr && !ocorr.pago;
        const quem = tipo === "receita" && r.compartilhado ? "grupo familiar" : (nomesP ? nomePessoa(r.carteira_id).split(" ")[0] : "");
        return `<div class="fixa-linha"><span><b>${esc(r.descricao)}</b><small>dia ${r.dia}${quem ? ` · ${esc(quem)}` : ""}${pendente ? ` · <em class="neg">${tipo === "receita" ? "a receber" : "a pagar"}</em>` : ""}</small></span>
          <span class="${tipo === "receita" ? "pos" : pendente ? "neg" : ""}">${brl.format(r.valor)}</span></div>`;
      }).join("") + (ativas.length > mostrar.length ? `<button type="button" class="link acao mais-fixas" data-abrir-gaveta="plan-fixas">+ ${ativas.length - mostrar.length} outra(s)</button>` : "") +
        `<div class="fixa-total"><span>Total por mês</span><span class="${tipo === "receita" ? "pos" : ""}">${brl.format(total)}</span></div>` +
        (parteFam ? `<div class="fixa-total sub"><span>Sua parte na família</span><span>${brl.format(parteFam)}</span></div>` : "");
    };
    $("#lado-despesas").innerHTML = lado("despesa");
    $("#lado-receitas").innerHTML = lado("receita");
  }

  // ---------- janela lateral (formulário, nota fiscal, fatura e fixas) ----------
  document.body.insertAdjacentHTML("beforeend", `<div class="gaveta-veu" id="gaveta-veu" hidden></div>
    <aside class="gaveta" id="gaveta" aria-hidden="true" role="dialog"><div class="gaveta-cab"><span id="gaveta-titulo"></span>
      <button type="button" class="btn-icone" id="gaveta-fechar" aria-label="Fechar"><svg class="icone" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg></button></div>
      <div class="gaveta-corpo" id="gaveta-corpo"></div></aside>`);
  const TITULOS_GAVETA = { "painel-nfce": "", "painel-fatura": "", "plan-fixas": "Receitas e contas fixas", "painel-plan-form": "" };
  function abrirGaveta(id) {
    fecharGaveta(true);
    const el = document.getElementById(id);
    if (!el) return;
    $("#gaveta-corpo").appendChild(el);
    $("#gaveta-titulo").textContent = TITULOS_GAVETA[id] || "";
    $("#gaveta").classList.add("aberta"); $("#gaveta").setAttribute("aria-hidden", "false");
    $("#gaveta-veu").hidden = false;
    document.body.classList.add("gaveta-aberta");
    if (id === "painel-fatura" && cartoesPlan.length && !$("#sel-cartao-fatura").value) $("#sel-cartao-fatura").value = cartoesPlan[0].id;
  }
  function fecharGaveta(trocando) {
    const el = $("#gaveta-corpo").firstElementChild;
    if (el) $("#plan-guardados").appendChild(el);
    if (trocando === true) return;
    $("#gaveta").classList.remove("aberta"); $("#gaveta").setAttribute("aria-hidden", "true");
    $("#gaveta-veu").hidden = true;
    document.body.classList.remove("gaveta-aberta");
  }
  $("#gaveta-fechar").addEventListener("click", () => fecharGaveta());
  $("#gaveta-veu").addEventListener("click", () => fecharGaveta());
  document.addEventListener("keydown", ev => {
    if (ev.key === "Escape" && $("#gaveta").classList.contains("aberta") && !document.querySelector("dialog[open]")) fecharGaveta();
  });
  document.addEventListener("click", ev => {
    const a = ev.target.closest("[data-abrir-gaveta]");
    if (a) { fecharMenuLanc(); abrirGaveta(a.dataset.abrirGaveta); return; }
    const n = ev.target.closest("[data-novo-lanc]");
    if (n) {
      limparForm();
      document.querySelector(`[data-plan-tipo="${n.dataset.novoLanc}"]`)?.click();
      abrirGaveta("painel-plan-form");
      setTimeout(() => $("#form-plan").valor.focus(), 50);
    }
  });

  // ---------- menu "⋯" de cada lançamento ----------
  function fecharMenuLanc() { $("#menu-lanc").classList.add("oculto"); }
  $("#menu-lanc").addEventListener("click", ev => { if (ev.target.closest("button")) setTimeout(fecharMenuLanc, 0); });
  document.body.appendChild($("#menu-lanc"));
  document.addEventListener("click", ev => {
    const b = ev.target.closest("[data-menu-lanc]");
    if (!b) { if (!ev.target.closest("#menu-lanc")) fecharMenuLanc(); return; }
    const l = dadosLanc.lancamentos.find(x => x.id === +b.dataset.menuLanc), m = $("#menu-lanc");
    m.innerHTML = `<button type="button" data-plan-editar="${l.id}">Editar</button>
      ${!l.pago ? `<button type="button" data-pagar="${l.id}">Marcar ${l.tipo === "receita" ? "recebido" : "pago"}</button>` : ""}
      ${l.nota_id ? `<button type="button" data-ver-nota="${l.nota_id}">Ver itens da nota</button>` : ""}
      ${l.conferido_em ? `<button type="button" data-desfazer-conf="${l.id}">Desfazer conferência</button>` : ""}
      <button type="button" class="perigo" data-plan-excluir="${l.id}">Excluir</button>`;
    const r = b.getBoundingClientRect();
    m.style.top = `${window.scrollY + r.bottom + 4}px`;
    m.style.left = `${Math.max(8, window.scrollX + r.right - 190)}px`;
    m.classList.remove("oculto");
  });
  $("#plan-chips").addEventListener("click", ev => {
    const b = ev.target.closest("[data-filtro]");
    if (!b) return;
    filtroPlan = b.dataset.filtro;
    $("#plan-chips").querySelectorAll("[data-filtro]").forEach(x => x.classList.toggle("ativo", x === b));
    renderLancamentos();
  });
  $("#plan-busca").addEventListener("input", () => renderLancamentos());
  $("#plan-pessoa").addEventListener("change", carregarLancamentos);

  document.addEventListener("click", async ev => {
    const er = ev.target.closest("[data-editar-rec]");
    if (er) {  // edita a ocorrência deste mês já marcando "aplicar aos próximos meses"
      const rid = +er.dataset.editarRec;
      const l = dadosLanc.lancamentos.find(x => x.recorrencia_id === rid && !x.projetado);
      if (!l) return toast("Vá até um mês em que este lançamento aparece para editá-lo.", true);
      editarLancamento(l.id);
      $("#form-plan").atualizar_proximos.checked = true;
      return;
    }
    const dc = ev.target.closest("[data-desfazer-conf]");
    if (dc) {
      if (!confirm("Desfazer a conferência? A compra continua lançada; ao importar a fatura de novo, a linha dela poderá ser conferida ou lançada.")) return;
      try { await api(`/api/plan/lancamentos/${dc.dataset.desfazerConf}/desfazer-conferencia`, { method: "POST" }); toast("Conferência desfeita."); carregarLancamentos(); }
      catch (e) { toast(e.message, true); }
      return;
    }
    const ed = ev.target.closest("[data-plan-editar]"), ex = ev.target.closest("[data-plan-excluir]"),
      enc = ev.target.closest("[data-plan-encerrar]");
    if (ed) editarLancamento(+ed.dataset.planEditar);
    function editarLancamento(id) {
      const l = dadosLanc.lancamentos.find(x => x.id === id), f = $("#form-plan");
      tipoForm = l.tipo;
      preencherCategorias(l.categoria_id);
      f.id.value = l.id; f.data.value = l.data; f.descricao.value = l.descricao; f.valor.value = fmtMoeda(l.valor);
      f.dataset.carteiraOriginal = l.carteira_id;
      f.valor_bruto.value = fmtMoeda(l.valor_bruto); f.pago.checked = !!l.pago;
      f.querySelectorAll('input[name="forma"]').forEach(r => (r.checked = r.value === (l.forma || "")));
      f.cartao_id.value = l.cartao_id || "";
      renderTitulares(l.carteira_id, l.tipo === "receita" && !!l.compartilhado);
      f.querySelector(`input[name="conta"][value="${l.compartilhado ? "familia" : "pessoal"}"]`).checked = true;
      f.atualizar_proximos.checked = false;
      f.querySelector(".campo-proximos").classList.toggle("oculto", !l.recorrencia_id);
      $("#plan-form-titulo").textContent = "Editar lançamento";
      $("#btn-plan-cancelar").classList.remove("oculto");
      ajustarForm();
      abrirGaveta("painel-plan-form");
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
    const exr = ev.target.closest("[data-excluir-rec]");
    if (exr) {
      const r = dadosLanc.recorrencias.find(x => x.id === +exr.dataset.excluirRec);
      if (!confirm(`Excluir “${r.descricao}” de vez? Apaga também os meses já lançados dela. Use quando foi lançada por engano (para parar só daqui para frente, use encerrar).`)) return;
      try {
        await api(`/api/plan/recorrencias/${r.id}?tudo=1`, { method: "DELETE" });
        toast(`“${r.descricao}” excluída.`);
        carregarLancamentos();
      } catch (e) { toast(e.message, true); }
      return;
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

  // ---------------- Nota fiscal (NFC-e) pelo QR Code ----------------
  let notasNfce = [], falhasNfce = [], promessaJsQR = null;

  function carregarJsQR() {
    return (promessaJsQR ||= new Promise((ok, falha) => {
      const s = document.createElement("script");
      s.src = "/static/vendor/jsQR.js";
      s.onload = () => ok(window.jsQR);
      s.onerror = () => { promessaJsQR = null; falha(new Error("jsQR")); };
      document.head.appendChild(s);
    }));
  }

  // lê o QR Code no próprio aparelho (a foto nem precisa ser enviada); se não achar, a foto vai para o servidor
  async function lerQrNoAparelho(arquivo) {
    let bmp;
    try { bmp = await createImageBitmap(arquivo, { imageOrientation: "from-image" }); } catch { return null; }
    if ("BarcodeDetector" in window) {
      try {
        const r = await new BarcodeDetector({ formats: ["qr_code"] }).detect(bmp);
        if (r[0]?.rawValue) return r[0].rawValue;
      } catch { /* sem suporte: segue com o jsQR */ }
    }
    let jsQR;
    try { jsQR = await carregarJsQR(); } catch { return null; }
    const tela = document.createElement("canvas"), g = tela.getContext("2d", { willReadFrequently: true });
    // [x, y, largura, altura] em fração da foto e o tamanho máximo do recorte
    for (const [fx, fy, fw, fh, alvo] of [[0, 0, 1, 1, 1200], [0, 0.45, 1, 0.55, 1500], [0, 0, 1, 1, 2000], [0, 0, 1, 1, 800]]) {
      const sw = bmp.width * fw, sh = bmp.height * fh, f = Math.min(1, alvo / Math.max(sw, sh));
      tela.width = Math.round(sw * f); tela.height = Math.round(sh * f);
      g.drawImage(bmp, bmp.width * fx, bmp.height * fy, sw, sh, 0, 0, tela.width, tela.height);
      const img = g.getImageData(0, 0, tela.width, tela.height);
      const r = jsQR(img.data, img.width, img.height, { inversionAttempts: "attemptBoth" });
      if (r?.data) return r.data;
    }
    return null;
  }

  // fotos do celular têm vários MB: reduz antes de enviar (o servidor tenta de novo com outro leitor)
  async function reduzirFoto(arquivo) {
    try {
      const bmp = await createImageBitmap(arquivo, { imageOrientation: "from-image" });
      const f = Math.min(1, 2600 / Math.max(bmp.width, bmp.height));
      const tela = document.createElement("canvas");
      tela.width = Math.round(bmp.width * f); tela.height = Math.round(bmp.height * f);
      tela.getContext("2d").drawImage(bmp, 0, 0, tela.width, tela.height);
      const blob = await new Promise(ok => tela.toBlob(ok, "image/jpeg", 0.9));
      return blob || arquivo;
    } catch { return arquivo; }
  }

  async function lerNotas(arquivos, textos = []) {
    if (!arquivos.length && !textos.length) return;
    const destino = $("#previa-nfce");
    const status = document.createElement("p");
    status.className = "dica nfce-lendo";
    status.textContent = arquivos.length ? `Procurando o QR Code em ${arquivos.length} foto(s)…` : "Consultando a nota na Sefaz…";
    destino.prepend(status);
    const fd = new FormData();
    textos.forEach(t => fd.append("texto", t));
    for (const a of arquivos) {
      const t = await lerQrNoAparelho(a);
      if (t) fd.append("texto", t);
      else fd.append("foto", await reduzirFoto(a), a.name || "foto.jpg");
    }
    status.textContent = "Consultando a nota na Sefaz…";
    try {
      await garantirCategorias();
      if (!cartoesPlan.length) await carregarCartoes().catch(() => {});
      const r = await fetch("/api/plan/nfce/ler", { method: "POST", body: fd,
        headers: { "X-Requested-With": "fetch", "X-Carteira": String(carteiraAtual) } });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(j.erro || `Erro ${r.status}`);
      const chaves = new Set(notasNfce.map(n => n.chave));
      j.notas.filter(n => !chaves.has(n.chave)).forEach(n => {
        n.pagamentos = n.pagamentos.length ? n.pagamentos : [{ forma: null, valor: n.total }];
        if (n.pagamentos.length === 1 && n.pagamentos[0].valor == null) n.pagamentos[0].valor = n.total;
        notasNfce.push(n);
      });
      falhasNfce = j.falhas;
      renderNotas();
      if (j.notas.length) toast(`${j.notas.length} nota(s) lida(s). Confira e clique em Lançar.`);
    } catch (e) { toast(e.message, true); }
    finally { status.remove(); }
  }

  function opcoesForma(sel) {
    return `<option value="">Forma de pagamento…</option>` + Object.entries(formasPlan).map(([v, n]) =>
      `<option value="${v}" ${v === sel ? "selected" : ""}>${esc(n)}</option>`).join("");
  }

  function linhaPagamento(p, k, j) {
    const cartaoUnico = cartoesPlan.length === 1 ? cartoesPlan[0].id : null;
    return `<div class="nfce-pag" data-pag="${j}">
      <select data-campo="forma" aria-label="Forma de pagamento">${opcoesForma(p.forma)}</select>
      <label class="nfce-valor"><span>R$</span><input data-campo="valor" inputmode="decimal" data-moeda value="${fmtMoeda(p.valor)}" aria-label="Valor"></label>
      <select data-campo="cartao_id" class="${p.forma === "credito" ? "" : "oculto"}" aria-label="Cartão">
        <option value="">${cartoesPlan.length ? "Qual cartão?" : "Cadastre o cartão na fatura abaixo"}</option>
        ${cartoesPlan.map(c => `<option value="${c.id}" ${c.id === (p.cartao_id || cartaoUnico) ? "selected" : ""}>${esc(c.nome)}</option>`).join("")}</select>
      ${p.forma_texto && !p.forma ? `<small class="dica">no cupom: ${esc(p.forma_texto)}</small>` : ""}
      ${j > 0 ? `<button type="button" class="link" data-nfce-tirar-pag="${k}:${j}">remover</button>` : ""}
    </div>`;
  }

  function renderNotas() {
    const ed = pessoasPlan.filter(p => p.editar);
    const minha = (ed.find(p => p.id === carteiraAtual) || ed.find(p => p.minha) || ed[0])?.id;
    $("#previa-nfce").innerHTML = (falhasNfce.length ? `<div class="aviso nfce-falhas">${falhasNfce.map(f =>
        `<div><strong>${esc(f.origem)}</strong>: ${esc(f.motivo)}</div>`).join("")}</div>` : "") +
      notasNfce.map((n, k) => {
        const credito = n.pagamentos.some(p => p.forma === "credito");
        const comb = n.combustivel;
        return `<div class="nfce-card" data-nfce="${k}">
          <div class="nfce-topo">
            <div><strong>${esc(n.descricao)}</strong>
              <small class="var-sub">${n.cnpj_formatado ? `CNPJ ${esc(n.cnpj_formatado)} · ` : ""}${esc(n.uf)} · cupom nº ${n.numero}${n.data ? ` · ${fmtData(n.data.slice(0, 10))}${n.data.length > 10 ? " às " + n.data.slice(11, 16) : ""}` : ""}</small></div>
            <div class="nfce-total">${n.total != null ? brl.format(n.total) : "valor a conferir"}
              ${n.desconto ? `<small class="var-sub pos">desconto de ${brl.format(n.desconto)}</small>` : ""}</div>
          </div>
          ${n.ja_lancada ? `<p class="aviso">Esta nota já foi lançada${n.ja_lancada.data ? ` (${fmtData(n.ja_lancada.data)})` : ""}. Lançar de novo vai duplicar a despesa.</p>` : ""}
          ${n.aviso ? `<p class="aviso nfce-aviso">${esc(n.aviso)}</p>` : ""}
          ${comb ? `<p class="dica nfce-comb">⛽ ${String(comb.litros).replace(".", ",")} L de ${esc(comb.produto.toLowerCase())} a ${brl.format(comb.preco_litro)}/L</p>` : ""}
          <div class="nfce-campos">
            <label>Descrição <input data-campo="descricao" value="${esc(n.descricao)}" maxlength="120"></label>
            <label>Data <input type="date" data-campo="data" value="${(n.data || hojeLocal()).slice(0, 10)}"></label>
            <label>Categoria <select data-campo="categoria_id" class="${n.categoria_id ? "" : "sem-categoria"}">${opcoesCategoria("despesa", n.categoria_id)}</select>
              ${n.origem_categoria ? `<small class="var-sub">${n.origem_categoria === "aprendida" ? "como da última vez nesta loja" : "sugestão automática"}</small>` : ""}</label>
            ${ed.length > 1 ? `<label>Quem pagou <select data-campo="carteira_id">${ed.map(p =>
              `<option value="${p.id}" ${p.id === minha ? "selected" : ""}>${esc(p.nome)}</option>`).join("")}</select></label>` : ""}
          </div>
          ${pessoasPlan.length > 1 ? `<label class="check nfce-familia"><input type="checkbox" data-campo="compartilhado"> Conta da família (entra na divisão do casal)</label>` : ""}
          <div class="nfce-pagamentos"><span class="rotulo-campo">Pagamento</span>
            ${n.pagamentos.map((p, j) => linhaPagamento(p, k, j)).join("")}
            <button type="button" class="link acao" data-nfce-mais-pag="${k}">+ pagou com mais de uma forma</button>
          </div>
          ${credito ? `<p class="dica nfce-credito">A parte no crédito fica <strong>aguardando a fatura</strong>; ao importar a fatura do cartão, o sistema confere e não lança de novo.</p>` : ""}
          ${n.itens.length ? `<details class="nfce-itens"><summary>Ver os ${n.itens.length} itens</summary>${tabelaItens(n.itens)}</details>` : ""}
          <div class="nfce-acoes">
            <button type="button" class="btn" data-nfce-lancar="${k}">Lançar despesa</button>
            <button type="button" class="link" data-nfce-descartar="${k}">descartar</button>
          </div>
        </div>`;
      }).join("");
  }

  function tabelaItens(itens) {
    return `<div class="rolagem"><table class="tabela-itens-nota"><tr><th>Produto</th><th>Qtde.</th><th>Unitário</th><th>Total</th></tr>
      ${itens.map(i => `<tr><td>${esc(i.descricao)}</td><td>${i.qtd != null ? String(i.qtd).replace(".", ",") : ""} ${esc(i.un || "")}</td>
        <td>${i.unitario != null ? brl.format(i.unitario) : ""}</td><td>${i.valor != null ? brl.format(i.valor) : ""}</td></tr>`).join("")}</table></div>`;
  }

  // guarda o que foi digitado antes de redesenhar os cartões
  function lerCard(k) {
    const card = $(`[data-nfce="${k}"]`), n = notasNfce[k];
    if (!card) return n;
    const campo = c => card.querySelector(`.nfce-campos [data-campo="${c}"], .nfce-familia [data-campo="${c}"]`);
    n.descricao = campo("descricao").value;
    n.data_lanc = campo("data").value;
    n.categoria_id = +campo("categoria_id").value || null;
    n.carteira_id = campo("carteira_id") ? +campo("carteira_id").value : null;
    n.compartilhado = campo("compartilhado") ? campo("compartilhado").checked : false;
    n.pagamentos = [...card.querySelectorAll(".nfce-pag")].map((el, j) => ({
      ...n.pagamentos[j], forma: el.querySelector('[data-campo="forma"]').value || null,
      valor: el.querySelector('[data-campo="valor"]').value, cartao_id: +el.querySelector('[data-campo="cartao_id"]').value || null }));
    return n;
  }
  const lerTodos = () => notasNfce.forEach((_, k) => lerCard(k));

  $("#btn-foto-nfce").addEventListener("click", () => $("#foto-nfce").click());
  $("#foto-nfce").addEventListener("change", ev => { const fs = [...ev.target.files]; ev.target.value = ""; lerTodos(); lerNotas(fs); });
  $("#form-nfce-texto").addEventListener("submit", ev => {
    ev.preventDefault();
    const t = ev.target.texto.value.trim();
    if (!t) return toast("Cole o link do QR Code ou a chave da nota.", true);
    ev.target.reset();
    lerTodos();
    lerNotas([], [t]);
  });
  $("#painel-nfce").addEventListener("change", ev => {
    const card = ev.target.closest("[data-nfce]");
    if (!card) return;
    if (ev.target.dataset.campo === "forma") {
      const k = +card.dataset.nfce;
      lerTodos();
      renderNotas();
      if (ev.target.value === "credito") $(`[data-nfce="${k}"] .nfce-pag [data-campo="cartao_id"]:not(.oculto)`)?.focus();
    }
    if (ev.target.dataset.campo === "categoria_id") ev.target.classList.toggle("sem-categoria", !ev.target.value);
  });
  $("#painel-nfce").addEventListener("click", async ev => {
    const mais = ev.target.closest("[data-nfce-mais-pag]"), tirar = ev.target.closest("[data-nfce-tirar-pag]");
    const desc = ev.target.closest("[data-nfce-descartar]"), lancar = ev.target.closest("[data-nfce-lancar]");
    if (mais) {
      lerTodos();
      const n = notasNfce[+mais.dataset.nfceMaisPag];
      const pago = n.pagamentos.reduce((s, p) => s + (lerMoeda(p.valor) || 0), 0);
      n.pagamentos.push({ forma: null, valor: n.total ? Math.max(0, +(n.total - pago).toFixed(2)) || null : null });
      renderNotas();
    } else if (tirar) {
      lerTodos();
      const [k, j] = tirar.dataset.nfceTirarPag.split(":").map(Number);
      notasNfce[k].pagamentos.splice(j, 1);
      renderNotas();
    } else if (desc) {
      lerTodos();
      notasNfce.splice(+desc.dataset.nfceDescartar, 1);
      renderNotas();
    } else if (lancar) {
      const k = +lancar.dataset.nfceLancar;
      lerTodos();
      const n = notasNfce[k];
      if (n.pagamentos.some(p => !p.forma)) return toast("Escolha a forma de pagamento.", true);
      if (n.pagamentos.some(p => p.forma === "credito" && !p.cartao_id))
        return toast(cartoesPlan.length ? "Escolha o cartão de crédito usado." : "Cadastre o cartão em “Importar fatura do cartão” para lançar a compra no crédito.", true);
      if (n.ja_lancada && !confirm("Esta nota já foi lançada. Lançar de novo mesmo assim?")) return;
      lancar.disabled = true;
      try {
        const r = await api("/api/plan/nfce/confirmar", { method: "POST", body: {
          chave: n.chave, url: n.url, emitente: n.emitente, cnpj: n.cnpj, emissao: n.data, total: n.total, itens: n.itens,
          descricao: n.descricao, data: n.data_lanc, categoria_id: n.categoria_id, carteira_id: n.carteira_id,
          compartilhado: n.compartilhado, pagamentos: n.pagamentos, forcar: !!n.ja_lancada } });
        notasNfce.splice(k, 1);
        renderNotas();
        if (!notasNfce.length && $("#painel-nfce").closest("#gaveta")) fecharGaveta();
        toast(`Despesa lançada: ${n.descricao}` + (r.aguardando_fatura ? " (a parte no crédito aguarda a fatura)" : "") + ".");
        carregarLancamentos();
      } catch (e) { lancar.disabled = false; toast(e.message, true); }
    }
  });
  // arrastar fotos para o quadro também funciona no computador
  $("#painel-nfce").addEventListener("dragover", ev => { ev.preventDefault(); });
  $("#painel-nfce").addEventListener("drop", ev => {
    ev.preventDefault();
    const fs = [...ev.dataTransfer.files].filter(f => f.type.startsWith("image/"));
    if (fs.length) { lerTodos(); lerNotas(fs); }
  });

  // itens da nota na lista de lançamentos
  document.addEventListener("click", async ev => {
    const b = ev.target.closest("[data-ver-nota]");
    if (!b) return;
    const tr = b.closest("tr"), prox = tr.nextElementSibling;
    if (prox?.classList.contains("linha-itens-nota")) return prox.remove();
    try {
      const n = await api(`/api/plan/notas/${b.dataset.verNota}`);
      tr.insertAdjacentHTML("afterend", `<tr class="linha-itens-nota"><td colspan="${tr.children.length}">
        <div class="dica">${esc(n.emitente || "")}${n.cnpj_formatado ? ` · CNPJ ${esc(n.cnpj_formatado)}` : ""}${n.total ? ` · total ${brl.format(n.total)}` : ""}
          ${n.url ? ` · <a href="${esc(n.url)}" target="_blank" rel="noopener">ver na Sefaz</a>` : ""}</div>
        ${n.itens.length ? tabelaItens(n.itens) : `<p class="dica">O portal não mostrou os itens desta nota.</p>`}</td></tr>`);
    } catch (e) { toast(e.message, true); }
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
    renderNavCartoes();
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
            ${i.ja_importado ? `<span class="selo">já importado</span>` : ""}${i.antecipada ? `<span class="selo">antecipada</span>` : ""}${i.portador && new Set(previaFatura.itens.map(x => x.portador).filter(Boolean)).size > 1 ? `<small class="var-sub">${esc(i.portador)}${i.final ? ` · final ${esc(i.final)}` : ""}</small>` : ""}</td>
          <td class="${i.tipo === "estorno" ? "pos" : ""}">${i.tipo === "estorno" ? "+" : ""}${brl.format(i.valor)}</td>
          <td>${i.tipo === "pagamento" ? `<span class="dica">ignorado</span>` : `<select data-fatura-cat="${n}" class="${i.categoria_id ? "" : "sem-categoria"}">
              ${opcoesCategoria(i.tipo === "estorno" ? "receita" : "despesa", i.categoria_id)}</select>
            ${i.origem_categoria ? `<small class="var-sub">${{ aprendida: "como da última vez", sua: "a que você escolheu", padrao: "sugestão automática", banco: "categoria do banco" }[i.origem_categoria] || ""}</small>` : ""}`}</td>
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
    if (i.antecipar) return `<span class="sit-ok">Parcela antecipada</span><small class="var-sub">sai de ${fmtData(i.antecipar).slice(3)} e entra nesta fatura</small>`;
    if (i.antecipada) return `<span class="dica">parcela antecipada</span>`;
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
      toast(`Fatura importada: ${r.lancamentos} lançamento(s) novo(s)` + (r.conferidos ? `, ${r.conferidos} conferido(s) com o que você já tinha lançado` : "") + (r.antecipadas ? `, ${r.antecipadas} parcela(s) antecipada(s) trazida(s) para este mês` : "") +
        (r.parcelas_futuras ? `, ${r.parcelas_futuras} parcela(s) futura(s)` : "") +
        (r.regras_aprendidas ? `. ${r.regras_aprendidas} categoria(s) aprendida(s) para as próximas faturas.` : "."));
      previaFatura = null;
      $("#previa-fatura").innerHTML = "";
      escolherArquivoFatura(null);
      if ($("#painel-fatura").closest("#gaveta")) fecharGaveta();
      recarregar();
    } catch (e) { toast(e.message, true); }
  });

  document.addEventListener("click", async ev => {
    const b = ev.target.closest("[data-remover-cartao]");
    if (!b || !confirm("Remover este cartão? Os lançamentos já feitos continuam.")) return;
    try { await api(`/api/plan/cartoes/${b.dataset.removerCartao}`, { method: "DELETE" }); await carregarCartoes(); }
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
      "idade_alvo", "meses_reserva", "prioridade"].forEach(k => { f[k].value = f[k].dataset.moeda !== undefined ? fmtMoeda(o[k]) : o[k] ?? ""; });
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
  const iniciais = nome => nome.trim().split(/\s+/).filter(p => p.length > 2 || p === p.toUpperCase()).slice(0, 2)
    .map(p => p[0]).join("").toUpperCase() || nome.slice(0, 1).toUpperCase();
  async function carregarMembros() {
    dadosMembros = await api("/api/plan/membros");
    const m = dadosMembros, pode = m.pode_configurar;
    document.querySelectorAll(".plan-admin").forEach(e => e.classList.toggle("oculto", !pode));
    $("#lista-membros").innerHTML = m.membros.map(p => `
      <div class="membro-card">
        <span class="membro-avatar par-${esc(p.parentesco)}">${esc(iniciais(p.nome))}</span>
        <div class="membro-info">
          <strong>${esc(p.nome)} ${p.minha ? `<span class="selo">você</span>` : ""}</strong>
          <small>${esc(m.parentescos[p.parentesco] || "Outro")}${p.idade != null ? ` · ${p.idade} ${p.idade === 1 ? "ano" : "anos"}` : ""}</small>
          <small class="membro-tags">
            <span class="${p.divide ? "pos" : ""}">${p.divide ? "divide as contas" : "não entra na divisão"}</span> ·
            <span>${p.tem_login ? `login: ${esc(p.login || p.carteira)}` : "sem acesso ao sistema"}</span></small>
        </div>
        ${pode ? `<button type="button" class="link acao" data-editar-membro="${p.id}">editar</button>` : ""}
      </div>`).join("");
    const minha = m.membros.find(p => p.minha);
    $("#dica-membros").innerHTML = !pode ? "Só o administrador altera os membros da família."
      : minha && minha.login && minha.parentesco !== "titular" && minha.nome.split(" ")[0] !== minha.login.split(" ")[0] && !avisoNomeDispensado(minha)
        ? `<span class="neg">Atenção:</span> o cadastro ligado ao seu login (${esc(minha.login)}) está com o nome <strong>${esc(minha.nome)}</strong>. Se foi engano, clique em editar e corrija; para cadastrar outra pessoa use “Cadastrar membro”.
           <button type="button" class="link acao" data-editar-membro="${minha.id}">Corrigir</button>
           <button type="button" class="link" data-dispensar-nome="${minha.id}:${esc(minha.nome)}">Está certo assim</button>`
        : !m.configurado ? "Confira o seu cadastro e cadastre os demais membros da família. Para dar login a alguém, use Acessos e conta → Usuários." : "";
  }

  // o cadastro abre também a partir do lançamento: o diálogo não pode ficar dentro da aba Família (oculta)
  document.body.appendChild($("#dialogo-membro"));
  function avisoNomeDispensado(m) {
    try { return localStorage.getItem("aviso-nome-membro") === `${m.id}:${m.nome}`; } catch { return false; }
  }
  document.addEventListener("click", ev => {
    const b = ev.target.closest("[data-dispensar-nome]");
    if (!b) return;
    try { localStorage.setItem("aviso-nome-membro", b.dataset.dispensarNome); } catch { /* sem armazenamento */ }
    $("#dica-membros").textContent = "";
  });
  function abrirMembro(p) {
    const f = $("#form-membro"), m = dadosMembros;
    f.reset();
    f.parentesco.innerHTML = Object.entries(m.parentescos).map(([v, n]) => `<option value="${v}">${esc(n)}</option>`).join("");
    f.id.value = p?.id || "";
    f.nome.value = p?.nome || "";
    f.parentesco.value = p?.parentesco || (m.membros.some(x => x.parentesco === "conjuge") ? "filho" : "conjuge");
    f.nascimento.value = p?.nascimento || "";
    f.divide.checked = p ? p.divide : f.parentesco.value === "conjuge";
    $("#titulo-membro").textContent = p ? "Editar membro da família" : "Cadastrar membro da família";
    $("#sub-membro").textContent = p ? (p.minha ? "Este é o seu cadastro." : "")
      : "Filhos, pais e quem não usa o sistema também podem ser cadastrados.";
    $("#login-membro").textContent = p?.tem_login ? `Acessa o sistema com o login de ${p.login || p.carteira}. Para mudar o acesso, use Acessos e conta.`
      : p ? "Não tem acesso ao sistema: os lançamentos dele são feitos por quem tem login." : "";
    $("#btn-remover-membro").classList.toggle("oculto", !p || p.tem_login);
    const outros = p ? m.membros.filter(x => x.id !== p.id && x.editar !== false) : [];
    $("#trocar-membro").classList.toggle("oculto", !outros.length);
    $("#trocar-membro").open = false;
    $("#sel-trocar-membro").innerHTML = outros.map(x => `<option value="${x.id}">${esc(x.nome)} (${esc(m.parentescos[x.parentesco] || "")})</option>`).join("");
    $("#dialogo-membro").showModal();
    f.nome.focus();
  }
  $("#form-membro").parentesco?.addEventListener("change", ev => {
    if (!$("#form-membro").id.value) $("#form-membro").divide.checked = ev.target.value === "conjuge" || ev.target.value === "titular";
  });
  document.addEventListener("click", ev => {
    const ed = ev.target.closest("[data-editar-membro]");
    if (ed) abrirMembro(dadosMembros.membros.find(p => p.id === +ed.dataset.editarMembro));
    if (ev.target.closest("[data-novo-membro]") || ev.target.closest("#btn-novo-membro")) {
      if (dadosMembros) abrirMembro(null);
      else api("/api/plan/membros").then(r => { dadosMembros = r; abrirMembro(null); });
    }
  });
  $("#btn-cancelar-membro").addEventListener("click", () => $("#dialogo-membro").close());
  $("#btn-trocar-membro").addEventListener("click", async () => {
    const f = $("#form-membro"), sel = $("#sel-trocar-membro");
    const outro = sel.options[sel.selectedIndex]?.text.replace(/ \(.*\)$/, "");
    if (!confirm(`Trocar ${f.nome.value} e ${outro} de lugar? Os nomes e todos os lançamentos dos dois serão trocados.`)) return;
    try {
      await api(`/api/plan/membros/${f.id.value}/trocar`, { method: "POST", body: { com: sel.value } });
      $("#dialogo-membro").close();
      toast("Membros trocados. Confira os nomes e, se quiser, edite o seu.");
      try { localStorage.removeItem("aviso-nome-membro"); } catch { /* sem armazenamento */ }
      dadosMembros = null;
      recarregar();
    } catch (e) { toast(e.message, true); }
  });
  $("#form-membro").addEventListener("submit", async ev => {
    ev.preventDefault();
    const d = formDados(ev.target);
    try {
      if (d.id) await api(`/api/plan/membros/${d.id}`, { method: "PUT", body: d });
      else membroRecemCadastrado = await api("/api/plan/membros", { method: "POST", body: d });
      $("#dialogo-membro").close();
      toast(d.id ? "Cadastro atualizado." : `${d.nome} foi cadastrado(a) e já aparece nos lançamentos.`);
      if (!d.id) await carregarCarteiras?.(carteiraAtual);
      dadosMembros = null;
      recarregar();
    } catch (e) { toast(e.message, true); }
  });
  $("#btn-remover-membro").addEventListener("click", async () => {
    const f = $("#form-membro");
    if (!confirm(`Remover ${f.nome.value} da família? Os lançamentos já feitos continuam guardados.`)) return;
    try {
      await api(`/api/plan/membros/${f.id.value}`, { method: "DELETE" });
      $("#dialogo-membro").close();
      toast("Membro removido da família.");
      dadosMembros = null;
      recarregar();
    } catch (e) { toast(e.message, true); }
  });

  let dadosFam = null;
  async function carregarFamilia() {
    atualizarSeletoresMes();
    carregarMembros().catch(e => toast(e.message, true));
    try { await garantirCategorias(); dadosFam = await api(`/api/plan/familia?mes=${mesPlan}`); } catch (e) { return toast(e.message, true); }
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
    $("#fam-regra").innerHTML = junto
      ? `No modo <strong>tudo junto</strong>, as faturas de cartão de todos os logins e as contas compartilhadas entram nas despesas da família e aparecem para todos.`
      : `Contas fixas e compras marcadas como <strong>compartilhadas</strong> entram na divisão e aparecem no login de cada membro com a parte dele.`;
    renderItensFamilia(f);
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
  // cada conta da família do mês e quanto fica para cada membro
  function renderItensFamilia(f) {
    const junto = f.modo === "junto", pessoasDiv = f.pessoas, minhas = new Set(f.minhas || []);
    const origem = l => l.cartao_id ? "fatura do cartão" : l.recorrencia_id ? "conta fixa" : l.parcela_total ? `parcela ${l.parcela_num}/${l.parcela_total}` : "compartilhada";
    $("#fam-itens-dica").textContent = junto
      ? "Tudo junto: as contas saem do caixa comum, sem divisão entre vocês."
      : `Divisão ${f.modos[f.modo]?.split(":")[0].toLowerCase() || ""}: ${pessoasDiv.map(p => `${p.nome} ${pct(p.peso, 0)}`).join(" · ")}.`;
    if (!f.itens?.length) {
      $("#fam-itens").innerHTML = `<tr><td class="dica">Nenhuma conta da família neste mês. Marque a despesa como “Compartilhada” ao lançar${junto ? " ou lance no cartão" : ""}.</td></tr>`;
      return;
    }
    const cols = junto || pessoasDiv.length < 2 ? [] : pessoasDiv;
    const soma = id => f.itens.reduce((s, l) => s + ((l.partes || []).find(x => x.id === id)?.valor || 0), 0);
    $("#fam-itens").innerHTML = `<tr><th>Data</th><th>Conta</th><th>Pago por</th><th>Valor</th>${cols.map(p =>
        `<th class="${minhas.has(p.id) ? "col-minha" : ""}">${esc(p.nome.split(" ")[0])}${minhas.has(p.id) ? " (você)" : ""}</th>`).join("")}</tr>` +
      f.itens.map(l => `<tr><td>${fmtData(l.data)}</td><td><strong>${esc(l.descricao)}</strong><small class="var-sub">${origem(l)} · ${esc(nomeCat(l.categoria_id))}</small></td>
        <td>${esc(l.pago_por)}</td><td>${brl.format(l.valor)}</td>
        ${cols.map(p => `<td class="${minhas.has(p.id) ? "col-minha" : ""}">${brl.format((l.partes || []).find(x => x.id === p.id)?.valor || 0)}</td>`).join("")}</tr>`).join("") +
      `<tr class="linha-total"><td></td><td>Total</td><td></td><td>${brl.format(f.itens.reduce((s, l) => s + l.valor, 0))}</td>${cols.map(p =>
        `<td class="${minhas.has(p.id) ? "col-minha" : ""}">${brl.format(soma(p.id))}</td>`).join("")}</tr>`;
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

  // ================= Cartões: um item no menu por cartão, com as faturas mês a mês =================
  let cartaoAtualId = null, dadosCartao = null;
  const ICONE_CARTAO = `<svg class="icone" viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5.5" width="18" height="13" rx="2.5"/><path d="M3 10h18M7 15h4"/></svg>`;
  document.body.appendChild($("#dialogo-cartao"));

  let pontosCartao = {};  // cartão -> "vermelho" (fatura vencendo) | "amarelo" (limite alto)
  function renderNavCartoes() {
    let caixa = $("#nav-cartoes");
    if (!caixa) {
      const ref = $("#nav-btn-cartoes");
      if (!ref) return;
      ref.insertAdjacentHTML("afterend", `<div class="nav-cartoes" id="nav-cartoes"></div>`);
      caixa = $("#nav-cartoes");
    }
    caixa.innerHTML = cartoesPlan.map(c => `<button type="button" class="nav-sub ${c.id === cartaoAtualId && $("#tab-plan-cartao").classList.contains("visivel") ? "ativo" : ""}"
        data-tab="plan-cartao" data-cartao-nav="${c.id}" title="Faturas do cartão ${esc(c.nome)}">${ICONE_CARTAO}<span>${esc(c.nome)}</span>${
        pontosCartao[c.id] ? `<i class="ponto-aviso ${pontosCartao[c.id]}" title="${pontosCartao[c.id] === "vermelho" ? "Fatura vence em breve" : "Limite alto"}"></i>` : ""}</button>`).join("");
  }
  function atualizarPontos(cartoes) {
    pontosCartao = {};
    cartoes.forEach(c => {
      const cods = new Set(c.alertas.map(a => a.codigo));
      if (cods.has("vencimento")) pontosCartao[c.cartao.id] = "vermelho";
      else if (cods.has("limite")) pontosCartao[c.cartao.id] = "amarelo";
    });
    renderNavCartoes();
  }
  api("/api/plan/cartoes").then(l => { cartoesPlan = l; renderNavCartoes(); }).catch(() => {});
  api("/api/plan/cartoes/resumo").then(r => atualizarPontos(r.cartoes)).catch(() => {});
  // "Cartões" abre e mostra os bancos; em outra aba eles se recolhem
  document.addEventListener("click", ev => {
    const b = ev.target.closest("nav button");
    if (!b) return;
    document.body.classList.toggle("cartoes-aberto", b.id === "nav-btn-cartoes" || b.hasAttribute("data-cartao-nav"));
  });

  document.addEventListener("click", ev => {
    const b = ev.target.closest("[data-cartao-nav]");
    if (!b) return;
    cartaoAtualId = +b.dataset.cartaoNav;
    const c = cartoesPlan.find(x => x.id === cartaoAtualId);
    document.querySelectorAll("nav button").forEach(x => x.classList.toggle("ativo", x === b));
    $("#nav-btn-cartoes").classList.add("aberto-pai");
    $("#titulo-pagina").textContent = c ? c.nome : "Cartão";
    $("#sub-pagina").textContent = "Faturas mês a mês, limite e avisos do cartão";
    document.title = `${c ? c.nome : "Cartão"} · Carteira de Aportes`;
    document.body.classList.remove("menu-aberto");
    window.scrollTo({ top: 0 });
    document.querySelectorAll(".tab").forEach(t => t.classList.toggle("visivel", t.id === "tab-plan-cartao"));
    carregarCartaoPagina();
  });

  const SITUACAO_FATURA = { aberta: "aberta", fechada: "fechada", encerrada: "encerrada", futura: "futura" };
  async function carregarCartaoPagina() {
    if (!cartaoAtualId) return;
    try {
      await garantirCategorias();
      if (!pessoasPlan.length) pessoasPlan = (await api(`/api/plan/lancamentos?mes=${mesPlan}`)).pessoas || [];
      [dadosCartao] = await Promise.all([api(`/api/plan/cartoes/${cartaoAtualId}/faturas`), carregarCartoes()]);
    } catch (e) { return toast(e.message, true); }
    const { cartao: c, resumo: r, faturas, alertas } = dadosCartao;
    const usadoPct = c.limite ? Math.min(100, r.usado / c.limite * 100) : null;
    const dias = c.dia_fechamento || c.dia_vencimento
      ? `fecha dia ${c.dia_fechamento || "≈" + ((c.dia_vencimento > 7 ? c.dia_vencimento - 7 : Math.min(c.dia_vencimento + 23, 28)))} · vence dia ${c.dia_vencimento || "—"}`
      : `<button type="button" class="link acao" data-config-cartao>informe os dias de fechamento e vencimento</button>`;
    $("#cartao-topo").innerHTML = `
      <div class="cartao-visual">
        <div class="cartao-plastico cor-${corBanco(c.nome)}"><span>${esc(c.nome)}</span><small>${c.final ? `•••• ${esc(c.final)}` : "&nbsp;"}</small></div>
        <div class="cartao-info">
          <strong>${esc(c.nome)}</strong>
          <small>${c.dono ? `de ${esc(c.dono)} · ` : ""}${dias}${c.dias_estimados ? " <span class=\"dica\">(fechamento estimado)</span>" : ""}</small>
          ${c.limite ? `<div class="barra-limite ${usadoPct >= 95 ? "neg" : usadoPct >= 80 ? "atencao" : ""}"><span style="width:${usadoPct}%"></span></div>
            <small>${brl.format(r.usado)} usados de ${brl.format(c.limite)} · <strong>${brl.format(r.disponivel)}</strong> disponível</small>`
            : `<small class="dica">Informe o limite para acompanhar quanto já está comprometido.</small>`}
        </div>
        ${c.pode_editar ? `<button type="button" class="secundario btn-pequeno" data-config-cartao>Configurar</button>` : ""}
      </div>`;
    $("#cartao-alertas").innerHTML = alertas.map(a => `<div class="aviso-cartao ${a.nivel}"><strong>${esc(a.titulo)}</strong><span>${esc(a.texto)}</span></div>`).join("");
    const prox = r.proxima;
    $("#cartao-cards").innerHTML = [
      ["Fatura aberta", brl.format(r.aberta), (faturas.find(f => f.situacao === "aberta")?.fechamento ? `fecha em ${fmtData(faturas.find(f => f.situacao === "aberta").fechamento)}` : "compras do ciclo atual")],
      ["Próxima a vencer", prox ? brl.format(prox.total) : "—", prox?.vencimento ? `vence em ${fmtData(prox.vencimento)}` : "informe o dia do vencimento"],
      ["Parcelas futuras", brl.format(r.futuras), "já comprometido nos próximos meses"],
      ["Aguardando fatura", String(r.aguardando), "compras lançadas à mão ainda não conferidas"],
    ].map(([t, v, s]) => `<div class="card"><div class="rotulo">${t}</div><div class="valor">${v}</div><small class="var-sub">${s}</small></div>`).join("");
    // a importação da fatura aparece aqui, já com este cartão escolhido
    $("#cartao-importar").appendChild($("#painel-fatura"));
    $("#sel-cartao-fatura").value = c.id;
    const nomeP = id => pessoasPlan.find(p => p.id === id)?.nome || "";
    // primeiro a fatura atual, depois as anteriores e, por último, as futuras (só parcelas)
    const ordem = { fechada: 0, aberta: 1, encerrada: 2, futura: 3 };
    const lista = [...faturas].sort((a, b) => ordem[a.situacao] - ordem[b.situacao] ||
      (a.situacao === "futura" ? a.mes.localeCompare(b.mes) : b.mes.localeCompare(a.mes)));
    let tituloFuturas = false;
    $("#cartao-faturas").innerHTML = lista.length ? lista.map(f => (f.situacao === "futura" && !tituloFuturas && (tituloFuturas = true)
        ? `<h4 class="titulo-futuras">Próximas faturas <small class="dica">parcelas já lançadas</small></h4>` : "") + `
      <details class="fatura-mes ${f.situacao}" ${f.situacao === "aberta" || f.situacao === "fechada" ? "open" : ""}>
        <summary>
          <span class="fatura-mes-nome">${nomeMes(f.mes)}</span>
          <span class="selo situacao-${f.situacao}">${SITUACAO_FATURA[f.situacao]}</span>
          <small class="dica">${f.vencimento ? `vence ${fmtData(f.vencimento)}` : ""}${f.importada && f.situacao !== "futura" ? " · importada" : ""} · ${f.qtd} ${f.situacao === "futura" ? "parcela(s)" : "compra(s)"}</small>
          <strong class="fatura-mes-total">${brl.format(f.total)}</strong>
        </summary>
        <div class="rolagem"><table class="tabela-fatura-mes"><tr><th>Data</th><th>Descrição</th><th>Categoria</th><th>Valor</th></tr>
          ${f.itens.map(l => `<tr><td>${fmtData(l.data)}</td>
            <td>${esc(l.descricao)} ${l.parcela_total ? `<span class="selo">${l.parcela_num}/${l.parcela_total}</span>` : ""}
              ${l.conferido_em ? `<span class="selo">✓ conferida</span>` : !l.chave_import && l.tipo === "despesa" && !l.parcela_total ? `<span class="selo">aguardando fatura</span>` : ""}
              ${pessoasPlan.length > 1 && l.carteira_id !== c.carteira_id ? `<small class="var-sub">${esc(nomeP(l.carteira_id))}</small>` : ""}</td>
            <td>${esc(nomeCat(l.categoria_id))}</td>
            <td class="${l.tipo === "receita" ? "pos" : ""}">${l.tipo === "receita" ? "−" : ""}${brl.format(l.valor)}</td></tr>`).join("")}
          ${f.creditos ? `<tr class="linha-total"><td></td><td>Compras ${brl.format(f.compras)} · créditos e estornos −${brl.format(f.creditos)}</td><td></td><td>${brl.format(f.total)}</td></tr>` : ""}
        </table></div>
      </details>`).join("")
      : `<p class="dica">Nenhuma compra neste cartão ainda. Importe a fatura acima ou lance uma compra no crédito.</p>`;
    renderNavCartoes();
  }

  document.addEventListener("click", ev => {
    if (ev.target.closest("[data-todos-cartoes]")) $("#nav-btn-cartoes").click();
    const v = ev.target.closest("[data-ver-cartao]");
    if (v) document.querySelector(`[data-cartao-nav="${v.dataset.verCartao}"]`)?.click();
  });

  // ---------- página "Cartões": resumo de todos ----------
  const CORES_BANCO = [[/nubank|\bnu\b/i, "nu"], [/banco do brasil|ourocard|\bbb\b/i, "bb"], [/sicredi/i, "sicredi"],
    [/ita[uú]/i, "itau"], [/inter\b/i, "inter"], [/santander/i, "santander"], [/bradesco/i, "bradesco"], [/caixa/i, "caixa"],
    [/c6/i, "c6"], [/xp\b/i, "xp"]];
  const corBanco = nome => (CORES_BANCO.find(([re]) => re.test(nome)) || [null, "padrao"])[1];
  let dadosCartoes = null;
  async function carregarCartoesResumo() {
    document.body.classList.add("cartoes-aberto");
    try {
      await garantirCategorias();
      dadosCartoes = await api("/api/plan/cartoes/resumo");
    } catch (e) { return toast(e.message, true); }
    cartoesPlan = dadosCartoes.cartoes.map(c => c.cartao);
    atualizarPontos(dadosCartoes.cartoes);
    const t = dadosCartoes.totais, prox = dadosCartoes.proximo_vencimento;
    const pctLimite = t.limite ? t.usado / t.limite * 100 : null;
    $("#cartoes-totais").innerHTML = [
      ["Total em aberto", brl.format(t.em_aberto), "faturas abertas e fechadas a pagar"],
      ["Próximo vencimento", prox ? brl.format(prox.total) : "—", prox ? `${esc(prox.cartao)} · vence ${fmtData(prox.vencimento).slice(0, 5)}` : "informe os dias dos cartões"],
      ["Parcelas futuras", brl.format(t.futuras), "já comprometido nos próximos meses"],
      ["Limite usado", pctLimite == null ? "—" : `${Math.round(pctLimite)}%`, pctLimite == null ? "informe o limite dos cartões"
        : `<span class="barra-limite ${pctLimite >= 95 ? "neg" : pctLimite >= 80 ? "atencao" : ""}" style="display:block;margin:6px 0 4px"><span style="width:${Math.min(100, pctLimite)}%"></span></span>${brl.format(t.usado)} de ${brl.format(t.limite)}`],
    ].map(([r, v, s]) => `<div class="card"><div class="rotulo">${r}</div><div class="valor">${v}</div><small class="var-sub">${s}</small></div>`).join("");
    const avisos = dadosCartoes.cartoes.flatMap(c => c.alertas).sort((a, b) => (a.nivel === "alerta" ? 0 : 1) - (b.nivel === "alerta" ? 0 : 1));
    $("#cartoes-avisos").innerHTML = avisos.map(a => `<div class="aviso-cartao ${a.nivel}"><strong>${esc(a.titulo)}</strong><span>${esc(a.texto)}</span></div>`).join("");
    $("#cartoes-grade").innerHTML = dadosCartoes.cartoes.length ? dadosCartoes.cartoes.map(({ cartao: c, resumo: r }) => {
      const pct = c.limite ? Math.min(100, r.usado / c.limite * 100) : null;
      const ult = [...r.ultimas].reverse(), maior = Math.max(1, ...ult.map(u => u.total));
      const dias = c.dia_fechamento || c.dia_vencimento ? `fecha dia ${c.dia_fechamento || "≈"} · vence dia ${c.dia_vencimento || "—"}` : "dias de fechamento e vencimento não informados";
      return `<div class="tile-cartao" data-ver-cartao="${c.id}" role="button" tabindex="0">
        <div class="tile-topo"><div class="mini-cartao cor-${corBanco(c.nome)}"><span>${esc(c.nome)}</span><small>${c.final ? `•••• ${esc(c.final)}` : "&nbsp;"}</small></div>
          <div><strong>${esc(c.nome)}</strong><small>${c.dono ? `de ${esc(c.dono)} · ` : ""}${dias}</small></div></div>
        <div class="tile-linhas">
          <span>Fatura aberta${r.aberta_fecha ? ` · fecha ${fmtData(r.aberta_fecha).slice(0, 5)}` : ""}</span><span>${brl.format(r.aberta)}</span>
          <span>Próxima a vencer${r.proxima?.vencimento ? ` · ${fmtData(r.proxima.vencimento).slice(0, 5)}` : ""}</span><span>${r.proxima ? brl.format(r.proxima.total) : "—"}</span>
          <span>Parcelas futuras</span><span>${r.futuras ? brl.format(r.futuras) : "—"}</span>
        </div>
        ${pct == null ? `<small class="dica">Sem limite informado</small>` : `<div><div class="barra-limite ${pct >= 95 ? "neg" : pct >= 80 ? "atencao" : ""}"><span style="width:${pct}%"></span></div>
          <small class="dica">${Math.round(r.usado / c.limite * 100)}% do limite · ${brl.format(r.disponivel)} disponível</small></div>`}
        ${ult.length ? `<div class="mini-grafico" title="Últimas faturas">${ult.map((u, i) => `<b class="${i === ult.length - 1 ? "atual" : ""}" style="height:${Math.max(4, u.total / maior * 100)}%" title="${nomeMes(u.mes)}: ${brl.format(u.total)}"></b>`).join("")}</div>
          <div class="mini-grafico-leg"><span>${nomeMes(ult[0].mes).slice(0, 3).toLowerCase()}</span><span>últimas ${ult.length} fatura(s)</span><span>${nomeMes(ult[ult.length - 1].mes).slice(0, 3).toLowerCase()}</span></div>` : ""}
        <span class="ver-faturas">Ver faturas →</span>
      </div>`;
    }).join("") : `<div class="painel"><p class="dica" style="margin:0">Nenhum cartão cadastrado. Clique em <strong>Novo cartão</strong> para começar.</p></div>`;
  }
  document.addEventListener("keydown", ev => {
    if (ev.key === "Enter" && ev.target.matches?.("[data-ver-cartao]")) ev.target.click();
  });
  document.addEventListener("click", ev => {
    if (!ev.target.closest("[data-novo-cartao]")) return;
    const f = $("#form-config-cartao");
    f.reset(); f.id.value = "";
    const ps = dadosCartoes?.pessoas || pessoasPlan.filter(p => p.editar);
    f.carteira_id.innerHTML = ps.map(p => `<option value="${p.id}">${esc(p.nome)}</option>`).join("");
    $("#dialogo-cartao h3").textContent = "Novo cartão";
    $("#btn-remover-cartao").classList.add("oculto");
    $("#dialogo-cartao").showModal();
  });

  function abrirConfigCartao() {
    const f = $("#form-config-cartao"), c = dadosCartao.cartao;
    f.id.value = c.id; f.nome.value = c.nome; f.final.value = c.final || ""; f.limite.value = fmtMoeda(c.limite);
    f.dia_fechamento.value = c.dia_fechamento || ""; f.dia_vencimento.value = c.dia_vencimento || "";
    f.carteira_id.innerHTML = dadosCartao.pessoas.map(p => `<option value="${p.id}" ${p.id === c.carteira_id ? "selected" : ""}>${esc(p.nome)}</option>`).join("");
    $("#dialogo-cartao h3").textContent = "Configurar cartão";
    $("#btn-remover-cartao").classList.remove("oculto");
    $("#dialogo-cartao").showModal();
  }
  document.addEventListener("click", ev => { if (ev.target.closest("[data-config-cartao]")) abrirConfigCartao(); });
  $("#btn-cancelar-cartao").addEventListener("click", () => $("#dialogo-cartao").close());
  $("#form-config-cartao").addEventListener("submit", async ev => {
    ev.preventDefault();
    const d = formDados(ev.target);
    try {
      if (!d.id) {  // novo cartão (pela página Cartões)
        await api("/api/plan/cartoes", { method: "POST", body: d });
        $("#dialogo-cartao").close();
        toast("Cartão cadastrado.");
        cartoesPlan = await api("/api/plan/cartoes");
        renderNavCartoes();
        return carregarCartoesResumo();
      }
      await api(`/api/plan/cartoes/${d.id}`, { method: "PUT", body: d });
      $("#dialogo-cartao").close();
      toast("Cartão atualizado.");
      cartoesPlan = await api("/api/plan/cartoes");
      $("#titulo-pagina").textContent = d.nome;
      carregarCartaoPagina();
    } catch (e) { toast(e.message, true); }
  });
  $("#btn-remover-cartao").addEventListener("click", async () => {
    const f = $("#form-config-cartao");
    if (!confirm(`Remover o cartão ${f.nome.value}? As compras já lançadas continuam.`)) return;
    try {
      await api(`/api/plan/cartoes/${f.id.value}`, { method: "DELETE" });
      $("#dialogo-cartao").close();
      cartoesPlan = await api("/api/plan/cartoes");
      renderNavCartoes();
      $("#nav-btn-cartoes").click();
    } catch (e) { toast(e.message, true); }
  });

  window.ABAS_MODULOS = { ...(window.ABAS_MODULOS || {}), "plan-resumo": carregarResumo, "plan-lancamentos": carregarLancamentos,
    "plan-orcamento": carregarOrcamento, "plan-objetivos": carregarObjetivos, "plan-familia": carregarFamilia,
    "plan-cartoes": carregarCartoesResumo };
})();
