/* Interface do gerador de escala. Os dados ficam no servidor (API em /api). */
(function () {
  'use strict';

  const M = window.EscalaMotor;
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
      setores: [], colaboradores: [], feriadosExtras: [],
      regras: { domingoHomensSemanas: 3, domingoMulheresSemanas: 2 },
      incluirFacultativos: false, escala: null, periodo: null,
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

  function configMotor() {
    return {
      setores: estado.setores, colaboradores: estado.colaboradores,
      feriadosExtras: estado.feriadosExtras, regras: estado.regras,
      incluirFacultativos: estado.incluirFacultativos,
      inicio: estado.escala && estado.escala.inicio, fim: estado.escala && estado.escala.fim,
    };
  }

  const nomeSetor = (id) => (estado.setores.find((s) => s.id === id) || {}).nome || '—';

  // ------------------------------------------------------------------ abas

  document.querySelectorAll('.aba').forEach((b) => b.addEventListener('click', () => mostrarAba(b.dataset.aba)));

  function mostrarAba(nome) {
    document.querySelectorAll('.aba').forEach((b) => b.classList.toggle('ativa', b.dataset.aba === nome));
    document.querySelectorAll('.painel').forEach((p) => p.classList.toggle('ativo', p.id === 'aba-' + nome));
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
    for (const sel of [$('#filtro-setor-colab'), $('#filtro-setor-escala')]) {
      const v = sel.value;
      sel.innerHTML = '<option value="">Todos os setores</option>' + opcoes;
      sel.value = estado.setores.some((s) => s.id === v) ? v : '';
    }
  }

  // ---------------------------------------------------------- colaboradores

  const formColab = $('#form-colab');
  $('#sel-jornada').innerHTML = Object.entries(M.JORNADAS)
    .map(([k, j]) => `<option value="${k}">${esc(j.nome)}</option>`).join('');

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
    };
    const id = f.id.value;
    const ok = await executar(() => (id ? api.put(`/api/colaboradores/${id}`, dados) : api.post('/api/colaboradores', dados)));
    if (ok) formColab.reset();
  });

  formColab.addEventListener('reset', () => setTimeout(() => {
    formColab.elements.id.value = '';
    $('#titulo-form-colab').textContent = 'Novo colaborador';
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
      $('#titulo-form-colab').textContent = 'Editar colaborador';
      atualizarDicaJornada();
      f.nome.focus();
    } else if (b.dataset.acao === 'excluir') {
      if (!(await confirmar(`Excluir ${c.nome} (matrícula ${c.matricula})?`))) return;
      await executar(() => api.del(`/api/colaboradores/${c.id}`));
    }
  });

  $('#filtro-setor-colab').addEventListener('change', renderColaboradores);

  function renderColaboradores() {
    const filtro = $('#filtro-setor-colab').value;
    const lista = estado.colaboradores
      .filter((c) => !filtro || c.setorId === filtro)
      .sort((a, b) => nomeSetor(a.setorId).localeCompare(nomeSetor(b.setorId)) || a.nome.localeCompare(b.nome));
    $('#lista-colabs').innerHTML = lista.map((c) => {
      const t = M.turnoTrabalho(c);
      return `<tr>
        <td>${esc(c.matricula)}</td><td>${esc(c.nome)}</td>
        <td>${c.sexo === 'F' ? 'Feminino' : 'Masculino'}</td>
        <td>${esc(nomeSetor(c.setorId))}</td><td>${esc(c.jornada)}</td>
        <td>${M.horaDeMinutos(t.inicio)}–${M.horaDeMinutos(t.fim)}</td>
        <td class="acoes">
          <button type="button" class="mini sec" data-acao="editar" data-id="${c.id}">Editar</button>
          <button type="button" class="mini perigo" data-acao="excluir" data-id="${c.id}">Excluir</button>
        </td></tr>`;
    }).join('') || '<tr><td colspan="7" class="vazio">Nenhum colaborador cadastrado.</td></tr>';
  }

  $('#arq-csv').addEventListener('change', async (ev) => {
    const arq = ev.target.files[0];
    ev.target.value = '';
    if (!arq) return;
    if (!exigirEdicao()) return;
    const texto = (await arq.text()).replace(/^﻿/, '');
    const linhas = texto.split(/\r?\n/).filter((l) => l.trim());
    if (linhas.length < 2) return avisar('Arquivo vazio.');
    const sep = linhas[0].includes(';') ? ';' : ',';
    const cab = linhas[0].split(sep).map((h) => h.trim().toLowerCase());
    const col = (nome) => cab.indexOf(nome);
    if (['nome', 'matricula', 'sexo', 'setor'].some((n) => col(n) < 0)) {
      return avisar('Cabeçalho deve conter: nome;matricula;sexo;setor;jornada;entrada');
    }
    const registros = linhas.slice(1).map((linha, n) => {
      const v = linha.split(sep).map((x) => x.trim());
      const pega = (nome) => (col(nome) >= 0 ? v[col(nome)] || '' : '');
      return {
        linha: n + 2, nome: pega('nome'), matricula: pega('matricula'), sexo: pega('sexo').toUpperCase(),
        setor: pega('setor'), jornada: pega('jornada'), entrada: pega('entrada'),
      };
    });
    let r = null;
    await executar(async () => { r = await api.post('/api/colaboradores/importar', { linhas: registros }); });
    if (r) {
      avisar(`${r.importados} colaborador(es) importado(s).` + (r.ignorados.length ? `\nIgnorados: ${r.ignorados.join('; ')}` : ''));
    }
  });

  // ---------------------------------------------------------------- regras

  const formRegras = $('#form-regras');
  formRegras.addEventListener('change', async () => {
    if (!exigirEdicao()) { renderRegras(); return; }
    await executar(() => api.put('/api/regras', {
      domingoHomensSemanas: Number(formRegras.elements.domingoHomensSemanas.value),
      incluirFacultativos: formRegras.elements.incluirFacultativos.checked,
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
    const p = estado.periodo;
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
    if (!estado.colaboradores.length) return avisar('Cadastre colaboradores primeiro.');
    if (estado.escala && !(await confirmar('Gerar uma nova escala substitui a atual (incluindo ajustes manuais). Continuar?'))) return;
    await executar(() => api.post('/api/escala/gerar', { inicio, fim }));
  });

  $('#filtro-setor-escala').addEventListener('change', renderEscala);

  $('#area-escala').addEventListener('click', async (ev) => {
    const td = ev.target.closest('td[data-c]');
    if (!td || !estado.escala) return;
    if (!exigirEdicao()) return;
    td.classList.add('salvando');
    await executar(() => api.post('/api/escala/celula', { colaboradorId: td.dataset.c, indice: Number(td.dataset.i) }));
  });

  function renderEscala() {
    const area = $('#area-escala');
    const e = estado.escala;
    if (!e) {
      area.innerHTML = '<div class="cartao vazio">Defina o período e clique em <b>Gerar escala</b>.</div>';
      $('#info-escala').textContent = '';
      $('#area-validacao').hidden = true;
      return;
    }
    const quando = (iso) => new Date(iso).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' });
    $('#info-escala').textContent = e.geradaEm
      ? `Escala gerada por ${e.geradaPor || '—'} em ${quando(e.geradaEm)}` +
        (e.atualizadaEm !== e.geradaEm ? `; último ajuste em ${quando(e.atualizadaEm)}.` : '.')
      : '';
    const cfg = configMotor();
    const ocorrencias = M.validarEscala(cfg, e);
    const filtro = $('#filtro-setor-escala').value;
    const setores = estado.setores.filter((s) => !filtro || s.id === filtro);
    const porCelula = {};
    for (const o of ocorrencias) {
      if (o.nivel === 'erro' && o.colaboradorId && o.data) porCelula[o.colaboradorId + '|' + o.data] = o;
    }

    const cabDias = e.dias.map((d) => `<th class="${d.dow === 0 ? 'dom' : ''} ${d.feriado ? 'fer' : ''}"
        title="${d.feriado ? esc(d.feriado.nome) : ''}">${d.data.slice(8)}<br><small>${M.NOMES_DIAS[d.dow].charAt(0)}</small></th>`).join('');

    let html = '';
    for (const s of setores) {
      const membros = estado.colaboradores.filter((c) => c.setorId === s.id && e.celulas[c.id])
        .sort((a, b) => a.nome.localeCompare(b.nome));
      const novos = estado.colaboradores.filter((c) => c.setorId === s.id && !e.celulas[c.id]).length;
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
        <h2>${esc(s.nome)} <small>mínimo ${s.minimoPorDia}/dia · ${dataBR(e.inicio)} a ${dataBR(e.fim)}</small></h2>
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
        ${alertas.length ? ` ${alertas.length} alerta(s) de cobertura.` : ''}</p>
      ${erros.length ? `<h3>Violações</h3><ul>${erros.map(item).join('')}</ul>` : ''}
      ${alertas.length ? `<h3>Alertas</h3><ul>${alertas.map(item).join('')}</ul>` : ''}
      ${infos.length ? `<details><summary>Observações (${infos.length})</summary><ul>${infos.map(item).join('')}</ul></details>` : ''}`;
    $('#area-validacao').hidden = false;
  }

  $('#btn-csv').addEventListener('click', () => {
    const e = estado.escala;
    if (!e) return avisar('Gere uma escala primeiro.');
    const filtro = $('#filtro-setor-escala').value;
    const q = (v) => `"${String(v).replace(/"/g, '""')}"`;
    const linhas = [['Setor', 'Matrícula', 'Nome', 'Sexo', 'Jornada', ...e.dias.map((d) => `${dataBR(d.data)} ${M.NOMES_DIAS[d.dow]}`),
      'Dias trabalhados', 'Folgas', 'Domingos de folga', 'Horas'].map(q).join(';')];
    for (const c of estado.colaboradores) {
      if (!e.celulas[c.id] || (filtro && c.setorId !== filtro)) continue;
      const r = M.resumirColaborador(e, c);
      linhas.push([nomeSetor(c.setorId), c.matricula, c.nome, c.sexo, c.jornada,
        ...e.celulas[c.id].map((t) => (t.tipo === 'T' ? `${M.horaDeMinutos(t.inicio)}-${M.horaDeMinutos(t.fim)}` : t.tipo === 'FER' ? 'FERIADO' : 'FOLGA')),
        r.dias, r.folgas, r.domingosFolga, horas(r.minutos)].map(q).join(';'));
    }
    baixar(`escala_${e.inicio}_${e.fim}.csv`, '﻿' + linhas.join('\r\n'), 'text/csv;charset=utf-8');
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
      baixar(`escala-backup-${b.exportadoEm.slice(0, 10)}.json`, JSON.stringify(b, null, 2), 'application/json');
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
    renderSetores();
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
      mostrarAba(estado.escala || !podeEditar() ? 'escala' : 'setores');
    },
    encerrar() {
      usuario = null;
      estado = estadoVazio();
      render();
      document.body.classList.remove('perfil-consulta', 'perfil-admin');
    },
    mostrarAba, avisar, confirmar, abrirDialogo, esc,
  };
})();
