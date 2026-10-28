const test = require('node:test');
const assert = require('node:assert');
const M = require('../js/motor.js');

const TODOS = [true, true, true, true, true, true, true];

function cenario(over = {}) {
  const setores = [
    { id: 's1', nome: 'Loja', minimoPorDia: 4, diasFuncionamento: TODOS, funcionaFeriados: true },
    { id: 's2', nome: 'Administrativo', minimoPorDia: 1, diasFuncionamento: [false, true, true, true, true, true, false], funcionaFeriados: false },
    { id: 's3', nome: 'Portaria', minimoPorDia: 1, diasFuncionamento: TODOS, funcionaFeriados: true },
  ];
  const colaboradores = [];
  const nomes = ['Ana', 'Bruno', 'Carla', 'Diego', 'Elisa', 'Fábio', 'Gabi', 'Heitor'];
  nomes.forEach((nome, k) => colaboradores.push({
    id: 'l' + k, nome, matricula: String(1000 + k), sexo: k % 2 ? 'M' : 'F', setorId: 's1', jornada: '6x1', entrada: '08:00',
  }));
  colaboradores.push({ id: 'a1', nome: 'Irene', matricula: '2001', sexo: 'F', setorId: 's2', jornada: '5x2', entrada: '08:00' });
  colaboradores.push({ id: 'a2', nome: 'João', matricula: '2002', sexo: 'M', setorId: 's2', jornada: '5x2-40', entrada: '09:00' });
  colaboradores.push({ id: 'p1', nome: 'Kátia', matricula: '3001', sexo: 'F', setorId: 's3', jornada: '12x36', entrada: '07:00' });
  colaboradores.push({ id: 'p2', nome: 'Luiz', matricula: '3002', sexo: 'M', setorId: 's3', jornada: '12x36', entrada: '19:00' });
  return Object.assign({ inicio: '2026-11-01', fim: '2026-12-31', setores, colaboradores, regras: {} }, over);
}

test('Páscoa e feriados móveis', () => {
  assert.strictEqual(M.pascoa(2026), '2026-04-05');
  assert.strictEqual(M.pascoa(2027), '2027-03-28');
  const f = M.feriadosNacionais(2026).map((x) => x.data);
  assert.ok(f.includes('2026-04-03')); // sexta da Paixão
  assert.ok(f.includes('2026-11-20')); // Consciência Negra
});

test('escala gerada não tem erros legais', () => {
  for (const [inicio, fim] of [['2026-11-01', '2026-12-31'], ['2026-10-14', '2027-03-09'], ['2027-01-01', '2027-01-31']]) {
    const cfg = cenario({ inicio, fim });
    const esc = M.gerarEscala(cfg);
    const erros = M.validarEscala(cfg, esc).filter((o) => o.nivel === 'erro');
    assert.deepStrictEqual(erros, [], `${inicio}..${fim}`);
  }
});

test('regra de domingos para homens a cada 7 semanas também é respeitada', () => {
  const cfg = cenario({ regras: { domingoHomensSemanas: 7 } });
  const esc = M.gerarEscala(cfg);
  assert.deepStrictEqual(M.validarEscala(cfg, esc).filter((o) => o.nivel === 'erro'), []);
});

test('mulheres folgam ao menos um domingo a cada 15 dias', () => {
  const cfg = cenario();
  const esc = M.gerarEscala(cfg);
  for (const c of cfg.colaboradores.filter((c) => c.sexo === 'F' && c.jornada !== '12x36')) {
    let seguidos = 0;
    esc.dias.forEach((d, i) => {
      if (d.dow !== 0) return;
      seguidos = esc.celulas[c.id][i].tipo === 'T' ? seguidos + 1 : 0;
      assert.ok(seguidos < 2, c.nome + ' ' + d.data);
    });
  }
});

test('setor fechado em fim de semana e feriado gera folgas', () => {
  const cfg = cenario();
  const esc = M.gerarEscala(cfg);
  const i = esc.dias.findIndex((d) => d.data === '2026-11-20');
  assert.strictEqual(esc.celulas.a1[i].tipo, 'FER');
  const sab = esc.dias.findIndex((d) => d.data === '2026-11-07');
  assert.strictEqual(esc.celulas.a1[sab].tipo, 'F');
});

