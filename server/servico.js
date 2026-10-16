/*
 * Regras de negócio do servidor: usuários, sessões, permissões, cadastros
 * e escala. Independente de HTTP para poder ser testado diretamente.
 */
'use strict';

const crypto = require('node:crypto');
const M = require('../js/motor.js');
const senhas = require('./senhas.js');

const PERFIS = {
  admin: { nome: 'Administrador', descricao: 'Acesso total, inclusive cadastro de usuários' },
  operador: { nome: 'Operador', descricao: 'Cadastra setores e colaboradores e gera escalas' },
  consulta: { nome: 'Consulta', descricao: 'Apenas visualiza as escalas' },
};
const NIVEL = { consulta: 1, operador: 2, admin: 3 };

const DURACAO_SESSAO = 8 * 60 * 60 * 1000;
const MAX_TENTATIVAS = 5;
const BLOQUEIO_MS = 5 * 60 * 1000;
const MAX_DIAS_ESCALA = 93;

class ErroApp extends Error {
  constructor(status, mensagem) {
    super(mensagem);
    this.status = status;
  }
}
const falhar = (status, msg) => { throw new ErroApp(status, msg); };

// ------------------------------------------------------------- validação

function texto(v, campo, max) {
  const s = String(v == null ? '' : v).trim();
  if (!s) falhar(400, `Informe ${campo}.`);
  if (s.length > max) falhar(400, `${campo[0].toUpperCase() + campo.slice(1)} deve ter no máximo ${max} caracteres.`);
  return s;
}

function dataValida(v, campo) {
  const s = String(v || '');
  if (!/^\d{4}-\d{2}-\d{2}$/.test(s) || M.formatarData(M.parseData(s)) !== s) falhar(400, `${campo} inválida.`);
  return s;
}

function normalizarLogin(login) {
  const l = String(login || '').trim().toLowerCase();
  if (!/^[a-z0-9._@-]{3,60}$/.test(l)) {
    falhar(400, 'O login deve ter de 3 a 60 caracteres: letras sem acento, números, ponto, hífen, sublinhado ou @.');
  }
  return l;
}

function exigirSenhaForte(senha) {
  const e = senhas.validarSenha(senha);
  if (e) falhar(400, e);
}

const novoId = () => crypto.randomUUID();
const dataBR = (d) => d.split('-').reverse().join('/');
const hashToken = (t) => crypto.createHash('sha256').update(String(t)).digest('hex');

// ---------------------------------------------------------------- mapas

const usuarioPublico = (u) => u && ({
  id: u.id, nome: u.nome, login: u.login, perfil: u.perfil, ativo: !!u.ativo,
  criadoEm: u.criado_em, ultimoAcesso: u.ultimo_acesso || null,
});

const setorDeLinha = (s) => ({
  id: s.id, nome: s.nome, minimoPorDia: s.minimo_por_dia,
  diasFuncionamento: JSON.parse(s.dias_funcionamento), funcionaFeriados: !!s.funciona_feriados,
});

const colabDeLinha = (c) => ({
  id: c.id, nome: c.nome, matricula: c.matricula, sexo: c.sexo,
  setorId: c.setor_id, jornada: c.jornada, entrada: c.entrada,
});

// ---------------------------------------------------------------- serviço

