/*
 * Preenche um modelo Word (.docx) da empresa com os dados do representante.
 * O modelo usa marcadores entre chaves, como {razão social} ou {CNPJ}
 * (maiúsculas, minúsculas e acentos tanto faz). O Word costuma quebrar o texto
 * em vários trechos ao editar; o marcador é reconhecido mesmo assim, desde que
 * fique dentro de um mesmo parágrafo.
 *
 * Funciona no navegador (window.EscalaModeloPreenchido) e no Node.
 */
(function (root, factory) {
  const req = (nome, global) => root[global] || (typeof require === 'function' ? require(nome) : null);
  const api = factory(req('./contrato-modelo.js', 'EscalaContrato'), req('./contrato-docx.js', 'EscalaContratoDocx'),
    req('./planilha.js', 'EscalaPlanilha'));
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.EscalaModeloPreenchido = api;
})(typeof self !== 'undefined' ? self : this, function (C, DOCX, P) {
  'use strict';

  const t = (v) => String(v == null ? '' : v).trim();
  const ESTADOS = { RS: 'Rio Grande do Sul', SC: 'Santa Catarina', SP: 'São Paulo' };

  /** Marcadores aceitos: [marcador, descrição, valor(d = representante, e = empresa representada)]. */
  const MARCADORES = [
    ['razão social', 'Razão social do representante', (d) => t(d.razao).toUpperCase()],
    ['CNPJ', 'CNPJ do representante', (d) => (t(d.cnpj) ? C.formatarCNPJ(d.cnpj) : '')],
    ['nome fantasia', 'Nome fantasia do representante', (d) => t(d.fantasia).toUpperCase()],
    ['código', 'Código do representante', (d) => t(d.codigo)],
    ['endereço', 'Rua, número e complemento', (d) => t(d.endereco)],
    ['bairro', 'Bairro', (d) => t(d.bairro)],
    ['cidade', 'Cidade', (d) => t(d.cidade)],
    ['UF', 'UF', (d) => t(d.uf).toUpperCase()],
    ['CEP', 'CEP', (d) => (t(d.cep) ? C.formatarCEP(d.cep) : '')],
    ['endereço completo', 'Endereço com bairro, cidade, UF e CEP', (d) => C.valores(d).endEmpresa],
    ['responsável', 'Nome completo do responsável legal', (d) => t(d.responsavel).toUpperCase()],
    ['nacionalidade', 'Nacionalidade do responsável', (d) => t(d.nacionalidade).toLowerCase()],
    ['data de nascimento', 'Data de nascimento (dd/mm/aaaa)', (d) => C.dataBR(d.nascimento)],
    ['RG', 'RG com órgão emissor', (d) => C.valores(d).rg],
    ['CPF', 'CPF do responsável', (d) => (t(d.cpf) ? C.formatarCPF(d.cpf) : '')],
    ['endereço residencial', 'Endereço residencial completo do responsável', (d) => C.valores(d).endResidencial],
    ['estado de atuação', 'Estado de atuação (por extenso)', (d) => C.listaEstados(d.estados).map((u) => ESTADOS[u] || u).join(', ')],
    ['zona de influência', 'Zona de influência/clientes (Anexo I)', (d) => t(d.zona)],
    ['data do contrato', 'Data do contrato (dd/mm/aaaa)', (d) => C.dataBR(d.dataContrato)],
    ['data do contrato por extenso', 'Ex.: 21 de outubro de 2026', (d) => C.dataExtenso(d.dataContrato)],
    ['empresa razão social', 'Razão social da empresa representada', (d, e) => t(e.razao)],
    ['empresa CNPJ', 'CNPJ da empresa representada', (d, e) => t(e.cnpj)],
    ['empresa nome fantasia', 'Nome fantasia da empresa representada', (d, e) => t(e.fantasia)],
    ['empresa endereço', 'Endereço da empresa representada', (d, e) => t(e.endereco)],
    ['empresa cidade', 'Cidade da empresa representada', (d, e) => t(e.cidade)],
    ['empresa UF', 'UF da empresa representada', (d, e) => t(e.uf)],
    ['empresa CEP', 'CEP da empresa representada', (d, e) => t(e.cep)],
  ];

  const chave = (s) => String(s).normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/\s+/g, ' ').trim();
  const PELA_CHAVE = new Map(MARCADORES.map((m) => [chave(m[0]), m]));
  const EM_BRANCO = '__________';

  const desfazer = (s) => s.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&apos;/g, "'")
    .replace(/&#(\d+);/g, (_, n) => String.fromCharCode(Number(n)))
    .replace(/&#x([0-9a-f]+);/gi, (_, n) => String.fromCharCode(parseInt(n, 16))).replace(/&amp;/g, '&');
  const escapar = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

  /**
   * Troca os marcadores de uma parte XML do Word.
   * @returns {{ xml, usados: string[], desconhecidos: string[], vazios: string[] }}
   */
  function preencherXml(xml, d, e) {
    // trechos de texto (<w:t>) em ordem, com o parágrafo a que pertencem
    const nos = [];
    const re = /<w:t(\s[^>]*)?>([^<]*)<\/w:t>|<w:t(\s[^>]*)?\/>|<\/w:p>/g;
    let paragrafo = 0;
    let m;
    while ((m = re.exec(xml))) {
      if (m[0] === '</w:p>') { paragrafo++; continue; }
      nos.push({ ini: m.index, fim: m.index + m[0].length, texto: desfazer(m[2] || ''), paragrafo });
    }
    let todo = '';
    for (const n of nos) { n.pos = todo.length; todo += n.texto; }
    const noDe = (pos) => {
      let i = 0;
      while (i < nos.length - 1 && nos[i + 1].pos <= pos) i++;
      return i;
    };
    const usados = new Set();
    const desconhecidos = new Set();
    const vazios = new Set();
    const trocas = [];
    const reMarcador = /\{([^{}]{1,60})\}/g;
    while ((m = reMarcador.exec(todo))) {
      const def = PELA_CHAVE.get(chave(m[1]));
      if (!def) { desconhecidos.add(m[0]); continue; }
      const a = noDe(m.index);
      const b = noDe(m.index + m[0].length - 1);
      if (nos[a].paragrafo !== nos[b].paragrafo) continue;
      const valor = t(def[2](d || {}, e || {}));
      usados.add(def[0]);
      if (!valor) vazios.add(def[0]);
      trocas.push({ a, b, ia: m.index - nos[a].pos, fb: m.index + m[0].length - nos[b].pos, valor: valor || EM_BRANCO });
    }
    // aplicadas do fim para o começo: as posições anteriores continuam valendo
    for (const x of trocas.reverse()) {
      if (x.a === x.b) {
        const n = nos[x.a];
        n.texto = n.texto.slice(0, x.ia) + x.valor + n.texto.slice(x.fb);
      } else {
        nos[x.a].texto = nos[x.a].texto.slice(0, x.ia) + x.valor;
        for (let i = x.a + 1; i < x.b; i++) nos[i].texto = '';
        nos[x.b].texto = nos[x.b].texto.slice(x.fb);
      }
      for (let i = x.a; i <= x.b; i++) nos[i].mudou = true;
    }
    let out = '';
    let ult = 0;
    for (const n of nos) {
      if (!n.mudou) continue;
      out += xml.slice(ult, n.ini) + `<w:t xml:space="preserve">${escapar(n.texto)}</w:t>`;
      ult = n.fim;
    }
    out += xml.slice(ult);
    return { xml: out, usados: [...usados], desconhecidos: [...desconhecidos], vazios: [...vazios] };
  }

  const PARTES = /^word\/(document|header\d*|footer\d*|footnotes|endnotes)\.xml$/;

  /**
   * Preenche o modelo .docx.
   * @param bytes  conteúdo do modelo (Uint8Array)
   * @param d      dados do representante (cadastro do contrato)
   * @param e      empresa representada (cadastro de empresas)
   * @returns {Promise<{ bytes: Uint8Array, usados, desconhecidos, vazios }>}
   */
  async function preencher(bytes, d, e) {
    let zip;
    try {
      zip = await P.lerZip(bytes);
    } catch (err) {
      throw new Error('O modelo não é um arquivo Word (.docx) válido.');
    }
    if (!zip.nomes.includes('word/document.xml')) throw new Error('O modelo não é um arquivo Word (.docx) válido.');
    const usados = new Set();
    const desconhecidos = new Set();
    const vazios = new Set();
    const arquivos = [];
    for (const nome of zip.nomes) {
      if (nome.endsWith('/')) continue;
      if (PARTES.test(nome)) {
        const r = preencherXml(await zip.texto(nome), d, e);
        r.usados.forEach((x) => usados.add(x));
        r.desconhecidos.forEach((x) => desconhecidos.add(x));
        r.vazios.forEach((x) => vazios.add(x));
        arquivos.push({ nome, dados: r.xml });
      } else {
        arquivos.push({ nome, dados: await zip.bytes(nome) });
      }
    }
    return { bytes: DOCX.zip(arquivos), usados: [...usados], desconhecidos: [...desconhecidos], vazios: [...vazios] };
  }

  return { MARCADORES, preencher, preencherXml };
});
