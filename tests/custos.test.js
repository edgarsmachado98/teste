const test = require('node:test');
const assert = require('node:assert');
const CU = require('../js/custos-calculo.js');
const { abrirBanco } = require('../server/db.js');
const { criarServico } = require('../server/servico.js');
const { criarApp } = require('../server/server.js');

const SETOR = 's1';
const colab = (id, extras = {}) => ({ id, nome: id, matricula: id, setorId: SETOR, jornada: '6x1', ...extras });

test('custo mensal: horas extras com DSR, encargos, provisões e benefícios', () => {
  // setembro/2026: 30 dias, 4 domingos + 7/9 = 5 dias de descanso e 25 úteis
  const cal = CU.calendario('2026-09', ['2026-09-07']);
  assert.deepStrictEqual(cal, { dias: 30, uteis: 25, descanso: 5 });
  const r = CU.calcularLancamento({ salario: 2200, he50: 10, faltas: 2, vr: 500, saude: 300 }, { jornada: '6x1' }, {}, cal);
  assert.strictEqual(r.valorHora, 10);          // 2.200 ÷ 220
  assert.strictEqual(r.he50, 150);              // 10 h × 10 × 1,5
  assert.strictEqual(r.dsr, 30);                // 150 ÷ 25 × 5
  assert.strictEqual(r.descontos, 20);          // 2 h de falta
  assert.strictEqual(r.remuneracao, 2360);
  assert.strictEqual(r.inss, 472);              // 20%
  assert.strictEqual(r.rat, 47.2);              // 2% × FAP 1
  assert.strictEqual(r.terceiros, 136.88);      // 5,8%
  assert.strictEqual(r.fgts, 188.8);            // 8%
  assert.strictEqual(r.provFerias, 262.22);     // 2.360 ÷ 12 × 4/3
  assert.strictEqual(r.prov13, 196.67);         // 2.360 ÷ 12
  assert.strictEqual(r.beneficios, 800);
  assert.strictEqual(r.custoTotal, CU.centavos(r.remuneracao + r.encargos + r.provisoes + r.beneficios));
  // Simples Nacional: só FGTS
  const s = CU.calcularLancamento({ salario: 1000 }, { jornada: '6x1' }, { regime: 'simples' }, cal);
  assert.strictEqual(s.encargos, 80);
  // divisores por jornada
  assert.deepStrictEqual(['6x1', '5x2-40', '6x1-6h', '12x36'].map(CU.divisor), [220, 200, 180, 210]);
});

test('leitura de planilha de lançamentos (cabeçalhos com acento, horas em hh:mm, motivos)', () => {
  const r = CU.lerPlanilhaLancamentos('Matrícula;Nome;Salário;HE 50% (h);Atestado (dias);Motivo;Coluna estranha\n' +
    '10001;Ana;2.350,00;10:30;2;Gripe forte;x\n;sem matrícula;1;1;;;\n');
  assert.deepStrictEqual(r.colunas, ['salario', 'he50', 'atestadoDias', 'atestadoMotivo']);
  assert.deepStrictEqual(r.ignoradas, ['Coluna estranha']);
  assert.strictEqual(r.linhas.length, 1);
  assert.strictEqual(r.linhas[0].atestadoMotivo, 'respiratorio');
  assert.strictEqual(CU.lerNumero(r.linhas[0].he50), 10.5);
  assert.strictEqual(CU.lerNumero(r.linhas[0].salario), 2350);
  assert.throws(() => CU.lerPlanilhaLancamentos('nome;salario\nAna;10'), /matricula/);
});

test('avos de 13º e de férias (15 dias ou mais contam como mês)', () => {
  assert.strictEqual(CU.avos13Ate('2020-05-10', '2026-09'), 9);
  assert.strictEqual(CU.avos13Ate('2026-03-20', '2026-09'), 6); // março com 12 dias não conta
  assert.strictEqual(CU.avos13Ate('2026-03-10', '2026-09'), 7);
  assert.strictEqual(CU.avosEntre('2025-03-10', '2026-01-31'), 11);
  assert.strictEqual(CU.inicioAquisitivo({ admissao: '2020-09-14' }, '2026-09-30'), '2026-09-14');
});