test('validador detecta violações após edição manual', () => {
  const cfg = cenario();
  const esc = M.gerarEscala(cfg);
  esc.celulas.l0 = esc.celulas.l0.map((t) => (t.tipo === 'T' ? t : M.turnoTrabalho(cfg.colaboradores[0])));
  const regras = new Set(M.validarEscala(cfg, esc).filter((o) => o.colaboradorId === 'l0' && o.nivel === 'erro').map((o) => o.regra));
  assert.ok(regras.has('DSR'));
  assert.ok(regras.has('Domingo'));
  assert.ok(regras.has('Carga semanal'));
});

test('horas noturnas do plantão 19h-07h', () => {
  assert.strictEqual(M.minutosNoturnos(19 * 60, 31 * 60), 7 * 60);
  assert.strictEqual(M.minutosNoturnos(8 * 60, 17 * 60), 0);
});

test('opção: folga não coincide com feriado', () => {
  // dezembro/2026: Natal (25, sexta) e Confraternização (01/01) com o setor aberto
  const base = cenario({ inicio: '2026-12-01', fim: '2026-12-31' });
  const folgasEmFeriado = (cfg) => {
    const esc = M.gerarEscala(cfg);
    return cfg.colaboradores.filter((c) => c.setorId === 's1')
      .reduce((n, c) => n + esc.celulas[c.id].filter((t, i) => t.tipo === 'F' && esc.dias[i].feriado && esc.dias[i].dow !== 0).length, 0);
  };
  const cfg = { ...base, regras: { evitarFolgaFeriado: true } };
  assert.strictEqual(folgasEmFeriado(cfg), 0);
  const esc = M.gerarEscala(cfg);
  assert.deepStrictEqual(M.validarEscala(cfg, esc).filter((o) => o.nivel === 'erro'), []);
});

test('opção: limite de folgas seguidas', () => {
  for (const max of [1, 2, 3]) {
    const cfg = cenario({ inicio: '2026-10-14', fim: '2027-01-10', regras: { maxFolgasSeguidas: max } });
    const esc = M.gerarEscala(cfg);
    for (const c of cfg.colaboradores.filter((x) => x.setorId === 's1')) {
      let seq = 0;
      for (const t of esc.celulas[c.id]) {
        seq = t.tipo !== 'T' ? seq + 1 : 0;
        assert.ok(seq <= max, `${c.nome}: ${seq} folgas seguidas (limite ${max})`);
      }
    }
    assert.deepStrictEqual(M.validarEscala(cfg, esc).filter((o) => o.nivel === 'erro'), []);
  }
});

test('validador avisa folga em feriado e folgas seguidas acima do limite', () => {
  const cfg = cenario({ inicio: '2026-11-01', fim: '2026-11-30', regras: { evitarFolgaFeriado: true, maxFolgasSeguidas: 2 } });
  const esc = M.gerarEscala(cfg);
  const i20 = esc.dias.findIndex((d) => d.data === '2026-11-20');
  for (const k of [0, 1, 2]) esc.celulas.l0[i20 + k] = { tipo: 'F' };
  const regras = M.validarEscala(cfg, esc).filter((o) => o.colaboradorId === 'l0').map((o) => o.regra);
  assert.ok(regras.includes('Folga em feriado'));
  assert.ok(regras.includes('Folgas seguidas'));
});

test('semana incompleta no início do período não passa de 44h (5x2)', () => {
  const cfg = cenario({ inicio: '2026-12-01', fim: '2026-12-31' });
  cfg.colaboradores.push({ id: 'x', nome: 'X', matricula: '9', sexo: 'M', setorId: 's1', jornada: '5x2', entrada: '08:00' });
  const esc = M.gerarEscala(cfg);
  assert.deepStrictEqual(M.validarEscala(cfg, esc).filter((o) => o.nivel === 'erro'), []);
});
