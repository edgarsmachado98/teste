/* Interface do CORE RH. Os dados ficam no servidor (API em /api). */
(function () {
  'use strict';

  const M = window.EscalaMotor;
  const P = window.EscalaPlanilha;
  const CU = window.EscalaCustos;
  const api = window.EscalaApi;
  const $ = (sel) => document.querySelector(sel);
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (ch) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
  const dataBR = (s) => s.split('-').reverse().join('/');
  const horas = (min) => `${Math.floor(min / 60)}h${String(Math.round(min % 60)).padStart(2, '0')}`;
  const SEG_A_SAB = [false, true, true, true, true, true, true];

  let estado = null;

  // Diálogos na própria página (alert/confirm nativos são bloqueados em alguns ambientes)
  const dialogo = $('#dialogo');
  let validarDialogo = null;
  /**
   * Abre o diálogo. Com `validar` (função assíncrona que lança erro), o OK só
   * fecha o diálogo quando a validação passa; o erro aparece em `erroEl`.
   */
  function abrirDialogo(msg, { cancelar = false, texto = null, senha = false, validar = null, erroEl = null } = {}) {
    $('#dialogo-msg').textContent = msg;
    const area = $('#dialogo-texto');
    area.hidden = texto == null;
    $('#dialogo-copiar').hidden = texto == null;
    if (texto != null) area.value = texto;
    $('#dialogo-senha').hidden = !senha;
    $('#dialogo-cancelar').hidden = !cancelar;
    validarDialogo = validar ? { validar, erroEl } : null;
    return new Promise((resolve) => {
      dialogo.onclose = () => { validarDialogo = null; resolve(dialogo.returnValue === 'ok'); };
      dialogo.returnValue = '';
      dialogo.showModal();
    });
  }
  dialogo.querySelector('form').addEventListener('submit', async (ev) => {
    if (!validarDialogo || !ev.submitter || ev.submitter.value !== 'ok') return;
    ev.preventDefault();
    const { validar, erroEl } = validarDialogo;
    ev.submitter.disabled = true;
    try {
      await validar();
      dialogo.close('ok');
    } catch (e) {
      if (erroEl) { erroEl.textContent = e.message; erroEl.hidden = false; }
    } finally {
      ev.submitter.disabled = false;
    }
  });
  const avisar = (msg) => { abrirDialogo(msg); };
  const confirmar = (msg) => abrirDialogo(msg, { cancelar: true });
  $('#dialogo-copiar').addEventListener('click', async () => {
    const area = $('#dialogo-texto');
    try { await navigator.clipboard.writeText(area.value); $('#dialogo-copiar').textContent = 'Copiado'; }
    catch (e) { area.focus(); area.select(); }
    setTimeout(() => { $('#dialogo-copiar').textContent = 'Copiar'; }, 1500);
  });
  // Dentro de um frame (visualizador) downloads e impressão não funcionam
  const emFrame = (() => { try { return window.self !== window.top; } catch (e) { return true; } })();
  if (emFrame) $('#btn-imprimir').hidden = true;

  // ------------------------------------------------------------ permissões

  let usuario = null;
  const podeEditar = () => !!usuario && usuario.perfil !== 'consulta';
  function exigirEdicao() {
    if (podeEditar()) return true;
    avisar('Seu perfil permite apenas consultar as escalas.');
    return false;
  }

  function estadoVazio() {
    return {
      setores: [], colaboradores: [], feriadosExtras: [], centrosCusto: [],
      regras: { domingoHomensSemanas: 3, domingoMulheresSemanas: 2 },
      incluirFacultativos: false, escala: null, escalas: {}, periodo: null,
    };
  }

  estado = estadoVazio();

  /** Busca os dados atuais no servidor e redesenha a tela. */
  async function recarregar() {
    try {
      estado = Object.assign(estadoVazio(), await api.get('/api/dados'));
    } catch (e) {
      if (e.status !== 401) avisar(e.message);
    }
    render();
    window.dispatchEvent(new CustomEvent('dados-atualizados'));
  }

  /**
   * Executa uma alteração no servidor; em caso de erro mostra a mensagem.
   * Sempre recarrega os dados depois (outros usuários podem ter alterado algo).
   */
  async function executar(fn) {
    let ok = true;
    try {
      await fn();
    } catch (e) {
      ok = false;
      if (e.status !== 401) avisar(e.message);
    }
    await recarregar();
    return ok;
  }

  /** Colaboradores com vínculo em algum dia do período (sem período: os não desligados). */
  function ativosNoPeriodo(inicio, fim) {
    if (!inicio || !fim) return estado.colaboradores.filter((c) => !c.desligamento);
    return estado.colaboradores.filter((c) => (!c.admissao || c.admissao <= fim) && (!c.desligamento || c.desligamento >= inicio));
  }

  // Escala por centro de custo: '' = todos os colaboradores; senão, o código do centro de custo
  const escopoAtual = () => $('#escopo-escala').value;
  const escalaDe = (escopo) => (estado.escalas || {})[escopo] || null;
  const escalaAtual = () => escalaDe(escopoAtual());
  const nomeEscopo = (escopo) => (escopo ? `Centro de custo ${escopo} · ${nomeCentro(escopo)}` : 'Todos os colaboradores');

  function configMotor(escopo = escopoAtual()) {
    const e = escalaDe(escopo);
    // escala já gerada guarda se excluiu quem não tem controle de jornada; para gerar, vale a caixa da tela
    const excluir = e ? e.excluirSemControle !== false : $('#excluir-sem-controle').checked;
    const colaboradores = ativosNoPeriodo(e && e.inicio, e && e.fim)
      .filter((c) => (!escopo || c.centroCustoCodigo === escopo) && (!excluir || !c.semControleJornada));
    // com centro de custo, a cobertura mínima considera só os setores dos colaboradores dele
    const usados = new Set(colaboradores.map((c) => c.setorId));
    return {
      setores: escopo ? estado.setores.filter((s) => usados.has(s.id)) : estado.setores,
      colaboradores,
      feriadosExtras: estado.feriadosExtras, regras: estado.regras,
      incluirFacultativos: estado.incluirFacultativos,
      inicio: e && e.inicio, fim: e && e.fim,
    };
  }

  const nomeSetor = (id) => (estado.setores.find((s) => s.id === id) || {}).nome || '—';

  // ------------------------------------------------------- módulos e abas
  // Cada painel pertence a um módulo (data-modulo). Módulos com mais de um
  // painel mostram abas internas; o sistema lembra a última aba de cada um.

  const ultimaAba = {};
  const abasDoModulo = (mod) => [...document.querySelectorAll(`.aba[data-modulo="${mod}"]`)];

  function mostrarModulo(mod) {
    const abas = abasDoModulo(mod);
    // no celular, módulo com seções mantém a gaveta aberta para escolher a seção
    mostrarAba(abas.length ? ultimaAba[mod] || abas[0].dataset.aba : mod, abas.length > 0);
  }

  function mostrarAba(nome, manterMenu) {
    const painel = document.getElementById('aba-' + nome);
    if (!painel) return;
    const mod = painel.dataset.modulo;
    ultimaAba[mod] = nome;
    document.querySelectorAll('.modulo').forEach((b) => b.classList.toggle('ativo', b.dataset.modulo === mod));
    const abas = abasDoModulo(mod);
    document.querySelectorAll('.subitens').forEach((d) => { d.hidden = d.dataset.modulo !== mod; });
    document.querySelectorAll('.aba').forEach((b) => {
      b.hidden = b.dataset.modulo !== mod;
      b.classList.toggle('ativa', b.dataset.aba === nome);
    });
    document.querySelectorAll('.painel').forEach((p) => p.classList.toggle('ativo', p === painel));
    // título da página: módulo e, quando houver, a seção dentro dele
    const nomeModulo = $(`.modulo[data-modulo="${mod}"] .rotulo`).textContent;
    const aba = abas.find((b) => b.dataset.aba === nome);
    $('#menu-titulo-modulo').textContent = nomeModulo;
    $('#titulo-pagina').textContent = aba ? aba.textContent : nomeModulo;
    $('#caminho-pagina').textContent = aba ? nomeModulo : 'CORE RH';
    document.title = mod === 'inicio' ? 'CORE RH' : `${$('#titulo-pagina').textContent} · CORE RH`;
    if (!manterMenu) abrirMenu(false);
    if (mod === 'inicio') renderInicio();
  }

  // menu lateral vira gaveta em telas estreitas
  function abrirMenu(abrir) {
    document.body.classList.toggle('menu-aberto', abrir);
    $('#fundo-menu').hidden = !abrir;
    $('#btn-menu').setAttribute('aria-expanded', String(abrir));
  }
  $('#btn-menu').addEventListener('click', () => abrirMenu(!document.body.classList.contains('menu-aberto')));
  $('#fundo-menu').addEventListener('click', () => abrirMenu(false));
  document.addEventListener('keydown', (ev) => { if (ev.key === 'Escape') abrirMenu(false); });

  document.querySelectorAll('.modulo').forEach((b) => b.addEventListener('click', () => mostrarModulo(b.dataset.modulo)));
  document.querySelectorAll('.aba').forEach((b) => b.addEventListener('click', () => mostrarAba(b.dataset.aba)));
  document.querySelectorAll('[data-ir]').forEach((b) => b.addEventListener('click', () => mostrarModulo(b.dataset.ir)));

  // ----------------------------------------------------------------- início

  function renderInicio() {
    if (!usuario) return;
    const h = new Date().getHours();
    const cumprimento = h < 12 ? 'Bom dia' : h < 18 ? 'Boa tarde' : 'Boa noite';
    $('#saudacao').textContent = `${cumprimento}, ${usuario.nome.split(' ')[0]}`;

    const ativos = estado.colaboradores.filter((c) => !c.desligamento || c.desligamento >= M.formatarData(new Date()));
    const mulheres = ativos.filter((c) => c.sexo === 'F').length;
    const total = ativos.length;
    let escalaValor = 'Nenhuma';
    let escalaDetalhe = podeEditar() ? 'Gere a primeira em Escalas de trabalho' : 'Ainda não há escala gerada';
    let escalaClasse = '';
    const geradas = Object.entries(estado.escalas || {});
    if (geradas.length) {
      // a escala mais recente; violações somadas de todas
      const [, e] = geradas.reduce((a, b) => (a[1].atualizadaEm >= b[1].atualizadaEm ? a : b));
      escalaValor = `${dataBR(e.inicio).slice(0, 5)} a ${dataBR(e.fim)}`;
      const erros = geradas.reduce((t, [escopo, x]) => t + M.validarEscala(configMotor(escopo), x).filter((o) => o.nivel === 'erro').length, 0);
      escalaDetalhe = (geradas.length > 1 ? `${geradas.length} escalas por centro de custo; ` : '') +
        (erros ? `${erros} violação(ões) da legislação` : 'sem violações da legislação');
      escalaClasse = erros ? 'ruim' : 'bom';
    }
    const tile = (rotulo, valor, detalhe, classe = '') => `<div class="tile">
        <span class="tile-rotulo">${rotulo}</span>
        <span class="tile-valor">${esc(valor)}</span>
        <span class="tile-detalhe ${classe}">${esc(detalhe)}</span></div>`;
    $('#resumo-inicio').innerHTML =
      tile('Colaboradores', String(total), total ? `${mulheres} mulheres, ${total - mulheres} homens` : 'Nenhum cadastrado') +
      tile('Setores', String(estado.setores.length), estado.setores.map((x) => x.nome).slice(0, 3).join(', ') +
        (estado.setores.length > 3 ? '…' : '') || 'Nenhum cadastrado') +
      tile('Escala atual', escalaValor, escalaDetalhe, escalaClasse);
  }

  // --------------------------------------------------------------- setores

  const formSetor = $('#form-setor');
  $('#dias-funcionamento').innerHTML = M.NOMES_DIAS.map((d, i) =>
    `<label class="check"><input type="checkbox" name="dia" value="${i}" ${i ? 'checked' : ''}> ${d}</label>`).join('');

  formSetor.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    if (!exigirEdicao()) return;
    const f = formSetor.elements;
    const dias = [0, 1, 2, 3, 4, 5, 6].map((i) => formSetor.querySelector(`input[name=dia][value="${i}"]`).checked);
    if (!dias.some(Boolean)) return avisar('Selecione ao menos um dia de funcionamento.');
    const dados = {
      nome: f.nome.value.trim(), minimoPorDia: Math.max(0, Number(f.minimoPorDia.value) || 0),
      diasFuncionamento: dias, funcionaFeriados: f.funcionaFeriados.checked,
    };
    const id = f.id.value;
    const ok = await executar(() => (id ? api.put(`/api/setores/${id}`, dados) : api.post('/api/setores', dados)));
    if (ok) formSetor.reset();
  });

  formSetor.addEventListener('reset', () => setTimeout(() => {
    formSetor.elements.id.value = '';
    $('#titulo-form-setor').textContent = 'Novo setor';
    formSetor.querySelectorAll('input[name=dia]').forEach((c) => { c.checked = SEG_A_SAB[c.value]; });
  }));

  $('#lista-setores').addEventListener('click', async (ev) => {
    const b = ev.target.closest('button');
    if (!b) return;
    const s = estado.setores.find((x) => x.id === b.dataset.id);
    if (!s || !exigirEdicao()) return;
    if (b.dataset.acao === 'editar') {
      const f = formSetor.elements;
      f.id.value = s.id; f.nome.value = s.nome; f.minimoPorDia.value = s.minimoPorDia;
      f.funcionaFeriados.checked = !!s.funcionaFeriados;
      formSetor.querySelectorAll('input[name=dia]').forEach((c) => { c.checked = !!s.diasFuncionamento[c.value]; });
      $('#titulo-form-setor').textContent = 'Editar setor';
      f.nome.focus();
    } else if (b.dataset.acao === 'excluir') {
      const qtd = estado.colaboradores.filter((c) => c.setorId === s.id).length;
      if (qtd) return avisar(`O setor possui ${qtd} colaborador(es). Remova-os ou altere o setor antes.`);
      if (!(await confirmar(`Excluir o setor "${s.nome}"?`))) return;
      await executar(() => api.del(`/api/setores/${s.id}`));
    }
  });

  function renderSetores() {
    $('#lista-setores').innerHTML = estado.setores.map((s) => `
      <tr>
        <td>${esc(s.nome)}</td>
        <td>${s.minimoPorDia}</td>
        <td>${M.NOMES_DIAS.filter((_, i) => s.diasFuncionamento[i]).join(', ')}</td>
        <td>${s.funcionaFeriados ? 'Sim' : 'Não'}</td>
        <td>${estado.colaboradores.filter((c) => c.setorId === s.id).length}</td>
        <td class="acoes">
          <button type="button" class="mini sec" data-acao="editar" data-id="${s.id}">Editar</button>
          <button type="button" class="mini perigo" data-acao="excluir" data-id="${s.id}">Excluir</button>
        </td>
      </tr>`).join('') || '<tr><td colspan="6" class="vazio">Nenhum setor cadastrado.</td></tr>';

    const opcoes = estado.setores.map((s) => `<option value="${s.id}">${esc(s.nome)}</option>`).join('');
    const selColab = $('#sel-setor-colab');
    const atual = selColab.value;
    selColab.innerHTML = opcoes;
    if (atual) selColab.value = atual;
    for (const sel of [$('#filtro-setor-colab')]) {
      const v = sel.value;
      sel.innerHTML = '<option value="">Todos os setores</option>' + opcoes;
      sel.value = estado.setores.some((s) => s.id === v) ? v : '';
    }
    const opcoesCentro = estado.centrosCusto.map((c) => `<option value="${esc(c.codigo)}">${esc(c.codigo)} · ${esc(c.nome)}</option>`).join('');
    const selCentro = $('#sel-centro-colab');
    const centroAtual = selCentro.value;
    selCentro.innerHTML = '<option value="">Sem centro de custo</option>' + opcoesCentro;
    selCentro.value = centroAtual;
    const filtroCentro = $('#filtro-centro-colab');
    const fc = filtroCentro.value;
    filtroCentro.innerHTML = '<option value="">Todos os centros de custo</option>' + opcoesCentro;
    filtroCentro.value = estado.centrosCusto.some((c) => c.codigo === fc) ? fc : '';
    // centros de custo da escala, com a quantidade de colaboradores ativos e se já há escala gerada
    const selEscopo = $('#escopo-escala');
    const escopo = selEscopo.value;
    const hoje = M.formatarData(new Date());
    const ativos = estado.colaboradores.filter((c) => !c.desligamento || c.desligamento >= hoje);
    const marca = (k) => (escalaDe(k) ? ' · escala gerada' : '');
    selEscopo.innerHTML = `<option value="">Todos os colaboradores (${ativos.length})${marca('')}</option>` +
      estado.centrosCusto.map((c) => [c, ativos.filter((x) => x.centroCustoCodigo === c.codigo).length])
        .filter(([c, n]) => n || escalaDe(c.codigo))
        .map(([c, n]) => `<option value="${esc(c.codigo)}">${esc(c.codigo)} · ${esc(c.nome)} (${n})${marca(c.codigo)}</option>`).join('');
    selEscopo.value = [...selEscopo.options].some((o) => o.value === escopo) ? escopo : '';
  }

  // -------------------------------------------------------- centros de custo

  const nomeCentro = (cod) => (estado.centrosCusto.find((c) => c.codigo === cod) || {}).nome || '';
  const formCentro = $('#form-centro');

  function renderCentros() {
    const busca = $('#busca-centro').value.trim().toLowerCase();
    const hoje = M.formatarData(new Date());
    const ativos = {};
    for (const c of estado.colaboradores) {
      if (c.centroCustoCodigo && (!c.desligamento || c.desligamento >= hoje)) ativos[c.centroCustoCodigo] = (ativos[c.centroCustoCodigo] || 0) + 1;
    }
    $('#lista-centros').innerHTML = estado.centrosCusto
      .filter((c) => !busca || c.codigo.toLowerCase().includes(busca) || c.nome.toLowerCase().includes(busca))
      .map((c) => `<tr><td>${esc(c.codigo)}</td><td>${esc(c.nome)}</td><td class="num">${ativos[c.codigo] || 0}</td>
        <td class="acoes so-edicao">
          <button type="button" class="mini sec" data-acao="editar" data-codigo="${esc(c.codigo)}">Editar</button>
          <button type="button" class="mini perigo" data-acao="excluir" data-codigo="${esc(c.codigo)}">Excluir</button>
        </td></tr>`).join('') ||
      `<tr><td colspan="4" class="vazio">${estado.centrosCusto.length ? 'Nenhum centro de custo encontrado.' : 'Nenhum centro de custo cadastrado. Importe a planilha do sistema de folha.'}</td></tr>`;
  }
  $('#busca-centro').addEventListener('input', renderCentros);

  formCentro.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    if (!exigirEdicao()) return;
    const f = formCentro.elements;
    const ok = await executar(() => api.post('/api/centros-custo', { codigo: f.codigo.value.trim(), nome: f.nome.value.trim() }));
    if (ok) formCentro.reset();
  });
  formCentro.addEventListener('reset', () => setTimeout(() => {
    formCentro.elements.codigo.readOnly = false;
    $('#titulo-form-centro').textContent = 'Novo centro de custo';
  }));
  $('#lista-centros').addEventListener('click', async (ev) => {
    const b = ev.target.closest('button[data-codigo]');
    if (!b || !exigirEdicao()) return;
    const c = estado.centrosCusto.find((x) => x.codigo === b.dataset.codigo);
    if (!c) return;
    if (b.dataset.acao === 'editar') {
      formCentro.elements.codigo.value = c.codigo;
      formCentro.elements.codigo.readOnly = true;
      formCentro.elements.nome.value = c.nome;
      $('#titulo-form-centro').textContent = 'Editar centro de custo';
      formCentro.elements.nome.focus();
    } else if (await confirmar(`Excluir o centro de custo ${c.codigo} · ${c.nome}?`)) {
      await executar(() => api.del(`/api/centros-custo/${encodeURIComponent(c.codigo)}`));
    }
  });

  const chaveCab = (v) => P.texto(v).toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/[^a-z0-9]/g, '');

  /** Relatório "Centros de Custos": linha de cabeçalho com Código e Nome; para em "Total". */
  function lerCentrosDaPlanilha(linhas) {
    const iCab = linhas.findIndex((l) => l.some((v) => /^cod(igo)?$/.test(chaveCab(v))) && l.some((v) => ['nome', 'descricao'].includes(chaveCab(v))));
    if (iCab < 0) throw new Error('Não encontrei as colunas Código e Nome na planilha.');
    const cab = linhas[iCab].map(chaveCab);
    const iCod = cab.findIndex((h) => /^cod(igo)?$/.test(h));
    const iNome = cab.findIndex((h) => ['nome', 'descricao'].includes(h));
    const out = [];
    for (let r = iCab + 1; r < linhas.length; r++) {
      const l = linhas[r];
      if (l.some((v) => /^total/.test(chaveCab(v)))) break;
      const codigo = P.texto(l[iCod]);
      const nome = P.texto(l[iNome]);
      if (codigo && nome) out.push({ linha: r + 1, codigo, nome });
    }
    return out;
  }

  $('#arq-centros').addEventListener('change', async (ev) => {
    const arq = ev.target.files[0];
    ev.target.value = '';
    if (!arq || !exigirEdicao()) return;
    let linhas;
    try {
      linhas = lerCentrosDaPlanilha(await P.ler(new Uint8Array(await arq.arrayBuffer())));
    } catch (e) {
      return avisar(`Não foi possível ler a planilha: ${e.message}`);
    }
    if (!linhas.length) return avisar('Nenhum centro de custo encontrado na planilha.');
    if (!(await confirmar(`Importar ${linhas.length} centro(s) de custo? Os novos serão cadastrados e os existentes terão o nome atualizado.`))) return;
    let r = null;
    await executar(async () => { r = await api.post('/api/centros-custo/importar', { linhas }); });
    if (r) {
      avisar(`${r.novos} centro(s) de custo novo(s) e ${r.atualizados} atualizado(s); ${linhas.length - r.novos - r.atualizados - r.ignorados.length} sem alteração.` +
        (r.ignorados.length ? `\nIgnorados: ${r.ignorados.join('; ')}` : ''));
    }
  });

  // ---------------------------------------------------------- colaboradores

  const formColab = $('#form-colab');
  $('#sel-jornada').innerHTML = Object.entries(M.JORNADAS)
    .map(([k, j]) => `<option value="${k}">${esc(j.nome)}</option>`).join('');
  $('#colab-beneficios').innerHTML = CU.BENEFICIOS.map((b) =>
    `<label>${esc(b.nome)} (R$)<input name="ben-${b.id}" inputmode="decimal" placeholder="0,00" autocomplete="off"></label>`).join('');
  $('#sel-tipo-deslig').innerHTML = '<option value="">Selecione</option>' +
    Object.entries(CU.TIPOS_DESLIGAMENTO).map(([k, t]) => `<option value="${k}">${esc(t.nome)}</option>`).join('');
  $('#sel-motivo-deslig').innerHTML = '<option value="">Não informado</option>' +
    Object.entries(CU.MOTIVOS_DESLIGAMENTO).map(([k, n]) => `<option value="${k}">${esc(n)}</option>`).join('');
  $('#sel-sem-controle').innerHTML = Object.entries(CU.SEM_CONTROLE_JORNADA).map(([k, n]) => `<option value="${k}">${esc(n)}</option>`).join('');
  const caixaSemControle = $('#colab-sem-controle');
  const mostrarMotivoControle = () => { $('#colab-motivo-controle').hidden = !caixaSemControle.checked; };
  caixaSemControle.addEventListener('change', mostrarMotivoControle);
  const moedaCampo = (v) => (v === '' || v == null ? '' : Number(v).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
  const CAMPOS_RH = ['cargo', 'admissao', 'desligamento', 'tipoDesligamento', 'motivoDesligamento', 'obsDesligamento', 'inicioAquisitivo',
    'centroCustoCodigo', 'codigoESocial', 'cbo', 'departamentoCodigo', 'departamento', 'estabelecimentoCodigo', 'estabelecimento',
    'sindicatoCodigo', 'sindicato', 'nascimento'];

  function atualizarDicaJornada() {
    const j = M.JORNADAS[formColab.elements.jornada.value];
    const ini = M.minutosDeHora(formColab.elements.entrada.value);
    const fim = ini + j.minutosTrabalho + j.intervalo;
    let texto = `Saída prevista: ${M.horaDeMinutos(fim)}${fim >= 1440 ? ' (dia seguinte)' : ''}`;
    texto += j.intervalo ? ` — intervalo de ${j.intervalo} min incluso.` : ' — intervalo indenizado (art. 59-A).';
    const noturno = M.minutosNoturnos(ini, fim);
    if (noturno) texto += ` ${horas(noturno)} em horário noturno (adicional — art. 73).`;
    $('#dica-jornada').textContent = texto;
  }
  formColab.elements.jornada.addEventListener('change', atualizarDicaJornada);
  formColab.elements.entrada.addEventListener('input', atualizarDicaJornada);

  formColab.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    if (!exigirEdicao()) return;
    const f = formColab.elements;
    if (!estado.setores.length) return avisar('Cadastre um setor primeiro.');
    const dados = {
      nome: f.nome.value.trim(), matricula: f.matricula.value.trim(),
      sexo: f.sexo.value, setorId: f.setorId.value, jornada: f.jornada.value, entrada: f.entrada.value,
      salario: f.salario.value, feriasVencidas: Number(f.feriasVencidas.value), beneficios: {}, pcd: f.pcd.checked,
      semControleJornada: caixaSemControle.checked ? f.semControleJornada.value : '',
    };
    for (const k of CAMPOS_RH) dados[k] = f[k].value.trim();
    for (const b of CU.BENEFICIOS) dados.beneficios[b.id] = f[`ben-${b.id}`].value;
    if (dados.desligamento && !dados.tipoDesligamento) {
      $('#colab-desligamento').open = true;
      return avisar('Informe o tipo de desligamento.');
    }
    const id = f.id.value;
    const ok = await executar(() => (id ? api.put(`/api/colaboradores/${id}`, dados) : api.post('/api/colaboradores', dados)));
    if (ok) formColab.reset();
  });

  formColab.addEventListener('reset', () => setTimeout(() => {
    formColab.elements.id.value = '';
    $('#titulo-form-colab').textContent = 'Novo colaborador';
    formColab.querySelectorAll('details').forEach((d) => { d.open = false; });
    caixaSemControle.checked = false;
    mostrarMotivoControle();
    atualizarDicaJornada();
  }));

  $('#lista-colabs').addEventListener('click', async (ev) => {
    const b = ev.target.closest('button');
    if (!b) return;
    const c = estado.colaboradores.find((x) => x.id === b.dataset.id);
    if (!c || !exigirEdicao()) return;
    if (b.dataset.acao === 'editar') {
      const f = formColab.elements;
      for (const k of ['id', 'nome', 'matricula', 'sexo', 'setorId', 'jornada', 'entrada']) f[k].value = c[k];
      for (const k of CAMPOS_RH) f[k].value = c[k] || '';
      f.salario.value = moedaCampo(c.salario);
      f.feriasVencidas.value = String(c.feriasVencidas || 0);
      f.pcd.checked = !!c.pcd;
      caixaSemControle.checked = !!c.semControleJornada;
      f.semControleJornada.value = c.semControleJornada || 'gestao';
      mostrarMotivoControle();
      for (const b of CU.BENEFICIOS) f[`ben-${b.id}`].value = moedaCampo(c.beneficios && c.beneficios[b.id]);
      $('#colab-desligamento').open = !!c.desligamento;
      $('#titulo-form-colab').textContent = 'Editar colaborador';
      atualizarDicaJornada();
      f.nome.focus();
    } else if (b.dataset.acao === 'excluir') {
      if (!(await confirmar(`Excluir ${c.nome} (matrícula ${c.matricula})?\n\nSe a pessoa saiu da empresa, prefira registrar o ` +
        'desligamento no cadastro: assim o histórico de custos e o turnover são mantidos.'))) return;
      await executar(() => api.del(`/api/colaboradores/${c.id}`));
    }
  });

  $('#filtro-setor-colab').addEventListener('change', renderColaboradores);
  $('#filtro-situacao-colab').addEventListener('change', renderColaboradores);
  $('#filtro-centro-colab').addEventListener('change', renderColaboradores);
  $('#busca-colab').addEventListener('input', renderColaboradores);

  function renderColaboradores() {
    const filtro = $('#filtro-setor-colab').value;
    const centro = $('#filtro-centro-colab').value;
    const busca = $('#busca-colab').value.trim().toLowerCase();
    const situacao = $('#filtro-situacao-colab').value;
    const hoje = M.formatarData(new Date());
    const desligado = (c) => !!c.desligamento && c.desligamento < hoje;
    const lista = estado.colaboradores
      .filter((c) => !filtro || c.setorId === filtro)
      .filter((c) => !centro || c.centroCustoCodigo === centro)
      .filter((c) => !busca || c.nome.toLowerCase().includes(busca) || c.matricula.toLowerCase().includes(busca))
      .filter((c) => (situacao === 'sem-controle' ? !!c.semControleJornada && !desligado(c)
        : !situacao || (situacao === 'desligados') === desligado(c)))
      .sort((a, b) => nomeSetor(a.setorId).localeCompare(nomeSetor(b.setorId)) || a.nome.localeCompare(b.nome));
    $('#lista-colabs').innerHTML = lista.map((c) => {
      const t = M.turnoTrabalho(c);
      return `<tr>
        <td>${esc(c.matricula)}</td><td>${esc(c.nome)}${c.cargo ? `<br><small class="suave">${esc(c.cargo)}</small>` : ''}</td>
        <td>${c.sexo === 'F' ? 'Feminino' : 'Masculino'}</td>
        <td>${esc(nomeSetor(c.setorId))}${c.centroCustoCodigo ? `<br><small class="suave">CC ${esc(c.centroCustoCodigo)} · ${esc(nomeCentro(c.centroCustoCodigo))}</small>` : ''}</td>
        <td>${c.semControleJornada ? `<span class="chip breve" title="${esc(CU.SEM_CONTROLE_JORNADA[c.semControleJornada])}">Sem controle</span>`
          : esc(c.jornada)}</td>
        <td>${M.horaDeMinutos(t.inicio)}–${M.horaDeMinutos(t.fim)}</td>
        <td>${c.desligamento ? `<span class="chip ${desligado(c) ? 'ruim' : 'breve'}">${desligado(c) ? 'Desligado' : 'Sai'} em ${dataBR(c.desligamento)}</span>`
          : `<span class="chip bom">Ativo</span>${c.admissao ? `<br><small class="suave">desde ${dataBR(c.admissao)}</small>` : ''}`}</td>
        <td class="acoes">
          <button type="button" class="mini sec" data-acao="editar" data-id="${c.id}">Editar</button>
          <button type="button" class="mini perigo" data-acao="excluir" data-id="${c.id}">Excluir</button>
        </td></tr>`;
    }).join('') || `<tr><td colspan="8" class="vazio">${estado.colaboradores.length ? 'Nenhum colaborador neste filtro.' : 'Nenhum colaborador cadastrado.'}</td></tr>`;
  }

  // [campo da linha, apelidos do cabeçalho (sem acento, só letras e números)]
  const COLUNAS_EMPREGADOS = [
    ['matricula', ['matricula', 'codepr', 'codempregado', 'codigoempregado', 'registro', 'chapa']],
    ['codigoESocial', ['codesocial', 'matriculaesocial', 'codigoesocial']],
    ['nome', ['nome', 'nomeempregado', 'nomecolaborador', 'empregado', 'colaborador']],
    ['admissao', ['admissao', 'dataadmissao', 'dataadmissao']],
    ['salario', ['salario', 'salariobase', 'salariocontratual']],
    ['cargo', ['cargo', 'descricaocargo', 'funcao', 'descricaofuncao']],
    ['cbo', ['cbo']],
    ['centroCustoCodigo', ['codccusto', 'codcentrocusto', 'codcentrodecusto', 'codigoccusto', 'codigocentrodecusto', 'centrocustocodigo']],
    ['centroCustoNome', ['descricaoccusto', 'centrodecusto', 'centrocusto', 'descricaocentrodecusto', 'ccusto']],
    ['estabelecimentoCodigo', ['codservico', 'codestabelecimento', 'codfilial']],
    ['estabelecimento', ['descricaoservico', 'estabelecimento', 'filial', 'descricaoestabelecimento']],
    ['departamentoCodigo', ['coddpto', 'coddepartamento', 'codigodepartamento']],
    ['departamento', ['descricaodpto', 'departamento', 'dpto', 'descricaodepartamento']],
    ['sindicatoCodigo', ['codsind', 'codsindicato']],
    ['sindicato', ['sindicato', 'descricaosindicato']],
    ['nascimento', ['datanascimento', 'nascimento', 'datadenascimento']],
    ['sexo', ['sexo']],
    ['pcd', ['possuideficiencia', 'deficiencia', 'pcd', 'deficiente']],
    ['setor', ['setor']],
    ['jornada', ['jornada']],
    ['entrada', ['entrada', 'horarioentrada', 'horariodeentrada']],
  ];

  /** Acha a linha de cabeçalho (com matrícula e nome) e converte as linhas seguintes em registros. */
  function lerEmpregados(linhas) {
    const temMatricula = (l) => l.some((v) => COLUNAS_EMPREGADOS[0][1].includes(chaveCab(v)));
    const iCab = linhas.slice(0, 30).findIndex((l) => temMatricula(l));
    if (iCab < 0) throw new Error('Não encontrei a coluna de matrícula (ex.: "Cód Epr" ou "matricula") no cabeçalho.');
    const cab = linhas[iCab].map(chaveCab);
    const indice = {};
    for (const [campo, apelidos] of COLUNAS_EMPREGADOS) {
      const i = cab.findIndex((h) => apelidos.includes(h));
      if (i >= 0) indice[campo] = i;
    }
    const registros = [];
    for (let r = iCab + 1; r < linhas.length; r++) {
      const l = linhas[r];
      const pega = (campo) => (indice[campo] == null ? '' : P.texto(l[indice[campo]]));
      const matricula = pega('matricula');
      if (!matricula || /^total/i.test(matricula)) continue;
      const reg = { linha: r + 1, matricula };
      for (const campo of Object.keys(indice)) {
        if (campo === 'matricula') continue;
        const bruto = l[indice[campo]];
        if (campo === 'admissao' || campo === 'nascimento') reg[campo] = P.lerData(bruto);
        else if (campo === 'sexo') reg[campo] = pega(campo).charAt(0).toUpperCase();
        else reg[campo] = pega(campo);
      }
      registros.push(reg);
    }
    return { registros, colunas: Object.keys(indice) };
  }

  $('#arq-csv').addEventListener('change', async (ev) => {
    const arq = ev.target.files[0];
    ev.target.value = '';
    if (!arq) return;
    if (!exigirEdicao()) return;
    let lido;
    try {
      lido = lerEmpregados(await P.ler(new Uint8Array(await arq.arrayBuffer())));
    } catch (e) {
      return avisar(`Não foi possível ler a planilha: ${e.message}`);
    }
    if (!lido.registros.length) return avisar('Nenhuma linha com matrícula encontrada.');
    const opcoes = await opcoesImportacao(lido.registros, lido.colunas);
    if (!opcoes) return;
    // setor das escalas: coluna "setor" da planilha ou, na falta dela, departamento ou centro de custo
    const registros = lido.registros.map((l) => ({
      ...l, setor: l.setor || (opcoes.setorDe === 'centroCusto' ? l.centroCustoNome : l.departamento) || '',
    }));
    const naPlanilha = new Set(registros.map((l) => l.matricula));
    const hoje = M.formatarData(new Date());
    const ausentes = estado.colaboradores.filter((c) => !naPlanilha.has(c.matricula) && (!c.desligamento || c.desligamento >= hoje));
    let r = null;
    await executar(async () => { r = await api.post('/api/colaboradores/importar', { linhas: registros, opcoes }); });
    if (r) {
      avisar(`${r.importados} colaborador(es) cadastrado(s) e ${r.atualizados || 0} atualizado(s).` +
        (r.centros ? `\n${r.centros} centro(s) de custo novo(s) ou renomeado(s).` : '') +
        (r.ignorados.length ? `\n\nIgnorados:\n${r.ignorados.slice(0, 20).join('\n')}` +
          (r.ignorados.length > 20 ? `\n… e mais ${r.ignorados.length - 20}` : '') : '') +
        (ausentes.length ? `\n\n${ausentes.length} colaborador(es) ativo(s) no sistema não constam na planilha. Se a planilha traz todos os ` +
          `ativos, registre o desligamento deles: ${ausentes.slice(0, 10).map((c) => `${c.matricula} ${c.nome}`).join('; ')}` +
          (ausentes.length > 10 ? '…' : '') + '.' : ''));
    }
  });

  // [grupo, nome, colunas que o compõem, marcado por padrão ao atualizar]
  const CAMPOS_IMPORTACAO = [
    ['cargo', 'Cargo e CBO', ['cargo', 'cbo'], true], ['salario', 'Salário', ['salario'], true],
    ['admissao', 'Admissão', ['admissao'], true], ['centroCusto', 'Centro de custo', ['centroCustoCodigo'], true],
    ['departamento', 'Departamento', ['departamento', 'departamentoCodigo'], true],
    ['estabelecimento', 'Estabelecimento', ['estabelecimento', 'estabelecimentoCodigo'], true],
    ['sindicato', 'Sindicato', ['sindicato', 'sindicatoCodigo'], true], ['nascimento', 'Nascimento', ['nascimento'], true],
    ['pcd', 'PcD', ['pcd'], true], ['codigoESocial', 'Cód. eSocial', ['codigoESocial'], true],
    ['nome', 'Nome', ['nome'], false], ['sexo', 'Sexo', ['sexo'], false], ['setor', 'Setor das escalas', ['setor'], false],
    ['jornada', 'Jornada', ['jornada'], false], ['entrada', 'Horário de entrada', ['entrada'], false],
  ];

  /** Caixa de diálogo: cadastrar matrículas novas e/ou atualizar as já cadastradas, escolhendo os campos. */
  function opcoesImportacao(registros, colunas) {
    const dlg = $('#dialogo-importar');
    const cadastradas = new Set(estado.colaboradores.map((c) => c.matricula));
    const existentes = registros.filter((r) => cadastradas.has(r.matricula)).length;
    const novas = registros.length - existentes;
    const temSetor = colunas.includes('setor') || colunas.includes('departamento') || colunas.includes('centroCustoNome');
    const podeCadastrar = colunas.includes('nome') && colunas.includes('sexo') && temSetor;
    // grupos de campos presentes na planilha ("setor" também vem do departamento ou do centro de custo)
    const grupos = CAMPOS_IMPORTACAO.filter(([g, , cols]) => cols.some((c) => colunas.includes(c)) || (g === 'setor' && temSetor));
    $('#imp-setor-rotulo').hidden = colunas.includes('setor') || !temSetor;
    $('#imp-resumo').textContent = `O arquivo tem ${registros.length} linha(s): ${novas} matrícula(s) nova(s) e ${existentes} já cadastrada(s).`;
    const cad = $('#imp-cadastrar');
    const atu = $('#imp-atualizar');
    $('#imp-cadastrar-rotulo').textContent = `Cadastrar as matrículas novas (${novas})`;
    $('#imp-atualizar-rotulo').textContent = `Atualizar os dados das matrículas já cadastradas (${existentes})`;
    cad.checked = podeCadastrar && novas > 0;
    cad.disabled = !podeCadastrar || !novas;
    $('#imp-cadastrar-dica').hidden = podeCadastrar || !novas;
    $('#imp-cadastrar-dica').textContent = 'Para cadastrar, o arquivo precisa das colunas nome, sexo e setor (ou departamento ou centro de custo).';
    atu.checked = existentes > 0 && grupos.length > 0;
    atu.disabled = !existentes || !grupos.length;
    $('#imp-lista-campos').innerHTML = grupos.length
      ? grupos.map(([k, nome, , padrao]) => `<label class="check"><input type="checkbox" name="imp-campo" value="${k}" ${padrao ? 'checked' : ''}> ${nome}</label>`).join('')
      : '<p class="dica">O arquivo não tem colunas que possam ser atualizadas.</p>';
    const atualizarEstado = () => {
      $('#imp-campos').disabled = !atu.checked;
      const campos = dlg.querySelectorAll('input[name=imp-campo]:checked').length;
      $('#imp-confirmar').disabled = !cad.checked && !(atu.checked && campos);
    };
    dlg.onchange = atualizarEstado;
    atualizarEstado();
    return new Promise((resolve) => {
      dlg.onclose = () => {
        if (dlg.returnValue !== 'ok') return resolve(null);
        resolve({
          setorDe: $('#imp-setor').value,
          cadastrar: cad.checked,
          atualizar: atu.checked ? [...dlg.querySelectorAll('input[name=imp-campo]:checked')].map((x) => x.value) : [],
        });
      };
      dlg.returnValue = '';
      dlg.showModal();
    });
  }

  // ---------------------------------------------------------------- regras

  const formRegras = $('#form-regras');
  formRegras.addEventListener('change', async () => {
    if (!exigirEdicao()) { renderRegras(); return; }
    await executar(() => api.put('/api/regras', {
      domingoHomensSemanas: Number(formRegras.elements.domingoHomensSemanas.value),
      incluirFacultativos: formRegras.elements.incluirFacultativos.checked,
      evitarFolgaFeriado: formRegras.elements.evitarFolgaFeriado.checked,
      maxFolgasSeguidas: Number(formRegras.elements.maxFolgasSeguidas.value),
    }));
  });

  $('#form-feriado').addEventListener('submit', async (ev) => {
    ev.preventDefault();
    if (!exigirEdicao()) return;
    const form = ev.target;
    const f = form.elements;
    const ok = await executar(() => api.post('/api/feriados', { data: f.data.value, nome: f.nome.value.trim() }));
    if (ok) form.reset();
  });

  $('#lista-feriados').addEventListener('click', async (ev) => {
    const b = ev.target.closest('button[data-data]');
    if (!b) return;
    if (!exigirEdicao()) return;
    await executar(() => api.del(`/api/feriados/${b.dataset.data}`));
  });

  function renderRegras() {
    formRegras.querySelectorAll('input, select').forEach((el) => {
      el.disabled = !podeEditar() || el.name === 'domingoMulheresSemanas';
    });
    formRegras.elements.domingoHomensSemanas.value = String(estado.regras.domingoHomensSemanas || 3);
    formRegras.elements.incluirFacultativos.checked = !!estado.incluirFacultativos;
    formRegras.elements.evitarFolgaFeriado.checked = !!estado.regras.evitarFolgaFeriado;
    formRegras.elements.maxFolgasSeguidas.value = String(estado.regras.maxFolgasSeguidas || 0);
    const ano = new Date().getFullYear();
    const nacionais = M.feriadosNacionais(ano, estado.incluirFacultativos)
      .concat(M.feriadosNacionais(ano + 1, estado.incluirFacultativos));
    const linhas = estado.feriadosExtras.map((f) => `<tr><td>${dataBR(f.data)}</td><td>${esc(f.nome)}</td><td>Local</td>
        <td class="acoes"><button type="button" class="mini perigo" data-data="${f.data}">Remover</button></td></tr>`)
      .concat(nacionais.map((f) => `<tr class="suave"><td>${dataBR(f.data)}</td><td>${esc(f.nome)}</td>
        <td>${f.tipo === 'facultativo' ? 'Facultativo' : 'Nacional'}</td><td></td></tr>`));
    $('#lista-feriados').innerHTML = linhas.join('');
  }

  // ---------------------------------------------------------------- escala

  const formGerar = $('#form-gerar');
  function periodoPadrao() {
    const p = escalaAtual();
    if (p) $('#excluir-sem-controle').checked = p.excluirSemControle !== false;
    if (p) { formGerar.elements.inicio.value = p.inicio; formGerar.elements.fim.value = p.fim; return; }
    const h = new Date();
    const ini = new Date(Date.UTC(h.getFullYear(), h.getMonth() + 1, 1));
    const fim = new Date(Date.UTC(h.getFullYear(), h.getMonth() + 2, 0));
    formGerar.elements.inicio.value = M.formatarData(ini);
    formGerar.elements.fim.value = M.formatarData(fim);
  }

  formGerar.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    if (!exigirEdicao()) return;
    const inicio = formGerar.elements.inicio.value;
    const fim = formGerar.elements.fim.value;
    if (!inicio || !fim || inicio > fim) return avisar('Período inválido.');
    if ((M.parseData(fim) - M.parseData(inicio)) / 86400000 > 92) return avisar('Gere no máximo 3 meses por vez.');
    const escopo = escopoAtual();
    if (!configMotor(escopo).colaboradores.length && !ativosNoPeriodo(inicio, fim).some((c) => !escopo || c.centroCustoCodigo === escopo)) {
      return avisar(escopo ? 'Nenhum colaborador ativo neste centro de custo.' : 'Cadastre colaboradores primeiro.');
    }
    if (escalaAtual() && !(await confirmar(`Gerar uma nova escala substitui a atual de "${nomeEscopo(escopo)}" (incluindo ajustes manuais). ` +
      'As escalas dos outros centros de custo não mudam. Continuar?'))) return;
    await executar(() => api.post('/api/escala/gerar', { inicio, fim, centroCusto: escopo, excluirSemControle: $('#excluir-sem-controle').checked }));
  });

  $('#escopo-escala').addEventListener('change', () => { periodoPadrao(); renderEscala(); });
  $('#excluir-sem-controle').addEventListener('change', renderEscala);

  $('#btn-excluir-escala').addEventListener('click', async () => {
    if (!exigirEdicao() || !escalaAtual()) return;
    if (!(await confirmar(`Excluir a escala de "${nomeEscopo(escopoAtual())}"?`))) return;
    await executar(() => api.del(`/api/escala?centroCusto=${encodeURIComponent(escopoAtual())}`));
  });

  $('#area-escala').addEventListener('click', async (ev) => {
    const td = ev.target.closest('td[data-c]');
    if (!td || !escalaAtual()) return;
    if (!exigirEdicao()) return;
    td.classList.add('salvando');
    await executar(() => api.post('/api/escala/celula', { colaboradorId: td.dataset.c, indice: Number(td.dataset.i), centroCusto: escopoAtual() }));
  });

  function renderEscala() {
    const area = $('#area-escala');
    const escopo = escopoAtual();
    const e = escalaAtual();
    $('#btn-excluir-escala').hidden = !e;
    if (!e) {
      const outras = Object.keys(estado.escalas || {}).filter((k) => k !== escopo).length;
      area.innerHTML = `<div class="cartao vazio">Ainda não há escala para <b>${esc(nomeEscopo(escopo))}</b>. Defina o período e clique em <b>Gerar escala</b>.` +
        (outras ? `<br><small>Há ${outras} escala(s) gerada(s) para outros centros de custo: escolha no campo Centro de custo.</small>` : '') + '</div>';
      $('#info-escala').textContent = '';
      $('#area-validacao').hidden = true;
      return;
    }
    const quando = (iso) => new Date(iso).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' });
    $('#info-escala').textContent = `${nomeEscopo(escopo)}. ` + (e.geradaEm
      ? `Escala gerada por ${e.geradaPor || '—'} em ${quando(e.geradaEm)}` +
        (e.atualizadaEm !== e.geradaEm ? `; último ajuste em ${quando(e.atualizadaEm)}.` : '.')
      : '');
    const cfg = configMotor();
    if (e.excluirSemControle !== false) {
      const fora = ativosNoPeriodo(e.inicio, e.fim).filter((c) => c.semControleJornada && (!escopo || c.centroCustoCodigo === escopo)).length;
      if (fora) $('#info-escala').textContent += ` ${fora} colaborador(es) sem controle de jornada (CLT art. 62) ficaram fora da escala.`;
    }
    const ocorrencias = M.validarEscala(cfg, e);
    const filtro = '';
    const setores = cfg.setores;
    const porCelula = {};
    for (const o of ocorrencias) {
      if (o.nivel === 'erro' && o.colaboradorId && o.data) porCelula[o.colaboradorId + '|' + o.data] = o;
    }

    const cabDias = e.dias.map((d) => `<th class="${d.dow === 0 ? 'dom' : ''} ${d.feriado ? 'fer' : ''}"
        title="${d.feriado ? esc(d.feriado.nome) : ''}">${d.data.slice(8)}<br><small>${M.NOMES_DIAS[d.dow].charAt(0)}</small></th>`).join('');

    let html = '';
    for (const s of setores) {
      const membros = cfg.colaboradores.filter((c) => c.setorId === s.id && e.celulas[c.id])
        .sort((a, b) => a.nome.localeCompare(b.nome));
      const novos = cfg.colaboradores.filter((c) => c.setorId === s.id && !e.celulas[c.id]).length;
      if (!membros.length) continue;
      const linhas = membros.map((c) => {
        const r = M.resumirColaborador(e, c);
        const cels = e.celulas[c.id].map((t, i) => {
          const d = e.dias[i];
          const erro = porCelula[c.id + '|' + d.data];
          const classe = [t.tipo, d.dow === 0 ? 'dom' : '', d.feriado ? 'fer' : '', erro ? 'erro' : ''].join(' ');
          const txt = t.tipo === 'T' ? M.horaDeMinutos(t.inicio).replace(':00', 'h') : t.tipo;
          const dica = `${dataBR(d.data)} — ` + (t.tipo === 'T'
            ? `${M.horaDeMinutos(t.inicio)} às ${M.horaDeMinutos(t.fim)}` : t.tipo === 'FER' ? 'Feriado' : 'Folga')
            + (d.feriado ? ` (${d.feriado.nome})` : '') + (erro ? `\n⚠ ${erro.mensagem}` : '');
          return `<td class="${classe}" data-c="${c.id}" data-i="${i}" title="${esc(dica)}">${txt}</td>`;
        }).join('');
        return `<tr>
          <th class="fixo">${esc(c.matricula)}</th>
          <th class="fixo nome" title="${esc(c.nome)}">${esc(c.nome)}</th>
          <td class="info">${c.sexo}</td><td class="info">${esc(c.jornada)}</td>
          ${cels}
          <td class="info">${r.dias}</td><td class="info">${r.folgas}</td><td class="info">${r.domingosFolga}</td>
          <td class="info">${horas(r.minutos)}</td><td class="info">${r.minutosNoturnos ? horas(r.minutosNoturnos) : '–'}</td>
        </tr>`;
      }).join('');
      const cobertura = e.dias.map((d, i) => {
        if (!M.setorAberto(s, d)) return '<td class="cob fechado">–</td>';
        const n = membros.filter((c) => e.celulas[c.id][i].tipo === 'T').length;
        return `<td class="cob ${n < (s.minimoPorDia || 0) ? 'baixo' : ''}">${n}</td>`;
      }).join('');
      html += `<div class="cartao bloco-setor">
        <h2>${esc(s.nome)} <small>${escopo ? `CC ${esc(escopo)} · ${esc(nomeCentro(escopo))} · ` : ''}mínimo ${s.minimoPorDia}/dia · ${dataBR(e.inicio)} a ${dataBR(e.fim)}</small></h2>
        ${novos ? `<p class="aviso">${novos} colaborador(es) cadastrado(s) após a geração não estão na escala — gere novamente.</p>` : ''}
        <div class="rolagem"><table class="grade">
          <thead><tr><th class="fixo">Matr.</th><th class="fixo nome">Nome</th><th>Sexo</th><th>Jornada</th>${cabDias}
            <th>Dias</th><th>Folgas</th><th>Dom. folga</th><th>Horas</th><th>Noturnas</th></tr></thead>
          <tbody>${linhas}</tbody>
          <tfoot><tr><th class="fixo" colspan="2">Em serviço</th><td></td><td></td>${cobertura}<td colspan="5"></td></tr></tfoot>
        </table></div></div>`;
    }
    area.innerHTML = html || '<div class="cartao vazio">Nenhum colaborador nos setores selecionados.</div>';
    renderValidacao(ocorrencias, filtro);
  }

  /** "2 alerta(s) de cobertura e 4 de folga em feriado." */
  function resumoAlertas(alertas) {
    const nomes = { Cobertura: 'de cobertura', 'Folga em feriado': 'de folga em feriado', 'Folgas seguidas': 'de folgas seguidas' };
    const cont = {};
    for (const a of alertas) cont[a.regra] = (cont[a.regra] || 0) + 1;
    const partes = Object.entries(cont).map(([r, n]) => `${n} ${nomes[r] || `(${r})`}`);
    const ultima = partes.pop();
    return `Alertas: ${partes.length ? partes.join(', ') + ' e ' : ''}${ultima}.`;
  }

  function renderValidacao(ocorrencias, filtro) {
    const nomeColab = (id) => {
      const c = estado.colaboradores.find((x) => x.id === id);
      return c ? `${c.nome} (${c.matricula})` : '';
    };
    const lista = ocorrencias.filter((o) => {
      if (!filtro) return true;
      const c = estado.colaboradores.find((x) => x.id === o.colaboradorId);
      return o.setorId === filtro || (c && c.setorId === filtro);
    });
    const erros = lista.filter((o) => o.nivel === 'erro');
    const alertas = lista.filter((o) => o.nivel === 'alerta');
    const infos = lista.filter((o) => o.nivel === 'info');
    const item = (o) => `<li class="${o.nivel}">
        <b>${esc(o.regra)}</b>${o.colaboradorId ? ' — ' + esc(nomeColab(o.colaboradorId)) : ''}${o.data ? ' — ' + dataBR(o.data) : ''}:
        ${esc(o.mensagem)} ${o.base ? `<span class="base">${esc(o.base)}</span>` : ''}</li>`;
    $('#validacao').innerHTML = `
      <p class="status ${erros.length ? 'ruim' : 'bom'}">${erros.length
        ? `${erros.length} violação(ões) da legislação encontrada(s).`
        : 'Nenhuma violação da legislação trabalhista encontrada.'}
        ${alertas.length ? ` ${resumoAlertas(alertas)}` : ''}</p>
      ${erros.length ? `<h3>Violações</h3><ul>${erros.map(item).join('')}</ul>` : ''}
      ${alertas.length ? `<h3>Alertas</h3><ul>${alertas.map(item).join('')}</ul>` : ''}
      ${infos.length ? `<details><summary>Observações (${infos.length})</summary><ul>${infos.map(item).join('')}</ul></details>` : ''}`;
    $('#area-validacao').hidden = false;
  }

  $('#btn-csv').addEventListener('click', () => {
    const e = escalaAtual();
    if (!e) return avisar('Gere uma escala primeiro.');
    const escopo = escopoAtual();
    const q = (v) => `"${String(v).replace(/"/g, '""')}"`;
    const linhas = [['Centro de custo', 'Setor', 'Matrícula', 'Nome', 'Sexo', 'Jornada', ...e.dias.map((d) => `${dataBR(d.data)} ${M.NOMES_DIAS[d.dow]}`),
      'Dias trabalhados', 'Folgas', 'Domingos de folga', 'Horas'].map(q).join(';')];
    for (const c of configMotor(escopo).colaboradores) {
      if (!e.celulas[c.id]) continue;
      const r = M.resumirColaborador(e, c);
      linhas.push([c.centroCustoCodigo ? `${c.centroCustoCodigo} ${nomeCentro(c.centroCustoCodigo)}` : '', nomeSetor(c.setorId), c.matricula, c.nome, c.sexo, c.jornada,
        ...e.celulas[c.id].map((t) => (t.tipo === 'T' ? `${M.horaDeMinutos(t.inicio)}-${M.horaDeMinutos(t.fim)}` : t.tipo === 'FER' ? 'FERIADO' : 'FOLGA')),
        r.dias, r.folgas, r.domingosFolga, horas(r.minutos)].map(q).join(';'));
    }
    baixar(`escala_${escopo ? `cc${escopo}_` : ''}${e.inicio}_${e.fim}.csv`, '﻿' + linhas.join('\r\n'), 'text/csv;charset=utf-8');
  });

  $('#btn-imprimir').addEventListener('click', () => window.print());

  // ---------------------------------------------------- backup / exemplo

  function baixar(nome, conteudo, tipo) {
    if (emFrame) {
      abrirDialogo(`Copie o conteúdo abaixo e salve como ${nome}.`, { texto: conteudo.replace(/^\uFEFF/, '') });
      return;
    }
    const url = URL.createObjectURL(new Blob([conteudo], { type: tipo }));
    const a = Object.assign(document.createElement('a'), { href: url, download: nome });
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  $('#btn-exportar-json').addEventListener('click', async () => {
    try {
      const b = await api.get('/api/backup');
      baixar(`gestao-rh-backup-${b.exportadoEm.slice(0, 10)}.json`, JSON.stringify(b, null, 2), 'application/json');
    } catch (e) {
      avisar(e.message);
    }
  });

  $('#arq-json').addEventListener('change', async (ev) => {
    const arq = ev.target.files[0];
    ev.target.value = '';
    if (!arq) return;
    if (!exigirEdicao()) return;
    let dados;
    try {
      dados = JSON.parse(await arq.text());
    } catch (e) {
      return avisar('Arquivo de backup inválido.');
    }
    if (!(await confirmar('Restaurar o backup substitui todos os setores, colaboradores e a escala atual. Continuar?'))) return;
    if (await executar(() => api.post('/api/restaurar', dados))) avisar('Backup restaurado.');
  });

  $('#btn-limpar').addEventListener('click', async () => {
    if (!exigirEdicao()) return;
    if (!(await confirmar('Apagar todos os setores, colaboradores e escalas? Os usuários do sistema são mantidos.'))) return;
    await executar(() => api.del('/api/dados'));
  });

  $('#btn-exemplo').addEventListener('click', async () => {
    if (!exigirEdicao()) return;
    if ((estado.setores.length || estado.colaboradores.length) && !(await confirmar('Substituir os dados atuais pelo exemplo?'))) return;
    await executar(() => api.post('/api/exemplo'));
  });

  // ------------------------------------------------------------- render

  function render() {
    renderInicio();
    renderSetores();
    renderCentros();
    renderColaboradores();
    renderRegras();
    renderEscala();
  }

  formSetor.dispatchEvent(new Event('reset'));
  atualizarDicaJornada();

  // A tela principal só é montada depois do login (js/acesso.js)
  window.EscalaApp = {
    async iniciar(u) {
      usuario = u;
      document.body.classList.toggle('perfil-consulta', !podeEditar());
      document.body.classList.toggle('perfil-admin', u.perfil === 'admin');
      await recarregar();
      periodoPadrao();
      mostrarAba('inicio');
      window.dispatchEvent(new CustomEvent('app-iniciado', { detail: u }));
    },
    encerrar() {
      usuario = null;
      window.dispatchEvent(new CustomEvent('app-encerrado'));
      estado = estadoVazio();
      render();
      document.body.classList.remove('perfil-consulta', 'perfil-admin');
    },
    mostrarAba, mostrarModulo, avisar, confirmar, abrirDialogo, esc, baixar,
    estado: () => estado, podeEditar, nomeCentro,
  };
})();