test('provisões: férias vencidas em dobro e prazo de concessão', () => {
  const dados = {
    setores: [{ id: SETOR, nome: 'Vendas' }],
    colaboradores: [colab('a', { admissao: '2020-09-14', salario: 3000, feriasVencidas: 2 }), colab('b', { salario: 2000 })],
    lancamentos: [{ competencia: '2026-09', colaboradorId: 'a', salario: 3000 }],
  };
  const r = CU.provisoes(dados, '2026-09');
  assert.strictEqual(r.semAdmissao.length, 1);
  const a = r.colaboradores[0];
  assert.strictEqual(a.avos13, 9);
  assert.strictEqual(a.valor13, 2250);
  assert.strictEqual(a.avosFerias, 1); // 14/09 a 30/09 = 17 dias
  // 2 vencidas + 1 em dobro + 1/12 proporcional, com 1/3
  assert.strictEqual(a.valorFerias, CU.centavos(3000 * (3 + 1 / 12) * 4 / 3));
  assert.match(a.alertas.join(' '), /dobro/);
  assert.strictEqual(a.prazo, '2027-09-13');
});

test('turnover, sinistralidade, banco de horas e absenteísmo', () => {
  const dados = {
    setores: [{ id: SETOR, nome: 'Vendas' }],
    colaboradores: [
      colab('a', { admissao: '2020-01-01' }), colab('b', { admissao: '2020-01-01' }), colab('c', { admissao: '2020-01-01' }),
      colab('d', { admissao: '2020-01-01', desligamento: '2026-02-10', tipoDesligamento: 'pedido', motivoDesligamento: 'salario' }),
      colab('e', { admissao: '2026-02-01' }),
    ],
    competencias: [{ competencia: '2026-01', sinistrosSaude: 800, premioSaude: 1000 }, { competencia: '2026-02', sinistrosSaude: 600 }],
    lancamentos: [
      { competencia: '2026-01', colaboradorId: 'a', salario: 2200, saude: 500, bhCredito: 50, bhDebito: 5, faltas: 7.33 },
      { competencia: '2026-02', colaboradorId: 'a', salario: 2200, saude: 500, atestadoDias: 20, atestadoMotivo: 'mental' },
    ],
  };
  const t = CU.turnover(dados, '2026-02', '2026-02');
  assert.deepStrictEqual([t.meses[0].hcInicio, t.meses[0].hcFim, t.admissoes, t.desligamentos, t.voluntario], [4, 4, 1, 1, 1]);
  assert.strictEqual(t.taxa, 25);                    // ((1 + 1) ÷ 2) ÷ 4
  assert.strictEqual(t.motivos[0].id, 'salario');
  const s = CU.sinistralidade(dados, '2026-01', '2026-02');
  assert.strictEqual(s.meses[0].indice, 80);
  assert.strictEqual(s.meses[1].premio, 500);        // sem fatura: soma dos lançamentos
  assert.strictEqual(s.meses[1].indice, 120);
  assert.strictEqual(s.acumulado12, 1400 / 1500 * 100);
  assert.strictEqual(s.situacao, 'critica');
  const bh = CU.bancoHoras(dados, '2026-02');
  assert.strictEqual(bh.colaboradores[0].saldo, 45);
  assert.strictEqual(bh.colaboradores[0].alto, true);
  assert.strictEqual(bh.passivo, CU.centavos(45 * 10 * 1.5));
  const med = CU.absenteismoMedico(dados, '2026-01', '2026-02');
  assert.strictEqual(med.afastamentos.length, 1);
  assert.strictEqual(med.motivos[0].id, 'mental');
  const ab = CU.absenteismoGeral(dados, '2026-01', '2026-02');
  assert.strictEqual(ab.total.faltas, 7.33);
  assert.ok(ab.total.taxa > 0);
});

// ------------------------------------------------------------ servidor

function servico() {
  const db = abrirBanco(':memory:');
  return { db, s: criarServico(db, { paramsHash: { N: 1024, r: 8, p: 1 }, agora: () => Date.parse('2026-10-19T12:00:00Z') }) };
}
const ADMIN = { id: 'adm', login: 'adm', perfil: 'admin' };
const CONSULTA = { id: 'c', login: 'c', perfil: 'consulta' };

