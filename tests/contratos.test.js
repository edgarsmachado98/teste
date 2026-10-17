const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const C = require('../js/contrato-modelo.js');
const D = require('../js/contrato-docx.js');
const { abrirBanco } = require('../server/db.js');
const { criarServico } = require('../server/servico.js');
const { criarApp } = require('../server/server.js');

const REP = {
  razao: '62.557.133 Marcos Antonio Carraro', cnpj: '62557133000110', fantasia: '',
  endereco: 'R Arlindo Rett Primo, 100 Sala 01', bairro: 'Jardim Sempre Verde', cidade: 'Jau', uf: 'SP', cep: '17211600',
  responsavel: 'Marcos Antonio Carraro', sexo: 'M', nacionalidade: 'brasileiro', nascimento: '1963-10-20',
  rg: '16435595', rgOrgao: 'SSP/SP', cpf: '05503031890', mesmoEndereco: true, zona: 'Jau e regiao', dataContrato: '2026-05-08',
};

/** Texto puro de um documento montado (sem marcações). */
const textoDe = (doc, vals) => doc.blocos.filter((b) => typeof b[1] === 'string' || typeof b[2] === 'string')
  .map((b) => C.trechos(typeof b[2] === 'string' ? b[2] : b[1], vals).map((t) => t.texto).join('')).join('\n');

test('CPF e CNPJ: dígitos verificadores e máscaras', () => {
  assert.ok(C.validarCPF('055.030.318-90'));
  assert.ok(!C.validarCPF('055.030.318-91'));
  assert.ok(!C.validarCPF('111.111.111-11'));
  assert.ok(C.validarCNPJ('62.557.133/0001-10'));
  assert.ok(C.validarCNPJ('95.597.647/0001-59'));
  assert.ok(!C.validarCNPJ('62.557.133/0001-11'));
  assert.strictEqual(C.formatarCNPJ('62557133000110'), '62.557.133/0001-10');
  assert.strictEqual(C.formatarCEP('17211600'), '17.211-600');
  assert.strictEqual(C.dataExtenso('2026-05-08'), '08 de maio de 2026');
});

test('o contrato reproduz o modelo com os dados do representante', () => {
  const vals = C.valores(REP);
  const docs = C.montar(REP);
  assert.deepStrictEqual(docs.map((d) => d.id), ['contratoCia', 'contratoAlimentos', 'politica', 'aditivo', 'termo']);
  const t = textoDe(docs[0], vals);
  assert.ok(t.includes('de outro lado 62.557.133 MARCOS ANTONIO CARRARO, pessoa jurídica de direito privado, de nome fantasia ***, ' +
    'estabelecida no endereço R ARLINDO RETT PRIMO, 100 SALA 01, BAIRRO JARDIM SEMPRE VERDE, JAU-SP, CEP 17.211-600, inscrita no ' +
    'CNPJ 62.557.133/0001-10, representada neste por MARCOS ANTONIO CARRARO, brasileiro, nascido em 20/10/1963, portador da ' +
    'cédula de identidade de nº 16435595 SSP/SP, inscrito no CPF sob nº 055.030.318-90'));
  assert.strictEqual(vals.zona, 'JAU E REGIAO');
  assert.ok(docs[0].blocos.some((b) => b[0] === 'zona')); // Anexo I
  assert.ok(t.includes('foro da Comarca de Santa Maria (RS)'));
  assert.ok(textoDe(docs[1], vals).includes('ANTONIAZZI IND E COM DE ALIMENTOS LTDA'));
  // nenhum campo fica sem valor e nenhuma marcação sobra no texto
  for (const d of docs) {
    const txt = textoDe(d, vals).replace(/\*\*\*/g, ''); // "***" é o nome fantasia vazio, como no modelo
    assert.ok(!/\[[a-zç ]+\]|⟦|\*\*|\{v\}/.test(txt), d.id);
  }
  assert.ok(textoDe(docs[4], vals).includes('Eu, MARCOS ANTONIO CARRARO, inscrito(a) no CPF sob nº 055.030.318-90'));
});

test('gênero, endereço residencial e documentos escolhidos', () => {
  const d = { ...REP, sexo: 'F', nacionalidade: 'brasileira', mesmoEndereco: false,
    resEndereco: 'Rua das Flores, 10', resBairro: 'Centro', resCidade: 'Bauru', resUf: 'SP', resCep: '17010000',
    documentos: ['contratoCia', 'termo'] };
  const docs = C.montar(d);
  assert.deepStrictEqual(docs.map((x) => x.id), ['contratoCia', 'termo']);
  const t = textoDe(docs[0], C.valores(d));
  assert.ok(t.includes('brasileira, nascida em 20/10/1963, portadora da cédula'));
  assert.ok(t.includes('inscrita no CPF'));
  assert.ok(t.includes('residente ao endereço RUA DAS FLORES, 10, BAIRRO CENTRO, BAURU-SP, CEP 17.010-000'));
  assert.deepStrictEqual(C.pendencias(d), []);
  const p = C.pendencias({ ...d, resCidade: '', cpf: '123' }).map((x) => x.campo);
  assert.ok(p.includes('resCidade') && p.includes('cpf'));
});

