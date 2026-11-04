const test = require('node:test');
const assert = require('node:assert');
const K = require('../js/distrato-calculo.js');
const M = require('../js/distrato-modelo.js');
const C = require('../js/contrato-modelo.js');
const IGPM = require('./dados/igpm-teste.js');
const { abrirBanco } = require('../server/db.js');
const { criarServico } = require('../server/servico.js');
const { criarApp } = require('../server/server.js');

// dados da planilha "Cálculo de Comissões" (saída em 11/02/2026)
const CIA = [['2023-10', 650], ['2024-01', 699.2], ['2024-02', 174.8], ['2024-05', 125.02], ['2024-06', 500.06],
  ['2024-09', 645.66], ['2024-10', 161.42], ['2025-04', 665.6], ['2025-05', 166.4]].map(([mes, valor]) => ({ mes, valor }));
const ALIM = [2159.95, 3964.98, 5289.58, 7308.53, 6583.54, 6501.29, 6187.06, 5618.92, 6211.03, 5083.18, 4999.70, 5886.09,
  4533.65, 3825.01, 5213.89, 3820.31, 4299.18, 4607.51, 3837.64, 3503.64, 3544.87, 3226.14, 3432.85, 3827.85, 3259.99,
  3293.49, 3701.47, 3674.65, 4790.08, 2840.98, 3111.93, 3546.49, 2930.29].map((valor, i) => ({ mes: K.somarMes('2023-06', i), valor }));

const CONTRATO = {
  razao: 'Francisco Matrone Siqueira', cnpj: '29356095000162', fantasia: 'Matrone Representações Comerciais',
  endereco: 'Rua Clemente Ferreira, 333', bairro: 'Centro', cidade: 'Bragança Paulista', uf: 'SP', cep: '12900050',
  responsavel: 'Francisco Matrone Siqueira', sexo: 'M', nacionalidade: 'brasileiro', nascimento: '1991-12-27',
  rg: '47959714', rgOrgao: 'SSP SP', cpf: '36087274855', mesmoEndereco: true, zona: 'Bragança Paulista e região',
  dataContrato: '2023-03-08',
};

test('atualização pelo IGP-M reproduz a planilha (mês da comissão até o mês anterior ao distrato)', () => {
  const r = K.calcular({ dataDistrato: '2026-02-11', comissoes: CIA }, IGPM);
  assert.deepStrictEqual(r.linhas.map((l) => l.atualizado),
    [700.75, 740.16, 184.91, 133.16, 527.91, 670.10, 166.50, 665.60, 166.40]);
  assert.strictEqual(r.somaAtualizada, 3955.49);
  assert.strictEqual(r.indenizacao, 329.62);
  assert.strictEqual(r.avisoPrevio, 332.83); // média das 3 últimas comissões (out/24, abr/25, mai/25)
  assert.deepStrictEqual(r.mesesAviso, ['2024-10', '2025-04', '2025-05']);
  assert.strictEqual(r.total, 662.45);
  assert.deepStrictEqual(r.indicesFaltando, []);
});

test('Antoniazzi Alimentos: indenização inclui a receber e títulos pendentes', () => {
  const r = K.calcular({ dataDistrato: '2026-02-11', comissoes: ALIM, aReceber: { valor: '514,46' }, pendentes: { valor: '3.547,55' } }, IGPM);
  assert.strictEqual(r.avisoPrevio, 3205.23);
  const dez23 = r.linhas.find((l) => l.mes === '2023-12');
  assert.strictEqual(dez23.atualizado, 6597.97); // a planilha traz 5.992,10, valor inconsistente com o IGP-M
  // com o valor da planilha em dez/2023, a base e a indenização ficam idênticas às do documento
  assert.strictEqual(K.centavos(r.baseIndenizacao - dez23.atualizado + 5992.10), 153781.46);
  assert.strictEqual(K.centavos((r.baseIndenizacao - dez23.atualizado + 5992.10) / 12), 12815.12);
  assert.strictEqual(r.total, K.centavos(r.avisoPrevio + r.indenizacao + 514.46 + 3547.55));
});

