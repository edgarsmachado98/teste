/* Hash de senhas com scrypt (node:crypto). Formato: scrypt$N$r$p$sal$hash */
'use strict';

const crypto = require('node:crypto');
const { promisify } = require('node:util');

const scrypt = promisify(crypto.scrypt);
const PADRAO = { N: 32768, r: 8, p: 1 };
const TAMANHO = 32;

async function gerarHash(senha, params = PADRAO) {
  const sal = crypto.randomBytes(16);
  const hash = await scrypt(String(senha), sal, TAMANHO, { ...params, maxmem: 128 * params.N * params.r * 2 });
  return ['scrypt', params.N, params.r, params.p, sal.toString('base64'), hash.toString('base64')].join('$');
}

async function conferir(senha, armazenado) {
  const [alg, N, r, p, sal, hash] = String(armazenado).split('$');
  if (alg !== 'scrypt') return false;
  const params = { N: Number(N), r: Number(r), p: Number(p) };
  const esperado = Buffer.from(hash, 'base64');
  const obtido = await scrypt(String(senha), Buffer.from(sal, 'base64'), esperado.length,
    { ...params, maxmem: 128 * params.N * params.r * 2 });
  return crypto.timingSafeEqual(obtido, esperado);
}

function validarSenha(senha) {
  if (typeof senha !== 'string' || senha.length < 8) return 'A senha deve ter pelo menos 8 caracteres.';
  if (senha.length > 200) return 'A senha deve ter no máximo 200 caracteres.';
  if (!/[A-Za-zÀ-ÿ]/.test(senha) || !/\d/.test(senha)) return 'A senha deve conter letras e números.';
  return null;
}

module.exports = { gerarHash, conferir, validarSenha, PADRAO };
