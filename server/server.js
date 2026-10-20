/*
 * Servidor HTTP do CORE RH (sem dependências externas).
 *
 *   npm start                     -> http://localhost:3000
 *
 * Variáveis de ambiente:
 *   PORT          porta (padrão 3000)
 *   HOST          interface de rede (padrão 127.0.0.1; use 0.0.0.0 para a rede local)
 *   DB_PATH       arquivo do banco SQLite (padrão ./dados/escala.db)
 *   COOKIE_SECURE "1" para exigir HTTPS no cookie de sessão (use atrás de proxy HTTPS)
 *   TRUST_PROXY   "1" para usar X-Forwarded-For/Proto (quando atrás de proxy reverso)
 */
'use strict';

const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const { abrirBanco } = require('./db.js');
const { criarServico, ErroApp } = require('./servico.js');

const RAIZ = path.resolve(__dirname, '..');
const ESTATICOS = {
  '/': 'index.html',
  '/index.html': 'index.html',
  '/favicon.ico': 'img/icone.png',
};
const PASTAS_ESTATICAS = ['/css/', '/js/', '/img/'];
const TIPOS = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.png': 'image/png',
};
const COOKIE = 'escala_sid';
const VERSAO = require('../package.json').version;
const LIMITE_CORPO = 1024 * 1024;
const LIMITE_CORPO_BACKUP = 20 * 1024 * 1024;

// ------------------------------------------------- limite de tentativas por IP

function criarLimitador(maximo, janelaMs, agora = () => Date.now()) {
  const mapa = new Map();
  return (chave) => {
    const t = agora();
    const reg = mapa.get(chave);
    if (!reg || reg.inicio + janelaMs < t) {
      mapa.set(chave, { inicio: t, n: 1 });
      if (mapa.size > 10000) for (const [k, v] of mapa) if (v.inicio + janelaMs < t) mapa.delete(k);
      return true;
    }
    reg.n++;
    return reg.n <= maximo;
  };
}

// ------------------------------------------------------------- utilidades

function cabecalhosSeguranca(res) {
  res.setHeader('X-Content-Type-Options', 'nosniff');
  res.setHeader('X-Frame-Options', 'DENY');
  res.setHeader('Referrer-Policy', 'no-referrer');
  res.setHeader('Cross-Origin-Opener-Policy', 'same-origin');
  res.setHeader('Content-Security-Policy',
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; " +
    "frame-ancestors 'none'; base-uri 'none'; form-action 'self'");
}

function json(res, status, corpo) {
  const txt = JSON.stringify(corpo === undefined ? { ok: true } : corpo);
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' });
  res.end(txt);
}

function lerCookies(req) {
  const out = {};
  for (const parte of String(req.headers.cookie || '').split(';')) {
    const i = parte.indexOf('=');
    if (i > 0) out[parte.slice(0, i).trim()] = decodeURIComponent(parte.slice(i + 1).trim());
  }
  return out;
}

function lerCorpo(req, limite) {
  return new Promise((resolve, reject) => {
    let tamanho = 0;
    const partes = [];
    req.on('data', (c) => {
      tamanho += c.length;
      if (tamanho > limite) {
        reject(new ErroApp(413, 'Conteúdo grande demais.'));
        req.destroy();
      } else partes.push(c);
    });
    req.on('end', () => {
      if (!tamanho) return resolve({});
      try {
        resolve(JSON.parse(Buffer.concat(partes).toString('utf8')));
      } catch (e) {
        reject(new ErroApp(400, 'JSON inválido.'));
      }
    });
    req.on('error', reject);
  });
}

// ------------------------------------------------------------------ app