test('deflação, opções e índices faltando', () => {
  const base = { dataDistrato: '2026-02-11', comissoes: [{ mes: '2025-06', valor: 1000 }] };
  assert.strictEqual(K.calcular(base, IGPM).linhas[0].atualizado, 1000); // acumulado negativo: mantém
  assert.strictEqual(K.calcular({ ...base, desconsiderarDeflacao: false }, IGPM).linhas[0].atualizado, 986.39);
  const r = K.calcular({ ...base, pagarAviso: false, pagarIndenizacao: false }, IGPM);
  assert.strictEqual(r.total, 0);
  assert.deepStrictEqual(K.calcular({ dataDistrato: '2026-05-10', comissoes: base.comissoes }, IGPM).indicesFaltando,
    ['2026-02', '2026-03', '2026-04']);
  assert.strictEqual(K.lerValor('R$ 3.547,55'), 3547.55);
  assert.strictEqual(K.lerValor('1234.5'), 1234.5);
  assert.strictEqual(K.lerValor(''), null);
});

test('valor por extenso', () => {
  assert.strictEqual(K.porExtenso(662.46), 'Seiscentos e sessenta e dois reais e quarenta e seis centavos');
  assert.strictEqual(K.porExtenso(20082.37), 'Vinte mil e oitenta e dois reais e trinta e sete centavos');
  assert.strictEqual(K.porExtenso(1), 'Um real');
  assert.strictEqual(K.porExtenso(1500), 'Mil e quinhentos reais');
  assert.strictEqual(K.porExtenso(1234567.01), 'Um milhão duzentos e trinta e quatro mil quinhentos e sessenta e sete reais e um centavo');
  assert.strictEqual(K.porExtenso(2000000), 'Dois milhões de reais');
  assert.strictEqual(K.porExtenso(0.45), 'Quarenta e cinco centavos');
});

test('termo de distrato e aviso prévio com os dados do representante e do cálculo', () => {
  const d = { representada: 'alimentos', dataInicio: '2023-03-08', dataDistrato: '2026-02-11', profissao: 'empresário',
    naturalidade: 'Bragança Paulista SP', comissoes: ALIM, aReceber: { inicio: '2026-02-01', fim: '2026-02-11', valor: 514.46 },
    pendentes: { inicio: '2026-01-22', fim: '2026-05-12', valor: 3547.55 } };
  const r = K.calcular(d, IGPM);
  const vals = M.valores(CONTRATO, d, r);
  const docs = M.montar(CONTRATO, d, r);
  assert.deepStrictEqual(docs.map((x) => x.id), ['distrato', 'aviso']);
  assert.strictEqual(docs[0].cabecalho, 'antoniazzi');
  const texto = (doc, v = vals) => doc.blocos.map((b) => [b[1]].flat().filter((x) => typeof x === 'string').join(' '))
    .map((t) => C.trechos(t, v).map((x) => x.texto).join('')).join('\n');
  const t = texto(docs[0]);
  assert.ok(t.includes('ANTONIAZZI INDUSTRIA E COMERCIO DE ALIMENTOS LTDA.'));
  assert.ok(t.includes('representada neste por FRANCISCO MATRONE SIQUEIRA, brasileiro, empresário, nascido em 27/12/1991, natural de Bragança Paulista SP'));
  assert.ok(t.includes('desde 08 de março de 2023'));
  assert.ok(t.includes(`R$ ${K.moeda(r.total)} (${r.totalExtenso}).`));
  assert.ok(t.includes('- Ref. Aviso prévio: R$ 3.205,23'));
  assert.ok(t.includes('- Comissões a receber de 01/02/2026 a 11/02/2026: R$ 514,46'));
  assert.ok(t.includes('- Comissões sobre títulos pendentes de 22/01/2026 a 12/05/2026: R$ 3.547,55'));
  assert.ok(t.includes('Canoas/RS, 11 de fevereiro de 2026.'));
  assert.ok(!/⟦|\[[a-z ]+\]/.test(t));
  const a = texto(docs[1]);
  assert.ok(a.includes('CONTRATANTE: ANTONIAZZI IND E COM. DE ALIMENTOS LTDA'));
  assert.ok(a.includes('Santa Maria, 11 de fevereiro de 2026.'));
  // Antoniazzi & Cia: sem linhas de comissões a receber/pendentes quando zeradas
  const dc = { ...d, representada: 'cia', comissoes: CIA, aReceber: {}, pendentes: {}, estadoCivil: 'casado' };
  const rc = K.calcular(dc, IGPM);
  const tc = texto(M.montar(CONTRATO, dc, rc)[0], M.valores(CONTRATO, dc, rc));
  assert.ok(tc.includes('R$ 662,45 (Seiscentos e sessenta e dois reais e quarenta e cinco centavos).'));
  assert.ok(!tc.includes('Comissões a receber'));
  assert.ok(tc.includes('brasileiro, empresário, casado, nascido'));
  assert.ok(tc.includes('Santa Maria/RS, 11 de fevereiro de 2026.'));
});

