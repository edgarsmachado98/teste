/* Módulo Contratos de representantes: cadastro, prévia e geração em PDF e Word. */
(function () {
  'use strict';

  const C = window.EscalaContrato;
  const api = window.EscalaApi;
  const App = window.EscalaApp;
  const $ = (sel) => document.querySelector(sel);
  const esc = App.esc;

  let usuario = null;
  let contratos = [];
  let empresas = []; // cadastro de empresas: as representadas definem os documentos legais disponíveis
  let atual = null; // contrato em edição ({} = novo)
  const podeEditar = () => !!usuario && usuario.perfil !== 'consulta';
  let exibindo = false; // aberto com "Exibir": só leitura
  const editavel = () => podeEditar() && !exibindo;

  const Doc = window.EscalaDocHTML;
  const documentoHTML = (dados, editavel) => Doc.renderizar(C.montar(dados), C.valores(dados), editavel);

  // ---------------------------------------------------------------- lista

  async function carregarEmpresas() {
    try {
      empresas = await api.get('/api/empresas');
    } catch (e) {
      empresas = [];
    }
  }

  async function carregar() {
    carregarEmpresas();
    try {
      contratos = await api.get('/api/contratos');
    } catch (e) {
      if (e.status !== 401) App.avisar(e.message);
      contratos = [];
    }
    renderLista();
  }

  /** Contratos com a busca e o filtro de situação da tela (a mesma lista exportada). */
  function listaFiltrada() {
    const busca = $('#ct-busca').value.trim().toLowerCase();
    const digitos = C.soDigitos(busca);
    const filtro = $('#ct-filtro').value;
    return contratos.filter((c) => (!filtro || c.situacao === filtro) &&
      (!busca || (c.razao || '').toLowerCase().includes(busca) || (c.responsavel || '').toLowerCase().includes(busca) ||
        (c.codigo || '').toLowerCase() === busca ||
        (digitos && C.soDigitos(c.cnpj).includes(digitos))));
  }

  function renderLista() {
    const lista = listaFiltrada();
    $('#ct-lista').innerHTML = lista.map((c) => `<tr>
        <td><b>${esc(c.razao)}</b><br><small class="suave">${c.codigo ? `Cód. ${esc(c.codigo)} · ` : ''}${esc(c.responsavel || '')}</small></td>
        <td>${esc(c.cnpj)}</td>
        <td>${esc([c.cidade, c.uf].filter(Boolean).join('-'))}${c.estados ? `<br><small class="suave">atuação: ${esc(C.listaEstados(c.estados).join(', '))}</small>` : ''}</td>
        <td>${esc((c.zona || '').split('\n')[0])}</td>
        <td>${esc(C.dataBR(c.dataContrato))}</td>
        <td>${c.situacao === 'encerrado' ? '<span class="chip">Encerrado</span>' : '<span class="chip bom">Ativo</span>'}
          ${c.pendencias ? `<span class="chip breve" title="Faltam dados para gerar o documento">${c.pendencias} pendência(s)</span>` : ''}</td>
        <td class="acoes">
          <button type="button" class="mini sec" data-acao="exibir" data-id="${c.id}">Exibir</button>
          ${podeEditar() ? `<button type="button" class="mini sec" data-acao="abrir" data-id="${c.id}">Editar</button>` : ''}
          ${podeEditar() ? `<button type="button" class="mini perigo" data-acao="excluir" data-id="${c.id}">Excluir</button>` : ''}
        </td></tr>`).join('') ||
      `<tr><td colspan="7" class="vazio">${contratos.length ? 'Nenhum contrato encontrado.' : 'Nenhum contrato cadastrado.'}</td></tr>`;
  }

  $('#ct-busca').addEventListener('input', renderLista);
  $('#ct-filtro').addEventListener('change', renderLista);
  $('#ct-novo').addEventListener('click', () => abrir({}));

  // ------------------------------------------------------- exportar lista

  const COLUNAS_EXPORT = [
    ['codigo', 'Código', 10], ['razao', 'Representante', 34], ['responsavel', 'Responsável', 26], ['cnpj', 'CNPJ', 19],
    ['cidade', 'Cidade/UF', 20], ['estados', 'Estado de atuação', 12], ['zona', 'Zona de influência', 34],
    ['dataContrato', 'Data do contrato', 12], ['situacao', 'Situação', 11],
  ];
  const valorExport = (c, k) => ({
    cidade: [c.cidade, c.uf].filter(Boolean).join('-'), estados: C.listaEstados(c.estados).join(', '),
    zona: String(c.zona || '').replace(/\s*\n\s*/g, '; '), dataContrato: C.dataBR(c.dataContrato),
    situacao: c.situacao === 'encerrado' ? 'Encerrado' : 'Ativo',
  }[k] ?? (c[k] || ''));

  function descricaoFiltro() {
    const filtro = { '': 'todos', ativo: 'ativos', encerrado: 'encerrados' }[$('#ct-filtro').value];
    const busca = $('#ct-busca').value.trim();
    return `Situação: ${filtro}${busca ? ` · busca: "${busca}"` : ''}`;
  }

  function baixarArquivo(nome, conteudo, tipo) {
    const url = URL.createObjectURL(new Blob([conteudo], { type: tipo }));
    const a = Object.assign(document.createElement('a'), { href: url, download: nome });
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  }

  function exportarPDF(lista, quando) {
    const area = $('#impressao');
    area.innerHTML = `<div class="rl-impressao"><header class="rl-cab">
        <img src="img/logo-moinho-santa-maria.png" alt="" width="60" height="70">
        <div><h1>Representantes comerciais</h1><p>${esc(descricaoFiltro())} · ${lista.length} representante(s) · emitido em ${esc(quando)}</p></div></header>
      <table class="tabela rl-tabela"><thead><tr>${COLUNAS_EXPORT.map(([, n]) => `<th>${esc(n)}</th>`).join('')}</tr></thead>
      <tbody>${lista.map((c) => `<tr>${COLUNAS_EXPORT.map(([k]) => `<td>${esc(valorExport(c, k))}</td>`).join('')}</tr>`).join('') ||
        `<tr><td colspan="${COLUNAS_EXPORT.length}" class="vazio">Nenhum representante.</td></tr>`}</tbody></table></div>`;
    const titulo = document.title;
    document.title = 'Representantes';
    document.body.classList.add('imprimindo', 'imprimindo-relatorio');
    const terminar = () => {
      document.body.classList.remove('imprimindo', 'imprimindo-relatorio');
      area.innerHTML = '';
      document.title = titulo;
      window.removeEventListener('afterprint', terminar);
    };
    window.addEventListener('afterprint', terminar);
    const img = area.querySelector('img');
    if (img.complete) window.print(); else { img.onload = () => window.print(); img.onerror = () => window.print(); }
  }

  async function exportarXlsx(lista, quando) {
    let logo = null;
    try {
      const r = await fetch('img/logo-moinho-santa-maria.png');
      if (r.ok) logo = { bytes: new Uint8Array(await r.arrayBuffer()), largura: 170, altura: 198 };
    } catch (e) { /* sem logotipo */ }
    const bytes = window.EscalaDistratoMemoria.tabelaXlsx({
      titulo: 'Representantes comerciais', subtitulo: `${descricaoFiltro()} · ${lista.length} representante(s) · emitido em ${quando}`,
      cabecalho: COLUNAS_EXPORT.map(([, n]) => n), larguras: COLUNAS_EXPORT.map(([, , w]) => w),
      linhas: lista.map((c) => COLUNAS_EXPORT.map(([k]) => valorExport(c, k))), logo, nomeAba: 'Representantes',
    });
    baixarArquivo(`representantes_${new Date().toISOString().slice(0, 10)}.xlsx`, bytes,
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet');
  }

  function exportarXml(lista) {
    const x = (v) => String(v == null ? '' : v).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    const campos = ['codigo', 'razao', 'fantasia', 'cnpj', 'responsavel', 'cpf', 'endereco', 'bairro', 'cidade', 'uf', 'cep', 'zona', 'dataContrato'];
    const corpo = lista.map((c) => `  <representante situacao="${c.situacao === 'encerrado' ? 'encerrado' : 'ativo'}">\n` +
      campos.map((k) => `    <${k}>${x(c[k])}</${k}>`).join('\n') +
      `\n    <estadosAtuacao>${C.listaEstados(c.estados).map((e) => `<estado>${e}</estado>`).join('')}</estadosAtuacao>\n  </representante>`).join('\n');
    const xml = `<?xml version="1.0" encoding="UTF-8"?>\n<representantes geradoEm="${new Date().toISOString()}" ` +
      `filtro="${x(descricaoFiltro())}" total="${lista.length}">\n${corpo}\n</representantes>\n`;
    baixarArquivo(`representantes_${new Date().toISOString().slice(0, 10)}.xml`, xml, 'application/xml;charset=utf-8');
  }

  $('#ct-exportar').addEventListener('click', () => {
    const lista = listaFiltrada();
    if (!lista.length) return App.avisar('Nenhum representante na lista para exportar.');
    const dlg = $('#dialogo-exportar');
    $('#exp-resumo').textContent = `${lista.length} representante(s), como na tela (${descricaoFiltro()}).`;
    dlg.onclose = async () => {
      if (dlg.returnValue !== 'ok') return;
      const formato = (dlg.querySelector('input[name=exp-formato]:checked') || {}).value;
      const quando = new Date().toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' });
      try {
        if (formato === 'pdf') exportarPDF(lista, quando);
        else if (formato === 'xlsx') await exportarXlsx(lista, quando);
        else exportarXml(lista);
      } catch (e) {
        App.avisar(e.message);
      }
    };
    dlg.returnValue = '';
    dlg.showModal();
  });

  $('#ct-lista').addEventListener('click', async (ev) => {
    const b = ev.target.closest('button[data-acao]');
    if (!b) return;
    const c = contratos.find((x) => x.id === b.dataset.id);
    if (!c) return;
    if (b.dataset.acao === 'abrir' || b.dataset.acao === 'exibir') abrir(c, b.dataset.acao === 'exibir');
    else if (b.dataset.acao === 'excluir') {
      if (!(await App.confirmar(`Excluir o contrato de ${c.razao}? Esta ação não pode ser desfeita.`))) return;
      try {
        await api.del(`/api/contratos/${c.id}`);
      } catch (e) {
        App.avisar(e.message);
      }
      carregar();
    }
  });

  // -------------------------------------------------------------- formulário

  const form = $('#ct-form');
  const GRUPOS = { empresa: '#ct-grupo-empresa', responsavel: '#ct-grupo-responsavel', residencia: '#ct-grupo-residencia', contrato: '#ct-grupo-contrato' };

  function campoHTML(c) {
    const id = `ct-${c.id}`;
    const obrig = c.obrig ? '<span class="obrig" aria-hidden="true"> *</span>' : '';
    const rot = `<span>${esc(c.rotulo)}${obrig}</span>`;
    const dica = c.dica ? `<small class="dica">${esc(c.dica)}</small>` : '';
    const largo = ['endereco', 'resEndereco', 'razao', 'responsavel', 'zona'].includes(c.id) ? ' largo' : '';
    switch (c.tipo) {
      case 'estados':
        return `<fieldset class="largo ct-estados" id="${id}"><legend>${esc(c.rotulo)}${obrig}</legend>` +
          C.ESTADOS_ATUACAO.map((e) => `<label class="check"><input type="radio" name="ct-estado" data-estado="${e.uf}"> ${esc(e.nome)} (${e.uf})</label>`).join('') +
          '<small class="dica largo" id="ct-modelo-regiao">Fica só no cadastro (não aparece no contrato). São Paulo usa o modelo com a ' +
          'Antoniazzi Alimentos; Rio Grande do Sul e Santa Catarina usam o modelo só da Antoniazzi &amp; Cia.</small></fieldset>';
      case 'check':
        return `<label class="check largo"><input type="checkbox" id="${id}" data-campo="${c.id}"> ${esc(c.rotulo)}</label>`;
      case 'uf':
        return `<label>${rot}<select id="${id}" data-campo="${c.id}"><option value=""></option>` +
          C.UFS.map((u) => `<option>${u}</option>`).join('') + '</select></label>';
      case 'sexo':
        return `<label>${rot}<select id="${id}" data-campo="${c.id}">` +
          '<option value="M">Masculino</option><option value="F">Feminino</option></select></label>';
      case 'data':
        return `<label>${rot}<input type="date" id="${id}" data-campo="${c.id}"></label>`;
      case 'texto':
        return `<label class="largo">${rot}<textarea id="${id}" data-campo="${c.id}" rows="2" maxlength="${c.max}"></textarea>${dica}</label>`;
      default: {
        const modo = { cpf: ' inputmode="numeric" placeholder="000.000.000-00"', cnpj: ' inputmode="numeric" placeholder="00.000.000/0000-00"', cep: ' inputmode="numeric" placeholder="00.000-000"' }[c.tipo] || '';
        return `<label class="${largo.trim()}">${rot}<input id="${id}" data-campo="${c.id}"${modo}` +
          (c.max ? ` maxlength="${c.max}"` : '') + ' autocomplete="off">' + dica + '</label>';
      }
    }
  }

  for (const [grupo, sel] of Object.entries(GRUPOS)) {
    $(sel).innerHTML = C.CAMPOS.filter((c) => c.grupo === grupo).map(campoHTML).join('');
  }
  const estadosMarcados = () => [...form.querySelectorAll('#ct-estados input[data-estado]:checked')].map((x) => x.dataset.estado).join(',');

  /** Lista de documentos legais conforme o estado de atuação, mantendo o que estava marcado. */
  const CNPJS_MODELO = C.DOCUMENTOS.filter((x) => x.empresa).map((x) => x.empresa);
  // documento embutido de uma empresa cadastrada e não marcada como representada fica fora da lista
  const docVisivel = (x) => !x.empresa || !empresas.some((e) => e.cnpj === x.empresa && !e.representada);
  /** Modelos de contrato anexados pelas demais empresas representadas ('arq:<id>'). */
  const anexos = () => empresas.filter((e) => e.representada && !CNPJS_MODELO.includes(e.cnpj)).map((e) => ({
    empresa: e,
    modelos: (e.arquivos || []).filter((a) => a.tipo === 'contrato').map((a) => ({ valor: `arq:${a.id}`, arquivo: a })),
  }));

  function renderDocumentos(marcados) {
    const d = { estados: estadosMarcados() };
    const reg = C.regiao(d);
    const atuais = marcados || [...form.querySelectorAll('input[name=documento]')].filter((x) => x.checked).map((x) => x.value);
    const antes = [...form.querySelectorAll('input[name=documento]')].map((x) => x.value);
    const lista = C.documentosDaRegiao(d).filter(docVisivel);
    const caixa = (valor, nome, marcado) =>
      `<label class="check"><input type="checkbox" name="documento" value="${esc(valor)}"${marcado ? ' checked' : ''}${editavel() ? '' : ' disabled'}> ${esc(nome)}</label>`;
    $('#ct-documentos').innerHTML = lista.map((x) =>
      // documento que aparece agora (ex.: contrato da Alimentos ao marcar SP) já vem marcado
      caixa(x.id, x.nome, atuais.includes(x.id) || (!marcados && !antes.includes(x.id)))).join('') +
      anexos().map((g) => `<div class="ct-docs-empresa"><b>${esc(g.empresa.fantasia || g.empresa.razao)}</b>
        ${g.modelos.map((m) => caixa(m.valor, `Modelo de contrato — ${m.arquivo.nome}`, atuais.includes(m.valor))).join('')
          || '<small class="suave">Nenhum modelo de contrato anexado no cadastro de empresas.</small>'}</div>`).join('');
    $('#ct-modelo-regiao').innerHTML = `Escolha um estado. Fica só no cadastro (não aparece no contrato). ${reg && reg !== 'conflito'
      ? `Modelo usado: <b>${esc(C.REGIOES[reg])}</b>.`
      : 'São Paulo usa o modelo com a Antoniazzi Alimentos; Rio Grande do Sul e Santa Catarina usam o modelo só da Antoniazzi &amp; Cia.'}`;
  }

  /** Modelos anexados escolhidos: ficam para baixar ao lado da prévia (não entram no PDF/Word gerado). */
  function anexosHTML(docs) {
    const itens = anexos().flatMap((g) => g.modelos.filter((m) => docs.includes(m.valor)).map((m) => ({ ...m, empresa: g.empresa })));
    if (!itens.length) return '';
    return `<div class="ct-anexos"><b>Modelos anexados no cadastro de empresas</b>
      <small>Modelos Word (.docx) com marcadores, como {razão social}, saem preenchidos com os dados deste cadastro.
        Os demais formatos ficam só para baixar.</small>
      ${itens.map((m) => `<div><span>${esc(m.empresa.fantasia || m.empresa.razao)} — ${esc(m.arquivo.nome)}</span>
        <span class="linha-botoes">
          ${/\.docx$/i.test(m.arquivo.nome) ? `<button type="button" class="mini" data-preencher="${esc(m.valor)}">Gerar Word preenchido</button>` : ''}
          <a class="botao sec mini" href="${urlAnexo(m)}" download="${esc(m.arquivo.nome)}">Baixar modelo</a>
        </span></div>`).join('')}
    </div>`;
  }

  const urlAnexo = (m) => `/api/empresas/${encodeURIComponent(m.empresa.id)}/arquivos/${encodeURIComponent(m.arquivo.id)}`;

  /** Gera o .docx a partir do modelo da empresa, trocando os marcadores pelos dados do representante. */
  async function gerarModelo(valor) {
    const m = anexos().flatMap((g) => g.modelos.map((x) => ({ ...x, empresa: g.empresa }))).find((x) => x.valor === valor);
    if (!m) return;
    const d = lerFormulario();
    try {
      const r = await fetch(urlAnexo(m), { credentials: 'same-origin' });
      if (!r.ok) throw new Error('Não foi possível baixar o modelo.');
      const res = await window.EscalaModeloPreenchido.preencher(new Uint8Array(await r.arrayBuffer()), d, m.empresa);
      // salva e registra no histórico quando possível; um cadastro ainda incompleto não impede o preenchimento
      try {
        if (editavel()) await salvar();
        if (atual && atual.id) await api.post(`/api/contratos/${atual.id}/documento`, { formato: 'modelo' });
      } catch (e) {
        if (e.status === 401) throw e;
      }
      const base = m.arquivo.nome.replace(/\.docx$/i, '');
      const blob = new Blob([res.bytes], { type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' });
      const url = URL.createObjectURL(blob);
      const a = Object.assign(document.createElement('a'), { href: url, download: `${base}_${C.nomeArquivo(d, 'docx').replace(/^Contrato_Representante_/, '')}` });
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 2000);
      const avisos = [];
      if (!res.usados.length) avisos.push('O modelo não tem nenhum marcador reconhecido; o arquivo saiu igual ao modelo. Veja a lista de marcadores em Cadastros › Empresas.');
      if (res.vazios.length) avisos.push(`Campos em branco no cadastro (saíram como ${'_'.repeat(10)}): ${res.vazios.join(', ')}.`);
      if (res.desconhecidos.length) avisos.push(`Marcadores não reconhecidos (ficaram como estão): ${res.desconhecidos.join(', ')}.`);
      if (avisos.length) App.avisar(avisos.join('\n\n'));
    } catch (e) {
      if (e.status !== 401) App.avisar(e.message);
    }
  }
  $('#ct-previa').addEventListener('click', (ev) => {
    const b = ev.target.closest('button[data-preencher]');
    if (b) gerarModelo(b.dataset.preencher);
  });



  renderDocumentos(C.DOCUMENTOS.map((x) => x.id));

  const MASCARAS = { cpf: C.formatarCPF, cnpj: C.formatarCNPJ, cep: C.formatarCEP };

  function lerFormulario() {
    const d = {};
    for (const c of C.CAMPOS) {
      const el = $(`#ct-${c.id}`);
      d[c.id] = c.tipo === 'check' ? el.checked : c.tipo === 'estados' ? estadosMarcados() : el.value;
    }
    d.documentos = [...form.querySelectorAll('input[name=documento]:checked')].map((x) => x.value);
    d.situacao = $('#ct-situacao').value;
    return d;
  }

  function preencher(d) {
    for (const c of C.CAMPOS) {
      const el = $(`#ct-${c.id}`);
      if (c.tipo === 'check') el.checked = d[c.id] !== false;
      else if (c.tipo === 'estados') {
        const lista = C.listaEstados(d[c.id]);
        // um único estado de atuação (cadastros antigos com mais de um ficam com o primeiro)
        el.querySelectorAll('input[data-estado]').forEach((x) => { x.checked = x.dataset.estado === lista[0]; });
      } else el.value = d[c.id] == null ? '' : d[c.id];
      el.classList.remove('invalido');
    }
    const docs = Array.isArray(d.documentos) && d.documentos.length ? d.documentos : C.DOCUMENTOS.map((x) => x.id);
    renderDocumentos(docs);
    $('#ct-situacao').value = d.situacao || 'ativo';
  }

  function hoje() {
    const h = new Date();
    return `${h.getFullYear()}-${String(h.getMonth() + 1).padStart(2, '0')}-${String(h.getDate()).padStart(2, '0')}`;
  }

  async function abrir(c, soLeitura) {
    await carregarEmpresas();
    atual = c;
    exibindo = !!soLeitura && !!c.id;
    const novo = !c.id;
    preencher(novo ? { sexo: 'M', nacionalidade: 'brasileiro', mesmoEndereco: true, dataContrato: hoje(), situacao: 'ativo' } : c);
    $('#ct-titulo').textContent = novo ? 'Novo contrato' : `Contrato — ${c.razao}`;
    form.querySelectorAll('input, select, textarea').forEach((el) => { el.disabled = !editavel(); });
    $('#ct-modo').hidden = !exibindo;
    $('#ct-editar').hidden = !exibindo || !podeEditar();
    $('#ct-salvar').hidden = !editavel();
    $('#ct-lista-cartao').hidden = true;
    $('#ct-editor').hidden = false;
    $('#ct-pendencias').hidden = true;
    atualizar();
    window.scrollTo(0, 0);
    if (editavel()) $('#ct-razao').focus({ preventScroll: true });
  }

  function fechar() {
    atual = null;
    exibindo = false;
    $('#ct-editor').hidden = true;
    $('#ct-lista-cartao').hidden = false;
    renderLista();
  }
  $('#ct-voltar').addEventListener('click', fechar);
  $('#ct-editar').addEventListener('click', () => { if (atual) abrir(atual, false); });
  document.querySelector('[data-voltar="ct"]').addEventListener('click', fechar);

  /** Folha provisória (logotipo e linhas simuladas) enquanto o estado de atuação não é escolhido. */
  function previaProvisoria() {
    const linhas = [100, 96, 98, 72, 0, 100, 94, 99, 97, 60, 0, 100, 92, 98, 85, 0, 97, 100, 66]
      .map((w) => (w ? `<span class="ct-sim-linha" data-largura="${w}"></span>` : '<span class="ct-sim-espaco"></span>')).join('');
    return `<div class="ct-previa-vazia"><div class="ct-sim-folha">
        <img src="img/logo-moinho-santa-maria.png" alt="" class="ct-sim-logo" width="170" height="198">
        <p class="ct-sim-titulo">CONTRATO DE REPRESENTAÇÃO COMERCIAL</p>
        <div class="ct-sim-linhas">${linhas}</div>
        <p class="ct-sim-aviso">Prévia provisória. Selecione o <b>estado de atuação do representante</b> para ver o documento.</p>
      </div></div>`;
  }

  let temporizador = null;
  function atualizar() {
    const d = lerFormulario();
    $('#ct-fs-residencia').hidden = d.mesmoEndereco;
    clearTimeout(temporizador);
    temporizador = setTimeout(() => {
      // sem o estado de atuação não se sabe o modelo: a prévia fica em branco
      $('#ct-previa').innerHTML = anexosHTML(d.documentos) + (C.regiao(d) ? documentoHTML(d, true)
        : previaProvisoria());
      $('#ct-previa').querySelectorAll('[data-largura]').forEach((x) => { x.style.width = `${x.dataset.largura}%`; });
      const n = d.documentos.length;
      const pend = C.pendencias(d).length;
      $('#ct-resumo-docs').textContent = `${n} documento(s)` + (pend ? ` · ${pend} campo(s) a preencher` : ' · pronto para gerar');
      // a lista de pendências, quando aberta, acompanha o que já foi corrigido
      if (!$('#ct-pendencias').hidden) mostrarPendencias(C.pendencias(d), false);
    }, 120);
  }

  form.addEventListener('input', (ev) => {
    const campo = ev.target.dataset && ev.target.dataset.campo;
    const def = C.CAMPOS.find((c) => c.id === campo);
    if (def && MASCARAS[def.tipo]) {
      const fim = ev.target.selectionEnd === ev.target.value.length;
      ev.target.value = MASCARAS[def.tipo](ev.target.value);
      if (fim) ev.target.setSelectionRange(ev.target.value.length, ev.target.value.length);
    }
    if (campo) ev.target.classList.remove('invalido');
    if (ev.target.dataset && ev.target.dataset.estado) renderDocumentos();
    atualizar();
  });
  form.addEventListener('change', (ev) => {
    // nacionalidade acompanha o sexo enquanto for o padrão
    if (ev.target.id === 'ct-sexo') {
      const nac = $('#ct-nacionalidade');
      if (/^brasileir[oa]$/i.test(nac.value.trim()) || !nac.value.trim()) nac.value = ev.target.value === 'F' ? 'brasileira' : 'brasileiro';
    }
    atualizar();
  });

  // clicar num dado destacado na prévia leva ao campo correspondente
  $('#ct-previa').addEventListener('click', (ev) => {
    const m = ev.target.closest('mark[data-campo]');
    if (!m || !editavel()) return;
    let alvo = C.ALVO[m.dataset.campo] || m.dataset.campo;
    if (alvo === 'resEndereco' && $('#ct-mesmoEndereco').checked) alvo = 'endereco';
    const el = $(`#ct-${alvo}`);
    if (el) { el.focus(); el.scrollIntoView({ block: 'center', behavior: 'smooth' }); }
  });

  function mostrarPendencias(lista, focar = true) {
    form.querySelectorAll('.invalido').forEach((el) => el.classList.remove('invalido'));
    for (const p of lista) { const el = $(`#ct-${p.campo}`); if (el) el.classList.add('invalido'); }
    const box = $('#ct-pendencias');
    box.hidden = !lista.length;
    box.innerHTML = lista.length ? `<b>Antes de gerar o documento:</b><ul>${lista.map((p) => `<li>${esc(p.mensagem)}</li>`).join('')}</ul>` : '';
    if (lista.length && focar) {
      const el = $(`#ct-${lista[0].campo}`);
      if (el) el.focus();
    }
  }

  async function salvar() {
    const d = lerFormulario();
    const salvo = atual && atual.id ? await api.put(`/api/contratos/${atual.id}`, d) : await api.post('/api/contratos', d);
    atual = salvo;
    $('#ct-titulo').textContent = `Contrato — ${salvo.razao}`;
    await carregar();
    return salvo;
  }

  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    if (!editavel()) return;
    try {
      const s = await salvar();
      App.avisar(s.pendencias ? `Contrato salvo. Ainda faltam ${s.pendencias} campo(s) para gerar o documento.` : 'Contrato salvo.');
    } catch (e) {
      App.avisar(e.message);
    }
  });

  /** Valida, salva (se o perfil permite) e registra no histórico antes de gerar. */
  async function prepararGeracao(formato) {
    const d = lerFormulario();
    const pend = C.pendencias(d);
    if (!d.documentos.length) pend.push({ campo: 'documentos', mensagem: 'Escolha ao menos um documento legal.' });
    mostrarPendencias(pend);
    if (pend.length) return null;
    try {
      if (editavel()) await salvar();
      if (atual && atual.id) await api.post(`/api/contratos/${atual.id}/documento`, { formato });
    } catch (e) {
      App.avisar(e.message);
      return null;
    }
    return d;
  }

  // ------------------------------------------------------------- PDF e Word

  $('#ct-pdf').addEventListener('click', async () => {
    const d = await prepararGeracao('pdf');
    if (d) Doc.imprimir(C.montar(d), C.valores(d), C.nomeArquivo(d, 'pdf'));
  });

  $('#ct-docx').addEventListener('click', async () => {
    const d = await prepararGeracao('docx');
    if (!d) return;
    try {
      await Doc.baixarWord(C.montar(d), C.valores(d), C.nomeArquivo(d, 'docx'));
    } catch (e) {
      App.avisar(e.message);
    }
  });

  // ------------------------------------------------------------- ciclo de vida

  window.addEventListener('app-iniciado', (ev) => {
    usuario = ev.detail;
    fechar();
    carregar();
  });
  window.addEventListener('app-encerrado', () => {
    usuario = null;
    contratos = [];
    fechar();
  });
  document.querySelector('.modulo[data-modulo=contratos]').addEventListener('click', () => { if (usuario && !atual) carregar(); });

  window.EscalaContratosUI = { documentoHTML };
})();
