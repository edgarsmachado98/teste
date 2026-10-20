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
  assert.strictEqual(achar('Total a pagar')[2], r.total);
  // as fórmulas estão na planilha (para a conferência no Excel)
  const zipTexto = Buffer.from(bytes).toString('latin1');
  assert.ok(zipTexto.includes('ROUND(C') && zipTexto.includes('SUM(F'));
});