test('API: índices do Banco Central, distrato, permissões e backup', async (t) => {
  // Banco Central simulado: devolve a série no formato da API SGS
  let chamadas = 0;
  const buscar = async (url) => {
    chamadas++;
    assert.match(url, /bcdata\.sgs\.189\/dados\?formato=json/);
    const lista = Object.entries(IGPM).map(([mes, v]) => ({ data: `01/${mes.slice(5)}/${mes.slice(0, 4)}`, valor: String(v) }));
    return { ok: true, status: 200, json: async () => lista };
  };
  const db = abrirBanco(':memory:');
  const app = criarApp({ servico: criarServico(db, { paramsHash: { N: 1024, r: 8, p: 1 }, buscar }), limiteLogin: () => true });
  await new Promise((r) => app.listen(0, '127.0.0.1', r));
  t.after(() => app.close());
  const base = `http://127.0.0.1:${app.address().port}`;
  const cliente = () => {
    let cookie = '';
    return async (metodo, caminho, corpo) => {
      const r = await fetch(base + caminho, { method: metodo, body: corpo === undefined ? undefined : JSON.stringify(corpo),
        headers: { 'X-Requested-With': 'escala', 'Content-Type': 'application/json', ...(cookie ? { Cookie: cookie } : {}) } });
      if (r.headers.get('set-cookie')) cookie = r.headers.get('set-cookie').split(';')[0];
      return { status: r.status, dados: await r.json().catch(() => null) };
    };
  };
  const adm = cliente();
  await adm('POST', '/api/primeiro-acesso', { nome: 'Maria', login: 'maria', senha: 'Gestora2026' });
  await adm('POST', '/api/usuarios', { nome: 'Ana', login: 'ana', senha: 'Consulta123', perfil: 'consulta' });

  let r = await adm('POST', '/api/indices/igpm/atualizar');
  assert.strictEqual(r.status, 200);
  assert.strictEqual(chamadas, 1);
  assert.strictEqual(r.dados.meses['2025-06'], -1.67);
  assert.strictEqual(r.dados.ultimoMes, '2026-01');
  r = await adm('PUT', '/api/indices/igpm/2026-02', { valor: '0,52' });
  assert.strictEqual(r.dados.meses['2026-02'], 0.52);
  assert.deepStrictEqual(r.dados.manuais, ['2026-02']);
  assert.strictEqual((await adm('PUT', '/api/indices/igpm/2026-13', { valor: '1' })).status, 400);
  await adm('DELETE', '/api/indices/igpm/2026-02');

  const ct = (await adm('POST', '/api/contratos', CONTRATO)).dados;
  const distrato = { contratoId: ct.id, representada: 'cia', dataInicio: '2023-03-08', dataDistrato: '2026-02-11', comissoes: CIA };
  r = await adm('POST', '/api/distratos', distrato);
  assert.strictEqual(r.status, 200, JSON.stringify(r.dados));
  assert.strictEqual(r.dados.resultado.total, 662.45);
  assert.strictEqual(r.dados.razao, 'Francisco Matrone Siqueira');
  const id = r.dados.id;
  assert.strictEqual((await adm('POST', '/api/distratos', distrato)).status, 409); // um por contrato e empresa
  assert.strictEqual((await adm('POST', '/api/distratos', { ...distrato, representada: 'alimentos' })).status, 200);
  assert.strictEqual((await adm('POST', '/api/distratos', { ...distrato, representada: 'x' })).status, 400);
  assert.strictEqual((await adm('POST', '/api/distratos', { ...distrato, pendentes: { valor: '100' } })).status, 400); // sem período
  r = await adm('PUT', `/api/distratos/${id}`, { ...distrato, pagarAviso: false });
  assert.strictEqual(r.dados.resultado.total, 329.62);

  // contrato com distrato não pode ser excluído
  assert.strictEqual((await adm('DELETE', `/api/contratos/${ct.id}`)).status, 409);

  const ana = cliente();
  await ana('POST', '/api/login', { login: 'ana', senha: 'Consulta123' });
  assert.strictEqual((await ana('GET', '/api/distratos')).dados.length, 2);
  assert.strictEqual((await ana('GET', '/api/indices/igpm')).status, 200);
  assert.strictEqual((await ana('POST', '/api/indices/igpm/atualizar')).status, 403);
  assert.strictEqual((await ana('POST', '/api/distratos', distrato)).status, 403);
  assert.strictEqual((await ana('POST', `/api/distratos/${id}/documento`, { formato: 'docx' })).status, 200);

  // backup e restauração mantêm distratos ligados aos contratos
  const b = (await adm('GET', '/api/backup')).dados;
  assert.strictEqual(b.distratos.length, 2);
  assert.ok(b.indices.length >= 30);
  assert.strictEqual((await adm('POST', '/api/restaurar', b)).status, 200);
  const depois = (await adm('GET', '/api/distratos')).dados;
  assert.strictEqual(depois.length, 2);
  assert.ok(depois.every((x) => x.razao === 'Francisco Matrone Siqueira'));

  // Banco Central indisponível: mensagem clara
  const app2 = criarApp({ servico: criarServico(abrirBanco(':memory:'), { paramsHash: { N: 1024, r: 8, p: 1 },
    buscar: async () => { throw new Error('getaddrinfo ENOTFOUND api.bcb.gov.br'); } }), limiteLogin: () => true });
  await new Promise((res) => app2.listen(0, '127.0.0.1', res));
  t.after(() => app2.close());
  const base2 = `http://127.0.0.1:${app2.address().port}`;
  const r1 = await fetch(base2 + '/api/primeiro-acesso', { method: 'POST', headers: { 'X-Requested-With': 'escala', 'Content-Type': 'application/json' },
    body: JSON.stringify({ nome: 'X', login: 'xadm', senha: 'Senha12345' }) });
  const ck = r1.headers.get('set-cookie').split(';')[0];
  const r2 = await fetch(base2 + '/api/indices/igpm/atualizar', { method: 'POST', headers: { 'X-Requested-With': 'escala', Cookie: ck } });
  assert.strictEqual(r2.status, 502);
  assert.match((await r2.json()).erro, /Banco Central.*manualmente/);

  const hist = (await adm('GET', '/api/auditoria')).dados.map((a) => a.acao);
  for (const a of ['indice.atualizar', 'indice.manual', 'distrato.criar', 'distrato.alterar', 'distrato.documento']) assert.ok(hist.includes(a), a);
});