test('Word: gera um .docx válido com o conteúdo e os logotipos', () => {
  const img = (f, w, h) => ({ bytes: new Uint8Array(fs.readFileSync(f)), largura: w, altura: h });
  const bytes = D.gerar(C.montar(REP), C.valores(REP), {
    moinho: img('img/logo-moinho.png', 261, 111), antoniazzi: img('img/logo-antoniazzi.png', 286, 244),
  });
  const buf = Buffer.from(bytes);
  assert.strictEqual(buf.readUInt32LE(0), 0x04034b50); // assinatura ZIP
  const fim = buf.lastIndexOf(Buffer.from([0x50, 0x4b, 0x05, 0x06]));
  assert.strictEqual(buf.readUInt16LE(fim + 10), 20); // partes no pacote
  const txt = buf.toString('utf8');
  for (const parte of ['word/document.xml', 'word/header_logo.xml', 'word/media/logo-moinho.png', '[Content_Types].xml']) {
    assert.ok(txt.includes(parte), parte);
  }
  assert.ok(txt.includes('055.030.318-90'));
  assert.ok(txt.includes('POLÍTICA DE PRIVACIDADE GERAL'));
  assert.strictEqual(D.crc32(new TextEncoder().encode('123456789')), 0xcbf43926);
});

test('API de contratos: cadastro, permissões, duplicidade e backup', async (t) => {
  const db = abrirBanco(':memory:');
  const app = criarApp({ servico: criarServico(db, { paramsHash: { N: 1024, r: 8, p: 1 } }), limiteLogin: () => true });
  await new Promise((r) => app.listen(0, '127.0.0.1', r));
  t.after(() => app.close());
  const base = `http://127.0.0.1:${app.address().port}`;
  const cliente = () => {
    let cookie = '';
    return async (metodo, caminho, corpo) => {
      const r = await fetch(base + caminho, {
        method: metodo, body: corpo === undefined ? undefined : JSON.stringify(corpo),
        headers: { 'X-Requested-With': 'escala', 'Content-Type': 'application/json', ...(cookie ? { Cookie: cookie } : {}) },
      });
      if (r.headers.get('set-cookie')) cookie = r.headers.get('set-cookie').split(';')[0];
      return { status: r.status, dados: await r.json().catch(() => null) };
    };
  };
  const adm = cliente();
  await adm('POST', '/api/primeiro-acesso', { nome: 'Maria', login: 'maria', senha: 'Gestora2026' });
  await adm('POST', '/api/usuarios', { nome: 'Ana', login: 'ana', senha: 'Consulta123', perfil: 'consulta' });

  let r = await adm('POST', '/api/contratos', { ...REP, cpf: '05503031891' });
  assert.strictEqual(r.status, 400);
  assert.match(r.dados.erro, /CPF/);
  r = await adm('POST', '/api/contratos', { razao: 'Rascunho Ltda', cnpj: '11.444.777/0001-61' });
  assert.strictEqual(r.status, 200);
  assert.ok(r.dados.pendencias > 0); // rascunho pode ser salvo incompleto
  r = await adm('POST', '/api/contratos', REP);
  assert.strictEqual(r.status, 200);
  const id = r.dados.id;
  assert.strictEqual(r.dados.cnpj, '62.557.133/0001-10');
  assert.strictEqual(r.dados.pendencias, 0);
  assert.strictEqual(r.dados.documentos.length, 5);
  r = await adm('POST', '/api/contratos', REP);
  assert.strictEqual(r.status, 409); // já existe contrato ativo para o CNPJ
  r = await adm('PUT', `/api/contratos/${id}`, { ...REP, situacao: 'encerrado' });
  assert.strictEqual(r.dados.situacao, 'encerrado');
  assert.strictEqual((await adm('POST', '/api/contratos', REP)).status, 200); // agora pode abrir outro

  const ana = cliente();
  await ana('POST', '/api/login', { login: 'ana', senha: 'Consulta123' });
  assert.strictEqual((await ana('GET', '/api/contratos')).dados.length, 3);
  assert.strictEqual((await ana('POST', '/api/contratos', REP)).status, 403);
  assert.strictEqual((await ana('DELETE', `/api/contratos/${id}`)).status, 403);
  assert.strictEqual((await ana('POST', `/api/contratos/${id}/documento`, { formato: 'pdf' })).status, 200);

  const b = (await adm('GET', '/api/backup')).dados;
  assert.strictEqual(b.contratos.length, 3);
  await adm('DELETE', `/api/contratos/${id}`);
  assert.strictEqual((await adm('GET', '/api/contratos')).dados.length, 2);
  assert.strictEqual((await adm('POST', '/api/restaurar', b)).status, 200);
  assert.strictEqual((await adm('GET', '/api/contratos')).dados.length, 3);

  const hist = (await adm('GET', '/api/auditoria')).dados.map((a) => a.acao);
  for (const a of ['contrato.criar', 'contrato.alterar', 'contrato.excluir', 'contrato.documento']) assert.ok(hist.includes(a), a);

  // logotipos e ícone são servidos; outros arquivos continuam bloqueados
  assert.strictEqual((await fetch(base + '/img/logo-moinho.png')).headers.get('content-type'), 'image/png');
  assert.strictEqual((await fetch(base + '/favicon.ico')).status, 200);
  assert.strictEqual((await fetch(base + '/img/../server/db.js')).status, 404);
});