function criarApp({ servico, cookieSeguro = false, confiarProxy = false, limiteLogin } = {}) {
  const permitirLogin = limiteLogin || criarLimitador(20, 15 * 60 * 1000);

  const ipDe = (req) => (confiarProxy && req.headers['x-forwarded-for']
    ? String(req.headers['x-forwarded-for']).split(',')[0].trim() : req.socket.remoteAddress);
  const ehHttps = (req) => req.socket.encrypted || (confiarProxy && req.headers['x-forwarded-proto'] === 'https');

  function definirCookie(req, res, token, maxAgeSeg) {
    const partes = [`${COOKIE}=${token}`, 'Path=/', 'HttpOnly', 'SameSite=Strict', `Max-Age=${maxAgeSeg}`];
    if (cookieSeguro || ehHttps(req)) partes.push('Secure');
    res.setHeader('Set-Cookie', partes.join('; '));
  }

  // Rotas: [método, padrão, handler(ctx)] — :param captura um segmento
  const rotas = [];
  const rota = (metodo, padrao, fn, opcoes = {}) => {
    const nomes = [];
    const re = new RegExp('^' + padrao.replace(/:(\w+)/g, (_, n) => { nomes.push(n); return '([^/]+)'; }) + '$');
    rotas.push({ metodo, re, nomes, fn, ...opcoes });
  };

  // ---- acesso
  rota('GET', '/api/status', ({ usuario }) => ({ temUsuarios: servico.temUsuarios(), usuario, versao: VERSAO }));

  rota('POST', '/api/primeiro-acesso', async ({ corpo, req, res }) => {
    const s = await servico.criarPrimeiroAdmin(corpo);
    definirCookie(req, res, s.token, Math.floor((s.expiraEm - Date.now()) / 1000));
    return { usuario: s.usuario };
  }, { limitar: true });

  rota('POST', '/api/login', async ({ corpo, req, res }) => {
    const s = await servico.login(corpo.login, corpo.senha);
    definirCookie(req, res, s.token, Math.floor((s.expiraEm - Date.now()) / 1000));
    return { usuario: s.usuario };
  }, { limitar: true });

  rota('POST', '/api/logout', ({ token, req, res }) => {
    servico.logout(token);
    definirCookie(req, res, '', 0);
  });

  rota('POST', '/api/minha-senha', ({ usuario, corpo, token }) =>
    servico.alterarMinhaSenha(usuario, corpo.atual, corpo.nova, token));

  // ---- usuários
  rota('GET', '/api/usuarios', ({ usuario }) => servico.listarUsuarios(usuario));
  rota('POST', '/api/usuarios', ({ usuario, corpo }) => servico.criarUsuario(usuario, corpo));
  rota('PUT', '/api/usuarios/:id', ({ usuario, corpo, p }) => servico.atualizarUsuario(usuario, p.id, corpo));
  rota('DELETE', '/api/usuarios/:id', ({ usuario, p }) => servico.removerUsuario(usuario, p.id));
  rota('GET', '/api/auditoria', ({ usuario, url }) => servico.auditoria(usuario, url.searchParams.get('limite')));

  // ---- dados
  rota('GET', '/api/dados', ({ usuario }) => servico.dados(usuario));
  rota('POST', '/api/setores', ({ usuario, corpo }) => servico.salvarSetor(usuario, { ...corpo, id: null }));
  rota('PUT', '/api/setores/:id', ({ usuario, corpo, p }) => servico.salvarSetor(usuario, { ...corpo, id: p.id }));
  rota('DELETE', '/api/setores/:id', ({ usuario, p }) => servico.removerSetor(usuario, p.id));
  rota('POST', '/api/colaboradores', ({ usuario, corpo }) => servico.salvarColaborador(usuario, { ...corpo, id: null }));
  rota('POST', '/api/colaboradores/importar', ({ usuario, corpo }) => servico.importarColaboradores(usuario, corpo.linhas, corpo.opcoes),
    { limiteCorpo: LIMITE_CORPO_BACKUP });
  rota('PUT', '/api/colaboradores/:id', ({ usuario, corpo, p }) => servico.salvarColaborador(usuario, { ...corpo, id: p.id }));
  rota('DELETE', '/api/colaboradores/:id', ({ usuario, p }) => servico.removerColaborador(usuario, p.id));
  rota('POST', '/api/centros-custo', ({ usuario, corpo }) => servico.salvarCentroCusto(usuario, corpo));
  rota('POST', '/api/centros-custo/importar', ({ usuario, corpo }) => servico.importarCentrosCusto(usuario, corpo.linhas));
  rota('DELETE', '/api/centros-custo/:codigo', ({ usuario, p }) => servico.removerCentroCusto(usuario, p.codigo));
  rota('PUT', '/api/regras', ({ usuario, corpo }) => servico.salvarConfig(usuario, corpo));
  rota('POST', '/api/feriados', ({ usuario, corpo }) => servico.salvarFeriado(usuario, corpo));
  rota('DELETE', '/api/feriados/:data', ({ usuario, p }) => servico.removerFeriado(usuario, p.data));
  rota('POST', '/api/escala/gerar', ({ usuario, corpo }) => servico.gerarEscala(usuario, corpo));
  rota('DELETE', '/api/escala', ({ usuario, url }) => servico.removerEscala(usuario, url.searchParams.get('centroCusto') || ''));
  rota('POST', '/api/escala/celula', ({ usuario, corpo }) => servico.alterarCelula(usuario, corpo));
  rota('POST', '/api/exemplo', ({ usuario }) => servico.carregarExemplo(usuario));
  rota('DELETE', '/api/dados', ({ usuario }) => servico.limparDados(usuario));
  rota('GET', '/api/backup', ({ usuario }) => servico.backup(usuario));
  rota('GET', '/api/contratos', ({ usuario }) => servico.listarContratos(usuario));
  rota('POST', '/api/contratos', ({ usuario, corpo }) => servico.salvarContrato(usuario, { ...corpo, id: null }));
  rota('PUT', '/api/contratos/:id', ({ usuario, corpo, p }) => servico.salvarContrato(usuario, { ...corpo, id: p.id }));
  rota('DELETE', '/api/contratos/:id', ({ usuario, p }) => servico.removerContrato(usuario, p.id));
  rota('POST', '/api/contratos/:id/documento', ({ usuario, corpo, p }) => servico.registrarDocumento(usuario, p.id, corpo.formato));
  rota('GET', '/api/indices/:serie', ({ usuario, p }) => servico.indices(usuario, p.serie));
  rota('POST', '/api/indices/:serie/atualizar', ({ usuario, p }) => servico.atualizarIndices(usuario, p.serie));
  rota('PUT', '/api/indices/:serie/:mes', ({ usuario, corpo, p }) => servico.salvarIndice(usuario, p.serie, p.mes, corpo.valor));
  rota('DELETE', '/api/indices/:serie/:mes', ({ usuario, p }) => servico.removerIndice(usuario, p.serie, p.mes));
  rota('GET', '/api/distratos', ({ usuario }) => servico.listarDistratos(usuario));
  rota('POST', '/api/distratos', ({ usuario, corpo }) => servico.salvarDistrato(usuario, { ...corpo, id: null }));
  rota('PUT', '/api/distratos/:id', ({ usuario, corpo, p }) => servico.salvarDistrato(usuario, { ...corpo, id: p.id }));
  rota('DELETE', '/api/distratos/:id', ({ usuario, p }) => servico.removerDistrato(usuario, p.id));
  rota('POST', '/api/distratos/:id/documento', ({ usuario, corpo, p }) => servico.registrarDocumentoDistrato(usuario, p.id, corpo.formato));
  rota('GET', '/api/custos', ({ usuario }) => servico.custos(usuario));
  rota('PUT', '/api/custos/parametros', ({ usuario, corpo }) => servico.salvarParametrosCustos(usuario, corpo));
  rota('POST', '/api/folha/:comp/abrir', ({ usuario, p }) => servico.abrirCompetencia(usuario, p.comp));
  rota('PUT', '/api/folha/:comp', ({ usuario, corpo, p }) => servico.salvarFolha(usuario, p.comp, corpo), { limiteCorpo: LIMITE_CORPO_BACKUP });
  rota('POST', '/api/folha/:comp/importar', ({ usuario, corpo, p }) => servico.importarFolha(usuario, p.comp, corpo.linhas), { limiteCorpo: LIMITE_CORPO_BACKUP });
  rota('DELETE', '/api/folha/:comp', ({ usuario, p }) => servico.removerCompetencia(usuario, p.comp));
  rota('POST', '/api/restaurar', ({ usuario, corpo }) => servico.restaurar(usuario, corpo), { limiteCorpo: LIMITE_CORPO_BACKUP });

  async function tratarApi(req, res, url) {
    const metodo = req.method;
    let achou = null;
    let params = null;
    let metodoErrado = false;
    for (const r of rotas) {
      const m = r.re.exec(url.pathname);
      if (!m) continue;
      if (r.metodo !== metodo) { metodoErrado = true; continue; }
      achou = r;
      params = Object.fromEntries(r.nomes.map((n, i) => [n, decodeURIComponent(m[i + 1])]));
      break;
    }
    if (!achou) return json(res, metodoErrado ? 405 : 404, { erro: metodoErrado ? 'Método não permitido.' : 'Rota não encontrada.' });

    if (metodo !== 'GET') {
      // proteção contra CSRF: cabeçalho próprio (força preflight entre origens) + mesma origem
      if (req.headers['x-requested-with'] !== 'escala') return json(res, 403, { erro: 'Requisição recusada.' });
      const origem = req.headers.origin;
      if (origem && origem !== `${ehHttps(req) ? 'https' : 'http'}://${req.headers.host}`) {
        return json(res, 403, { erro: 'Origem não permitida.' });
      }
    }
    if (achou.limitar && !permitirLogin(ipDe(req))) {
      return json(res, 429, { erro: 'Muitas tentativas a partir deste endereço. Aguarde alguns minutos.' });
    }

    const token = lerCookies(req)[COOKIE] || null;
    const usuario = servico.sessao(token);
    const corpo = metodo === 'GET' ? {} : await lerCorpo(req, achou.limiteCorpo || LIMITE_CORPO);
    const resultado = await achou.fn({ req, res, url, p: params, corpo, token, usuario });
    return json(res, 200, resultado);
  }

  function tratarEstatico(req, res, url) {
    if (req.method !== 'GET' && req.method !== 'HEAD') return json(res, 405, { erro: 'Método não permitido.' });
    let rel = ESTATICOS[url.pathname];
    if (!rel && PASTAS_ESTATICAS.some((p) => url.pathname.startsWith(p))) rel = url.pathname.slice(1);
    const arquivo = rel && path.resolve(RAIZ, rel);
    if (!arquivo || !arquivo.startsWith(RAIZ + path.sep) || !TIPOS[path.extname(arquivo)]) {
      res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
      return res.end('Não encontrado');
    }
    fs.readFile(arquivo, (err, conteudo) => {
      if (err) {
        res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
        return res.end('Não encontrado');
      }
      res.writeHead(200, { 'Content-Type': TIPOS[path.extname(arquivo)], 'Cache-Control': 'no-store' });
      res.end(req.method === 'HEAD' ? undefined : conteudo);
    });
  }

  return http.createServer(async (req, res) => {
    cabecalhosSeguranca(res);
    let url;
    try {
      url = new URL(req.url, 'http://localhost');
    } catch (e) {
      return json(res, 400, { erro: 'Endereço inválido.' });
    }
    try {
      if (url.pathname.startsWith('/api/')) await tratarApi(req, res, url);
      else tratarEstatico(req, res, url);
    } catch (e) {
      if (res.headersSent) return;
      if (e instanceof ErroApp) return json(res, e.status, { erro: e.message });
      console.error(new Date().toISOString(), req.method, url.pathname, e);
      json(res, 500, { erro: 'Erro interno no servidor.' });
    }
  });
}