test('comissões depois do mês do distrato não entram no cálculo', () => {
  const r = K.calcular({ dataDistrato: '2026-02-11', comissoes: [...CIA, { mes: '2026-06', valor: 999 }] }, IGPM);
  assert.deepStrictEqual(r.foraDoPeriodo, ['2026-06']);
  assert.strictEqual(r.total, 662.45);
});

test('memória de cálculo: HTML e planilha Excel com fórmulas que fecham com o cálculo', async () => {
  const MEM = require('../js/distrato-memoria.js');
  const P = require('../js/planilha.js');
  const d = {
    dataInicio: '2023-03-08', dataDistrato: '2026-02-11', comissoes: CIA,
    aReceber: { inicio: '2026-01-01', fim: '2026-02-11', valor: 120.5 }, pendentes: { inicio: '2025-12-01', fim: '2026-02-11', valor: 80 },
  };
  const r = K.calcular(d, IGPM);
  const m = MEM.montar({ razao: CONTRATO.razao, cnpj: C.formatarCNPJ(CONTRATO.cnpj) }, d, r, IGPM, { nome: 'Antoniazzi & Cia Ltda', cnpj: '95.597.647/0001-59' });
  const html = MEM.html(m);
  assert.match(html, /Memória de cálculo do distrato/);
  assert.ok(html.includes(K.moeda(r.total)));
  assert.ok(html.includes('out/2023'));
  assert.strictEqual((html.match(/class="mc-aviso"/g) || []).length, 3);

  const bytes = MEM.xlsx(m);
  const linhas = await P.ler(bytes);
  const achar = (rotulo) => linhas.find((l) => l[0] === rotulo);
  assert.strictEqual(linhas[0][0], 'Memória de cálculo do distrato');
  assert.strictEqual(achar('out/2023')[5], 700.75);
  assert.strictEqual(achar(`Total (${r.linhas.length} meses)`)[5], r.somaAtualizada);
  assert.strictEqual(achar('Total a pagar')[5], r.total);
  assert.strictEqual(achar('Indenização (1/12)')[5], r.indenizacao);
  assert.strictEqual(achar('Aviso prévio')[5], r.avisoPrevio);
  // as fórmulas estão na planilha (para a conferência no Excel)
  const zipTexto = Buffer.from(bytes).toString('latin1');
  assert.ok(zipTexto.includes('ROUND(F') && zipTexto.includes('SUM(F'));
});

