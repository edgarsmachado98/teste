/* Cadastro de empresas: dados, regime tributário, modelos (contrato, distrato, planilha de comissões) e logotipo. */
(function () {
  'use strict';

  const C = window.EscalaContrato;
  const api = window.EscalaApi;
  const App = window.EscalaApp;
  const $ = (sel) => document.querySelector(sel);
  const esc = App.esc;

  const REGIMES = ['Simples Nacional', 'Lucro Presumido', 'Lucro Real', 'MEI', 'Outro'];
  // mesmos tipos e extensões aceitos pelo servidor
  const ARQUIVOS = [
    { tipo: 'contrato', nome: 'Modelo de contrato', aceita: '.docx,.doc,.pdf,.odt' },
    { tipo: 'distrato', nome: 'Modelo de distrato', aceita: '.docx,.doc,.pdf,.odt' },
    { tipo: 'planilha', nome: 'Modelo de planilha de comissões para distrato', aceita: '.xlsx,.xls,.ods,.csv,.pdf' },
    { tipo: 'logo', nome: 'Logotipo (PNG ou JPG)', aceita: '.png,.jpg,.jpeg' },
  ];
  const MAX = 10 * 1024 * 1024;

  let usuario = null;
  let empresas = [];
  const podeEditar = () => !!usuario && usuario.perfil !== 'consulta';
  const form = $('#form-empresa');
  const urlArquivo = (e, a) => `/api/empresas/${encodeURIComponent(e.id)}/arquivos/${encodeURIComponent(a.id)}`;
  const logoDe = (e) => (e.arquivos || []).find((a) => a.tipo === 'logo');
  const tamanho = (n) => (n >= 1048576 ? `${(n / 1048576).toLocaleString('pt-BR', { maximumFractionDigits: 1 })} MB`
    : `${Math.max(1, Math.round(n / 1024))} KB`);
  const quando = (iso) => (iso ? new Date(iso).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' }) : '');

  $('#sel-regime-empresa').innerHTML = '<option value="">Selecione</option>' + REGIMES.map((r) => `<option>${esc(r)}</option>`).join('');
  $('#sel-uf-empresa').innerHTML = '<option value=""></option>' + C.UFS.map((u) => `<option>${u}</option>`).join('');

  async function carregar() {
    try {
      empresas = await api.get('/api/empresas');
    } catch (e) {
      if (e.status !== 401) App.avisar(e.message);
    }
    renderLista();
  }

  function renderLista() {
    const busca = $('#busca-empresa').value.trim().toLowerCase();
    const dig = C.soDigitos(busca);
    const lista = empresas.filter((e) => !busca || e.razao.toLowerCase().includes(busca) || (e.fantasia || '').toLowerCase().includes(busca) ||
      (dig && C.soDigitos(e.cnpj).includes(dig)));
    $('#lista-empresas').innerHTML = lista.map((e) => {
      const tem = (t) => (e.arquivos || []).some((a) => a.tipo === t);
      const chips = ARQUIVOS.filter((a) => a.tipo !== 'logo' && tem(a.tipo))
        .map((a) => {
          const n = (e.arquivos || []).filter((x) => x.tipo === a.tipo).length;
          return `<span class="chip bom mini">${esc(a.nome.replace('Modelo de ', '').replace(' para distrato', ''))}${n > 1 ? ` (${n})` : ''}</span>`;
        }).join(' ');
      return `<tr>
        <td>${logoDe(e) ? `<img src="${urlArquivo(e, logoDe(e))}" alt="" class="emp-logo-lista">` : ''}</td>
        <td><b>${esc(e.razao)}</b>${e.fantasia ? `<br><small class="suave">${esc(e.fantasia)}</small>` : ''}</td>
        <td>${esc(e.cnpj)}</td><td>${esc(e.regime || '—')}</td>
        <td>${esc([e.cidade, e.uf].filter(Boolean).join('-'))}</td>
        <td>${chips || '<small class="suave">nenhum modelo</small>'}</td>
        <td class="acoes">
          <button type="button" class="mini sec" data-acao="exibir" data-id="${e.id}">Exibir</button>
          ${podeEditar() ? `<button type="button" class="mini sec" data-acao="editar" data-id="${e.id}">Editar</button>` : ''}
          ${podeEditar() ? `<button type="button" class="mini perigo" data-acao="excluir" data-id="${e.id}">Excluir</button>` : ''}
        </td></tr>`;
    }).join('') || `<tr><td colspan="7" class="vazio">${empresas.length ? 'Nenhuma empresa encontrada.' : 'Nenhuma empresa cadastrada.'}</td></tr>`;
  }
  $('#busca-empresa').addEventListener('input', renderLista);

  // modo do formulário: 'novo' (arquivos escolhidos ficam pendentes até salvar), 'exibir' (só leitura) ou 'editar'
  let modo = 'novo';
  let pendentes = []; // { chave, tipo, nome, tamanho, conteudo (base64) }
  let seq = 0;

  const botaoArquivo = (def, temAlgum, rotulos) => `<div class="linha-botoes"><label class="botao sec mini">${
    def.tipo === 'logo' ? (temAlgum ? rotulos[1] : rotulos[0]) : (temAlgum ? 'Adicionar outro' : rotulos[0])
  }<input type="file" data-tipo="${def.tipo}" accept="${def.aceita}"${def.tipo === 'logo' ? '' : ' multiple'} hidden></label></div>`;

  // modelos: vários por tipo (ex.: contrato SP e contrato RS/SC); logotipo: um só
  function renderArquivos(e) {
    $('#emp-arquivos-dica').hidden = modo !== 'novo' || !podeEditar();
    $('#emp-lista-arquivos').innerHTML = ARQUIVOS.map((def) => {
      const logo = def.tipo === 'logo';
      let itens;
      let temAlgum;
      if (modo === 'novo') {
        const lista = pendentes.filter((x) => x.tipo === def.tipo);
        temAlgum = lista.length > 0;
        itens = lista.map((a) => `<div class="emp-item">
          ${logo ? `<img src="data:${/\.png$/i.test(a.nome) ? 'image/png' : 'image/jpeg'};base64,${a.conteudo}" alt="Logotipo">` : ''}
          <small><b>${esc(a.nome)}</b> · ${tamanho(a.tamanho)} · será enviado ao salvar</small>
          <div class="linha-botoes"><button type="button" class="mini perigo" data-retirar="${a.chave}">Retirar</button></div></div>`).join('');
      } else {
        const lista = ((e && e.arquivos) || []).filter((x) => x.tipo === def.tipo);
        temAlgum = lista.length > 0;
        itens = lista.map((a) => `<div class="emp-item">
          ${logo ? `<img src="${urlArquivo(e, a)}" alt="Logotipo">` : ''}
          <small><b>${esc(a.nome)}</b> · ${tamanho(a.tamanho)} · ${esc(quando(a.enviadoEm))}${a.enviadoPor ? ` por ${esc(a.enviadoPor)}` : ''}</small>
          <div class="linha-botoes">
            <a class="botao sec mini" href="${urlArquivo(e, a)}" download="${esc(a.nome)}">Baixar</a>
            ${modo === 'editar' ? `<button type="button" class="mini perigo" data-remover="${a.id}">Remover</button>` : ''}
          </div></div>`).join('');
      }
      const podeEnviar = podeEditar() && modo !== 'exibir';
      return `<div class="emp-arquivo">
        <b>${esc(def.nome)}</b>
        ${itens || '<small>Nenhum arquivo.</small>'}
        ${podeEnviar ? botaoArquivo(def, temAlgum, modo === 'novo' ? ['Escolher arquivo', 'Trocar'] : ['Enviar', 'Substituir']) : ''}
        </div>`;
    }).join('');
  }

  /** Mostra uma empresa (exibir/editar) ou o formulário em branco de nova empresa. */
  function preencher(e, m) {
    modo = e && e.id ? (m === 'editar' && podeEditar() ? 'editar' : 'exibir') : 'novo';
    pendentes = [];
    form.reset();
    const f = form.elements;
    for (const k of ['id', 'razao', 'cnpj', 'fantasia', 'regime', 'endereco', 'telefone', 'cidade', 'uf', 'cep']) f[k].value = (e && e[k]) || '';
    $('#titulo-form-empresa').textContent = modo === 'novo' ? 'Nova empresa' : `${modo === 'editar' ? 'Editar empresa' : 'Empresa'} — ${e.razao}`;
    const leitura = !podeEditar() || modo === 'exibir';
    form.querySelectorAll('input:not([type=file]), select').forEach((el) => { el.disabled = leitura; });
    $('#emp-voltar').hidden = modo === 'novo';
    $('#emp-salvar').hidden = leitura;
    $('#emp-editar').hidden = modo !== 'exibir' || !podeEditar();
    $('#emp-cancelar').textContent = modo === 'novo' ? 'Limpar' : 'Voltar';
    renderArquivos(e);
  }

  const atual = () => empresas.find((x) => x.id === form.elements.id.value);
  const voltar = () => { preencher(null); form.scrollIntoView({ block: 'start' }); };
  $('#emp-voltar').addEventListener('click', voltar);
  $('#emp-cancelar').addEventListener('click', voltar);
  $('#emp-editar').addEventListener('click', () => preencher(atual(), 'editar'));
  form.elements.cnpj.addEventListener('input', (ev) => { ev.target.value = C.formatarCNPJ(ev.target.value); });
  form.elements.cep.addEventListener('input', (ev) => { ev.target.value = C.formatarCEP(ev.target.value); });

  const lerBase64 = (arquivo) => new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result).replace(/^data:[^,]*,/, ''));
    r.onerror = () => reject(new Error('Não foi possível ler o arquivo.'));
    r.readAsDataURL(arquivo);
  });

  /** Envia os arquivos um a um; devolve a empresa atualizada e as mensagens de erro. */
  async function enviar(id, itens) {
    let salvo = null;
    const erros = [];
    for (const a of itens) {
      try {
        salvo = await api.post(`/api/empresas/${id}/arquivos/${a.tipo}`, { nome: a.nome, conteudo: a.conteudo });
      } catch (e) {
        if (e.status === 401) throw e;
        erros.push(`${a.nome}: ${e.message}`);
      }
    }
    return { salvo, erros };
  }

  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    if (!podeEditar() || modo === 'exibir') return;
    const f = form.elements;
    const dados = {};
    for (const k of ['razao', 'cnpj', 'fantasia', 'regime', 'endereco', 'telefone', 'cidade', 'uf', 'cep']) dados[k] = f[k].value.trim();
    const novo = modo === 'novo';
    try {
      let salvo = novo ? await api.post('/api/empresas', dados) : await api.put(`/api/empresas/${f.id.value}`, dados);
      let erros = [];
      if (novo && pendentes.length) {
        const r = await enviar(salvo.id, pendentes);
        salvo = r.salvo || salvo;
        erros = r.erros;
      }
      await carregar();
      preencher(salvo, 'exibir');
      App.avisar(erros.length ? `Empresa salva, mas alguns arquivos não foram enviados:\n${erros.join('\n')}`
        : novo ? 'Empresa cadastrada.' : 'Empresa salva.');
    } catch (e) {
      if (e.status !== 401) App.avisar(e.message);
    }
  });

  $('#lista-empresas').addEventListener('click', async (ev) => {
    const b = ev.target.closest('button[data-acao]');
    if (!b) return;
    const e = empresas.find((x) => x.id === b.dataset.id);
    if (!e) return;
    if (b.dataset.acao !== 'excluir') { preencher(e, b.dataset.acao); form.scrollIntoView({ block: 'start' }); return; }
    if (!(await App.confirmar(`Excluir a empresa ${e.razao} e os arquivos anexados a ela?`))) return;
    try {
      await api.del(`/api/empresas/${e.id}`);
      if (form.elements.id.value === e.id) preencher(null);
      await carregar();
    } catch (err) {
      if (err.status !== 401) App.avisar(err.message);
    }
  });

  $('#emp-lista-arquivos').addEventListener('change', async (ev) => {
    const input = ev.target.closest('input[type=file][data-tipo]');
    if (!input || !input.files.length) return;
    const def = ARQUIVOS.find((a) => a.tipo === input.dataset.tipo);
    const extensoes = def.aceita.split(',');
    const itens = [];
    for (const arquivo of input.files) {
      if (arquivo.size > MAX) { App.avisar(`${arquivo.name}: o arquivo deve ter no máximo 10 MB.`); return; }
      if (!extensoes.some((x) => arquivo.name.toLowerCase().endsWith(x))) {
        App.avisar(`${arquivo.name}: envie um arquivo ${extensoes.join(', ')}.`);
        return;
      }
      try {
        itens.push({ chave: String(++seq), tipo: def.tipo, nome: arquivo.name, tamanho: arquivo.size, conteudo: await lerBase64(arquivo) });
      } catch (e) {
        App.avisar(e.message);
        return;
      }
    }
    if (modo === 'novo') {
      if (def.tipo === 'logo') pendentes = pendentes.filter((x) => x.tipo !== 'logo');
      pendentes.push(...itens);
      renderArquivos(null);
      return;
    }
    try {
      const { salvo, erros } = await enviar(form.elements.id.value, itens);
      await carregar();
      if (salvo) preencher(salvo, 'editar');
      if (erros.length) App.avisar(erros.join('\n'));
    } catch (e) {
      if (e.status !== 401) App.avisar(e.message);
    }
  });

  $('#emp-lista-arquivos').addEventListener('click', async (ev) => {
    const retirar = ev.target.closest('button[data-retirar]');
    if (retirar) {
      pendentes = pendentes.filter((x) => x.chave !== retirar.dataset.retirar);
      renderArquivos(null);
      return;
    }
    const b = ev.target.closest('button[data-remover]');
    if (!b) return;
    const e = atual();
    const a = e && (e.arquivos || []).find((x) => x.id === b.dataset.remover);
    if (!a || !(await App.confirmar(`Remover o arquivo "${a.nome}"?`))) return;
    try {
      const salvo = await api.del(`/api/empresas/${e.id}/arquivos/${a.id}`);
      await carregar();
      preencher(salvo, 'editar');
    } catch (err) {
      if (err.status !== 401) App.avisar(err.message);
    }
  });

  window.addEventListener('app-iniciado', (ev) => { usuario = ev.detail; preencher(null); carregar(); });
  window.addEventListener('app-encerrado', () => { usuario = null; empresas = []; renderLista(); });
  document.querySelector('.aba[data-aba=empresas]').addEventListener('click', () => { if (usuario) carregar(); });
})();
