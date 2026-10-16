const test = require('node:test');
const assert = require('node:assert');
const { abrirBanco } = require('../server/db.js');
const { criarServico } = require('../server/servico.js');
const { criarApp } = require('../server/server.js');

let agora = Date.now();

async function iniciar() {
  const db = abrirBanco(':memory:');
  const servico = criarServico(db, { paramsHash: { N: 1024, r: 8, p: 1 }, agora: () => agora });
  const app = criarApp({ servico, limiteLogin: () => true });
  await new Promise((r) => app.listen(0, '127.0.0.1', r));
  const base = `http://127.0.0.1:${app.address().port}`;
  return { app, base, db };
}

/** Cliente com "pote" de cookies, como um navegador. */
function cliente(base) {
  let cookie = '';
  return async (metodo, caminho, corpo, extras = {}) => {
    const headers = { 'X-Requested-With': 'escala', ...(cookie ? { Cookie: cookie } : {}), ...extras };
    if (corpo !== undefined) headers['Content-Type'] = 'application/json';
    const r = await fetch(base + caminho, { method: metodo, headers, body: corpo !== undefined ? JSON.stringify(corpo) : undefined });
    const sc = r.headers.get('set-cookie');
    if (sc) cookie = sc.split(';')[0];
    let dados = null;
    try { dados = await r.json(); } catch (e) { /* sem corpo */ }
    return { status: r.status, dados, setCookie: sc };
  };
}

test('fluxo completo: primeiro acesso, perfis, dados e escala', async (t) => {
  const { app, base } = await iniciar();
  t.after(() => app.close());
  const adm = cliente(base);

  let r = await adm('GET', '/api/status');
  assert.deepStrictEqual(r.dados, { temUsuarios: false, usuario: null });

  r = await adm('GET', '/api/dados');
  assert.strictEqual(r.status, 401);

  r = await adm('POST', '/api/primeiro-acesso', { nome: 'Maria', login: 'Maria', senha: 'fraca' });
  assert.strictEqual(r.status, 400);
  r = await adm('POST', '/api/primeiro-acesso', { nome: 'Maria', login: 'Maria', senha: 'Gestora2026' });
  assert.strictEqual(r.status, 200);
  assert.strictEqual(r.dados.usuario.perfil, 'admin');
  assert.match(r.setCookie, /HttpOnly/);
  assert.match(r.setCookie, /SameSite=Strict/);

  // segundo "primeiro acesso" é recusado
  r = await cliente(base)('POST', '/api/primeiro-acesso', { nome: 'X', login: 'intruso', senha: 'Intruso2026' });
  assert.strictEqual(r.status, 409);

  r = await adm('POST', '/api/usuarios', { nome: 'João', login: 'joao', senha: 'Operador123', perfil: 'operador' });
  assert.strictEqual(r.status, 200);
  r = await adm('POST', '/api/usuarios', { nome: 'Ana', login: 'ana', senha: 'Consulta123', perfil: 'consulta' });
  const idAna = r.dados.id;
  r = await adm('POST', '/api/usuarios', { nome: 'Dup', login: 'ana', senha: 'Consulta123', perfil: 'consulta' });
  assert.strictEqual(r.status, 409);

  // operador cadastra setor e colaboradores e gera a escala
  const op = cliente(base);
  assert.strictEqual((await op('POST', '/api/login', { login: 'joao', senha: 'Operador123' })).status, 200);
  assert.strictEqual((await op('GET', '/api/usuarios')).status, 403);
  r = await op('POST', '/api/setores', {
    nome: 'Loja', minimoPorDia: 2, diasFuncionamento: [true, true, true, true, true, true, true], funcionaFeriados: true,
  });
  const loja = r.dados.id;
  for (const [k, sexo] of ['F', 'M', 'F', 'M'].entries()) {
    r = await op('POST', '/api/colaboradores', { nome: 'P' + k, matricula: '10' + k, sexo, setorId: loja, jornada: '6x1', entrada: '08:00' });
    assert.strictEqual(r.status, 200, JSON.stringify(r.dados));
  }
  r = await op('POST', '/api/colaboradores', { nome: 'Rep', matricula: '100', sexo: 'F', setorId: loja, jornada: '6x1', entrada: '08:00' });
  assert.strictEqual(r.status, 409);
  r = await op('POST', '/api/colaboradores', { nome: 'X', matricula: '999', sexo: 'Z', setorId: loja, jornada: '6x1', entrada: '08:00' });
  assert.strictEqual(r.status, 400);

  r = await op('POST', '/api/colaboradores/importar', { linhas: [
    { linha: 2, nome: 'Csv1', matricula: '200', sexo: 'F', setor: 'Portaria', jornada: '12x36', entrada: '7:00' },
    { linha: 3, nome: 'Csv2', matricula: '100', sexo: 'M', setor: 'Loja' },
  ] });
  assert.strictEqual(r.dados.importados, 1);
  assert.match(r.dados.ignorados[0], /linha 3/);

  r = await op('POST', '/api/escala/gerar', { inicio: '2026-11-01', fim: '2026-11-30' });
  assert.strictEqual(r.status, 200);
  assert.strictEqual(r.dados.dias.length, 30);
  assert.strictEqual(r.dados.geradaPor, 'joao');
  r = await op('POST', '/api/escala/gerar', { inicio: '2026-01-01', fim: '2026-06-30' });
  assert.strictEqual(r.status, 400);

  const dados = (await op('GET', '/api/dados')).dados;
  const colab = dados.colaboradores.find((c) => c.matricula === '100');
  const antes = dados.escala.celulas[colab.id][3].tipo;
  r = await op('POST', '/api/escala/celula', { colaboradorId: colab.id, indice: 3 });
  assert.notStrictEqual(r.dados.celulas[colab.id][3].tipo, antes);

  // consulta só lê
  const ana = cliente(base);
  await ana('POST', '/api/login', { login: 'ana', senha: 'Consulta123' });
  assert.strictEqual((await ana('GET', '/api/dados')).dados.colaboradores.length, 5);
  assert.strictEqual((await ana('POST', '/api/escala/celula', { colaboradorId: colab.id, indice: 3 })).status, 403);
  assert.strictEqual((await ana('DELETE', `/api/setores/${loja}`)).status, 403);

  // setor com colaboradores não pode ser excluído
  assert.strictEqual((await op('DELETE', `/api/setores/${loja}`)).status, 409);
  // limpar dados é só do admin
  assert.strictEqual((await op('DELETE', '/api/dados')).status, 403);

  // desativar usuário encerra a sessão dele
  await adm('PUT', `/api/usuarios/${idAna}`, { ativo: false });
  assert.strictEqual((await ana('GET', '/api/dados')).status, 401);
  assert.strictEqual((await ana('POST', '/api/login', { login: 'ana', senha: 'Consulta123' })).status, 403);

  // backup e restauração preservam os dados
  const b = (await adm('GET', '/api/backup')).dados;
  await adm('DELETE', '/api/dados');
  assert.strictEqual((await adm('GET', '/api/dados')).dados.colaboradores.length, 0);
  assert.strictEqual((await adm('POST', '/api/restaurar', b)).status, 200);
  const rest = (await adm('GET', '/api/dados')).dados;
  assert.strictEqual(rest.colaboradores.length, 5);
  assert.strictEqual(Object.keys(rest.escala.celulas).length, 5);

  // histórico registra as ações
  const hist = (await adm('GET', '/api/auditoria')).dados.map((a) => a.acao);
  for (const acao of ['usuario.primeiro_admin', 'colaborador.importar', 'escala.gerar', 'escala.ajuste', 'dados.restaurar']) {
    assert.ok(hist.includes(acao), acao);
  }

  // logout invalida o cookie no servidor
  await op('POST', '/api/logout');
  assert.strictEqual((await op('GET', '/api/dados')).status, 401);
});

