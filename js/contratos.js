/* Módulo Contratos de representantes: cadastro, prévia e geração em PDF e Word. */
(function () {
  'use strict';

  const C = window.EscalaContrato;
  const DOCX = window.EscalaContratoDocx;
  const api = window.EscalaApi;
  const App = window.EscalaApp;
  const $ = (sel) => document.querySelector(sel);
  const esc = App.esc;

  // tamanho em pixels dos logotipos (para manter a proporção no Word)
  const LOGOS = {
    moinho: { arquivo: 'img/logo-moinho.png', largura: 261, altura: 111 },
    antoniazzi: { arquivo: 'img/logo-antoniazzi.png', largura: 286, altura: 244 },
  };

  let usuario = null;
  let contratos = [];
  let atual = null; // contrato em edição ({} = novo)
  const podeEditar = () => !!usuario && usuario.perfil !== 'consulta';

  // ------------------------------------------------------- render do documento

  function inline(texto, vals, editavel) {
    return C.trechos(texto, vals).map((t) => {
      let h = esc(t.texto).replace(/\n/g, '<br>');
      if (t.campo) {
        const cls = 'ct-campo' + (t.vazio ? ' vazio' : '');
        h = editavel ? `<mark class="${cls}" data-campo="${t.campo}" title="Clique para editar">${h}</mark>` : h;
      }
      if (t.v) h = `<span class="ct-vermelho">${h}</span>`;
      if (t.u) h = `<u>${h}</u>`;
      if (t.i) h = `<em>${h}</em>`;
      if (t.b) h = `<strong>${h}</strong>`;
      return h;
    }).join('');
  }

  function cabecalhoHTML(tipo, vals, editavel) {
    const dados = `<div class="ct-cab-dados">${C.CABECALHO.map((l) => `<div>${inline(l, vals, editavel)}</div>`).join('')}</div>`;
    if (tipo === 'logo') return `<div class="ct-cab"><img src="${LOGOS.moinho.arquivo}" alt="Moinho Santa Maria" class="ct-logo">${dados}</div>`;
    if (tipo === 'logos') {
      return `<div class="ct-cab ct-cab-logos"><div class="ct-logos"><img src="${LOGOS.antoniazzi.arquivo}" alt="Antoniazzi Alimentos">` +
        `<img src="${LOGOS.moinho.arquivo}" alt="Moinho Santa Maria"></div>${dados}</div>`;
    }
    if (tipo === 'dados') return `<div class="ct-cab">${dados}</div>`;
    return '';
  }

  function blocoHTML(b, vals, ed) {
    const [tipo, a1, a2, a3] = b;
    const T = (t) => inline(t, vals, ed);
    const linhaAss = (linhas, cls = '') => `<div class="ct-ass ${cls}"><span class="ct-linha"></span>` +
      linhas.map((l) => `<strong>${T(l)}</strong>`).join('<br>') + '</div>';
    const testemunhas = (modo) => (modo === 'linha'
      ? '<div class="ct-test ct-test-linha">TESTEMUNHAS: <span class="ct-linha"></span><span class="ct-linha"></span></div>'
      : '<p class="ct-test-rotulo">TESTEMUNHAS:</p><div class="ct-test"><span class="ct-linha"></span><span class="ct-linha"></span></div>');
    switch (tipo) {
      case 'titulo': return `<h3 class="ct-titulo${a2 && a2.centro ? ' centro' : ''}">${T(a1)}</h3>`;
      case 'tituloCentro': return `<h3 class="ct-titulo-centro">${T(a1)}</h3>`;
      case 'secao': return `<h4 class="ct-secao">${T(a1)}</h4>`;
      case 'secaoPol': return `<h4 class="ct-secao-pol">${T(a1)}</h4>`;
      case 'p': return `<p class="ct-p">${T(a1)}</p>`;
      case 'pc': return `<p class="ct-p ct-compacto">${T(a1)}</p>`;
      case 'pp': return `<p class="ct-p ct-recuo">${T(a1)}</p>`;
      case 'pt': return `<p class="ct-p ct-termo">${T(a1)}</p>`;
      case 'n': return `<div class="ct-n"><span class="ct-num">${a3 && a3.semNegrito ? esc(a1) : `<strong>${esc(a1)}</strong>`}</span>` +
        `<p class="ct-p">${T(a2)}</p></div>`;
      case 'item': return `<div class="ct-item"><span>•</span><p class="ct-p">${T(a1)}</p></div>`;
      case 'rotulo': return `<p class="ct-rotulo">${T(a1)}</p>`;
      case 'zona': return `<p class="ct-zona"><strong>${T('⟦zona⟧')}</strong></p>`;
      case 'contato': return `<p class="ct-contato">${T(a1)}</p>`;
      case 'data': return `<p class="ct-data">${esc(a1)}, ${T('⟦data⟧')}.</p>`;
      case 'ass2': return `<div class="ct-assinaturas">${linhaAss(a1.assinatura)}${linhaAss(['⟦razao⟧', 'CNPJ: ⟦cnpj⟧'], 'centro')}</div>` +
        testemunhas(a2);
      case 'ass1': return `<div class="ct-assinaturas um">${linhaAss(['⟦razao⟧', 'CNPJ: ⟦cnpj⟧'], 'centro')}</div>${testemunhas('abaixo')}`;
      case 'assPolitica': return '<div class="ct-ass-pol">' + [['ANTONIAZZI & CIA LTDA'],
        ['ANTONIAZZI INDÚSTRIA E COMÉRCIO', 'DE ALIMENTOS LTDA'],
        ['⟦razao⟧', 'CNPJ: ⟦cnpj⟧', 'Representante: ⟦responsavel⟧']].map((l) => linhaAss(l)).join('') + '</div>';
      case 'assTermo': return `<div class="ct-ass-termo">${linhaAss(['REPRESENTANTE COMERCIAL', '⟦razao⟧', 'CNPJ: ⟦cnpj⟧', '__⟦responsavel⟧__'], 'centro')}</div>`;
      case 'versoes': return '<table class="ct-versoes"><thead><tr><th>Data</th><th>Versão</th><th>Descrição</th><th>Autor</th></tr></thead><tbody>' +
        C.VERSOES.map((l) => `<tr>${l.map((x) => `<td>${esc(x)}</td>`).join('')}</tr>`).join('') + '</tbody></table>';
      default: return '';
    }
  }

  /**
   * HTML do pacote. Cada "folha" (trecho entre quebras de página) é uma tabela cujo
   * <thead> traz o cabeçalho, que o navegador repete em todas as páginas impressas.
   */
  function documentoHTML(dados, editavel) {
    const vals = C.valores(dados);
    return C.montar(dados).map((doc) => {
      const folhas = [[]];
      for (const b of doc.blocos) {
        if (b[0] === 'quebra') folhas.push([]);
        else folhas[folhas.length - 1].push(b);
      }
      const cab = cabecalhoHTML(doc.cabecalho, vals, editavel);
      return `<section class="ct-doc ct-fonte-${doc.fonte}" data-doc="${doc.id}">` + folhas.map((bs) =>
        '<table class="ct-folha">' + (cab ? `<thead><tr><td>${cab}</td></tr></thead>` : '') +
        `<tbody><tr><td class="ct-corpo">${bs.map((b) => blocoHTML(b, vals, editavel)).join('')}</td></tr></tbody></table>`).join('') +
        '</section>';
    }).join('');
  }

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
        (digitos && C.soDigitos(c.cnpj).includes(digitos))));
    $('#ct-lista').innerHTML = lista.map((c) => `<tr>
        <td><b>${esc(c.razao)}</b><br><small class="suave">${esc(c.responsavel || '')}</small></td>
        <td>${esc(c.cnpj)}</td>
        <td>${esc([c.cidade, c.uf].filter(Boolean).join('-'))}</td>
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
  $('#ct-documentos').innerHTML = C.DOCUMENTOS.map((d) =>
    `<label class="check"><input type="checkbox" name="documento" value="${d.id}"> ${esc(d.nome)}</label>`).join('');

  const MASCARAS = { cpf: C.formatarCPF, cnpj: C.formatarCNPJ, cep: C.formatarCEP };

  function lerFormulario() {
    const d = {};
    for (const c of C.CAMPOS) {
      const el = $(`#ct-${c.id}`);
      d[c.id] = c.tipo === 'check' ? el.checked : el.value;
    }
    d.documentos = [...form.querySelectorAll('input[name=documento]:checked')].map((x) => x.value);
    d.situacao = $('#ct-situacao').value;
    return d;
  }

  function preencher(d) {
    for (const c of C.CAMPOS) {
      const el = $(`#ct-${c.id}`);
      if (c.tipo === 'check') el.checked = d[c.id] !== false;
      else el.value = d[c.id] == null ? '' : d[c.id];
      el.classList.remove('invalido');
    }
    const docs = Array.isArray(d.documentos) && d.documentos.length ? d.documentos : C.DOCUMENTOS.map((x) => x.id);
    form.querySelectorAll('input[name=documento]').forEach((x) => { x.checked = docs.includes(x.value); });
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
    if (!d) return;
    const area = $('#impressao');
    area.innerHTML = documentoHTML(d, false);
    const titulo = document.title;
    document.title = C.nomeArquivo(d, 'pdf').replace(/\.pdf$/, '');
    document.body.classList.add('imprimindo');
    // espera os logotipos carregarem antes de abrir a impressão
    await Promise.all([...area.querySelectorAll('img')].map((img) => (img.complete ? null
      : new Promise((r) => { img.onload = r; img.onerror = r; }))));
    const terminar = () => {
      document.body.classList.remove('imprimindo');
      area.innerHTML = '';
      document.title = titulo;
      window.removeEventListener('afterprint', terminar);
    };
    window.addEventListener('afterprint', terminar);
    window.print();
  });

  async function bytesDe(url) {
    const r = await fetch(url);
    if (!r.ok) throw new Error('Não foi possível carregar o logotipo.');
    return new Uint8Array(await r.arrayBuffer());
  }

  $('#ct-docx').addEventListener('click', async () => {
    const d = await prepararGeracao('docx');
    if (!d) return;
    try {
      const imagens = {};
      for (const [k, l] of Object.entries(LOGOS)) imagens[k] = { bytes: await bytesDe(l.arquivo), largura: l.largura, altura: l.altura };
      const bytes = DOCX.gerar(C.montar(d), C.valores(d), imagens);
      const blob = new Blob([bytes], { type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' });
      const url = URL.createObjectURL(blob);
      const a = Object.assign(document.createElement('a'), { href: url, download: C.nomeArquivo(d, 'docx') });
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 2000);
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
