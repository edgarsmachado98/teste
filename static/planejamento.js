// Módulo adicional: Planejamento financeiro (carregado só quando o módulo está ativo na licença).
// Usa as funções do app base (api, brl, esc, grafico, toast...).
(function () {
  const hojeLocal = () => new Date().toLocaleDateString("sv-SE");
  let mesPlan = hojeLocal().slice(0, 7);
  let categoriasPlan = [], formasPlan = {}, dadosLanc = null, tipoForm = "despesa";

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
    if (aba === "plan-resumo") carregarResumo();
    if (aba === "plan-lancamentos") carregarLancamentos();
  }

  async function garantirCategorias() {
    if (categoriasPlan.length) return;
    const r = await api("/api/plan/categorias");
    categoriasPlan = r.categorias;
    formasPlan = r.formas;
    $("#form-plan").forma.innerHTML = `<option value="">—</option>` +
      Object.entries(formasPlan).map(([v, n]) => `<option value="${v}">${esc(n)}</option>`).join("");
    preencherCategorias();
  }

  function preencherCategorias(selecionada) {
    const grupos = {};
    categoriasPlan.filter(c => c.tipo === tipoForm).forEach(c => (grupos[c.grupo] ||= []).push(c));
    $("#form-plan").categoria_id.innerHTML = `<option value="">Escolha…</option>` + Object.entries(grupos).map(([g, cs]) =>
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

    const ind = [
      ["Taxa de poupança", r.taxa_poupanca == null ? "—" : pct(r.taxa_poupanca, 1), "Quanto da renda foi investido. Uma boa referência é 20% ou mais."],
      ["Custo de vida médio", r.custo_de_vida == null ? "—" : brl.format(r.custo_de_vida), "Média das despesas dos últimos 12 meses fechados. Base da reserva de emergência."],
      ["Reserva de emergência ideal", r.custo_de_vida == null ? "—" : `${brl.format(r.custo_de_vida * 6)} a ${brl.format(r.custo_de_vida * 12)}`, "De 6 a 12 meses do custo de vida."],
      ["Proventos pagam", r.cobertura_proventos == null ? "—" : `${pct(r.cobertura_proventos, 1)} das despesas`, "Quanto da sua vida a renda dos investimentos já sustenta."],
    ];
    $("#plan-indicadores").innerHTML = ind.map(([n, v, d]) => `<div><span>${n}</span><strong>${v}</strong><small>${d}</small></div>`).join("");

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
  function ajustarForm() {
    const f = $("#form-plan"), receita = tipoForm === "receita", editando = !!f.id.value;
    document.querySelectorAll("[data-plan-tipo]").forEach(b => b.classList.toggle("ativo", b.dataset.planTipo === tipoForm));
    document.querySelectorAll("#form-plan .so-receita").forEach(e => e.classList.toggle("oculto", !receita));
    document.querySelectorAll("#form-plan .so-despesa").forEach(e => e.classList.toggle("oculto", receita));
    document.querySelectorAll("#form-plan .so-novo").forEach(e => e.classList.toggle("oculto", editando));
    f.querySelector(".so-despesa-opt").disabled = receita;
    if (receita && f.repetir.value === "parcelado") f.repetir.value = "nao";
    const rep = editando ? "nao" : f.repetir.value;
    f.querySelector(".campo-parcelas").classList.toggle("oculto", rep !== "parcelado");
    f.querySelector(".campo-fim").classList.toggle("oculto", rep !== "mensal");
    f.querySelector("[data-rotulo-valor]").textContent = rep === "parcelado" ? "Valor total (R$)" : receita ? "Valor líquido (R$)" : "Valor (R$)";
    f.querySelector("[data-rotulo-pago]").textContent = receita ? "Já recebido" : "Já pago";
    f.descricao.placeholder = receita ? "ex.: Salário da empresa X" : "ex.: Supermercado";
    const dicas = {
      mensal: "Será lançado automaticamente todo mês, no mesmo dia. Nos meses seguintes ele aparece como pendente até você marcar.",
      parcelado: "O valor total é dividido nas parcelas, uma por mês a partir desta data.",
      nao: receita ? "Informe o valor que cai na conta (líquido). O bruto é opcional e mostra quanto foi descontado." : "",
    };
    $("#plan-dica-form").textContent = editando ? "" : dicas[rep];
  }

  document.querySelectorAll("[data-plan-tipo]").forEach(b => b.addEventListener("click", () => {
    if ($("#form-plan").id.value) return;  // na edição o tipo não muda
    tipoForm = b.dataset.planTipo;
    preencherCategorias();
    ajustarForm();
  }));
  $("#form-plan").repetir.addEventListener("change", ajustarForm);

  function limparForm() {
    const f = $("#form-plan");
    f.reset();
    f.id.value = "";
    f.data.value = mesPlan === hojeLocal().slice(0, 7) ? hojeLocal() : `${mesPlan}-01`;
    $("#plan-form-titulo").textContent = "Novo lançamento";
    $("#btn-plan-salvar").textContent = "Adicionar";
    $("#btn-plan-cancelar").classList.add("oculto");
    f.querySelector(".campo-proximos").classList.add("oculto");
    preencherCategorias();
    ajustarForm();
  }
  $("#btn-plan-cancelar").addEventListener("click", limparForm);

  $("#form-plan").addEventListener("submit", async ev => {
    ev.preventDefault();
    const f = ev.target, d = formDados(f), id = d.id;
    const body = { tipo: tipoForm, data: d.data, descricao: d.descricao, categoria_id: d.categoria_id, valor: d.valor,
      valor_bruto: tipoForm === "receita" ? d.valor_bruto : "", forma: tipoForm === "despesa" ? d.forma : "", pago: d.pago,
      repetir: d.repetir, parcelas: d.parcelas, fim: d.fim, atualizar_proximos: d.atualizar_proximos };
    try {
      if (id) await api(`/api/plan/lancamentos/${id}`, { method: "PUT", body });
      else await api("/api/plan/lancamentos", { method: "POST", body });
      toast(id ? "Lançamento atualizado." : d.repetir === "mensal" ? "Lançado para todo mês." :
        d.repetir === "parcelado" ? `Compra lançada em ${d.parcelas} parcelas.` : "Lançamento adicionado.");
      const manterData = f.data.value;
      limparForm();
      if (!id) f.data.value = manterData;
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
      dadosLanc = await api(`/api/plan/lancamentos?mes=${mesPlan}`);
    } catch (e) { return toast(e.message, true); }
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
    $("#tabela-plan").innerHTML = lista.length ? `<tr><th>Data</th><th>Descrição</th><th>Pagamento</th><th>Valor</th><th>Situação</th><th></th></tr>` +
      lista.map(l => {
        const selos = [l.recorrencia_id ? "todo mês" : "", l.parcela_total ? `${l.parcela_num}/${l.parcela_total}` : "", l.projetado ? "previsto" : ""]
          .filter(Boolean).map(s => `<span class="selo">${s}</span>`).join(" ");
        const situacao = l.projetado ? `<span class="dica">previsto</span>`
          : l.pago ? `<span class="pos">${l.tipo === "receita" ? "recebido" : "pago"}</span>`
          : `<button type="button" class="link acao requer-edicao" data-pagar="${l.id}">marcar ${l.tipo === "receita" ? "recebido" : "pago"}</button>`;
        return `<tr class="${l.projetado ? "desativado" : ""}">
          <td>${fmtData(l.data)}</td>
          <td><strong>${esc(l.descricao)}</strong> ${selos}<small class="var-sub">${esc(nomeCat(l.categoria_id))}${l.valor_bruto ? ` · bruto ${brl.format(l.valor_bruto)}` : ""}</small></td>
          <td>${esc(formasPlan[l.forma] || "—")}</td>
          <td class="${l.tipo === "receita" ? "pos" : ""}">${l.tipo === "receita" ? "+" : "−"}${brl.format(l.valor)}</td>
          <td>${situacao}</td>
          <td>${l.projetado ? "" : `<span class="requer-edicao"><button class="link editar" data-plan-editar="${l.id}">editar</button><button class="link" data-plan-excluir="${l.id}">excluir</button></span>`}</td></tr>`;
      }).join("")
      : `<tr><td>${todos.length ? "Nenhum lançamento com este filtro." : "Nenhum lançamento neste mês."}</td></tr>`;

    const recs = dadosLanc.recorrencias;
    $("#tabela-plan-fixas").innerHTML = recs.length ? `<tr><th>Descrição</th><th>Dia</th><th>Valor</th><th>Período</th><th></th></tr>` +
      recs.map(r => `<tr><td><strong>${esc(r.descricao)}</strong><small class="var-sub">${r.tipo === "receita" ? "Receita" : "Despesa"} · ${esc(nomeCat(r.categoria_id))}</small></td>
        <td>${r.dia}</td><td class="${r.tipo === "receita" ? "pos" : ""}">${brl.format(r.valor)}</td>
        <td>desde ${fmtData(r.inicio + "-01").slice(3)}${r.fim ? ` até ${fmtData(r.fim + "-01").slice(3)}` : ""}</td>
        <td>${r.fim && r.fim < dadosLanc.mes_atual ? `<span class="dica">encerrada</span>` : `<button class="link requer-edicao" data-plan-encerrar="${r.id}">encerrar</button>`}</td></tr>`).join("")
      : `<tr><td>Nenhuma receita ou conta fixa. Ao lançar, escolha “Todo mês”.</td></tr>`;
  }
  $("#plan-filtro").addEventListener("change", renderLancamentos);

  document.addEventListener("click", async ev => {
    const ed = ev.target.closest("[data-plan-editar]"), ex = ev.target.closest("[data-plan-excluir]"),
      enc = ev.target.closest("[data-plan-encerrar]");
    if (ed) {
      const l = dadosLanc.lancamentos.find(x => x.id === +ed.dataset.planEditar), f = $("#form-plan");
      tipoForm = l.tipo;
      preencherCategorias(l.categoria_id);
      f.id.value = l.id; f.data.value = l.data; f.descricao.value = l.descricao; f.valor.value = l.valor;
      f.valor_bruto.value = l.valor_bruto || ""; f.forma.value = l.forma || ""; f.pago.checked = !!l.pago;
      f.atualizar_proximos.checked = false;
      f.querySelector(".campo-proximos").classList.toggle("oculto", !l.recorrencia_id);
      $("#plan-form-titulo").textContent = "Editar lançamento";
      $("#btn-plan-salvar").textContent = "Salvar alterações";
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

  window.ABAS_MODULOS = { ...(window.ABAS_MODULOS || {}), "plan-resumo": carregarResumo, "plan-lancamentos": carregarLancamentos };
})();