test('segurança: senha nunca armazenada, bloqueio, CSRF, último admin e arquivos', async (t) => {
  const { app, base, db } = await iniciar();
  t.after(() => app.close());
  const adm = cliente(base);
  await adm('POST', '/api/primeiro-acesso', { nome: 'Maria', login: 'maria', senha: 'Gestora2026' });
  const linha = db.prepare('SELECT * FROM usuarios').get();
  assert.ok(!JSON.stringify(linha).includes('Gestora2026'));
  assert.match(linha.senha_hash, /^scrypt\$/);
  assert.ok(!db.prepare('SELECT token_hash FROM sessoes').get().token_hash.includes('='));

  // sem o cabeçalho próprio (formulário de outro site) a alteração é recusada
  let r = await adm('POST', '/api/setores', {}, { 'X-Requested-With': '' });
  assert.strictEqual(r.status, 403);
  r = await adm('POST', '/api/setores', {}, { Origin: 'https://site-malicioso.example' });
  assert.strictEqual(r.status, 403);

  // último admin protegido
  const eu = (await adm('GET', '/api/status')).dados.usuario;
  assert.strictEqual((await adm('PUT', `/api/usuarios/${eu.id}`, { perfil: 'operador' })).status, 400);
  assert.strictEqual((await adm('DELETE', `/api/usuarios/${eu.id}`)).status, 400);

  // bloqueio após 5 erros, liberado depois de 5 minutos
  const x = cliente(base);
  for (let i = 0; i < 5; i++) assert.strictEqual((await x('POST', '/api/login', { login: 'maria', senha: 'errada' + i })).status, 401);
  r = await x('POST', '/api/login', { login: 'maria', senha: 'Gestora2026' });
  assert.strictEqual(r.status, 429);
  agora += 5 * 60 * 1000 + 1000;
  assert.strictEqual((await x('POST', '/api/login', { login: 'maria', senha: 'Gestora2026' })).status, 200);

  // sessão expira em 8 horas
  agora += 8 * 60 * 60 * 1000 + 1000;
  assert.strictEqual((await x('GET', '/api/dados')).status, 401);

  // arquivos: só a interface é servida
  const ok = await fetch(base + '/');
  assert.strictEqual(ok.status, 200);
  assert.match(ok.headers.get('content-security-policy'), /default-src 'self'/);
  for (const caminho of ['/server/servico.js', '/package.json', '/js/../server/db.js', '/dados/escala.db', '/js/%2e%2e/server/db.js']) {
    assert.strictEqual((await fetch(base + caminho)).status, 404, caminho);
  }
});
