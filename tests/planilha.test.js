const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const P = require('../js/planilha.js');
const CU = require('../js/custos-calculo.js');
const { abrirBanco } = require('../server/db.js');
const { criarServico } = require('../server/servico.js');

// planilhas fictícias no layout do relatório "Empregados em Excel" e "Centros de Custos" do sistema de folha
const arquivo = (nome) => fs.readFileSync(path.join(__dirname, 'dados', nome));

test('lê .xls (BIFF8) e .xlsx com o mesmo conteúdo', async () => {
  const xls = await P.ler(arquivo('empregados-teste.xls'));
  const xlsx = await P.ler(arquivo('empregados-teste.xlsx'));
  assert.deepStrictEqual(xls, xlsx);
  assert.strictEqual(xls.length, 4);
  assert.deepStrictEqual(xls[0].slice(0, 5), ['Cód Epr', 'Cód eSocial', 'Nome', 'Admissão', 'Salário']);
  assert.strictEqual(xls[1][2], 'FULANA DE TAL');
  assert.strictEqual(xls[3][8], 'APRENDIZAGEM');
  const cc = await P.ler(arquivo('centros-teste.xls'));
  assert.deepStrictEqual(cc[3].filter((v) => v != null), ['Código', 'Nome']);
  assert.deepStrictEqual(cc[4].filter((v) => v != null), [18, 'ADMINISTRAÇÃO DA PRODUÇÃO']);
});

test('CSV (ponto e vírgula, aspas, Windows-1252), datas e números da folha', async () => {
  const latin = Buffer.from('matricula;nome\n1;"JOÃO; DA SILVA"\n', 'latin1');
  assert.deepStrictEqual(await P.ler(latin), [['matricula', 'nome'], ['1', 'JOÃO; DA SILVA'], [null]]);
  assert.strictEqual(P.lerData('04/12/1965'), '1965-12-04');
  assert.strictEqual(P.lerData(46314.86), '2026-10-19');
  assert.strictEqual(P.lerData(''), '');
  assert.strictEqual(CU.lerNumero('7.265.69'), 7265.69);
  assert.strictEqual(CU.lerNumero('2390.970000'), 2390.97);
  assert.strictEqual(CU.lerNumero('2.390,97'), 2390.97);
});

test('centros de custo, importação de empregados e perfil do quadro', () => {
  const db = abrirBanco(':memory:');
  const s = criarServico(db, { paramsHash: { N: 1024, r: 8, p: 1 } });
  const A = { id: 'a', login: 'a', perfil: 'admin' };
  let r = s.importarCentrosCusto(A, [{ codigo: '18', nome: 'ADMINISTRAÇÃO DA PRODUÇÃO' }, { codigo: '2', nome: 'LOGISTICA' }, { codigo: '', nome: 'X' }]);
  assert.deepStrictEqual([r.novos, r.atualizados, r.ignorados.length], [2, 0, 1]);
  // linhas como a tela monta a partir da planilha (setor = departamento)
  const linha = {
    linha: 2, matricula: '3', codigoESocial: '3', nome: 'FULANA DE TAL', admissao: '1991-09-18', salario: '7.265.69', cargo: 'COORDENADORA',
    cbo: '141615', centroCustoCodigo: '2', centroCustoNome: 'LOGÍSTICA', estabelecimentoCodigo: '1', estabelecimento: 'EMPRESA TESTE',
    departamentoCodigo: '3', departamento: 'LOGISTICA', sindicatoCodigo: '203', sindicato: 'SINDICATO TESTE', nascimento: '1965-12-04',
    sexo: 'F', pcd: 'Não', setor: 'LOGISTICA',
  };
  r = s.importarColaboradores(A, [linha, { ...linha, linha: 3, matricula: '5990', nome: 'CICLANO', sexo: 'M', cargo: 'APRENDIZ', pcd: 'Sim',
    centroCustoCodigo: '17', centroCustoNome: 'APRENDIZAGEM', salario: '950.250000', nascimento: '2009-11-10', admissao: '2026-10-19' }]);
  assert.deepStrictEqual([r.importados, r.atualizados, r.centros], [2, 0, 2]); // CC 17 criado e CC 2 renomeado
  let d = s.dados(A);
  assert.deepStrictEqual(d.centrosCusto.map((c) => c.codigo), ['2', '17', '18']);
  assert.strictEqual(d.centrosCusto[0].nome, 'LOGÍSTICA');
  const fulana = d.colaboradores.find((c) => c.matricula === '3');
  assert.deepStrictEqual([fulana.salario, fulana.cbo, fulana.centroCustoCodigo, fulana.departamento, fulana.pcd], [7265.69, '141615', '2', 'LOGISTICA', false]);
  // perfil Consulta vê o centro de custo, mas não o salário
  const vista = s.dados({ id: 'c', login: 'c', perfil: 'consulta' }).colaboradores.find((c) => c.matricula === '3');
  assert.deepStrictEqual([vista.centroCustoCodigo, vista.salario, vista.nascimento], ['2', undefined, undefined]);

  // reimportação: atualiza só os grupos marcados
  r = s.importarColaboradores(A, [{ ...linha, salario: '8000', centroCustoCodigo: '18', centroCustoNome: 'ADMINISTRAÇÃO DA PRODUÇÃO', departamento: 'OUTRO' }],
    { cadastrar: true, atualizar: ['salario', 'centroCusto'] });
  assert.strictEqual(r.atualizados, 1);
  d = s.dados(A);
  const f2 = d.colaboradores.find((c) => c.matricula === '3');
  assert.deepStrictEqual([f2.salario, f2.centroCustoCodigo, f2.departamento], [8000, '18', 'LOGISTICA']);
  assert.throws(() => s.removerCentroCusto(A, '18'), /colaborador/);
  assert.throws(() => s.salvarColaborador(A, { ...f2, centroCustoCodigo: '999' }), /não cadastrado/);

  // perfil do quadro: cota de PcD só a partir de 100 empregados
  const q = CU.perfilQuadro({ ...d, lancamentos: [] }, '2026-10');
  assert.deepStrictEqual([q.geral.total, q.geral.pcd, q.geral.aprendizes], [2, 1, 1]);
  assert.strictEqual(q.cota.pct, 0);
  assert.deepStrictEqual(CU.cotaPcd(363), { pct: 3, exigidos: 11 });
  assert.deepStrictEqual(CU.cotaPcd(1001), { pct: 5, exigidos: 51 });
});
