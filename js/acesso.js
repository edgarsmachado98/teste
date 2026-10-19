/* Tela de login, primeiro acesso, sessão e cadastro de usuários (via API do servidor). */
(function () {
  'use strict';

  const api = window.EscalaApi;
  const App = window.EscalaApp;
  const $ = (sel) => document.querySelector(sel);
  const esc = App.esc;

  const PERFIS = {
    admin: { nome: 'Administrador', descricao: 'Acesso total, inclusive cadastro de usuários' },
    operador: { nome: 'Operador', descricao: 'Cadastra setores e colaboradores e gera escalas' },
    consulta: { nome: 'Consulta', descricao: 'Apenas visualiza as escalas' },
  };
  const ACOES = {
    'acesso.login': 'Entrou no sistema',
    'acesso.bloqueado': 'Acesso bloqueado',
    'usuario.primeiro_admin': 'Criou o administrador',
    'usuario.criar': 'Cadastrou usuário',
    'usuario.alterar': 'Alterou usuário',
    'usuario.excluir': 'Excluiu usuário',
    'usuario.senha_propria': 'Trocou a própria senha',
    'setor.criar': 'Cadastrou setor',
    'setor.alterar': 'Alterou setor',
    'setor.excluir': 'Excluiu setor',
    'colaborador.criar': 'Cadastrou colaborador',
    'colaborador.alterar': 'Alterou colaborador',
    'colaborador.excluir': 'Excluiu colaborador',
    'colaborador.importar': 'Importou colaboradores',
    'colaborador.desligar': 'Registrou desligamento',
    'centro.criar': 'Cadastrou centro de custo',
    'centro.alterar': 'Alterou centro de custo',
    'centro.excluir': 'Excluiu centro de custo',
    'centro.importar': 'Importou centros de custo',
    'custos.parametros': 'Alterou encargos e alertas',
    'folha.abrir': 'Abriu competência da folha',
    'folha.salvar': 'Salvou lançamentos da folha',
    'folha.importar': 'Importou lançamentos da folha',
    'folha.excluir': 'Excluiu competência da folha',
    'regras.alterar': 'Alterou regras',
    'feriado.salvar': 'Cadastrou feriado',
    'feriado.excluir': 'Excluiu feriado',
    'escala.gerar': 'Gerou escala',
    'escala.ajuste': 'Ajustou escala',
    'dados.exemplo': 'Carregou dados de exemplo',
    'dados.limpar': 'Apagou todos os dados',
    'dados.backup': 'Exportou backup',
    'dados.restaurar': 'Restaurou backup',
    'contrato.criar': 'Cadastrou contrato de representante',
    'contrato.alterar': 'Alterou contrato de representante',
    'contrato.excluir': 'Excluiu contrato de representante',
    'contrato.documento': 'Gerou documento do contrato',
    'distrato.criar': 'Registrou distrato',
    'distrato.alterar': 'Alterou distrato',
    'distrato.excluir': 'Excluiu distrato',
    'distrato.documento': 'Gerou documento do distrato',
    'indice.atualizar': 'Atualizou o IGP-M',
    'indice.manual': 'Informou índice manualmente',
  };
  const quando = (iso) => (iso ? new Date(iso).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' }) : 'Nunca');

  let usuario = null;

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

  // ------------------------------------------------------------- sessão

  async function entrar(u) {
    usuario = u;
    $('#tela-acesso').hidden = true;
    $('#app').hidden = false;
    $('#usuario-nome').textContent = u.nome;
    $('#usuario-perfil').textContent = PERFIS[u.perfil].nome;
    await App.iniciar(u);
    if (u.perfil === 'admin') renderUsuarios();
  }

  function mostrarAcesso(primeiro, mensagem) {
    usuario = null;
    App.encerrar();
    $('#app').hidden = true;
    $('#tela-acesso').hidden = false;
    $('#form-login').hidden = primeiro;
    $('#form-primeiro').hidden = !primeiro;
    for (const f of [$('#form-login'), $('#form-primeiro')]) f.reset();
    $('#login-erro').hidden = true;
    $('#primeiro-erro').hidden = true;
    if (mensagem) mostrarErro($('#login-erro'), mensagem);
    (primeiro ? $('#pri-nome') : $('#login-usuario')).focus();
  }

  async function verificarSessao() {
    try {
      const s = await api.get('/api/status');
      if (s.versao) document.getElementById('versao-sistema').textContent = `Versão ${s.versao}`;
      if (s.usuario) await entrar(s.usuario);
      else mostrarAcesso(!s.temUsuarios);
    } catch (e) {
      mostrarAcesso(false, e.message);
    }
  }

  window.addEventListener('sessao-expirada', () => {
    if (usuario) mostrarAcesso(false, 'Sua sessão expirou ou foi encerrada. Entre novamente.');
  });

  // -------------------------------------------------------------- login

  $('#form-login').addEventListener('submit', (ev) => {
    ev.preventDefault();
    const f = ev.target.elements;
    const erro = $('#login-erro');
    erro.hidden = true;
    ocupado(ev.target, async () => {
      try {
        const r = await api.post('/api/login', { login: f.login.value, senha: f.senha.value });
        await entrar(r.usuario);
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
        const r = await api.post('/api/primeiro-acesso', { nome: f.nome.value, login: f.login.value, senha: f.senha.value });
        await entrar(r.usuario);
      } catch (e) {
        mostrarErro(erro, e.message);
        if (e.status === 409) setTimeout(() => mostrarAcesso(false, e.message), 1500);
      }
    });
  });

  $('#btn-sair').addEventListener('click', async () => {
    try { await api.post('/api/logout'); } catch (e) { /* encerra localmente mesmo assim */ }
    mostrarAcesso(false);
  });

  // ---------------------------------------------------- trocar senha

  $('#btn-minha-senha').addEventListener('click', async () => {
    const atual = $('#dlg-senha-atual');
    const nova = $('#dlg-senha-nova');
    const confirma = $('#dlg-senha-confirma');
    const erro = $('#dlg-senha-erro');
    for (const el of [atual, nova, confirma]) el.value = '';
    erro.hidden = true;
    $('#dialogo-senha-atual-rotulo').hidden = false;
    const promessa = App.abrirDialogo('Alterar minha senha', {
      cancelar: true,
      senha: true,
      erroEl: erro,
      validar: async () => {
        if (nova.value !== confirma.value) throw new Error('As senhas não conferem.');
        await api.post('/api/minha-senha', { atual: atual.value, nova: nova.value });
      },
    });
    atual.focus();
    if (await promessa) App.avisar('Senha alterada. Suas sessões em outros computadores foram encerradas.');
  });

  // ------------------------------------------------- cadastro de usuários

  const formUsu = $('#form-usuario');
  $('#usu-perfil').innerHTML = Object.entries(PERFIS)
    .map(([k, p]) => `<option value="${k}">${esc(p.nome)}</option>`).join('');
  $('#perfis-lista').innerHTML = Object.values(PERFIS)
    .map((p) => `<li><b>${esc(p.nome)}:</b> ${esc(p.descricao)}.</li>`).join('');

  function atualizarDicaPerfil() {
    $('#usu-perfil-dica').textContent = PERFIS[$('#usu-perfil').value].descricao + '.';
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
    if (f.senha.value !== f.confirma.value) return mostrarErro(erro, 'As senhas não conferem.');
    ocupado(formUsu, async () => {
      try {
        if (f.id.value) {
          const dados = { nome: f.nome.value, perfil: f.perfil.value, ativo: f.ativo.checked };
          if (f.senha.value) dados.senha = f.senha.value;
          const u = await api.put(`/api/usuarios/${f.id.value}`, dados);
          if (u.id === usuario.id) {
            usuario = u;
            $('#usuario-nome').textContent = u.nome;
          }
        } else {
          await api.post('/api/usuarios', {
            nome: f.nome.value, login: f.login.value, senha: f.senha.value, perfil: f.perfil.value,
          });
        }
        formUsu.reset();
        renderUsuarios();
      } catch (e) {
        mostrarErro(erro, e.message);
      }
    });
  });

  let usuariosCache = [];

  $('#lista-usuarios').addEventListener('click', async (ev) => {
    const b = ev.target.closest('button[data-acao]');
    if (!b) return;
    const u = usuariosCache.find((x) => x.id === b.dataset.id);
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
        $('#usu-senha-dica').textContent = 'Deixe em branco para manter a senha atual. Ao redefinir, as sessões abertas do usuário são encerradas.';
        $('#titulo-form-usuario').textContent = 'Editar usuário';
        atualizarDicaPerfil();
        f.nome.focus();
      } else if (b.dataset.acao === 'desbloquear') {
        await api.put(`/api/usuarios/${u.id}`, { desbloquear: true });
        renderUsuarios();
      } else if (b.dataset.acao === 'excluir') {
        if (!(await App.confirmar(`Excluir o usuário ${u.nome} (${u.login})?`))) return;
        await api.del(`/api/usuarios/${u.id}`);
        renderUsuarios();
      }
    } catch (e) {
      App.avisar(e.message);
    }
  });

  async function renderUsuarios() {
    try {
      usuariosCache = await api.get('/api/usuarios');
    } catch (e) {
      if (e.status !== 401) App.avisar(e.message);
      return;
    }
    $('#lista-usuarios').innerHTML = usuariosCache.map((u) => {
      const situacao = u.bloqueado ? '<span class="chip ruim">Bloqueado</span>'
        : u.ativo ? '<span class="chip bom">Ativo</span>' : '<span class="chip">Inativo</span>';
      const eu = u.id === usuario.id;
      return `<tr>
        <td>${esc(u.nome)}${eu ? ' <small>(você)</small>' : ''}</td>
        <td>${esc(u.login)}</td>
        <td>${esc(PERFIS[u.perfil].nome)}</td>
        <td>${situacao}</td>
        <td>${quando(u.ultimoAcesso)}</td>
        <td class="acoes">
          ${u.bloqueado ? `<button type="button" class="mini sec" data-acao="desbloquear" data-id="${u.id}">Desbloquear</button>` : ''}
          <button type="button" class="mini sec" data-acao="editar" data-id="${u.id}">Editar</button>
          ${eu ? '' : `<button type="button" class="mini perigo" data-acao="excluir" data-id="${u.id}">Excluir</button>`}
        </td></tr>`;
    }).join('');
    renderAuditoria();
  }

  async function renderAuditoria() {
    try {
      const lista = await api.get('/api/auditoria?limite=200');
      $('#lista-auditoria').innerHTML = lista.map((a) => `<tr>
        <td>${quando(a.em)}</td><td>${esc(a.usuario || '—')}</td>
        <td>${esc(ACOES[a.acao] || a.acao)}</td><td>${esc(a.detalhe || '')}</td></tr>`).join('')
        || '<tr><td colspan="4" class="vazio">Nenhum registro.</td></tr>';
    } catch (e) {
      if (e.status !== 401) App.avisar(e.message);
    }
  }

  $('#btn-auditoria').addEventListener('click', renderAuditoria);
  document.querySelector('.modulo[data-modulo=usuarios]').addEventListener('click', () => {
    if (usuario && usuario.perfil === 'admin') renderUsuarios();
  });

  // ------------------------------------------------------------ início

  modoNovo();
  verificarSessao();
})();