// -------------------------------------------------------------- execução

const MANTER_COPIAS = 20;

/**
 * Cópia do banco ao iniciar (antes de qualquer atualização do esquema), em dados/backups.
 * Mantém as 20 mais recentes. Usa VACUUM INTO, que gera uma cópia consistente mesmo com WAL.
 */
function copiaDeSeguranca(arquivo) {
  if (!fs.existsSync(arquivo) || !fs.statSync(arquivo).size) return null;
  const pasta = path.join(path.dirname(arquivo), 'backups');
  fs.mkdirSync(pasta, { recursive: true });
  const agora = new Date();
  const p2 = (n) => String(n).padStart(2, '0');
  const carimbo = `${agora.getFullYear()}-${p2(agora.getMonth() + 1)}-${p2(agora.getDate())}_${p2(agora.getHours())}h${p2(agora.getMinutes())}`;
  const destino = path.join(pasta, `${path.basename(arquivo, '.db')}_${carimbo}_v${VERSAO}.db`);
  if (fs.existsSync(destino)) return destino;
  const { DatabaseSync } = require('node:sqlite');
  const origem = new DatabaseSync(arquivo);
  try {
    origem.exec(`VACUUM INTO '${destino.replace(/'/g, "''")}'`);
  } finally {
    origem.close();
  }
  const copias = fs.readdirSync(pasta).filter((n) => n.endsWith('.db')).sort();
  for (const antiga of copias.slice(0, Math.max(0, copias.length - MANTER_COPIAS))) fs.rmSync(path.join(pasta, antiga), { force: true });
  return destino;
}

