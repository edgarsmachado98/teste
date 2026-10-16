const test = require('node:test');
const assert = require('node:assert');
const { criarAuth } = require('../js/auth.js');

function memoria() {
  const m = {};
  return { getItem: (k) => (k in m ? m[k] : null), setItem: (k, v) => { m[k] = String(v); }, dump: () => m };
}

function novo(agora) {
  const st = memoria();
  return { st, auth: criarAuth(st, 'u', { iteracoes: 1000, agora }) };
}

test('primeiro usuário vira administrador e a senha não é armazenada', async () => {
  const { st, auth } = novo();
  assert.strictEqual(auth.temUsuarios(), false);
  const u = await auth.cadastrar({ nome: 'Maria', login: 'Maria.RH', senha: 'segredo123', perfil: 'consulta' });
  assert.strictEqual(u.perfil, 'admin');
  assert.strictEqual(u.login, 'maria.rh');
  assert.ok(!st.dump().u.includes('segredo123'));
  assert.strictEqual(u.hash, undefined);
});

test('login, senha errada e validações', async () => {
  const { auth } = novo();
  await auth.cadastrar({ nome: 'Maria', login: 'maria', senha: 'segredo123' });
  assert.strictEqual((await auth.autenticar('MARIA', 'segredo123')).nome, 'Maria');
  await assert.rejects(auth.autenticar('maria', 'errada123'), /incorretos/);
  await assert.rejects(auth.autenticar('ninguem', 'segredo123'), /incorretos/);
  await assert.rejects(auth.cadastrar({ nome: 'X', login: 'maria', senha: 'outra1234', perfil: 'operador' }), /em uso/);
  await assert.rejects(auth.cadastrar({ nome: 'X', login: 'jose', senha: 'curta1', perfil: 'operador' }), /8 caracteres/);
  await assert.rejects(auth.cadastrar({ nome: 'X', login: 'jose', senha: 'somenteletras', perfil: 'operador' }), /letras e números/);
});

test('bloqueia após 5 tentativas e libera depois de 5 minutos', async () => {
  let t = 1_000_000;
  const { auth } = novo(() => t);
  await auth.cadastrar({ nome: 'Maria', login: 'maria', senha: 'segredo123' });
  for (let i = 0; i < 5; i++) await assert.rejects(auth.autenticar('maria', 'errada123'));
  await assert.rejects(auth.autenticar('maria', 'segredo123'), /bloqueado/);
  t += 5 * 60 * 1000 + 1;
  assert.ok(await auth.autenticar('maria', 'segredo123'));
});

test('protege o último administrador e o próprio usuário', async () => {
  const { auth } = novo();
  const adm = await auth.cadastrar({ nome: 'Maria', login: 'maria', senha: 'segredo123' });
  const op = await auth.cadastrar({ nome: 'José', login: 'jose', senha: 'segredo456', perfil: 'operador' });
  assert.throws(() => auth.atualizar(adm.id, { perfil: 'operador' }), /administrador/);
  assert.throws(() => auth.atualizar(adm.id, { ativo: false }), /administrador/);
  assert.throws(() => auth.remover(adm.id, op.id), /último administrador/);
  assert.throws(() => auth.remover(adm.id, adm.id), /próprio/);
  auth.atualizar(op.id, { ativo: false });
  await assert.rejects(auth.autenticar('jose', 'segredo456'), /desativado/);
  auth.remover(op.id, adm.id);
  assert.strictEqual(auth.listar().length, 1);
});

test('troca de senha exige a senha atual quando informada', async () => {
  const { auth } = novo();
  const u = await auth.cadastrar({ nome: 'Maria', login: 'maria', senha: 'segredo123' });
  await assert.rejects(auth.definirSenha(u.id, 'nova12345', 'errada'), /atual/);
  await auth.definirSenha(u.id, 'nova12345', 'segredo123');
  await assert.rejects(auth.autenticar('maria', 'segredo123'));
  assert.ok(await auth.autenticar('maria', 'nova12345'));
});