test('não optante do Simples: IR de 1,5% sobre aviso, a receber e pendentes e de 15% sobre a indenização', async () => {
  // valores do distrato de exemplo enviado pela empresa (out/2026)
  const d = {
    dataInicio: '2026-06-15', dataDistrato: '2026-10-16', comissoes: [{ mes: '2026-10', valor: 312.61 }],
    aReceber: { inicio: '2026-10-01', fim: '2026-10-16', valor: 175.82 }, pendentes: { inicio: '2026-09-20', fim: '2027-01-16', valor: 255.55 },
  };
  const semIR = K.calcular({ ...d, simples: { situacao: 'optante' } }, {});
  assert.deepStrictEqual([semIR.total, semIR.reterIR, semIR.ir.total, semIR.liquido], [597.57, false, 0, 597.57]);
  const r = K.calcular({ ...d, simples: { situacao: 'nao_optante' } }, {});
  assert.deepStrictEqual([r.indenizacao, r.avisoPrevio], [62.00, 104.20]);
  assert.deepStrictEqual(r.ir, { aviso: 1.56, aReceber: 2.64, pendentes: 3.83, indenizacao: 9.30, comissoes: 8.03, total: 17.33 });
  assert.strictEqual(r.liquido, 580.24);
  assert.strictEqual(r.liquidoExtenso, 'Quinhentos e oitenta reais e vinte e quatro centavos');

  // cláusula segunda: quantia líquida, parcelas brutas e o IR retido
  const contrato = { ...CONTRATO, cnpj: C.formatarCNPJ(CONTRATO.cnpj) };
  const dd = { ...d, representada: 'alimentos', simples: { situacao: 'nao_optante' }, documentos: ['distrato'] };
  const doc = M.montar(contrato, dd, r)[0];
  const vals = M.valores(contrato, dd, r);
  const texto = doc.blocos.filter((b) => b[0] === 'p').map((b) => C.trechos(b[1], vals).map((t) => t.texto).join('')).join('\n');
  assert.match(texto, /R\$ 580,24 \(Quinhentos e oitenta reais e vinte e quatro centavos\)/);
  assert.match(texto, /Valor bruto: R\$ 597,57/);
  assert.match(texto, /IRRF de 1,5% .*base R\$ 535,57\): R\$ 8,03/);
  assert.match(texto, /IRRF de 15% .*base R\$ 62,00\): R\$ 9,30/);
  assert.match(texto, /Valor líquido: R\$ 580,24/);

  // memória de cálculo com a seção de IR
  const MEM = require('../js/distrato-memoria.js');
  const P = require('../js/planilha.js');
  const m = MEM.montar(contrato, dd, r, {}, { nome: 'Antoniazzi Alimentos', cnpj: '11.780.083/0001-03' });
  assert.match(MEM.html(m), /Valor líquido a pagar<\/th><th class="num">580,24/);
  const linhas = await P.ler(MEM.xlsx(m));
  assert.strictEqual(linhas.find((l) => l[0] === 'Total do IR retido')[5], 17.33);
  assert.strictEqual(linhas.find((l) => l[0] === 'Valor líquido a pagar')[5], 580.24);
});

