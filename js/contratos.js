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
  let atual = null; // contrato em edição ({} = novo)
  const podeEditar = () => !!usuario && usuario.perfil !== 'consulta';

  const Doc = window.EscalaDocHTML;
  const documentoHTML = (dados, editavel) => Doc.renderizar(C.montar(dados), C.valores(dados), editavel);

  // ---------------------------------------------------------------- lista

  async function carregar() {
    try {
      contratos = await api.get('/api/contratos');
    } catch (e) {
      if (e.status !== 401) App.avisar(e.message);
      contratos = [];
    }
    renderLista();
  }

  function renderLista() {
    const busca = $('#ct-busca').value.trim().toLowerCase();
    const digitos = C.soDigitos(busca);
    const filtro = $('#ct-filtro').value;
    const lista = contratos.filter((c) => (!filtro || c.situacao === filtro) &&
      (!busca || (c.razao || '').toLowerCase().includes(busca) || (c.responsavel || '').toLowerCase().includes(busca) ||
        (c.codigo || '').toLowerCase() === busca ||
        (digitos && C.soDigitos(c.cnpj).includes(digitos))));
    $('#ct-lista').innerHTML = lista.map((c) => `<tr>
        <td><b>${esc(c.razao)}</b><br><small class="suave">${c.codigo ? `Cód. ${esc(c.codigo)} · ` : ''}${esc(c.responsavel || '')}</small></td>
        <td>${esc(c.cnpj)}</td>
        <td>${esc([c.cidade, c.uf].filter(Boolean).join('-'))}${c.estados ? `<br><small class="suave">atuação: ${esc(C.listaEstados(c.estados).join(', '))}</small>` : ''}</td>
        <td>${esc((c.zona || '').split('\n')[0])}</td>
        <td>${esc(C.dataBR(c.dataContrato))}</td>
        <td>${c.situacao === 'encerrado' ? '<span class="chip">Encerrado</span>' : '<span class="chip bom">Ativo</span>'}
          ${c.pendencias ? `<span class="chip breve" title="Faltam dados para gerar o documento">${c.pendencias} pendência(s)</span>` : ''}</td>
        <td class="acoes">
          <button type="button" class="mini sec" data-acao="abrir" data-id="${c.id}">${podeEditar() ? 'Editar' : 'Ver'}</button>
          ${podeEditar() ? `<button type="button" class="mini perigo" data-acao="excluir" data-id="${c.id}">Excluir</button>` : ''}
        </td></tr>`).join('') ||
      `<tr><td colspan="7" class="vazio">${contratos.length ? 'Nenhum contrato encontrado.' : 'Nenhum contrato cadastrado.'}</td></tr>`;
  }

  $('#ct-busca').addEventListener('input', renderLista);
  $('#ct-filtro').addEventListener('change', renderLista);
  $('#ct-novo').addEventListener('click', () => abrir({}));

  $('#ct-lista').addEventListener('click', async (ev) => {
    const b = ev.target.closest('button[data-acao]');
    if (!b) return;
    const c = contratos.find((x) => x.id === b.dataset.id);
    if (!c) return;
    if (b.dataset.acao === 'abrir') abrir(c);
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
          C.ESTADOS_ATUACAO.map((e) => `<label class="check"><input type="checkbox" data-estado="${e.uf}"> ${esc(e.nome)} (${e.uf})</label>`).join('') +
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

  /** Lista de documentos do pacote conforme o estado de atuação, mantendo o que estava marcado. */
  function renderDocumentos(marcados) {
    const d = { estados: estadosMarcados() };
    const reg = C.regiao(d);
    const atuais = marcados || [...form.querySelectorAll('input[name=documento]')].filter((x) => x.checked).map((x) => x.value);
    const antes = [...form.querySelectorAll('input[name=documento]')].map((x) => x.value);
    const lista = C.documentosDaRegiao(d);
    $('#ct-documentos').innerHTML = lista.map((x) => {
      // documento que aparece agora (ex.: contrato da Alimentos ao marcar SP) já vem marcado
      const marcado = atuais.includes(x.id) || (!marcados && !antes.includes(x.id));
      return `<label class="check"><input type="checkbox" name="documento" value="${x.id}"${marcado ? ' checked' : ''}> ${esc(x.nome)}</label>`;
    }).join('');
    $('#ct-modelo-regiao').innerHTML = reg === 'conflito'
      ? '<b class="ruim">Marque São Paulo ou Rio Grande do Sul/Santa Catarina: os modelos de contrato são diferentes.</b>'
      : `Fica só no cadastro (não aparece no contrato). ${reg ? `Modelo usado: <b>${esc(C.REGIOES[reg])}</b>.`
        : 'São Paulo usa o modelo com a Antoniazzi Alimentos; Rio Grande do Sul e Santa Catarina usam o modelo só da Antoniazzi &amp; Cia.'}`;
  }

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
        el.querySelectorAll('input[data-estado]').forEach((x) => { x.checked = lista.includes(x.dataset.estado); });
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

  function abrir(c) {
    atual = c;
    const novo = !c.id;
    preencher(novo ? { sexo: 'M', nacionalidade: 'brasileiro', mesmoEndereco: true, dataContrato: hoje(), situacao: 'ativo' } : c);
    $('#ct-titulo').textContent = novo ? 'Novo contrato' : `Contrato — ${c.razao}`;
    form.querySelectorAll('input, select, textarea').forEach((el) => { el.disabled = !podeEditar(); });
    $('#ct-lista-cartao').hidden = true;
    $('#ct-editor').hidden = false;
    $('#ct-pendencias').hidden = true;
    atualizar();
    window.scrollTo(0, 0);
    if (podeEditar()) $('#ct-razao').focus();
  }

  function fechar() {
    atual = null;
    $('#ct-editor').hidden = true;
    $('#ct-lista-cartao').hidden = false;
    renderLista();
  }
  $('#ct-voltar').addEventListener('click', fechar);

  let temporizador = null;
  function atualizar() {
    const d = lerFormulario();
    $('#ct-fs-residencia').hidden = d.mesmoEndereco;
    clearTimeout(temporizador);
    temporizador = setTimeout(() => {
      $('#ct-previa').innerHTML = documentoHTML(d, true);
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
    if (!m || !podeEditar()) return;
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
    if (!podeEditar()) return;
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
    if (!d.documentos.length) pend.push({ campo: 'documentos', mensagem: 'Escolha ao menos um documento do pacote.' });
    mostrarPendencias(pend);
    if (pend.length) return null;
    try {
      if (podeEditar()) await salvar();
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
