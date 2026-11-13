const test = require('node:test');
const assert = require('node:assert');
const { abrirBanco } = require('../server/db.js');
const { criarServico } = require('../server/servico.js');
const { criarApp } = require('../server/server.js');
const padrao = require('../server/empresas-padrao.js');

const A = { id: 'a', login: 'adm', perfil: 'admin' };
const CONSULTA = { id: 'c', login: 'c', perfil: 'consulta' };
const PNG = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 1, 2, 3]);
const b64 = (b) => Buffer.from(b).toString('base64');
const novo = () => criarServico(abrirBanco(':memory:'), { paramsHash: { N: 1024, r: 8, p: 1 } });

test('empresas: cadastro, validações, modelos e logotipo', () => {
  const s = novo();
  assert.throws(() => s.salvarEmpresa(A, { razao: 'X', cnpj: '11.111.111/1111-11' }), /CNPJ inválido/);
  assert.throws(() => s.salvarEmpresa(A, { razao: 'X', cnpj: '29356095000162', regime: 'Outro regime' }), /Regime/);
  assert.throws(() => s.salvarEmpresa(CONSULTA, { razao: 'X', cnpj: '29356095000162' }), (e) => e.status === 403);
  const e = s.salvarEmpresa(A, { razao: 'Nova Ltda', cnpj: '29356095000162', regime: 'Lucro Real', cep: '97010050', uf: 'rs' });
  assert.deepStrictEqual([e.cnpj, e.cep, e.uf, e.regime], ['29.356.095/0001-62', '97.010-050', 'RS', 'Lucro Real']);
  assert.throws(() => s.salvarEmpresa(A, { razao: 'Outra', cnpj: '29.356.095/0001-62' }), (x) => x.status === 409);

  // vários modelos do mesmo tipo
  s.enviarArquivoEmpresa(A, e.id, 'contrato', { nome: 'Contrato SP.docx', conteudo: b64('um') });
  let r = s.enviarArquivoEmpresa(A, e.id, 'contrato', { nome: 'Contrato RS.docx', conteudo: b64('dois') });
  assert.strictEqual(r.arquivos.filter((a) => a.tipo === 'contrato').length, 2);
  assert.throws(() => s.enviarArquivoEmpresa(A, e.id, 'planilha', { nome: 'x.exe', conteudo: b64('x') }), /envie um arquivo/);
  assert.throws(() => s.enviarArquivoEmpresa(A, e.id, 'logo', { nome: 'falso.png', conteudo: b64('texto') }), /PNG ou JPG/);
  assert.throws(() => s.enviarArquivoEmpresa(A, e.id, 'outro', { nome: 'a.pdf', conteudo: b64('x') }), /Tipo/);

  // um só logotipo: o novo substitui o anterior
  s.enviarArquivoEmpresa(A, e.id, 'logo', { nome: 'a.png', conteudo: b64(PNG) });
  r = s.enviarArquivoEmpresa(A, e.id, 'logo', { nome: 'b.png', conteudo: b64(PNG) });
  const logos = r.arquivos.filter((a) => a.tipo === 'logo');
  assert.deepStrictEqual(logos.map((a) => a.nome), ['b.png']);

  const contratoRs = r.arquivos.find((a) => a.nome === 'Contrato RS.docx');
  const baixado = s.baixarArquivoEmpresa(CONSULTA, e.id, contratoRs.id);
  assert.deepStrictEqual([baixado.binario.toString(), baixado.inline], ['dois', false]);
  assert.strictEqual(s.baixarArquivoEmpresa(CONSULTA, e.id, logos[0].id).inline, true);
  r = s.removerArquivoEmpresa(A, e.id, contratoRs.id);
  assert.deepStrictEqual(r.arquivos.filter((a) => a.tipo === 'contrato').map((a) => a.nome), ['Contrato SP.docx']);

  // backup e restauração levam as empresas com os arquivos
  const copia = s.backup(A);
  const s2 = novo();
  s2.restaurar(A, copia);
  const [e2] = s2.listarEmpresas(CONSULTA);
  assert.strictEqual(e2.razao, 'Nova Ltda');
  assert.strictEqual(e2.arquivos.length, 2);
  const sp = e2.arquivos.find((a) => a.tipo === 'contrato');
  assert.strictEqual(s2.baixarArquivoEmpresa(A, e2.id, sp.id).binario.toString(), 'um');

  s.removerEmpresa(A, e.id);
  assert.deepStrictEqual(s.listarEmpresas(CONSULTA), []);
});

