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
          <button type="button" class="mini sec" data-acao="editar" data-id="${e.id}">${podeEditar() ? 'Editar' : 'Ver'}</button>
          ${podeEditar() ? `<button type="button" class="mini perigo" data-acao="excluir" data-id="${e.id}">Excluir</button>` : ''}
        </td></tr>`;
    }).join('') || `<tr><td colspan="7" class="vazio">${empresas.length ? 'Nenhuma empresa encontrada.' : 'Nenhuma empresa cadastrada.'}</td></tr>`;
  }
  $('#busca-empresa').addEventListener('input', renderLista);

  // modelos: vários por tipo (ex.: contrato SP e contrato RS/SC); logotipo: um só
  function renderArquivos(e) {
    $('#emp-arquivos-dica').hidden = !!(e && e.id);
    $('#emp-lista-arquivos').innerHTML = e && e.id ? ARQUIVOS.map((def) => {
      const lista = (e.arquivos || []).filter((x) => x.tipo === def.tipo);
      const logo = def.tipo === 'logo';
      const itens = lista.map((a) => `<div class="emp-item">
          ${logo ? `<img src="${urlArquivo(e, a)}" alt="Logotipo">` : ''}
          <small><b>${esc(a.nome)}</b> · ${tamanho(a.tamanho)} · ${esc(quando(a.enviadoEm))}${a.enviadoPor ? ` por ${esc(a.enviadoPor)}` : ''}</small>
          <div class="linha-botoes">
            <a class="botao sec mini" href="${urlArquivo(e, a)}" download="${esc(a.nome)}">Baixar</a>
            ${podeEditar() ? `<button type="button" class="mini perigo" data-remover="${a.id}">Remover</button>` : ''}
          </div></div>`).join('');
      return `<div class="emp-arquivo">
        <b>${esc(def.nome)}</b>
        ${itens || '<small>Nenhum arquivo.</small>'}
        ${podeEditar() ? `<div class="linha-botoes"><label class="botao sec mini">${logo ? (lista.length ? 'Substituir' : 'Enviar') : (lista.length ? 'Adicionar outro' : 'Enviar')}<input type="file" data-tipo="${def.tipo}" accept="${def.aceita}" hidden></label></div>` : ''}
        </div>`;
    }).join('') : '';
  }

  function preencher(e) {
    form.reset();
    const f = form.elements;
    for (const k of ['id', 'razao', 'cnpj', 'fantasia', 'regime', 'endereco', 'telefone', 'cidade', 'uf', 'cep']) f[k].value = (e && e[k]) || '';
    $('#titulo-form-empresa').textContent = e && e.id ? `Empresa — ${e.razao}` : 'Nova empresa';
    form.querySelectorAll('input, select').forEach((el) => { el.disabled = !podeEditar(); });
    renderArquivos(e);
  }

  form.addEventListener('reset', () => setTimeout(() => { if (!form.elements.id.value) renderArquivos(null); }));
  form.elements.cnpj.addEventListener('input', (ev) => { ev.target.value = C.formatarCNPJ(ev.target.value); });
  form.elements.cep.addEventListener('input', (ev) => { ev.target.value = C.formatarCEP(ev.target.value); });

  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    if (!podeEditar()) return;
    const f = form.elements;
    const dados = {};
    for (const k of ['razao', 'cnpj', 'fantasia', 'regime', 'endereco', 'telefone', 'cidade', 'uf', 'cep']) dados[k] = f[k].value.trim();
    try {
      const salvo = f.id.value ? await api.put(`/api/empresas/${f.id.value}`, dados) : await api.post('/api/empresas', dados);
      const novo = !f.id.value;
      await carregar();
      preencher(salvo);
      App.avisar(novo ? 'Empresa cadastrada. Agora você pode anexar os modelos e o logotipo.' : 'Empresa salva.');
    } catch (e) {
      if (e.status !== 401) App.avisar(e.message);
    }
  });

  $('#lista-empresas').addEventListener('click', async (ev) => {
    const b = ev.target.closest('button[data-acao]');
    if (!b) return;
    const e = empresas.find((x) => x.id === b.dataset.id);
    if (!e) return;
    if (b.dataset.acao === 'editar') { preencher(e); form.scrollIntoView({ block: 'start' }); return; }
    if (!(await App.confirmar(`Excluir a empresa ${e.razao} e os arquivos anexados a ela?`))) return;
    try {
      await api.del(`/api/empresas/${e.id}`);
      if (form.elements.id.value === e.id) preencher(null);
      await carregar();
    } catch (err) {
      if (err.status !== 401) App.avisar(err.message);
    }
  });

  const lerBase64 = (arquivo) => new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result).replace(/^data:[^,]*,/, ''));
    r.onerror = () => reject(new Error('Não foi possível ler o arquivo.'));
    r.readAsDataURL(arquivo);
  });

  $('#emp-lista-arquivos').addEventListener('change', async (ev) => {
    const input = ev.target.closest('input[type=file][data-tipo]');
    if (!input || !input.files[0]) return;
    const arquivo = input.files[0];
    const id = form.elements.id.value;
    if (arquivo.size > MAX) { App.avisar('O arquivo deve ter no máximo 10 MB.'); return; }
    try {
      const salvo = await api.post(`/api/empresas/${id}/arquivos/${input.dataset.tipo}`, { nome: arquivo.name, conteudo: await lerBase64(arquivo) });
      await carregar();
      preencher(salvo);
    } catch (e) {
      if (e.status !== 401) App.avisar(e.message);
    }
  });

  $('#emp-lista-arquivos').addEventListener('click', async (ev) => {
    const b = ev.target.closest('button[data-remover]');
    if (!b) return;
    const e = empresas.find((x) => x.id === form.elements.id.value);
    const a = e && (e.arquivos || []).find((x) => x.id === b.dataset.remover);
    if (!a || !(await App.confirmar(`Remover o arquivo "${a.nome}"?`))) return;
    try {
      const salvo = await api.del(`/api/empresas/${e.id}/arquivos/${a.id}`);
      await carregar();
      preencher(salvo);
    } catch (e) {
      if (e.status !== 401) App.avisar(e.message);
    }
  });

  window.addEventListener('app-iniciado', (ev) => { usuario = ev.detail; preencher(null); carregar(); });
  window.addEventListener('app-encerrado', () => { usuario = null; empresas = []; renderLista(); });
  document.querySelector('.aba[data-aba=empresas]').addEventListener('click', () => { if (usuario) carregar(); });
})();
