/*
 * Regras de negócio do servidor: usuários, sessões, permissões, cadastros
 * e escala. Independente de HTTP para poder ser testado diretamente.
 */
'use strict';

const crypto = require('node:crypto');
const M = require('../js/motor.js');
const CT = require('../js/contrato-modelo.js');
const K = require('../js/distrato-calculo.js');
const CU = require('../js/custos-calculo.js');

/** Séries de índices disponíveis (Sistema Gerenciador de Séries do Banco Central). */
const SERIES = { igpm: { sgs: 189, nome: 'IGP-M (FGV)' } };

/** Cadastro de empresas: regimes tributários e arquivos que podem ser anexados (extensões aceitas). */
const REGIMES_EMPRESA = ['Simples Nacional', 'Lucro Presumido', 'Lucro Real', 'MEI', 'Outro'];
const ARQUIVOS_EMPRESA = {
  contrato: { nome: 'Modelo de contrato', extensoes: ['docx', 'doc', 'pdf', 'odt'] },
  distrato: { nome: 'Modelo de distrato', extensoes: ['docx', 'doc', 'pdf', 'odt'] },
  planilha: { nome: 'Modelo de planilha de comissões para distrato', extensoes: ['xlsx', 'xls', 'ods', 'csv', 'pdf'] },
  logo: { nome: 'Logotipo', extensoes: ['png', 'jpg', 'jpeg'] },
};
const TIPOS_MIME = {
  docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', doc: 'application/msword',
  pdf: 'application/pdf', odt: 'application/vnd.oasis.opendocument.text',
  xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', xls: 'application/vnd.ms-excel',
  ods: 'application/vnd.oasis.opendocument.spreadsheet', csv: 'text/csv', png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg',
};
const MAX_ARQUIVO = 10 * 1024 * 1024;
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

/** Dados vindos do sistema de folha (planilha de empregados) e tamanho máximo de cada um. */
const TEXTOS_FOLHA = {
  codigoESocial: 30, cbo: 10, centroCustoCodigo: 20, departamentoCodigo: 20, departamento: 80,
  estabelecimentoCodigo: 20, estabelecimento: 120, sindicatoCodigo: 20, sindicato: 150,
};

/** Dados contratuais do colaborador usados nos custos (coluna rh, em JSON). */
function rhPadrao(rh) {
  const r = rh || {};
  const beneficios = {};
  for (const b of CU.BENEFICIOS) beneficios[b.id] = r.beneficios && r.beneficios[b.id] !== '' && r.beneficios[b.id] != null ? r.beneficios[b.id] : '';
  return {
    cargo: r.cargo || '', salario: r.salario == null ? '' : r.salario, admissao: r.admissao || '',
    desligamento: r.desligamento || '', tipoDesligamento: r.tipoDesligamento || '',
    motivoDesligamento: r.motivoDesligamento || '', obsDesligamento: r.obsDesligamento || '',
    feriasVencidas: r.feriasVencidas || 0, inicioAquisitivo: r.inicioAquisitivo || '', beneficios,
    ...Object.fromEntries(Object.keys(TEXTOS_FOLHA).map((k) => [k, r[k] || ''])),
    nascimento: r.nascimento || '', pcd: !!r.pcd, semControleJornada: r.semControleJornada || '',
  };
}

const colabDeLinha = (c) => ({
  id: c.id, nome: c.nome, matricula: c.matricula, sexo: c.sexo,
  setorId: c.setor_id, jornada: c.jornada, entrada: c.entrada,
  ...rhPadrao(JSON.parse(c.rh || '{}')),
});

/** Perfil Consulta não vê salário, benefícios nem os motivos do desligamento. */
const colabSemCustos = (c) => ({
  id: c.id, nome: c.nome, matricula: c.matricula, sexo: c.sexo, setorId: c.setorId, jornada: c.jornada,
  entrada: c.entrada, cargo: c.cargo, admissao: c.admissao, desligamento: c.desligamento,
  centroCustoCodigo: c.centroCustoCodigo, departamento: c.departamento, estabelecimento: c.estabelecimento,
  semControleJornada: c.semControleJornada,
});

// ---------------------------------------------------------------- serviço

