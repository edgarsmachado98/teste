/*
 * Motor de geração e validação de escalas de trabalho conforme a legislação
 * trabalhista brasileira (CF/88, CLT, Lei 605/1949, Lei 10.101/2000).
 *
 * Funciona no navegador (expõe window.EscalaMotor) e no Node (module.exports).
 * Datas são sempre strings "AAAA-MM-DD" tratadas em UTC para evitar fuso horário.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.EscalaMotor = api;
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const DIA_MS = 86400000;
  const NOMES_DIAS = ['Dom', 'Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb'];

  // ---------------------------------------------------------------- datas

  function parseData(s) {
    const [a, m, d] = s.split('-').map(Number);
    return new Date(Date.UTC(a, m - 1, d));
  }

  function formatarData(dt) {
    return dt.toISOString().slice(0, 10);
  }

  function somarDias(s, n) {
    return formatarData(new Date(parseData(s).getTime() + n * DIA_MS));
  }

  function diaSemana(s) {
    return parseData(s).getUTCDay();
  }

  function listarDatas(inicio, fim) {
    const out = [];
    for (let d = inicio; d <= fim; d = somarDias(d, 1)) out.push(d);
    return out;
  }

  /** Segunda-feira da semana (semana de seg a dom) que contém a data. */
  function segundaDaSemana(s) {
    const dow = diaSemana(s);
    return somarDias(s, dow === 0 ? -6 : 1 - dow);
  }

  function minutosDeHora(hhmm) {
    const [h, m] = String(hhmm || '00:00').split(':').map(Number);
    return h * 60 + (m || 0);
  }

  function horaDeMinutos(min) {
    const m = ((min % 1440) + 1440) % 1440;
    return String(Math.floor(m / 60)).padStart(2, '0') + ':' + String(m % 60).padStart(2, '0');
  }

  // ------------------------------------------------------------- feriados

  /** Domingo de Páscoa (algoritmo anônimo gregoriano). */
  function pascoa(ano) {
    const a = ano % 19;
    const b = Math.floor(ano / 100);
    const c = ano % 100;
    const d = Math.floor(b / 4);
    const e = b % 4;
    const f = Math.floor((b + 8) / 25);
    const g = Math.floor((b - f + 1) / 3);
    const h = (19 * a + b - d - g + 15) % 30;
    const i = Math.floor(c / 4);
    const k = c % 4;
    const l = (32 + 2 * e + 2 * i - h - k) % 7;
    const m = Math.floor((a + 11 * h + 22 * l) / 451);
    const mes = Math.floor((h + l - 7 * m + 114) / 31);
    const dia = ((h + l - 7 * m + 114) % 31) + 1;
    return formatarData(new Date(Date.UTC(ano, mes - 1, dia)));
  }

  /**
   * Feriados nacionais (Lei 662/1949 e alterações, Lei 6.802/1980,
   * Lei 14.759/2023) e Sexta-feira da Paixão (Lei 9.093/1995).
   * Pontos facultativos (Carnaval, Corpus Christi) só entram se solicitado.
   */
  function feriadosNacionais(ano, incluirFacultativos) {
    const fixos = [
      ['01-01', 'Confraternização Universal'],
      ['04-21', 'Tiradentes'],
      ['05-01', 'Dia do Trabalho'],
      ['09-07', 'Independência do Brasil'],
      ['10-12', 'Nossa Senhora Aparecida'],
      ['11-02', 'Finados'],
      ['11-15', 'Proclamação da República'],
      ['11-20', 'Dia Nacional de Zumbi e da Consciência Negra'],
      ['12-25', 'Natal'],
    ];
    const lista = fixos.map(([md, nome]) => ({ data: `${ano}-${md}`, nome, tipo: 'nacional' }));
    const p = pascoa(ano);
    lista.push({ data: somarDias(p, -2), nome: 'Sexta-feira da Paixão', tipo: 'nacional' });
    if (incluirFacultativos) {
      lista.push({ data: somarDias(p, -48), nome: 'Carnaval (ponto facultativo)', tipo: 'facultativo' });
      lista.push({ data: somarDias(p, -47), nome: 'Carnaval (ponto facultativo)', tipo: 'facultativo' });
      lista.push({ data: somarDias(p, 60), nome: 'Corpus Christi (ponto facultativo)', tipo: 'facultativo' });
    }
    return lista.sort((x, y) => x.data.localeCompare(y.data));
  }

  function mapaFeriados(cfg) {
    const mapa = {};
    const anoIni = Number(cfg.inicio.slice(0, 4));
    const anoFim = Number(cfg.fim.slice(0, 4));
    for (let a = anoIni; a <= anoFim; a++) {
      for (const f of feriadosNacionais(a, cfg.incluirFacultativos)) mapa[f.data] = f;
    }
    for (const f of cfg.feriadosExtras || []) {
      if (f && f.data) mapa[f.data] = { data: f.data, nome: f.nome || 'Feriado local', tipo: 'local' };
    }
    return mapa;
  }

  // -------------------------------------------------------------- jornadas

  /**
   * minutosTrabalho: jornada diária efetiva; intervalo: intrajornada (art. 71 CLT).
   * folgasSemana: folgas por semana (seg-dom). ciclo: escala 12x36 (art. 59-A).
   */
  const JORNADAS = {
    '6x1': {
      nome: '6x1 — 7h20/dia (44h semanais)',
      folgasSemana: 1, minutosTrabalho: 440, intervalo: 60,
    },
    '5x2': {
      nome: '5x2 — 8h48/dia (44h, compensação do sábado)',
      folgasSemana: 2, minutosTrabalho: 528, intervalo: 60, compensacao: true,
    },
    '5x2-40': {
      nome: '5x2 — 8h/dia (40h semanais)',
      folgasSemana: 2, minutosTrabalho: 480, intervalo: 60,
    },
    '6x1-6h': {
      nome: '6x1 — 6h/dia (36h semanais)',
      folgasSemana: 1, minutosTrabalho: 360, intervalo: 15,
    },
    '12x36': {
      nome: '12x36 — 12h de trabalho por 36h de descanso',
      ciclo: true, minutosTrabalho: 720, intervalo: 0,
    },
  };

  const REGRAS_PADRAO = {
    maxDiasConsecutivos: 6,       // art. 67 CLT + OJ 410 SDI-1 TST
    domingoMulheresSemanas: 2,    // art. 386 CLT (revezamento quinzenal)
    domingoHomensSemanas: 3,      // Lei 10.101/2000, art. 6º, par. único (comércio)
    interjornadaMinutos: 660,     // art. 66 CLT (11h)
    maxMinutosSemana: 2640,       // art. 7º, XIII, CF (44h)
    maxMinutosDia: 600,           // art. 59 CLT (8h + 2h extras)
  };

  function regrasDe(cfg) {
    return Object.assign({}, REGRAS_PADRAO, cfg.regras || {});
  }

  function turnoTrabalho(colab) {
    const j = JORNADAS[colab.jornada] || JORNADAS['6x1'];
    const ini = minutosDeHora(colab.entrada || '08:00');
    return { tipo: 'T', inicio: ini, fim: ini + j.minutosTrabalho + j.intervalo, minutos: j.minutosTrabalho };
  }

  /** Minutos de trabalho noturno (22h às 5h, art. 73 CLT) contidos no turno. */
  function minutosNoturnos(inicio, fim) {
    let total = 0;
    // janelas noturnas relativas ao dia de início do turno: [-2h,5h], [22h,29h], [46h,53h]
    for (const [a, b] of [[-120, 300], [1320, 1740], [2760, 3180]]) {
      total += Math.max(0, Math.min(fim, b) - Math.max(inicio, a));
    }
    return total;
  }

  // -------------------------------------------------------------- geração

  function setorAberto(setor, dia) {
    const funciona = setor.diasFuncionamento ? setor.diasFuncionamento[dia.dow] : true;
    if (!funciona) return false;
    if (dia.feriado && !setor.funcionaFeriados) return false;
    return true;
  }

  /** Fechamento regular (dia da semana em que o setor não funciona) conta como folga/DSR. */
  function fechamentoRegular(setor, dia) {
    return setor.diasFuncionamento ? !setor.diasFuncionamento[dia.dow] : false;
  }

  function celulaFolga(dia, setor) {
    if (dia.feriado && !fechamentoRegular(setor, dia) && !setor.funcionaFeriados) return { tipo: 'FER' };
    return { tipo: 'F' };
  }

  function gerarEscala(cfg) {
    if (!cfg.inicio || !cfg.fim || cfg.inicio > cfg.fim) throw new Error('Período inválido.');
    const feriados = mapaFeriados(cfg);
    const dias = listarDatas(cfg.inicio, cfg.fim).map((data) => ({
      data, dow: diaSemana(data), feriado: feriados[data] || null,
    }));
    const celulas = {};
    for (const setor of cfg.setores || []) {
      const membros = (cfg.colaboradores || []).filter((c) => c.setorId === setor.id);
      gerarSetor(setor, membros, dias, regrasDe(cfg), celulas);
    }
    return { inicio: cfg.inicio, fim: cfg.fim, dias, celulas };
  }

  function gerarSetor(setor, membros, dias, regras, celulas) {
    const n = dias.length;
    const ultimo = n - 1;
    const aberto = dias.map((d) => setorAberto(setor, d));
    const regular = dias.map((d) => fechamentoRegular(setor, d));

    // --- 12x36: alterna trabalho/descanso, defasando metade da equipe
    const ciclo = membros.filter((c) => (JORNADAS[c.jornada] || {}).ciclo);
    ciclo.forEach((c, k) => {
      celulas[c.id] = dias.map((d, i) =>
        aberto[i] && (i + k) % 2 === 0 ? turnoTrabalho(c) : celulaFolga(d, setor));
    });
    const cicloTrabalhando = dias.map((_, i) =>
      ciclo.filter((c) => celulas[c.id][i].tipo === 'T').length);

    // --- escalas semanais (6x1, 5x2...) com rodízio de domingos
    const rot = membros.filter((c) => !(JORNADAS[c.jornada] || {}).ciclo);
    if (!rot.length) return;

    const ordemDomingo = {};
    let contDom = 0;
    dias.forEach((d, i) => { if (d.dow === 0) ordemDomingo[i] = contDom++; });

    const est = rot.map((c) => {
      const periodo = c.sexo === 'F' ? regras.domingoMulheresSemanas : regras.domingoHomensSemanas;
      celulas[c.id] = new Array(n);
      return {
        c, j: JORNADAS[c.jornada] || JORNADAS['6x1'], periodo: Math.max(1, Number(periodo) || 1), fase: 0,
        ultimaFolga: -1, folgasSemana: 0, domingosSeguidos: 0,
      };
    });

    // escolhe a fase do rodízio de domingos de cada pessoa equilibrando quantas
    // folgam em cada domingo (períodos menores primeiro: mulheres, art. 386)
    const domingosAbertos = Object.keys(ordemDomingo).map(Number).filter((i) => aberto[i]);
    const folgasPorDomingo = {};
    domingosAbertos.forEach((i) => { folgasPorDomingo[i] = 0; });
    est.slice().sort((a, b) => a.periodo - b.periodo).forEach((e) => {
      let melhor = 0;
      let melhorCusto = null;
      for (let f = 0; f < e.periodo; f++) {
        const alvo = domingosAbertos.filter((i) => (ordemDomingo[i] + f) % e.periodo === 0);
        const custo = [Math.max(0, ...alvo.map((i) => folgasPorDomingo[i] + 1)), alvo.length];
        if (!melhorCusto || custo[0] < melhorCusto[0] || (custo[0] === melhorCusto[0] && custo[1] < melhorCusto[1])) {
          melhor = f;
          melhorCusto = custo;
        }
      }
      e.fase = melhor;
      domingosAbertos.forEach((i) => { if ((ordemDomingo[i] + melhor) % e.periodo === 0) folgasPorDomingo[i]++; });
    });

    const domingoPlanejado = (e, i) =>
      dias[i].dow === 0 && aberto[i] && (ordemDomingo[i] + e.fase) % e.periodo === 0;

    // próximo dia (> i) em que a folga já é garantida: fechamento ou domingo planejado
    const proximaFolgaGarantida = (e, i) => {
      for (let j = i + 1; j <= ultimo; j++) if (!aberto[j] || domingoPlanejado(e, j)) return j;
      return Infinity;
    };

    let fimSemana = -1;
    let semanaTruncada = false;

    for (let i = 0; i < n; i++) {
      const dia = dias[i];
      if (i === 0 || dia.dow === 1) {
        const ate = i + ((7 - dia.dow) % 7);
        fimSemana = Math.min(ate, ultimo);
        // semana incompleta no início ou no fim do período: a cota semanal não é
        // exigida (os dias fora do período são desconhecidos); vale o limite de
        // dias consecutivos, que já garante o DSR
        semanaTruncada = ate > ultimo || dia.dow !== 1;
        est.forEach((e) => { e.folgasSemana = 0; });
      }

      if (!aberto[i]) {
        for (const e of est) {
          celulas[e.c.id][i] = celulaFolga(dia, setor);
          if (regular[i]) e.folgasSemana++;
          e.ultimaFolga = i;
          if (dia.dow === 0) e.domingosSeguidos = 0;
        }
        continue;
      }

      // dias úteis (não-domingo) abertos restantes na semana, incluindo hoje
      let diasUteisRestantes = 0;
      for (let j = i; j <= fimSemana; j++) if (aberto[j] && dias[j].dow !== 0) diasUteisRestantes++;
      let fechadosFuturos = 0;
      for (let j = i + 1; j <= fimSemana; j++) if (regular[j]) fechadosFuturos++;

      const obrigatorios = [];
      const candidatos = [];
      let necessidadeTotal = 0;

      for (const e of est) {
        const consecutivos = i - e.ultimaFolga - 1;
        const prazo = e.ultimaFolga + regras.maxDiasConsecutivos + 1;
        const domFim = dias[fimSemana].dow === 0 ? fimSemana : -1;
        const reservado = domFim > i && domingoPlanejado(e, domFim);
        const cota = semanaTruncada ? 0 : e.j.folgasSemana;
        const faltam = cota - e.folgasSemana - (reservado ? 1 : 0) - fechadosFuturos;
        const proxima = proximaFolgaGarantida(e, i);
        const prazoNaSemana = prazo <= fimSemana && prazo < proxima;
        const necessidade = Math.max(faltam, prazoNaSemana ? 1 : 0);

        const limite = prazoNaSemana ? Math.min(prazo, fimSemana) : fimSemana;
        let disponiveis = 0;
        for (let j = i; j <= limite; j++) {
          if (aberto[j] && !(reservado && j === domFim)) disponiveis++;
        }

        const obrig =
          domingoPlanejado(e, i) ||
          consecutivos >= regras.maxDiasConsecutivos ||
          (dia.dow === 0 && e.domingosSeguidos >= e.periodo - 1) ||
          (necessidade > 0 && necessidade >= disponiveis);

        if (necessidade > 0) necessidadeTotal += necessidade;
        if (obrig) obrigatorios.push(e);
        else if (necessidade > 0 && dia.dow !== 0) candidatos.push({ e, prazo, disponiveis });
      }

      // distribui as folgas opcionais de modo uniforme ao longo da semana,
      // sem deixar o setor abaixo do mínimo de pessoas
      let extras = 0;
      if (dia.dow !== 0 && diasUteisRestantes > 0) {
        const alvo = Math.ceil(necessidadeTotal / diasUteisRestantes);
        const trabalhando = est.length - obrigatorios.length + cicloTrabalhando[i];
        const folgaPossivel = Math.max(0, trabalhando - (Number(setor.minimoPorDia) || 0));
        extras = Math.min(Math.max(0, alvo - obrigatorios.length), folgaPossivel, candidatos.length);
      }
      candidatos.sort((a, b) => a.prazo - b.prazo || a.disponiveis - b.disponiveis || a.e.fase - b.e.fase);
      const folgam = new Set(obrigatorios.concat(candidatos.slice(0, extras).map((x) => x.e)));

      for (const e of est) {
        if (folgam.has(e)) {
          celulas[e.c.id][i] = { tipo: 'F' };
          e.folgasSemana++;
          e.ultimaFolga = i;
          if (dia.dow === 0) e.domingosSeguidos = 0;
        } else {
          celulas[e.c.id][i] = turnoTrabalho(e.c);
          if (dia.dow === 0) e.domingosSeguidos++;
        }
      }
    }
  }

  // ------------------------------------------------------------ validação

  /**
   * Retorna lista de ocorrências { nivel: 'erro'|'alerta'|'info', colaboradorId?,
   * setorId?, data?, regra, mensagem, base }.
   */
  function validarEscala(cfg, escala) {
    const regras = regrasDe(cfg);
    const out = [];
    const { dias, celulas } = escala;
    const add = (o) => out.push(o);

    for (const c of cfg.colaboradores || []) {
      const cel = celulas[c.id];
      if (!cel) continue;
      const j = JORNADAS[c.jornada] || JORNADAS['6x1'];
      const setor = (cfg.setores || []).find((s) => s.id === c.setorId);

      // dias consecutivos sem descanso
      if (!j.ciclo) {
        let seq = 0;
        for (let i = 0; i < cel.length; i++) {
          seq = cel[i].tipo === 'T' ? seq + 1 : 0;
          if (seq === regras.maxDiasConsecutivos + 1) {
            add({
              nivel: 'erro', colaboradorId: c.id, data: dias[i].data, regra: 'DSR',
              mensagem: `${seq} dias consecutivos de trabalho sem repouso semanal.`,
              base: 'CF art. 7º, XV; CLT art. 67; OJ 410 SDI-1 TST',
            });
          }
        }
      } else {
        for (let i = 1; i < cel.length; i++) {
          if (cel[i].tipo === 'T' && cel[i - 1].tipo === 'T') {
            add({
              nivel: 'erro', colaboradorId: c.id, data: dias[i].data, regra: '12x36',
              mensagem: 'Plantões 12x36 em dias seguidos (sem as 36h de descanso).',
              base: 'CLT art. 59-A',
            });
          }
        }
      }

      // interjornada e jornada diária
      for (let i = 0; i < cel.length; i++) {
        const t = cel[i];
        if (t.tipo !== 'T') continue;
        if (!j.ciclo && t.minutos > regras.maxMinutosDia) {
          add({
            nivel: 'erro', colaboradorId: c.id, data: dias[i].data, regra: 'Jornada diária',
            mensagem: `Jornada de ${(t.minutos / 60).toFixed(1)}h excede 10h diárias.`,
            base: 'CLT art. 59',
          });
        }
        if (i > 0 && cel[i - 1].tipo === 'T') {
          const descanso = 1440 + t.inicio - cel[i - 1].fim;
          if (descanso < regras.interjornadaMinutos) {
            add({
              nivel: 'erro', colaboradorId: c.id, data: dias[i].data, regra: 'Interjornada',
              mensagem: `Descanso entre jornadas de ${horaDeMinutos(Math.max(0, descanso))} (mínimo 11h).`,
              base: 'CLT art. 66',
            });
          }
        }
      }

      // carga semanal (semana seg-dom)
      if (!j.ciclo) {
        const semanas = {};
        cel.forEach((t, i) => {
          if (t.tipo !== 'T') return;
          const k = segundaDaSemana(dias[i].data);
          semanas[k] = (semanas[k] || 0) + t.minutos;
        });
        for (const [seg, min] of Object.entries(semanas)) {
          if (min > regras.maxMinutosSemana) {
            add({
              nivel: 'erro', colaboradorId: c.id, data: seg, regra: 'Carga semanal',
              mensagem: `Semana iniciada em ${seg.split('-').reverse().join('/')} com ${(min / 60).toFixed(1)}h (limite 44h).`,
              base: 'CF art. 7º, XIII; CLT art. 58',
            });
          }
        }
      }

      // revezamento de domingos
      if (!j.ciclo) {
        const mulher = c.sexo === 'F';
        const periodo = mulher ? regras.domingoMulheresSemanas : regras.domingoHomensSemanas;
        let seguidos = 0;
        for (let i = 0; i < cel.length; i++) {
          if (dias[i].dow !== 0) continue;
          seguidos = cel[i].tipo === 'T' ? seguidos + 1 : 0;
          if (seguidos === periodo) {
            add({
              nivel: 'erro', colaboradorId: c.id, data: dias[i].data, regra: 'Domingo',
              mensagem: mulher
                ? `${seguidos} domingos seguidos trabalhados: mulheres devem folgar um domingo a cada 15 dias.`
                : `${seguidos} domingos seguidos trabalhados: o repouso deve coincidir com o domingo ao menos 1 vez a cada ${periodo} semanas.`,
              base: mulher ? 'CLT art. 386' : (periodo <= 3 ? 'Lei 10.101/2000, art. 6º, par. único' : 'Portaria MTP 671/2021'),
            });
          }
        }
      }

      // feriados trabalhados
      const feriadosTrab = cel.filter((t, i) => t.tipo === 'T' && dias[i].feriado).length;
      if (feriadosTrab && !j.ciclo) {
        add({
          nivel: 'info', colaboradorId: c.id, regra: 'Feriado',
          mensagem: `${feriadosTrab} feriado(s) trabalhado(s): pagar em dobro ou conceder folga compensatória.`,
          base: 'Lei 605/1949, art. 9º; Súmula 146 TST',
        });
      }
      if (j.compensacao) {
        add({
          nivel: 'info', colaboradorId: c.id, regra: 'Compensação',
          mensagem: 'Jornada de 8h48 exige acordo de compensação de horas (sábado).',
          base: 'CLT art. 59, §§ 2º e 6º; Súmula 85 TST',
        });
      }
      if (j.ciclo) {
        add({
          nivel: 'info', colaboradorId: c.id, regra: '12x36',
          mensagem: 'Escala 12x36 exige previsão em acordo individual escrito, acordo ou convenção coletiva.',
          base: 'CLT art. 59-A',
        });
      }
      if (!setor) {
        add({ nivel: 'alerta', colaboradorId: c.id, regra: 'Setor', mensagem: 'Colaborador sem setor válido.', base: '' });
      }
    }

    // cobertura mínima por setor
    for (const s of cfg.setores || []) {
      const membros = (cfg.colaboradores || []).filter((c) => c.setorId === s.id && celulas[c.id]);
      const minimo = Number(s.minimoPorDia) || 0;
      if (!minimo) continue;
      dias.forEach((d, i) => {
        if (!setorAberto(s, d)) return;
        const n = membros.filter((c) => celulas[c.id][i].tipo === 'T').length;
        if (n < minimo) {
          add({
            nivel: 'alerta', setorId: s.id, data: d.data, regra: 'Cobertura',
            mensagem: `Setor ${s.nome}: ${n} pessoa(s) trabalhando, mínimo definido ${minimo}.`,
            base: 'Configuração do setor',
          });
        }
      });
    }

    return out;
  }

  // --------------------------------------------------------------- resumo

  function resumirColaborador(escala, colab) {
    const cel = escala.celulas[colab.id] || [];
    const r = { dias: 0, folgas: 0, domingosFolga: 0, feriadosTrabalhados: 0, minutos: 0, minutosNoturnos: 0 };
    cel.forEach((t, i) => {
      const d = escala.dias[i];
      if (t.tipo === 'T') {
        r.dias++;
        r.minutos += t.minutos;
        r.minutosNoturnos += minutosNoturnos(t.inicio, t.fim);
        if (d.feriado) r.feriadosTrabalhados++;
      } else {
        r.folgas++;
        if (d.dow === 0) r.domingosFolga++;
      }
    });
    return r;
  }

  return {
    NOMES_DIAS, JORNADAS, REGRAS_PADRAO,
    parseData, formatarData, somarDias, diaSemana, listarDatas, segundaDaSemana,
    minutosDeHora, horaDeMinutos, minutosNoturnos,
    pascoa, feriadosNacionais, mapaFeriados,
    turnoTrabalho, setorAberto, gerarEscala, validarEscala, resumirColaborador,
  };
});
