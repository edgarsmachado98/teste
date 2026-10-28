/*
 * Gera o pacote do contrato em formato Word (.docx), sem bibliotecas externas.
 * Um .docx é um arquivo ZIP com partes XML (Office Open XML).
 *
 * Uso: EscalaContratoDocx.gerar(documentos, valores, imagens) -> Uint8Array
 *   documentos: resultado de EscalaContrato.montar(dados)
 *   valores:    resultado de EscalaContrato.valores(dados)
 *   imagens:    { moinho: { bytes, largura, altura }, antoniazzi: { ... } }  (PNG)
 */
(function (root, factory) {
  const api = factory(root.EscalaContrato || (typeof require === 'function' ? require('./contrato-modelo.js') : null));
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.EscalaContratoDocx = api;
})(typeof self !== 'undefined' ? self : this, function (C) {
  'use strict';

  // ------------------------------------------------------------------- ZIP

  const TABELA_CRC = (() => {
    const t = new Uint32Array(256);
    for (let n = 0; n < 256; n++) {
      let c = n;
      for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
      t[n] = c >>> 0;
    }
    return t;
  })();

  function crc32(bytes) {
    let c = 0xffffffff;
    for (let i = 0; i < bytes.length; i++) c = TABELA_CRC[(c ^ bytes[i]) & 0xff] ^ (c >>> 8);
    return (c ^ 0xffffffff) >>> 0;
  }

  /** ZIP sem compressão (método "store"), suficiente e válido para .docx. */
  function zip(arquivos) {
    const enc = new TextEncoder();
    const partes = [];
    const central = [];
    let pos = 0;
    const DATA_DOS = (0 << 9) | (1 << 5) | 1; // 01/01/1980
    for (const a of arquivos) {
      const nome = enc.encode(a.nome);
      const dados = typeof a.dados === 'string' ? enc.encode(a.dados) : a.dados;
      const crc = crc32(dados);
      const loc = new DataView(new ArrayBuffer(30));
      loc.setUint32(0, 0x04034b50, true);
      loc.setUint16(4, 20, true);
      loc.setUint16(6, 0x0800, true); // nomes em UTF-8
      loc.setUint16(8, 0, true);
      loc.setUint16(10, 0, true);
      loc.setUint16(12, DATA_DOS, true);
      loc.setUint32(14, crc, true);
      loc.setUint32(18, dados.length, true);
      loc.setUint32(22, dados.length, true);
      loc.setUint16(26, nome.length, true);
      loc.setUint16(28, 0, true);
      partes.push(new Uint8Array(loc.buffer), nome, dados);
      const cen = new DataView(new ArrayBuffer(46));
      cen.setUint32(0, 0x02014b50, true);
      cen.setUint16(4, 20, true);
      cen.setUint16(6, 20, true);
      cen.setUint16(8, 0x0800, true);
      cen.setUint16(10, 0, true);
      cen.setUint16(12, 0, true);
      cen.setUint16(14, DATA_DOS, true);
      cen.setUint32(16, crc, true);
      cen.setUint32(20, dados.length, true);
      cen.setUint32(24, dados.length, true);
      cen.setUint16(28, nome.length, true);
      cen.setUint32(42, pos, true);
      central.push(new Uint8Array(cen.buffer), nome);
      pos += 30 + nome.length + dados.length;
    }
    const tamCentral = central.reduce((s, p) => s + p.length, 0);
    const fim = new DataView(new ArrayBuffer(22));
    fim.setUint32(0, 0x06054b50, true);
    fim.setUint16(8, arquivos.length, true);
    fim.setUint16(10, arquivos.length, true);
    fim.setUint32(12, tamCentral, true);
    fim.setUint32(16, pos, true);
    const todas = partes.concat(central, [new Uint8Array(fim.buffer)]);
    const out = new Uint8Array(todas.reduce((s, p) => s + p.length, 0));
    let o = 0;
    for (const p of todas) { out.set(p, o); o += p.length; }
    return out;
  }

  // ------------------------------------------------------------- WordprocessingML

  const NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" ' +
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" ' +
    'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" ' +
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" ' +
    'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"';

  const xml = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

  // tipografia por "fonte" do documento (seguindo o modelo)
  const ESTILO = {
    contrato: { fonte: 'Times New Roman', tam: 24, linha: 276, apos: 160 },
    politica: { fonte: 'Times New Roman', tam: 19, linha: 360, apos: 160 },
    termo: { fonte: 'Calibri', tam: 24, linha: 360, apos: 160 },
    distrato: { fonte: 'Arial', tam: 21, linha: 264, apos: 200 },
  };

  function run(texto, f, est) {
    const props = [`<w:rFonts w:ascii="${f.fonte}" w:hAnsi="${f.fonte}" w:cs="${f.fonte}"/>`];
    if (est.b) props.push('<w:b/><w:bCs/>');
    if (est.i) props.push('<w:i/><w:iCs/>');
    if (est.u) props.push('<w:u w:val="single"/>');
    if (est.v) props.push('<w:color w:val="FF0000"/>');
    else if (est.cor) props.push(`<w:color w:val="${est.cor}"/>`);
    props.push(`<w:sz w:val="${est.tam || f.tam}"/><w:szCs w:val="${est.tam || f.tam}"/>`);
    const linhas = String(texto).split('\n');
    const corpo = linhas.map((l, i) => (i ? '<w:br/>' : '') + `<w:t xml:space="preserve">${xml(l)}</w:t>`).join('');
    return `<w:r><w:rPr>${props.join('')}</w:rPr>${corpo}</w:r>`;
  }

  /** Texto com marcações -> runs. extra: estilos aplicados a tudo (ex.: { b: true }). */
  function runs(texto, vals, f, extra = {}) {
    return C.trechos(texto, vals).map((t) => run(t.texto, f, {
      b: t.b || extra.b, i: t.i || extra.i, u: t.u || extra.u, v: t.v, cor: extra.cor, tam: extra.tam,
    })).join('');
  }

  function par(conteudo, o = {}) {
    const p = [];
    if (o.estilo) p.push(`<w:pStyle w:val="${o.estilo}"/>`);
    if (o.manter) p.push('<w:keepNext/>');
    if (o.quebraAntes) p.push('<w:pageBreakBefore/>');
    p.push(`<w:spacing w:before="${o.antes || 0}" w:after="${o.apos == null ? 0 : o.apos}" w:line="${o.linha || 240}" w:lineRule="auto"/>`);
    if (o.esq || o.pendente || o.primeira || o.dir) {
      p.push(`<w:ind w:left="${o.esq || 0}" w:right="${o.dir || 0}"` +
        (o.pendente ? ` w:hanging="${o.pendente}"` : '') + (o.primeira ? ` w:firstLine="${o.primeira}"` : '') + '/>');
    }
    p.push(`<w:jc w:val="${o.alinhar || 'both'}"/>`);
    if (o.secao) p.push(o.secao);
    return `<w:p><w:pPr>${p.join('')}</w:pPr>${conteudo}</w:p>`;
  }

  /** Tabela sem bordas com colunas de larguras dadas (twips). */
  function tabela(colunas, celulas) {
    const sem = ['top', 'left', 'bottom', 'right', 'insideH', 'insideV'].map((b) => `<w:${b} w:val="nil"/>`).join('');
    const total = colunas.reduce((s, x) => s + x, 0);
    return `<w:tbl><w:tblPr><w:tblW w:w="${total}" w:type="dxa"/><w:tblBorders>${sem}</w:tblBorders>` +
      '<w:tblLayout w:type="fixed"/><w:tblCellMar><w:left w:w="0" w:type="dxa"/><w:right w:w="0" w:type="dxa"/></w:tblCellMar>' +
      `</w:tblPr><w:tblGrid>${colunas.map((w) => `<w:gridCol w:w="${w}"/>`).join('')}</w:tblGrid>` +
      '<w:tr><w:trPr><w:cantSplit/></w:trPr>' +
      celulas.map((cel, i) => `<w:tc><w:tcPr><w:tcW w:w="${colunas[i]}" w:type="dxa"/></w:tcPr>${cel || par('')}</w:tc>`).join('') +
      '</w:tr></w:tbl>';
  }

  // largura útil da página (carta 8,5" com margens 1,48" e 1")
  const LARGURA_UTIL = 12240 - 2126 - 1440;

  function blocosParaXml(doc, vals) {
    const f = ESTILO[doc.fonte] || ESTILO.contrato;
    const out = [];
    let quebra = false;
    const P = (conteudo, o = {}) => {
      out.push(par(conteudo, { linha: f.linha, apos: f.apos, ...o, quebraAntes: quebra || o.quebraAntes }));
      quebra = false;
    };
    const linhaAss = (n) => '_'.repeat(n);
    const assinatura = (linhas, centro) => [
      par(run(linhaAss(30), f, {}), { alinhar: centro ? 'center' : 'left', antes: 600, manter: true }),
      ...linhas.map((l) => par(runs(l, vals, f, { b: true }), { alinhar: centro ? 'center' : 'left', manter: true })),
    ].join('');
    const testemunhas = (modo) => {
      if (modo === 'linha') {
        P(run('TESTEMUNHAS:  ' + linhaAss(26) + '        ' + linhaAss(26), f, {}), { antes: 480, alinhar: 'left' });
      } else {
        P(run('TESTEMUNHAS:', f, {}), { antes: 480, alinhar: 'left', manter: true });
        out.push(tabela([LARGURA_UTIL / 2, LARGURA_UTIL / 2], [
          par(run(linhaAss(26), f, {}), { antes: 480, alinhar: 'left' }),
          par(run(linhaAss(26), f, {}), { antes: 480, alinhar: 'left' }),
        ]));
      }
    };
    for (const b of doc.blocos) {
      const [tipo, a1, a2, a3] = b;
      switch (tipo) {
        case 'quebra': quebra = true; break;
        case 'titulo':
          P(runs(a1, vals, { ...f, fonte: 'Cambria' }, { b: true, i: true, u: !(a2 && a2.centro), tam: 26 }),
            { alinhar: (a2 && a2.centro) ? 'center' : 'left', apos: 360 });
          break;
        case 'tituloCentro':
          P(runs(a1, vals, f, { b: true }), { alinhar: 'center', apos: 360, antes: 240 });
          break;
        case 'secao':
          P(runs(a1, vals, f, { b: true }), { alinhar: 'left', antes: 120, manter: true });
          break;
        case 'clausula':
          P(runs(a1, vals, f, { b: true, u: true }), { alinhar: 'left', antes: 160, apos: 0, manter: true });
          break;
        case 'dataLivre':
          P(runs(a1, vals, f), { alinhar: a2 && a2.direita ? 'right' : 'left', esq: a2 && a2.recuo ? 1700 : 0, antes: 360, apos: 240, manter: true });
          break;
        case 'assLado':
          out.push(tabela([LARGURA_UTIL / 2, LARGURA_UTIL / 2], a1.map((l) => assinatura(l, true))));
          break;
        case 'assPilha':
          out.push(assinatura(a1, false));
          break;
        case 'testNum':
          P(run('Testemunhas:', f, {}), { antes: 480, alinhar: 'left', manter: true });
          P(run('1.' + linhaAss(32), f, {}), { antes: 360, alinhar: 'left', manter: true });
          P(run('2.' + linhaAss(32), f, {}), { antes: 360, alinhar: 'left' });
          break;
        case 'secaoPol':
          P(runs(a1, vals, f, { b: true }), { alinhar: 'left', esq: 360, antes: 240, manter: true });
          break;
        case 'p': P(runs(a1, vals, f)); break;
        case 'pc': P(runs(a1, vals, f), { apos: 40 }); break;
        case 'pp': P(runs(a1, vals, f), { primeira: 709 }); break;
        case 'pt': P(runs(a1, vals, f), { primeira: 284, linha: 360 }); break;
        case 'n': {
          const negrito = !(a3 && a3.semNegrito);
          P(run(a1, f, { b: negrito }) + '<w:r><w:tab/></w:r>' + runs(a2, vals, f), { esq: 567, pendente: 567 });
          break;
        }
        case 'item': P(run('•', f, {}) + '<w:r><w:tab/></w:r>' + runs(a1, vals, f), { esq: 720, pendente: 360 }); break;
        case 'rotulo': P(runs(a1, vals, { ...f, fonte: 'Calibri' }, { b: true, tam: 18 }), { esq: 160, antes: 120 }); break;
        case 'zona': P(runs('⟦zona⟧', vals, f, { b: true }), { alinhar: 'left', antes: 240, apos: 240 }); break;
        case 'contato': P(runs(a1, vals, f), { esq: 4300 }); break;
        case 'data': P(runs(`${a1}, ⟦data⟧.`, vals, f), { alinhar: 'left', antes: 240, manter: true }); break;
        case 'ass2': {
          const rep = ['⟦razao⟧', 'CNPJ: ⟦cnpj⟧'];
          out.push(tabela([LARGURA_UTIL / 2, LARGURA_UTIL / 2], [assinatura(a1.assinatura, false), assinatura(rep, true)]));
          testemunhas(a2);
          break;
        }
        case 'ass1':
          out.push(assinatura(['⟦razao⟧', 'CNPJ: ⟦cnpj⟧'], true));
          testemunhas('abaixo');
          break;
        case 'assPolitica':
          for (const linhas of a1 || [['ANTONIAZZI & CIA LTDA'], ['ANTONIAZZI INDÚSTRIA E COMÉRCIO', 'DE ALIMENTOS LTDA'],
            ['⟦razao⟧', 'CNPJ: ⟦cnpj⟧', 'Representante: ⟦responsavel⟧']]) {
            out.push(par(run(linhaAss(36), f, { b: true }), { esq: 3600, antes: 720 }));
            for (const l of linhas) out.push(par(runs(l, vals, f, { b: true }), { esq: 3600 }));
          }
          break;
        case 'assTermo':
          out.push(par(run(linhaAss(50), f, {}), { alinhar: 'center', antes: 1200 }));
          for (const l of ['REPRESENTANTE COMERCIAL', '⟦razao⟧', 'CNPJ: ⟦cnpj⟧', '__⟦responsavel⟧__']) {
            out.push(par(runs(l, vals, { ...f, fonte: 'Arial' }, { b: true, tam: 16 }), { alinhar: 'center' }));
          }
          break;
        case 'versoes': {
          const bordas = ['top', 'left', 'bottom', 'right', 'insideH', 'insideV']
            .map((x) => `<w:${x} w:val="single" w:sz="4" w:space="0" w:color="000000"/>`).join('');
          const cols = [1300, 800, 4200, 2000];
          const celula = (t, i, neg) => `<w:tc><w:tcPr><w:tcW w:w="${cols[i]}" w:type="dxa"/>` +
            `${neg ? '<w:shd w:val="clear" w:color="auto" w:fill="F2F2F2"/>' : ''}<w:vAlign w:val="center"/></w:tcPr>` +
            par(run(t, f, { b: neg, tam: 16 }), { alinhar: i === 2 ? 'left' : 'center' }) + '</w:tc>';
          const linhas = [['Data', 'Versão', 'Descrição', 'Autor']].concat(a1 || C.VERSOES);
          out.push(`<w:tbl><w:tblPr><w:tblW w:w="${cols.reduce((s, x) => s + x, 0)}" w:type="dxa"/><w:jc w:val="center"/>` +
            `<w:tblBorders>${bordas}</w:tblBorders><w:tblLayout w:type="fixed"/></w:tblPr><w:tblGrid>` +
            cols.map((w) => `<w:gridCol w:w="${w}"/>`).join('') + '</w:tblGrid>' +
            linhas.map((l, k) => `<w:tr>${l.map((t, i) => celula(t, i, k === 0)).join('')}</w:tr>`).join('') + '</w:tbl>');
          out.push(par('', { apos: 240 }));
          break;
        }
        default: break;
      }
    }
    return out.join('');
  }

  // -------------------------------------------------------- imagens e cabeçalho

  const EMU_POR_CM = 360000;
  let idDesenho = 1;

  function imagem(rid, img, larguraCm) {
    const cx = Math.round(larguraCm * EMU_POR_CM);
    const cy = Math.round(cx * img.altura / img.largura);
    const id = idDesenho++;
    return '<w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0">' +
      `<wp:extent cx="${cx}" cy="${cy}"/><wp:docPr id="${id}" name="Logotipo ${id}"/>` +
      '<wp:cNvGraphicFramePr><a:graphicFrameLocks noChangeAspect="1"/></wp:cNvGraphicFramePr>' +
      '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic>' +
      `<pic:nvPicPr><pic:cNvPr id="${id}" name="logo${id}.png"/><pic:cNvPicPr/></pic:nvPicPr>` +
      `<pic:blipFill><a:blip r:embed="${rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>` +
      `<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="${cx}" cy="${cy}"/></a:xfrm>` +
      '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic>' +
      '</wp:inline></w:drawing></w:r>';
  }

  function cabecalhoXml(tipo, vals, imagens) {
    const f = { fonte: 'Arial', tam: 15 };
    const dados = C.CABECALHO.map((l) => par(runs(l, vals, f, { cor: '333333' }), { alinhar: 'left' })).join('');
    let corpo = '';
    if (tipo === 'logo') {
      corpo = tabela([1500, LARGURA_UTIL - 1500], [par(imagem('rIdMoinho', imagens.moinho, 2.2), { alinhar: 'left' }), dados]);
      corpo += par('');
    } else if (tipo === 'logos') {
      corpo = par(imagem('rIdAntoniazzi', imagens.antoniazzi, 2.0) + run('      ', f, {}) +
        imagem('rIdMoinho', imagens.moinho, 2.4), { alinhar: 'center', apos: 240 }) + dados + par('');
    } else if (tipo === 'antoniazzi') {
      corpo = par(imagem('rIdAntoniazzi', imagens.antoniazzi, 2.2), { alinhar: 'center' });
    } else if (tipo === 'dados') {
      corpo = dados + par('');
    } else {
      corpo = par('');
    }
    return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:hdr ${NS}>${corpo}</w:hdr>`;
  }

  const rodapeXml = () => `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:ftr ${NS}>` +
    par('<w:r><w:rPr><w:sz w:val="20"/></w:rPr><w:fldChar w:fldCharType="begin"/></w:r>' +
      '<w:r><w:rPr><w:sz w:val="20"/></w:rPr><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>' +
      '<w:r><w:rPr><w:sz w:val="20"/></w:rPr><w:fldChar w:fldCharType="separate"/></w:r>' +
      '<w:r><w:rPr><w:sz w:val="20"/></w:rPr><w:t>1</w:t></w:r>' +
      '<w:r><w:rPr><w:sz w:val="20"/></w:rPr><w:fldChar w:fldCharType="end"/></w:r>', { alinhar: 'right' }) +
    '</w:ftr>';
  const rodapeVazio = () => `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:ftr ${NS}>${par('')}</w:ftr>`;

  // ------------------------------------------------------------------ pacote

  function gerar(documentos, vals, imagens) {
    idDesenho = 1;
    const tiposCab = ['logo', 'dados', 'nenhum', 'logos', 'antoniazzi'];
    const corpo = [];
    documentos.forEach((doc, i) => {
      const comNumero = doc.fonte === 'contrato' && doc.cabecalho !== 'nenhum';
      const sect = '<w:sectPr>' +
        // logotipo só na primeira página (distrato da Antoniazzi Alimentos, como no modelo)
        (doc.cabecalho === 'antoniazzi'
          ? '<w:headerReference w:type="default" r:id="rIdCab_nenhum"/><w:headerReference w:type="first" r:id="rIdCab_antoniazzi"/>'
          : `<w:headerReference w:type="default" r:id="rIdCab_${doc.cabecalho}"/>`) +
        `<w:footerReference w:type="default" r:id="${comNumero ? 'rIdRodNum' : 'rIdRodVazio'}"/>` +
        (i ? '<w:type w:val="nextPage"/>' : '') +
        '<w:pgSz w:w="12240" w:h="15840"/>' +
        '<w:pgMar w:top="1900" w:right="1440" w:bottom="1300" w:left="2126" w:header="420" w:footer="500" w:gutter="0"/>' +
        '<w:pgNumType w:start="1"/>' + (doc.cabecalho === 'antoniazzi' ? '<w:titlePg/>' : '') + '</w:sectPr>';
      corpo.push(blocosParaXml(doc, vals));
      // as propriedades de seção ficam no último parágrafo da seção (ou no fim do corpo)
      if (i < documentos.length - 1) corpo.push(par('', { secao: sect }));
      else corpo.push(sect);
    });

    const documento = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document ${NS}><w:body>` +
      corpo.join('') + '</w:body></w:document>';

    const estilos = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
      '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">' +
      '<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" ' +
      'w:cs="Times New Roman" w:eastAsia="Times New Roman"/><w:sz w:val="24"/><w:szCs w:val="24"/>' +
      '<w:lang w:val="pt-BR" w:eastAsia="pt-BR" w:bidi="ar-SA"/></w:rPr></w:rPrDefault>' +
      '<w:pPrDefault><w:pPr><w:spacing w:after="0" w:line="240" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>' +
      '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>' +
      '</w:styles>';

    const relsCab = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
      '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
      '<Relationship Id="rIdMoinho" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/logo-moinho.png"/>' +
      '<Relationship Id="rIdAntoniazzi" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/logo-antoniazzi.png"/>' +
      '</Relationships>';

    const relsDoc = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
      '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
      '<Relationship Id="rIdEstilos" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>' +
      tiposCab.map((t) => `<Relationship Id="rIdCab_${t}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="header_${t}.xml"/>`).join('') +
      '<Relationship Id="rIdRodNum" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer_numero.xml"/>' +
      '<Relationship Id="rIdRodVazio" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer_vazio.xml"/>' +
      '</Relationships>';

    const tiposConteudo = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
      '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">' +
      '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>' +
      '<Default Extension="xml" ContentType="application/xml"/>' +
      '<Default Extension="png" ContentType="image/png"/>' +
      '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>' +
      '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>' +
      tiposCab.map((t) => `<Override PartName="/word/header_${t}.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/>`).join('') +
      '<Override PartName="/word/footer_numero.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>' +
      '<Override PartName="/word/footer_vazio.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>' +
      '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>' +
      '</Types>';

    const relsRaiz = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
      '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
      '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>' +
      '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>' +
      '</Relationships>';

    const agora = new Date().toISOString().replace(/\.\d+Z$/, 'Z');
    const core = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
      '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" ' +
      'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" ' +
      'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">' +
      `<dc:title>${xml('Contrato de Representação Comercial - ' + (vals.razao || ''))}</dc:title>` +
      '<dc:creator>CORE RH</dc:creator>' +
      `<dcterms:created xsi:type="dcterms:W3CDTF">${agora}</dcterms:created></cp:coreProperties>`;

    const arquivos = [
      { nome: '[Content_Types].xml', dados: tiposConteudo },
      { nome: '_rels/.rels', dados: relsRaiz },
      { nome: 'docProps/core.xml', dados: core },
      { nome: 'word/document.xml', dados: documento },
      { nome: 'word/styles.xml', dados: estilos },
      { nome: 'word/_rels/document.xml.rels', dados: relsDoc },
      { nome: 'word/footer_numero.xml', dados: rodapeXml() },
      { nome: 'word/footer_vazio.xml', dados: rodapeVazio() },
      { nome: 'word/media/logo-moinho.png', dados: imagens.moinho.bytes },
      { nome: 'word/media/logo-antoniazzi.png', dados: imagens.antoniazzi.bytes },
    ];
    for (const t of tiposCab) {
      arquivos.push({ nome: `word/header_${t}.xml`, dados: cabecalhoXml(t, vals, imagens) });
      arquivos.push({ nome: `word/_rels/header_${t}.xml.rels`, dados: relsCab });
    }
    return zip(arquivos);
  }

  return { gerar, zip, crc32 };
});
