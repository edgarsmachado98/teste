/* Módulo Relatórios: distratos salvos (com o resultado gravado) e contratos de representantes, com pesquisa e exportação. */
(function () {
  'use strict';

  const C = window.EscalaContrato;
  const K = window.EscalaDistratoCalculo;
  const api = window.EscalaApi;
  const App = window.EscalaApp;
  const $ = (sel) => document.querySelector(sel);
  const esc = App.esc;
  const dataBR = (iso) => (iso ? iso.slice(0, 10).split('-').reverse().join('/') : '');
  const dataHora = (iso) => (iso ? new Date(iso).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' }) : '');
  const nomeEmpresa = (r) => (r === 'alimentos' ? 'Antoniazzi Alimentos' : 'Antoniazzi & Cia');
  const sem = (s) => String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
  const contem = (valor, busca) => !busca || sem(valor).includes(sem(busca));
  const contemCnpj = (cnpj, busca) => !C.soDigitos(busca) || C.soDigitos(cnpj).includes(C.soDigitos(busca));

  let usuario = null;
  let distratos = [];
  let contratos = [];

  async function carregar() {
    try {
      [distratos, contratos] = await Promise.all([api.get('/api/distratos'), api.get('/api/contratos')]);
    } catch (e) {
      if (e.status !== 401) App.avisar(e.message);
    }
    renderDistratos();
    renderContratos();
  }

  // ---------------------------------------------------------------- distratos

  /** Valores gravados ao salvar; distratos salvos antes desta versão usam o cálculo atual. */
  function valores(d) {
    const s = d.resultadoSalvo;
    if (s) return s;
    const r = d.resultado || {};
    return {
      indenizacao: r.indenizacao, avisoPrevio: r.avisoPrevio, pendentes: r.pendentes, aReceber: r.aReceber,
      ir: r.ir ? r.ir.total : 0, liquido: r.liquido == null ? r.total : r.liquido, salvoEm: d.atualizadoEm, salvoPor: d.criadoPor,
    };
  }

  function filtrarDistratos() {
    const f = { razao: $('#rd-razao').value.trim(), cnpj: $('#rd-cnpj').value.trim(), empresa: $('#rd-empresa').value, cidade: $('#rd-cidade').value.trim() };
    return distratos.filter((d) => contem(d.razao, f.razao) && contemCnpj(d.cnpj, f.cnpj) &&
      (!f.empresa || d.representada === f.empresa) && contem(d.cidade, f.cidade))
      .sort((a, b) => String(b.dataDistrato).localeCompare(String(a.dataDistrato)) || String(a.razao).localeCompare(String(b.razao)));
  }

  const COLS_D = [
    ['Representante', (d) => d.razao, 34],
    ['CNPJ', (d) => d.cnpj, 20],
    ['Empresa representada', (d) => nomeEmpresa(d.representada), 22],
    ['Cidade', (d) => [d.cidade, d.uf].filter(Boolean).join('-'), 20],
    ['Data do distrato', (d) => dataBR(d.dataDistrato), 14],
    ['Indenização (1/12)', (d) => valores(d).indenizacao, 16, true],
    ['Aviso prévio', (d) => valores(d).avisoPrevio, 14, true],
    ['Títulos pendentes', (d) => valores(d).pendentes, 15, true],
    ['A receber', (d) => valores(d).aReceber, 14, true],
    ['IR retido', (d) => valores(d).ir, 12, true],
    ['Total líquido', (d) => valores(d).liquido, 15, true],
    ['Salvo em', (d) => dataHora(valores(d).salvoEm), 16],
  ];
  const moeda = (v) => `R$ ${K.moeda(Number(v) || 0)}`;
  const soma = (lista, i) => lista.reduce((s, d) => s + (Number(COLS_D[i][1](d)) || 0), 0);

  function renderDistratos() {
    const lista = filtrarDistratos();
    $('#rd-resumo').textContent = `· ${lista.length} de ${distratos.length}`;
    $('#rd-lista').innerHTML = lista.map((d) => `<tr>${COLS_D.map(([, f, , num], i) =>
      `<td${num ? ' class="num"' : ''}>${i === 0 ? `<b>${esc(f(d))}</b>` : esc(num ? moeda(f(d)) : f(d))}</td>`).join('')}
        <td class="acoes"><button type="button" class="mini sec" data-distrato="${d.id}">Exibir</button></td></tr>`).join('') ||
      `<tr><td colspan="${COLS_D.length + 1}" class="vazio">${distratos.length ? 'Nenhum distrato encontrado com essa pesquisa.' : 'Nenhum distrato salvo.'}</td></tr>`;
    $('#rd-total').innerHTML = lista.length > 1 ? `<tr><td colspan="5">Total (${lista.length} distratos)</td>${
      COLS_D.slice(5, 11).map((c, j) => `<td class="num">${moeda(soma(lista, j + 5))}</td>`).join('')}<td colspan="2"></td></tr>` : '';
  }
  ['#rd-razao', '#rd-cnpj', '#rd-empresa', '#rd-cidade'].forEach((s) => $(s).addEventListener('input', renderDistratos));
  $('#rd-cnpj').addEventListener('input', (ev) => { ev.target.value = C.formatarCNPJ(ev.target.value); });

  $('#rd-lista').addEventListener('click', async (ev) => {
    const b = ev.target.closest('button[data-distrato]');
    if (!b) return;
    App.mostrarModulo('distratos');
    await window.EscalaDistratosUI.abrirPorId(b.dataset.distrato, true, 'rel-distratos');
  });

  // ---------------------------------------------------------------- contratos

  function filtrarContratos() {
    const f = { razao: $('#rc-razao').value.trim(), cnpj: $('#rc-cnpj').value.trim(), cidade: $('#rc-cidade').value.trim() };
    return contratos.filter((c) => contem(c.razao, f.razao) && contemCnpj(c.cnpj, f.cnpj) && contem(c.cidade, f.cidade))
      .sort((a, b) => String(a.razao).localeCompare(String(b.razao)));
  }
  const distratosDe = (c) => distratos.filter((d) => d.contratoId === c.id);

  const COLS_C = [
    ['Representante', (c) => c.razao, 34],
    ['CNPJ', (c) => c.cnpj, 20],
    ['Cidade', (c) => [c.cidade, c.uf].filter(Boolean).join('-'), 20],
    ['Estado de atuação', (c) => C.listaEstados(c.estados).join(', '), 14],
    ['Data do contrato', (c) => dataBR(c.dataContrato), 14],
    ['Situação', (c) => (c.situacao === 'encerrado' ? 'Encerrado' : 'Ativo'), 12],
    ['Distratos', (c) => distratosDe(c).map((d) => `${nomeEmpresa(d.representada)} (${dataBR(d.dataDistrato)})`).join('; '), 40],
  ];

  function renderContratos() {
    const lista = filtrarContratos();
    $('#rc-resumo').textContent = `· ${lista.length} de ${contratos.length}`;
    $('#rc-lista').innerHTML = lista.map((c) => `<tr>
        <td><b>${esc(c.razao)}</b></td><td>${esc(c.cnpj)}</td><td>${esc(COLS_C[2][1](c))}</td><td>${esc(COLS_C[3][1](c))}</td>
        <td>${esc(COLS_C[4][1](c))}</td>
        <td>${c.situacao === 'encerrado' ? '<span class="chip">Encerrado</span>' : '<span class="chip bom">Ativo</span>'}</td>
        <td>${distratosDe(c).map((d) => `<button type="button" class="mini sec" data-distrato="${d.id}">${esc(nomeEmpresa(d.representada))}</button>`).join(' ') ||
          '<small class="suave">—</small>'}</td>
        <td class="acoes"><button type="button" class="mini sec" data-contrato="${c.id}">Exibir</button></td></tr>`).join('') ||
      `<tr><td colspan="8" class="vazio">${contratos.length ? 'Nenhum contrato encontrado com essa pesquisa.' : 'Nenhum contrato cadastrado.'}</td></tr>`;
  }
  ['#rc-razao', '#rc-cnpj', '#rc-cidade'].forEach((s) => $(s).addEventListener('input', renderContratos));
  $('#rc-cnpj').addEventListener('input', (ev) => { ev.target.value = C.formatarCNPJ(ev.target.value); });

  $('#rc-lista').addEventListener('click', async (ev) => {
    const b = ev.target.closest('button[data-contrato], button[data-distrato]');
    if (!b) return;
    if (b.dataset.contrato) {
      App.mostrarModulo('contratos');
      await window.EscalaContratosUI.abrirPorId(b.dataset.contrato, true, 'rel-contratos');
    } else {
      App.mostrarModulo('distratos');
      await window.EscalaDistratosUI.abrirPorId(b.dataset.distrato, true, 'rel-contratos');
    }
  });

  // ---------------------------------------------------------------- exportação

  const hoje = () => new Date().toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' });

  async function logo() {
    try {
      const r = await fetch('img/logo-moinho-santa-maria.png');
      if (r.ok) return { bytes: new Uint8Array(await r.arrayBuffer()), largura: 170, altura: 198 };
    } catch (e) { /* sem logotipo */ }
    return null;
  }

  async function exportarXlsx(titulo, cols, lista, arquivo) {
    const bytes = window.EscalaDistratoMemoria.tabelaXlsx({
      titulo, subtitulo: `${lista.length} registro(s) · emitido em ${hoje()}`,
      cabecalho: cols.map((c) => c[0]), larguras: cols.map((c) => c[2]),
      linhas: lista.map((x) => cols.map(([, f, , num]) => (num ? Number(f(x)) || 0 : f(x)))),
      moeda: cols.map((c, i) => (c[3] ? i : -1)).filter((i) => i >= 0), logo: await logo(), nomeAba: 'Relatório',
    });
    App.baixar(`${arquivo}_${new Date().toISOString().slice(0, 10)}.xlsx`, bytes,
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet');
  }

  function imprimir(titulo, cols, lista) {
    const area = $('#impressao');
    area.innerHTML = `<div class="rl-impressao"><header class="rl-cab">
        <img src="img/logo-moinho-santa-maria.png" alt="" width="60" height="70">
        <div><h1>${esc(titulo)}</h1><p>${lista.length} registro(s) · emitido em ${esc(hoje())}</p></div></header>
      <table class="tabela rl-tabela"><thead><tr>${cols.map((c) => `<th>${esc(c[0])}</th>`).join('')}</tr></thead>
      <tbody>${lista.map((x) => `<tr>${cols.map(([, f, , num]) => `<td${num ? ' class="num"' : ''}>${esc(num ? moeda(f(x)) : f(x))}</td>`).join('')}</tr>`).join('') ||
        `<tr><td colspan="${cols.length}" class="vazio">Nenhum registro.</td></tr>`}</tbody></table></div>`;
    const tituloPagina = document.title;
    document.title = titulo;
    document.body.classList.add('imprimindo', 'imprimindo-relatorio');
    const terminar = () => {
      document.body.classList.remove('imprimindo', 'imprimindo-relatorio');
      area.innerHTML = '';
      document.title = tituloPagina;
      window.removeEventListener('afterprint', terminar);
    };
    window.addEventListener('afterprint', terminar);
    const img = area.querySelector('img');
    if (img.complete) window.print(); else { img.onload = () => window.print(); img.onerror = () => window.print(); }
  }

  $('#rd-xlsx').addEventListener('click', () => exportarXlsx('Relatório de distratos', COLS_D, filtrarDistratos(), 'relatorio_distratos'));
  $('#rd-pdf').addEventListener('click', () => imprimir('Relatório de distratos', COLS_D, filtrarDistratos()));
  $('#rc-xlsx').addEventListener('click', () => exportarXlsx('Contratos de representantes', COLS_C, filtrarContratos(), 'relatorio_contratos'));
  $('#rc-pdf').addEventListener('click', () => imprimir('Contratos de representantes', COLS_C, filtrarContratos()));

  window.addEventListener('app-iniciado', (ev) => { usuario = ev.detail; });
  window.addEventListener('app-encerrado', () => { usuario = null; distratos = []; contratos = []; });
  document.querySelectorAll('.modulo[data-modulo=relatorios], .aba[data-modulo=relatorios]')
    .forEach((b) => b.addEventListener('click', () => { if (usuario) carregar(); }));
})();