function criarServico(db, opcoes = {}) {
  const agora = opcoes.agora || (() => Date.now());
  const iso = () => new Date(agora()).toISOString();
  const paramsHash = opcoes.paramsHash || senhas.PADRAO;
  const hashSenha = (s) => senhas.gerarHash(s, paramsHash);
  const buscarUrl = opcoes.buscar || ((url, o) => fetch(url, o));
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
      regras: {
        domingoHomensSemanas: c.domingoHomensSemanas || 3,
        domingoMulheresSemanas: 2,
        evitarFolgaFeriado: !!c.evitarFolgaFeriado,
        maxFolgasSeguidas: c.maxFolgasSeguidas || 0,
      },
      incluirFacultativos: !!c.incluirFacultativos,
    };
  }

  function lerSetores() {
    return q('SELECT * FROM setores ORDER BY nome COLLATE NOCASE').all().map(setorDeLinha);
  }

  function lerColaboradores() {
    return q('SELECT * FROM colaboradores ORDER BY nome COLLATE NOCASE').all().map(colabDeLinha);
  }

  const escalaDeLinha = (e) => Object.assign(JSON.parse(e.dados), {
    escopo: e.escopo, geradaEm: e.gerada_em, atualizadaEm: e.atualizada_em, geradaPor: e.gerada_por,
  });

  /** Escala de um escopo: '' (todos os colaboradores) ou o código do centro de custo. */
  function lerEscala(escopo = '') {
    const e = q('SELECT * FROM escalas WHERE escopo = ?').get(String(escopo || ''));
    return e ? escalaDeLinha(e) : null;
  }

  function lerEscalas() {
    return Object.fromEntries(q('SELECT * FROM escalas').all().map((e) => [e.escopo, escalaDeLinha(e)]));
  }

  function escopoValido(v) {
    const escopo = String(v || '').trim();
    if (escopo && !q('SELECT 1 FROM centros_custo WHERE codigo = ?').get(escopo)) falhar(400, `Centro de custo ${escopo} não cadastrado.`);
    return escopo;
  }
  const nomeEscopo = (escopo) => {
    if (!escopo) return 'todos os colaboradores';
    const c = q('SELECT nome FROM centros_custo WHERE codigo = ?').get(escopo);
    return `centro de custo ${escopo}${c ? ` ${c.nome}` : ''}`;
  };

  function dados(ator) {
    exigir(ator, 'consulta');
    const escala = lerEscala('');
    const verCustos = NIVEL[ator.perfil] >= NIVEL.operador;
    return {
      setores: lerSetores(),
      centrosCusto: lerCentrosCusto(),
      colaboradores: verCustos ? lerColaboradores() : lerColaboradores().map(colabSemCustos),
      feriadosExtras: q('SELECT data, nome FROM feriados ORDER BY data').all().map((f) => ({ ...f })),
      ...config(),
      escala,
      escalas: lerEscalas(),
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
      sexo, setorId: d.setorId, jornada: d.jornada, entrada, rh: normalizarRH(d),
    };
  }

  /** Valor numérico opcional ('' quando vazio). */
  function numeroOpcional(v, rotulo, max) {
    const n = CU.lerNumero(v);
    if (n == null) {
      if (v != null && String(v).trim() !== '') falhar(400, `${rotulo}: valor inválido.`);
      return '';
    }
    if (n < 0 || n > max) falhar(400, `${rotulo}: valor inválido.`);
    return CU.centavos(n);
  }

  function normalizarRH(d) {
    const cargo = String(d.cargo || '').trim();
    if (cargo.length > 60) falhar(400, 'Cargo deve ter no máximo 60 caracteres.');
    const admissao = d.admissao ? dataValida(d.admissao, 'Data de admissão') : '';
    const desligamento = d.desligamento ? dataValida(d.desligamento, 'Data de desligamento') : '';
    if (admissao && desligamento && desligamento < admissao) falhar(400, 'A data de desligamento deve ser posterior à admissão.');
    let tipo = '';
    if (desligamento) {
      tipo = CU.TIPOS_DESLIGAMENTO[d.tipoDesligamento] ? d.tipoDesligamento : falhar(400, 'Informe o tipo de desligamento.');
    }
    const obs = desligamento ? String(d.obsDesligamento || '').trim() : '';
    if (obs.length > 300) falhar(400, 'Observação do desligamento deve ter no máximo 300 caracteres.');
    const vencidas = Number(d.feriasVencidas || 0);
    if (!Number.isInteger(vencidas) || vencidas < 0 || vencidas > 3) falhar(400, 'Férias vencidas: informe de 0 a 3 períodos.');
    const beneficios = {};
    for (const b of CU.BENEFICIOS) beneficios[b.id] = numeroOpcional(d.beneficios && d.beneficios[b.id], b.nome, 100000);
    return {
      cargo, salario: numeroOpcional(d.salario, 'Salário', 10000000), admissao, desligamento, tipoDesligamento: tipo,
      motivoDesligamento: desligamento && CU.MOTIVOS_DESLIGAMENTO[d.motivoDesligamento] ? d.motivoDesligamento : '',
      obsDesligamento: obs, feriasVencidas: vencidas,
      inicioAquisitivo: d.inicioAquisitivo ? dataValida(d.inicioAquisitivo, 'Início do período aquisitivo') : '',
      beneficios, ...dadosFolha(d),
      semControleJornada: semControle(d.semControleJornada),
    };
  }

  function semControle(v) {
    const k = String(v || '').trim();
    if (k && !CU.SEM_CONTROLE_JORNADA[k]) falhar(400, 'Motivo de ausência de controle de jornada inválido.');
    return k;
  }

  const simNao = (v) => (typeof v === 'boolean' ? v : /^(s|sim|true|1|x)$/i.test(String(v || '').trim()));

  function dadosFolha(d) {
    const out = {};
    for (const [k, max] of Object.entries(TEXTOS_FOLHA)) {
      const v = String(d[k] == null ? '' : d[k]).trim();
      if (v.length > max) falhar(400, `${k === 'cbo' ? 'CBO' : k}: no máximo ${max} caracteres.`);
      out[k] = v;
    }
    if (out.cbo && !/^\d{4,6}(-\d)?$/.test(out.cbo)) falhar(400, `CBO inválido: ${out.cbo}.`);
    if (out.centroCustoCodigo && !q('SELECT 1 FROM centros_custo WHERE codigo = ?').get(out.centroCustoCodigo)) {
      falhar(400, `Centro de custo ${out.centroCustoCodigo} não cadastrado.`);
    }
    out.nascimento = d.nascimento ? dataValida(d.nascimento, 'Data de nascimento') : '';
    out.pcd = simNao(d.pcd);
    return out;
  }

  // ------------------------------------------------------- centros de custo

  const lerCentrosCusto = () => q('SELECT codigo, nome FROM centros_custo').all()
    .map((c) => ({ ...c })).sort((a, b) => a.codigo.localeCompare(b.codigo, 'pt-BR', { numeric: true }));

  function normalizarCentro(d) {
    const codigo = texto(d.codigo, 'o código do centro de custo', 20);
    return { codigo, nome: texto(d.nome, 'o nome do centro de custo', 80) };
  }
  const gravarCentro = (c) => q(`INSERT INTO centros_custo (codigo, nome, atualizado_em) VALUES (?, ?, ?)
    ON CONFLICT(codigo) DO UPDATE SET nome = excluded.nome, atualizado_em = excluded.atualizado_em`).run(c.codigo, c.nome, iso());

  function salvarCentroCusto(ator, d) {
    exigir(ator, 'operador');
    const c = normalizarCentro(d);
    const existia = q('SELECT 1 FROM centros_custo WHERE codigo = ?').get(c.codigo);
    gravarCentro(c);
    auditar(ator, existia ? 'centro.alterar' : 'centro.criar', `${c.codigo} ${c.nome}`);
    return lerCentrosCusto();
  }

  function removerCentroCusto(ator, codigo) {
    exigir(ator, 'operador');
    const c = q('SELECT * FROM centros_custo WHERE codigo = ?').get(String(codigo)) || falhar(404, 'Centro de custo não encontrado.');
    const n = lerColaboradores().filter((x) => x.centroCustoCodigo === c.codigo).length;
    if (n) falhar(409, `O centro de custo tem ${n} colaborador(es). Altere-os antes de excluir.`);
    q('DELETE FROM centros_custo WHERE codigo = ?').run(c.codigo);
    auditar(ator, 'centro.excluir', `${c.codigo} ${c.nome}`);
    return lerCentrosCusto();
  }

  /** Importa a lista de centros de custo (código e nome): cria os novos e atualiza o nome dos existentes. */
  function importarCentrosCusto(ator, linhas) {
    exigir(ator, 'operador');
    if (!Array.isArray(linhas) || !linhas.length) falhar(400, 'Nenhum centro de custo para importar.');
    if (linhas.length > 5000) falhar(400, 'Importe no máximo 5000 centros de custo por vez.');
    let novos = 0;
    let atualizados = 0;
    const ignorados = [];
    db.transacao(() => {
      for (const [i, l] of linhas.entries()) {
        try {
          const c = normalizarCentro(l);
          const atual = q('SELECT nome FROM centros_custo WHERE codigo = ?').get(c.codigo);
          if (atual && atual.nome === c.nome) continue;
          gravarCentro(c);
          if (atual) atualizados++; else novos++;
        } catch (e) {
          if (!(e instanceof ErroApp)) throw e;
          ignorados.push(`linha ${l.linha || i + 1} (${e.message.replace(/\.$/, '')})`);
        }
      }
    });
    auditar(ator, 'centro.importar', `${novos} novo(s), ${atualizados} atualizado(s)`);
    return { novos, atualizados, ignorados, centrosCusto: lerCentrosCusto() };
  }

  function gravarColab(c, id) {
    const repetida = q('SELECT id FROM colaboradores WHERE matricula = ?').get(c.matricula);
    if (repetida && repetida.id !== id) falhar(409, `A matrícula ${c.matricula} já está cadastrada.`);
    if (id) {
      const r = q('UPDATE colaboradores SET nome = ?, matricula = ?, sexo = ?, setor_id = ?, jornada = ?, entrada = ?, rh = ? WHERE id = ?')
        .run(c.nome, c.matricula, c.sexo, c.setorId, c.jornada, c.entrada, JSON.stringify(c.rh), id);
      if (!r.changes) falhar(404, 'Colaborador não encontrado.');
      return id;
    }
    const novo = novoId();
    q('INSERT INTO colaboradores (id, nome, matricula, sexo, setor_id, jornada, entrada, rh) VALUES (?, ?, ?, ?, ?, ?, ?, ?)')
      .run(novo, c.nome, c.matricula, c.sexo, c.setorId, c.jornada, c.entrada, JSON.stringify(c.rh));
    return novo;
  }

  function salvarColaborador(ator, d) {
    exigir(ator, 'operador');
    const c = normalizarColab(d);
    const antes = d.id ? q('SELECT rh FROM colaboradores WHERE id = ?').get(d.id) : null;
    const id = gravarColab(c, d.id);
    const desligouAgora = c.rh.desligamento && (!antes || JSON.parse(antes.rh || '{}').desligamento !== c.rh.desligamento);
    auditar(ator, desligouAgora ? 'colaborador.desligar' : d.id ? 'colaborador.alterar' : 'colaborador.criar',
      `${c.matricula} ${c.nome}${desligouAgora ? ` em ${dataBR(c.rh.desligamento)} (${CU.TIPOS_DESLIGAMENTO[c.rh.tipoDesligamento].nome})` : ''}`);
    return colabDeLinha(q('SELECT * FROM colaboradores WHERE id = ?').get(id));
  }

  function removerColaborador(ator, id) {
    exigir(ator, 'operador');
    const c = q('SELECT * FROM colaboradores WHERE id = ?').get(id) || falhar(404, 'Colaborador não encontrado.');
    const n = q('SELECT COUNT(*) AS n FROM folha_lancamentos WHERE colaborador_id = ?').get(id).n;
    if (n) {
      falhar(409, `${c.nome} tem ${n} lançamento(s) de folha. Para manter o histórico de custos e o turnover, ` +
        'registre o desligamento no cadastro em vez de excluir.');
    }
    q('DELETE FROM colaboradores WHERE id = ?').run(id);
    auditar(ator, 'colaborador.excluir', `${c.matricula} ${c.nome}`);
  }

  /** Grupos de dados que a importação pode atualizar, com os campos de cada um. */
  const GRUPOS_IMPORTACAO = {
    nome: ['nome'], sexo: ['sexo'], setor: ['setor'], jornada: ['jornada'], entrada: ['entrada'],
    cargo: ['cargo', 'cbo'], salario: ['salario'], admissao: ['admissao'], centroCusto: ['centroCustoCodigo'],
    departamento: ['departamentoCodigo', 'departamento'], estabelecimento: ['estabelecimentoCodigo', 'estabelecimento'],
    sindicato: ['sindicatoCodigo', 'sindicato'], nascimento: ['nascimento'], pcd: ['pcd'], codigoESocial: ['codigoESocial'],
  };

  /** Setor pelo nome; se não existir, é criado (seg a sáb). */
  function setorPorNome(nome) {
    const nomeSetor = texto(nome, 'o setor', 60);
    let setor = q('SELECT id FROM setores WHERE nome = ? COLLATE NOCASE').get(nomeSetor);
    if (!setor) {
      setor = { id: novoId() };
      q('INSERT INTO setores (id, nome, minimo_por_dia, dias_funcionamento, funciona_feriados) VALUES (?, ?, 1, ?, 0)')
        .run(setor.id, nomeSetor, JSON.stringify([false, true, true, true, true, true, true]));
    }
    return setor.id;
  }
  const horaCSV = (v) => (/^\d{1,2}:\d{2}$/.test(String(v || '')) ? String(v).padStart(5, '0') : null);

  /**
   * Importação em lote (CSV).
   * opcoes.cadastrar: cadastra as matrículas novas (setores inexistentes são criados);
   * opcoes.atualizar: campos que serão atualizados nas matrículas já cadastradas
   * (só os preenchidos na planilha; colunas vazias mantêm o valor atual).
   */
  function importarColaboradores(ator, linhas, opcoes = {}) {
    exigir(ator, 'operador');
    const cadastrar = opcoes.cadastrar !== false;
    const atualizar = Array.isArray(opcoes.atualizar)
      ? opcoes.atualizar.filter((k) => GRUPOS_IMPORTACAO[k]) : ['cargo', 'salario', 'admissao'];
    const preenchido = (v) => v != null && String(v).trim() !== '';
    if (!Array.isArray(linhas) || !linhas.length) falhar(400, 'Nenhuma linha para importar.');
    if (linhas.length > 5000) falhar(400, 'Importe no máximo 5000 colaboradores por vez.');
    const ignorados = [];
    let importados = 0;
    let atualizados = 0;
    let centros = 0;
    db.transacao(() => {
      // centros de custo citados na planilha de empregados entram no cadastro de centros
      const vistos = new Set();
      for (const l of linhas) {
        if (!preenchido(l.centroCustoCodigo) || !preenchido(l.centroCustoNome) || vistos.has(String(l.centroCustoCodigo))) continue;
        vistos.add(String(l.centroCustoCodigo));
        const c = { codigo: String(l.centroCustoCodigo).trim().slice(0, 20), nome: String(l.centroCustoNome).trim().slice(0, 80) };
        const atual = q('SELECT nome FROM centros_custo WHERE codigo = ?').get(c.codigo);
        if (!atual || atual.nome !== c.nome) { gravarCentro(c); centros++; }
      }
      linhas.forEach((l, i) => {
        const ref = `linha ${l.linha || i + 2}`;
        try {
          const existente = q('SELECT * FROM colaboradores WHERE matricula = ?').get(String(l.matricula || '').trim());
          if (existente) {
            if (!atualizar.length) throw new ErroApp(409, 'matrícula já cadastrada');
            const atual = colabDeLinha(existente);
            const campos = atualizar.flatMap((g) => GRUPOS_IMPORTACAO[g]).filter((k) => preenchido(l[k]));
            if (!campos.length) throw new ErroApp(409, 'matrícula já cadastrada, sem dados para atualizar');
            for (const k of campos) {
              const v = String(l[k]).trim();
              if (k === 'setor') atual.setorId = setorPorNome(v);
              else if (k === 'sexo') atual.sexo = v.charAt(0).toUpperCase();
              else if (k === 'entrada') atual.entrada = horaCSV(v) || v;
              else if (k === 'pcd') atual.pcd = simNao(v);
              else atual[k] = v;
            }
            gravarColab(normalizarColab(atual), atual.id);
            atualizados++;
            return;
          }
          if (!cadastrar) throw new ErroApp(409, 'matrícula não cadastrada');
          if (!String(l.nome || '').trim() || !String(l.setor || '').trim()) {
            throw new ErroApp(400, 'matrícula não cadastrada; para cadastrar, informe nome, sexo e setor');
          }
          const setorId = setorPorNome(l.setor);
          const entrada = horaCSV(l.entrada) || '08:00';
          const c = normalizarColab({ ...l, setorId, jornada: l.jornada || '6x1', entrada, sexo: String(l.sexo || '').charAt(0) });
          if (q('SELECT 1 FROM colaboradores WHERE matricula = ?').get(c.matricula)) throw new ErroApp(409, 'matrícula repetida');
          gravarColab(c, null);
          importados++;
        } catch (e) {
          if (!(e instanceof ErroApp)) throw e;
          ignorados.push(`${ref} (${e.message.replace(/\.$/, '')})`);
        }
      });
    });
    auditar(ator, 'colaborador.importar', `${importados} cadastrado(s), ${atualizados} atualizado(s), ${ignorados.length} ignorado(s)` +
      (centros ? `; ${centros} centro(s) de custo novo(s) ou renomeado(s)` : ''));
    return { importados, atualizados, ignorados, centros };
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
    if (d.evitarFolgaFeriado != null) st.run('evitarFolgaFeriado', JSON.stringify(!!d.evitarFolgaFeriado));
    if (d.maxFolgasSeguidas != null) {
      const v = Number(d.maxFolgasSeguidas);
      if (!Number.isInteger(v) || v < 0 || v > 7) falhar(400, 'Limite de folgas seguidas inválido (0 a 7 dias).');
      st.run('maxFolgasSeguidas', JSON.stringify(v));
    }
    const c = config();
    auditar(ator, 'regras.alterar', `domingo dos homens a cada ${c.regras.domingoHomensSemanas} semanas; ` +
      `Carnaval/Corpus Christi como feriado: ${c.incluirFacultativos ? 'sim' : 'não'}; ` +
      `folga em feriado: ${c.regras.evitarFolgaFeriado ? 'evitar' : 'permitida'}; ` +
      `folgas seguidas: ${c.regras.maxFolgasSeguidas ? 'até ' + c.regras.maxFolgasSeguidas + ' dias' : 'sem limite'}`);
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

  function configMotor(inicio, fim, escopo = '', excluirSemControle = true) {
    const c = config();
    // desligados antes do período ou admitidos depois dele ficam fora da escala; com centro de custo, só os dele;
    // quem não tem controle de jornada (CLT art. 62) fica fora, a menos que se peça para incluir
    const ativos = lerColaboradores().filter((c) => (!c.admissao || c.admissao <= fim) && (!c.desligamento || c.desligamento >= inicio) &&
      (!escopo || c.centroCustoCodigo === escopo) && (!excluirSemControle || !c.semControleJornada));
    // só os setores dos colaboradores da escala entram na cobertura mínima
    const setoresUsados = new Set(ativos.map((x) => x.setorId));
    return {
      inicio, fim, setores: lerSetores().filter((s) => !escopo || setoresUsados.has(s.id)), colaboradores: ativos,
      feriadosExtras: q('SELECT data, nome FROM feriados').all().map((f) => ({ ...f })),
      regras: c.regras, incluirFacultativos: c.incluirFacultativos,
    };
  }

  function gravarEscala(ator, e, nova, escopo = '') {
    const dadosJson = JSON.stringify({
      inicio: e.inicio, fim: e.fim, dias: e.dias, celulas: e.celulas, excluirSemControle: e.excluirSemControle !== false,
    });
    if (nova) {
      q(`INSERT INTO escalas (escopo, inicio, fim, dados, gerada_por, gerada_em, atualizada_em) VALUES (?, ?, ?, ?, ?, ?, ?)
         ON CONFLICT(escopo) DO UPDATE SET inicio = excluded.inicio, fim = excluded.fim, dados = excluded.dados,
         gerada_por = excluded.gerada_por, gerada_em = excluded.gerada_em, atualizada_em = excluded.atualizada_em`)
        .run(escopo, e.inicio, e.fim, dadosJson, ator.login, iso(), iso());
    } else {
      q('UPDATE escalas SET dados = ?, atualizada_em = ? WHERE escopo = ?').run(dadosJson, iso(), escopo);
    }
  }

  function gerarEscala(ator, d) {
    exigir(ator, 'operador');
    const inicio = dataValida(d.inicio, 'Data inicial');
    const fim = dataValida(d.fim, 'Data final');
    if (inicio > fim) falhar(400, 'A data final deve ser posterior à inicial.');
    if ((M.parseData(fim) - M.parseData(inicio)) / 86400000 + 1 > MAX_DIAS_ESCALA) falhar(400, 'Gere no máximo 3 meses por vez.');
    const escopo = escopoValido(d.centroCusto);
    const excluirSemControle = d.excluirSemControle !== false;
    const cfg = configMotor(inicio, fim, escopo, excluirSemControle);
    if (!cfg.colaboradores.length) {
      falhar(400, escopo ? 'Nenhum colaborador ativo com controle de jornada neste centro de custo no período.' : 'Cadastre colaboradores primeiro.');
    }
    const e = { ...M.gerarEscala(cfg), excluirSemControle };
    gravarEscala(ator, e, true, escopo);
    const erros = M.validarEscala(cfg, e).filter((o) => o.nivel === 'erro').length;
    auditar(ator, 'escala.gerar', `${nomeEscopo(escopo)}: ${dataBR(inicio)} a ${dataBR(fim)}${erros ? `, ${erros} violação(ões)` : ''}`);
    return lerEscala(escopo);
  }

  function removerEscala(ator, escopo) {
    exigir(ator, 'operador');
    escopo = String(escopo || '');
    if (!q('DELETE FROM escalas WHERE escopo = ?').run(escopo).changes) falhar(404, 'Escala não encontrada.');
    auditar(ator, 'escala.excluir', nomeEscopo(escopo));
  }

  /** Alterna uma célula entre trabalho e folga. */
  function alterarCelula(ator, d) {
    exigir(ator, 'operador');
    const escopo = String(d.centroCusto || '');
    const e = lerEscala(escopo) || falhar(404, 'Nenhuma escala gerada.');
    const c = q('SELECT * FROM colaboradores WHERE id = ?').get(d.colaboradorId) || falhar(404, 'Colaborador não encontrado.');
    const cel = e.celulas[c.id] || falhar(400, 'Colaborador não faz parte desta escala. Gere a escala novamente.');
    const i = Number(d.indice);
    if (!Number.isInteger(i) || i < 0 || i >= cel.length) falhar(400, 'Dia inválido.');
    cel[i] = cel[i].tipo === 'T' ? { tipo: e.dias[i].feriado ? 'FER' : 'F' } : M.turnoTrabalho(colabDeLinha(c));
    gravarEscala(ator, e, false, escopo);
    auditar(ator, 'escala.ajuste', `${c.matricula} ${c.nome} em ${dataBR(e.dias[i].data)}: ${cel[i].tipo === 'T' ? 'trabalho' : 'folga'}` +
      (escopo ? ` (${nomeEscopo(escopo)})` : ''));
    return lerEscala(escopo);
  }

  // ------------------------------------------- exemplo, limpeza, backup

  function limparTabelas() {
    db.exec('DELETE FROM folha_lancamentos; DELETE FROM folha_competencias; DELETE FROM escalas; DELETE FROM colaboradores; DELETE FROM centros_custo; DELETE FROM setores; DELETE FROM feriados; DELETE FROM configuracoes;');
  }

  function carregarExemplo(ator) {
    exigir(ator, 'operador');
    const todos = [true, true, true, true, true, true, true];
    const setores = [
      ['Vendas', 4, todos, true], ['Administrativo', 1, [false, true, true, true, true, true, false], false],
      ['Segurança', 1, todos, true],
    ];
    // [nome, sexo, setor, jornada, entrada, cargo, salário, admissão, extras]
    const atual = new Date(agora()).toISOString().slice(0, 7);
    const mes = (n, dia) => `${CU.somarMes(atual, n)}-${dia}`;
    const pessoas = [
      ['Ana Souza', 'F', 0, '6x1', '08:00', 'Vendedora', 2350, '2021-03-08', { he50: [8, 14] }],
      ['Bruno Lima', 'M', 0, '6x1', '08:00', 'Vendedor', 2350, '2022-07-11', { he50: [0, 6] }],
      ['Carla Mendes', 'F', 0, '6x1', '10:00', 'Supervisora de vendas', 3400, '2019-05-02', { feriasVencidas: 1, saude: 770 }],
      ['Diego Alves', 'M', 0, '6x1', '10:00', 'Vendedor', 2350, '2020-09-14', { feriasVencidas: 2 }],
      ['Eduarda Rocha', 'F', 0, '6x1', '12:00', 'Vendedora', 2250, '2023-01-16', {}],
      ['Felipe Costa', 'M', 0, '6x1', '12:00', 'Vendedor', 2450, '2021-11-03', { he50: [18, 28] }],
      ['Gabriela Nunes', 'F', 0, '6x1', '13:00', 'Vendedora', 2250, '2024-02-05', { banco: [9, 12, 0, 2] }],
      ['Henrique Dias', 'M', 0, '6x1', '13:00', 'Vendedor', 2150, '2024-08-19', {}],
      ['Isabela Martins', 'F', 1, '5x2', '08:00', 'Analista de RH', 4200, '2020-02-10', { banco: [4, 10, 2, 8], saude: 770 }],
      ['João Pereira', 'M', 1, '5x2-40', '09:00', 'Assistente financeiro', 3800, '2022-04-04', { he50: [0, 5], banco: [3, 8, 0, 6] }],
      ['Karina Ferreira', 'F', 2, '12x36', '07:00', 'Vigilante', 2550, '2021-06-01', { he100: true }],
      ['Lucas Oliveira', 'M', 2, '12x36', '07:00', 'Vigilante', 2550, '2023-09-11', { he100: true }],
      ['Marcos Ribeiro', 'M', 2, '12x36', '19:00', 'Vigilante', 2550, '2020-12-07', { he100: true, noturno: 98 }],
      ['Natália Gomes', 'F', 2, '12x36', '19:00', 'Vigilante', 2550, mes(-3, '05'), { noturno: 98 }],
      // desligados no período (histórico para o turnover)
      ['Otávio Prado', 'M', 0, '6x1', '08:00', 'Vendedor', 2350, '2023-02-13', {
        desligamento: mes(-4, '18'), tipoDesligamento: 'pedido', motivoDesligamento: 'concorrencia',
        obsDesligamento: 'Recebeu proposta com salário 15% maior.' }],
      ['Paula Teixeira', 'F', 0, '6x1', '10:00', 'Vendedora', 2250, mes(-9, '03'), {
        desligamento: mes(-2, '10'), tipoDesligamento: 'sem_justa', motivoDesligamento: 'desempenho' }],
      ['Rafael Moura', 'M', 2, '12x36', '19:00', 'Vigilante', 2550, mes(-5, '02'), {
        desligamento: CU.ultimoDia(CU.somarMes(atual, -3)), tipoDesligamento: 'termino', motivoDesligamento: 'fim_contrato', noturno: 98 }],
    ];
    // gerador pseudoaleatório determinístico: o exemplo sai igual a cada carga
    let semente = 20240611;
    const sorteio = () => {
      semente = (semente * 1103515245 + 12345) % 2147483648;
      return semente / 2147483648;
    };
    const entre = (a, b) => Math.round(a + sorteio() * (b - a));
    const motivos = Object.keys(CU.MOTIVOS_ATESTADO);
    db.transacao(() => {
      limparTabelas();
      const ids = setores.map(([nome, minimo, dias, fer]) => {
        const id = novoId();
        q('INSERT INTO setores (id, nome, minimo_por_dia, dias_funcionamento, funciona_feriados) VALUES (?, ?, ?, ?, ?)')
          .run(id, nome, minimo, JSON.stringify(dias), fer ? 1 : 0);
        return id;
      });
      const centros = [['1', 'ADMINISTRATIVO'], ['3', 'COMERCIAL'], ['42', 'PORTARIA']];
      for (const [codigo, nome] of centros) gravarCentro({ codigo, nome });
      const colabs = pessoas.map(([nome, sexo, s, jornada, entrada, cargo, salario, admissao, x], k) => {
        const c = {
          centroCustoCodigo: [centros[1], centros[0], centros[2]][s][0], departamento: setores[s][0].toUpperCase(),
          estabelecimento: 'MATRIZ', nascimento: `${1970 + ((k * 7) % 33)}-${String((k % 12) + 1).padStart(2, '0')}-15`,
          pcd: nome === 'Henrique Dias',
          id: novoId(), nome, matricula: String(10001 + k), sexo, setorId: ids[s], jornada, entrada, cargo, salario, admissao,
          desligamento: x.desligamento || '', tipoDesligamento: x.tipoDesligamento || '', motivoDesligamento: x.motivoDesligamento || '',
          obsDesligamento: x.obsDesligamento || '', feriasVencidas: x.feriasVencidas || 0, inicioAquisitivo: '',
          beneficios: {
            vt: jornada === '12x36' ? 120 : 176, vr: s === 1 ? 660 : 550, va: 250, saude: x.saude || 385, seguro: 14.9, outrosBeneficios: '',
          },
          extras: x, setor: s,
        };
        const n = normalizarColab(c);
        q('INSERT INTO colaboradores (id, nome, matricula, sexo, setor_id, jornada, entrada, rh) VALUES (?, ?, ?, ?, ?, ?, ?, ?)')
          .run(c.id, n.nome, n.matricula, n.sexo, n.setorId, n.jornada, n.entrada, JSON.stringify(n.rh));
        return c;
      });
      // seis meses de folha com horas extras, ocorrências, banco de horas e sinistralidade do plano de saúde
      const fatores = [0.58, 0.64, 0.71, 0.69, 0.78, 0.82];
      CU.listarCompetencias(CU.somarMes(atual, -6), CU.somarMes(atual, -1)).forEach((comp, m) => {
        garantirCompetencia(comp);
        let premio = 0;
        for (const c of colabs) {
          if (!CU.ativoNoMes(c, comp)) continue;
          const x = c.extras;
          const l = lancamentoPadrao(c);
          // mês de admissão ou de desligamento: salário proporcional aos dias
          const ini = c.admissao > CU.primeiroDia(comp) ? Number(c.admissao.slice(8)) : 1;
          const fim = c.desligamento && c.desligamento < CU.ultimoDia(comp) ? Number(c.desligamento.slice(8)) : 30;
          const dias = Math.min(30, fim) - ini + 1;
          l.salario = CU.centavos(c.salario * dias / 30);
          if (c.setor === 2) l.adicionais = CU.centavos(l.salario * 0.3); // periculosidade dos vigilantes (CLT art. 193)
          if (x.he50) l.he50 = entre(x.he50[0], x.he50[1]);
          else if (sorteio() < 0.2) l.he50 = entre(1, 4);
          if (x.he100 && sorteio() < 0.35) l.he100 = 12;
          if (x.noturno) l.noturno = Math.round(x.noturno * dias / 30);
          if (sorteio() < 0.1) l.faltas = c.jornada === '12x36' ? 12 : 7.33;
          if (sorteio() < 0.25) l.atrasos = entre(1, 4) / 2;
          if (sorteio() < 0.15) { l.atestadoDias = entre(1, 3); l.atestadoMotivo = motivos[entre(0, motivos.length - 1)]; }
          if (c.nome === 'Diego Alves' && m === 4) { l.atestadoDias = 18; l.atestadoMotivo = 'osteomuscular'; }
          if (c.nome === 'Eduarda Rocha' && m >= 3) { l.atestadoDias = entre(2, 4); l.atestadoMotivo = 'mental'; }
          if (x.banco) { l.bhCredito = entre(x.banco[0], x.banco[1]); l.bhDebito = entre(x.banco[2], x.banco[3]); }
          if (c.desligamento && c.desligamento.slice(0, 7) === comp) { l.vt = CU.centavos(l.vt * dias / 30); l.vr = CU.centavos(l.vr * dias / 30); }
          premio += l.saude;
          gravarLancamento(comp, c.id, normalizarLancamento(l, c.nome));
        }
        q('UPDATE folha_competencias SET dados = ? WHERE competencia = ?')
          .run(JSON.stringify({ premioSaude: '', sinistrosSaude: CU.centavos(premio * fatores[m]) }), comp);
      });
    });
    auditar(ator, 'dados.exemplo', null);
  }

  function limparDados(ator) {
    exigir(ator, 'admin');
    db.transacao(limparTabelas);
    auditar(ator, 'dados.limpar', null);
  }

  // ------------------------------------------- contratos de representante

  const SITUACOES = ['ativo', 'encerrado'];

  /** Mantém só os campos conhecidos do modelo e valida o que foi preenchido. */
  function normalizarContrato(d) {
    const out = {};
    for (const c of CT.CAMPOS) {
      if (c.tipo === 'check') { out[c.id] = d[c.id] !== false; continue; }
      if (c.tipo === 'estados') {
        const lista = CT.listaEstados(Array.isArray(d[c.id]) ? d[c.id].join(',') : d[c.id]);
        if (lista.length > 1) falhar(400, 'Estado de atuação: selecione apenas um estado.');
        out[c.id] = lista.join('');
        continue;
      }
      let v = d[c.id] == null ? '' : String(d[c.id]).trim();
      if (c.max && v.length > c.max) falhar(400, `${c.rotulo}: no máximo ${c.max} caracteres.`);
      if (c.tipo === 'cpf') v = v ? CT.formatarCPF(v) : '';
      if (c.tipo === 'cnpj') v = v ? CT.formatarCNPJ(v) : '';
      if (c.tipo === 'cep') v = v ? CT.formatarCEP(v) : '';
      if (c.tipo === 'uf') v = v.toUpperCase();
      if (c.tipo === 'sexo' && v && !['F', 'M'].includes(v)) falhar(400, 'Sexo deve ser F ou M.');
      if (c.tipo === 'data' && v) dataValida(v, c.rotulo);
      out[c.id] = v;
    }
    // só os documentos do modelo do estado de atuação (RS/SC não tem o contrato da Antoniazzi Alimentos)
    const disponiveis = CT.documentosDaRegiao(out);
    // modelos de contrato anexados por empresas representadas entram como 'arq:<id do arquivo>'
    const anexoValido = (x) => {
      const id = /^arq:([\w-]{1,64})$/.exec(x);
      const l = id && q(`SELECT e.dados FROM empresas_arquivos a JOIN empresas e ON e.id = a.empresa_id
        WHERE a.id = ? AND a.tipo = 'contrato'`).get(id[1]);
      return !!l && JSON.parse(l.dados).representada === true;
    };
    const docs = Array.isArray(d.documentos)
      ? d.documentos.filter((x) => typeof x === 'string' && (disponiveis.some((y) => y.id === x) || anexoValido(x))) : [];
    out.documentos = docs.length ? [...new Set(docs)] : disponiveis.map((x) => x.id);
    out.situacao = SITUACOES.includes(d.situacao) ? d.situacao : 'ativo';
    // para salvar basta identificar o representante; o restante pode ser completado depois
    if (!out.razao) falhar(400, 'Informe a razão social do representante.');
    if (!out.cnpj) falhar(400, 'Informe o CNPJ do representante.');
    for (const p of CT.pendencias(out)) {
      if (/inválid|dígitos/.test(p.mensagem)) falhar(400, p.mensagem);
    }
    return out;
  }

  const contratoDeLinha = (l) => ({
    id: l.id, ...JSON.parse(l.dados), situacao: l.situacao,
    criadoPor: l.criado_por, criadoEm: l.criado_em, atualizadoEm: l.atualizado_em,
  });

  function listarContratos(ator) {
    exigir(ator, 'consulta');
    return q('SELECT * FROM contratos_representante ORDER BY razao_social COLLATE NOCASE').all().map((l) => {
      const c = contratoDeLinha(l);
      return { ...c, pendencias: CT.pendencias(c).length };
    });
  }

  function salvarContrato(ator, d) {
    exigir(ator, 'operador');
    const c = normalizarContrato(d);
    const repetido = q("SELECT id FROM contratos_representante WHERE cnpj = ? AND situacao = 'ativo'").get(c.cnpj);
    if (repetido && repetido.id !== d.id && c.situacao === 'ativo') {
      falhar(409, `Já existe um contrato ativo para o CNPJ ${c.cnpj}.`);
    }
    const { situacao, ...dadosJson } = c;
    let id = d.id;
    if (id) {
      const r = q('UPDATE contratos_representante SET razao_social = ?, cnpj = ?, situacao = ?, dados = ?, atualizado_em = ? WHERE id = ?')
        .run(c.razao, c.cnpj, situacao, JSON.stringify(dadosJson), iso(), id);
      if (!r.changes) falhar(404, 'Contrato não encontrado.');
      auditar(ator, 'contrato.alterar', `${c.razao} (${c.cnpj})${situacao === 'encerrado' ? ', encerrado' : ''}`);
    } else {
      id = novoId();
      q(`INSERT INTO contratos_representante (id, razao_social, cnpj, situacao, dados, criado_por, criado_em, atualizado_em)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?)`).run(id, c.razao, c.cnpj, situacao, JSON.stringify(dadosJson), ator.login, iso(), iso());
      auditar(ator, 'contrato.criar', `${c.razao} (${c.cnpj})`);
    }
    const salvo = contratoDeLinha(q('SELECT * FROM contratos_representante WHERE id = ?').get(id));
    return { ...salvo, pendencias: CT.pendencias(salvo).length };
  }

  function removerContrato(ator, id) {
    exigir(ator, 'operador');
    const l = q('SELECT * FROM contratos_representante WHERE id = ?').get(id) || falhar(404, 'Contrato não encontrado.');
    const n = q('SELECT COUNT(*) AS n FROM distratos WHERE contrato_id = ?').get(id).n;
    if (n) falhar(409, `O contrato possui ${n} distrato(s) registrado(s). Exclua os distratos antes.`);
    q('DELETE FROM contratos_representante WHERE id = ?').run(id);
    auditar(ator, 'contrato.excluir', `${l.razao_social} (${l.cnpj})`);
  }

  /** Registra no histórico que o documento foi gerado (PDF ou Word). */
  function registrarDocumento(ator, id, formato) {
    exigir(ator, 'consulta');
    const l = q('SELECT * FROM contratos_representante WHERE id = ?').get(id) || falhar(404, 'Contrato não encontrado.');
    const nomes = { pdf: 'PDF', docx: 'Word', modelo: 'Word preenchido a partir do modelo da empresa' };
    if (!nomes[formato]) falhar(400, 'Formato inválido.');
    auditar(ator, 'contrato.documento', `${l.razao_social}: ${nomes[formato]}`);
  }

  // ------------------------------------------------------------- índices

  function lerIndices(serie) {
    const out = {};
    for (const l of q('SELECT mes, valor FROM indices WHERE serie = ? ORDER BY mes').all(serie)) out[l.mes] = l.valor;
    return out;
  }

  function serieValida(serie) {
    return SERIES[serie] || falhar(404, 'Índice não disponível.');
  }

  function indices(ator, serie) {
    exigir(ator, 'consulta');
    const s = serieValida(serie);
    const meses = lerIndices(serie);
    const info = q('SELECT MAX(atualizado_em) AS em FROM indices WHERE serie = ? AND fonte = ?').get(serie, 'bcb');
    const manuais = q('SELECT mes FROM indices WHERE serie = ? AND fonte = ? ORDER BY mes').all(serie, 'manual').map((l) => l.mes);
    const lista = Object.keys(meses);
    return { serie, nome: s.nome, meses, manuais, ultimoMes: lista[lista.length - 1] || null, atualizadoEm: info.em || null };
  }

  /** Busca a série no Banco Central (API pública do SGS) e grava no banco. */
  async function atualizarIndices(ator, serie) {
    exigir(ator, 'operador');
    const s = serieValida(serie);
    const hoje = new Date(agora());
    const fim = `${String(hoje.getDate()).padStart(2, '0')}/${String(hoje.getMonth() + 1).padStart(2, '0')}/${hoje.getFullYear()}`;
    const url = `https://api.bcb.gov.br/dados/serie/bcdata.sgs.${s.sgs}/dados?formato=json&dataInicial=01/01/2000&dataFinal=${fim}`;
    let lista;
    try {
      const r = await buscarUrl(url, { signal: AbortSignal.timeout(20000), headers: { Accept: 'application/json' } });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      lista = await r.json();
      if (!Array.isArray(lista)) throw new Error('resposta inesperada');
    } catch (e) {
      falhar(502, `Não foi possível consultar o Banco Central (${e.message}). Verifique a conexão com a internet ` +
        'do servidor ou informe os índices manualmente.');
    }
    let n = 0;
    db.transacao(() => {
      const st = q(`INSERT INTO indices (serie, mes, valor, fonte, atualizado_em) VALUES (?, ?, ?, 'bcb', ?)
        ON CONFLICT(serie, mes) DO UPDATE SET valor = excluded.valor, fonte = 'bcb', atualizado_em = excluded.atualizado_em`);
      for (const it of lista) {
        const m = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(String(it.data || ''));
        const v = Number(String(it.valor).replace(',', '.'));
        if (!m || !Number.isFinite(v)) continue;
        st.run(serie, `${m[3]}-${m[2]}`, v, iso());
        n++;
      }
    });
    auditar(ator, 'indice.atualizar', `${s.nome}: ${n} mês(es) obtidos do Banco Central`);
    return indices(ator, serie);
  }

  function salvarIndice(ator, serie, mes, valor) {
    exigir(ator, 'operador');
    const s = serieValida(serie);
    if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(String(mes))) falhar(400, 'Mês inválido.');
    const v = K.lerValor(valor);
    if (v == null || v < -50 || v > 50) falhar(400, 'Informe a variação mensal em % (ex.: 0,41 ou -0,36).');
    q(`INSERT INTO indices (serie, mes, valor, fonte, atualizado_em) VALUES (?, ?, ?, 'manual', ?)
       ON CONFLICT(serie, mes) DO UPDATE SET valor = excluded.valor, fonte = 'manual', atualizado_em = excluded.atualizado_em`)
      .run(serie, mes, v, iso());
    auditar(ator, 'indice.manual', `${s.nome} ${mes.split('-').reverse().join('/')}: ${String(v).replace('.', ',')}%`);
    return indices(ator, serie);
  }

  function removerIndice(ator, serie, mes) {
    exigir(ator, 'operador');
    serieValida(serie);
    q('DELETE FROM indices WHERE serie = ? AND mes = ?').run(serie, String(mes));
    return indices(ator, serie);
  }

  // ------------------------------------------------------------ distratos

  const periodoValido = (p, rotulo) => {
    p = p || {};
    const valor = K.lerValor(p.valor);
    if (valor != null && valor < 0) falhar(400, `${rotulo}: o valor não pode ser negativo.`);
    const out = { inicio: p.inicio || '', fim: p.fim || '', valor: valor == null ? '' : K.centavos(valor) };
    if (out.inicio) dataValida(out.inicio, `${rotulo}: data inicial`);
    if (out.fim) dataValida(out.fim, `${rotulo}: data final`);
    if (out.inicio && out.fim && out.inicio > out.fim) falhar(400, `${rotulo}: a data final deve ser posterior à inicial.`);
    if (out.valor && (!out.inicio || !out.fim)) falhar(400, `${rotulo}: informe o período (início e fim).`);
    return out;
  };

  function normalizarSimples(s) {
    s = s && typeof s === 'object' ? s : {};
    const situacao = ['optante', 'nao_optante'].includes(s.situacao) ? s.situacao : '';
    const txt = (v, max) => String(v == null ? '' : v).slice(0, max);
    return {
      situacao, fonte: s.fonte === 'consulta' ? 'consulta' : situacao ? 'manual' : '',
      consultadoEm: txt(s.consultadoEm, 40), detalhe: txt(s.detalhe, 300),
    };
  }

  function normalizarDistrato(d) {
    const contrato = q('SELECT * FROM contratos_representante WHERE id = ?').get(d.contratoId) ||
      falhar(400, 'Selecione o contrato do representante.');
    if (!['cia', 'alimentos'].includes(d.representada)) falhar(400, 'Selecione a empresa representada.');
    const dataInicio = dataValida(d.dataInicio, 'Data de início do contrato');
    const dataDistrato = dataValida(d.dataDistrato, 'Data do distrato');
    const dataAviso = d.dataAviso ? dataValida(d.dataAviso, 'Data do aviso prévio') : dataDistrato;
    if (dataInicio > dataDistrato) falhar(400, 'A data do distrato deve ser posterior ao início do contrato.');
    if (!Array.isArray(d.comissoes) || d.comissoes.length > 600) falhar(400, 'Lista de comissões inválida.');
    const comissoes = [];
    for (const c of d.comissoes) {
      if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(String(c && c.mes))) falhar(400, 'Mês de comissão inválido.');
      const v = K.lerValor(c.valor);
      if (v == null) continue;
      if (v < 0) falhar(400, `Comissão de ${K.rotuloMes(c.mes)} não pode ser negativa.`);
      comissoes.push({ mes: c.mes, valor: K.centavos(v) });
    }
    const t = (v, max) => {
      const s = String(v == null ? '' : v).trim();
      if (s.length > max) falhar(400, `Texto muito longo (máximo ${max} caracteres).`);
      return s;
    };
    const docs = Array.isArray(d.documentos) ? d.documentos.filter((x) => ['distrato', 'aviso'].includes(x)) : [];
    return {
      contrato,
      dados: {
        contratoId: contrato.id, representada: d.representada, dataInicio, dataDistrato, dataAviso, comissoes,
        aReceber: periodoValido(d.aReceber, 'Comissões a receber'),
        pendentes: periodoValido(d.pendentes, 'Comissões sobre títulos pendentes'),
        pagarAviso: d.pagarAviso !== false, pagarIndenizacao: d.pagarIndenizacao !== false,
        desconsiderarDeflacao: d.desconsiderarDeflacao !== false,
        profissao: t(d.profissao, 60), estadoCivil: t(d.estadoCivil, 120), naturalidade: t(d.naturalidade, 80),
        documentos: docs.length ? docs : ['distrato', 'aviso'],
        simples: normalizarSimples(d.simples),
      },
    };
  }

  const distratoDeLinha = (l, ind) => {
    const dados = JSON.parse(l.dados);
    const c = q('SELECT razao_social, cnpj, dados FROM contratos_representante WHERE id = ?').get(l.contrato_id) || {};
    const dc = c.dados ? JSON.parse(c.dados) : {};
    return {
      id: l.id, ...dados, razao: c.razao_social, cnpj: c.cnpj, cidade: dc.cidade || '', uf: dc.uf || '',
      resultado: K.calcular(dados, ind || lerIndices('igpm')),
      criadoPor: l.criado_por, criadoEm: l.criado_em, atualizadoEm: l.atualizado_em,
    };
  };

  function listarDistratos(ator) {
    exigir(ator, 'consulta');
    const ind = lerIndices('igpm');
    return q('SELECT * FROM distratos ORDER BY data_distrato DESC').all().map((l) => distratoDeLinha(l, ind));
  }

  function salvarDistrato(ator, d) {
    exigir(ator, 'operador');
    const { contrato, dados } = normalizarDistrato(d);
    const r = K.calcular(dados, lerIndices('igpm'));
    const existente = q('SELECT id FROM distratos WHERE contrato_id = ? AND representada = ?').get(dados.contratoId, dados.representada);
    if (existente && existente.id !== d.id) {
      falhar(409, 'Já existe um distrato deste contrato para esta empresa representada. Abra-o na lista para editar.');
    }
    const empresa = dados.representada === 'cia' ? 'Antoniazzi & Cia' : 'Antoniazzi Alimentos';
    const detalhe = `${contrato.razao_social} / ${empresa}: total R$ ${K.moeda(r.total)}`;
    // resultado como estava ao salvar (relatórios): o cálculo ao vivo muda se o IGP-M for revisto
    dados.resultadoSalvo = {
      somaNominal: r.somaNominal, somaAtualizada: r.somaAtualizada, pendentes: r.pendentes, aReceber: r.aReceber,
      indenizacao: r.indenizacao, avisoPrevio: r.avisoPrevio, total: r.total, reterIR: !!r.reterIR, ir: r.ir ? r.ir.total : 0,
      liquido: r.liquido == null ? r.total : r.liquido, salvoEm: iso(), salvoPor: ator.login,
    };
    let id = d.id;
    if (id) {
      const res = q('UPDATE distratos SET contrato_id = ?, representada = ?, data_distrato = ?, total = ?, dados = ?, atualizado_em = ? WHERE id = ?')
        .run(dados.contratoId, dados.representada, dados.dataDistrato, r.total, JSON.stringify(dados), iso(), id);
      if (!res.changes) falhar(404, 'Distrato não encontrado.');
      auditar(ator, 'distrato.alterar', detalhe);
    } else {
      id = novoId();
      q(`INSERT INTO distratos (id, contrato_id, representada, data_distrato, total, dados, criado_por, criado_em, atualizado_em)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`).run(id, dados.contratoId, dados.representada, dados.dataDistrato, r.total,
        JSON.stringify(dados), ator.login, iso(), iso());
      auditar(ator, 'distrato.criar', detalhe);
    }
    // com o distrato, o contrato do representante passa a encerrado
    const encerrou = q("UPDATE contratos_representante SET situacao = 'encerrado', atualizado_em = ? WHERE id = ? AND situacao <> 'encerrado'")
      .run(iso(), dados.contratoId).changes > 0;
    if (encerrou) auditar(ator, 'contrato.alterar', `${contrato.razao_social} (${contrato.cnpj}), encerrado pelo distrato`);
    return { ...distratoDeLinha(q('SELECT * FROM distratos WHERE id = ?').get(id)), contratoEncerrado: encerrou };
  }

  function removerDistrato(ator, id) {
    exigir(ator, 'operador');
    const l = q('SELECT * FROM distratos WHERE id = ?').get(id) || falhar(404, 'Distrato não encontrado.');
    q('DELETE FROM distratos WHERE id = ?').run(id);
    const c = q('SELECT * FROM contratos_representante WHERE id = ?').get(l.contrato_id) || {};
    auditar(ator, 'distrato.excluir', `${c.razao_social || ''} / ${l.representada === 'cia' ? 'Antoniazzi & Cia' : 'Antoniazzi Alimentos'}`);
    // sem nenhum distrato, o contrato volta a ativo (se não houver outro contrato ativo do mesmo CNPJ)
    const restantes = q('SELECT COUNT(*) AS n FROM distratos WHERE contrato_id = ?').get(l.contrato_id).n;
    const outroAtivo = c.id && q("SELECT 1 FROM contratos_representante WHERE cnpj = ? AND situacao = 'ativo' AND id <> ?").get(c.cnpj, c.id);
    if (c.id && !restantes && !outroAtivo && c.situacao === 'encerrado') {
      q("UPDATE contratos_representante SET situacao = 'ativo', atualizado_em = ? WHERE id = ?").run(iso(), c.id);
      auditar(ator, 'contrato.alterar', `${c.razao_social} (${c.cnpj}), reativado ao excluir o distrato`);
    }
  }

  // ------------------------------------------------- Simples Nacional (CNPJ)

  const dataDeAPI = (v) => {
    const s = String(v || '');
    if (/^\d{4}-\d{2}-\d{2}/.test(s)) return s.slice(0, 10);
    const m = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(s);
    return m ? `${m[3]}-${m[2]}-${m[1]}` : '';
  };

  /**
   * Situação do CNPJ no Simples Nacional, pelos dados abertos da Receita Federal (BrasilAPI; ReceitaWS como
   * alternativa). A "Consulta Optantes" do Portal do Simples exige captcha e não pode ser consultada pelo sistema.
   */
  async function consultarSimples(ator, cnpj) {
    exigir(ator, 'operador');
    const dig = String(cnpj || '').replace(/\D/g, '');
    if (dig.length !== 14 || !CT.validarCNPJ(dig)) falhar(400, 'CNPJ inválido.');
    const pedir = async (url) => {
      const r = await buscarUrl(url, { signal: AbortSignal.timeout(15000), headers: { Accept: 'application/json' } });
      if (r.status === 404) falhar(404, 'CNPJ não encontrado na base da Receita Federal.');
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json();
    };
    const fontes = [
      async () => {
        const j = await pedir(`https://brasilapi.com.br/api/cnpj/v1/${dig}`);
        return {
          razao: j.razao_social || '', situacaoCadastral: j.descricao_situacao_cadastral || '',
          optante: typeof j.opcao_pelo_simples === 'boolean' ? j.opcao_pelo_simples : null,
          dataOpcao: dataDeAPI(j.data_opcao_pelo_simples), dataExclusao: dataDeAPI(j.data_exclusao_do_simples),
          mei: j.opcao_pelo_mei === true, fonte: 'BrasilAPI (dados abertos da Receita Federal)',
        };
      },
      async () => {
        const j = await pedir(`https://receitaws.com.br/v1/cnpj/${dig}`);
        if (j.status === 'ERROR') falhar(404, j.message || 'CNPJ não encontrado.');
        const s = j.simples || {};
        return {
          razao: j.nome || '', situacaoCadastral: j.situacao || '',
          optante: typeof s.optante === 'boolean' ? s.optante : null,
          dataOpcao: dataDeAPI(s.data_opcao), dataExclusao: dataDeAPI(s.data_exclusao),
          mei: !!(j.simei && j.simei.optante), fonte: 'ReceitaWS (dados da Receita Federal)',
        };
      },
    ];
    const erros = [];
    for (const fonte of fontes) {
      try {
        const r = await fonte();
        auditar(ator, 'distrato.simples', `${CT.formatarCNPJ(dig)}: ${r.optante == null ? 'sem informação' : r.optante ? 'optante' : 'não optante'} (${r.fonte})`);
        return { cnpj: CT.formatarCNPJ(dig), ...r, consultadoEm: iso() };
      } catch (e) {
        if (e instanceof ErroApp) throw e;
        erros.push(e.message);
      }
    }
    falhar(502, `Não foi possível consultar a Receita Federal (${erros.join('; ')}). Confira na Consulta Optantes do ` +
      'Portal do Simples Nacional e marque a situação manualmente.');
  }

  function registrarDocumentoDistrato(ator, id, formato) {
    exigir(ator, 'consulta');
    const l = q('SELECT * FROM distratos WHERE id = ?').get(id) || falhar(404, 'Distrato não encontrado.');
    const nomes = { pdf: 'PDF', docx: 'Word', 'memoria-pdf': 'memória de cálculo em PDF', 'memoria-xlsx': 'memória de cálculo em Excel' };
    if (!nomes[formato]) falhar(400, 'Formato inválido.');
    const c = q('SELECT razao_social FROM contratos_representante WHERE id = ?').get(l.contrato_id) || {};
    auditar(ator, 'distrato.documento', `${c.razao_social || ''}: ${nomes[formato]}`);
  }

  // ------------------------------------------------------ custos de pessoal

  function lerParametrosCustos() {
    const l = q("SELECT valor FROM configuracoes WHERE chave = 'custos'").get();
    return CU.parametros(l ? JSON.parse(l.valor) : {});
  }

  const competenciaDeLinha = (l) => ({ competencia: l.competencia, ...JSON.parse(l.dados), criadaEm: l.criada_em, atualizadaEm: l.atualizada_em });
  const lancamentoDeLinha = (l) => ({ competencia: l.competencia, colaboradorId: l.colaborador_id, ...JSON.parse(l.dados) });

  function custos(ator) {
    exigir(ator, 'operador');
    return {
      parametros: lerParametrosCustos(),
      competencias: q('SELECT * FROM folha_competencias ORDER BY competencia').all().map(competenciaDeLinha),
      lancamentos: q('SELECT * FROM folha_lancamentos ORDER BY competencia').all().map(lancamentoDeLinha),
    };
  }

  function salvarParametrosCustos(ator, d) {
    exigir(ator, 'operador');
    const faixa = (k, rotulo, min, max) => {
      const v = CU.lerNumero(d[k]);
      if (v == null || v < min || v > max) falhar(400, `${rotulo}: informe um valor de ${String(min).replace('.', ',')} a ${String(max).replace('.', ',')}.`);
      return v;
    };
    if (!CU.REGIMES[d.regime]) falhar(400, 'Regime tributário inválido.');
    const p = {
      regime: d.regime, inss: faixa('inss', 'INSS patronal', 0, 30), rat: faixa('rat', 'RAT', 0, 3),
      fap: faixa('fap', 'FAP', 0.5, 2), terceiros: faixa('terceiros', 'Terceiros', 0, 10), fgts: faixa('fgts', 'FGTS', 0, 10),
      alertaSinistralidade: faixa('alertaSinistralidade', 'Alerta de sinistralidade', 1, 200),
      limiteSinistralidade: faixa('limiteSinistralidade', 'Limite de sinistralidade', 1, 200),
      alertaHorasExtras: faixa('alertaHorasExtras', 'Alerta de horas extras', 0, 300),
      alertaBancoHoras: faixa('alertaBancoHoras', 'Alerta de banco de horas', 0, 1000),
    };
    if (p.limiteSinistralidade < p.alertaSinistralidade) falhar(400, 'O limite de sinistralidade deve ser maior ou igual ao alerta.');
    q("INSERT INTO configuracoes (chave, valor) VALUES ('custos', ?) ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor")
      .run(JSON.stringify(p));
    const e = CU.encargos(p);
    auditar(ator, 'custos.parametros', `${CU.REGIMES[p.regime]}; encargos de ${String(CU.centavos(e.total)).replace('.', ',')}% sobre a remuneração`);
    return p;
  }

  function competenciaValida(comp) {
    if (!CU.competenciaValida(comp)) falhar(400, 'Competência inválida (use AAAA-MM).');
    return comp;
  }

  /** Lançamento com os valores do cadastro (salário e benefícios). */
  function lancamentoPadrao(c) {
    const l = {};
    for (const campo of CU.CAMPOS) l[campo.id] = campo.tipo === 'motivo' ? '' : 0;
    l.salario = Number(c.salario) || 0;
    for (const b of CU.BENEFICIOS) l[b.id] = Number(c.beneficios[b.id]) || 0;
    return l;
  }

  function normalizarLancamento(d, rotulo) {
    const out = {};
    const limites = { moeda: 10000000, horas: 744, dias: 31 };
    for (const c of CU.CAMPOS) {
      if (c.tipo === 'motivo') continue;
      const v = CU.lerNumero(d[c.id]);
      if (v == null) {
        if (d[c.id] != null && String(d[c.id]).trim() !== '') falhar(400, `${rotulo}: ${c.nome} inválido.`);
        out[c.id] = 0;
        continue;
      }
      if (v < 0 || v > limites[c.tipo]) falhar(400, `${rotulo}: ${c.nome} inválido.`);
      if (c.tipo === 'dias' && !Number.isInteger(v)) falhar(400, `${rotulo}: ${c.nome} deve ser um número inteiro de dias.`);
      out[c.id] = c.tipo === 'moeda' ? CU.centavos(v) : Math.round(v * 100) / 100;
    }
    out.atestadoMotivo = out.atestadoDias ? (CU.MOTIVOS_ATESTADO[d.atestadoMotivo] ? d.atestadoMotivo : 'outros') : '';
    return out;
  }

  const rotuloComp = (comp) => CU.rotuloComp(comp);
  const gravarLancamento = (comp, colabId, l) => q(`INSERT INTO folha_lancamentos (competencia, colaborador_id, dados) VALUES (?, ?, ?)
    ON CONFLICT(competencia, colaborador_id) DO UPDATE SET dados = excluded.dados`).run(comp, colabId, JSON.stringify(l));
  const garantirCompetencia = (comp) => q(`INSERT INTO folha_competencias (competencia, dados, criada_em, atualizada_em)
    VALUES (?, '{}', ?, ?) ON CONFLICT(competencia) DO NOTHING`).run(comp, iso(), iso());
  const tocarCompetencia = (comp) => q('UPDATE folha_competencias SET atualizada_em = ? WHERE competencia = ?').run(iso(), comp);

  /** Cria a competência com um lançamento para cada colaborador com vínculo no mês. */
  function abrirCompetencia(ator, comp) {
    exigir(ator, 'operador');
    competenciaValida(comp);
    let criados = 0;
    db.transacao(() => {
      garantirCompetencia(comp);
      const existe = q('SELECT 1 FROM folha_lancamentos WHERE competencia = ? AND colaborador_id = ?');
      for (const c of lerColaboradores()) {
        if (!CU.ativoNoMes(c, comp) || existe.get(comp, c.id)) continue;
        gravarLancamento(comp, c.id, lancamentoPadrao(c));
        criados++;
      }
      tocarCompetencia(comp);
    });
    auditar(ator, 'folha.abrir', `${rotuloComp(comp)}: ${criados} lançamento(s) criado(s)`);
    return custos(ator);
  }

  function salvarFolha(ator, comp, d) {
    exigir(ator, 'operador');
    competenciaValida(comp);
    const linhaComp = q('SELECT * FROM folha_competencias WHERE competencia = ?').get(comp) ||
      falhar(404, `A competência ${rotuloComp(comp)} não foi aberta.`);
    const lista = Array.isArray(d.lancamentos) ? d.lancamentos : [];
    if (lista.length > 5000) falhar(400, 'Envie no máximo 5000 lançamentos por vez.');
    const dadosComp = JSON.parse(linhaComp.dados);
    if ('premioSaude' in d) dadosComp.premioSaude = numeroOpcional(d.premioSaude, 'Fatura do plano de saúde', 100000000);
    if ('sinistrosSaude' in d) dadosComp.sinistrosSaude = numeroOpcional(d.sinistrosSaude, 'Sinistros do plano de saúde', 100000000);
    let salvos = 0;
    let removidos = 0;
    db.transacao(() => {
      q('UPDATE folha_competencias SET dados = ?, atualizada_em = ? WHERE competencia = ?').run(JSON.stringify(dadosComp), iso(), comp);
      for (const l of lista) {
        const c = q('SELECT * FROM colaboradores WHERE id = ?').get(l && l.colaboradorId) || falhar(400, 'Colaborador do lançamento não encontrado.');
        if (l.remover) {
          removidos += q('DELETE FROM folha_lancamentos WHERE competencia = ? AND colaborador_id = ?').run(comp, c.id).changes;
          continue;
        }
        gravarLancamento(comp, c.id, normalizarLancamento(l, `${c.nome} (${c.matricula})`));
        salvos++;
      }
    });
    auditar(ator, 'folha.salvar', `${rotuloComp(comp)}: ${salvos} lançamento(s) salvo(s)${removidos ? `, ${removidos} removido(s)` : ''}`);
    return custos(ator);
  }

  /** Importa uma planilha: cada linha (pela matrícula) atualiza só as colunas informadas. */
  function importarFolha(ator, comp, linhas) {
    exigir(ator, 'operador');
    competenciaValida(comp);
    if (!Array.isArray(linhas) || !linhas.length) falhar(400, 'Nenhuma linha para importar.');
    if (linhas.length > 5000) falhar(400, 'Importe no máximo 5000 linhas por vez.');
    const ignorados = [];
    let importados = 0;
    db.transacao(() => {
      garantirCompetencia(comp);
      for (const [i, l] of linhas.entries()) {
        const ref = `linha ${l.linha || i + 2}`;
        const linhaColab = q('SELECT * FROM colaboradores WHERE matricula = ?').get(String(l.matricula || '').trim());
        if (!linhaColab) { ignorados.push(`${ref} (matrícula ${l.matricula} não cadastrada)`); continue; }
        const c = colabDeLinha(linhaColab);
        const atual = q('SELECT dados FROM folha_lancamentos WHERE competencia = ? AND colaborador_id = ?').get(comp, c.id);
        const base = atual ? JSON.parse(atual.dados) : lancamentoPadrao(c);
        for (const campo of CU.CAMPOS) if (l[campo.id] != null && l[campo.id] !== '') base[campo.id] = l[campo.id];
        try {
          gravarLancamento(comp, c.id, normalizarLancamento(base, `${ref}, ${c.nome}`));
          importados++;
        } catch (e) {
          if (!(e instanceof ErroApp)) throw e;
          ignorados.push(e.message.replace(/\.$/, ''));
        }
      }
      tocarCompetencia(comp);
    });
    auditar(ator, 'folha.importar', `${rotuloComp(comp)}: ${importados} linha(s) importada(s), ${ignorados.length} ignorada(s)`);
    return { importados, ignorados, ...custos(ator) };
  }

  function removerCompetencia(ator, comp) {
    exigir(ator, 'operador');
    competenciaValida(comp);
    const n = q('SELECT COUNT(*) AS n FROM folha_lancamentos WHERE competencia = ?').get(comp).n;
    if (!q('DELETE FROM folha_competencias WHERE competencia = ?').run(comp).changes) falhar(404, 'Competência não encontrada.');
    auditar(ator, 'folha.excluir', `${rotuloComp(comp)} (${n} lançamento(s))`);
    return custos(ator);
  }

  // ------------------------------------------------------------- empresas

  const arquivosDe = (id) => q('SELECT id, tipo, nome, mime, tamanho, enviado_por, enviado_em FROM empresas_arquivos WHERE empresa_id = ? ORDER BY enviado_em')
    .all(id).map((a) => ({ id: a.id, tipo: a.tipo, nome: a.nome, mime: a.mime, tamanho: a.tamanho, enviadoPor: a.enviado_por, enviadoEm: a.enviado_em }));

  const empresaDeLinha = (l) => ({
    id: l.id, ...JSON.parse(l.dados), razao: l.razao_social, cnpj: l.cnpj,
    criadoEm: l.criado_em, atualizadoEm: l.atualizado_em, arquivos: arquivosDe(l.id),
  });

  function listarEmpresas(ator) {
    exigir(ator, 'consulta');
    return q('SELECT * FROM empresas ORDER BY razao_social COLLATE NOCASE').all().map(empresaDeLinha);
  }

  function normalizarEmpresa(d) {
    const txt = (v, max, rotulo, obrig) => {
      const s = String(v == null ? '' : v).trim();
      if (obrig && !s) falhar(400, `Informe ${rotulo}.`);
      if (s.length > max) falhar(400, `${rotulo[0].toUpperCase() + rotulo.slice(1)}: no máximo ${max} caracteres.`);
      return s;
    };
    const cnpj = CT.soDigitos(d.cnpj);
    if (!cnpj) falhar(400, 'Informe o CNPJ.');
    if (!CT.validarCNPJ(cnpj)) falhar(400, 'CNPJ inválido (confira os dígitos).');
    const uf = String(d.uf || '').trim().toUpperCase();
    if (uf && !CT.UFS.includes(uf)) falhar(400, 'Estado (UF) inválido.');
    const cep = CT.soDigitos(d.cep);
    if (cep && cep.length !== 8) falhar(400, 'CEP deve ter 8 dígitos.');
    const regime = String(d.regime || '').trim();
    if (regime && !REGIMES_EMPRESA.includes(regime)) falhar(400, 'Regime tributário inválido.');
    return {
      razao: txt(d.razao, 150, 'a razão social', true), cnpj: CT.formatarCNPJ(cnpj), fantasia: txt(d.fantasia, 150, 'o nome fantasia'),
      regime, endereco: txt(d.endereco, 200, 'o endereço'), telefone: txt(d.telefone, 30, 'o telefone'),
      cidade: txt(d.cidade, 100, 'a cidade'), uf, cep: cep ? CT.formatarCEP(cep) : '',
      representada: d.representada === true,
    };
  }

  function salvarEmpresa(ator, d) {
    exigir(ator, 'operador');
    const e = normalizarEmpresa(d);
    const repetida = q('SELECT id FROM empresas WHERE cnpj = ?').get(e.cnpj);
    if (repetida && repetida.id !== d.id) falhar(409, `Já existe uma empresa cadastrada com o CNPJ ${e.cnpj}.`);
    const { razao, cnpj, ...resto } = e;
    let id = d.id;
    if (id) {
      if (!q('UPDATE empresas SET razao_social = ?, cnpj = ?, dados = ?, atualizado_em = ? WHERE id = ?')
        .run(razao, cnpj, JSON.stringify(resto), iso(), id).changes) falhar(404, 'Empresa não encontrada.');
      auditar(ator, 'empresa.alterar', `${razao} (${cnpj})`);
    } else {
      id = novoId();
      q('INSERT INTO empresas (id, razao_social, cnpj, dados, criado_em, atualizado_em) VALUES (?, ?, ?, ?, ?, ?)')
        .run(id, razao, cnpj, JSON.stringify(resto), iso(), iso());
      auditar(ator, 'empresa.criar', `${razao} (${cnpj})`);
    }
    return empresaDeLinha(q('SELECT * FROM empresas WHERE id = ?').get(id));
  }

  function removerEmpresa(ator, id) {
    exigir(ator, 'operador');
    const l = q('SELECT * FROM empresas WHERE id = ?').get(id) || falhar(404, 'Empresa não encontrada.');
    q('DELETE FROM empresas WHERE id = ?').run(id);
    auditar(ator, 'empresa.excluir', `${l.razao_social} (${l.cnpj})`);
  }

  function gravarArquivoEmpresa(empresaId, tipo, nome, dados, por, em) {
    const ext = String((nome.match(/\.([a-z0-9]+)$/i) || [])[1] || '').toLowerCase();
    // logotipo: um só por empresa (o novo substitui o anterior); modelos: vários por tipo
    if (tipo === 'logo') q("DELETE FROM empresas_arquivos WHERE empresa_id = ? AND tipo = 'logo'").run(empresaId);
    q(`INSERT INTO empresas_arquivos (id, empresa_id, tipo, nome, mime, tamanho, dados, enviado_por, enviado_em)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`).run(novoId(), empresaId, tipo, nome, TIPOS_MIME[ext] || 'application/octet-stream',
      dados.length, dados, por, em);
  }

  /** Anexa um modelo (ou substitui o logotipo). d = { nome, conteudo (base64) }. */
  function enviarArquivoEmpresa(ator, id, tipo, d) {
    exigir(ator, 'operador');
    const l = q('SELECT * FROM empresas WHERE id = ?').get(id) || falhar(404, 'Empresa não encontrada.');
    const def = ARQUIVOS_EMPRESA[tipo] || falhar(400, 'Tipo de arquivo inválido.');
    const nome = String((d && d.nome) || '').replace(/[\\/:*?"<>|\u0000-\u001f]/g, '_').trim().slice(0, 150);
    const ext = (nome.match(/\.([a-z0-9]+)$/i) || [])[1];
    if (!nome || !ext || !def.extensoes.includes(ext.toLowerCase())) {
      falhar(400, `${def.nome}: envie um arquivo ${def.extensoes.map((x) => `.${x}`).join(', ')}.`);
    }
    const dados = Buffer.from(String((d && d.conteudo) || ''), 'base64');
    if (!dados.length) falhar(400, 'Arquivo vazio.');
    if (dados.length > MAX_ARQUIVO) falhar(413, 'O arquivo deve ter no máximo 10 MB.');
    if (tipo === 'logo') {
      const png = dados[0] === 0x89 && dados[1] === 0x50 && dados[2] === 0x4e && dados[3] === 0x47;
      const jpg = dados[0] === 0xff && dados[1] === 0xd8;
      if (!png && !jpg) falhar(400, 'O logotipo deve ser uma imagem PNG ou JPG.');
    }
    gravarArquivoEmpresa(id, tipo, nome, dados, ator.login, iso());
    auditar(ator, 'empresa.arquivo', `${l.razao_social}: ${def.nome.toLowerCase()} (${nome})`);
    return empresaDeLinha(l);
  }

  /** Arquivo para download: { binario, nome, mime, inline }. */
  function baixarArquivoEmpresa(ator, id, arquivoId) {
    exigir(ator, 'consulta');
    const a = q('SELECT * FROM empresas_arquivos WHERE empresa_id = ? AND id = ?').get(id, String(arquivoId)) ||
      falhar(404, 'Arquivo não encontrado.');
    return { binario: Buffer.from(a.dados), nome: a.nome, mime: a.mime, inline: a.tipo === 'logo' };
  }

  function removerArquivoEmpresa(ator, id, arquivoId) {
    exigir(ator, 'operador');
    const l = q('SELECT * FROM empresas WHERE id = ?').get(id) || falhar(404, 'Empresa não encontrada.');
    const a = q('SELECT tipo, nome FROM empresas_arquivos WHERE empresa_id = ? AND id = ?').get(id, String(arquivoId)) ||
      falhar(404, 'Arquivo não encontrado.');
    q('DELETE FROM empresas_arquivos WHERE id = ?').run(String(arquivoId));
    auditar(ator, 'empresa.arquivo', `${l.razao_social}: ${a.nome} removido`);
    return empresaDeLinha(l);
  }

  /**
   * Cadastra as empresas já usadas pelo sistema (Antoniazzi & Cia e Antoniazzi Alimentos) com os modelos atuais
   * em Word, o modelo da planilha de comissões e o logotipo. Só roda uma vez, com o cadastro vazio.
   * arquivos: { 'nome': { tipo, dados } } por CNPJ, gerados por quem chama (ver server/empresas-padrao.js).
   */
  function semearEmpresas(padrao) {
    // bancos que já tinham as empresas padrão (versão 4.10): marca-as como representadas uma única vez
    if (!q("SELECT valor FROM configuracoes WHERE chave = 'empresasRepresentadas'").get()) {
      db.transacao(() => {
        for (const em of padrao.filter((x) => x.representada)) {
          const l = q('SELECT id, dados FROM empresas WHERE cnpj = ?').get(CT.formatarCNPJ(em.cnpj));
          if (l) q('UPDATE empresas SET dados = ? WHERE id = ?').run(JSON.stringify({ ...JSON.parse(l.dados), representada: true }), l.id);
        }
        q("INSERT INTO configuracoes (chave, valor) VALUES ('empresasRepresentadas', 'true')").run();
      });
    }
    const ja = q("SELECT valor FROM configuracoes WHERE chave = 'empresasPadrao'").get();
    if (ja || q('SELECT COUNT(*) AS n FROM empresas').get().n) return 0;
    let n = 0;
    db.transacao(() => {
      for (const em of padrao) {
        const e = normalizarEmpresa(em);
        const { razao, cnpj, ...resto } = e;
        const id = novoId();
        q('INSERT INTO empresas (id, razao_social, cnpj, dados, criado_em, atualizado_em) VALUES (?, ?, ?, ?, ?, ?)')
          .run(id, razao, cnpj, JSON.stringify(resto), iso(), iso());
        for (const a of em.arquivos || []) gravarArquivoEmpresa(id, a.tipo, a.nome, Buffer.from(a.dados), 'sistema', iso());
        n++;
      }
      q("INSERT INTO configuracoes (chave, valor) VALUES ('empresasPadrao', 'true')").run();
    });
    if (n) auditar(null, 'empresa.criar', `${n} empresa(s) já existentes cadastradas com os modelos atuais`);
    return n;
  }

  function backup(ator) {
    exigir(ator, 'admin');
    const d = dados(ator);
    const contratos = q('SELECT * FROM contratos_representante').all().map(contratoDeLinha);
    const distratos = q('SELECT * FROM distratos').all().map((l) => ({ ...JSON.parse(l.dados), criadoPor: l.criado_por, criadoEm: l.criado_em }));
    const indicesSalvos = q('SELECT serie, mes, valor, fonte FROM indices ORDER BY serie, mes').all().map((l) => ({ ...l }));
    const folha = {
      parametros: lerParametrosCustos(),
      competencias: q('SELECT * FROM folha_competencias ORDER BY competencia').all().map(competenciaDeLinha),
      lancamentos: q('SELECT * FROM folha_lancamentos ORDER BY competencia').all().map(lancamentoDeLinha),
    };
    auditar(ator, 'dados.backup', null);
    const empresas = q('SELECT * FROM empresas').all().map((l) => ({
      ...empresaDeLinha(l),
      arquivos: q('SELECT * FROM empresas_arquivos WHERE empresa_id = ?').all(l.id).map((a) => ({
        tipo: a.tipo, nome: a.nome, conteudo: Buffer.from(a.dados).toString('base64'), enviadoPor: a.enviado_por, enviadoEm: a.enviado_em,
      })),
    }));
    return { versao: 6, exportadoEm: iso(), ...d, contratos, distratos, indices: indicesSalvos, folha, empresas };
  }

  function restaurar(ator, b) {
    exigir(ator, 'admin');
    if (!b || !Array.isArray(b.setores) || !Array.isArray(b.colaboradores)) falhar(400, 'Arquivo de backup inválido.');
    const mapaColab = {};
    db.transacao(() => {
      limparTabelas();
      for (const c of Array.isArray(b.centrosCusto) ? b.centrosCusto : []) gravarCentro(normalizarCentro(c));
      const mapaSetor = {};
      for (const s of b.setores) {
        const n = normalizarSetor(s);
        const id = novoId();
        mapaSetor[s.id] = id;
        q('INSERT INTO setores (id, nome, minimo_por_dia, dias_funcionamento, funciona_feriados) VALUES (?, ?, ?, ?, ?)')
          .run(id, n.nome, n.minimo, JSON.stringify(n.dias), n.feriados ? 1 : 0);
      }
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
      if (b.regras) {
        st.run('evitarFolgaFeriado', JSON.stringify(!!b.regras.evitarFolgaFeriado));
        const max = Number(b.regras.maxFolgasSeguidas);
        if (Number.isInteger(max) && max >= 0 && max <= 7) st.run('maxFolgasSeguidas', JSON.stringify(max));
      }
      // backups antigos têm só "escala" (de todos); os novos, "escalas" por centro de custo
      const escalas = b.escalas && typeof b.escalas === 'object' ? b.escalas : (b.escala ? { '': b.escala } : {});
      for (const [escopo, e] of Object.entries(escalas)) {
        if (!e || !e.inicio || !e.fim || !Array.isArray(e.dias) || !e.celulas || typeof e.celulas !== 'object') continue;
        if (escopo && !q('SELECT 1 FROM centros_custo WHERE codigo = ?').get(escopo)) continue;
        const celulas = {};
        for (const [idAntigo, lista] of Object.entries(e.celulas)) {
          if (mapaColab[idAntigo] && Array.isArray(lista) && lista.length === e.dias.length) celulas[mapaColab[idAntigo]] = lista;
        }
        gravarEscala(ator, { inicio: dataValida(e.inicio, 'Data'), fim: dataValida(e.fim, 'Data'), dias: e.dias, celulas,
          excluirSemControle: e.excluirSemControle }, true, escopo);
      }
      const f = b.folha;
      if (f && typeof f === 'object') {
        if (f.parametros) st.run('custos', JSON.stringify(CU.parametros(f.parametros)));
        for (const c of Array.isArray(f.competencias) ? f.competencias : []) {
          const comp = competenciaValida(c.competencia);
          const dadosComp = {
            premioSaude: numeroOpcional(c.premioSaude, 'Fatura do plano de saúde', 100000000),
            sinistrosSaude: numeroOpcional(c.sinistrosSaude, 'Sinistros do plano de saúde', 100000000),
          };
          q('INSERT OR REPLACE INTO folha_competencias (competencia, dados, criada_em, atualizada_em) VALUES (?, ?, ?, ?)')
            .run(comp, JSON.stringify(dadosComp), c.criadaEm || iso(), c.atualizadaEm || iso());
        }
        for (const l of Array.isArray(f.lancamentos) ? f.lancamentos : []) {
          const novo = mapaColab[l.colaboradorId];
          if (!novo || !CU.competenciaValida(l.competencia)) continue;
          garantirCompetencia(l.competencia);
          gravarLancamento(l.competencia, novo, normalizarLancamento(l, `Lançamento de ${rotuloComp(l.competencia)}`));
        }
      }
    });
    if (Array.isArray(b.contratos)) {
      db.transacao(() => {
        q('DELETE FROM distratos').run();
        q('DELETE FROM contratos_representante').run();
        const mapa = {};
        for (const ct of b.contratos) {
          const c = normalizarContrato(ct);
          const { situacao, ...dadosJson } = c;
          const novo = novoId();
          if (ct.id) mapa[ct.id] = novo;
          q(`INSERT INTO contratos_representante (id, razao_social, cnpj, situacao, dados, criado_por, criado_em, atualizado_em)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?)`).run(novo, c.razao, c.cnpj, situacao, JSON.stringify(dadosJson),
            ct.criadoPor || ator.login, ct.criadoEm || iso(), iso());
        }
        for (const ds of Array.isArray(b.distratos) ? b.distratos : []) {
          if (!mapa[ds.contratoId]) continue;
          const { dados: dd } = normalizarDistrato({ ...ds, contratoId: mapa[ds.contratoId] });
          const r = K.calcular(dd, lerIndices('igpm'));
          q(`INSERT INTO distratos (id, contrato_id, representada, data_distrato, total, dados, criado_por, criado_em, atualizado_em)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`).run(novoId(), dd.contratoId, dd.representada, dd.dataDistrato, r.total,
            JSON.stringify(dd), ds.criadoPor || ator.login, ds.criadoEm || iso(), iso());
        }
      });
    }
    if (Array.isArray(b.empresas)) {
      db.transacao(() => {
        q('DELETE FROM empresas').run();
        for (const em of b.empresas) {
          const e = normalizarEmpresa(em);
          const { razao, cnpj, ...resto } = e;
          const id = novoId();
          q('INSERT INTO empresas (id, razao_social, cnpj, dados, criado_em, atualizado_em) VALUES (?, ?, ?, ?, ?, ?)')
            .run(id, razao, cnpj, JSON.stringify(resto), em.criadoEm || iso(), iso());
          for (const a of Array.isArray(em.arquivos) ? em.arquivos : []) {
            if (!ARQUIVOS_EMPRESA[a.tipo] || !a.conteudo) continue;
            const dados = Buffer.from(String(a.conteudo), 'base64');
            gravarArquivoEmpresa(id, a.tipo, String(a.nome).slice(0, 150), dados, a.enviadoPor || ator.login, a.enviadoEm || iso());
          }
        }
      });
    }
    if (Array.isArray(b.indices)) {
      db.transacao(() => {
        const st = q(`INSERT INTO indices (serie, mes, valor, fonte, atualizado_em) VALUES (?, ?, ?, ?, ?)
          ON CONFLICT(serie, mes) DO UPDATE SET valor = excluded.valor, fonte = excluded.fonte, atualizado_em = excluded.atualizado_em`);
        for (const it of b.indices) {
          if (SERIES[it.serie] && /^\d{4}-\d{2}$/.test(it.mes) && Number.isFinite(Number(it.valor))) {
            st.run(it.serie, it.mes, Number(it.valor), it.fonte === 'bcb' ? 'bcb' : 'manual', iso());
          }
        }
      });
    }
    auditar(ator, 'dados.restaurar', `${b.setores.length} setor(es), ${b.colaboradores.length} colaborador(es)` +
      (Array.isArray(b.contratos) ? `, ${b.contratos.length} contrato(s)` : '') +
      (b.folha && Array.isArray(b.folha.lancamentos) ? `, ${b.folha.lancamentos.length} lançamento(s) de folha` : ''));
  }

  return {
    temUsuarios, criarPrimeiroAdmin, login, sessao, logout, alterarMinhaSenha,
    listarUsuarios, criarUsuario, atualizarUsuario, removerUsuario, auditoria,
    dados, removerEscala, salvarSetor, removerSetor, salvarColaborador, removerColaborador, importarColaboradores,
    salvarConfig, salvarFeriado, removerFeriado, gerarEscala, alterarCelula,
    carregarExemplo, limparDados, backup, restaurar,
    listarContratos, salvarContrato, removerContrato, registrarDocumento,
    indices, atualizarIndices, salvarIndice, removerIndice,
    listarDistratos, salvarDistrato, removerDistrato, registrarDocumentoDistrato, consultarSimples,
    custos, salvarParametrosCustos, abrirCompetencia, salvarFolha, importarFolha, removerCompetencia,
    salvarCentroCusto, removerCentroCusto, importarCentrosCusto,
    listarEmpresas, salvarEmpresa, removerEmpresa, enviarArquivoEmpresa, baixarArquivoEmpresa, removerArquivoEmpresa, semearEmpresas,
  };
}

module.exports = { criarServico, ErroApp, PERFIS, REGIMES_EMPRESA, ARQUIVOS_EMPRESA };
