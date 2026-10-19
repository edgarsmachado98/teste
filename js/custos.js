/* Módulo Custos de pessoal: lançamentos mensais da folha, relatórios gerenciais e parâmetros de encargos. */
(function () {
  'use strict';

  const CU = window.EscalaCustos;
  const M = window.EscalaMotor;
  const api = window.EscalaApi;
  const App = window.EscalaApp;
  const $ = (sel) => document.querySelector(sel);
  const esc = App.esc;
  const dataBR = (iso) => (iso ? iso.split('-').reverse().join('/') : '');

  let usuario = null;
  let dados = { parametros: CU.PARAMETROS_PADRAO, competencias: [], lancamentos: [] };
  let comp = null;      // competência aberta na grade
  let rascunho = {};    // colaboradorId -> lançamento em edição
  let removidos = new Set();
  let sujo = false;

  const podeVer = () => !!usuario && usuario.perfil !== 'consulta';
  const estado = () => App.estado();
  const colab = (id) => estado().colaboradores.find((c) => c.id === id);
  const nomeSetor = (id) => (estado().setores.find((s) => s.id === id) || {}).nome || '—';

  // ------------------------------------------------------------- formatos

  const fmt = (v, casas = 2) => (Number(v) || 0).toLocaleString('pt-BR', { minimumFractionDigits: casas, maximumFractionDigits: casas });
  const moeda = (v) => `R$ ${fmt(v)}`;
  const pct = (v) => (v == null ? '—' : `${fmt(v, 1)}%`);
  const horas = (v) => `${fmt(v, Number.isInteger(Math.round((Number(v) || 0) * 100) / 100) ? 0 : 1)} h`;
  const campoTexto = (c, v) => {
    if (c.tipo === 'motivo') return v || '';
    const n = Number(v) || 0;
    if (!n) return '';
    return c.tipo === 'moeda' ? fmt(n) : fmt(n, Number.isInteger(n) ? 0 : 2);
  };

  /** Feriados nacionais e locais dos anos usados (para o reflexo das horas extras no DSR). */
  function feriados(anos) {
    const e = estado();
    const lista = e.feriadosExtras.map((f) => f.data);
    for (const a of anos) lista.push(...M.feriadosNacionais(a, e.incluirFacultativos).map((f) => f.data));
    return lista;
  }
  const anosDe = (comps) => [...new Set(comps.map((c) => Number(c.slice(0, 4))))];

  // dimensão de agrupamento dos relatórios: o cálculo agrupa por "setorId", então cada colaborador
  // recebe a chave da dimensão escolhida (setor, centro de custo, departamento ou estabelecimento)
  const DIMENSOES = {
    setor: ['Setor', 'todos os setores'], centroCusto: ['Centro de custo', 'todos os centros de custo'],
    departamento: ['Departamento', 'todos os departamentos'], estabelecimento: ['Estabelecimento', 'todos os estabelecimentos'],
  };
  let rot = 'Setor';

  function agrupar(dim) {
    const e = estado();
    if (dim === 'setor') return { colaboradores: e.colaboradores, grupos: e.setores.map((s) => ({ id: s.id, nome: s.nome })) };
    const chave = {
      centroCusto: (c) => [c.centroCustoCodigo, c.centroCustoCodigo ? `${c.centroCustoCodigo} · ${App.nomeCentro(c.centroCustoCodigo)}` : 'Sem centro de custo'],
      departamento: (c) => [c.departamento, c.departamento || 'Sem departamento'],
      estabelecimento: (c) => [c.estabelecimento, c.estabelecimento || 'Sem estabelecimento'],
    }[dim];
    const grupos = new Map();
    const colaboradores = e.colaboradores.map((c) => {
      const [id, nome] = chave(c);
      const k = `${dim}:${id || ''}`;
      grupos.set(k, nome);
      return { ...c, setorId: k };
    });
    return {
      colaboradores,
      grupos: [...grupos].map(([id, nome]) => ({ id, nome })).sort((a, b) => a.nome.localeCompare(b.nome, 'pt-BR', { numeric: true })),
    };
  }

  /** Dados para os relatórios (lançamentos já salvos). */
  function baseRelatorios() {
    const e = estado();
    const comps = dados.competencias.map((c) => c.competencia);
    const g = agrupar($('#rl-dimensao').value);
    return {
      colaboradores: g.colaboradores, setores: g.grupos, lancamentos: dados.lancamentos,
      competencias: dados.competencias, parametros: dados.parametros,
      feriados: feriados(anosDe(comps.length ? comps : [mesAtual()])),
    };
  }

  function mesAtual() {
    const h = new Date();
    return `${h.getFullYear()}-${String(h.getMonth() + 1).padStart(2, '0')}`;
  }

  // ---------------------------------------------------------------- carga

  async function carregar() {
    if (!podeVer()) return;
    try {
      dados = await api.get('/api/custos');
    } catch (e) {
      if (e.status !== 401) App.avisar(e.message);
      return;
    }
    renderTudo();
  }

  function renderTudo() {
    renderCompetencias();
    if (comp && !dados.competencias.some((c) => c.competencia === comp)) comp = null;
    if (!comp && dados.competencias.length) comp = dados.competencias[dados.competencias.length - 1].competencia;
    abrirGrade(comp, true);
    if (!comp && !$('#fl-comp').value) $('#fl-comp').value = CU.somarMes(mesAtual(), -1);
    renderParametros();
    prepararFiltros();
    renderRelatorio();
  }

  window.addEventListener('app-iniciado', (ev) => {
    usuario = ev.detail;
    comp = null;
    carregar();
  });
  window.addEventListener('app-encerrado', () => {
    usuario = null;
    dados = { parametros: CU.PARAMETROS_PADRAO, competencias: [], lancamentos: [] };
    rascunho = {};
    sujo = false;
  });
  // cadastro alterado (colaboradores, setores, feriados): redesenha sem perder a edição
  window.addEventListener('dados-atualizados', () => {
    if (!podeVer()) return;
    if (!sujo) { carregar(); return; }
    prepararFiltros();
    renderRelatorio();
  });
  document.querySelectorAll('[data-modulo="custos"]').forEach((b) => {
    if (b.matches('button')) b.addEventListener('click', () => { if (!sujo) carregar(); });
  });
  window.addEventListener('beforeunload', (ev) => {
    if (sujo) { ev.preventDefault(); ev.returnValue = ''; }
  });

  // ---------------------------------------------------------- competências

  function renderCompetencias() {
    const lista = [...dados.competencias].reverse();
    $('#fl-competencias').innerHTML = lista.length
      ? lista.map((c) => {
        const n = dados.lancamentos.filter((l) => l.competencia === c.competencia).length;
        return `<button type="button" class="fl-comp ${c.competencia === comp ? 'ativa' : ''}" data-comp="${c.competencia}">
          <b>${CU.rotuloComp(c.competencia)}</b><small>${n} lançamento(s)</small></button>`;
      }).join('')
      : '<p class="vazio">Nenhuma competência aberta. Escolha o mês e clique em <b>Abrir competência</b>.</p>';
  }

  async function descartarAlteracoes() {
    if (!sujo) return true;
    if (!(await App.confirmar('Há lançamentos alterados e não salvos. Descartar as alterações?'))) return false;
    sujo = false;
    return true;
  }

  $('#fl-competencias').addEventListener('click', async (ev) => {
    const b = ev.target.closest('button[data-comp]');
    if (!b || b.dataset.comp === comp || !(await descartarAlteracoes())) return;
    abrirGrade(b.dataset.comp, true);
    renderCompetencias();
  });

  $('#fl-abrir').addEventListener('click', async () => {
    const c = $('#fl-comp').value;
    if (!CU.competenciaValida(c)) return App.avisar('Escolha o mês da competência.');
    if (c !== comp && !(await descartarAlteracoes())) return;
    if (c === comp && sujo) await salvar(false);
    try {
      const antes = dados.lancamentos.filter((l) => l.competencia === c).length;
      dados = await api.post(`/api/folha/${c}/abrir`, {});
      const depois = dados.lancamentos.filter((l) => l.competencia === c).length;
      comp = c;
      sujo = false;
      renderTudo();
      if (antes && depois === antes) App.avisar(`A competência ${CU.rotuloComp(c)} já tinha todos os colaboradores com vínculo no mês.`);
    } catch (e) {
      if (e.status !== 401) App.avisar(e.message);
    }
  });

  // ------------------------------------------------------------------ grade

  const CAMPOS = CU.CAMPOS;
  const GRUPOS = [...new Set(CAMPOS.map((c) => c.grupo))];

  function abrirGrade(c, recarregarRascunho) {
    comp = c;
    $('#fl-area').hidden = !c;
    if (!c) return;
    $('#fl-comp').value = c;
    if (recarregarRascunho) {
      rascunho = {};
      removidos = new Set();
      for (const l of dados.lancamentos.filter((x) => x.competencia === c)) rascunho[l.colaboradorId] = { ...l };
      const info = dados.competencias.find((x) => x.competencia === c) || {};
      $('#fl-premio').value = info.premioSaude === '' || info.premioSaude == null ? '' : fmt(info.premioSaude);
      $('#fl-sinistros').value = info.sinistrosSaude === '' || info.sinistrosSaude == null ? '' : fmt(info.sinistrosSaude);
      sujo = false;
    }
    $('#fl-titulo').textContent = `Competência ${CU.rotuloComp(c)}`;
    renderGrade();
  }

  function linhasDaGrade() {
    const busca = $('#fl-busca').value.trim().toLowerCase();
    return Object.keys(rascunho).map((id) => ({ id, c: colab(id) })).filter((x) => x.c)
      .filter((x) => !busca || x.c.nome.toLowerCase().includes(busca) || x.c.matricula.includes(busca))
      .sort((a, b) => nomeSetor(a.c.setorId).localeCompare(nomeSetor(b.c.setorId)) || a.c.nome.localeCompare(b.c.nome));
  }

  const calendarioComp = () => CU.calendario(comp, feriados([Number(comp.slice(0, 4))]).filter((f) => f.startsWith(comp)));

  function calcular(id) {
    return CU.calcularLancamento(rascunho[id], colab(id), dados.parametros, calendarioComp());
  }

  function renderGrade() {
    const linhas = linhasDaGrade();
    const opcoesMotivo = '<option value=""></option>' +
      Object.entries(CU.MOTIVOS_ATESTADO).map(([k, n]) => `<option value="${k}">${esc(n)}</option>`).join('');
    const cabGrupos = GRUPOS.map((g) => `<th colspan="${CAMPOS.filter((c) => c.grupo === g).length}" class="fl-grupo">${esc(g)}</th>`).join('');
    const cabCampos = CAMPOS.map((c) => `<th class="${c.tipo === 'motivo' ? '' : 'num'}">${esc(c.nome)}</th>`).join('');
    const corpo = linhas.map(({ id, c }) => {
      const l = rascunho[id];
      const removido = removidos.has(id);
      const cels = CAMPOS.map((campo) => {
        if (campo.tipo === 'motivo') {
          return `<td><select class="fl-in" data-c="${id}" data-k="${campo.id}" aria-label="${esc(campo.nome)} de ${esc(c.nome)}">${
            opcoesMotivo.replace(`value="${l.atestadoMotivo || ''}"`, `value="${l.atestadoMotivo || ''}" selected`)}</select></td>`;
        }
        return `<td><input class="fl-in num ${campo.tipo}" data-c="${id}" data-k="${campo.id}" inputmode="decimal" placeholder="0"
          value="${esc(campoTexto(campo, l[campo.id]))}" aria-label="${esc(campo.nome)} de ${esc(c.nome)}"></td>`;
      }).join('');
      const desligado = c.desligamento && c.desligamento.slice(0, 7) === comp ? `<small class="ruim">desligamento em ${dataBR(c.desligamento)}</small>` : '';
      const admitido = c.admissao && c.admissao.slice(0, 7) === comp ? `<small class="bom">admissão em ${dataBR(c.admissao)}</small>` : '';
      return `<tr class="${removido ? 'removido' : ''}" data-linha="${id}">
        <th class="fixo"><b>${esc(c.nome)}</b><small>${esc(c.matricula)} · ${esc(nomeSetor(c.setorId))}</small>${admitido}${desligado}</th>
        ${cels}
        <td class="num total" data-total="${id}"></td>
        <td><button type="button" class="mini ${removido ? 'sec' : 'perigo'}" data-remover="${id}">${removido ? 'Manter' : 'Remover'}</button></td>
      </tr>`;
    }).join('');
    $('#fl-grade').innerHTML = `
      <thead><tr><th class="fixo" rowspan="2">Colaborador</th>${cabGrupos}<th rowspan="2" class="num">Custo total</th><th rowspan="2"></th></tr>
        <tr>${cabCampos}</tr></thead>
      <tbody>${corpo || `<tr><td colspan="${CAMPOS.length + 3}" class="vazio">Nenhum lançamento${$('#fl-busca').value ? ' encontrado' : ''}.</td></tr>`}</tbody>
      <tfoot><tr><th class="fixo">Totais</th>${CAMPOS.map((c) => `<td class="num" data-soma="${c.id}"></td>`).join('')}
        <td class="num total" id="fl-soma-total"></td><td></td></tr></tfoot>`;
    $('#fl-premio').placeholder = 'soma dos lançamentos';
    atualizarTotais();
    const semLancamento = estado().colaboradores.filter((x) => CU.ativoNoMes(x, comp) && !rascunho[x.id]).length;
    $('#fl-status').textContent = (semLancamento
      ? `${semLancamento} colaborador(es) com vínculo no mês ainda sem lançamento — clique em Abrir competência para incluí-los. ` : '') +
      (sujo ? 'Há alterações não salvas.' : '');
  }

  function atualizarTotais() {
    const somas = {};
    let total = 0;
    let saude = 0;
    for (const id of Object.keys(rascunho)) {
      if (!colab(id)) continue;
      const cel = document.querySelector(`[data-total="${id}"]`);
      if (removidos.has(id)) { if (cel) cel.textContent = '—'; continue; }
      const r = calcular(id);
      if (cel) {
        cel.textContent = fmt(r.custoTotal);
        cel.title = `Remuneração ${moeda(r.remuneracao)} + encargos ${moeda(r.encargos)} + provisões ${moeda(r.provisoes)} + benefícios ${moeda(r.beneficios)}`;
      }
      total += r.custoTotal;
      saude += r.porBeneficio.saude;
      for (const c of CAMPOS) if (c.tipo !== 'motivo') somas[c.id] = (somas[c.id] || 0) + (CU.lerNumero(rascunho[id][c.id]) || 0);
    }
    for (const c of CAMPOS) {
      const el = document.querySelector(`[data-soma="${c.id}"]`);
      if (el) el.textContent = c.tipo === 'motivo' ? '' : c.tipo === 'moeda' ? fmt(somas[c.id]) : fmt(somas[c.id] || 0, c.tipo === 'dias' ? 0 : 1);
    }
    $('#fl-soma-total').textContent = fmt(total);
    $('#fl-premio').placeholder = `soma dos lançamentos: ${fmt(saude)}`;
  }

  function marcarSujo() {
    sujo = true;
    if (!/não salvas/.test($('#fl-status').textContent)) $('#fl-status').textContent += ' Há alterações não salvas.';
  }

  $('#fl-grade').addEventListener('input', (ev) => {
    const el = ev.target.closest('.fl-in');
    if (!el) return;
    const l = rascunho[el.dataset.c];
    if (!l) return;
    l[el.dataset.k] = el.value;
    if (el.tagName === 'INPUT') el.classList.toggle('invalido', el.value.trim() !== '' && CU.lerNumero(el.value) == null);
    marcarSujo();
    atualizarTotais();
  });
  $('#fl-grade').addEventListener('change', (ev) => {
    const el = ev.target.closest('select.fl-in');
    if (el) { rascunho[el.dataset.c][el.dataset.k] = el.value; marcarSujo(); }
  });
  $('#fl-grade').addEventListener('click', (ev) => {
    const b = ev.target.closest('button[data-remover]');
    if (!b) return;
    const id = b.dataset.remover;
    if (removidos.has(id)) removidos.delete(id); else removidos.add(id);
    marcarSujo();
    renderGrade();
  });
  // Enter desce para a linha de baixo, como numa planilha
  $('#fl-grade').addEventListener('keydown', (ev) => {
    if (ev.key !== 'Enter' || !ev.target.matches('input.fl-in')) return;
    ev.preventDefault();
    const td = ev.target.closest('td');
    const tr = td.parentElement;
    const proxima = ev.shiftKey ? tr.previousElementSibling : tr.nextElementSibling;
    const alvo = proxima && proxima.children[td.cellIndex] && proxima.children[td.cellIndex].querySelector('input');
    if (alvo) { alvo.focus(); alvo.select(); }
  });
  $('#fl-busca').addEventListener('input', renderGrade);
  for (const sel of ['#fl-premio', '#fl-sinistros']) $(sel).addEventListener('input', marcarSujo);

  async function salvar(avisarOk = true) {
    if (!comp) return false;
    const invalidos = document.querySelectorAll('#fl-grade .invalido').length;
    if (invalidos) { App.avisar(`Corrija os ${invalidos} campo(s) destacados em vermelho (use números como 10,5 ou 1.234,56).`); return false; }
    const lancamentos = Object.keys(rascunho).filter((id) => colab(id)).map((id) => (removidos.has(id)
      ? { colaboradorId: id, remover: true } : { ...rascunho[id], colaboradorId: id }));
    $('#fl-salvar').disabled = true;
    try {
      dados = await api.put(`/api/folha/${comp}`, {
        lancamentos, premioSaude: $('#fl-premio').value, sinistrosSaude: $('#fl-sinistros').value,
      });
      sujo = false;
      renderTudo();
      if (avisarOk) $('#fl-status').textContent = `Lançamentos de ${CU.rotuloComp(comp)} salvos.`;
      return true;
    } catch (e) {
      if (e.status !== 401) App.avisar(e.message);
      return false;
    } finally {
      $('#fl-salvar').disabled = false;
    }
  }
  $('#fl-salvar').addEventListener('click', () => salvar());

  $('#fl-excluir').addEventListener('click', async () => {
    if (!comp) return;
    const n = Object.keys(rascunho).length;
    if (!(await App.confirmar(`Excluir a competência ${CU.rotuloComp(comp)} e os ${n} lançamento(s) dela? Esta ação não pode ser desfeita.`))) return;
    try {
      dados = await api.del(`/api/folha/${comp}`);
      comp = null;
      sujo = false;
      renderTudo();
    } catch (e) {
      if (e.status !== 401) App.avisar(e.message);
    }
  });

  // ----------------------------------------------------- planilha e CSV

  function modeloCSV() {
    const cab = ['matricula', 'nome', ...CAMPOS.map((c) => c.apelidos[0])];
    const linhas = linhasDaGrade().map(({ id, c }) => {
      const l = rascunho[id];
      return [c.matricula, c.nome, ...CAMPOS.map((campo) => (campo.tipo === 'motivo' ? (l.atestadoMotivo ? CU.MOTIVOS_ATESTADO[l.atestadoMotivo] : '') : campoTexto(campo, l[campo.id])))];
    });
    const q = (v) => (/[;"\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : String(v));
    return '﻿' + [cab, ...linhas].map((l) => l.map(q).join(';')).join('\r\n');
  }
  $('#fl-modelo').addEventListener('click', () => {
    if (!comp) return;
    App.baixar(`lancamentos_${comp}.csv`, modeloCSV(), 'text/csv;charset=utf-8');
  });

  async function importar(texto) {
    let lido;
    try {
      lido = CU.lerPlanilhaLancamentos(texto);
    } catch (e) {
      return App.avisar(e.message);
    }
    if (!lido.linhas.length) return App.avisar('Nenhuma linha com matrícula encontrada.');
    const nomes = lido.colunas.map((id) => CAMPOS.find((c) => c.id === id).nome);
    if (!(await App.confirmar(`Importar ${lido.linhas.length} linha(s) para ${CU.rotuloComp(comp)}?\n\nColunas reconhecidas: ${nomes.join(', ')}.` +
      (lido.ignoradas.length ? `\nColunas ignoradas: ${lido.ignoradas.join(', ')}.` : '') +
      '\n\nSó as colunas reconhecidas são alteradas; os demais valores do lançamento são mantidos.'))) return;
    if (sujo && !(await salvar(false))) return;
    try {
      const r = await api.post(`/api/folha/${comp}/importar`, { linhas: lido.linhas });
      dados = { parametros: r.parametros, competencias: r.competencias, lancamentos: r.lancamentos };
      sujo = false;
      renderTudo();
      App.avisar(`${r.importados} linha(s) importada(s).` + (r.ignorados.length ? `\n\nIgnoradas:\n${r.ignorados.slice(0, 15).join('\n')}` +
        (r.ignorados.length > 15 ? `\n… e mais ${r.ignorados.length - 15}` : '') : ''));
    } catch (e) {
      if (e.status !== 401) App.avisar(e.message);
    }
  }

  $('#fl-arquivo').addEventListener('change', async (ev) => {
    const arq = ev.target.files[0];
    ev.target.value = '';
    if (arq && comp) importar(await arq.text());
  });

  $('#fl-colar').addEventListener('click', async () => {
    if (!comp) return;
    const area = $('#dialogo-texto');
    const p = App.abrirDialogo('Cole as linhas copiadas da planilha, incluindo a linha de cabeçalho com a coluna "matricula" ' +
      '(veja os nomes das colunas em Baixar modelo).', { cancelar: true, texto: '' });
    area.readOnly = false;
    area.value = '';
    $('#dialogo-copiar').hidden = true;
    area.focus();
    const ok = await p;
    area.readOnly = true;
    if (ok && area.value.trim()) importar(area.value);
  });

  // ------------------------------------------------------------ parâmetros

  const formEnc = $('#form-encargos');
  $('#enc-regime').innerHTML = Object.entries(CU.REGIMES).map(([k, n]) => `<option value="${k}">${esc(n)}</option>`).join('');

  function renderParametros() {
    const p = CU.parametros(dados.parametros);
    for (const k of Object.keys(CU.PARAMETROS_PADRAO)) {
      const el = formEnc.elements[k];
      if (el) el.value = k === 'regime' || k === 'rat' ? String(p[k]) : fmt(p[k], Number.isInteger(p[k]) ? 0 : 2);
    }
    atualizarRegime();
    renderResumoEncargos(p);
  }

  function atualizarRegime() {
    const simples = formEnc.elements.regime.value === 'simples';
    for (const k of ['inss', 'rat', 'fap', 'terceiros']) formEnc.elements[k].disabled = simples;
  }

  function parametrosDoForm() {
    const out = {};
    for (const k of Object.keys(CU.PARAMETROS_PADRAO)) out[k] = formEnc.elements[k].value;
    return out;
  }

  function renderResumoEncargos(p) {
    const e = CU.encargos(p);
    const r = CU.calcularLancamento({ salario: 1000 }, { jornada: '6x1' }, p, { uteis: 25, descanso: 5 });
    const linha = (rotulo, valor, base) => `<tr><td>${rotulo}</td><td class="num">${valor}</td><td class="suave">${base}</td></tr>`;
    $('#enc-resumo').innerHTML = `<table class="tabela">
      <thead><tr><th>Item</th><th class="num">Percentual</th><th>Base legal</th></tr></thead><tbody>
      ${linha('INSS patronal', pct(e.inss), 'Lei 8.212/1991, art. 22, I')}
      ${linha('RAT/SAT × FAP', pct(e.rat), 'Lei 8.212/1991, art. 22, II; Lei 10.666/2003')}
      ${linha('Terceiros (Sistema S, salário-educação, Incra)', pct(e.terceiros), 'conforme o FPAS da empresa')}
      ${linha('FGTS', pct(e.fgts), 'Lei 8.036/1990, art. 15')}
      <tr class="destaque"><td><b>Encargos sobre a remuneração</b></td><td class="num"><b>${pct(e.total)}</b></td><td></td></tr>
      ${linha('Provisão de férias (1/12 + 1/3)', pct(100 / 12 * 4 / 3), 'CF art. 7º, XVII; CLT art. 130')}
      ${linha('Provisão de 13º salário (1/12)', pct(100 / 12), 'Lei 4.090/1962')}
      ${linha('Encargos sobre as provisões', pct((100 / 12 * 4 / 3 + 100 / 12) * e.total / 100), 'mesmos percentuais acima')}
      </tbody></table>
      <p class="dica">Exemplo: para R$ 1.000,00 de salário, sem horas extras nem benefícios, a empresa gasta
        <b>${moeda(r.custoTotal)}</b> por mês (${fmt(r.multiplicador)} vezes o salário): encargos de ${moeda(r.encargos)} e
        provisões com encargos de ${moeda(r.provisoes)}. Os benefícios são somados ao custo pelo valor informado no lançamento.</p>
      <p class="dica">Horas extras: valor-hora = salário ÷ divisor da jornada (220 para 44h semanais, 200 para 40h, 180 para 36h,
        210 para 12x36), com 50% ou 100% e reflexo no DSR proporcional a domingos e feriados do mês. Faltas e atrasos
        são descontados pelo valor-hora; atestados não descontam.</p>`;
  }

  formEnc.elements.regime.addEventListener('change', () => { atualizarRegime(); renderResumoEncargos(parametrosDoForm()); });
  formEnc.addEventListener('input', () => renderResumoEncargos(parametrosDoForm()));
  formEnc.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    try {
      dados.parametros = await api.put('/api/custos/parametros', parametrosDoForm());
      renderParametros();
      if (comp) atualizarTotais();
      renderRelatorio();
      App.avisar('Parâmetros salvos. Os custos e relatórios já usam os novos percentuais.');
    } catch (e) {
      if (e.status !== 401) App.avisar(e.message);
    }
  });

  // ------------------------------------------------------------ relatórios

  const RELATORIOS = [
    { grupo: 'Quadro de pessoal', itens: [
      ['quadro', 'Perfil do quadro de pessoal'],
    ] },
    { grupo: 'Custos e orçamento', itens: [
      ['headcount', 'Headcount e massa salarial'],
      ['horas-extras', 'Horas extras e adicionais'],
      ['provisoes', 'Provisão de férias e 13º salário'],
      ['custo', 'Custo total por colaborador'],
    ] },
    { grupo: 'Gestão de benefícios', itens: [
      ['sinistralidade', 'Sinistralidade do plano de saúde'],
      ['beneficios', 'Custo per capita de benefícios'],
      ['absenteismo-medico', 'Absenteísmo por motivo médico'],
    ] },
    { grupo: 'Movimentação de pessoal', itens: [
      ['turnover', 'Turnover (rotatividade)'],
      ['turnover-tipo', 'Turnover voluntário e involuntário'],
      ['motivos', 'Motivos de desligamento'],
    ] },
    { grupo: 'Produtividade e tempo', itens: [
      ['absenteismo', 'Taxa de absenteísmo geral'],
      ['banco-horas', 'Banco de horas e compensações'],
    ] },
  ];
  const NOMES_RELATORIO = Object.fromEntries(RELATORIOS.flatMap((g) => g.itens));
  $('#rl-tipo').innerHTML = RELATORIOS.map((g) => `<optgroup label="${esc(g.grupo)}">${
    g.itens.map(([k, n]) => `<option value="${k}">${esc(n)}</option>`).join('')}</optgroup>`).join('');

  let periodoDefinido = false;
  function prepararFiltros() {
    const sel = $('#rl-setor');
    const v = sel.value;
    const dim = $('#rl-dimensao').value;
    const grupos = agrupar(dim).grupos;
    rot = DIMENSOES[dim][0];
    $('#rl-filtro-rotulo').textContent = rot;
    sel.innerHTML = `<option value="">${DIMENSOES[dim][1][0].toUpperCase() + DIMENSOES[dim][1].slice(1)}</option>` +
      grupos.map((s) => `<option value="${esc(s.id)}">${esc(s.nome)}</option>`).join('');
    sel.value = grupos.some((s) => s.id === v) ? v : '';
    if (!periodoDefinido) {
      const comps = dados.competencias.map((c) => c.competencia);
      const ate = comps.length ? comps[comps.length - 1] : mesAtual();
      $('#rl-ate').value = ate;
      $('#rl-de').value = CU.somarMes(ate, -5);
      if (comps.length) periodoDefinido = true;
    }
  }
  $('#rl-dimensao').addEventListener('change', () => { prepararFiltros(); renderRelatorio(); });
  for (const id of ['#rl-tipo', '#rl-de', '#rl-ate', '#rl-setor']) {
    $(id).addEventListener('change', () => { if (id !== '#rl-setor' && id !== '#rl-tipo') periodoDefinido = true; renderRelatorio(); });
  }

  // célula: texto simples ou { t: texto (CSV), h: html, c: classe }
  const celula = (x) => (x && typeof x === 'object' ? x : { t: x == null ? '' : String(x) });
  const chip = (texto, classe) => ({ t: texto, h: `<span class="chip ${classe}">${esc(texto)}</span>` });
  const barra = (valor, maximo, texto, classe = '') => ({
    t: texto, c: 'num', h: `<span class="rl-barra ${classe}"><span data-largura="${Math.max(0, Math.min(100, maximo ? valor / maximo * 100 : 0)).toFixed(1)}"></span></span>${esc(texto)}`,
  });
  const num = (t) => ({ t, c: 'num' });
  const colabCel = (c, setor) => ({ t: `${c.nome} (${c.matricula})`, h: `<b>${esc(c.nome)}</b><small>${esc(c.matricula)}${setor ? ' · ' + esc(setor) : ''}</small>` });

  /** Cada relatório devolve { tiles, avisos, tabelas: [{ titulo, cab, linhas, rodape }], notas }. */
  const GERADORES = {
    quadro(d, de, ate, setor) {
      const r = CU.perfilQuadro(d, ate, setor);
      const g = r.geral;
      const pctDe = (n, t) => (t ? `${fmt(n / t * 100, 1)}%` : '—');
      const avisos = [];
      if (r.cota.pct) {
        avisos.push(r.cota.deficit
          ? `<b>Cota de PcD:</b> com ${r.cota.totalEmpresa} empregados a empresa deve ter ${r.cota.pct}% (${r.cota.exigidos}) de pessoas com deficiência ou reabilitadas; há ${r.cota.pcd}, faltam ${r.cota.deficit} (Lei 8.213/1991, art. 93).`
          : `Cota de PcD cumprida: ${r.cota.pcd} de ${r.cota.exigidos} exigidos (${r.cota.pct}% de ${r.cota.totalEmpresa} empregados).`);
      }
      const semDados = d.colaboradores.filter((c) => CU.ativoEm(c, CU.ultimoDia(ate)) && (!c.admissao || !c.nascimento)).length;
      if (semDados) avisos.push(`${semDados} colaborador(es) sem data de admissão ou de nascimento: importe a planilha de empregados para completar.`);
      const faixa = (lista) => lista.map((f) => [f.nome, num(String(f.total)), barra(f.total, g.total, pctDe(f.total, g.total))]);
      const anos = (v) => (v == null ? '—' : `${fmt(v, 1)} anos`);
      const maiorGrupo = Math.max(1, ...r.grupos.map((x) => x.total));
      return {
        tiles: [
          ['Colaboradores ativos', String(g.total), `${g.mulheres} mulheres, ${g.homens} homens`],
          ['Salário médio', moeda(g.salarioMedio), `folha contratual ${moeda(g.folhaContratual)}`],
          ['Idade média', anos(g.idadeMedia), `tempo de casa médio: ${anos(g.tempoCasaMedio)}`],
          ['PcD na empresa', `${r.cota.pcd} de ${r.cota.exigidos}`, r.cota.pct ? `cota de ${r.cota.pct}%` : 'menos de 100 empregados: sem cota', r.cota.deficit ? 'ruim' : 'bom'],
        ],
        avisos,
        tabelas: [{
          titulo: `Por ${rot.toLowerCase()}`,
          cab: [rot, { t: 'Ativos', c: 'num' }, { t: 'Mulheres', c: 'num' }, { t: 'Homens', c: 'num' }, { t: 'PcD', c: 'num' }, { t: 'Aprendizes', c: 'num' },
            { t: 'Salário médio', c: 'num' }, { t: 'Folha contratual', c: 'num' }, { t: 'Idade média', c: 'num' }, { t: 'Tempo de casa', c: 'num' }],
          linhas: r.grupos.map((x) => [x.nome, barra(x.total, maiorGrupo, String(x.total)), num(String(x.mulheres)), num(String(x.homens)), num(String(x.pcd)),
            num(String(x.aprendizes)), num(fmt(x.salarioMedio)), num(fmt(x.folhaContratual)), num(anos(x.idadeMedia)), num(anos(x.tempoCasaMedio))]),
          rodape: ['Total', num(String(g.total)), num(String(g.mulheres)), num(String(g.homens)), num(String(g.pcd)), num(String(g.aprendizes)),
            num(fmt(g.salarioMedio)), num(fmt(g.folhaContratual)), num(anos(g.idadeMedia)), num(anos(g.tempoCasaMedio))],
        }, {
          titulo: 'Faixa etária', cab: ['Faixa', { t: 'Colaboradores', c: 'num' }, { t: '%', c: 'num' }], linhas: faixa(r.idade),
        }, {
          titulo: 'Tempo de casa', cab: ['Faixa', { t: 'Colaboradores', c: 'num' }, { t: '%', c: 'num' }], linhas: faixa(r.tempoCasa),
        }],
        notas: [`Posição no último dia de ${CU.rotuloComp(ate)}, pelos dados do cadastro (salário contratual da ficha). ` +
          'A cota de PcD considera todos os empregados ativos. Aprendizes: cargos com "aprendiz" no nome; a cota de 5% a 15% (CLT art. 429) ' +
          'incide sobre as funções que exigem formação profissional, conforme a CBO.'],
      };
    },

    headcount(d, de, ate, setor) {
      const r = CU.headcountMassa(d, de, ate, setor);
      const ult = r.meses[r.meses.length - 1];
      const vidasMes = r.meses.reduce((t, m) => t + m.lancamentos, 0);
      const maxMassa = Math.max(...r.meses.map((m) => m.total.massa), 0);
      return {
        tiles: [
          ['Headcount em ' + CU.rotuloComp(ate), String(ult ? ult.total.hc : 0), `${r.variacaoHeadcount >= 0 ? '+' : ''}${r.variacaoHeadcount} no período`],
          ['Massa salarial do período', moeda(r.massaTotal), 'salários, horas extras, adicionais e DSR'],
          ['Custo total do período', moeda(r.custoTotal), 'com encargos, provisões e benefícios'],
          ['Custo médio por colaborador', moeda(vidasMes ? r.custoTotal / vidasMes : 0), 'por mês'],
        ],
        tabelas: [{
          titulo: 'Evolução mensal',
          cab: ['Mês', ...r.setores.map((s) => ({ t: `HC ${s.nome}`, c: 'num' })), { t: 'Headcount', c: 'num' }, { t: 'Massa salarial', c: 'num' }, { t: 'Custo total', c: 'num' }],
          linhas: r.meses.map((m) => [CU.rotuloComp(m.competencia), ...r.setores.map((s) => num(String(m.porSetor[s.id].hc))),
            num(String(m.total.hc)), m.temLancamentos ? barra(m.total.massa, maxMassa, fmt(m.total.massa)) : num('sem lançamentos'), num(m.temLancamentos ? fmt(m.total.custo) : '—')]),
        }, {
          titulo: `Por ${rot.toLowerCase()} no período`,
          cab: [rot, { t: 'HC inicial', c: 'num' }, { t: 'HC final', c: 'num' }, { t: 'Variação', c: 'num' }, { t: 'Massa salarial', c: 'num' }, { t: '% da massa', c: 'num' }, { t: 'Custo total', c: 'num' }],
          linhas: r.setores.map((s) => {
            const massa = r.meses.reduce((t, m) => t + m.porSetor[s.id].massa, 0);
            const custo = r.meses.reduce((t, m) => t + m.porSetor[s.id].custo, 0);
            const ini = r.meses[0].porSetor[s.id].hc;
            const fim = ult.porSetor[s.id].hc;
            return [s.nome, num(String(ini)), num(String(fim)), num(`${fim - ini >= 0 ? '+' : ''}${fim - ini}`), num(fmt(massa)),
              num(pct(r.massaTotal ? massa / r.massaTotal * 100 : 0)), num(fmt(custo))];
          }),
        }],
        notas: ['Headcount: colaboradores com vínculo no último dia de cada mês. Massa salarial: remuneração dos lançamentos (salário + horas extras + adicionais + DSR − faltas).'],
      };
    },

    'horas-extras'(d, de, ate, setor) {
      const r = CU.horasExtras(d, de, ate, setor);
      const p = CU.parametros(d.parametros);
      const avisos = r.setores.filter((s) => s.equivalente >= 0.5).map((s) =>
        `As horas extras de <b>${esc(s.setor)}</b> equivalem a ${fmt(s.equivalente, 1)} colaborador(es) em jornada integral: avalie uma contratação ou a revisão dos processos.`);
      if (r.recorrentes) avisos.push(`${r.recorrentes} colaborador(es) fizeram horas extras em 3 meses seguidos ou mais. Horas extras habituais integram férias, 13º e aviso prévio (Súmula 376 do TST).`);
      return {
        tiles: [
          ['Horas extras', horas(r.totalHoras), `${fmt(r.meses ? r.totalHoras / r.meses : 0, 1)} h por mês`],
          ['Horas extras e adicionais', moeda(r.totalValor), 'com noturno, DSR e outros adicionais'],
          ['Horas extras recorrentes', String(r.recorrentes), '3 meses seguidos ou mais', r.recorrentes ? 'ruim' : 'bom'],
          ['Acima do alerta', String(r.colaboradores.filter((x) => x.acimaDoLimite).length), `média acima de ${fmt(p.alertaHorasExtras, 0)} h/mês`],
        ],
        avisos,
        tabelas: [{
          titulo: `Por ${rot.toLowerCase()}`,
          cab: [rot, { t: 'Colaboradores', c: 'num' }, { t: 'Horas extras', c: 'num' }, { t: 'Valor total', c: 'num' }, { t: 'Equivale a (colaboradores)', c: 'num' }],
          linhas: r.setores.map((s) => [s.setor, num(String(s.colaboradores)), num(horas(s.horas)), num(fmt(s.valor)), num(fmt(s.equivalente, 2))]),
        }, {
          titulo: 'Por colaborador',
          cab: ['Colaborador', { t: 'HE 50%', c: 'num' }, { t: 'HE 100%', c: 'num' }, { t: 'Média h/mês', c: 'num' }, { t: 'Meses com HE', c: 'num' },
            { t: 'Valor HE', c: 'num' }, { t: 'Noturno', c: 'num' }, { t: 'DSR', c: 'num' }, { t: 'Outros adic.', c: 'num' }, { t: 'Total', c: 'num' }, { t: '% do salário', c: 'num' }, 'Alerta'],
          linhas: r.colaboradores.map((x) => [colabCel(x.colab, x.setor), num(horas(x.he50)), num(horas(x.he100)), num(fmt(x.media, 1)), num(String(x.meses)),
            num(fmt(x.valorHE)), num(fmt(x.valorNoturno)), num(fmt(x.dsr)), num(fmt(x.adicionais)), num(fmt(x.valor)), num(pct(x.pctSalario)),
            x.recorrente || x.acimaDoLimite ? chip([x.recorrente ? 'Recorrente' : '', x.acimaDoLimite ? 'Acima do alerta' : ''].filter(Boolean).join(' · '), 'ruim') : '']),
        }],
        notas: ['Equivalência: horas extras médias por mês ÷ horas mensais da jornada dos colaboradores do setor. DSR: reflexo das horas extras e do adicional noturno nos domingos e feriados (Súmula 172 do TST).'],
      };
    },

    provisoes(d, de, ate, setor) {
      const r = CU.provisoes(d, ate, setor);
      const avisos = [];
      if (r.semAdmissao.length) avisos.push(`${r.semAdmissao.length} colaborador(es) sem data de admissão ficaram fora do cálculo: ${esc(r.semAdmissao.map((c) => c.nome).join(', '))}.`);
      const dobro = r.colaboradores.filter((x) => x.vencidas >= 2);
      if (dobro.length) avisos.push(`<b>Férias em dobro:</b> ${esc(dobro.map((x) => x.colab.nome).join(', '))} têm dois ou mais períodos vencidos (CLT art. 137).`);
      return {
        tiles: [
          ['13º salário acumulado', moeda(r.total13), `posição em ${CU.rotuloComp(ate)}`],
          ['Férias + 1/3 acumuladas', moeda(r.totalFerias), 'vencidas e proporcionais'],
          ['Encargos sobre provisões', moeda(r.totalEncargos), 'INSS, RAT, terceiros e FGTS'],
          ['Passivo total', moeda(r.total), `${r.colaboradores.length} colaborador(es)`],
        ],
        avisos,
        tabelas: [{
          titulo: `Passivo por colaborador em ${CU.rotuloComp(ate)}`,
          cab: ['Colaborador', { t: 'Base mensal', c: 'num' }, { t: 'Avos 13º', c: 'num' }, { t: '13º', c: 'num' }, { t: 'Avos férias', c: 'num' },
            { t: 'Vencidas', c: 'num' }, { t: 'Férias + 1/3', c: 'num' }, { t: 'Encargos', c: 'num' }, { t: 'Total', c: 'num' }, 'Alertas'],
          linhas: r.colaboradores.map((x) => [colabCel(x.colab, x.setor), num(fmt(x.salario + x.mediaVariaveis)), num(`${x.avos13}/12`), num(fmt(x.valor13)),
            num(`${x.avosFerias}/12`), num(String(x.vencidas)), num(fmt(x.valorFerias)), num(fmt(x.encargos)), num(fmt(x.total)),
            x.alertas.length ? { t: x.alertas.join(' '), h: `<small class="ruim">${esc(x.alertas.join(' '))}</small>` } : '']),
          rodape: ['Total', '', '', num(fmt(r.total13)), '', '', num(fmt(r.totalFerias)), num(fmt(r.totalEncargos)), num(fmt(r.total)), ''],
        }, {
          titulo: `Provisão lançada mês a mês em ${ate.slice(0, 4)}`,
          cab: ['Mês', { t: 'Férias + 1/3', c: 'num' }, { t: '13º', c: 'num' }, { t: 'Encargos', c: 'num' }, { t: 'Total', c: 'num' }],
          linhas: r.meses.filter((m) => m.lancamentos).map((m) => [CU.rotuloComp(m.competencia), num(fmt(m.ferias)), num(fmt(m.decimo)), num(fmt(m.encargos)), num(fmt(m.ferias + m.decimo + m.encargos))]),
        }],
        notas: ['Base mensal: último salário lançado + média das verbas variáveis dos últimos 12 meses (Súmulas 45 e 347 do TST). ' +
          'O passivo não desconta parcelas já pagas (1ª parcela do 13º até 30/11; 2ª até 20/12) nem férias gozadas que não foram atualizadas no cadastro.'],
      };
    },

    custo(d, de, ate, setor) {
      const r = CU.custoColaborador(d, de, ate, setor);
      const t = r.total;
      const mesesColab = r.colaboradores.reduce((s, x) => s + x.meses, 0);
      return {
        tiles: [
          ['Custo total', moeda(t.custoTotal), `${CU.rotuloComp(de)} a ${CU.rotuloComp(ate)}`],
          ['Custo médio por colaborador', moeda(mesesColab ? t.custoTotal / mesesColab : 0), 'por mês'],
          ['Custo ÷ salário', `${fmt(t.multiplicador)}×`, 'quanto cada R$ 1 de salário custa'],
          ['Encargos sobre a remuneração', pct(r.encargos.total), CU.REGIMES[CU.parametros(d.parametros).regime]],
        ],
        tabelas: [{
          titulo: 'Por colaborador',
          cab: ['Colaborador', { t: 'Meses', c: 'num' }, { t: 'Salário', c: 'num' }, { t: 'Variáveis', c: 'num' }, { t: 'Descontos', c: 'num' },
            { t: 'Encargos', c: 'num' }, { t: 'Provisões', c: 'num' }, { t: 'Benefícios', c: 'num' }, { t: 'Custo total', c: 'num' }, { t: 'Média mensal', c: 'num' }, { t: 'Custo ÷ salário', c: 'num' }],
          linhas: r.colaboradores.map((x) => [colabCel(x.colab, x.setor), num(String(x.meses)), num(fmt(x.salario)), num(fmt(x.variaveis)), num(fmt(x.descontos)),
            num(fmt(x.encargos)), num(fmt(x.provisoes)), num(fmt(x.beneficios)), num(fmt(x.custoTotal)), num(fmt(x.mediaMensal)), num(`${fmt(x.multiplicador)}×`)]),
          rodape: ['Total', '', num(fmt(t.salario)), num(fmt(t.variaveis)), num(fmt(t.descontos)), num(fmt(t.encargos)), num(fmt(t.provisoes)),
            num(fmt(t.beneficios)), num(fmt(t.custoTotal)), '', num(`${fmt(t.multiplicador)}×`)],
        }, {
          titulo: `Por ${rot.toLowerCase()}`,
          cab: [rot, { t: 'Colaboradores', c: 'num' }, { t: 'Remuneração', c: 'num' }, { t: 'Encargos', c: 'num' }, { t: 'Provisões', c: 'num' },
            { t: 'Benefícios', c: 'num' }, { t: 'Custo total', c: 'num' }, { t: '% do custo', c: 'num' }],
          linhas: r.setores.map((s) => [s.setor, num(String(s.colaboradores)), num(fmt(s.remuneracao)), num(fmt(s.encargos)), num(fmt(s.provisoes)),
            num(fmt(s.beneficios)), barra(s.custoTotal, t.custoTotal, fmt(s.custoTotal)), num(pct(t.custoTotal ? s.custoTotal / t.custoTotal * 100 : 0))]),
        }],
        notas: ['Custo total = remuneração + encargos (INSS patronal, RAT × FAP, terceiros, FGTS) + provisões de férias e 13º com encargos + benefícios pagos pela empresa.'],
      };
    },

    sinistralidade(d, de, ate) {
      const r = CU.sinistralidade(d, de, ate);
      const situacoes = { saudavel: ['Saudável', 'bom'], atencao: ['Atenção', 'breve'], critica: ['Crítica', 'ruim'], 'sem-dados': ['Sem dados', ''] };
      const [nomeSit, classeSit] = situacoes[r.situacao];
      const avisos = [];
      if (r.situacao === 'critica') avisos.push(`A sinistralidade acumulada está acima de ${fmt(r.limite, 0)}%: a operadora tende a aplicar reajuste elevado na renovação. Negocie com antecedência e avalie programas de saúde preventiva.`);
      else if (r.situacao === 'atencao') avisos.push(`A sinistralidade acumulada passou de ${fmt(r.alerta, 0)}%: acompanhe de perto antes da renovação do contrato.`);
      if (!r.meses.some((m) => m.sinistros != null)) avisos.push('Informe os sinistros de cada mês em Lançamentos (campo "Sinistros do mês") para calcular o índice.');
      const cor = (v) => (v == null ? '' : v >= r.limite ? 'ruim' : v >= r.alerta ? 'atencao' : 'bom');
      return {
        tiles: [
          ['Prêmio pago', moeda(r.premio), 'meses com sinistros informados'],
          ['Sinistros', moeda(r.sinistros), 'utilização do plano'],
          ['Sinistralidade do período', pct(r.indice), 'sinistros ÷ prêmio'],
          ['Acumulado 12 meses', pct(r.acumulado12), nomeSit, classeSit],
        ],
        avisos,
        tabelas: [{
          titulo: 'Mês a mês',
          cab: ['Mês', { t: 'Prêmio', c: 'num' }, { t: 'Sinistros', c: 'num' }, { t: 'Sinistralidade', c: 'num' }, { t: 'Acumulado 12 meses', c: 'num' }],
          linhas: r.meses.map((m) => [CU.rotuloComp(m.competencia), num(fmt(m.premio)), num(m.sinistros == null ? '—' : fmt(m.sinistros)),
            m.indice == null ? num('—') : barra(m.indice, 120, pct(m.indice), cor(m.indice)), num(pct(m.acumulado12))]),
        }],
        notas: [`Faixas: até ${fmt(r.alerta, 0)}% saudável; de ${fmt(r.alerta, 0)}% a ${fmt(r.limite, 0)}% atenção; acima de ${fmt(r.limite, 0)}% crítica (ajuste em Encargos e alertas). Sem a fatura informada, o prêmio é a soma do plano de saúde nos lançamentos.`],
      };
    },

    beneficios(d, de, ate, setor) {
      const r = CU.beneficiosPerCapita(d, de, ate, setor);
      return {
        tiles: [
          ['Custo com benefícios', moeda(r.total), `${r.meses} mês(es)`],
          ['Per capita mensal', moeda(r.perCapita), 'por vida ativa'],
          ['Peso na remuneração', pct(r.pctRemuneracao), 'benefícios ÷ remuneração'],
          ['Vidas ativas', fmt(r.vidasMedia, 1), 'média mensal'],
        ],
        tabelas: [{
          titulo: 'Por benefício',
          cab: ['Benefício', { t: 'Custo no período', c: 'num' }, { t: 'Beneficiários (vidas-mês)', c: 'num' }, { t: 'Per capita/mês', c: 'num' },
            { t: 'Por beneficiário/mês', c: 'num' }, { t: '% da remuneração', c: 'num' }],
          linhas: r.linhas.map((l) => [l.nome, barra(l.total, r.total, fmt(l.total)), num(String(l.beneficiarios)), num(fmt(l.perCapita)), num(fmt(l.porBeneficiario)), num(pct(l.pctRemuneracao))]),
          rodape: ['Total', num(fmt(r.total)), '', num(fmt(r.perCapita)), '', num(pct(r.pctRemuneracao))],
        }],
        notas: ['Per capita: custo ÷ vidas ativas (colaboradores com vínculo no fim de cada mês). Por beneficiário: custo ÷ lançamentos com o benefício.'],
      };
    },

    'absenteismo-medico'(d, de, ate, setor) {
      const r = CU.absenteismoMedico(d, de, ate, setor);
      const avisos = [];
      const top = r.motivos[0];
      if (top && ['mental', 'osteomuscular'].includes(top.id)) {
        avisos.push(`<b>${esc(top.nome)}</b> é o principal motivo de afastamento (${pct(top.pct)} dos dias): considere ações de ${top.id === 'mental' ? 'saúde mental e gestão do estresse' : 'ergonomia e ginástica laboral (NR-17)'}.`);
      }
      if (r.afastamentos.length) avisos.push(`${r.afastamentos.length} atestado(s) com mais de 15 dias no mês: a partir do 16º dia o afastamento é pago pelo INSS (Lei 8.213/1991, art. 60). Encaminhe à perícia.`);
      return {
        tiles: [
          ['Dias de atestado', String(r.totalDias), `${r.atestados} atestado(s)`],
          ['Colaboradores afastados', String(r.colaboradores), 'ao menos um atestado'],
          ['Principal motivo', top ? top.nome : '—', top ? pct(top.pct) + ' dos dias' : ''],
          ['Afastamentos acima de 15 dias', String(r.afastamentos.length), 'encaminhar ao INSS', r.afastamentos.length ? 'ruim' : 'bom'],
        ],
        avisos,
        tabelas: [{
          titulo: 'Por motivo',
          cab: ['Motivo', { t: 'Dias', c: 'num' }, { t: 'Atestados', c: 'num' }, { t: 'Colaboradores', c: 'num' }, { t: '% dos dias', c: 'num' }],
          linhas: r.motivos.map((m) => [m.nome, num(String(m.dias)), num(String(m.atestados)), num(String(m.colaboradores)), barra(m.pct, 100, pct(m.pct))]),
        }, {
          titulo: `Por ${rot.toLowerCase()}`,
          cab: [rot, { t: 'Dias', c: 'num' }, { t: 'Atestados', c: 'num' }],
          linhas: r.setores.map((s) => [s.setor, num(String(s.dias)), num(String(s.atestados))]),
        }, ...(r.afastamentos.length ? [{
          titulo: 'Afastamentos acima de 15 dias',
          cab: ['Colaborador', 'Mês', { t: 'Dias', c: 'num' }, 'Motivo'],
          linhas: r.afastamentos.map((a) => [colabCel(a.colab), CU.rotuloComp(a.competencia), num(String(a.dias)), a.motivo]),
        }] : [])],
        notas: ['Os motivos são registrados por grupo, sem o CID, para preservar o sigilo médico (Resolução CFM 1.658/2002).'],
      };
    },

    turnover(d, de, ate, setor) {
      const r = CU.turnover(d, de, ate, setor);
      const n = r.meses.length || 1;
      return {
        tiles: [
          ['Turnover do período', pct(r.taxa), `${fmt(r.taxa / n, 1)}% ao mês em média`],
          ['Admissões', String(r.admissoes), `${CU.rotuloComp(de)} a ${CU.rotuloComp(ate)}`],
          ['Desligamentos', String(r.desligamentos), `${r.saidasPrecoces} antes de 90 dias de casa`],
          ['Headcount médio', fmt(r.hcMedio, 1), 'colaboradores'],
        ],
        avisos: r.saidasPrecoces ? [`${r.saidasPrecoces} desligamento(s) nos primeiros 90 dias: revise o recrutamento e a integração de novos colaboradores.`] : [],
        tabelas: [{
          titulo: 'Mês a mês',
          cab: ['Mês', { t: 'HC início', c: 'num' }, { t: 'HC fim', c: 'num' }, { t: 'Admissões', c: 'num' }, { t: 'Desligamentos', c: 'num' }, { t: 'Turnover', c: 'num' }],
          linhas: r.meses.map((m) => [CU.rotuloComp(m.competencia), num(String(m.hcInicio)), num(String(m.hcFim)), num(String(m.admissoes)),
            num(String(m.desligamentos)), barra(m.taxa, 20, pct(m.taxa))]),
          rodape: ['Período', '', '', num(String(r.admissoes)), num(String(r.desligamentos)), num(pct(r.taxa))],
        }],
        notas: ['Turnover = ((admissões + desligamentos) ÷ 2) ÷ headcount médio × 100. Headcount médio do mês = (início + fim) ÷ 2.'],
      };
    },

    'turnover-tipo'(d, de, ate, setor) {
      const r = CU.turnover(d, de, ate, setor);
      const avisos = [];
      if (r.voluntario > r.involuntario) avisos.push('Os pedidos de demissão superam as dispensas: investigue liderança, clima e salários em Motivos de desligamento.');
      return {
        tiles: [
          ['Turnover voluntário', pct(r.taxaVoluntaria), `${r.voluntario} pedido(s) de demissão`, r.voluntario > r.involuntario ? 'ruim' : ''],
          ['Turnover involuntário', pct(r.taxaInvoluntaria), `${r.involuntario} dispensa(s) ou término(s)`],
          ['Acordos (art. 484-A)', String(r.acordo), r.outros ? `${r.outros} outro(s)` : ''],
          ['Tempo médio de casa', r.tempoMedioMeses == null ? '—' : `${fmt(r.tempoMedioMeses, 1)} meses`, 'dos desligados no período'],
        ],
        avisos,
        tabelas: [{
          titulo: 'Mês a mês',
          cab: ['Mês', { t: 'HC médio', c: 'num' }, { t: 'Voluntários', c: 'num' }, { t: 'Involuntários', c: 'num' }, { t: 'Acordos', c: 'num' }, { t: 'Outros', c: 'num' }, { t: 'Taxa de saída', c: 'num' }],
          linhas: r.meses.map((m) => [CU.rotuloComp(m.competencia), num(fmt(m.hcMedio, 1)), num(String(m.voluntario)), num(String(m.involuntario)),
            num(String(m.acordo)), num(String(m.outros)), num(pct(m.taxaSaida))]),
        }, {
          titulo: 'Desligados no período',
          cab: ['Colaborador', 'Data', 'Tipo', 'Classificação', { t: 'Tempo de casa', c: 'num' }],
          linhas: r.desligados.map((x) => [colabCel(x.colab, x.setor), dataBR(x.colab.desligamento), x.tipo, x.grupo,
            num(x.mesesDeCasa == null ? '—' : `${x.mesesDeCasa} meses`)]),
        }],
        notas: ['Voluntário: pedido de demissão. Involuntário: dispensa com ou sem justa causa e término de contrato. Taxa = desligamentos do tipo ÷ headcount médio do período.'],
      };
    },

    motivos(d, de, ate, setor) {
      const r = CU.turnover(d, de, ate, setor);
      const vol = r.motivos.filter((m) => m.voluntario).sort((a, b) => b.voluntario - a.voluntario)[0];
      return {
        tiles: [
          ['Desligamentos', String(r.desligamentos), `${CU.rotuloComp(de)} a ${CU.rotuloComp(ate)}`],
          ['Principal motivo', r.motivos[0] ? r.motivos[0].nome : '—', r.motivos[0] ? `${r.motivos[0].total} caso(s)` : ''],
          ['Principal motivo voluntário', vol ? vol.nome : '—', vol ? `${vol.voluntario} pedido(s)` : ''],
          ['Sem motivo registrado', String((r.motivos.find((m) => m.id === 'nao_informado') || { total: 0 }).total), 'complete a entrevista de desligamento'],
        ],
        tabelas: [{
          titulo: 'Motivos',
          cab: ['Motivo', { t: 'Total', c: 'num' }, { t: 'Voluntários', c: 'num' }, { t: 'Involuntários', c: 'num' }, { t: 'Acordos', c: 'num' }, { t: '% dos desligamentos', c: 'num' }],
          linhas: r.motivos.map((m) => [m.nome, num(String(m.total)), num(String(m.voluntario)), num(String(m.involuntario)), num(String(m.acordo)),
            barra(m.total, r.desligamentos, pct(r.desligamentos ? m.total / r.desligamentos * 100 : 0))]),
        }, {
          titulo: 'Entrevistas de desligamento',
          cab: ['Colaborador', 'Data', 'Classificação', 'Motivo', 'Observação'],
          linhas: r.desligados.map((x) => [colabCel(x.colab, x.setor), dataBR(x.colab.desligamento), x.grupo, x.motivo, x.colab.obsDesligamento || '']),
        }],
        notas: ['Registre o motivo e a observação no cadastro do colaborador, em Desligamento.'],
      };
    },

    absenteismo(d, de, ate, setor) {
      const r = CU.absenteismoGeral(d, de, ate, setor);
      const t = r.total;
      const linha = (x, primeira) => [primeira, num(fmt(x.previstas, 0)), num(fmt(x.faltas, 1)), num(fmt(x.atrasos, 1)), num(fmt(x.atestados, 1)),
        num(fmt(x.perdidas, 1)), barra(x.taxa, 10, pct(x.taxa), x.taxa > 5 ? 'ruim' : x.taxa > 3 ? 'atencao' : 'bom')];
      const cab = (primeira) => [primeira, { t: 'Horas previstas', c: 'num' }, { t: 'Faltas', c: 'num' }, { t: 'Atrasos e saídas', c: 'num' },
        { t: 'Atestados', c: 'num' }, { t: 'Horas perdidas', c: 'num' }, { t: 'Absenteísmo', c: 'num' }];
      return {
        tiles: [
          ['Absenteísmo geral', pct(t.taxa), 'horas perdidas ÷ previstas', t.taxa > 5 ? 'ruim' : t.taxa > 3 ? '' : 'bom'],
          ['Sem atestados', pct(t.taxaSemAtestado), 'faltas, atrasos e saídas antecipadas'],
          ['Horas perdidas', horas(t.perdidas), `de ${fmt(t.previstas, 0)} h previstas`],
          ['Faltas injustificadas', horas(t.faltas), `atrasos e saídas: ${horas(t.atrasos)}`],
        ],
        tabelas: [
          { titulo: `Por ${rot.toLowerCase()}`, cab: cab(rot), linhas: r.setores.map((x) => linha(x, x.setor)) },
          { titulo: 'Mês a mês', cab: cab('Mês'), linhas: r.meses.map((x) => linha(x, CU.rotuloComp(x.competencia))) },
          { titulo: 'Colaboradores com mais horas perdidas', cab: cab('Colaborador'), linhas: r.colaboradores.slice(0, 15).map((x) => linha(x, colabCel(x.colab, x.setor))) },
        ],
        notas: ['Horas previstas: horas semanais da jornada × dias do mês ÷ 7. Atestados: dias × horas diárias da jornada. Referência usual de mercado: até 3% é considerado adequado.'],
      };
    },

    'banco-horas'(d, de, ate, setor) {
      const r = CU.bancoHoras(d, ate, setor);
      const desligadosComSaldo = r.colaboradores.filter((x) => x.desligado && x.saldo > 0);
      const avisos = [];
      if (r.acimaDoLimite) avisos.push(`${r.acimaDoLimite} colaborador(es) com saldo acima de ${fmt(r.limite, 0)} h: programe folgas compensatórias. Saldo não compensado no prazo do acordo é pago como hora extra (CLT art. 59, §§ 2º, 3º e 5º).`);
      if (desligadosComSaldo.length) avisos.push(`${desligadosComSaldo.length} desligado(s) com saldo positivo: o saldo deve ser pago na rescisão.`);
      return {
        tiles: [
          ['Saldo a compensar', horas(r.saldoPositivo), `posição em ${CU.rotuloComp(ate)}`],
          ['Passivo estimado', moeda(r.passivo), 'se pago como hora extra (50%)'],
          ['Acima do alerta', String(r.acimaDoLimite), `saldo maior que ${fmt(r.limite, 0)} h`, r.acimaDoLimite ? 'ruim' : 'bom'],
          ['Saldos negativos', horas(Math.abs(r.saldoNegativo)), 'horas devidas pelos colaboradores'],
        ],
        avisos,
        tabelas: [{
          titulo: 'Saldos por colaborador',
          cab: ['Colaborador', { t: 'Créditos', c: 'num' }, { t: 'Compensadas', c: 'num' }, { t: 'Saldo', c: 'num' }, { t: 'Valor-hora', c: 'num' }, { t: 'Passivo (HE 50%)', c: 'num' }, 'Alerta'],
          linhas: r.colaboradores.map((x) => [colabCel(x.colab, x.setor), num(horas(x.credito)), num(horas(x.debito)), num(horas(x.saldo)),
            num(fmt(x.valorHora)), num(fmt(x.passivo)),
            x.alto ? chip('Saldo alto', 'ruim') : x.negativo ? chip('Saldo negativo', 'breve') : x.desligado && x.saldo > 0 ? chip('Pagar na rescisão', 'ruim') : '']),
        }],
        notas: ['Saldo acumulado com todos os lançamentos até o mês de referência (o campo "De" não se aplica).'],
      };
    },
  };

  let ultimoRelatorio = null;

  function montarHTML(rel) {
    const tile = ([rotulo, valor, detalhe, classe]) => `<div class="tile"><span class="tile-rotulo">${esc(rotulo)}</span>
      <span class="tile-valor">${esc(valor)}</span><span class="tile-detalhe ${classe || ''}">${esc(detalhe || '')}</span></div>`;
    const cel = (x, tag = 'td') => {
      const c = celula(x);
      return `<${tag} class="${c.c || ''}">${c.h != null ? c.h : esc(c.t)}</${tag}>`;
    };
    const tabela = (t) => `<div class="cartao"><h3>${esc(t.titulo)}</h3><div class="rl-rolagem"><table class="tabela rl-tabela">
      <thead><tr>${t.cab.map((x) => cel(x, 'th')).join('')}</tr></thead>
      <tbody>${t.linhas.map((l) => `<tr>${l.map((x) => cel(x)).join('')}</tr>`).join('') ||
        `<tr><td colspan="${t.cab.length}" class="vazio">Sem dados no período.</td></tr>`}</tbody>
      ${t.rodape && t.linhas.length ? `<tfoot><tr>${t.rodape.map((x) => cel(x, 'th')).join('')}</tr></tfoot>` : ''}
    </table></div></div>`;
    return `<div class="resumo">${rel.tiles.map(tile).join('')}</div>
      ${(rel.avisos || []).map((a) => `<p class="aviso rl-aviso">${a}</p>`).join('')}
      ${rel.tabelas.map(tabela).join('')}
      ${(rel.notas || []).map((n) => `<p class="dica">${esc(n)}</p>`).join('')}`;
  }

  function renderRelatorio() {
    if (!podeVer()) return;
    const tipo = $('#rl-tipo').value;
    let de = $('#rl-de').value;
    let ate = $('#rl-ate').value;
    const saida = $('#rl-saida');
    if (!CU.competenciaValida(de) || !CU.competenciaValida(ate)) {
      saida.innerHTML = '<div class="cartao vazio">Escolha o período.</div>';
      return;
    }
    if (de > ate) [de, ate] = [ate, de];
    if (!dados.lancamentos.length && !['turnover', 'turnover-tipo', 'motivos', 'quadro'].includes(tipo)) {
      saida.innerHTML = `<div class="cartao vazio">Ainda não há lançamentos de folha. Abra uma competência em <b>Lançamentos</b>${
        App.podeEditar() ? ' ou use <b>Carregar exemplo</b> para conhecer os relatórios' : ''}.</div>`;
      ultimoRelatorio = null;
      return;
    }
    const setor = $('#rl-setor').value;
    const rel = GERADORES[tipo](baseRelatorios(), de, ate, setor);
    ultimoRelatorio = { tipo, de, ate, setor, rel };
    saida.innerHTML = montarHTML(rel);
    larguras(saida);
  }

  // a política de segurança (CSP) não aceita style="" no HTML: a largura das barras vai pelo DOM
  function larguras(el) {
    el.querySelectorAll('[data-largura]').forEach((b) => { b.style.width = `${b.dataset.largura}%`; });
  }

  function descricaoFiltro() {
    const r = ultimoRelatorio;
    const periodo = ['provisoes', 'banco-horas', 'quadro'].includes(r.tipo) ? `posição em ${CU.rotuloComp(r.ate)}` : `${CU.rotuloComp(r.de)} a ${CU.rotuloComp(r.ate)}`;
    const dim = $('#rl-dimensao').value;
    const grupo = r.setor && agrupar(dim).grupos.find((g) => g.id === r.setor);
    return `${periodo} · ${grupo ? `${DIMENSOES[dim][0]}: ${grupo.nome}` : DIMENSOES[dim][1]}`;
  }

  $('#rl-csv').addEventListener('click', () => {
    if (!ultimoRelatorio) return App.avisar('Não há relatório para exportar.');
    const q = (v) => (/[;"\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : String(v));
    const linhas = [[NOMES_RELATORIO[ultimoRelatorio.tipo]], [descricaoFiltro()], []];
    const rel = ultimoRelatorio.rel;
    linhas.push(...rel.tiles.map(([r, v, d]) => [r, v, d || '']), []);
    for (const t of rel.tabelas) {
      linhas.push([t.titulo], t.cab.map((x) => celula(x).t), ...t.linhas.map((l) => l.map((x) => celula(x).t)));
      if (t.rodape) linhas.push(t.rodape.map((x) => celula(x).t));
      linhas.push([]);
    }
    App.baixar(`${ultimoRelatorio.tipo}_${ultimoRelatorio.de}_${ultimoRelatorio.ate}.csv`,
      '﻿' + linhas.map((l) => l.map(q).join(';')).join('\r\n'), 'text/csv;charset=utf-8');
  });

  $('#rl-imprimir').addEventListener('click', () => {
    if (!ultimoRelatorio) return App.avisar('Não há relatório para imprimir.');
    const area = $('#impressao');
    const agora = new Date().toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' });
    area.innerHTML = `<div class="rl-impressao"><header class="rl-cab">
        <img src="img/logo-moinho-santa-maria.png" alt="" width="60" height="70">
        <div><h1>${esc(NOMES_RELATORIO[ultimoRelatorio.tipo])}</h1>
        <p>${esc(descricaoFiltro())} · emitido em ${esc(agora)} por ${esc(usuario.nome)}</p></div></header>
        ${montarHTML(ultimoRelatorio.rel)}</div>`;
    larguras(area);
    const titulo = document.title;
    document.title = `${NOMES_RELATORIO[ultimoRelatorio.tipo]} ${ultimoRelatorio.de} a ${ultimoRelatorio.ate}`;
    document.body.classList.add('imprimindo', 'imprimindo-relatorio');
    const terminar = () => {
      document.body.classList.remove('imprimindo', 'imprimindo-relatorio');
      area.innerHTML = '';
      document.title = titulo;
      window.removeEventListener('afterprint', terminar);
    };
    window.addEventListener('afterprint', terminar);
    window.print();
  });
})();