test('competência, lançamentos, importação, desligamento e permissões', () => {
  const { s } = servico();
  const setor = s.salvarSetor(ADMIN, { nome: 'Vendas', minimoPorDia: 0, diasFuncionamento: [true, true, true, true, true, true, true] });
  const base = { sexo: 'F', setorId: setor.id, jornada: '6x1', entrada: '08:00' };
  const ana = s.salvarColaborador(ADMIN, { ...base, nome: 'Ana', matricula: '1', salario: '2.200,00', admissao: '2024-01-10', beneficios: { vr: '500' } });
  const bia = s.salvarColaborador(ADMIN, { ...base, nome: 'Bia', matricula: '2', salario: 3000, admissao: '2026-10-25' });
  assert.strictEqual(ana.salario, 2200);
  assert.strictEqual(ana.beneficios.vr, 500);

  // perfil Consulta não vê salários nem acessa os custos
  const visto = s.dados(CONSULTA).colaboradores.find((c) => c.id === ana.id);
  assert.strictEqual(visto.salario, undefined);
  assert.strictEqual(visto.beneficios, undefined);
  assert.throws(() => s.custos(CONSULTA), (e) => e.status === 403);

  // setembro: só Ana tinha vínculo (Bia é admitida em outubro)
  let c = s.abrirCompetencia(ADMIN, '2026-09');
  assert.strictEqual(c.lancamentos.length, 1);
  assert.strictEqual(c.lancamentos[0].salario, 2200);
  assert.strictEqual(c.lancamentos[0].vr, 500);
  c = s.abrirCompetencia(ADMIN, '2026-10');
  assert.strictEqual(c.lancamentos.filter((l) => l.competencia === '2026-10').length, 2);

  c = s.salvarFolha(ADMIN, '2026-09', { premioSaude: '', sinistrosSaude: '1.234,50', lancamentos: [{ colaboradorId: ana.id, salario: '2.200,00', he50: '10,5', atestadoDias: 2 }] });
  const l = c.lancamentos.find((x) => x.competencia === '2026-09');
  assert.strictEqual(l.he50, 10.5);
  assert.strictEqual(l.atestadoMotivo, 'outros');
  assert.strictEqual(c.competencias[0].sinistrosSaude, 1234.5);
  assert.throws(() => s.salvarFolha(ADMIN, '2026-09', { lancamentos: [{ colaboradorId: ana.id, he50: 'abc' }] }), /HE 50%/);
  assert.throws(() => s.salvarFolha(ADMIN, '2026-08', { lancamentos: [] }), (e) => e.status === 404);

  // importação altera só as colunas informadas
  const r = s.importarFolha(ADMIN, '2026-09', [{ linha: 2, matricula: '1', faltas: '7,33' }, { linha: 3, matricula: '999', he50: 1 }]);
  assert.strictEqual(r.importados, 1);
  assert.match(r.ignorados[0], /999/);
  const li = r.lancamentos.find((x) => x.competencia === '2026-09');
  assert.deepStrictEqual([li.he50, li.faltas, li.salario], [10.5, 7.33, 2200]);

  // quem tem lançamentos não pode ser excluído; o desligamento exige o tipo
  assert.throws(() => s.removerColaborador(ADMIN, ana.id), (e) => e.status === 409);
  assert.throws(() => s.salvarColaborador(ADMIN, { ...ana, id: ana.id, desligamento: '2026-10-15' }), /tipo de desligamento/);
  s.salvarColaborador(ADMIN, { ...ana, id: ana.id, desligamento: '2026-10-15', tipoDesligamento: 'pedido', motivoDesligamento: 'salario' });

  // desligados antes do período não entram na escala
  const e = s.gerarEscala(ADMIN, { inicio: '2026-11-01', fim: '2026-11-30' });
  assert.deepStrictEqual(Object.keys(e.celulas), [bia.id]);

  // parâmetros
  assert.throws(() => s.salvarParametrosCustos(ADMIN, { ...CU.PARAMETROS_PADRAO, fap: 3 }), /FAP/);
  const p = s.salvarParametrosCustos(ADMIN, { ...CU.PARAMETROS_PADRAO, fap: '1,5' });
  assert.strictEqual(p.fap, 1.5);

  // backup e restauração mantêm a folha e os dados contratuais
  const b = JSON.parse(JSON.stringify(s.backup(ADMIN)));
  assert.strictEqual(b.versao, 5);
  s.restaurar(ADMIN, b);
  const depois = s.custos(ADMIN);
  assert.strictEqual(depois.lancamentos.length, 3);
  assert.strictEqual(depois.parametros.fap, 1.5);
  assert.strictEqual(depois.competencias.find((x) => x.competencia === '2026-09').sinistrosSaude, 1234.5);
  const anaRestaurada = s.dados(ADMIN).colaboradores.find((x) => x.matricula === '1');
  assert.strictEqual(anaRestaurada.desligamento, '2026-10-15');
  assert.strictEqual(depois.lancamentos.find((x) => x.competencia === '2026-09').colaboradorId, anaRestaurada.id);

  s.removerCompetencia(ADMIN, '2026-10');
  assert.strictEqual(s.custos(ADMIN).competencias.length, 1);
});

