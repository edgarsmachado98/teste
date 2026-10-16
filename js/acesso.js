/* Tela de login, primeiro acesso, sessão e cadastro de usuários do sistema. */
(function () {
  'use strict';

  const A = window.EscalaAuth;
  const App = window.EscalaApp;
  const $ = (sel) => document.querySelector(sel);
  const esc = App.esc;
  const CHAVE_SESSAO = 'gerador-escala-sessao-v1';
  const DURACAO_SESSAO = 8 * 60 * 60 * 1000; // 8 horas

  // localStorage pode estar indisponível (janela anônima, bloqueio de dados)
  const memoria = {};
  function armazenamento(tipo) {
    try {
      const st = window[tipo];
      const k = '__teste__';
      st.setItem(k, '1');
      st.removeItem(k);
      return st;
    } catch (e) {
      return {
        getItem: (k) => (k in memoria ? memoria[k] : null),
        setItem: (k, v) => { memoria[k] = String(v); },
        removeItem: (k) => { delete memoria[k]; },
      };
    }
  }

  const auth = A.criarAuth(armazenamento('localStorage'));
  const sessaoSt = armazenamento('sessionStorage');
  let usuario = null;

  // ------------------------------------------------------------- sessão

  function lerSessao() {
    try {
      const s = JSON.parse(sessaoSt.getItem(CHAVE_SESSAO));
      if (!s || s.expira < Date.now()) return null;
      const u = auth.buscar(s.id);
      return u && u.ativo ? u : null;
    } catch (e) {
      return null;
    }
  }

  function gravarSessao(u) {
    sessaoSt.setItem(CHAVE_SESSAO, JSON.stringify({ id: u.id, expira: Date.now() + DURACAO_SESSAO }));
  }

  function entrar(u) {
    usuario = u;
    gravarSessao(u);
    $('#tela-acesso').hidden = true;
    $('#app').hidden = false;
    $('#usuario-nome').textContent = u.nome;
    $('#usuario-perfil').textContent = A.PERFIS[u.perfil].nome;
    App.iniciar(u);
    if (u.perfil === 'admin') renderUsuarios();
  }

  function sair() {
    usuario = null;
    sessaoSt.removeItem(CHAVE_SESSAO);
    App.encerrar();
    mostrarAcesso();
  }

  function mostrarAcesso() {
    $('#app').hidden = true;
    $('#tela-acesso').hidden = false;
    const primeiro = !auth.temUsuarios();
    $('#form-login').hidden = primeiro;
    $('#form-primeiro').hidden = !primeiro;
    for (const f of [$('#form-login'), $('#form-primeiro')]) f.reset();
    for (const el of [$('#login-erro'), $('#primeiro-erro')]) el.hidden = true;
    (primeiro ? $('#pri-nome') : $('#login-usuario')).focus();
  }

  // a sessão expira mesmo com a página aberta
  setInterval(() => {
    if (usuario && !lerSessao()) {
      sair();
      mostrarErro($('#login-erro'), 'Sua sessão expirou. Entre novamente.');
    }
  }, 60 * 1000);

  function mostrarErro(el, msg) {
    el.textContent = msg;
    el.hidden = false;
  }

  async function ocupado(form, fn) {
    const botao = form.querySelector('button[type=submit]');
    const texto = botao.textContent;
    botao.disabled = true;
    botao.textContent = 'Aguarde…';
    try {
      await fn();
    } finally {
      botao.disabled = false;
      botao.textContent = texto;
    }
  }

  // -------------------------------------------------------------- login

  $('#form-login').addEventListener('submit', (ev) => {
    ev.preventDefault();
    const f = ev.target.elements;
    const erro = $('#login-erro');
    erro.hidden = true;
    ocupado(ev.target, async () => {
      try {
        entrar(await auth.autenticar(f.login.value, f.senha.value));
      } catch (e) {
        f.senha.value = '';
        f.senha.focus();
        mostrarErro(erro, e.message);
      }
    });
  });

  $('#form-primeiro').addEventListener('submit', (ev) => {
    ev.preventDefault();
    const f = ev.target.elements;
    const erro = $('#primeiro-erro');
    erro.hidden = true;
    if (f.senha.value !== f.confirma.value) return mostrarErro(erro, 'As senhas não conferem.');
    ocupado(ev.target, async () => {
      try {
        entrar(await auth.cadastrar({ nome: f.nome.value, login: f.login.value, senha: f.senha.value, perfil: 'admin' }));
      } catch (e) {
        mostrarErro(erro, e.message);
      }
    });
  });

  $('#btn-sair').addEventListener('click', sair);

  // ---------------------------------------------------- trocar senha

  function pedirNovaSenha(titulo, { exigirAtual, aplicar }) {
    const atual = $('#dlg-senha-atual');
    const nova = $('#dlg-senha-nova');
    const confirma = $('#dlg-senha-confirma');
    const erro = $('#dlg-senha-erro');
    for (const el of [atual, nova, confirma]) el.value = '';
    erro.hidden = true;
    $('#dialogo-senha-atual-rotulo').hidden = !exigirAtual;
    const promessa = App.abrirDialogo(titulo, {
      cancelar: true,
      senha: true,
      erroEl: erro,
      validar: async () => {
        if (nova.value !== confirma.value) throw new Error('As senhas não conferem.');
        await aplicar(nova.value, exigirAtual ? atual.value : undefined);
      },
    });
    (exigirAtual ? atual : nova).focus();
    return promessa;
  }

  $('#btn-minha-senha').addEventListener('click', async () => {
    const ok = await pedirNovaSenha('Alterar minha senha', {
      exigirAtual: true,
      aplicar: (nova, atual) => auth.definirSenha(usuario.id, nova, atual),
    });
    if (ok) App.avisar('Senha alterada.');
  });

  // ------------------------------------------------- cadastro de usuários

  const formUsu = $('#form-usuario');
  $('#usu-perfil').innerHTML = Object.entries(A.PERFIS)
    .map(([k, p]) => `<option value="${k}">${esc(p.nome)}</option>`).join('');
  $('#perfis-lista').innerHTML = Object.values(A.PERFIS)
    .map((p) => `<li><b>${esc(p.nome)}:</b> ${esc(p.descricao)}.</li>`).join('');

  function atualizarDicaPerfil() {
    $('#usu-perfil-dica').textContent = A.PERFIS[$('#usu-perfil').value].descricao + '.';
  }
  $('#usu-perfil').addEventListener('change', atualizarDicaPerfil);

  function modoNovo() {
    formUsu.elements.id.value = '';
    $('#titulo-form-usuario').textContent = 'Novo usuário';
    $('#usu-login').readOnly = false;
    $('#usu-ativo-rotulo').hidden = true;
    $('#usu-senha-rotulo').textContent = 'Senha';
    $('#usu-senha-dica').textContent = 'Mínimo de 8 caracteres, com letras e números.';
    $('#usu-perfil').value = 'operador';
    $('#usuario-erro').hidden = true;
    atualizarDicaPerfil();
  }

  formUsu.addEventListener('reset', () => setTimeout(modoNovo));

  formUsu.addEventListener('submit', (ev) => {
    ev.preventDefault();
    const f = formUsu.elements;
    const erro = $('#usuario-erro');
    erro.hidden = true;
    if (!usuario || usuario.perfil !== 'admin') return mostrarErro(erro, 'Apenas administradores cadastram usuários.');
    if (f.senha.value !== f.confirma.value) return mostrarErro(erro, 'As senhas não conferem.');
    ocupado(formUsu, async () => {
      try {
        if (f.id.value) {
          if (f.id.value === usuario.id && (f.perfil.value !== 'admin' || !f.ativo.checked)) {
            throw new Error('Você não pode retirar o próprio acesso de administrador.');
          }
          const erroSenha = f.senha.value && A.validarSenha(f.senha.value);
          if (erroSenha) throw new Error(erroSenha);
          auth.atualizar(f.id.value, { nome: f.nome.value, perfil: f.perfil.value, ativo: f.ativo.checked });
          if (f.senha.value) await auth.definirSenha(f.id.value, f.senha.value);
          if (f.id.value === usuario.id) {
            usuario = auth.buscar(usuario.id);
            $('#usuario-nome').textContent = usuario.nome;
          }
        } else {
          await auth.cadastrar({ nome: f.nome.value, login: f.login.value, senha: f.senha.value, perfil: f.perfil.value });
        }
        formUsu.reset();
        renderUsuarios();
      } catch (e) {
        mostrarErro(erro, e.message);
      }
    });
  });

  $('#lista-usuarios').addEventListener('click', async (ev) => {
    const b = ev.target.closest('button[data-acao]');
    if (!b || !usuario || usuario.perfil !== 'admin') return;
    const u = auth.buscar(b.dataset.id);
    if (!u) return;
    try {
      if (b.dataset.acao === 'editar') {
        const f = formUsu.elements;
        modoNovo();
        f.id.value = u.id;
        f.nome.value = u.nome;
        f.login.value = u.login;
        f.perfil.value = u.perfil;
        f.ativo.checked = u.ativo;
        $('#usu-login').readOnly = true;
        $('#usu-ativo-rotulo').hidden = false;
        $('#usu-senha-rotulo').textContent = 'Nova senha (opcional)';
        $('#usu-senha-dica').textContent = 'Deixe em branco para manter a senha atual.';
        $('#titulo-form-usuario').textContent = 'Editar usuário';
        atualizarDicaPerfil();
        f.nome.focus();
      } else if (b.dataset.acao === 'desbloquear') {
        auth.atualizar(u.id, { desbloquear: true });
        renderUsuarios();
      } else if (b.dataset.acao === 'excluir') {
        if (!(await App.confirmar(`Excluir o usuário ${u.nome} (${u.login})?`))) return;
        auth.remover(u.id, usuario.id);
        renderUsuarios();
      }
    } catch (e) {
      App.avisar(e.message);
    }
  });

  function renderUsuarios() {
    const fmt = (iso) => (iso ? new Date(iso).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' }) : 'Nunca');
    const lista = auth.listar().sort((a, b) => a.nome.localeCompare(b.nome));
    $('#lista-usuarios').innerHTML = lista.map((u) => {
      const bloqueado = auth.bloqueado(u.id);
      const situacao = bloqueado ? '<span class="chip ruim">Bloqueado</span>'
        : u.ativo ? '<span class="chip bom">Ativo</span>' : '<span class="chip">Inativo</span>';
      return `<tr>
        <td>${esc(u.nome)}${u.id === usuario.id ? ' <small>(você)</small>' : ''}</td>
        <td>${esc(u.login)}</td>
        <td>${esc(A.PERFIS[u.perfil].nome)}</td>
        <td>${situacao}</td>
        <td>${fmt(u.ultimoAcesso)}</td>
        <td class="acoes">
          ${bloqueado ? `<button type="button" class="mini sec" data-acao="desbloquear" data-id="${u.id}">Desbloquear</button>` : ''}
          <button type="button" class="mini sec" data-acao="editar" data-id="${u.id}">Editar</button>
          ${u.id === usuario.id ? '' : `<button type="button" class="mini perigo" data-acao="excluir" data-id="${u.id}">Excluir</button>`}
        </td></tr>`;
    }).join('');
  }

  document.querySelector('.aba[data-aba=usuarios]').addEventListener('click', () => {
    if (usuario && usuario.perfil === 'admin') renderUsuarios();
  });

  // ------------------------------------------------------------ início

  modoNovo();
  const sessao = lerSessao();
  if (sessao) entrar(sessao);
  else mostrarAcesso();
})();