if (require.main === module) {
  const porta = Number(process.env.PORT) || 3000;
  const host = process.env.HOST || '127.0.0.1';
  const arquivo = process.env.DB_PATH || path.join(RAIZ, 'dados', 'escala.db');
  let copia = null;
  try {
    copia = copiaDeSeguranca(arquivo);
  } catch (e) {
    console.error('Aviso: não foi possível fazer a cópia de segurança do banco:', e.message);
  }
  const db = abrirBanco(arquivo);
  const servidor = criarApp({
    servico: criarServico(db),
    cookieSeguro: process.env.COOKIE_SECURE === '1',
    confiarProxy: process.env.TRUST_PROXY === '1',
  });
  servidor.on('error', (e) => {
    if (e.code === 'EADDRINUSE') {
      console.error('');
      console.error(`ATENÇÃO: a porta ${porta} já está em uso.`);
      console.error('Provavelmente o sistema (talvez uma versão anterior) já está aberto em outra janela.');
      console.error('Feche a outra janela do servidor e inicie de novo, ou use outra porta (ex.: PORT=3001).');
      console.error('');
    } else {
      console.error('Não foi possível iniciar o servidor:', e.message);
    }
    db.close();
    process.exit(1);
  });
  servidor.listen(porta, host, () => {
    const endereco = host === '0.0.0.0' ? 'localhost' : host;
    console.log(`CORE RH — versão ${VERSAO}`);
    console.log(`Rodando em http://${endereco}:${porta}`);
    console.log(`Banco de dados: ${arquivo}`);
    if (copia) console.log(`Cópia de segurança: ${copia}`);
  });
  const encerrar = () => servidor.close(() => { db.close(); process.exit(0); });
  process.on('SIGINT', encerrar);
  process.on('SIGTERM', encerrar);
}

module.exports = { criarApp, criarLimitador, copiaDeSeguranca };
