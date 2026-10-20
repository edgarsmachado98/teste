/* Módulo Distratos: cálculo (IGP-M), termo de distrato e aviso prévio em PDF e Word. */
(function () {
  'use strict';

  const C = window.EscalaContrato;
  const K = window.EscalaDistratoCalculo;
  const M = window.EscalaDistrato;
  const MEM = window.EscalaDistratoMemoria;
  const Doc = window.EscalaDocHTML;
  const api = window.EscalaApi;
  const App = window.EscalaApp;
  const $ = (sel) => document.querySelector(sel);
  const esc = App.esc;
  const dataBR = (iso) => (iso ? iso.split('-').reverse().join('/') : '');

  let usuario = null;
  let distratos = [];
  let contratos = [];
  let igpm = { meses: {}, manuais: [] };
  let atual = null;     // distrato em edição ({} = novo)
  let contrato = null;  // contrato do representante selecionado
  const valoresMes = {}; // 'AAAA-MM' -> texto digitado
  const podeEditar = () => !!usuario && usuario.perfil !== 'consulta';

  // ------------------------------------------------------------------ lista

  async function carregar() {
    try {
      [distratos, contratos, igpm] = await Promise.all([
        api.get('/api/distratos'), api.get('/api/contratos'), api.get('/api/indices/igpm'),
      ]);
    } catch (e) {
      if (e.status !== 401) App.avisar(e.message);
    }
    renderLista();
  }

  const nomeEmpresa = (r) => (r === 'alimentos' ? 'Antoniazzi Alimentos' : 'Antoniazzi & Cia');

  function renderLista() {
    const busca = $('#dt-busca').value.trim().toLowerCase();
    const dig = C.soDigitos(busca);
    const lista = distratos.filter((d) => !busca || (d.razao || '').toLowerCase().includes(busca) ||
      (dig && C.soDigitos(d.cnpj).includes(dig)));
    $('#dt-lista').innerHTML = lista.map((d) => `<tr>
        <td><b>${esc(d.razao)}</b></td><td>${esc(d.cnpj)}</td><td>${nomeEmpresa(d.representada)}</td>
        <td>${dataBR(d.dataDistrato)}</td><td class="num">R$ ${K.moeda(d.resultado.total)}</td>
        <td class="acoes">
          <button type="button" class="mini sec" data-acao="abrir" data-id="${d.id}">${podeEditar() ? 'Editar' : 'Ver'}</button>
          ${podeEditar() ? `<button type="button" class="mini perigo" data-acao="excluir" data-id="${d.id}">Excluir</button>` : ''}
        </td></tr>`).join('') ||
      `<tr><td colspan="6" class="vazio">${distratos.length ? 'Nenhum distrato encontrado.' : 'Nenhum distrato registrado.'}</td></tr>`;
  }

  $('#dt-busca').addEventListener('input', renderLista);
  $('#dt-novo').addEventListener('click', () => abrir({}));
  $('#dt-lista').addEventListener('click', async (ev) => {
    const b = ev.target.closest('button[data-acao]');
    if (!b) return;
    const d = distratos.find((x) => x.id === b.dataset.id);
    if (!d) return;
    if (b.dataset.acao === 'abrir') abrir(d);
    else if (await App.confirmar(`Excluir o distrato de ${d.razao} (${nomeEmpresa(d.representada)})?`)) {
      try { await api.del(`/api/distratos/${d.id}`); } catch (e) { App.avisar(e.message); }
      carregar();
    }
  });

  // ------------------------------------------------------------------ editor

  const form = $('#dt-form');
  const hoje = () => {
    const h = new Date();
    return `${h.getFullYear()}-${String(h.getMonth() + 1).padStart(2, '0')}-${String(h.getDate()).padStart(2, '0')}`;
  };

  function abrir(d) {
    atual = d;
    Object.keys(valoresMes).forEach((k) => delete valoresMes[k]);
    for (const c of d.comissoes || []) valoresMes[c.mes] = K.moeda(c.valor);
    contrato = d.contratoId ? contratos.find((c) => c.id === d.contratoId) || null : null;
    $('#dt-cnpj').value = contrato ? contrato.cnpj : '';
    form.querySelectorAll('input[name=representada]').forEach((r) => { r.checked = r.value === d.representada; });
    $('#dt-inicio').value = d.dataInicio || (contrato && contrato.dataContrato) || '';
    $('#dt-data').value = d.dataDistrato || hoje();
    $('#dt-data-aviso').value = d.dataAviso || d.dataDistrato || hoje();
    $('#dt-data-aviso').dataset.auto = d.dataAviso && d.dataAviso !== d.dataDistrato ? 'nao' : '';
    const per = (p, pref) => {
      $(`#dt-${pref}-inicio`).value = (p && p.inicio) || '';
      $(`#dt-${pref}-fim`).value = (p && p.fim) || '';
      $(`#dt-${pref}-valor`).value = p && p.valor !== '' && p.valor != null ? K.moeda(p.valor) : '';
    };
    per(d.pendentes, 'pend');
    per(d.aReceber, 'rec');
    $('#dt-pagar-indenizacao').checked = d.pagarIndenizacao !== false;
    $('#dt-pagar-aviso').checked = d.pagarAviso !== false;
    $('#dt-deflacao').checked = d.desconsiderarDeflacao !== false;
    $('#dt-profissao').value = d.profissao == null ? 'empresário' : d.profissao;
    $('#dt-estado-civil').value = d.estadoCivil || '';
    $('#dt-naturalidade').value = d.naturalidade || '';
    const docs = d.documentos && d.documentos.length ? d.documentos : ['distrato', 'aviso'];
    form.querySelectorAll('input[name=dt-documento]').forEach((x) => { x.checked = docs.includes(x.value); });
    $('#dt-titulo').textContent = d.id ? `Distrato — ${d.razao} (${nomeEmpresa(d.representada)})` : 'Novo distrato';
    form.querySelectorAll('input, select, textarea').forEach((el) => { el.disabled = !podeEditar(); });
    $('#dt-pendencias').hidden = true;
    $('#dt-lista-cartao').hidden = true;
    $('#dt-editor').hidden = false;
    renderRepresentante();
    renderMeses();
    atualizar();
    window.scrollTo(0, 0);
    if (podeEditar() && !contrato) $('#dt-cnpj').focus();
  }

  function fechar() {
    atual = null;
    contrato = null;
    $('#dt-editor').hidden = true;
    $('#dt-lista-cartao').hidden = false;
    renderLista();
  }
  $('#dt-voltar').addEventListener('click', fechar);

  // ------------------------------------------------- busca do representante

  $('#dt-cnpj').addEventListener('input', (ev) => { ev.target.value = C.formatarCNPJ(ev.target.value); });
  $('#dt-cnpj').addEventListener('keydown', (ev) => { if (ev.key === 'Enter') { ev.preventDefault(); buscar(); } });
  $('#dt-buscar').addEventListener('click', buscar);

  function buscar() {
    const dig = C.soDigitos($('#dt-cnpj').value);
    if (dig.length !== 14) return App.avisar('Informe o CNPJ completo do representante (14 dígitos).');
    const achados = contratos.filter((c) => C.soDigitos(c.cnpj) === dig)
      .sort((a, b) => (a.situacao === 'ativo' ? -1 : 1) - (b.situacao === 'ativo' ? -1 : 1) || String(b.dataContrato).localeCompare(a.dataContrato));
    if (!achados.length) {
      contrato = null;
      renderRepresentante('Nenhum contrato cadastrado com este CNPJ. Cadastre-o em Contratos de representantes.');
      return;
    }
    contrato = achados[0];
    if (!$('#dt-inicio').value || !atual.id) $('#dt-inicio').value = contrato.dataContrato || '';
    renderRepresentante();
    renderMeses();
    atualizar();
  }

  function renderRepresentante(msg) {
    const box = $('#dt-representante');
    box.hidden = false;
    if (!contrato) {
      box.innerHTML = msg ? `<p class="aviso">${esc(msg)}</p>` : '';
      box.hidden = !msg;
      return;
    }
    const pend = C.pendencias(contrato);
    box.innerHTML = `<dl class="dt-dados">
        <dt>Razão social</dt><dd>${esc(contrato.razao)}</dd>
        <dt>CNPJ</dt><dd>${esc(contrato.cnpj)}</dd>
        <dt>Responsável</dt><dd>${esc(contrato.responsavel || '—')} · CPF ${esc(contrato.cpf || '—')}</dd>
        <dt>Endereço</dt><dd>${esc(C.valores(contrato).endEmpresa || '—')}</dd>
        <dt>Contrato</dt><dd>desde ${dataBR(contrato.dataContrato) || '—'} · ${contrato.situacao === 'encerrado' ? 'encerrado' : 'ativo'}</dd>
      </dl>` + (pend.length ? `<p class="aviso">O cadastro deste contrato está incompleto (${pend.length} campo(s)). Complete-o em Contratos de representantes para gerar os documentos.</p>` : '');
  }

  // ------------------------------------------------------- comissões mensais

  function mesesDoPeriodo() {
    const ini = $('#dt-inicio').value;
    const fim = $('#dt-data').value;
    const lista = ini && fim ? K.listarMeses(K.mesDe(ini), K.mesDe(fim)) : [];
    // mantém meses já digitados fora do período, para não perder dados
    for (const m of Object.keys(valoresMes)) if (valoresMes[m] && !lista.includes(m)) lista.push(m);
    return lista.sort();
  }

  function renderMeses() {
    const meses = mesesDoPeriodo();
    $('#dt-meses').innerHTML = meses.map((m) => `<tr data-mes="${m}">
        <td>${K.rotuloMes(m)}</td>
        <td class="num"><input class="dt-valor" data-mes="${m}" inputmode="decimal" value="${esc(valoresMes[m] || '')}" aria-label="Comissão de ${K.rotuloMes(m)}"${podeEditar() ? '' : ' disabled'}></td>
        <td class="num dt-fator"></td><td class="num dt-atualizado"></td></tr>`).join('') ||
      '<tr><td colspan="4" class="vazio">Informe o início do contrato e a data do distrato.</td></tr>';
  }

  $('#dt-meses').addEventListener('input', (ev) => {
    if (ev.target.classList.contains('dt-valor')) {
      valoresMes[ev.target.dataset.mes] = ev.target.value;
      atualizar();
    }
  });
  $('#dt-meses').addEventListener('change', (ev) => {
    if (!ev.target.classList.contains('dt-valor')) return;
    const v = K.lerValor(ev.target.value);
    if (v != null) ev.target.value = K.moeda(v);
    valoresMes[ev.target.dataset.mes] = ev.target.value;
  });

  $('#dt-limpar-meses').addEventListener('click', async () => {
    if (!(await App.confirmar('Apagar os valores de comissão digitados?'))) return;
    Object.keys(valoresMes).forEach((k) => delete valoresMes[k]);
    renderMeses();
    atualizar();
  });

  const MESES_TXT = { jan: 1, fev: 2, mar: 3, abr: 4, mai: 5, jun: 6, jul: 7, ago: 8, set: 9, out: 10, nov: 11, dez: 12 };
  /** Lê o mês em formatos comuns de planilha: abr-24, abr/2024, 04/2024, 01/04/2024, 2024-04. */
  function lerMes(t) {
    t = String(t).trim().toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
    let m = /^([a-z]{3})[a-z]*[\s./-]*(\d{2}|\d{4})$/.exec(t);
    if (m && MESES_TXT[m[1]]) return `${m[2].length === 2 ? '20' + m[2] : m[2]}-${String(MESES_TXT[m[1]]).padStart(2, '0')}`;
    m = /^(?:\d{1,2}\/)?(\d{1,2})\/(\d{4})$/.exec(t);
    if (m) return `${m[2]}-${m[1].padStart(2, '0')}`;
    m = /^(\d{4})-(\d{1,2})/.exec(t);
    if (m) return `${m[1]}-${m[2].padStart(2, '0')}`;
    return null;
  }

  $('#dt-colar').addEventListener('click', async () => {
    const area = $('#dialogo-texto');
    const ok = await (async () => {
      const p = App.abrirDialogo('Cole as linhas da planilha com o mês e o valor da comissão (ex.: “abr-24  572,76” ou “04/2024;572,76”).',
        { cancelar: true, texto: '' });
      area.readOnly = false;
      area.value = '';
      $('#dialogo-copiar').hidden = true;
      area.focus();
      const r = await p;
      area.readOnly = true;
      return r;
    })();
    if (!ok) return;
    let n = 0;
    const ignoradas = [];
    for (const linha of area.value.split(/\r?\n/)) {
      if (!linha.trim()) continue;
      const partes = linha.split(/\t|;|\s{2,}/).map((x) => x.trim()).filter(Boolean);
      const mes = partes.length > 1 ? lerMes(partes[0]) : null;
      const valor = partes.length > 1 ? K.lerValor(partes[1]) : null;
      if (mes && valor != null) { valoresMes[mes] = K.moeda(valor); n++; } else ignoradas.push(linha.trim());
    }
    renderMeses();
    atualizar();
    App.avisar(`${n} mês(es) preenchido(s).` + (ignoradas.length ? `\nLinhas não reconhecidas: ${ignoradas.slice(0, 5).join(' | ')}` : ''));
  });

  // ------------------------------------------------------------------ cálculo

  function lerFormulario() {
    const rep = form.querySelector('input[name=representada]:checked');
    const per = (pref) => ({ inicio: $(`#dt-${pref}-inicio`).value, fim: $(`#dt-${pref}-fim`).value, valor: $(`#dt-${pref}-valor`).value });
    return {
      contratoId: contrato ? contrato.id : null,
      representada: rep ? rep.value : null,
      dataInicio: $('#dt-inicio').value,
      dataDistrato: $('#dt-data').value,
      dataAviso: $('#dt-data-aviso').value || $('#dt-data').value,
      comissoes: mesesDoPeriodo().map((m) => ({ mes: m, valor: valoresMes[m] || '' })).filter((c) => String(c.valor).trim()),
      pendentes: per('pend'),
      aReceber: per('rec'),
      pagarIndenizacao: $('#dt-pagar-indenizacao').checked,
      pagarAviso: $('#dt-pagar-aviso').checked,
      desconsiderarDeflacao: $('#dt-deflacao').checked,
      profissao: $('#dt-profissao').value,
      estadoCivil: $('#dt-estado-civil').value,
      naturalidade: $('#dt-naturalidade').value,
      documentos: [...form.querySelectorAll('input[name=dt-documento]:checked')].map((x) => x.value),
    };
  }

  let temporizador = null;
  function atualizar() {
    clearTimeout(temporizador);
    temporizador = setTimeout(recalcular, 100);
  }

  function recalcular() {
    const d = lerFormulario();
    const r = K.calcular(d, igpm.meses);
    // linhas da tabela de meses
    const porMes = Object.fromEntries(r.linhas.map((l) => [l.mes, l]));
    document.querySelectorAll('#dt-meses tr[data-mes]').forEach((tr) => {
      const l = porMes[tr.dataset.mes];
      tr.querySelector('.dt-fator').textContent = l ? `${((l.fator - 1) * 100).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}%` : '';
      tr.querySelector('.dt-atualizado').textContent = l ? K.moeda(l.atualizado) : '';
      tr.classList.toggle('dt-aviso-mes', r.mesesAviso.includes(tr.dataset.mes) && d.pagarAviso);
      tr.classList.toggle('dt-fora', r.foraDoPeriodo.includes(tr.dataset.mes));
    });
    $('#dt-soma-nominal').textContent = K.moeda(r.somaNominal);
    $('#dt-soma-atualizada').textContent = K.moeda(r.somaAtualizada);

    // status do índice
    $('#dt-indice-status').textContent = igpm.ultimoMes
      ? `IGP-M até ${K.rotuloMes(igpm.ultimoMes)}${igpm.atualizadoEm ? ` · Banco Central em ${new Date(igpm.atualizadoEm).toLocaleDateString('pt-BR')}` : ''}`
      : 'Tabela do IGP-M vazia — clique em “Atualizar IGP-M”.';
    const falt = $('#dt-faltando');
    falt.hidden = !r.indicesFaltando.length;
    falt.innerHTML = r.indicesFaltando.length ? `<p><b>Faltam ${r.indicesFaltando.length} mês(es) do IGP-M</b> para corrigir as comissões.
        ${podeEditar() ? 'Atualize pelo Banco Central ou informe a variação mensal (%) abaixo:' : 'Peça a um operador para atualizar o IGP-M.'}</p>` +
      (podeEditar() ? '<div class="dt-faltando-grade">' + r.indicesFaltando.slice(0, 24).map((m) =>
        `<label><span>${K.rotuloMes(m)}</span><input data-indice="${m}" inputmode="decimal" placeholder="0,00"></label>`).join('') + '</div>' : '') : '';

    // resultado
    const tile = (rotulo, valor, detalhe = '', cls = '') => `<div class="tile ${cls}"><span class="tile-rotulo">${rotulo}</span>` +
      `<span class="tile-valor">R$ ${K.moeda(valor)}</span><span class="tile-detalhe">${detalhe}</span></div>`;
    $('#dt-tiles').innerHTML =
      tile('Comissões atualizadas', r.somaAtualizada, `${r.linhas.length} mês(es) · nominal R$ ${K.moeda(r.somaNominal)}`) +
      tile('Indenização (1/12)', r.indenizacao, d.pagarIndenizacao ? `base R$ ${K.moeda(r.baseIndenizacao)} ÷ 12` : 'não paga') +
      tile('Aviso prévio', r.avisoPrevio, d.pagarAviso ? (r.mesesAviso.length ? `média de ${r.mesesAviso.map(K.rotuloMes).join(', ')}` : '—') : 'não pago') +
      tile('Títulos pendentes', r.pendentes, d.pendentes.inicio ? `${dataBR(d.pendentes.inicio)} a ${dataBR(d.pendentes.fim)}` : '') +
      tile('A receber', r.aReceber, d.aReceber.inicio ? `${dataBR(d.aReceber.inicio)} a ${dataBR(d.aReceber.fim)}` : '');
    $('#dt-total').innerHTML = `<span>Total líquido</span><b>R$ ${K.moeda(r.total)}</b><small>${esc(r.totalExtenso)}</small>`;

    // prévia dos documentos
    if (contrato && d.representada) {
      $('#dt-previa').innerHTML = Doc.renderizar(M.montar(contrato, d, r), M.valores(contrato, d, r), true);
      $('#dt-resumo-docs').textContent = `${d.documentos.length} documento(s) · ${nomeEmpresa(d.representada)}`;
    } else {
      $('#dt-previa').innerHTML = '<p class="vazio">Busque o representante pelo CNPJ e escolha a empresa representada para ver os documentos.</p>';
      $('#dt-resumo-docs').textContent = '';
    }
    if (!$('#dt-pendencias').hidden) mostrarPendencias(pendencias(d, r), false);
    return { d, r };
  }

  form.addEventListener('input', (ev) => {
    if (ev.target.closest('#dt-meses')) return;
    if (['dt-inicio', 'dt-data'].includes(ev.target.id)) renderMeses();
    if (ev.target.id === 'dt-data' && (!$('#dt-data-aviso').value || $('#dt-data-aviso').dataset.auto !== 'nao')) {
      $('#dt-data-aviso').value = ev.target.value;
    }
    if (ev.target.id === 'dt-data-aviso') ev.target.dataset.auto = 'nao';
    atualizar();
  });
  form.addEventListener('change', (ev) => {
    if (/-valor$/.test(ev.target.id)) {
      const v = K.lerValor(ev.target.value);
      if (v != null) ev.target.value = K.moeda(v);
    }
    atualizar();
  });

  // índices informados à mão para os meses que faltam
  $('#dt-faltando').addEventListener('change', async (ev) => {
    const mes = ev.target.dataset.indice;
    if (!mes || !ev.target.value.trim()) return;
    try {
      igpm = await api.put(`/api/indices/igpm/${mes}`, { valor: ev.target.value });
      atualizar();
    } catch (e) {
      App.avisar(e.message);
    }
  });

  $('#dt-atualizar-igpm').addEventListener('click', async (ev) => {
    const b = ev.currentTarget;
    b.disabled = true;
    b.textContent = 'Consultando o Banco Central…';
    try {
      igpm = await api.post('/api/indices/igpm/atualizar');
      atualizar();
    } catch (e) {
      App.avisar(e.message);
    } finally {
      b.disabled = false;
      b.textContent = 'Atualizar IGP-M (Banco Central)';
    }
  });

  // ------------------------------------------------------ salvar e gerar

  function pendencias(d, r) {
    const out = [];
    if (!contrato) out.push({ campo: 'dt-cnpj', mensagem: 'Busque o representante pelo CNPJ.' });
    else if (C.pendencias(contrato).length) out.push({ campo: 'dt-cnpj', mensagem: 'Complete o cadastro do contrato do representante.' });
    if (!d.representada) out.push({ campo: 'dt-representada', mensagem: 'Escolha a empresa representada.' });
    if (!d.dataInicio) out.push({ campo: 'dt-inicio', mensagem: 'Informe o início do contrato.' });
    if (!d.dataDistrato) out.push({ campo: 'dt-data', mensagem: 'Informe a data do distrato.' });
    if (!r.linhas.length) out.push({ campo: 'dt-meses', mensagem: 'Informe as comissões recebidas em pelo menos um mês.' });
    if (r.indicesFaltando.length) out.push({ campo: 'dt-faltando', mensagem: `Faltam índices do IGP-M (${r.indicesFaltando.map(K.rotuloMes).join(', ')}).` });
    if (r.foraDoPeriodo.length) {
      out.push({ campo: 'dt-meses', mensagem: `Há comissões depois da data do distrato (${r.foraDoPeriodo.map(K.rotuloMes).join(', ')}); elas não entram no cálculo. Corrija ou apague esses valores.` });
    }
    for (const [pref, nome] of [['pend', 'títulos pendentes'], ['rec', 'comissões a receber']]) {
      const p = pref === 'pend' ? d.pendentes : d.aReceber;
      if (K.lerValor(p.valor) && (!p.inicio || !p.fim)) out.push({ campo: `dt-${pref}-inicio`, mensagem: `Informe o período das ${nome}.` });
    }
    if (!d.documentos.length) out.push({ campo: 'dt-documento', mensagem: 'Escolha ao menos um documento.' });
    return out;
  }

  function mostrarPendencias(lista, focar = true) {
    const box = $('#dt-pendencias');
    box.hidden = !lista.length;
    box.innerHTML = lista.length ? `<b>Antes de gerar os documentos:</b><ul>${lista.map((p) => `<li>${esc(p.mensagem)}</li>`).join('')}</ul>` : '';
    if (lista.length && focar) {
      const el = document.getElementById(lista[0].campo);
      if (el && el.focus) el.focus();
    }
  }

  async function salvar() {
    const d = lerFormulario();
    const salvo = atual && atual.id ? await api.put(`/api/distratos/${atual.id}`, d) : await api.post('/api/distratos', d);
    atual = salvo;
    $('#dt-titulo').textContent = `Distrato — ${salvo.razao} (${nomeEmpresa(salvo.representada)})`;
    distratos = await api.get('/api/distratos');
    return salvo;
  }

  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    if (!podeEditar()) return;
    try {
      await salvar();
      App.avisar('Distrato salvo.');
    } catch (e) {
      App.avisar(e.message);
    }
  });

  async function preparar(formato) {
    const { d, r } = recalcular();
    const pend = pendencias(d, r);
    mostrarPendencias(pend);
    if (pend.length) return null;
    try {
      if (podeEditar()) await salvar();
      if (atual && atual.id) await api.post(`/api/distratos/${atual.id}/documento`, { formato });
    } catch (e) {
      App.avisar(e.message);
      return null;
    }
    return { docs: M.montar(contrato, d, r), vals: M.valores(contrato, d, r), d };
  }

  $('#dt-pdf').addEventListener('click', async () => {
    const g = await preparar('pdf');
    if (g) Doc.imprimir(g.docs, g.vals, M.nomeArquivo(contrato, g.d, 'pdf'));
  });
  $('#dt-docx').addEventListener('click', async () => {
    const g = await preparar('docx');
    if (!g) return;
    try {
      await Doc.baixarWord(g.docs, g.vals, M.nomeArquivo(contrato, g.d, 'docx'));
    } catch (e) {
      App.avisar(e.message);
    }
  });

  // ------------------------------------------------------- memória de cálculo

  async function prepararMemoria(formato) {
    const { d, r } = recalcular();
    const falta = [];
    if (!contrato) falta.push('busque o representante pelo CNPJ');
    if (!d.representada) falta.push('escolha a empresa representada');
    if (!d.dataDistrato) falta.push('informe a data do distrato');
    if (!r.linhas.length) falta.push('informe as comissões mensais');
    if (falta.length) { App.avisar(`Para gerar a memória de cálculo, ${falta.join(', ')}.`); return null; }
    if (r.indicesFaltando.length && !(await App.confirmar(`Faltam ${r.indicesFaltando.length} mês(es) do IGP-M; a correção ficará incompleta. ` +
      'Gerar a memória mesmo assim?'))) return null;
    try {
      if (podeEditar()) await salvar();
      if (atual && atual.id) await api.post(`/api/distratos/${atual.id}/documento`, { formato });
    } catch (e) {
      App.avisar(e.message);
      return null;
    }
    const empresa = M.EMPRESAS[d.representada];
    return { m: MEM.montar(contrato, d, r, igpm.meses, { nome: empresa.nome, cnpj: empresa.cnpj }), d };
  }
  const nomeMemoria = (d, ext) => M.nomeArquivo(contrato, d, ext).replace(/^Distrato_/, 'Memoria_calculo_distrato_');

  $('#dt-memoria-pdf').addEventListener('click', async () => {
    const g = await prepararMemoria('memoria-pdf');
    if (!g) return;
    const area = $('#impressao');
    area.innerHTML = MEM.html(g.m);
    const titulo = document.title;
    document.title = nomeMemoria(g.d, 'pdf').replace(/\.pdf$/, '');
    document.body.classList.add('imprimindo', 'imprimindo-memoria');
    const terminar = () => {
      document.body.classList.remove('imprimindo', 'imprimindo-memoria');
      area.innerHTML = '';
      document.title = titulo;
      window.removeEventListener('afterprint', terminar);
    };
    window.addEventListener('afterprint', terminar);
    window.print();
  });

  $('#dt-memoria-xlsx').addEventListener('click', async () => {
    const g = await prepararMemoria('memoria-xlsx');
    if (!g) return;
    const blob = new Blob([MEM.xlsx(g.m)], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
    const url = URL.createObjectURL(blob);
    const a = Object.assign(document.createElement('a'), { href: url, download: nomeMemoria(g.d, 'xlsx') });
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  });

  // clicar num dado destacado na prévia leva ao campo correspondente
  $('#dt-previa').addEventListener('click', (ev) => {
    const m = ev.target.closest('mark[data-campo]');
    if (!m) return;
    const alvo = { profissao: 'dt-profissao', estadoCivil: 'dt-estado-civil', naturalidade: 'dt-naturalidade',
      dataInicio: 'dt-inicio', dataDistrato: 'dt-data', dataAviso: 'dt-data-aviso', pendentes: 'dt-pend-valor',
      periodoPendentes: 'dt-pend-inicio', aReceber: 'dt-rec-valor', periodoReceber: 'dt-rec-inicio' }[m.dataset.campo];
    const el = alvo ? document.getElementById(alvo) : null;
    if (el) { el.focus(); el.scrollIntoView({ block: 'center', behavior: 'smooth' }); }
    else App.avisar('Este dado vem do cadastro do contrato (Contratos de representantes) ou do cálculo.');
  });

  // ------------------------------------------------------------ ciclo de vida

  window.addEventListener('app-iniciado', (ev) => {
    usuario = ev.detail;
    fechar();
    carregar();
  });
  window.addEventListener('app-encerrado', () => {
    usuario = null;
    distratos = [];
    contratos = [];
    fechar();
  });
  document.querySelector('.modulo[data-modulo=distratos]').addEventListener('click', () => { if (usuario && !atual) carregar(); });
})();
