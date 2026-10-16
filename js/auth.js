/*
 * Cadastro e autenticação de usuários do sistema.
 *
 * As senhas nunca são guardadas: armazena-se apenas um hash PBKDF2-SHA-256
 * com sal aleatório por usuário (Web Crypto). Os dados ficam no armazenamento
 * informado (localStorage no navegador), portanto valem apenas neste navegador.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.EscalaAuth = api;
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const ITERACOES = 150000;
  const MAX_TENTATIVAS = 5;
  const BLOQUEIO_MS = 5 * 60 * 1000;

  const PERFIS = {
    admin: { nome: 'Administrador', descricao: 'Acesso total, inclusive cadastro de usuários' },
    operador: { nome: 'Operador', descricao: 'Cadastra setores e colaboradores e gera escalas' },
    consulta: { nome: 'Consulta', descricao: 'Apenas visualiza as escalas' },
  };

  function cripto() {
    const c = (typeof globalThis !== 'undefined' && globalThis.crypto) || null;
    if (!c || !c.subtle) throw new Error('Este navegador não oferece criptografia segura (Web Crypto). Abra o sistema em um navegador atualizado.');
    return c;
  }

  const paraHex = (buf) => Array.from(new Uint8Array(buf)).map((b) => b.toString(16).padStart(2, '0')).join('');
  const deHex = (hex) => new Uint8Array(hex.match(/../g).map((h) => parseInt(h, 16)));

  async function gerarHash(senha, salHex, iteracoes) {
    const c = cripto();
    const chave = await c.subtle.importKey('raw', new TextEncoder().encode(senha), 'PBKDF2', false, ['deriveBits']);
    const bits = await c.subtle.deriveBits(
      { name: 'PBKDF2', hash: 'SHA-256', salt: deHex(salHex), iterations: iteracoes }, chave, 256);
    return paraHex(bits);
  }

  function novoSal() {
    return paraHex(cripto().getRandomValues(new Uint8Array(16)));
  }

  /** Comparação em tempo constante para não vazar informação pelo tempo de resposta. */
  function iguais(a, b) {
    if (a.length !== b.length) return false;
    let dif = 0;
    for (let i = 0; i < a.length; i++) dif |= a.charCodeAt(i) ^ b.charCodeAt(i);
    return dif === 0;
  }

  function validarSenha(senha) {
    if (typeof senha !== 'string' || senha.length < 8) return 'A senha deve ter pelo menos 8 caracteres.';
    if (!/[A-Za-zÀ-ÿ]/.test(senha) || !/\d/.test(senha)) return 'A senha deve conter letras e números.';
    return null;
  }

  function normalizarLogin(login) {
    return String(login || '').trim().toLowerCase();
  }

  function validarLogin(login) {
    if (!/^[a-z0-9._@-]{3,60}$/.test(login)) {
      return 'O login deve ter de 3 a 60 caracteres: letras sem acento, números, ponto, hífen, sublinhado ou @.';
    }
    return null;
  }

  /** Remove dados sensíveis antes de entregar o usuário à interface. */
  function publico(u) {
    return {
      id: u.id, nome: u.nome, login: u.login, perfil: u.perfil, ativo: u.ativo,
      criadoEm: u.criadoEm, ultimoAcesso: u.ultimoAcesso || null,
    };
  }

  function criarAuth(storage, chave, opcoes) {
    chave = chave || 'gerador-escala-usuarios-v1';
    const agora = (opcoes && opcoes.agora) || (() => Date.now());
    const iteracoes = (opcoes && opcoes.iteracoes) || ITERACOES;

    function ler() {
      try {
        const d = JSON.parse(storage.getItem(chave));
        return Array.isArray(d) ? d : [];
      } catch (e) {
        return [];
      }
    }

    function gravar(lista) {
      storage.setItem(chave, JSON.stringify(lista));
    }

    const erro = (msg) => { throw new Error(msg); };
    const admins = (lista) => lista.filter((u) => u.perfil === 'admin' && u.ativo);

    async function cadastrar({ nome, login, senha, perfil }) {
      const lista = ler();
      nome = String(nome || '').trim();
      login = normalizarLogin(login);
      if (!nome) erro('Informe o nome.');
      const e1 = validarLogin(login); if (e1) erro(e1);
      if (lista.some((u) => u.login === login)) erro(`O login "${login}" já está em uso.`);
      const e2 = validarSenha(senha); if (e2) erro(e2);
      // o primeiro usuário é sempre administrador
      if (!lista.length) perfil = 'admin';
      if (!PERFIS[perfil]) erro('Perfil inválido.');
      const sal = novoSal();
      const u = {
        id: agora().toString(36) + Math.random().toString(36).slice(2, 8),
        nome, login, perfil, ativo: true, sal, iteracoes, hash: await gerarHash(senha, sal, iteracoes),
        criadoEm: new Date(agora()).toISOString(), tentativas: 0, bloqueadoAte: 0,
      };
      lista.push(u);
      gravar(lista);
      return publico(u);
    }

    async function autenticar(login, senha) {
      const lista = ler();
      const u = lista.find((x) => x.login === normalizarLogin(login));
      const falha = 'Login ou senha incorretos.';
      if (!u) {
        // calcula um hash mesmo assim para o tempo de resposta não revelar se o login existe
        await gerarHash(String(senha || ''), '00000000000000000000000000000000', iteracoes);
        erro(falha);
      }
      if (u.bloqueadoAte && u.bloqueadoAte > agora()) {
        const min = Math.ceil((u.bloqueadoAte - agora()) / 60000);
        erro(`Acesso bloqueado por excesso de tentativas. Tente novamente em ${min} minuto(s).`);
      }
      const ok = iguais(await gerarHash(String(senha || ''), u.sal, u.iteracoes || iteracoes), u.hash);
      if (!ok) {
        u.tentativas = (u.tentativas || 0) + 1;
        if (u.tentativas >= MAX_TENTATIVAS) {
          u.tentativas = 0;
          u.bloqueadoAte = agora() + BLOQUEIO_MS;
        }
        gravar(lista);
        erro(falha);
      }
      if (!u.ativo) erro('Usuário desativado. Procure um administrador.');
      u.tentativas = 0;
      u.bloqueadoAte = 0;
      u.ultimoAcesso = new Date(agora()).toISOString();
      gravar(lista);
      return publico(u);
    }

    function atualizar(id, dados) {
      const lista = ler();
      const u = lista.find((x) => x.id === id) || erro('Usuário não encontrado.');
      const nome = dados.nome != null ? String(dados.nome).trim() : u.nome;
      if (!nome) erro('Informe o nome.');
      const perfil = dados.perfil || u.perfil;
      if (!PERFIS[perfil]) erro('Perfil inválido.');
      const ativo = dados.ativo != null ? !!dados.ativo : u.ativo;
      if (u.perfil === 'admin' && u.ativo && (perfil !== 'admin' || !ativo) && admins(lista).length === 1) {
        erro('O sistema precisa de pelo menos um administrador ativo.');
      }
      Object.assign(u, { nome, perfil, ativo });
      if (dados.desbloquear) { u.tentativas = 0; u.bloqueadoAte = 0; }
      gravar(lista);
      return publico(u);
    }

    async function definirSenha(id, novaSenha, senhaAtual) {
      const lista = ler();
      const u = lista.find((x) => x.id === id) || erro('Usuário não encontrado.');
      if (senhaAtual !== undefined) {
        const ok = iguais(await gerarHash(String(senhaAtual), u.sal, u.iteracoes || iteracoes), u.hash);
        if (!ok) erro('A senha atual está incorreta.');
      }
      const e = validarSenha(novaSenha); if (e) erro(e);
      u.sal = novoSal();
      u.iteracoes = iteracoes;
      u.hash = await gerarHash(novaSenha, u.sal, iteracoes);
      u.tentativas = 0;
      u.bloqueadoAte = 0;
      gravar(lista);
    }

    function remover(id, solicitanteId) {
      const lista = ler();
      const u = lista.find((x) => x.id === id) || erro('Usuário não encontrado.');
      if (id === solicitanteId) erro('Você não pode excluir o próprio usuário.');
      if (u.perfil === 'admin' && u.ativo && admins(lista).length === 1) erro('Não é possível excluir o último administrador.');
      gravar(lista.filter((x) => x.id !== id));
    }

    function buscar(id) {
      const u = ler().find((x) => x.id === id);
      return u ? publico(u) : null;
    }

    function bloqueado(id) {
      const u = ler().find((x) => x.id === id);
      return !!(u && u.bloqueadoAte && u.bloqueadoAte > agora());
    }

    return {
      temUsuarios: () => ler().length > 0,
      listar: () => ler().map(publico),
      buscar, bloqueado, cadastrar, autenticar, atualizar, definirSenha, remover,
    };
  }

  return { PERFIS, criarAuth, validarSenha, validarLogin, normalizarLogin };
});