function criarServico(db, opcoes = {}) {
  const agora = opcoes.agora || (() => Date.now());
  const iso = () => new Date(agora()).toISOString();
  const paramsHash = opcoes.paramsHash || senhas.PADRAO;
  const hashSenha = (s) => senhas.gerarHash(s, paramsHash);
  // hash de referência para igualar o tempo de resposta quando o login não existe
  const hashFicticio = hashSenha('senha-ficticia-0');

  const q = (sql) => db.prepare(sql);

  function auditar(ator, acao, detalhe) {
    q('INSERT INTO auditoria (em, usuario_id, usuario_login, acao, detalhe) VALUES (?, ?, ?, ?, ?)')
      .run(iso(), ator ? ator.id : null, ator ? ator.login : null, acao, detalhe || null);
  }

  function exigir(ator, perfil) {
    if (!ator) falhar(401, 'Faça login para continuar.');
    if (NIVEL[ator.perfil] < NIVEL[perfil]) {
      falhar(403, perfil === 'admin' ? 'Apenas administradores podem fazer isso.' : 'Seu perfil permite apenas consultar as escalas.');
    }
  }

  const contarAdminsAtivos = () => q("SELECT COUNT(*) AS n FROM usuarios WHERE perfil = 'admin' AND ativo = 1").get().n;
  const buscarUsuario = (id) => q('SELECT * FROM usuarios WHERE id = ?').get(id);

  // --------------------------------------------------------- acesso

  function temUsuarios() {
    return q('SELECT COUNT(*) AS n FROM usuarios').get().n > 0;
  }

  async function inserirUsuario({ nome, login, senha, perfil }) {
    nome = texto(nome, 'o nome', 100);
    login = normalizarLogin(login);
    if (!PERFIS[perfil]) falhar(400, 'Perfil inválido.');
    exigirSenhaForte(senha);
    const hash = await hashSenha(senha);
    if (q('SELECT 1 FROM usuarios WHERE login = ?').get(login)) falhar(409, `O login "${login}" já está em uso.`);
    const id = novoId();
    q(`INSERT INTO usuarios (id, nome, login, perfil, ativo, senha_hash, criado_em)
       VALUES (?, ?, ?, ?, 1, ?, ?)`).run(id, nome, login, perfil, hash, iso());
    return buscarUsuario(id);
  }

  async function criarPrimeiroAdmin(dados) {
    if (temUsuarios()) falhar(409, 'O administrador já foi criado. Faça login.');
    const u = await inserirUsuario({ ...dados, perfil: 'admin' });
    // corrida: se outro pedido criou um usuário ao mesmo tempo, desfaz este
    if (q('SELECT COUNT(*) AS n FROM usuarios').get().n > 1) {
      q('DELETE FROM usuarios WHERE id = ?').run(u.id);
      falhar(409, 'O administrador já foi criado. Faça login.');
    }
    auditar(u, 'usuario.primeiro_admin', u.login);
    return criarSessao(u);
  }

  function criarSessao(u) {
    const token = crypto.randomBytes(32).toString('base64url');
    q('DELETE FROM sessoes WHERE expira_em < ?').run(agora());
    q('INSERT INTO sessoes (token_hash, usuario_id, criada_em, expira_em) VALUES (?, ?, ?, ?)')
      .run(hashToken(token), u.id, agora(), agora() + DURACAO_SESSAO);
    q('UPDATE usuarios SET ultimo_acesso = ? WHERE id = ?').run(iso(), u.id);
    return { token, expiraEm: agora() + DURACAO_SESSAO, usuario: usuarioPublico(buscarUsuario(u.id)) };
  }

  async function login(loginInformado, senha) {
    const erroPadrao = 'Login ou senha incorretos.';
    const l = String(loginInformado || '').trim().toLowerCase();
    const u = q('SELECT * FROM usuarios WHERE login = ?').get(l);
    if (!u) {
      await senhas.conferir(String(senha || ''), await hashFicticio);
      falhar(401, erroPadrao);
    }
    if (u.bloqueado_ate > agora()) {
      const min = Math.ceil((u.bloqueado_ate - agora()) / 60000);
      falhar(429, `Acesso bloqueado por excesso de tentativas. Tente novamente em ${min} minuto(s).`);
    }
    const ok = await senhas.conferir(String(senha || ''), u.senha_hash);
    if (!ok) {
      const tentativas = u.tentativas + 1;
      if (tentativas >= MAX_TENTATIVAS) {
        q('UPDATE usuarios SET tentativas = 0, bloqueado_ate = ? WHERE id = ?').run(agora() + BLOQUEIO_MS, u.id);
        auditar(usuarioPublico(u), 'acesso.bloqueado', `${MAX_TENTATIVAS} tentativas com senha incorreta`);
      } else {
        q('UPDATE usuarios SET tentativas = ? WHERE id = ?').run(tentativas, u.id);
      }
      falhar(401, erroPadrao);
    }
    if (!u.ativo) falhar(403, 'Usuário desativado. Procure um administrador.');
    q('UPDATE usuarios SET tentativas = 0, bloqueado_ate = 0 WHERE id = ?').run(u.id);
    auditar(usuarioPublico(u), 'acesso.login', null);
    return criarSessao(u);
  }

  /** Usuário dono do token, ou null se a sessão não existir/expirou/usuário inativo. */
  function sessao(token) {
    if (!token) return null;
    const s = q('SELECT * FROM sessoes WHERE token_hash = ?').get(hashToken(token));
    if (!s) return null;
    if (s.expira_em < agora()) {
      q('DELETE FROM sessoes WHERE token_hash = ?').run(s.token_hash);
      return null;
    }
    const u = buscarUsuario(s.usuario_id);
    return u && u.ativo ? usuarioPublico(u) : null;
  }

  function logout(token) {
    if (token) q('DELETE FROM sessoes WHERE token_hash = ?').run(hashToken(token));
  }

  async function alterarMinhaSenha(ator, atual, nova, token) {
    exigir(ator, 'consulta');
    const u = buscarUsuario(ator.id);
    if (!(await senhas.conferir(String(atual || ''), u.senha_hash))) falhar(400, 'A senha atual está incorreta.');
    exigirSenhaForte(nova);
    q('UPDATE usuarios SET senha_hash = ? WHERE id = ?').run(await hashSenha(nova), u.id);
    // encerra as outras sessões deste usuário
    q('DELETE FROM sessoes WHERE usuario_id = ? AND token_hash <> ?').run(u.id, hashToken(token || ''));
    auditar(ator, 'usuario.senha_propria', null);
  }

  // ------------------------------------------------------- usuários

  function listarUsuarios(ator) {
    exigir(ator, 'admin');
    return q('SELECT * FROM usuarios ORDER BY nome COLLATE NOCASE').all().map((u) => ({
      ...usuarioPublico(u), bloqueado: u.bloqueado_ate > agora(),
    }));
  }

  async function criarUsuario(ator, dados) {
    exigir(ator, 'admin');
    const u = await inserirUsuario(dados);
    auditar(ator, 'usuario.criar', `${u.login} (${PERFIS[u.perfil].nome})`);
    return usuarioPublico(u);
  }

  async function atualizarUsuario(ator, id, dados) {
    exigir(ator, 'admin');
    const u = buscarUsuario(id) || falhar(404, 'Usuário não encontrado.');
    const nome = dados.nome != null ? texto(dados.nome, 'o nome', 100) : u.nome;
    const perfil = dados.perfil || u.perfil;
    if (!PERFIS[perfil]) falhar(400, 'Perfil inválido.');
    const ativo = dados.ativo != null ? !!dados.ativo : !!u.ativo;
    if (id === ator.id && (perfil !== 'admin' || !ativo)) falhar(400, 'Você não pode retirar o próprio acesso de administrador.');
    if (u.perfil === 'admin' && u.ativo && (perfil !== 'admin' || !ativo) && contarAdminsAtivos() === 1) {
      falhar(400, 'O sistema precisa de pelo menos um administrador ativo.');
    }
    let novoHash = null;
    if (dados.senha) {
      exigirSenhaForte(dados.senha);
      novoHash = await hashSenha(dados.senha);
    }
    db.transacao(() => {
      q('UPDATE usuarios SET nome = ?, perfil = ?, ativo = ? WHERE id = ?').run(nome, perfil, ativo ? 1 : 0, id);
      if (dados.desbloquear) q('UPDATE usuarios SET tentativas = 0, bloqueado_ate = 0 WHERE id = ?').run(id);
      if (novoHash) {
        q('UPDATE usuarios SET senha_hash = ?, tentativas = 0, bloqueado_ate = 0 WHERE id = ?').run(novoHash, id);
      }
      // senha redefinida ou usuário desativado: derruba as sessões abertas
      if (novoHash || !ativo) q('DELETE FROM sessoes WHERE usuario_id = ?').run(id);
    });
    const mudancas = [];
    if (nome !== u.nome) mudancas.push('nome');
    if (perfil !== u.perfil) mudancas.push(`perfil: ${PERFIS[perfil].nome}`);
    if (ativo !== !!u.ativo) mudancas.push(ativo ? 'reativado' : 'desativado');
    if (novoHash) mudancas.push('senha redefinida');
    if (dados.desbloquear) mudancas.push('desbloqueado');
    auditar(ator, 'usuario.alterar', `${u.login}${mudancas.length ? ': ' + mudancas.join(', ') : ''}`);
    return usuarioPublico(buscarUsuario(id));
  }

  function removerUsuario(ator, id) {
    exigir(ator, 'admin');
    const u = buscarUsuario(id) || falhar(404, 'Usuário não encontrado.');
    if (id === ator.id) falhar(400, 'Você não pode excluir o próprio usuário.');
    if (u.perfil === 'admin' && u.ativo && contarAdminsAtivos() === 1) falhar(400, 'Não é possível excluir o último administrador.');
    q('DELETE FROM usuarios WHERE id = ?').run(id);
    auditar(ator, 'usuario.excluir', u.login);
  }

  function auditoria(ator, limite = 200) {
    exigir(ator, 'admin');
    return q('SELECT em, usuario_login AS usuario, acao, detalhe FROM auditoria ORDER BY id DESC LIMIT ?')
      .all(Math.min(Math.max(1, Number(limite) || 200), 1000));
  }

  // ------------------------------------------------------------ dados

  function config() {
    const linhas = q('SELECT chave, valor FROM configuracoes').all();
    const c = Object.fromEntries(linhas.map((l) => [l.chave, JSON.parse(l.valor)]));
    return {
      regras: { domingoHomensSemanas: c.domingoHomensSemanas || 3, domingoMulheresSemanas: 2 },
      incluirFacultativos: !!c.incluirFacultativos,
    };
  }

  function lerSetores() {
    return q('SELECT * FROM setores ORDER BY nome COLLATE NOCASE').all().map(setorDeLinha);
  }

  function lerColaboradores() {
    return q('SELECT * FROM colaboradores ORDER BY nome COLLATE NOCASE').all().map(colabDeLinha);
  }

  function lerEscala() {
    const e = q('SELECT * FROM escala WHERE id = 1').get();
    if (!e) return null;
    return Object.assign(JSON.parse(e.dados), { geradaEm: e.gerada_em, atualizadaEm: e.atualizada_em, geradaPor: e.gerada_por });
  }

  function dados(ator) {
    exigir(ator, 'consulta');
    const escala = lerEscala();
    return {
      setores: lerSetores(),
      colaboradores: lerColaboradores(),
      feriadosExtras: q('SELECT data, nome FROM feriados ORDER BY data').all().map((f) => ({ ...f })),
      ...config(),
      escala,
      periodo: escala ? { inicio: escala.inicio, fim: escala.fim } : null,
    };
  }

  // ---------------------------------------------------------- setores

  function normalizarSetor(d) {
    const dias = Array.isArray(d.diasFuncionamento) && d.diasFuncionamento.length === 7
      ? d.diasFuncionamento.map(Boolean) : falhar(400, 'Dias de funcionamento inválidos.');
    if (!dias.some(Boolean)) falhar(400, 'Selecione ao menos um dia de funcionamento.');
    const minimo = Number(d.minimoPorDia);
    if (!Number.isInteger(minimo) || minimo < 0 || minimo > 999) falhar(400, 'Mínimo por dia deve ser um número inteiro de 0 a 999.');
    return { nome: texto(d.nome, 'o nome do setor', 60), minimo, dias, feriados: !!d.funcionaFeriados };
  }

  function salvarSetor(ator, d) {
    exigir(ator, 'operador');
    const s = normalizarSetor(d);
    const repetido = q('SELECT id FROM setores WHERE nome = ? COLLATE NOCASE').get(s.nome);
    if (repetido && repetido.id !== d.id) falhar(409, `Já existe um setor chamado "${s.nome}".`);
    let id = d.id;
    if (id) {
      const r = q('UPDATE setores SET nome = ?, minimo_por_dia = ?, dias_funcionamento = ?, funciona_feriados = ? WHERE id = ?')
        .run(s.nome, s.minimo, JSON.stringify(s.dias), s.feriados ? 1 : 0, id);
      if (!r.changes) falhar(404, 'Setor não encontrado.');
      auditar(ator, 'setor.alterar', s.nome);
    } else {
      id = novoId();
      q('INSERT INTO setores (id, nome, minimo_por_dia, dias_funcionamento, funciona_feriados) VALUES (?, ?, ?, ?, ?)')
        .run(id, s.nome, s.minimo, JSON.stringify(s.dias), s.feriados ? 1 : 0);
      auditar(ator, 'setor.criar', s.nome);
    }
    return setorDeLinha(q('SELECT * FROM setores WHERE id = ?').get(id));
  }

  function removerSetor(ator, id) {
    exigir(ator, 'operador');
    const s = q('SELECT * FROM setores WHERE id = ?').get(id) || falhar(404, 'Setor não encontrado.');
    const n = q('SELECT COUNT(*) AS n FROM colaboradores WHERE setor_id = ?').get(id).n;
    if (n) falhar(409, `O setor possui ${n} colaborador(es). Remova-os ou altere o setor antes.`);
    q('DELETE FROM setores WHERE id = ?').run(id);
    auditar(ator, 'setor.excluir', s.nome);
  }

  // ---------------------------------------------------- colaboradores

  function normalizarColab(d) {
    const sexo = String(d.sexo || '').toUpperCase();
    if (!['F', 'M'].includes(sexo)) falhar(400, 'Sexo deve ser F ou M.');
    if (!M.JORNADAS[d.jornada]) falhar(400, 'Jornada inválida.');
    const entrada = String(d.entrada || '');
    if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(entrada)) falhar(400, 'Horário de entrada inválido (use HH:MM).');
    if (!q('SELECT 1 FROM setores WHERE id = ?').get(d.setorId)) falhar(400, 'Setor não encontrado.');
    return {
      nome: texto(d.nome, 'o nome do colaborador', 100),
      matricula: texto(d.matricula, 'a matrícula', 20),
      sexo, setorId: d.setorId, jornada: d.jornada, entrada,
    };
  }

  function gravarColab(c, id) {
    const repetida = q('SELECT id FROM colaboradores WHERE matricula = ?').get(c.matricula);
    if (repetida && repetida.id !== id) falhar(409, `A matrícula ${c.matricula} já está cadastrada.`);
    if (id) {
      const r = q('UPDATE colaboradores SET nome = ?, matricula = ?, sexo = ?, setor_id = ?, jornada = ?, entrada = ? WHERE id = ?')
        .run(c.nome, c.matricula, c.sexo, c.setorId, c.jornada, c.entrada, id);
      if (!r.changes) falhar(404, 'Colaborador não encontrado.');
      return id;
    }
    const novo = novoId();
    q('INSERT INTO colaboradores (id, nome, matricula, sexo, setor_id, jornada, entrada) VALUES (?, ?, ?, ?, ?, ?, ?)')
      .run(novo, c.nome, c.matricula, c.sexo, c.setorId, c.jornada, c.entrada);
    return novo;
  }

  function salvarColaborador(ator, d) {
    exigir(ator, 'operador');
    const c = normalizarColab(d);
    const id = gravarColab(c, d.id);
    auditar(ator, d.id ? 'colaborador.alterar' : 'colaborador.criar', `${c.matricula} ${c.nome}`);
    return colabDeLinha(q('SELECT * FROM colaboradores WHERE id = ?').get(id));
  }

  function removerColaborador(ator, id) {
    exigir(ator, 'operador');
    const c = q('SELECT * FROM colaboradores WHERE id = ?').get(id) || falhar(404, 'Colaborador não encontrado.');
    q('DELETE FROM colaboradores WHERE id = ?').run(id);
    auditar(ator, 'colaborador.excluir', `${c.matricula} ${c.nome}`);
  }

  /** Importação em lote (CSV). Setores inexistentes são criados (seg a sáb). */
  function importarColaboradores(ator, linhas) {
    exigir(ator, 'operador');
    if (!Array.isArray(linhas) || !linhas.length) falhar(400, 'Nenhuma linha para importar.');
    if (linhas.length > 5000) falhar(400, 'Importe no máximo 5000 colaboradores por vez.');
    const ignorados = [];
    let importados = 0;
    db.transacao(() => {
      linhas.forEach((l, i) => {
        const ref = `linha ${l.linha || i + 2}`;
        try {
          const nomeSetor = texto(l.setor, 'o setor', 60);
          let setor = q('SELECT id FROM setores WHERE nome = ? COLLATE NOCASE').get(nomeSetor);
          if (!setor) {
            setor = { id: novoId() };
            q('INSERT INTO setores (id, nome, minimo_por_dia, dias_funcionamento, funciona_feriados) VALUES (?, ?, 1, ?, 0)')
              .run(setor.id, nomeSetor, JSON.stringify([false, true, true, true, true, true, true]));
          }
          const entrada = /^\d{1,2}:\d{2}$/.test(String(l.entrada || '')) ? String(l.entrada).padStart(5, '0') : '08:00';
          const c = normalizarColab({ ...l, setorId: setor.id, jornada: l.jornada || '6x1', entrada, sexo: String(l.sexo || '').charAt(0) });
          if (q('SELECT 1 FROM colaboradores WHERE matricula = ?').get(c.matricula)) throw new ErroApp(409, 'matrícula repetida');
          gravarColab(c, null);
          importados++;
        } catch (e) {
          if (!(e instanceof ErroApp)) throw e;
          ignorados.push(`${ref} (${e.message.replace(/\.$/, '')})`);
        }
      });
    });
    auditar(ator, 'colaborador.importar', `${importados} importado(s), ${ignorados.length} ignorado(s)`);
    return { importados, ignorados };
  }

  // ------------------------------------------------- regras e feriados

  function salvarConfig(ator, d) {
    exigir(ator, 'operador');
    const st = q('INSERT INTO configuracoes (chave, valor) VALUES (?, ?) ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor');
    if (d.domingoHomensSemanas != null) {
      const v = Number(d.domingoHomensSemanas);
      if (![3, 7].includes(v)) falhar(400, 'Regra de domingos inválida.');
      st.run('domingoHomensSemanas', JSON.stringify(v));
    }
    if (d.incluirFacultativos != null) st.run('incluirFacultativos', JSON.stringify(!!d.incluirFacultativos));
    const c = config();
    auditar(ator, 'regras.alterar', `domingo dos homens a cada ${c.regras.domingoHomensSemanas} semanas; ` +
      `Carnaval/Corpus Christi como feriado: ${c.incluirFacultativos ? 'sim' : 'não'}`);
    return c;
  }

  function salvarFeriado(ator, d) {
    exigir(ator, 'operador');
    const data = dataValida(d.data, 'Data');
    const nome = texto(d.nome, 'o nome do feriado', 80);
    q('INSERT INTO feriados (data, nome) VALUES (?, ?) ON CONFLICT(data) DO UPDATE SET nome = excluded.nome').run(data, nome);
    auditar(ator, 'feriado.salvar', `${dataBR(data)} ${nome}`);
  }

  function removerFeriado(ator, data) {
    exigir(ator, 'operador');
    q('DELETE FROM feriados WHERE data = ?').run(String(data));
    auditar(ator, 'feriado.excluir', dataBR(String(data)));
  }

  // ------------------------------------------------------------ escala

  function configMotor(inicio, fim) {
    const c = config();
    return {
      inicio, fim, setores: lerSetores(), colaboradores: lerColaboradores(),
      feriadosExtras: q('SELECT data, nome FROM feriados').all().map((f) => ({ ...f })),
      regras: c.regras, incluirFacultativos: c.incluirFacultativos,
    };
  }

  function gravarEscala(ator, e, nova) {
    const dadosJson = JSON.stringify({ inicio: e.inicio, fim: e.fim, dias: e.dias, celulas: e.celulas });
    if (nova) {
      q(`INSERT INTO escala (id, inicio, fim, dados, gerada_por, gerada_em, atualizada_em) VALUES (1, ?, ?, ?, ?, ?, ?)
         ON CONFLICT(id) DO UPDATE SET inicio = excluded.inicio, fim = excluded.fim, dados = excluded.dados,
         gerada_por = excluded.gerada_por, gerada_em = excluded.gerada_em, atualizada_em = excluded.atualizada_em`)
        .run(e.inicio, e.fim, dadosJson, ator.login, iso(), iso());
    } else {
      q('UPDATE escala SET dados = ?, atualizada_em = ? WHERE id = 1').run(dadosJson, iso());
    }
  }

  function gerarEscala(ator, d) {
    exigir(ator, 'operador');
    const inicio = dataValida(d.inicio, 'Data inicial');
    const fim = dataValida(d.fim, 'Data final');
    if (inicio > fim) falhar(400, 'A data final deve ser posterior à inicial.');
    if ((M.parseData(fim) - M.parseData(inicio)) / 86400000 + 1 > MAX_DIAS_ESCALA) falhar(400, 'Gere no máximo 3 meses por vez.');
    const cfg = configMotor(inicio, fim);
    if (!cfg.colaboradores.length) falhar(400, 'Cadastre colaboradores primeiro.');
    const e = M.gerarEscala(cfg);
    gravarEscala(ator, e, true);
    const erros = M.validarEscala(cfg, e).filter((o) => o.nivel === 'erro').length;
    auditar(ator, 'escala.gerar', `${dataBR(inicio)} a ${dataBR(fim)}${erros ? `, ${erros} violação(ões)` : ''}`);
    return lerEscala();
  }

  /** Alterna uma célula entre trabalho e folga. */
  function alterarCelula(ator, d) {
    exigir(ator, 'operador');
    const e = lerEscala() || falhar(404, 'Nenhuma escala gerada.');
    const c = q('SELECT * FROM colaboradores WHERE id = ?').get(d.colaboradorId) || falhar(404, 'Colaborador não encontrado.');
    const cel = e.celulas[c.id] || falhar(400, 'Colaborador não faz parte desta escala. Gere a escala novamente.');
    const i = Number(d.indice);
    if (!Number.isInteger(i) || i < 0 || i >= cel.length) falhar(400, 'Dia inválido.');
    cel[i] = cel[i].tipo === 'T' ? { tipo: e.dias[i].feriado ? 'FER' : 'F' } : M.turnoTrabalho(colabDeLinha(c));
    gravarEscala(ator, e, false);
    auditar(ator, 'escala.ajuste', `${c.matricula} ${c.nome} em ${dataBR(e.dias[i].data)}: ${cel[i].tipo === 'T' ? 'trabalho' : 'folga'}`);
    return lerEscala();
  }

  // ------------------------------------------- exemplo, limpeza, backup

  function limparTabelas() {
    db.exec('DELETE FROM escala; DELETE FROM colaboradores; DELETE FROM setores; DELETE FROM feriados; DELETE FROM configuracoes;');
  }

  function carregarExemplo(ator) {
    exigir(ator, 'operador');
    const todos = [true, true, true, true, true, true, true];
    const setores = [
      ['Vendas', 4, todos, true], ['Administrativo', 1, [false, true, true, true, true, true, false], false],
      ['Segurança', 1, todos, true],
    ];
    const pessoas = [
      ['Ana Souza', 'F', 0, '6x1', '08:00'], ['Bruno Lima', 'M', 0, '6x1', '08:00'],
      ['Carla Mendes', 'F', 0, '6x1', '10:00'], ['Diego Alves', 'M', 0, '6x1', '10:00'],
      ['Eduarda Rocha', 'F', 0, '6x1', '12:00'], ['Felipe Costa', 'M', 0, '6x1', '12:00'],
      ['Gabriela Nunes', 'F', 0, '6x1', '13:00'], ['Henrique Dias', 'M', 0, '6x1', '13:00'],
      ['Isabela Martins', 'F', 1, '5x2', '08:00'], ['João Pereira', 'M', 1, '5x2-40', '09:00'],
      ['Karina Ferreira', 'F', 2, '12x36', '07:00'], ['Lucas Oliveira', 'M', 2, '12x36', '07:00'],
      ['Marcos Ribeiro', 'M', 2, '12x36', '19:00'], ['Natália Gomes', 'F', 2, '12x36', '19:00'],
    ];
    db.transacao(() => {
      limparTabelas();
      const ids = setores.map(([nome, minimo, dias, fer]) => {
        const id = novoId();
        q('INSERT INTO setores (id, nome, minimo_por_dia, dias_funcionamento, funciona_feriados) VALUES (?, ?, ?, ?, ?)')
          .run(id, nome, minimo, JSON.stringify(dias), fer ? 1 : 0);
        return id;
      });
      pessoas.forEach(([nome, sexo, s, jornada, entrada], k) => {
        q('INSERT INTO colaboradores (id, nome, matricula, sexo, setor_id, jornada, entrada) VALUES (?, ?, ?, ?, ?, ?, ?)')
          .run(novoId(), nome, String(10001 + k), sexo, ids[s], jornada, entrada);
      });
    });
    auditar(ator, 'dados.exemplo', null);
  }

  function limparDados(ator) {
    exigir(ator, 'admin');
    db.transacao(limparTabelas);
    auditar(ator, 'dados.limpar', null);
  }

  function backup(ator) {
    exigir(ator, 'admin');
    const d = dados(ator);
    auditar(ator, 'dados.backup', null);
    return { versao: 1, exportadoEm: iso(), ...d };
  }

  function restaurar(ator, b) {
    exigir(ator, 'admin');
    if (!b || !Array.isArray(b.setores) || !Array.isArray(b.colaboradores)) falhar(400, 'Arquivo de backup inválido.');
    db.transacao(() => {
      limparTabelas();
      const mapaSetor = {};
      for (const s of b.setores) {
        const n = normalizarSetor(s);
        const id = novoId();
        mapaSetor[s.id] = id;
        q('INSERT INTO setores (id, nome, minimo_por_dia, dias_funcionamento, funciona_feriados) VALUES (?, ?, ?, ?, ?)')
          .run(id, n.nome, n.minimo, JSON.stringify(n.dias), n.feriados ? 1 : 0);
      }
      const mapaColab = {};
      for (const c of b.colaboradores) {
        const n = normalizarColab({ ...c, setorId: mapaSetor[c.setorId] });
        mapaColab[c.id] = gravarColab(n, null);
      }
      for (const f of b.feriadosExtras || []) {
        q('INSERT OR REPLACE INTO feriados (data, nome) VALUES (?, ?)').run(dataValida(f.data, 'Data'), texto(f.nome, 'o nome do feriado', 80));
      }
      const st = q('INSERT INTO configuracoes (chave, valor) VALUES (?, ?)');
      if (b.regras && [3, 7].includes(Number(b.regras.domingoHomensSemanas))) {
        st.run('domingoHomensSemanas', JSON.stringify(Number(b.regras.domingoHomensSemanas)));
      }
      st.run('incluirFacultativos', JSON.stringify(!!b.incluirFacultativos));
      const e = b.escala;
      if (e && e.inicio && e.fim && Array.isArray(e.dias) && e.celulas && typeof e.celulas === 'object') {
        const celulas = {};
        for (const [idAntigo, lista] of Object.entries(e.celulas)) {
          if (mapaColab[idAntigo] && Array.isArray(lista) && lista.length === e.dias.length) celulas[mapaColab[idAntigo]] = lista;
        }
        gravarEscala(ator, { inicio: dataValida(e.inicio, 'Data'), fim: dataValida(e.fim, 'Data'), dias: e.dias, celulas }, true);
      }
    });
    auditar(ator, 'dados.restaurar', `${b.setores.length} setor(es), ${b.colaboradores.length} colaborador(es)`);
  }

  return {
    temUsuarios, criarPrimeiroAdmin, login, sessao, logout, alterarMinhaSenha,
    listarUsuarios, criarUsuario, atualizarUsuario, removerUsuario, auditoria,
    dados, salvarSetor, removerSetor, salvarColaborador, removerColaborador, importarColaboradores,
    salvarConfig, salvarFeriado, removerFeriado, gerarEscala, alterarCelula,
    carregarExemplo, limparDados, backup, restaurar,
  };
}

module.exports = { criarServico, ErroApp, PERFIS };
