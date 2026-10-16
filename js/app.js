/* Interface do gerador de escala. Dados ficam no localStorage do navegador. */
(function () {
  'use strict';

  const M = window.EscalaMotor;
  const CHAVE = 'gerador-escala-clt-v1';
  const $ = (sel) => document.querySelector(sel);
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (ch) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
  const novoId = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
  const dataBR = (s) => s.split('-').reverse().join('/');
  const horas = (min) => `${Math.floor(min / 60)}h${String(Math.round(min % 60)).padStart(2, '0')}`;
  const SEG_A_SAB = [false, true, true, true, true, true, true];

  let estado = carregar();

  function estadoVazio() {
    return {
      setores: [], colaboradores: [], feriadosExtras: [],
      regras: { domingoHomensSemanas: 3, domingoMulheresSemanas: 2 },
      incluirFacultativos: false, escala: null, periodo: null,
    };
  }

  function carregar() {
    try {
      const salvo = JSON.parse(localStorage.getItem(CHAVE));
      if (salvo && Array.isArray(salvo.setores)) return Object.assign(estadoVazio(), salvo);
    } catch (e) { /* armazenamento indisponível */ }
    return estadoVazio();
  }

  function salvar() {
    try { localStorage.setItem(CHAVE, JSON.stringify(estado)); } catch (e) { /* ignora */ }
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

  formSetor.addEventListener('submit', (ev) => {
    ev.preventDefault();
    const f = formSetor.elements;
    const dias = [0, 1, 2, 3, 4, 5, 6].map((i) => formSetor.querySelector(`input[name=dia][value="${i}"]`).checked);
    if (!dias.some(Boolean)) return alert('Selecione ao menos um dia de funcionamento.');
    const dados = {
      id: f.id.value || novoId(), nome: f.nome.value.trim(),
      minimoPorDia: Math.max(0, Number(f.minimoPorDia.value) || 0),
      diasFuncionamento: dias, funcionaFeriados: f.funcionaFeriados.checked,
    };
    const i = estado.setores.findIndex((s) => s.id === dados.id);
    if (i >= 0) estado.setores[i] = dados; else estado.setores.push(dados);
    formSetor.reset();
    salvarERender();
  });

  formSetor.addEventListener('reset', () => setTimeout(() => {
    formSetor.elements.id.value = '';
    $('#titulo-form-setor').textContent = 'Novo setor';
    formSetor.querySelectorAll('input[name=dia]').forEach((c) => { c.checked = SEG_A_SAB[c.value]; });
  }));

  $('#lista-setores').addEventListener('click', (ev) => {
    const b = ev.target.closest('button');
    if (!b) return;
    const s = estado.setores.find((x) => x.id === b.dataset.id);
    if (b.dataset.acao === 'editar') {
      const f = formSetor.elements;
      f.id.value = s.id; f.nome.value = s.nome; f.minimoPorDia.value = s.minimoPorDia;
      f.funcionaFeriados.checked = !!s.funcionaFeriados;
      formSetor.querySelectorAll('input[name=dia]').forEach((c) => { c.checked = !!s.diasFuncionamento[c.value]; });
      $('#titulo-form-setor').textContent = 'Editar setor';
      f.nome.focus();
    } else if (b.dataset.acao === 'excluir') {
      const qtd = estado.colaboradores.filter((c) => c.setorId === s.id).length;
      if (qtd) return alert(`O setor possui ${qtd} colaborador(es). Remova-os ou altere o setor antes.`);
      if (!confirm(`Excluir o setor "${s.nome}"?`)) return;
      estado.setores = estado.setores.filter((x) => x.id !== s.id);
      salvarERender();
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

  formColab.addEventListener('submit', (ev) => {
    ev.preventDefault();
    const f = formColab.elements;
    if (!estado.setores.length) return alert('Cadastre um setor primeiro.');
    const dados = {
      id: f.id.value || novoId(), nome: f.nome.value.trim(), matricula: f.matricula.value.trim(),
      sexo: f.sexo.value, setorId: f.setorId.value, jornada: f.jornada.value, entrada: f.entrada.value,
    };
    if (estado.colaboradores.some((c) => c.matricula === dados.matricula && c.id !== dados.id)) {
      return alert(`A matrícula ${dados.matricula} já está cadastrada.`);
    }
    const i = estado.colaboradores.findIndex((c) => c.id === dados.id);
    if (i >= 0) estado.colaboradores[i] = dados; else estado.colaboradores.push(dados);
    formColab.reset();
    salvarERender();
  });

  formColab.addEventListener('reset', () => setTimeout(() => {
    formColab.elements.id.value = '';
    $('#titulo-form-colab').textContent = 'Novo colaborador';
    atualizarDicaJornada();
  }));

  $('#lista-colabs').addEventListener('click', (ev) => {
    const b = ev.target.closest('button');
    if (!b) return;
    const c = estado.colaboradores.find((x) => x.id === b.dataset.id);
    if (b.dataset.acao === 'editar') {
      const f = formColab.elements;
      for (const k of ['id', 'nome', 'matricula', 'sexo', 'setorId', 'jornada', 'entrada']) f[k].value = c[k];
      $('#titulo-form-colab').textContent = 'Editar colaborador';
      atualizarDicaJornada();
      f.nome.focus();
    } else if (b.dataset.acao === 'excluir') {
      if (!confirm(`Excluir ${c.nome} (matrícula ${c.matricula})?`)) return;
      estado.colaboradores = estado.colaboradores.filter((x) => x.id !== c.id);
      salvarERender();
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
    const texto = (await arq.text()).replace(/^﻿/, '');
    const linhas = texto.split(/\r?\n/).filter((l) => l.trim());
    if (linhas.length < 2) return alert('Arquivo vazio.');
    const sep = linhas[0].includes(';') ? ';' : ',';
    const cab = linhas[0].split(sep).map((h) => h.trim().toLowerCase());
    const col = (nome) => cab.indexOf(nome);
    if (['nome', 'matricula', 'sexo', 'setor'].some((n) => col(n) < 0)) {
      return alert('Cabeçalho deve conter: nome;matricula;sexo;setor;jornada;entrada');
    }
    let ok = 0;
    const erros = [];
    linhas.slice(1).forEach((linha, n) => {
      const v = linha.split(sep).map((x) => x.trim());
      const pega = (nome) => (col(nome) >= 0 ? v[col(nome)] || '' : '');
      const sexo = pega('sexo').toUpperCase().charAt(0);
      const jornada = pega('jornada') || '6x1';
      const matricula = pega('matricula');
      if (!pega('nome') || !matricula || !['F', 'M'].includes(sexo) || !M.JORNADAS[jornada] || !pega('setor')) {
        return erros.push(`linha ${n + 2}`);
      }
      if (estado.colaboradores.some((c) => c.matricula === matricula)) return erros.push(`linha ${n + 2} (matrícula repetida)`);
      let setor = estado.setores.find((s) => s.nome.toLowerCase() === pega('setor').toLowerCase());
      if (!setor) {
        setor = { id: novoId(), nome: pega('setor'), minimoPorDia: 1, diasFuncionamento: SEG_A_SAB.slice(), funcionaFeriados: false };
        estado.setores.push(setor);
      }
      estado.colaboradores.push({
        id: novoId(), nome: pega('nome'), matricula, sexo, setorId: setor.id, jornada,
        entrada: /^\d{1,2}:\d{2}$/.test(pega('entrada')) ? pega('entrada').padStart(5, '0') : '08:00',
      });
      ok++;
    });
    salvarERender();
    alert(`${ok} colaborador(es) importado(s).` + (erros.length ? `\nIgnorados: ${erros.join(', ')}` : ''));
  });

  // ---------------------------------------------------------------- regras

  const formRegras = $('#form-regras');
  formRegras.addEventListener('change', () => {
    estado.regras.domingoHomensSemanas = Number(formRegras.elements.domingoHomensSemanas.value);
    estado.incluirFacultativos = formRegras.elements.incluirFacultativos.checked;
    salvarERender();
  });

  $('#form-feriado').addEventListener('submit', (ev) => {
    ev.preventDefault();
    const f = ev.target.elements;
    estado.feriadosExtras = estado.feriadosExtras.filter((x) => x.data !== f.data.value);
    estado.feriadosExtras.push({ data: f.data.value, nome: f.nome.value.trim() });
    estado.feriadosExtras.sort((a, b) => a.data.localeCompare(b.data));
    ev.target.reset();
    salvarERender();
  });

  $('#lista-feriados').addEventListener('click', (ev) => {
    const b = ev.target.closest('button[data-data]');
    if (!b) return;
    estado.feriadosExtras = estado.feriadosExtras.filter((x) => x.data !== b.dataset.data);
    salvarERender();
  });

  function renderRegras() {
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
  (function periodoPadrao() {
    const p = estado.periodo;
    if (p) { formGerar.elements.inicio.value = p.inicio; formGerar.elements.fim.value = p.fim; return; }
    const h = new Date();
    const ini = new Date(Date.UTC(h.getFullYear(), h.getMonth() + 1, 1));
    const fim = new Date(Date.UTC(h.getFullYear(), h.getMonth() + 2, 0));
    formGerar.elements.inicio.value = M.formatarData(ini);
    formGerar.elements.fim.value = M.formatarData(fim);
  })();

  formGerar.addEventListener('submit', (ev) => {
    ev.preventDefault();
    const inicio = formGerar.elements.inicio.value;
    const fim = formGerar.elements.fim.value;
    if (!inicio || !fim || inicio > fim) return alert('Período inválido.');
    if ((M.parseData(fim) - M.parseData(inicio)) / 86400000 > 92) return alert('Gere no máximo 3 meses por vez.');
    if (!estado.colaboradores.length) return alert('Cadastre colaboradores primeiro.');
    if (estado.escala && !confirm('Gerar uma nova escala substitui a atual (incluindo ajustes manuais). Continuar?')) return;
    const cfg = Object.assign(configMotor(), { inicio, fim });
    estado.escala = M.gerarEscala(cfg);
    estado.periodo = { inicio, fim };
    salvarERender();
  });

  $('#filtro-setor-escala').addEventListener('change', renderEscala);

  $('#area-escala').addEventListener('click', (ev) => {
    const td = ev.target.closest('td[data-c]');
    if (!td || !estado.escala) return;
    const colab = estado.colaboradores.find((c) => c.id === td.dataset.c);
    const i = Number(td.dataset.i);
    const cel = estado.escala.celulas[colab.id];
    cel[i] = cel[i].tipo === 'T'
      ? { tipo: estado.escala.dias[i].feriado ? 'FER' : 'F' }
      : M.turnoTrabalho(colab);
    salvarERender();
  });

  function renderEscala() {
    const area = $('#area-escala');
    const e = estado.escala;
    if (!e) {
      area.innerHTML = '<div class="cartao vazio">Defina o período e clique em <b>Gerar escala</b>.</div>';
      $('#area-validacao').hidden = true;
      return;
    }
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
    if (!e) return alert('Gere uma escala primeiro.');
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
    const url = URL.createObjectURL(new Blob([conteudo], { type: tipo }));
    const a = Object.assign(document.createElement('a'), { href: url, download: nome });
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  $('#btn-exportar-json').addEventListener('click', () =>
    baixar('escala-backup.json', JSON.stringify(estado, null, 2), 'application/json'));

  $('#arq-json').addEventListener('change', async (ev) => {
    const arq = ev.target.files[0];
    ev.target.value = '';
    if (!arq) return;
    try {
      const dados = JSON.parse(await arq.text());
      if (!Array.isArray(dados.setores) || !Array.isArray(dados.colaboradores)) throw new Error();
      estado = Object.assign(estadoVazio(), dados);
      salvarERender();
    } catch (e) {
      alert('Arquivo de backup inválido.');
    }
  });

  $('#btn-limpar').addEventListener('click', () => {
    if (!confirm('Apagar todos os setores, colaboradores e escalas?')) return;
    estado = estadoVazio();
    salvarERender();
  });

  $('#btn-exemplo').addEventListener('click', () => {
    if ((estado.setores.length || estado.colaboradores.length) && !confirm('Substituir os dados atuais pelo exemplo?')) return;
    const todos = [true, true, true, true, true, true, true];
    estado = estadoVazio();
    estado.setores = [
      { id: 'vendas', nome: 'Vendas', minimoPorDia: 4, diasFuncionamento: todos, funcionaFeriados: true },
      { id: 'adm', nome: 'Administrativo', minimoPorDia: 1, diasFuncionamento: [false, true, true, true, true, true, false], funcionaFeriados: false },
      { id: 'seg', nome: 'Segurança', minimoPorDia: 1, diasFuncionamento: todos, funcionaFeriados: true },
    ];
    const pessoas = [
      ['Ana Souza', 'F', 'vendas', '6x1', '08:00'], ['Bruno Lima', 'M', 'vendas', '6x1', '08:00'],
      ['Carla Mendes', 'F', 'vendas', '6x1', '10:00'], ['Diego Alves', 'M', 'vendas', '6x1', '10:00'],
      ['Eduarda Rocha', 'F', 'vendas', '6x1', '12:00'], ['Felipe Costa', 'M', 'vendas', '6x1', '12:00'],
      ['Gabriela Nunes', 'F', 'vendas', '6x1', '13:00'], ['Henrique Dias', 'M', 'vendas', '6x1', '13:00'],
      ['Isabela Martins', 'F', 'adm', '5x2', '08:00'], ['João Pereira', 'M', 'adm', '5x2-40', '09:00'],
      ['Karina Ferreira', 'F', 'seg', '12x36', '07:00'], ['Lucas Oliveira', 'M', 'seg', '12x36', '07:00'],
      ['Marcos Ribeiro', 'M', 'seg', '12x36', '19:00'], ['Natália Gomes', 'F', 'seg', '12x36', '19:00'],
    ];
    estado.colaboradores = pessoas.map(([nome, sexo, setorId, jornada, entrada], k) => ({
      id: 'ex' + k, nome, matricula: String(10001 + k), sexo, setorId, jornada, entrada,
    }));
    salvarERender();
  });

  // ------------------------------------------------------------- render

  function salvarERender() {
    salvar();
    renderSetores();
    renderColaboradores();
    renderRegras();
    renderEscala();
  }

  formSetor.dispatchEvent(new Event('reset'));
  atualizarDicaJornada();
  salvarERender();
})();
