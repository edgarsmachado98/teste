// Módulo adicional: Compras (histórico de preços pelas notas fiscais e lista de compras pelo menor preço).
// Usa as funções do app base (api, brl, esc, fmtData, toast, grafico...) e o LeitorQR compartilhado.
(function () {
  if (!document.getElementById("tab-cmp-lista")) return;
  const hoje = () => new Date().toLocaleDateString("sv-SE");
  const dataCurta = iso => iso ? fmtData(iso).slice(0, 5) : "";
  let dadosLista = null, modoLista = "lista", dadosResumo = null, diasResumo = 90, planAtivo = false, planCats = [], planCartoes = [];
  let notas = [], falhas = [];
  const preco = v => brl.format(v);

  // ---------------- janela lateral do módulo ----------------
  document.body.insertAdjacentHTML("beforeend", `<div class="gaveta-veu" id="cmp-veu" hidden></div>
    <aside class="gaveta" id="cmp-gaveta" aria-hidden="true" role="dialog"><div class="gaveta-cab"><span></span>
      <button type="button" class="btn-icone" id="cmp-fechar" aria-label="Fechar"><svg class="icone" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg></button></div>
      <div class="gaveta-corpo" id="cmp-gaveta-corpo"></div></aside>`);
  function abrir(conteudo) {
    fechar(true);
    const corpo = $("#cmp-gaveta-corpo");
    if (typeof conteudo === "string") corpo.innerHTML = conteudo; else corpo.appendChild(conteudo);
    $("#cmp-gaveta").classList.add("aberta"); $("#cmp-gaveta").setAttribute("aria-hidden", "false");
    $("#cmp-veu").hidden = false;
    document.body.classList.add("gaveta-aberta");
    corpo.scrollTop = 0;
  }
  function fechar(trocando) {
    const corpo = $("#cmp-gaveta-corpo"), painel = $("#cmp-painel-nota");
    if (painel && corpo.contains(painel)) $("#cmp-guardados").appendChild(painel);
    corpo.innerHTML = "";
    if (trocando === true) return;
    $("#cmp-gaveta").classList.remove("aberta"); $("#cmp-gaveta").setAttribute("aria-hidden", "true");
    $("#cmp-veu").hidden = true;
    document.body.classList.remove("gaveta-aberta");
  }
  $("#cmp-fechar").addEventListener("click", () => fechar());
  $("#cmp-veu").addEventListener("click", () => fechar());
  document.addEventListener("keydown", ev => {
    if (ev.key === "Escape" && $("#cmp-gaveta").classList.contains("aberta") && document.getElementById("lqr")?.classList.contains("oculto") !== false) fechar();
  });
  function recarregar() {
    const aba = document.querySelector("nav button.ativo")?.dataset.tab;
    ({ "cmp-lista": carregarLista, "cmp-precos": carregarPrecos, "cmp-mercados": carregarMercados }[aba] || (() => {}))();
  }

  // ================= Ler nota fiscal =================
  document.addEventListener("click", ev => {
    if (!ev.target.closest("[data-cmp-ler]")) return;
    notas = []; falhas = [];
    renderNotas();
    abrir($("#cmp-painel-nota"));
  });
  $("#cmp-escanear").addEventListener("click", () => LeitorQR.escanear(t => lerNotas([], [t]), fs => lerNotas(fs)));
  $("#cmp-fotos").addEventListener("click", () => $("#cmp-arquivos").click());
  $("#cmp-arquivos").addEventListener("change", ev => { const fs = [...ev.target.files]; ev.target.value = ""; lerNotas(fs); });
  $("#cmp-form-link").addEventListener("submit", ev => {
    ev.preventDefault();
    const t = ev.target.texto.value.trim();
    if (!t) return toast("Cole o link do QR Code ou a chave da nota.", true);
    ev.target.reset();
    lerNotas([], [t]);
  });

  async function garantirPlanejamento() {
    if (!planAtivo || planCats.length) return;
    try {
      const [c, k] = await Promise.all([api("/api/plan/categorias"), api("/api/plan/cartoes")]);
      planCats = c.categorias.filter(x => x.tipo === "despesa");
      planCartoes = k;
    } catch { planAtivo = false; }
  }

  async function lerNotas(arquivos, textos = []) {
    const st = document.createElement("p");
    st.className = "dica cmp-lendo";
    st.textContent = arquivos.length ? "Procurando o QR Code na foto…" : "Consultando a nota na Sefaz…";
    $("#cmp-notas").prepend(st);
    const fd = new FormData();
    textos.forEach(t => fd.append("texto", t));
    for (const a of arquivos) {
      const t = await LeitorQR.lerArquivo(a);
      if (t) fd.append("texto", t); else fd.append("foto", await LeitorQR.reduzir(a), a.name || "foto.jpg");
    }
    st.textContent = "Consultando a nota na Sefaz…";
    try {
      const r = await fetch("/api/compras/ler", { method: "POST", body: fd,
        headers: { "X-Requested-With": "fetch", "X-Carteira": String(carteiraAtual) } });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(j.erro || `Erro ${r.status}`);
      planAtivo = j.planejamento;
      await garantirPlanejamento();
      const ja = new Set(notas.map(n => n.chave));
      j.notas.filter(n => !ja.has(n.chave)).forEach(n => {
        n.lancar = planAtivo && !n.ja_registrada;
        n.pagamentos = (n.pagamentos || []).length ? n.pagamentos : [{ forma: null, valor: n.total }];
        notas.push(n);
      });
      falhas = j.falhas;
      renderNotas();
    } catch (e) { toast(e.message, true); }
    finally { st.remove(); }
  }

  const FORMAS = { pix: "Pix", debito: "Débito", credito: "Cartão de crédito", dinheiro: "Dinheiro", boleto: "Boleto", transferencia: "Transferência" };
  function renderNotas() {
    const catPadrao = planCats.find(c => c.nome === "Mercado")?.id;
    $("#cmp-notas").innerHTML = (falhas.length ? `<div class="aviso">${falhas.map(f => `<div><strong>${esc(f.origem)}</strong>: ${esc(f.motivo)}</div>`).join("")}</div>` : "") +
      notas.map((n, k) => {
        const baratos = n.itens.filter(i => i.mais_barato);
        const credito = n.pagamentos.some(p => p.forma === "credito");
        const soCartao = n.pagamentos.every(p => p.forma === "credito");
        const fora = n.pagamentos.filter(p => p.forma !== "credito").reduce((a, p) => a + (p.valor || 0), 0);
        return `<article class="cmp-nota" data-nota="${k}">
          <header><div><strong>${esc(n.loja_nome || n.descricao)}</strong>
            <small>${n.data ? `${fmtData(n.data.slice(0, 10))}${n.data.length > 10 ? " às " + n.data.slice(11, 16) : ""} · ` : ""}${n.itens.length} itens${n.cnpj_formatado ? ` · CNPJ ${esc(n.cnpj_formatado)}` : ""}</small></div>
            <span class="cmp-nota-total">${n.total != null ? preco(n.total) : "—"}</span></header>
          ${n.ja_registrada ? `<p class="aviso">Esta nota já está no histórico (${fmtData(n.ja_registrada.data)}).</p>` : ""}
          ${n.aviso ? `<p class="aviso">${esc(n.aviso)}</p>` : ""}
          ${baratos.length ? `<p class="cmp-dica-barato">${baratos.length} ${baratos.length === 1 ? "item saiu" : "itens saíram"} mais barato em outro mercado na última compra.</p>` : ""}
          <div class="cmp-itens-nota">${n.itens.map(i => `<div class="cmp-item-nota">
            <span>${esc(i.descricao)}<small>${i.qtd != null ? `${String(i.qtd).replace(".", ",")} ${esc(i.un || "")}` : ""}${i.unitario != null ? ` × ${preco(i.unitario)}` : ""}</small>
              ${i.mais_barato ? `<small class="cmp-mais-barato">${preco(i.mais_barato.unitario)} no ${esc(i.mais_barato.loja)} em ${dataCurta(i.mais_barato.data)}</small>` : ""}</span>
            <b>${i.valor != null ? preco(i.valor) : ""}</b></div>`).join("")}</div>
          ${planAtivo && !n.ja_registrada ? `<div class="cmp-lancar">
            ${soCartao ? `<p class="cmp-cartao-info"><b>Pago no cartão de crédito.</b> Não vira despesa agora: ela entra quando você importar a fatura do cartão, já ligada a esta nota. Aqui ficam só os preços.</p>` : `
            <label class="interruptor"><input type="checkbox" data-n-lancar ${n.lancar ? "checked" : ""}><span></span><b>Lançar ${credito ? `os ${preco(fora)} pagos fora do cartão` : "também"} como despesa no Planejamento</b></label>
            <div class="cmp-lancar-campos ${n.lancar ? "" : "oculto"}">
              <label>Categoria <select data-n-cat>${planCats.map(c => `<option value="${c.id}" ${c.id === (n.categoria_id || catPadrao) ? "selected" : ""}>${esc(c.nome)}</option>`).join("")}</select></label>
              ${n.pagamentos.length === 1 ? `<label>Pagamento <select data-n-forma>${Object.entries(FORMAS).map(([v, t]) => `<option value="${v}" ${v === n.pagamentos[0].forma ? "selected" : ""}>${t}</option>`).join("")}</select></label>`
                : `<p class="dica">Pago em ${n.pagamentos.map(p => `${esc(p.forma_texto || FORMAS[p.forma] || "?")} ${preco(p.valor)}`).join(" + ")}</p>`}
            </div>
            ${credito ? `<p class="cmp-cartao-info">A parte no cartão (${preco(n.pagamentos.filter(p => p.forma === "credito").reduce((a, p) => a + p.valor, 0))}) entra pela fatura do cartão.</p>` : ""}`}
          </div>` : ""}
          <footer><button type="button" class="link" data-n-descartar>Descartar</button>
            <button type="button" class="btn" data-n-salvar ${n.ja_registrada ? "disabled" : ""}>Salvar compra</button></footer>
        </article>`;
      }).join("");
  }
  $("#cmp-notas").addEventListener("change", ev => {
    const art = ev.target.closest("[data-nota]");
    if (!art) return;
    const n = notas[+art.dataset.nota];
    if (ev.target.matches("[data-n-lancar]")) { n.lancar = ev.target.checked; art.querySelector(".cmp-lancar-campos").classList.toggle("oculto", !n.lancar); }
    if (ev.target.matches("[data-n-forma]")) { n.pagamentos[0].forma = ev.target.value; renderNotas(); }
    if (ev.target.matches("[data-n-cat]")) n.categoria_id = +ev.target.value;
  });
  $("#cmp-notas").addEventListener("click", async ev => {
    const art = ev.target.closest("[data-nota]");
    if (!art) return;
    const k = +art.dataset.nota, n = notas[k];
    if (ev.target.closest("[data-n-descartar]")) { notas.splice(k, 1); renderNotas(); return; }
    const b = ev.target.closest("[data-n-salvar]");
    if (!b) return;
    b.disabled = true;
    try {
      let lancou = false;
      const soCartao = n.pagamentos.every(p => p.forma === "credito");
      // no cartão: o Planejamento só guarda a nota (a despesa vem pela fatura); fora dele, lança a despesa
      if (planAtivo && (n.lancar || soCartao)) {
        const pags = n.pagamentos.map(p => ({ forma: p.forma || "dinheiro", valor: p.valor }));
        try {
          await api("/api/plan/nfce/confirmar", { method: "POST", body: {
            chave: n.chave, url: n.url, emitente: n.emitente, cnpj: n.cnpj, emissao: n.data, total: n.total, itens: n.itens,
            descricao: n.descricao, data: (n.data || hoje()).slice(0, 10), categoria_id: +(art.querySelector("[data-n-cat]")?.value || 0) || null,
            pagamentos: pags } }).then(r => { lancou = r.lancado > 0; });
        } catch (e) { if (e.status !== 409) throw e; }
      }
      await api("/api/compras/registrar", { method: "POST", body: { ...n, data: n.data } });
      notas.splice(k, 1);
      renderNotas();
      const noCartao = n.pagamentos.filter(p => p.forma === "credito").reduce((a, p) => a + (p.valor || 0), 0);
      toast(`Compra no ${n.loja_nome || "mercado"} salva${lancou ? " e lançada nas despesas" : ""}.` +
        (planAtivo && noCartao ? ` Os ${preco(noCartao)} no cartão entram pela fatura.` : ""));
      if (!notas.length) fechar();
      recarregar();
    } catch (e) { b.disabled = false; toast(e.message, true); }
  });

  // ================= Lista de compras =================
  async function carregarLista() {
    try { dadosLista = await api("/api/compras/lista"); } catch (e) { return toast(e.message, true); }
    renderLista();
  }

  function linhaItem(i) {
    const m = i.melhor, outros = (i.precos || []).slice(1);
    const total = m ? m.unitario * (i.qtd || 1) : null;
    return `<div class="cmp-item ${i.comprado ? "comprado" : ""}" data-item="${i.id}">
      <label class="cmp-check"><input type="checkbox" data-comprado ${i.comprado ? "checked" : ""} aria-label="Comprado"><span></span></label>
      <div class="cmp-item-info">
        <strong>${esc(i.nome)}</strong>
        ${m ? `<small><span class="cmp-preco-melhor">${preco(m.unitario)}</span> no ${esc(m.loja)}${m.antigo ? ` <em title="Preço de ${fmtData(m.data)}">· ${dataCurta(m.data)}</em>` : ""}${
          outros.length ? ` · <button type="button" class="link acao" data-ver-precos>${outros.length === 1 ? "outro mercado" : `mais ${outros.length} mercados`}</button>` : ""}</small>
          <div class="cmp-outros oculto">${outros.map(p => `<span>${esc(p.loja)} <b>${preco(p.unitario)}</b>${p.antigo ? ` <em>${dataCurta(p.data)}</em>` : ""}</span>`).join("")}</div>`
          : `<small class="dica">sem preço ainda: aparece quando uma nota com este item for lida</small>`}
      </div>
      <div class="cmp-qtd mini"><button type="button" data-qtd="-1" aria-label="Menos">−</button><span>${String(+i.qtd.toFixed(3)).replace(".", ",")}</span><button type="button" data-qtd="1" aria-label="Mais">+</button></div>
      <span class="cmp-item-total">${total != null ? preco(total) : ""}${i.economia ? `<small>economia ${preco(i.economia)}</small>` : ""}</span>
      <button type="button" class="btn-mais" data-remover aria-label="Remover da lista">×</button>
    </div>`;
  }

  function renderLista() {
    const d = dadosLista, pend = d.itens.filter(i => !i.comprado), feitos = d.itens.filter(i => i.comprado);
    $("#cmp-lista-sub").textContent = d.itens.length ? `${pend.length} para comprar${feitos.length ? ` · ${feitos.length} no carrinho` : ""}` : "";
    $("#cmp-frequentes").innerHTML = d.sugestoes.length ? `<span class="dica">Você costuma comprar:</span>` +
      d.sugestoes.map(s => `<button type="button" class="chip-add" data-sugestao="${s.produto_id}">+ ${esc(s.nome)}</button>`).join("") : "";
    let html;
    if (!d.itens.length) {
      html = `<div class="cmp-vazio"><strong>Lista vazia</strong><p>Digite um item acima ou toque nas sugestões. Depois de ler algumas notas fiscais,
        o sistema mostra onde cada item está mais barato.</p><button type="button" class="secundario" data-cmp-ler>Ler a primeira nota</button></div>`;
    } else if (modoLista === "mercado") {
      const grupos = {};
      pend.forEach(i => (grupos[i.melhor ? i.melhor.loja : "Sem preço registrado"] ||= []).push(i));
      html = Object.entries(grupos).sort((a, b) => b[1].length - a[1].length).map(([loja, its]) => {
        const tot = its.reduce((a, i) => a + (i.melhor ? i.melhor.unitario * i.qtd : 0), 0);
        return `<div class="cmp-grupo"><div class="cmp-grupo-cab"><span>${esc(loja)}</span><span>${tot ? preco(tot) : ""}</span></div>${its.map(linhaItem).join("")}</div>`;
      }).join("") + (feitos.length ? `<div class="cmp-grupo"><div class="cmp-grupo-cab"><span>No carrinho</span></div>${feitos.map(linhaItem).join("")}</div>` : "");
    } else {
      html = pend.map(linhaItem).join("") + (feitos.length ? `<div class="cmp-grupo-cab feito"><span>No carrinho</span></div>${feitos.map(linhaItem).join("")}` : "");
    }
    $("#cmp-lista").innerHTML = html;
    // onde comprar
    const m = d.melhor, um = d.um_mercado;
    $("#cmp-onde").innerHTML = !d.com_preco ? `<h3>Onde comprar</h3><p class="dica">Os preços aparecem aqui assim que houver notas fiscais lidas com os itens da lista.</p>` : `
      <h3>Onde comprar</h3>
      <div class="cmp-melhor">
        <small>Melhor combinação</small>
        <strong>${preco(m.total)}</strong>
        ${d.economia ? `<span class="cmp-economia">${preco(d.economia)} a menos que tudo no ${esc(um.loja)}</span>` : ""}
        ${m.lojas.map(g => `<div class="cmp-melhor-loja"><span><b>${esc(g.loja)}</b><small>${g.itens.length} ${g.itens.length === 1 ? "item" : "itens"}: ${esc(g.itens.slice(0, 3).join(", "))}${g.itens.length > 3 ? "…" : ""}</small></span><span>${preco(g.total)}</span></div>`).join("")}
        ${d.com_preco < d.pendentes ? `<p class="cmp-sem-preco">${d.pendentes - d.com_preco} ${d.pendentes - d.com_preco === 1 ? "item ainda sem preço" : "itens ainda sem preço"}</p>` : ""}
      </div>
      ${d.por_loja.length ? `<div class="cmp-um-lugar"><small>Tudo num mercado só</small>
        ${d.por_loja.map((l, i) => `<div class="cmp-loja-linha ${i === 0 ? "destaque" : ""}"><span><b>${esc(l.loja)}</b><small>${l.itens} de ${d.com_preco} itens${l.faltam.length ? ` · sem ${esc(l.faltam.slice(0, 2).join(", "))}${l.faltam.length > 2 ? "…" : ""}` : ""}</small></span><span>${preco(l.total)}</span></div>`).join("")}
      </div>` : ""}`;
  }

  // adicionar item (com sugestão dos produtos já comprados)
  let buscaT = null, autoItens = [], autoSel = -1;
  $("#cmp-add-texto").addEventListener("input", ev => {
    clearTimeout(buscaT);
    const q = ev.target.value.trim();
    if (q.length < 2) return $("#cmp-auto").classList.add("oculto");
    buscaT = setTimeout(async () => {
      try { autoItens = await api(`/api/compras/buscar?q=${encodeURIComponent(q)}`); } catch { autoItens = []; }
      autoSel = -1;
      $("#cmp-auto").innerHTML = autoItens.map((p, i) => `<button type="button" data-auto="${i}"><span>${esc(p.nome)}</span>
        <small>${preco(p.menor.unitario)} no ${esc(p.menor.loja)}</small></button>`).join("");
      $("#cmp-auto").classList.toggle("oculto", !autoItens.length);
    }, 180);
  });
  $("#cmp-add-texto").addEventListener("keydown", ev => {
    if ($("#cmp-auto").classList.contains("oculto") || !autoItens.length) return;
    if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
      ev.preventDefault();
      autoSel = (autoSel + (ev.key === "ArrowDown" ? 1 : -1) + autoItens.length) % autoItens.length;
      $("#cmp-auto").querySelectorAll("button").forEach((b, i) => b.classList.toggle("ativo", i === autoSel));
    }
    if (ev.key === "Escape") $("#cmp-auto").classList.add("oculto");
  });
  $("#cmp-auto").addEventListener("mousedown", ev => {
    const b = ev.target.closest("[data-auto]");
    if (!b) return;
    ev.preventDefault();
    adicionar({ produto_id: autoItens[+b.dataset.auto].id });
  });
  document.addEventListener("click", ev => { if (!ev.target.closest(".cmp-campo-busca")) $("#cmp-auto")?.classList.add("oculto"); });
  $("#cmp-form-add").addEventListener("submit", ev => {
    ev.preventDefault();
    if (autoSel >= 0 && autoItens[autoSel] && !$("#cmp-auto").classList.contains("oculto")) return adicionar({ produto_id: autoItens[autoSel].id });
    const t = $("#cmp-add-texto").value.trim();
    if (!t) return $("#cmp-add-texto").focus();
    adicionar({ texto: t });
  });
  document.addEventListener("click", ev => {
    const b = ev.target.closest("[data-cmp-add-qtd]");
    if (!b) return;
    const i = $("#cmp-add-qtd"), v = Math.max(1, (parseFloat(i.value.replace(",", ".")) || 1) + +b.dataset.cmpAddQtd);
    i.value = String(v);
  });
  async function adicionar(item) {
    try {
      const r = await api("/api/compras/lista", { method: "POST", body: { ...item, qtd: $("#cmp-add-qtd").value } });
      $("#cmp-add-texto").value = ""; $("#cmp-add-qtd").value = "1";
      $("#cmp-auto").classList.add("oculto");
      if (r.somado) toast("Já estava na lista: quantidade somada.");
      await carregarLista();
      $("#cmp-add-texto").focus();
    } catch (e) { toast(e.message, true); }
  }
  $("#cmp-frequentes").addEventListener("click", ev => {
    const b = ev.target.closest("[data-sugestao]");
    if (b) adicionar({ produto_id: +b.dataset.sugestao });
  });
  $("#cmp-lista").addEventListener("click", async ev => {
    const linha = ev.target.closest("[data-item]");
    if (!linha) return;
    const id = +linha.dataset.item, item = dadosLista.itens.find(i => i.id === id);
    if (ev.target.closest("[data-ver-precos]")) return linha.querySelector(".cmp-outros").classList.toggle("oculto");
    const q = ev.target.closest("[data-qtd]"), rm = ev.target.closest("[data-remover]");
    try {
      if (q) await api(`/api/compras/lista/${id}`, { method: "PUT", body: { qtd: Math.max(0, item.qtd + +q.dataset.qtd) } });
      else if (rm) await api(`/api/compras/lista/${id}`, { method: "DELETE" });
      else return;
      carregarLista();
    } catch (e) { toast(e.message, true); }
  });
  $("#cmp-lista").addEventListener("change", async ev => {
    if (!ev.target.matches("[data-comprado]")) return;
    const id = +ev.target.closest("[data-item]").dataset.item;
    try { await api(`/api/compras/lista/${id}`, { method: "PUT", body: { comprado: ev.target.checked } }); carregarLista(); }
    catch (e) { toast(e.message, true); }
  });
  $("#cmp-limpar").addEventListener("click", async () => {
    try { const r = await api("/api/compras/lista", { method: "DELETE" }); toast(r.removidos ? `${r.removidos} item(ns) tirado(s) da lista.` : "Nenhum item marcado como comprado."); carregarLista(); }
    catch (e) { toast(e.message, true); }
  });
  $("#cmp-modo-lista").addEventListener("click", ev => {
    const b = ev.target.closest("[data-modo]");
    if (!b) return;
    modoLista = b.dataset.modo;
    $("#cmp-modo-lista").querySelectorAll("button").forEach(x => x.classList.toggle("ativo", x === b));
    renderLista();
  });

  // ================= Preços =================
  let buscaPrecoT = null;
  async function carregarPrecos() {
    const q = new URLSearchParams({ busca: $("#cmp-busca-produto").value.trim(), loja: $("#cmp-filtro-loja").value, ordem: $("#cmp-ordem").value });
    let r;
    try { r = await api(`/api/compras/produtos?${q}`); } catch (e) { return toast(e.message, true); }
    const sel = $("#cmp-filtro-loja"), atual = sel.value;
    sel.innerHTML = `<option value="">Todos os mercados</option>` + r.lojas.map(l => `<option value="${l.id}">${esc(l.nome)}</option>`).join("");
    sel.value = atual;
    $("#cmp-produtos").innerHTML = r.produtos.length ? r.produtos.map(p => {
      const dif = p.qtd_lojas > 1 ? p.maior.unitario - p.menor.unitario : 0;
      const v = p.variacao;
      return `<button type="button" class="cmp-prod" data-produto="${p.id}">
        <span class="cmp-prod-nome"><b>${esc(p.nome)}</b><small>${p.compras} compra(s) · ${p.qtd_lojas} mercado(s)</small></span>
        <span class="cmp-prod-menor"><b>${preco(p.menor.unitario)}</b><small>${esc(p.menor.loja)}${dif > 0.009 ? ` · +${preco(dif)} no mais caro` : ""}</small></span>
        <span class="cmp-prod-ultimo"><b>${preco(p.ultimo.unitario)}</b><small>${esc(p.ultimo.loja)} · ${dataCurta(p.ultimo.data)}</small></span>
        <span class="cmp-prod-var">${v == null ? `<small class="dica">—</small>` : `<span class="cmp-var ${v > 0.5 ? "sobe" : v < -0.5 ? "desce" : ""}">${v > 0 ? "+" : ""}${String(v).replace(".", ",")}%</span>`}</span>
        <span class="cmp-prod-add" data-add-lista="${p.id}" title="Adicionar à lista" role="button">+ lista</span>
      </button>`;
    }).join("") : `<div class="cmp-vazio"><strong>${$("#cmp-busca-produto").value ? "Nada encontrado" : "Nenhum produto ainda"}</strong>
      <p>Cada nota fiscal lida traz os produtos e os preços. Quanto mais notas, melhor a comparação entre mercados.</p>
      <button type="button" class="secundario" data-cmp-ler>Ler nota fiscal</button></div>`;
  }
  $("#cmp-busca-produto").addEventListener("input", () => { clearTimeout(buscaPrecoT); buscaPrecoT = setTimeout(carregarPrecos, 220); });
  $("#cmp-filtro-loja").addEventListener("change", carregarPrecos);
  $("#cmp-ordem").addEventListener("change", carregarPrecos);
  $("#cmp-produtos").addEventListener("click", async ev => {
    const add = ev.target.closest("[data-add-lista]");
    if (add) {
      ev.stopPropagation();
      try { await api("/api/compras/lista", { method: "POST", body: { produto_id: +add.dataset.addLista, qtd: 1 } }); toast("Adicionado à lista de compras."); }
      catch (e) { toast(e.message, true); }
      return;
    }
    const b = ev.target.closest("[data-produto]");
    if (b) abrirProduto(+b.dataset.produto);
  });

  const CORES = ["#0c6b58", "#2b59c3", "#b45309", "#7c3aed", "#be123c", "#0e7490", "#4d7c0f"];
  async function abrirProduto(id) {
    let d;
    try { d = await api(`/api/compras/produtos/${id}`); } catch (e) { return toast(e.message, true); }
    const r = d.resumo, lojas = {};
    d.historico.forEach(h => (lojas[h.loja] ||= []).push(h));
    abrir(`<div class="cmp-detalhe">
      <div class="cmp-detalhe-cab"><div><h3 id="cmp-prod-nome">${esc(d.produto.nome)}</h3><small class="dica">${d.historico.length} compra(s) em ${Object.keys(lojas).length} mercado(s)</small></div>
        <button type="button" class="link acao" data-renomear-produto="${id}">renomear</button></div>
      ${r ? `<div class="cmp-detalhe-nums">
        <div><small>Menor preço</small><b class="pos">${preco(r.menor.unitario)}</b><span>${esc(r.menor.loja)}</span></div>
        <div><small>Última compra</small><b>${preco(r.ultimo.unitario)}</b><span>${esc(r.ultimo.loja)} · ${dataCurta(r.ultimo.data)}</span></div>
        <div><small>Média paga</small><b>${preco(r.media)}</b><span>${r.variacao == null ? "" : `${r.variacao > 0 ? "+" : ""}${String(r.variacao).replace(".", ",")}% em 6 meses`}</span></div>
      </div>` : ""}
      <div class="cmp-grafico"><canvas id="cmp-grafico-produto" height="190"></canvas></div>
      <h4>Preço atual em cada mercado</h4>
      ${(r?.lojas || []).map((l, i) => `<div class="cmp-loja-linha ${i === 0 ? "destaque" : ""}"><span><b>${esc(l.loja)}</b><small>comprado em ${fmtData(l.data)}</small></span><span>${preco(l.unitario)}</span></div>`).join("")}
      <h4>Histórico</h4>
      <div class="rolagem"><table class="cmp-tabela"><tr><th>Data</th><th>Mercado</th><th>Qtde.</th><th>Unitário</th></tr>
        ${[...d.historico].reverse().map(h => `<tr><td>${fmtData(h.data)}</td><td>${esc(h.loja)}</td><td>${h.qtd != null ? String(h.qtd).replace(".", ",") : ""} ${esc(h.un || "")}</td><td>${h.unitario != null ? preco(h.unitario) : ""}</td></tr>`).join("")}</table></div>
      <details class="cmp-juntar"><summary>É o mesmo produto que outro da lista? Juntar</summary>
        <p class="dica">Mercados escrevem o mesmo produto de jeitos diferentes. Nomes nas notas: ${d.nomes_nas_notas.map(esc).join(" · ")}</p>
        <div class="cmp-juntar-busca"><input id="cmp-juntar-q" placeholder="Buscar o outro produto…" autocomplete="off"><div id="cmp-juntar-res"></div></div>
      </details>
      <div class="cmp-detalhe-acoes"><button type="button" class="btn" data-add-lista-det="${id}">Adicionar à lista</button></div>
    </div>`);
    grafico("cmp-grafico-produto", {
      type: "line",
      data: { datasets: Object.entries(lojas).map(([loja, hs], i) => ({ label: loja, data: hs.map(h => ({ x: h.data, y: h.unitario })),
        borderColor: CORES[i % CORES.length], backgroundColor: CORES[i % CORES.length], tension: .25, pointRadius: 3, spanGaps: true })) },
      options: { responsive: true, maintainAspectRatio: false, parsing: false,
        scales: { x: { type: "category", labels: [...new Set(d.historico.map(h => h.data))].sort(), ticks: { callback(v) { return dataCurta(this.getLabelForValue(v)); } } },
                  y: { ticks: { callback: v => preco(v) } } },
        plugins: { legend: { position: "bottom", labels: { boxWidth: 10 } }, tooltip: { callbacks: { label: c => `${c.dataset.label}: ${preco(c.parsed.y)}` } } } },
    });
    $("#cmp-gaveta-corpo").dataset.produto = id;
  }
  $("#cmp-gaveta-corpo").addEventListener("click", async ev => {
    const corpo = $("#cmp-gaveta-corpo");
    const ren = ev.target.closest("[data-renomear-produto]");
    if (ren) {
      const nome = prompt("Nome do produto:", $("#cmp-prod-nome").textContent);
      if (!nome) return;
      try { await api(`/api/compras/produtos/${ren.dataset.renomearProduto}`, { method: "PUT", body: { nome } }); $("#cmp-prod-nome").textContent = nome; recarregar(); }
      catch (e) { toast(e.message, true); }
    }
    const add = ev.target.closest("[data-add-lista-det]");
    if (add) {
      try { await api("/api/compras/lista", { method: "POST", body: { produto_id: +add.dataset.addListaDet, qtd: 1 } }); toast("Adicionado à lista de compras."); }
      catch (e) { toast(e.message, true); }
    }
    const j = ev.target.closest("[data-juntar]");
    if (j) {
      if (!confirm(`Juntar "${j.dataset.nome}" com "${$("#cmp-prod-nome").textContent}"? Os preços dos dois passam a ser comparados juntos.`)) return;
      try {
        await api(`/api/compras/produtos/${corpo.dataset.produto}/juntar`, { method: "POST", body: { com: +j.dataset.juntar } });
        toast("Produtos juntados.");
        abrirProduto(+corpo.dataset.produto);
        recarregar();
      } catch (e) { toast(e.message, true); }
    }
    const loja = ev.target.closest("[data-renomear-loja]");
    if (loja) {
      const nome = prompt("Nome do mercado:", loja.dataset.nome);
      if (!nome) return;
      try { await api(`/api/compras/lojas/${loja.dataset.renomearLoja}`, { method: "PUT", body: { nome } }); fechar(); recarregar(); }
      catch (e) { toast(e.message, true); }
    }
    const exc = ev.target.closest("[data-excluir-compra]");
    if (exc) {
      if (!confirm("Tirar esta nota do histórico de compras? (Se ela foi lançada como despesa, a despesa continua.)")) return;
      try { await api(`/api/compras/compras/${exc.dataset.excluirCompra}`, { method: "DELETE" }); fechar(); recarregar(); }
      catch (e) { toast(e.message, true); }
    }
  });
  let juntarT = null;
  $("#cmp-gaveta-corpo").addEventListener("input", ev => {
    if (ev.target.id !== "cmp-juntar-q") return;
    clearTimeout(juntarT);
    const q = ev.target.value.trim(), atual = +$("#cmp-gaveta-corpo").dataset.produto;
    juntarT = setTimeout(async () => {
      let r = [];
      if (q.length >= 2) { try { r = await api(`/api/compras/buscar?q=${encodeURIComponent(q)}`); } catch { r = []; } }
      $("#cmp-juntar-res").innerHTML = r.filter(p => p.id !== atual).map(p => `<button type="button" class="link acao" data-juntar="${p.id}" data-nome="${esc(p.nome)}">${esc(p.nome)}</button>`).join("");
    }, 200);
  });

  // ================= Mercados =================
  async function carregarMercados() {
    try { dadosResumo = await api(`/api/compras/resumo?dias=${diasResumo}`); } catch (e) { return toast(e.message, true); }
    const r = dadosResumo, rotulo = { 30: "nos últimos 30 dias", 90: "nos últimos 3 meses", 365: "nos últimos 12 meses" }[diasResumo];
    $("#cmp-kpis").innerHTML = [
      ["Gasto", preco(r.gasto), rotulo],
      ["Compras", String(r.compras), `${r.lojas.filter(l => l.visitas).length} mercado(s)`],
      ["Ticket médio", r.ticket ? preco(r.ticket) : "—", "por compra"],
      ["Itens comprados", String(r.itens), "somando todas as notas"],
    ].map(([t, v, s]) => `<div class="card"><div class="rotulo">${t}</div><div class="valor">${v}</div><small class="var-sub">${s}</small></div>`).join("");
    $("#cmp-lojas").innerHTML = r.lojas.length ? r.lojas.map(l => `<div class="cmp-loja-card">
      <div class="cmp-loja-topo"><span class="cmp-loja-ic">${esc(l.nome.slice(0, 1))}</span><div><b>${esc(l.nome)}</b><small>${l.endereco ? esc(l.endereco.split(",").slice(-2).join(",").trim()) : esc(l.cnpj)}</small></div></div>
      <div class="cmp-loja-nums">
        <div><small>Gasto</small><b>${preco(l.gasto)}</b></div>
        <div><small>Compras</small><b>${l.visitas}</b></div>
        <div><small>Ticket</small><b>${l.ticket ? preco(l.ticket) : "—"}</b></div>
      </div>
      <div class="cmp-loja-rodape"><span>${l.mais_barato_em ? `Mais barato em <b>${l.mais_barato_em}</b> produto(s)` : "—"}</span><span>última ida ${dataCurta(l.ultima)}</span></div>
    </div>`).join("") : "";
    $("#cmp-ultimas").innerHTML = r.ultimas.length ? `<div class="cmp-notas-lista">${r.ultimas.map(c => `<button type="button" class="cmp-nota-linha" data-compra="${c.id}">
        <span class="cmp-nota-data"><b>${fmtData(c.data).slice(0, 2)}</b><small>${new Date(c.data + "T12:00").toLocaleDateString("pt-BR", { month: "short" }).replace(".", "")}</small></span>
        <span><b>${esc(c.loja)}</b><small>${c.qtd_itens} itens${c.hora ? ` · ${c.hora}` : ""}</small></span>
        <span class="cmp-nota-valor">${c.total != null ? preco(c.total) : ""}</span></button>`).join("")}</div>`
      : `<div class="cmp-vazio"><strong>Nenhuma nota ainda</strong><p>Leia o QR Code dos cupons do mercado, posto ou farmácia para montar o histórico de preços.</p>
         <button type="button" class="btn" data-cmp-ler>Ler nota fiscal</button></div>`;
  }
  $("#cmp-periodo").addEventListener("click", ev => {
    const b = ev.target.closest("[data-dias]");
    if (!b) return;
    diasResumo = +b.dataset.dias;
    $("#cmp-periodo").querySelectorAll("button").forEach(x => x.classList.toggle("ativo", x === b));
    carregarMercados();
  });
  $("#cmp-ultimas").addEventListener("click", async ev => {
    const b = ev.target.closest("[data-compra]");
    if (!b) return;
    let c;
    try { c = await api(`/api/compras/compras/${b.dataset.compra}`); } catch (e) { return toast(e.message, true); }
    abrir(`<div class="cmp-detalhe">
      <div class="cmp-detalhe-cab"><div><h3>${esc(c.loja)}</h3><small class="dica">${fmtData(c.data)}${c.hora ? ` às ${c.hora}` : ""} · CNPJ ${esc(c.cnpj)}</small></div>
        <button type="button" class="link acao" data-renomear-loja="${c.loja_id}" data-nome="${esc(c.loja)}">renomear mercado</button></div>
      <div class="cmp-itens-nota">${c.itens.map(i => `<div class="cmp-item-nota"><span>${esc(i.produto)}<small>${i.qtd != null ? `${String(i.qtd).replace(".", ",")} ${esc(i.un || "")}` : ""}${i.unitario != null ? ` × ${preco(i.unitario)}` : ""}</small></span><b>${i.valor != null ? preco(i.valor) : ""}</b></div>`).join("")}</div>
      <div class="cmp-total-nota"><span>Total${c.desconto ? ` (desconto de ${preco(c.desconto)})` : ""}</span><b>${c.total != null ? preco(c.total) : ""}</b></div>
      <div class="cmp-detalhe-acoes">${c.url ? `<a class="link acao" href="${esc(c.url)}" target="_blank" rel="noopener">ver na Sefaz</a>` : ""}
        <button type="button" class="link" data-excluir-compra="${c.id}">Tirar do histórico</button></div>
    </div>`);
  });

  window.ABAS_MODULOS = { ...(window.ABAS_MODULOS || {}), "cmp-lista": carregarLista, "cmp-precos": carregarPrecos, "cmp-mercados": carregarMercados };
})();