test('consulta do Simples Nacional pelos dados abertos da Receita (BrasilAPI e alternativa)', async () => {
  const respostas = [];
  const buscar = async (url) => {
    const r = respostas.shift();
    if (r instanceof Error) throw r;
    return { ok: r.status === 200, status: r.status, json: async () => r.corpo, url };
  };
  const db = abrirBanco(':memory:');
  const s = criarServico(db, { paramsHash: { N: 1024, r: 8, p: 1 }, buscar });
  const A = { id: 'a', login: 'a', perfil: 'admin' };
  respostas.push({ status: 200, corpo: { razao_social: 'X LTDA', descricao_situacao_cadastral: 'ATIVA', opcao_pelo_simples: false,
    data_opcao_pelo_simples: '2015-01-01', data_exclusao_do_simples: '2020-12-31', opcao_pelo_mei: false } });
  let r = await s.consultarSimples(A, '29.356.095/0001-62');
  assert.deepStrictEqual([r.optante, r.dataExclusao, r.situacaoCadastral, r.cnpj], [false, '2020-12-31', 'ATIVA', '29.356.095/0001-62']);
  // BrasilAPI fora do ar: usa a ReceitaWS
  respostas.push(new Error('timeout'), { status: 200, corpo: { nome: 'X LTDA', situacao: 'ATIVA', simples: { optante: true, data_opcao: '01/07/2007' } } });
  r = await s.consultarSimples(A, '29356095000162');
  assert.deepStrictEqual([r.optante, r.dataOpcao, r.fonte], [true, '2007-07-01', 'ReceitaWS (dados da Receita Federal)']);
  respostas.push(new Error('a'), new Error('b'));
  await assert.rejects(s.consultarSimples(A, '29356095000162'), (e) => e.status === 502 && /Consulta Optantes/.test(e.message));
  respostas.push({ status: 404, corpo: {} });
  await assert.rejects(s.consultarSimples(A, '29356095000162'), (e) => e.status === 404);
  await assert.rejects(s.consultarSimples(A, '11111111111111'), /CNPJ inválido/);
  await assert.rejects(s.consultarSimples({ id: 'c', login: 'c', perfil: 'consulta' }, '29356095000162'), (e) => e.status === 403);
});