test('empresas já existentes: cadastradas uma única vez com os modelos atuais', () => {
  const s = novo();
  assert.strictEqual(s.semearEmpresas(padrao()), 2);
  const lista = s.listarEmpresas(CONSULTA);
  const cia = lista.find((e) => e.cnpj === '95.597.647/0001-59');
  const alim = lista.find((e) => e.cnpj === '11.780.083/0001-03');
  assert.deepStrictEqual(cia.arquivos.map((a) => a.tipo).sort(), ['contrato', 'contrato', 'distrato', 'logo', 'planilha']);
  assert.deepStrictEqual(alim.arquivos.map((a) => a.tipo).sort(), ['contrato', 'distrato', 'logo', 'planilha']);
  const docx = s.baixarArquivoEmpresa(A, cia.id, cia.arquivos.find((a) => a.tipo === 'contrato').id);
  assert.strictEqual(docx.binario.subarray(0, 2).toString(), 'PK');
  // excluída pelo usuário, não volta na próxima inicialização
  s.removerEmpresa(A, alim.id);
  assert.strictEqual(s.semearEmpresas(padrao()), 0);
  assert.strictEqual(s.listarEmpresas(CONSULTA).length, 1);
});

test('empresas: rotas HTTP de envio e download', async (t) => {
  const s = novo();
  const app = criarApp({ servico: s, limiteLogin: () => true });
  await new Promise((r) => app.listen(0, '127.0.0.1', r));
  t.after(() => app.close());
  const base = `http://127.0.0.1:${app.address().port}`;
  let cookie = '';
  const req = async (metodo, caminho, corpo) => {
    const r = await fetch(base + caminho, { method: metodo,
      headers: { 'X-Requested-With': 'escala', 'Content-Type': 'application/json', ...(cookie ? { Cookie: cookie } : {}) },
      body: corpo !== undefined ? JSON.stringify(corpo) : undefined });
    const sc = r.headers.get('set-cookie');
    if (sc) cookie = sc.split(';')[0];
    return r;
  };
  await req('POST', '/api/primeiro-acesso', { nome: 'Maria', login: 'maria', senha: 'Gestora2026' });
  const e = await (await req('POST', '/api/empresas', { razao: 'Nova Ltda', cnpj: '29356095000162' })).json();
  let r = await req('POST', `/api/empresas/${e.id}/arquivos/distrato`, { nome: 'Distrato modelo.pdf', conteudo: b64('%PDF-1.4') });
  assert.strictEqual(r.status, 200);
  const a = (await r.json()).arquivos[0];
  r = await req('GET', `/api/empresas/${e.id}/arquivos/${a.id}`);
  assert.strictEqual(r.status, 200);
  assert.strictEqual(r.headers.get('content-type'), 'application/pdf');
  assert.match(r.headers.get('content-disposition'), /^attachment;.*Distrato%20modelo\.pdf/);
  assert.strictEqual(await r.text(), '%PDF-1.4');
  assert.strictEqual((await req('DELETE', `/api/empresas/${e.id}/arquivos/${a.id}`)).status, 200);
  assert.strictEqual((await req('GET', `/api/empresas/${e.id}/arquivos/${a.id}`)).status, 404);
});

test('empresa representada: modelos de contrato dela entram nos documentos legais do representante', () => {
  const s = novo();
  s.semearEmpresas(padrao());
  assert.ok(s.listarEmpresas(CONSULTA).every((e) => e.representada === true));
  const rep = s.salvarEmpresa(A, { razao: 'Representada Nova', cnpj: '29356095000162', representada: true });
  const outra = s.salvarEmpresa(A, { razao: 'Só cadastro', cnpj: '11222333000181' });
  assert.strictEqual(outra.representada, false);
  const m1 = s.enviarArquivoEmpresa(A, rep.id, 'contrato', { nome: 'Modelo.docx', conteudo: b64('x') }).arquivos[0];
  const m2 = s.enviarArquivoEmpresa(A, outra.id, 'contrato', { nome: 'Outro.docx', conteudo: b64('y') }).arquivos[0];
  const c = s.salvarContrato(A, { razao: 'Rep Ltda', cnpj: '45.997.418/0001-53', estados: 'SP',
    documentos: ['contratoCia', `arq:${m1.id}`, `arq:${m2.id}`, 'arq:inexistente'] });
  // só o modelo da empresa marcada como representada é aceito
  assert.deepStrictEqual(c.documentos, ['contratoCia', `arq:${m1.id}`]);
});

test('bancos da versão 4.10: empresas padrão passam a ser representadas', () => {
  const db = abrirBanco(':memory:');
  const s = criarServico(db, { paramsHash: { N: 1024, r: 8, p: 1 } });
  s.semearEmpresas(padrao().map((e) => ({ ...e, representada: false })));
  db.prepare("DELETE FROM configuracoes WHERE chave = 'empresasRepresentadas'").run();
  s.semearEmpresas(padrao());
  assert.ok(s.listarEmpresas(CONSULTA).every((e) => e.representada === true));
});