test('importação de colaboradores atualiza cargo, salário e admissão de matrículas já cadastradas', () => {
  const { s } = servico();
  const setor = s.salvarSetor(ADMIN, { nome: 'Vendas', minimoPorDia: 0, diasFuncionamento: [true, true, true, true, true, true, true] });
  s.salvarColaborador(ADMIN, { nome: 'Ana', matricula: '1', sexo: 'F', setorId: setor.id, jornada: '5x2', entrada: '09:00', cargo: 'Vendedora', salario: 2000 });
  const r = s.importarColaboradores(ADMIN, [
    { linha: 2, matricula: '1', cargo: '', salario: '2.450,00', admissao: '2021-03-08' },
    { linha: 3, matricula: '2', nome: 'Bia', sexo: 'F', setor: 'Vendas', salario: '1.900,00' },
    { linha: 4, matricula: '1' },
    { linha: 5, matricula: '1', salario: 'abc' },
  ]);
  assert.deepStrictEqual([r.importados, r.atualizados, r.ignorados.length], [1, 1, 2]);
  assert.match(r.ignorados[0], /linha 4.*sem dados para atualizar/);
  assert.match(r.ignorados[1], /linha 5.*Salário/);
  const ana = s.dados(ADMIN).colaboradores.find((c) => c.matricula === '1');
  // só os campos informados mudam; jornada, horário e cargo vazio ficam como estavam
  assert.deepStrictEqual([ana.salario, ana.admissao, ana.cargo, ana.jornada, ana.entrada], [2450, '2021-03-08', 'Vendedora', '5x2', '09:00']);

  // opções da caixa de diálogo: só atualizar (sem cadastrar) e escolher os campos, inclusive setor
  const r2 = s.importarColaboradores(ADMIN, [
    { linha: 2, matricula: '1', nome: 'Ana Lima', setor: 'Logística', salario: '9.999,00' },
    { linha: 3, matricula: '3', nome: 'Caio', sexo: 'M', setor: 'Vendas' },
  ], { cadastrar: false, atualizar: ['nome', 'setor'] });
  assert.deepStrictEqual([r2.importados, r2.atualizados], [0, 1]);
  assert.match(r2.ignorados[0], /linha 3.*não cadastrada/);
  const d = s.dados(ADMIN);
  const ana2 = d.colaboradores.find((c) => c.matricula === '1');
  assert.deepStrictEqual([ana2.nome, d.setores.find((x) => x.id === ana2.setorId).nome, ana2.salario], ['Ana Lima', 'Logística', 2450]);
  // nada a atualizar: matrícula existente é ignorada
  const r3 = s.importarColaboradores(ADMIN, [{ linha: 2, matricula: '1', salario: 1 }], { atualizar: [] });
  assert.match(r3.ignorados[0], /já cadastrada/);
});

test('exemplo traz seis meses de folha e os relatórios funcionam com ele', () => {
  const { s } = servico();
  s.carregarExemplo(ADMIN);
  const c = s.custos(ADMIN);
  const d = s.dados(ADMIN);
  assert.deepStrictEqual(c.competencias.map((x) => x.competencia), ['2026-04', '2026-05', '2026-06', '2026-07', '2026-08', '2026-09']);
  const dados = { ...c, colaboradores: d.colaboradores, setores: d.setores, feriados: [] };
  const t = CU.turnover(dados, '2026-04', '2026-09');
  assert.deepStrictEqual([t.admissoes, t.desligamentos, t.voluntario, t.involuntario], [2, 3, 1, 2]);
  assert.ok(CU.custoColaborador(dados, '2026-04', '2026-09').total.custoTotal > 0);
  assert.ok(CU.provisoes(dados, '2026-09').colaboradores.some((x) => x.vencidas === 2));
  assert.strictEqual(CU.sinistralidade(dados, '2026-04', '2026-09').situacao, 'atencao');
  assert.ok(CU.bancoHoras(dados, '2026-09').acimaDoLimite >= 1);
});

test('rotas HTTP dos custos exigem perfil Operador', async (t) => {
  const db = abrirBanco(':memory:');
  const s = criarServico(db, { paramsHash: { N: 1024, r: 8, p: 1 } });
  const app = criarApp({ servico: s, limiteLogin: () => true });
  await new Promise((r) => app.listen(0, '127.0.0.1', r));
  t.after(() => app.close());
  const base = `http://127.0.0.1:${app.address().port}`;
  const h = { 'X-Requested-With': 'escala', 'Content-Type': 'application/json' };
  let r = await fetch(`${base}/api/primeiro-acesso`, { method: 'POST', headers: h, body: JSON.stringify({ nome: 'Adm', login: 'adm', senha: 'Gestora2026' }) });
  const cookie = r.headers.get('set-cookie').split(';')[0];
  r = await fetch(`${base}/api/custos`, { headers: { ...h, Cookie: cookie } });
  assert.strictEqual(r.status, 200);
  assert.deepStrictEqual((await r.json()).lancamentos, []);
  r = await fetch(`${base}/api/folha/2026-13/abrir`, { method: 'POST', headers: { ...h, Cookie: cookie }, body: '{}' });
  assert.strictEqual(r.status, 400);
  r = await fetch(`${base}/api/custos`, { headers: h });
  assert.strictEqual(r.status, 401);
});