test('salvar o distrato encerra o contrato do representante; excluir o último distrato reativa', () => {
  const db = abrirBanco(':memory:');
  const s = criarServico(db, { paramsHash: { N: 1024, r: 8, p: 1 } });
  const A = { id: 'a', login: 'a', perfil: 'admin' };
  const c = s.salvarContrato(A, { ...CONTRATO, estados: 'SP' });
  assert.throws(() => s.salvarContrato(A, { ...CONTRATO, cnpj: '11222333000181', estados: 'RS,SC' }), /apenas um estado/);
  assert.strictEqual(c.situacao, 'ativo');
  const base = { contratoId: c.id, dataInicio: '2023-03-08', dataDistrato: '2026-02-11', comissoes: CIA };
  const d1 = s.salvarDistrato(A, { ...base, representada: 'cia' });
  assert.strictEqual(d1.contratoEncerrado, true);
  assert.strictEqual(s.listarContratos(A)[0].situacao, 'encerrado');
  const d2 = s.salvarDistrato(A, { ...base, representada: 'alimentos' });
  assert.strictEqual(d2.contratoEncerrado, false); // já estava encerrado
  s.removerDistrato(A, d1.id);
  assert.strictEqual(s.listarContratos(A)[0].situacao, 'encerrado'); // ainda há o distrato da Alimentos
  s.removerDistrato(A, d2.id);
  assert.strictEqual(s.listarContratos(A)[0].situacao, 'ativo');
  assert.ok(s.auditoria(A).some((a) => /encerrado pelo distrato/.test(a.detalhe)));

  // planilha da lista de representantes
  const MEM = require('../js/distrato-memoria.js');
  const P = require('../js/planilha.js');
  return P.ler(MEM.tabelaXlsx({ titulo: 'Representantes comerciais', subtitulo: 'Situação: ativos', cabecalho: ['Código', 'Representante'],
    linhas: [['10', 'A'], ['', 'B']], larguras: [10, 30] })).then((l) => {
    assert.deepStrictEqual(l[3], ['Código', 'Representante']);
    assert.deepStrictEqual(l[4], ['10', 'A']);
  });
});

test('relatórios: o distrato guarda o resultado de quando foi salvo, por empresa representada', () => {
  const db = abrirBanco(':memory:');
  const s = criarServico(db, { paramsHash: { N: 1024, r: 8, p: 1 } });
  const A = { id: 'a', login: 'adm', perfil: 'admin' };
  const c = s.salvarContrato(A, { ...CONTRATO, estados: 'SP' });
  const base = { contratoId: c.id, dataInicio: '2023-03-08', dataDistrato: '2026-02-11', comissoes: CIA };
  const d1 = s.salvarDistrato(A, { ...base, representada: 'cia' });
  const d2 = s.salvarDistrato(A, { ...base, representada: 'alimentos', simples: { situacao: 'nao_optante', fonte: 'manual' } });
  assert.strictEqual(d1.resultadoSalvo.total, d1.resultado.total);
  assert.strictEqual(d1.resultadoSalvo.liquido, d1.resultado.total);
  assert.strictEqual(d1.resultadoSalvo.salvoPor, 'adm');
  assert.ok(d2.resultadoSalvo.ir > 0);
  assert.strictEqual(d2.resultadoSalvo.liquido, d2.resultado.liquido);
  assert.strictEqual(d1.cidade, CONTRATO.cidade);
  const lista = s.listarDistratos(A).filter((d) => d.contratoId === c.id);
  assert.deepStrictEqual(lista.map((d) => d.representada).sort(), ['alimentos', 'cia']);
});

test('contrato: observações ficam só no cadastro', () => {
  const db = abrirBanco(':memory:');
  const s = criarServico(db, { paramsHash: { N: 1024, r: 8, p: 1 } });
  const A = { id: 'a', login: 'adm', perfil: 'admin' };
  const c = s.salvarContrato(A, { ...CONTRATO, estados: 'SP', observacoes: '  Prefere contato por e-mail.\nVisita mensal.  ' });
  assert.strictEqual(c.observacoes, 'Prefere contato por e-mail.\nVisita mensal.');
  assert.strictEqual(s.listarContratos(A).find((x) => x.id === c.id).observacoes, c.observacoes);
  const texto = JSON.stringify(C.montar(c));
  assert.ok(!texto.includes('Prefere contato'));
  assert.throws(() => s.salvarContrato(A, { ...CONTRATO, id: c.id, estados: 'SP', observacoes: 'x'.repeat(4001) }), /4000/);
});
