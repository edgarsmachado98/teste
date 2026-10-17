/*
 * Renderização compartilhada dos documentos (contratos, distratos, aviso prévio):
 * HTML da prévia/impressão, impressão em PDF e download do Word (.docx).
 * Os documentos vêm como blocos (ver js/contrato-modelo.js e js/distrato-modelo.js).
 */
(function () {
  'use strict';

  const C = window.EscalaContrato;
  const DOCX = window.EscalaContratoDocx;
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (ch) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));

  // tamanho em pixels dos logotipos (para manter a proporção no Word)
  const LOGOS = {
    moinho: { arquivo: 'img/logo-moinho.png', largura: 261, altura: 111 },
    antoniazzi: { arquivo: 'img/logo-antoniazzi.png', largura: 286, altura: 244 },
  };

  function inline(texto, vals, editavel) {
    return C.trechos(texto, vals).map((t) => {
      let h = esc(t.texto).replace(/\n/g, '<br>');
      if (t.campo && editavel) {
        const cls = 'ct-campo' + (t.vazio ? ' vazio' : '');
        h = `<mark class="${cls}" data-campo="${t.campo}" title="Clique para editar">${h}</mark>`;
      }
      if (t.v) h = `<span class="ct-vermelho">${h}</span>`;
      if (t.u) h = `<u>${h}</u>`;
      if (t.i) h = `<em>${h}</em>`;
      if (t.b) h = `<strong>${h}</strong>`;
      return h;
    }).join('');
  }

  function cabecalhoHTML(tipo, vals, editavel) {
    const dados = `<div class="ct-cab-dados">${C.CABECALHO.map((l) => `<div>${inline(l, vals, editavel)}</div>`).join('')}</div>`;
    if (tipo === 'logo') return `<div class="ct-cab"><img src="${LOGOS.moinho.arquivo}" alt="Moinho Santa Maria" class="ct-logo">${dados}</div>`;
    if (tipo === 'logos') {
      return `<div class="ct-cab ct-cab-logos"><div class="ct-logos"><img src="${LOGOS.antoniazzi.arquivo}" alt="Antoniazzi Alimentos">` +
        `<img src="${LOGOS.moinho.arquivo}" alt="Moinho Santa Maria"></div>${dados}</div>`;
    }
    if (tipo === 'antoniazzi') return `<div class="ct-cab ct-cab-centro"><img src="${LOGOS.antoniazzi.arquivo}" alt="Antoniazzi Alimentos" class="ct-logo-ant"></div>`;
    if (tipo === 'dados') return `<div class="ct-cab">${dados}</div>`;
    return '';
  }

  function blocoHTML(b, vals, ed) {
    const [tipo, a1, a2, a3] = b;
    const T = (t) => inline(t, vals, ed);
    const linhaAss = (linhas, cls = '') => `<div class="ct-ass ${cls}"><span class="ct-linha"></span>` +
      linhas.map((l) => `<strong>${T(l)}</strong>`).join('<br>') + '</div>';
    const testemunhas = (modo) => (modo === 'linha'
      ? '<div class="ct-test ct-test-linha">TESTEMUNHAS: <span class="ct-linha"></span><span class="ct-linha"></span></div>'
      : '<p class="ct-test-rotulo">TESTEMUNHAS:</p><div class="ct-test"><span class="ct-linha"></span><span class="ct-linha"></span></div>');
    switch (tipo) {
      case 'titulo': return `<h3 class="ct-titulo${a2 && a2.centro ? ' centro' : ''}">${T(a1)}</h3>`;
      case 'tituloCentro': return `<h3 class="ct-titulo-centro">${T(a1)}</h3>`;
      case 'secao': return `<h4 class="ct-secao">${T(a1)}</h4>`;
      case 'secaoPol': return `<h4 class="ct-secao-pol">${T(a1)}</h4>`;
      case 'clausula': return `<h4 class="ct-clausula">${T(a1)}</h4>`;
      case 'p': return `<p class="ct-p">${T(a1)}</p>`;
      case 'pc': return `<p class="ct-p ct-compacto">${T(a1)}</p>`;
      case 'pp': return `<p class="ct-p ct-recuo">${T(a1)}</p>`;
      case 'pt': return `<p class="ct-p ct-termo">${T(a1)}</p>`;
      case 'n': return `<div class="ct-n"><span class="ct-num">${a3 && a3.semNegrito ? esc(a1) : `<strong>${esc(a1)}</strong>`}</span>` +
        `<p class="ct-p">${T(a2)}</p></div>`;
      case 'item': return `<div class="ct-item"><span>•</span><p class="ct-p">${T(a1)}</p></div>`;
      case 'rotulo': return `<p class="ct-rotulo">${T(a1)}</p>`;
      case 'zona': return `<p class="ct-zona"><strong>${T('⟦zona⟧')}</strong></p>`;
      case 'contato': return `<p class="ct-contato">${T(a1)}</p>`;
      case 'data': return `<p class="ct-data">${esc(a1)}, ${T('⟦data⟧')}.</p>`;
      case 'dataLivre': return `<p class="ct-data${a2 && a2.direita ? ' direita' : ''}${a2 && a2.recuo ? ' recuo' : ''}">${T(a1)}</p>`;
      case 'ass2': return `<div class="ct-assinaturas">${linhaAss(a1.assinatura)}${linhaAss(['⟦razao⟧', 'CNPJ: ⟦cnpj⟧'], 'centro')}</div>` +
        testemunhas(a2);
      case 'ass1': return `<div class="ct-assinaturas um">${linhaAss(['⟦razao⟧', 'CNPJ: ⟦cnpj⟧'], 'centro')}</div>${testemunhas('abaixo')}`;
      case 'assLado': return `<div class="ct-assinaturas">${a1.map((l) => linhaAss(l, 'centro')).join('')}</div>`;
      case 'assPilha': return `<div class="ct-assinaturas um esquerda">${linhaAss(a1)}</div>`;
      case 'testNum': return '<p class="ct-test-rotulo">Testemunhas:</p><div class="ct-test-num">' +
        '<p>1.<span class="ct-linha"></span></p><p>2.<span class="ct-linha"></span></p></div>';
      case 'assPolitica': return '<div class="ct-ass-pol">' + [['ANTONIAZZI & CIA LTDA'],
        ['ANTONIAZZI INDÚSTRIA E COMÉRCIO', 'DE ALIMENTOS LTDA'],
        ['⟦razao⟧', 'CNPJ: ⟦cnpj⟧', 'Representante: ⟦responsavel⟧']].map((l) => linhaAss(l)).join('') + '</div>';
      case 'assTermo': return `<div class="ct-ass-termo">${linhaAss(['REPRESENTANTE COMERCIAL', '⟦razao⟧', 'CNPJ: ⟦cnpj⟧', '__⟦responsavel⟧__'], 'centro')}</div>`;
      case 'versoes': return '<table class="ct-versoes"><thead><tr><th>Data</th><th>Versão</th><th>Descrição</th><th>Autor</th></tr></thead><tbody>' +
        C.VERSOES.map((l) => `<tr>${l.map((x) => `<td>${esc(x)}</td>`).join('')}</tr>`).join('') + '</tbody></table>';
      default: return '';
    }
  }

  /**
   * HTML dos documentos. Cada "folha" (trecho entre quebras de página) é uma tabela
   * cujo <thead> traz o cabeçalho, que o navegador repete em todas as páginas impressas.
   */
  function renderizar(documentos, vals, editavel) {
    return documentos.map((doc) => {
      const folhas = [[]];
      for (const b of doc.blocos) {
        if (b[0] === 'quebra') folhas.push([]);
        else folhas[folhas.length - 1].push(b);
      }
      const cab = cabecalhoHTML(doc.cabecalho, vals, editavel);
      // o logotipo da Antoniazzi aparece só no início do documento; os demais se repetem em cada página
      const soNoInicio = doc.cabecalho === 'antoniazzi';
      return `<section class="ct-doc ct-fonte-${doc.fonte}" data-doc="${doc.id}">` + folhas.map((bs, i) =>
        '<table class="ct-folha">' + (cab && !soNoInicio ? `<thead><tr><td>${cab}</td></tr></thead>` : '') +
        `<tbody><tr><td class="ct-corpo">${soNoInicio && i === 0 ? cab : ''}${bs.map((b) => blocoHTML(b, vals, editavel)).join('')}</td></tr></tbody></table>`).join('') +
        '</section>';
    }).join('');
  }

  /** Abre a impressão só com os documentos (o usuário escolhe "Salvar como PDF"). */
  async function imprimir(documentos, vals, nomeArquivo) {
    const area = document.getElementById('impressao');
    area.innerHTML = renderizar(documentos, vals, false);
    const titulo = document.title;
    document.title = nomeArquivo.replace(/\.pdf$/, '');
    document.body.classList.add('imprimindo');
    // espera os logotipos carregarem antes de abrir a impressão
    await Promise.all([...area.querySelectorAll('img')].map((img) => (img.complete ? null
      : new Promise((r) => { img.onload = r; img.onerror = r; }))));
    const terminar = () => {
      document.body.classList.remove('imprimindo');
      area.innerHTML = '';
      document.title = titulo;
      window.removeEventListener('afterprint', terminar);
    };
    window.addEventListener('afterprint', terminar);
    window.print();
  }

  async function bytesDe(url) {
    const r = await fetch(url);
    if (!r.ok) throw new Error('Não foi possível carregar o logotipo.');
    return new Uint8Array(await r.arrayBuffer());
  }

  /** Gera o .docx e inicia o download. */
  async function baixarWord(documentos, vals, nomeArquivo) {
    const imagens = {};
    for (const [k, l] of Object.entries(LOGOS)) imagens[k] = { bytes: await bytesDe(l.arquivo), largura: l.largura, altura: l.altura };
    const bytes = DOCX.gerar(documentos, vals, imagens);
    const blob = new Blob([bytes], { type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' });
    const url = URL.createObjectURL(blob);
    const a = Object.assign(document.createElement('a'), { href: url, download: nomeArquivo });
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  }

  window.EscalaDocHTML = { renderizar, imprimir, baixarWord, LOGOS };
})();
