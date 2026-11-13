/*
 * Custos de pessoal: custo mensal de cada colaborador (salário, adicionais,
 * encargos, provisões e benefícios) e os relatórios gerenciais da folha.
 *
 * Regras adotadas (Lucro Presumido/Real; no Simples Nacional, anexos I a III,
 * não há INSS patronal, RAT nem terceiros):
 *  - valor-hora = salário ÷ divisor (horas semanais × 5: 220 para 44h);
 *  - horas extras com 50% e 100% (CF art. 7º, XVI) e adicional noturno de 20%
 *    (CLT art. 73), com reflexo no DSR (Lei 605/1949; Súmula 172 do TST);
 *  - faltas e atrasos injustificados são descontados; atestados são pagos;
 *  - encargos sobre a remuneração: INSS patronal, RAT × FAP, terceiros e FGTS;
 *  - provisões mensais: férias (1/12 + 1/3) e 13º salário (1/12), com encargos.
 *
 * Funciona no navegador (window.EscalaCustos) e no Node.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.EscalaCustos = api;
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const centavos = (v) => Math.round((Number(v) || 0) * 100) / 100;
  const soma = (lista, f) => lista.reduce((t, x) => t + (Number(f(x)) || 0), 0);

  const PARAMETROS_PADRAO = {
    regime: 'lucro', inss: 20, rat: 2, fap: 1, terceiros: 5.8, fgts: 8,
    alertaSinistralidade: 70, limiteSinistralidade: 75, alertaHorasExtras: 20, alertaBancoHoras: 40,
  };

  const REGIMES = {
    lucro: 'Lucro Presumido ou Lucro Real',
    simples: 'Simples Nacional (anexos I a III, sem INSS patronal)',
  };

  /** Horas semanais e horas por dia de cada jornada do cadastro. */
  const JORNADA_HORAS = {
    '6x1': { semana: 44, dia: 440 / 60 },
    '5x2': { semana: 44, dia: 528 / 60 },
    '5x2-40': { semana: 40, dia: 8 },
    '6x1-6h': { semana: 36, dia: 6 },
    '12x36': { semana: 42, dia: 12 },
  };
  const horasDaJornada = (j) => JORNADA_HORAS[j] || JORNADA_HORAS['6x1'];
  const divisor = (j) => horasDaJornada(j).semana * 5;

  const BENEFICIOS = [
    { id: 'vt', nome: 'Vale-transporte' },
    { id: 'vr', nome: 'Vale-refeição' },
    { id: 'va', nome: 'Vale-alimentação' },
    { id: 'saude', nome: 'Plano de saúde' },
    { id: 'seguro', nome: 'Seguro de vida' },
    { id: 'outrosBeneficios', nome: 'Outros benefícios' },
  ];

  const TIPOS_DESLIGAMENTO = {
    pedido: { nome: 'Pedido de demissão', grupo: 'voluntario' },
    sem_justa: { nome: 'Dispensa sem justa causa', grupo: 'involuntario' },
    justa: { nome: 'Dispensa por justa causa', grupo: 'involuntario' },
    termino: { nome: 'Término de contrato (experiência ou prazo determinado)', grupo: 'involuntario' },
    acordo: { nome: 'Acordo entre as partes (art. 484-A)', grupo: 'acordo' },
    outros: { nome: 'Aposentadoria, falecimento ou outros', grupo: 'outros' },
  };
  /** Empregados sem controle de jornada (CLT art. 62): fora das regras de duração do trabalho e das escalas. */
  const SEM_CONTROLE_JORNADA = {
    gestao: 'Cargo de gestão (art. 62, II)',
    externo: 'Atividade externa incompatível com controle (art. 62, I)',
    teletrabalho: 'Teletrabalho por produção ou tarefa (art. 62, III)',
  };
  const GRUPOS_DESLIGAMENTO = { voluntario: 'Voluntário', involuntario: 'Involuntário', acordo: 'Acordo', outros: 'Outros' };

  /** Motivos apontados na entrevista de desligamento. */
  const MOTIVOS_DESLIGAMENTO = {
    salario: 'Remuneração abaixo do mercado',
    concorrencia: 'Proposta de outra empresa',
    lideranca: 'Relação com a liderança',
    clima: 'Clima organizacional',
    carreira: 'Falta de crescimento ou carreira',
    jornada: 'Jornada ou escala de trabalho',
    distancia: 'Distância ou mudança de cidade',
    pessoal: 'Motivos pessoais ou familiares',
    saude: 'Saúde',
    desempenho: 'Desempenho',
    disciplina: 'Comportamento ou disciplina',
    reestruturacao: 'Reestruturação ou redução de quadro',
    fim_contrato: 'Fim do contrato',
    outros: 'Outros',
  };

  /** Grupos de motivo dos atestados médicos (sem CID individual, por sigilo). */
  const MOTIVOS_ATESTADO = {
    mental: 'Saúde mental e estresse',
    osteomuscular: 'LER/DORT e dores osteomusculares',
    respiratorio: 'Doenças respiratórias e sazonais',
    acidente: 'Acidentes e lesões',
    gastro: 'Doenças gastrointestinais',
    odonto: 'Odontológico',
    exames: 'Consultas e exames',
    outros: 'Outros ou não informado',
  };

  /** Campos do lançamento mensal, na ordem da grade e do modelo de planilha. */
  const CAMPOS = [
    { id: 'salario', nome: 'Salário', tipo: 'moeda', grupo: 'Remuneração', apelidos: ['salario', 'salariobase', 'salariomensal'] },
    { id: 'he50', nome: 'HE 50% (h)', tipo: 'horas', grupo: 'Remuneração', apelidos: ['he50', 'horasextras50', 'extra50', 'he50h'] },
    { id: 'he100', nome: 'HE 100% (h)', tipo: 'horas', grupo: 'Remuneração', apelidos: ['he100', 'horasextras100', 'extra100', 'he100h'] },
    { id: 'noturno', nome: 'Noturno (h)', tipo: 'horas', grupo: 'Remuneração', apelidos: ['noturno', 'adicionalnoturno', 'horasnoturnas', 'noturnoh'] },
    { id: 'adicionais', nome: 'Outros adicionais', tipo: 'moeda', grupo: 'Remuneração', apelidos: ['adicionais', 'outrosadicionais', 'gratificacoes'] },
    { id: 'faltas', nome: 'Faltas (h)', tipo: 'horas', grupo: 'Ocorrências', apelidos: ['faltas', 'faltash', 'horasfalta', 'horasdefalta'] },
    { id: 'atrasos', nome: 'Atrasos e saídas (h)', tipo: 'horas', grupo: 'Ocorrências', apelidos: ['atrasos', 'atrasossaidas', 'atrasosesaidas', 'atrasosh'] },
    { id: 'atestadoDias', nome: 'Atestado (dias)', tipo: 'dias', grupo: 'Ocorrências', apelidos: ['atestado', 'atestados', 'atestadodias', 'diasatestado', 'diasdeatestado'] },
    { id: 'atestadoMotivo', nome: 'Motivo do atestado', tipo: 'motivo', grupo: 'Ocorrências', apelidos: ['motivo', 'motivoatestado', 'motivodoatestado'] },
    { id: 'bhCredito', nome: 'Banco: crédito (h)', tipo: 'horas', grupo: 'Banco de horas', apelidos: ['bhcredito', 'bancocredito', 'creditobh', 'bancodehorascredito'] },
    { id: 'bhDebito', nome: 'Banco: compensado (h)', tipo: 'horas', grupo: 'Banco de horas', apelidos: ['bhdebito', 'bancodebito', 'debitobh', 'bhcompensado', 'bancodehorascompensado'] },
    ...BENEFICIOS.map((b) => ({ id: b.id, nome: b.nome, tipo: 'moeda', grupo: 'Benefícios (custo da empresa)' })),
  ];
  CAMPOS.find((c) => c.id === 'vt').apelidos = ['vt', 'valetransporte'];
  CAMPOS.find((c) => c.id === 'vr').apelidos = ['vr', 'valerefeicao'];
  CAMPOS.find((c) => c.id === 'va').apelidos = ['va', 'valealimentacao'];
  CAMPOS.find((c) => c.id === 'saude').apelidos = ['saude', 'planodesaude', 'planosaude', 'convenio'];
  CAMPOS.find((c) => c.id === 'seguro').apelidos = ['seguro', 'segurodevida', 'segurovida'];
  CAMPOS.find((c) => c.id === 'outrosBeneficios').apelidos = ['outrosbeneficios', 'beneficios'];

  // ------------------------------------------------------------- leitura

  const semAcento = (s) => String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '');
  const chave = (s) => semAcento(s).toLowerCase().replace(/[^a-z0-9]/g, '');

  /** "1.234,56" / "1234,56" / "1234.56" / "10:30" (horas) -> número ; vazio -> null */
  function lerNumero(s) {
    if (s == null) return null;
    if (typeof s === 'number') return Number.isFinite(s) ? s : null;
    let t = String(s).trim().replace(/[R$\s%]/g, '');
    if (!t) return null;
    const hm = /^(-?)(\d+):([0-5]\d)$/.exec(t);
    if (hm) return (hm[1] ? -1 : 1) * (Number(hm[2]) + Number(hm[3]) / 60);
    if (/,\d+$/.test(t)) t = t.replace(/\./g, '').replace(',', '.');
    else if (/^-?\d{1,3}(\.\d{3})+\.\d{1,2}$/.test(t)) t = t.replace(/\.(?=.*\.)/g, ''); // 7.265.69 (digitado à mão)
    else if (/^-?\d{1,3}(\.\d{3})+$/.test(t)) t = t.replace(/\./g, '');
    else t = t.replace(/,/g, '');
    const n = Number(t);
    return Number.isFinite(n) ? n : null;
  }

  /** Converte o texto do motivo (nome ou código) para o código do grupo. */
  function lerMotivoAtestado(s) {
    const k = chave(s);
    if (!k) return '';
    if (MOTIVOS_ATESTADO[k]) return k;
    for (const [id, nome] of Object.entries(MOTIVOS_ATESTADO)) if (chave(nome).includes(k) || k.includes(id)) return id;
    if (/estresse|ansiedade|depress|burnout|mental|^f\d/.test(k)) return 'mental';
    if (/ler|dort|coluna|lombar|tendin|^m\d/.test(k)) return 'osteomuscular';
    if (/gripe|resfriado|covid|respirat|sinusite|^j\d/.test(k)) return 'respiratorio';
    return 'outros';
  }

  /** Separa um texto de planilha/CSV em linhas e colunas (aceita aspas). */
  function lerTabela(texto) {
    const linhas = String(texto || '').replace(/^﻿/, '').split(/\r?\n/).filter((l) => l.trim());
    if (!linhas.length) return [];
    const p = linhas[0];
    const sep = p.includes('\t') ? '\t' : p.includes(';') ? ';' : ',';
    return linhas.map((linha) => {
      const out = [];
      let atual = '';
      let aspas = false;
      for (let i = 0; i < linha.length; i++) {
        const ch = linha[i];
        if (aspas) {
          if (ch === '"' && linha[i + 1] === '"') { atual += '"'; i++; } else if (ch === '"') aspas = false; else atual += ch;
        } else if (ch === '"') aspas = true;
        else if (ch === sep) { out.push(atual.trim()); atual = ''; } else atual += ch;
      }
      out.push(atual.trim());
      return out;
    });
  }

  /**
   * Lê uma planilha de lançamentos (primeira linha = cabeçalho com a matrícula
   * e os campos). Devolve { linhas: [{ matricula, ...campos }], colunas, ignoradas }.
   */
  function lerPlanilhaLancamentos(texto) {
    const tabela = lerTabela(texto);
    if (tabela.length < 2) throw new Error('A planilha precisa de uma linha de cabeçalho e ao menos uma linha de dados.');
    const cab = tabela[0].map(chave);
    const iMatr = cab.findIndex((h) => ['matricula', 'matr', 'registro', 'chapa'].includes(h));
    if (iMatr < 0) throw new Error('O cabeçalho precisa ter a coluna "matricula".');
    const colunas = {};
    const ignoradas = [];
    cab.forEach((h, i) => {
      if (i === iMatr || !h) return;
      const c = CAMPOS.find((x) => x.apelidos.includes(h) || chave(x.nome) === h || chave(x.id) === h);
      if (c) colunas[c.id] = i;
      else if (!['nome', 'colaborador', 'setor', 'competencia', 'cargo'].includes(h)) ignoradas.push(tabela[0][i]);
    });
    if (!Object.keys(colunas).length) throw new Error('Nenhuma coluna reconhecida. Baixe o modelo para ver os nomes das colunas.');
    const linhas = tabela.slice(1).map((v, n) => {
      const l = { linha: n + 2, matricula: v[iMatr] || '' };
      for (const [id, i] of Object.entries(colunas)) {
        const bruto = v[i] == null ? '' : v[i];
        if (bruto === '') continue;
        l[id] = id === 'atestadoMotivo' ? lerMotivoAtestado(bruto) : bruto;
      }
      return l;
    }).filter((l) => l.matricula);
    return { linhas, colunas: Object.keys(colunas), ignoradas };
  }

  // -------------------------------------------------------------- datas

  const somarMes = (comp, n) => {
    const [a, m] = comp.split('-').map(Number);
    const t = a * 12 + (m - 1) + n;
    return `${Math.floor(t / 12)}-${String((t % 12) + 1).padStart(2, '0')}`;
  };
  const diasNoMes = (comp) => {
    const [a, m] = comp.split('-').map(Number);
    return new Date(Date.UTC(a, m, 0)).getUTCDate();
  };
  const primeiroDia = (comp) => `${comp}-01`;
  const ultimoDia = (comp) => `${comp}-${String(diasNoMes(comp)).padStart(2, '0')}`;
  const competenciaValida = (c) => /^\d{4}-(0[1-9]|1[0-2])$/.test(String(c || ''));

  function listarCompetencias(de, ate) {
    const out = [];
    if (!competenciaValida(de) || !competenciaValida(ate) || de > ate) return out;
    for (let c = de; c <= ate && out.length < 240; c = somarMes(c, 1)) out.push(c);
    return out;
  }

  const ROTULOS_MES = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];
  const rotuloComp = (c) => `${ROTULOS_MES[Number(c.slice(5)) - 1]}/${c.slice(0, 4)}`;

  /** Dias úteis e dias de descanso (domingos e feriados) da competência. */
  function calendario(comp, feriados) {
    const fer = new Set(feriados || []);
    const [a, m] = comp.split('-').map(Number);
    let uteis = 0;
    let descanso = 0;
    const n = diasNoMes(comp);
    for (let d = 1; d <= n; d++) {
      const data = `${comp}-${String(d).padStart(2, '0')}`;
      const dow = new Date(Date.UTC(a, m - 1, d)).getUTCDay();
      if (dow === 0 || fer.has(data)) descanso++;
      else uteis++;
    }
    return { dias: n, uteis, descanso };
  }

  /** Colaborador com vínculo ativo na data (admissão até o dia do desligamento). */
  const ativoEm = (c, data) => (!c.admissao || c.admissao <= data) && (!c.desligamento || c.desligamento > data);
  /** Teve vínculo em algum dia da competência. */
  const ativoNoMes = (c, comp) => (!c.admissao || c.admissao <= ultimoDia(comp)) &&
    (!c.desligamento || c.desligamento >= primeiroDia(comp));

  // -------------------------------------------------------------- cálculo

  function parametros(p) {
    const out = { ...PARAMETROS_PADRAO };
    for (const k of Object.keys(PARAMETROS_PADRAO)) {
      if (k === 'regime') { if (REGIMES[p && p.regime]) out.regime = p.regime; continue; }
      const v = lerNumero(p && p[k]);
      if (v != null) out[k] = v;
    }
    return out;
  }

  /** Percentuais de encargos sobre a remuneração. */
  function encargos(p) {
    p = parametros(p);
    const simples = p.regime === 'simples';
    const inss = simples ? 0 : p.inss;
    const rat = simples ? 0 : p.rat * p.fap;
    const terceiros = simples ? 0 : p.terceiros;
    return { inss, rat, terceiros, fgts: p.fgts, total: inss + rat + terceiros + p.fgts };
  }

  const num = (v) => lerNumero(v) || 0;

  /**
   * Custo de um lançamento mensal.
   * @param l      lançamento ({ salario, he50, he100, noturno, adicionais, faltas, atrasos, ... })
   * @param colab  colaborador (usa a jornada para o valor-hora)
   * @param p      parâmetros de encargos
   * @param cal    calendário da competência (dias úteis e de descanso)
   */
  function calcularLancamento(l, colab, p, cal) {
    const e = encargos(p);
    const salario = num(l.salario);
    const valorHora = salario / divisor(colab && colab.jornada);
    const he50 = num(l.he50) * valorHora * 1.5;
    const he100 = num(l.he100) * valorHora * 2;
    const noturno = num(l.noturno) * valorHora * 0.2;
    const variaveisHora = he50 + he100 + noturno;
    const dsr = cal && cal.uteis ? variaveisHora / cal.uteis * cal.descanso : 0;
    const adicionais = num(l.adicionais);
    const descontos = (num(l.faltas) + num(l.atrasos)) * valorHora;
    const remuneracao = Math.max(0, salario + variaveisHora + dsr + adicionais - descontos);
    const r = {
      salario, valorHora, he50, he100, noturno, dsr, adicionais, descontos, remuneracao,
      variaveis: variaveisHora + dsr + adicionais,
      inss: remuneracao * e.inss / 100, rat: remuneracao * e.rat / 100,
      terceiros: remuneracao * e.terceiros / 100, fgts: remuneracao * e.fgts / 100,
      provFerias: remuneracao / 12 * 4 / 3, prov13: remuneracao / 12,
    };
    r.encargos = r.inss + r.rat + r.terceiros + r.fgts;
    r.encargosProvisoes = (r.provFerias + r.prov13) * e.total / 100;
    r.provisoes = r.provFerias + r.prov13 + r.encargosProvisoes;
    r.porBeneficio = {};
    for (const b of BENEFICIOS) r.porBeneficio[b.id] = num(l[b.id]);
    r.beneficios = soma(BENEFICIOS, (b) => r.porBeneficio[b.id]);
    r.custoTotal = r.remuneracao + r.encargos + r.provisoes + r.beneficios;
    r.multiplicador = salario ? r.custoTotal / salario : 0;
    for (const k of Object.keys(r)) if (typeof r[k] === 'number' && k !== 'multiplicador' && k !== 'valorHora') r[k] = centavos(r[k]);
    return r;
  }

  // ------------------------------------------------------ base dos relatórios

  /**
   * Prepara os dados para os relatórios.
   * dados = { colaboradores, setores, lancamentos, competencias, parametros, feriados (lista de datas) }
   */
  function base(dados) {
    const colabs = new Map((dados.colaboradores || []).map((c) => [c.id, c]));
    const setores = new Map((dados.setores || []).map((s) => [s.id, s]));
    const p = parametros(dados.parametros);
    const cal = {};
    const calDe = (comp) => (cal[comp] = cal[comp] || calendario(comp, (dados.feriados || []).filter((f) => f.startsWith(comp))));
    const lancs = (dados.lancamentos || []).filter((l) => colabs.has(l.colaboradorId)).map((l) => {
      const c = colabs.get(l.colaboradorId);
      return { ...l, colab: c, calc: calcularLancamento(l, c, p, calDe(l.competencia)) };
    });
    return { colabs, setores, p, lancs, calDe, comps: new Map((dados.competencias || []).map((c) => [c.competencia, c])) };
  }

  const doSetor = (setorId) => (c) => !setorId || c.setorId === setorId;
  const noPeriodo = (de, ate) => (l) => l.competencia >= de && l.competencia <= ate;
  const nomeSetor = (b, id) => (b.setores.get(id) || {}).nome || 'Sem setor';
  const horasPrevistasMes = (c, comp) => horasDaJornada(c.jornada).semana * diasNoMes(comp) / 7;

  // ------------------------------------------------- 1. headcount e massa

  function headcountMassa(dados, de, ate, setorId) {
    const b = base(dados);
    const colabs = [...b.colabs.values()].filter(doSetor(setorId));
    const ids = [...new Set(colabs.map((c) => c.setorId))];
    const setores = ids.map((id) => ({ id, nome: nomeSetor(b, id) })).sort((x, y) => x.nome.localeCompare(y.nome));
    const meses = listarCompetencias(de, ate).map((comp) => {
      const fim = ultimoDia(comp);
      const porSetor = {};
      for (const s of setores) porSetor[s.id] = { hc: 0, massa: 0, custo: 0 };
      for (const c of colabs) if (ativoEm(c, fim)) porSetor[c.setorId].hc++;
      for (const l of b.lancs) {
        if (l.competencia !== comp || !porSetor[l.colab.setorId]) continue;
        porSetor[l.colab.setorId].massa += l.calc.remuneracao;
        porSetor[l.colab.setorId].custo += l.calc.custoTotal;
      }
      const total = { hc: soma(setores, (s) => porSetor[s.id].hc), massa: soma(setores, (s) => porSetor[s.id].massa),
        custo: soma(setores, (s) => porSetor[s.id].custo) };
      const lancamentos = b.lancs.filter((l) => l.competencia === comp && porSetor[l.colab.setorId]).length;
      return { competencia: comp, porSetor, total, lancamentos, temLancamentos: lancamentos > 0 };
    });
    const primeiro = meses[0];
    const ultimo = meses[meses.length - 1];
    return {
      setores, meses,
      variacaoHeadcount: primeiro && ultimo ? ultimo.total.hc - primeiro.total.hc : 0,
      massaTotal: centavos(soma(meses, (m) => m.total.massa)),
      custoTotal: centavos(soma(meses, (m) => m.total.custo)),
    };
  }

  // ------------------------------------------- 2. horas extras e adicionais

  function horasExtras(dados, de, ate, setorId) {
    const b = base(dados);
    const p = b.p;
    const comps = listarCompetencias(de, ate);
    const porColab = new Map();
    for (const l of b.lancs.filter(noPeriodo(de, ate))) {
      if (!doSetor(setorId)(l.colab)) continue;
      const r = porColab.get(l.colaboradorId) || {
        colab: l.colab, he50: 0, he100: 0, noturno: 0, valorHE: 0, valorNoturno: 0, dsr: 0, adicionais: 0, salario: 0, mesesComHE: new Set(),
      };
      r.he50 += num(l.he50); r.he100 += num(l.he100); r.noturno += num(l.noturno);
      r.valorHE += l.calc.he50 + l.calc.he100; r.valorNoturno += l.calc.noturno; r.dsr += l.calc.dsr;
      r.adicionais += l.calc.adicionais; r.salario += l.calc.salario;
      if (num(l.he50) + num(l.he100) > 0) r.mesesComHE.add(l.competencia);
      porColab.set(l.colaboradorId, r);
    }
    const colaboradores = [...porColab.values()].map((r) => {
      let seguidos = 0;
      let maior = 0;
      for (const c of comps) { seguidos = r.mesesComHE.has(c) ? seguidos + 1 : 0; maior = Math.max(maior, seguidos); }
      const horas = r.he50 + r.he100;
      const media = comps.length ? horas / comps.length : 0;
      const valor = r.valorHE + r.valorNoturno + r.dsr + r.adicionais;
      return {
        colab: r.colab, setor: nomeSetor(b, r.colab.setorId), he50: r.he50, he100: r.he100, horas, noturno: r.noturno,
        valorHE: centavos(r.valorHE), valorNoturno: centavos(r.valorNoturno), dsr: centavos(r.dsr), adicionais: centavos(r.adicionais),
        valor: centavos(valor), meses: r.mesesComHE.size, seguidos: maior, media,
        pctSalario: r.salario ? valor / r.salario * 100 : 0,
        recorrente: maior >= 3, acimaDoLimite: media > p.alertaHorasExtras,
      };
    }).filter((r) => r.horas || r.noturno || r.adicionais).sort((x, y) => y.valor - x.valor);
    const setores = {};
    for (const r of colaboradores) {
      const s = setores[r.colab.setorId] || (setores[r.colab.setorId] = { setor: r.setor, horas: 0, valor: 0, colaboradores: 0, horasPrevistas: 0 });
      s.horas += r.horas; s.valor += r.valor; s.colaboradores++;
      s.horasPrevistas += horasPrevistasMes(r.colab, comps[0] || de);
    }
    const listaSetores = Object.values(setores).map((s) => ({
      ...s, valor: centavos(s.valor),
      // horas extras do período convertidas em colaboradores de jornada integral
      equivalente: comps.length && s.colaboradores ? s.horas / comps.length / (s.horasPrevistas / s.colaboradores) : 0,
    })).sort((x, y) => y.valor - x.valor);
    return {
      colaboradores, setores: listaSetores, meses: comps.length,
      totalHoras: soma(colaboradores, (r) => r.horas), totalValor: centavos(soma(colaboradores, (r) => r.valor)),
      recorrentes: colaboradores.filter((r) => r.recorrente).length,
    };
  }

  // ------------------------------------------- 3. provisão de férias e 13º

  /** Meses completos entre duas datas (fração de 15 dias ou mais conta como mês — CLT arts. 130 e 146; Lei 4.090/1962). */
  function avosEntre(inicio, fim) {
    const [a1, m1, d1] = inicio.split('-').map(Number);
    const [a2, m2, d2] = fim.split('-').map(Number);
    let meses = (a2 - a1) * 12 + (m2 - m1);
    let dias = d2 - d1 + 1;
    if (dias < 0) { meses--; dias += new Date(Date.UTC(a2, m2 - 1, 0)).getUTCDate(); }
    if (dias >= 15) meses++;
    return Math.max(0, meses);
  }
  /** Avos de 13º no ano da competência: meses do calendário com 15 dias ou mais de trabalho (Lei 4.090/1962, art. 1º, § 2º). */
  function avos13Ate(admissao, ref) {
    const ano = ref.slice(0, 4);
    if (admissao.slice(0, 4) < ano) return Number(ref.slice(5));
    if (admissao.slice(0, 7) > ref) return 0;
    const mesAdm = admissao.slice(0, 7);
    const diasTrabalhados = diasNoMes(mesAdm) - Number(admissao.slice(8)) + 1;
    return Number(ref.slice(5)) - Number(mesAdm.slice(5)) + (diasTrabalhados >= 15 ? 1 : 0);
  }
  const somarAnos = (data, n) => `${Number(data.slice(0, 4)) + n}${data.slice(4)}`;
  const menosUmDia = (data) => {
    const d = new Date(`${data}T00:00:00Z`);
    d.setUTCDate(d.getUTCDate() - 1);
    return d.toISOString().slice(0, 10);
  };

  /** Início do período aquisitivo de férias em aberto na data de referência. */
  function inicioAquisitivo(c, ref) {
    let ini = c.inicioAquisitivo || c.admissao;
    if (!ini || ini > ref) return null;
    while (somarAnos(ini, 1) <= ref) ini = somarAnos(ini, 1);
    return ini;
  }

  function provisoes(dados, ref, setorId) {
    const b = base(dados);
    const e = encargos(b.p);
    const dataRef = ultimoDia(ref);
    const anoRef = ref.slice(0, 4);
    const colaboradores = [];
    const semAdmissao = [];
    for (const c of b.colabs.values()) {
      if (!doSetor(setorId)(c) || !ativoEm(c, dataRef)) continue;
      if (!c.admissao) { semAdmissao.push(c); continue; }
      const proprios = b.lancs.filter((l) => l.colaboradorId === c.id && l.competencia <= ref).sort((x, y) => x.competencia.localeCompare(y.competencia));
      const ultimo = proprios[proprios.length - 1];
      const salario = ultimo ? ultimo.calc.salario : num(c.salario);
      const doze = proprios.filter((l) => l.competencia > somarMes(ref, -12));
      const mediaVariaveis = doze.length ? soma(doze, (l) => l.calc.variaveis) / doze.length : 0;
      const remuneracao = salario + mediaVariaveis;
      // 13º: avos do ano até a referência
      const avos13 = avos13Ate(c.admissao, ref);
      const valor13 = remuneracao * avos13 / 12;
      // férias: períodos vencidos + proporcionais, com 1/3
      const iniAq = inicioAquisitivo(c, dataRef);
      const avosFerias = iniAq ? Math.min(12, avosEntre(iniAq, dataRef)) : 0;
      const vencidas = Math.max(0, Math.round(num(c.feriasVencidas)));
      const emDobro = Math.max(0, vencidas - 1);
      const valorFerias = remuneracao * (vencidas + emDobro + avosFerias / 12) * 4 / 3;
      const alertas = [];
      let prazo = null;
      if (vencidas >= 2) alertas.push(`${vencidas} períodos vencidos: férias fora do prazo são pagas em dobro (CLT art. 137).`);
      if (vencidas >= 1 && iniAq) {
        prazo = menosUmDia(somarAnos(iniAq, 1));
        alertas.push(`Conceder as férias vencidas até ${prazo.split('-').reverse().join('/')}.`);
      }
      const encargosValor = (valor13 + valorFerias) * e.total / 100;
      colaboradores.push({
        colab: c, setor: nomeSetor(b, c.setorId), salario, mediaVariaveis: centavos(mediaVariaveis),
        avos13, valor13: centavos(valor13), inicioAquisitivo: iniAq, avosFerias, vencidas,
        valorFerias: centavos(valorFerias), encargos: centavos(encargosValor),
        total: centavos(valor13 + valorFerias + encargosValor), prazo, alertas,
      });
    }
    colaboradores.sort((x, y) => y.total - x.total);
    // provisão mês a mês no ano da referência (o que vai sendo acumulado no caixa)
    const meses = listarCompetencias(`${anoRef}-01`, ref).map((comp) => {
      const ls = b.lancs.filter((l) => l.competencia === comp && doSetor(setorId)(l.colab));
      return {
        competencia: comp, lancamentos: ls.length, ferias: centavos(soma(ls, (l) => l.calc.provFerias)),
        decimo: centavos(soma(ls, (l) => l.calc.prov13)), encargos: centavos(soma(ls, (l) => l.calc.encargosProvisoes)),
      };
    });
    return {
      colaboradores, semAdmissao, meses, referencia: ref,
      total13: centavos(soma(colaboradores, (r) => r.valor13)),
      totalFerias: centavos(soma(colaboradores, (r) => r.valorFerias)),
      totalEncargos: centavos(soma(colaboradores, (r) => r.encargos)),
      total: centavos(soma(colaboradores, (r) => r.total)),
    };
  }

  // ---------------------------------------- 4. custo total por colaborador

  const COMPONENTES = ['salario', 'variaveis', 'descontos', 'remuneracao', 'encargos', 'provisoes', 'beneficios', 'custoTotal'];

  function custoColaborador(dados, de, ate, setorId) {
    const b = base(dados);
    const porColab = new Map();
    for (const l of b.lancs.filter(noPeriodo(de, ate))) {
      if (!doSetor(setorId)(l.colab)) continue;
      const r = porColab.get(l.colaboradorId) || { colab: l.colab, setor: nomeSetor(b, l.colab.setorId), meses: 0 };
      r.meses++;
      for (const k of COMPONENTES) r[k] = (r[k] || 0) + l.calc[k];
      for (const k of ['inss', 'rat', 'terceiros', 'fgts']) r[k] = (r[k] || 0) + l.calc[k];
      porColab.set(l.colaboradorId, r);
    }
    const colaboradores = [...porColab.values()].map((r) => {
      const out = { ...r };
      for (const k of [...COMPONENTES, 'inss', 'rat', 'terceiros', 'fgts']) out[k] = centavos(r[k]);
      out.mediaMensal = centavos(r.custoTotal / r.meses);
      out.multiplicador = r.salario ? r.custoTotal / r.salario : 0;
      return out;
    }).sort((x, y) => y.custoTotal - x.custoTotal);
    const setores = {};
    for (const r of colaboradores) {
      const s = setores[r.colab.setorId] || (setores[r.colab.setorId] = { setor: r.setor, colaboradores: 0 });
      s.colaboradores++;
      for (const k of COMPONENTES) s[k] = centavos((s[k] || 0) + r[k]);
    }
    const total = {};
    for (const k of COMPONENTES) total[k] = centavos(soma(colaboradores, (r) => r[k]));
    total.multiplicador = total.salario ? total.custoTotal / total.salario : 0;
    return {
      colaboradores, setores: Object.values(setores).sort((x, y) => y.custoTotal - x.custoTotal),
      total, encargos: encargos(b.p),
    };
  }

  // ------------------------------------------------- 5. sinistralidade

  function sinistralidade(dados, de, ate) {
    const b = base(dados);
    const linhas = [];
    const todas = [...b.comps.keys()].sort();
    const premioDe = (comp) => {
      const c = b.comps.get(comp) || {};
      const informado = lerNumero(c.premioSaude);
      if (informado != null) return informado;
      return soma(b.lancs.filter((l) => l.competencia === comp), (l) => l.calc.porBeneficio.saude);
    };
    const sinistrosDe = (comp) => lerNumero((b.comps.get(comp) || {}).sinistrosSaude);
    for (const comp of listarCompetencias(de, ate)) {
      const premio = premioDe(comp);
      const sinistros = sinistrosDe(comp);
      // acumulado dos 12 meses até a competência (como a operadora calcula o reajuste)
      const janela = todas.filter((c) => c > somarMes(comp, -12) && c <= comp && sinistrosDe(c) != null);
      const p12 = soma(janela, premioDe);
      const s12 = soma(janela, (c) => sinistrosDe(c));
      linhas.push({
        competencia: comp, premio: centavos(premio), sinistros: sinistros == null ? null : centavos(sinistros),
        indice: sinistros != null && premio ? sinistros / premio * 100 : null,
        acumulado12: p12 ? s12 / p12 * 100 : null,
      });
    }
    const comDados = linhas.filter((l) => l.sinistros != null);
    const premio = soma(comDados, (l) => l.premio);
    const sinistrosTotal = soma(comDados, (l) => l.sinistros);
    const indice = premio ? sinistrosTotal / premio * 100 : null;
    const ultimo = [...linhas].reverse().find((l) => l.acumulado12 != null);
    const ref = ultimo ? ultimo.acumulado12 : indice;
    const situacao = ref == null ? 'sem-dados' : ref >= b.p.limiteSinistralidade ? 'critica'
      : ref >= b.p.alertaSinistralidade ? 'atencao' : 'saudavel';
    return {
      meses: linhas, premio: centavos(premio), sinistros: centavos(sinistrosTotal), indice,
      acumulado12: ultimo ? ultimo.acumulado12 : null, situacao,
      alerta: b.p.alertaSinistralidade, limite: b.p.limiteSinistralidade,
    };
  }

  // ---------------------------------------- 6. custo per capita de benefícios

  function beneficiosPerCapita(dados, de, ate, setorId) {
    const b = base(dados);
    const colabs = [...b.colabs.values()].filter(doSetor(setorId));
    const comps = listarCompetencias(de, ate);
    const vidas = soma(comps, (comp) => colabs.filter((c) => ativoEm(c, ultimoDia(comp))).length);
    const ls = b.lancs.filter(noPeriodo(de, ate)).filter((l) => doSetor(setorId)(l.colab));
    const remuneracao = soma(ls, (l) => l.calc.remuneracao);
    const linhas = BENEFICIOS.map((ben) => {
      const total = soma(ls, (l) => l.calc.porBeneficio[ben.id]);
      const beneficiarios = ls.filter((l) => l.calc.porBeneficio[ben.id] > 0).length;
      return {
        id: ben.id, nome: ben.nome, total: centavos(total), beneficiarios,
        perCapita: vidas ? total / vidas : 0, porBeneficiario: beneficiarios ? total / beneficiarios : 0,
        pctRemuneracao: remuneracao ? total / remuneracao * 100 : 0,
      };
    });
    const total = soma(linhas, (l) => l.total);
    return {
      linhas, total: centavos(total), vidasMes: vidas, meses: comps.length,
      vidasMedia: comps.length ? vidas / comps.length : 0,
      perCapita: vidas ? total / vidas : 0, pctRemuneracao: remuneracao ? total / remuneracao * 100 : 0,
      remuneracao: centavos(remuneracao),
    };
  }

  // ---------------------------------------- 7. absenteísmo por motivo médico

  function absenteismoMedico(dados, de, ate, setorId) {
    const b = base(dados);
    const ls = b.lancs.filter(noPeriodo(de, ate)).filter((l) => doSetor(setorId)(l.colab) && num(l.atestadoDias) > 0);
    const totalDias = soma(ls, (l) => num(l.atestadoDias));
    const motivos = Object.entries(MOTIVOS_ATESTADO).map(([id, nome]) => {
      const doMotivo = ls.filter((l) => (l.atestadoMotivo || 'outros') === id);
      const dias = soma(doMotivo, (l) => num(l.atestadoDias));
      return {
        id, nome, dias, atestados: doMotivo.length, colaboradores: new Set(doMotivo.map((l) => l.colaboradorId)).size,
        pct: totalDias ? dias / totalDias * 100 : 0,
      };
    }).filter((m) => m.dias).sort((x, y) => y.dias - x.dias);
    const setores = {};
    for (const l of ls) {
      const s = setores[l.colab.setorId] || (setores[l.colab.setorId] = { setor: nomeSetor(b, l.colab.setorId), dias: 0, atestados: 0 });
      s.dias += num(l.atestadoDias);
      s.atestados++;
    }
    // mais de 15 dias no mês: a partir do 16º dia o afastamento é pago pelo INSS (Lei 8.213/1991, art. 60)
    const afastamentos = ls.filter((l) => num(l.atestadoDias) > 15).map((l) => ({
      colab: l.colab, competencia: l.competencia, dias: num(l.atestadoDias), motivo: MOTIVOS_ATESTADO[l.atestadoMotivo] || MOTIVOS_ATESTADO.outros,
    }));
    return {
      motivos, setores: Object.values(setores).sort((x, y) => y.dias - x.dias), totalDias, atestados: ls.length,
      colaboradores: new Set(ls.map((l) => l.colaboradorId)).size, afastamentos,
    };
  }

  // ------------------------------------------------------- 8. turnover

  function turnover(dados, de, ate, setorId) {
    const b = base(dados);
    const colabs = [...b.colabs.values()].filter(doSetor(setorId));
    const grupo = (c) => (TIPOS_DESLIGAMENTO[c.tipoDesligamento] || TIPOS_DESLIGAMENTO.outros).grupo;
    const meses = listarCompetencias(de, ate).map((comp) => {
      const hcInicio = colabs.filter((c) => ativoEm(c, menosUmDia(primeiroDia(comp)))).length;
      const hcFim = colabs.filter((c) => ativoEm(c, ultimoDia(comp))).length;
      const admissoes = colabs.filter((c) => c.admissao && c.admissao.slice(0, 7) === comp).length;
      const saidas = colabs.filter((c) => c.desligamento && c.desligamento.slice(0, 7) === comp);
      const porGrupo = { voluntario: 0, involuntario: 0, acordo: 0, outros: 0 };
      for (const c of saidas) porGrupo[grupo(c)]++;
      const hcMedio = (hcInicio + hcFim) / 2;
      return {
        competencia: comp, hcInicio, hcFim, hcMedio, admissoes, desligamentos: saidas.length, ...porGrupo,
        taxa: hcMedio ? (admissoes + saidas.length) / 2 / hcMedio * 100 : 0,
        taxaSaida: hcMedio ? saidas.length / hcMedio * 100 : 0,
      };
    });
    const hcMedio = meses.length ? soma(meses, (m) => m.hcMedio) / meses.length : 0;
    const t = (k) => soma(meses, (m) => m[k]);
    const desligados = colabs.filter((c) => c.desligamento && c.desligamento.slice(0, 7) >= de && c.desligamento.slice(0, 7) <= ate)
      .sort((x, y) => y.desligamento.localeCompare(x.desligamento));
    const motivos = {};
    for (const c of desligados) {
      const k = c.motivoDesligamento || 'nao_informado';
      const m = motivos[k] || (motivos[k] = { id: k, nome: MOTIVOS_DESLIGAMENTO[k] || 'Não informado', total: 0, voluntario: 0, involuntario: 0, acordo: 0, outros: 0 });
      m.total++;
      m[grupo(c)]++;
    }
    const tempoCasa = desligados.filter((c) => c.admissao).map((c) => avosEntre(c.admissao, c.desligamento));
    return {
      meses, hcMedio,
      admissoes: t('admissoes'), desligamentos: t('desligamentos'),
      voluntario: t('voluntario'), involuntario: t('involuntario'), acordo: t('acordo'), outros: t('outros'),
      taxa: hcMedio ? (t('admissoes') + t('desligamentos')) / 2 / hcMedio * 100 : 0,
      taxaVoluntaria: hcMedio ? t('voluntario') / hcMedio * 100 : 0,
      taxaInvoluntaria: hcMedio ? t('involuntario') / hcMedio * 100 : 0,
      motivos: Object.values(motivos).sort((x, y) => y.total - x.total),
      desligados: desligados.map((c) => ({
        colab: c, setor: nomeSetor(b, c.setorId), tipo: (TIPOS_DESLIGAMENTO[c.tipoDesligamento] || TIPOS_DESLIGAMENTO.outros).nome,
        grupo: GRUPOS_DESLIGAMENTO[grupo(c)], motivo: MOTIVOS_DESLIGAMENTO[c.motivoDesligamento] || 'Não informado',
        mesesDeCasa: c.admissao ? avosEntre(c.admissao, c.desligamento) : null,
      })),
      tempoMedioMeses: tempoCasa.length ? soma(tempoCasa, (x) => x) / tempoCasa.length : null,
      // saídas nos primeiros 90 dias (contrato de experiência — CLT art. 445)
      saidasPrecoces: desligados.filter((c) => c.admissao && (Date.parse(c.desligamento) - Date.parse(c.admissao)) / 86400000 < 90).length,
    };
  }

  // ------------------------------------------------ 9. absenteísmo geral

  function absenteismoGeral(dados, de, ate, setorId) {
    const b = base(dados);
    const ls = b.lancs.filter(noPeriodo(de, ate)).filter((l) => doSetor(setorId)(l.colab));
    const linha = (l) => {
      const h = horasDaJornada(l.colab.jornada);
      return {
        previstas: horasPrevistasMes(l.colab, l.competencia), faltas: num(l.faltas), atrasos: num(l.atrasos),
        atestados: num(l.atestadoDias) * h.dia,
      };
    };
    const acumular = (alvo, x) => { for (const k of ['previstas', 'faltas', 'atrasos', 'atestados']) alvo[k] = (alvo[k] || 0) + x[k]; return alvo; };
    const fechar = (r) => {
      r.perdidas = r.faltas + r.atrasos + r.atestados;
      r.taxa = r.previstas ? r.perdidas / r.previstas * 100 : 0;
      r.taxaSemAtestado = r.previstas ? (r.faltas + r.atrasos) / r.previstas * 100 : 0;
      return r;
    };
    const setores = {};
    const colabs = {};
    const meses = {};
    const total = {};
    for (const l of ls) {
      const x = linha(l);
      acumular(setores[l.colab.setorId] || (setores[l.colab.setorId] = { setor: nomeSetor(b, l.colab.setorId) }), x);
      acumular(colabs[l.colaboradorId] || (colabs[l.colaboradorId] = { colab: l.colab, setor: nomeSetor(b, l.colab.setorId) }), x);
      acumular(meses[l.competencia] || (meses[l.competencia] = { competencia: l.competencia }), x);
      acumular(total, x);
    }
    return {
      total: fechar({ previstas: 0, faltas: 0, atrasos: 0, atestados: 0, ...total }),
      setores: Object.values(setores).map(fechar).sort((x, y) => y.taxa - x.taxa),
      colaboradores: Object.values(colabs).map(fechar).filter((r) => r.perdidas).sort((x, y) => y.taxa - x.taxa),
      meses: Object.values(meses).map(fechar).sort((x, y) => x.competencia.localeCompare(y.competencia)),
    };
  }

  // ------------------------------------------------ 10. banco de horas

  function bancoHoras(dados, ate, setorId) {
    const b = base(dados);
    const porColab = new Map();
    for (const l of b.lancs) {
      if (l.competencia > ate || !doSetor(setorId)(l.colab)) continue;
      const r = porColab.get(l.colaboradorId) || { colab: l.colab, setor: nomeSetor(b, l.colab.setorId), credito: 0, debito: 0, ultimo: null };
      r.credito += num(l.bhCredito);
      r.debito += num(l.bhDebito);
      if (!r.ultimo || l.competencia > r.ultimo.competencia) r.ultimo = l;
      porColab.set(l.colaboradorId, r);
    }
    const colaboradores = [...porColab.values()].filter((r) => r.credito || r.debito).map((r) => {
      const saldo = r.credito - r.debito;
      const valorHora = r.ultimo.calc.valorHora;
      // saldo positivo não compensado é pago como hora extra na rescisão (CLT art. 59, § 3º)
      const passivo = Math.max(0, saldo) * valorHora * 1.5;
      return {
        colab: r.colab, setor: r.setor, credito: r.credito, debito: r.debito, saldo, valorHora,
        passivo: centavos(passivo), alto: saldo > b.p.alertaBancoHoras, negativo: saldo < 0,
        desligado: !!r.colab.desligamento && r.colab.desligamento <= ultimoDia(ate),
      };
    }).sort((x, y) => y.saldo - x.saldo);
    return {
      colaboradores, limite: b.p.alertaBancoHoras,
      saldoPositivo: soma(colaboradores, (r) => Math.max(0, r.saldo)),
      saldoNegativo: soma(colaboradores, (r) => Math.min(0, r.saldo)),
      passivo: centavos(soma(colaboradores, (r) => r.passivo)),
      acimaDoLimite: colaboradores.filter((r) => r.alto).length,
    };
  }

  // ------------------------------------------ 11. perfil do quadro de pessoal

  /** Percentual mínimo de PcD/reabilitados conforme o total de empregados (Lei 8.213/1991, art. 93). */
  function cotaPcd(total) {
    const pct = total >= 1001 ? 5 : total >= 501 ? 4 : total >= 201 ? 3 : total >= 100 ? 2 : 0;
    return { pct, exigidos: Math.ceil(total * pct / 100) };
  }

  const FAIXAS_IDADE = [['Até 24 anos', 0, 25], ['25 a 34', 25, 35], ['35 a 44', 35, 45], ['45 a 54', 45, 55], ['55 ou mais', 55, 200]];
  const FAIXAS_CASA = [['Menos de 1 ano', 0, 1], ['1 a 3 anos', 1, 3], ['3 a 5 anos', 3, 5], ['5 a 10 anos', 5, 10], ['10 anos ou mais', 10, 200]];
  const anosEntre = (ini, fim) => {
    const [a1, m1, d1] = ini.split('-').map(Number);
    const [a2, m2, d2] = fim.split('-').map(Number);
    return a2 - a1 - (m2 < m1 || (m2 === m1 && d2 < d1) ? 1 : 0);
  };

  function perfilQuadro(dados, ref, setorId) {
    const b = base(dados);
    const data = ultimoDia(ref);
    const todos = [...b.colabs.values()].filter((c) => ativoEm(c, data));
    const ativos = todos.filter(doSetor(setorId));
    const aprendiz = (c) => /aprendi/i.test(c.cargo || '');
    const resumo = (lista) => {
      const sal = lista.map((c) => num(c.salario)).filter((v) => v > 0);
      const idades = lista.filter((c) => c.nascimento).map((c) => anosEntre(c.nascimento, data));
      const casa = lista.filter((c) => c.admissao).map((c) => anosEntre(c.admissao, data) + (avosEntre(c.admissao, data) % 12) / 12);
      return {
        total: lista.length, mulheres: lista.filter((c) => c.sexo === 'F').length, homens: lista.filter((c) => c.sexo === 'M').length,
        pcd: lista.filter((c) => c.pcd).length, aprendizes: lista.filter(aprendiz).length,
        salarioMedio: sal.length ? soma(sal, (v) => v) / sal.length : 0, folhaContratual: centavos(soma(sal, (v) => v)),
        idadeMedia: idades.length ? soma(idades, (v) => v) / idades.length : null,
        tempoCasaMedio: casa.length ? soma(casa, (v) => v) / casa.length : null,
      };
    };
    const grupos = {};
    for (const c of ativos) (grupos[c.setorId] = grupos[c.setorId] || []).push(c);
    const faixas = (defs, valor) => defs.map(([nome, min, max]) => ({
      nome, total: ativos.filter((c) => { const v = valor(c); return v != null && v >= min && v < max; }).length,
    })).concat([{ nome: 'Sem data', total: ativos.filter((c) => valor(c) == null).length }]).filter((f) => f.total || f.nome !== 'Sem data');
    // a cota de PcD vale para a empresa toda (todos os estabelecimentos), não para o grupo filtrado
    const cota = cotaPcd(todos.length);
    const pcdEmpresa = todos.filter((c) => c.pcd).length;
    return {
      referencia: ref, geral: resumo(ativos),
      grupos: Object.entries(grupos).map(([id, lista]) => ({ id, nome: nomeSetor(b, id), ...resumo(lista) })).sort((x, y) => y.total - x.total),
      idade: faixas(FAIXAS_IDADE, (c) => (c.nascimento ? anosEntre(c.nascimento, data) : null)),
      tempoCasa: faixas(FAIXAS_CASA, (c) => (c.admissao ? anosEntre(c.admissao, data) : null)),
      cota: { ...cota, totalEmpresa: todos.length, pcd: pcdEmpresa, deficit: Math.max(0, cota.exigidos - pcdEmpresa) },
    };
  }

  return {
    PARAMETROS_PADRAO, REGIMES, JORNADA_HORAS, BENEFICIOS, CAMPOS,
    TIPOS_DESLIGAMENTO, GRUPOS_DESLIGAMENTO, SEM_CONTROLE_JORNADA, MOTIVOS_DESLIGAMENTO, MOTIVOS_ATESTADO,
    centavos, lerNumero, lerTabela, lerPlanilhaLancamentos, lerMotivoAtestado,
    somarMes, diasNoMes, primeiroDia, ultimoDia, competenciaValida, listarCompetencias, rotuloComp,
    calendario, ativoEm, ativoNoMes, avosEntre, avos13Ate, inicioAquisitivo, divisor, horasDaJornada,
    parametros, encargos, calcularLancamento,
    headcountMassa, horasExtras, provisoes, custoColaborador, sinistralidade,
    beneficiosPerCapita, absenteismoMedico, turnover, absenteismoGeral, bancoHoras, perfilQuadro, cotaPcd,
  };
});
