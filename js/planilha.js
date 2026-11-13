/*
 * Leitura de planilhas sem dependências: Excel 97-2003 (.xls, BIFF8), Excel
 * (.xlsx) e texto (.csv/.txt). Devolve a primeira aba como lista de linhas,
 * cada uma com os valores das células (texto, número ou null).
 *
 * Funciona no navegador (window.EscalaPlanilha) e no Node.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.EscalaPlanilha = api;
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  // ------------------------------------------------ contêiner OLE2 (CFB)

  const ASSINATURA_CFB = [0xd0, 0xcf, 0x11, 0xe0, 0xa1, 0xb1, 0x1a, 0xe1];
  const FIM_CADEIA = 0xfffffffe;

  /** Extrai um fluxo (stream) do arquivo composto do Office pelo nome. */
  function fluxoCFB(bytes, nomes) {
    const dv = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    const tamSetor = 1 << dv.getUint16(0x1e, true);
    const tamMini = 1 << dv.getUint16(0x20, true);
    const setor = (n) => 512 + n * tamSetor;
    // DIFAT: 109 entradas no cabeçalho + setores adicionais
    const difat = [];
    for (let i = 0; i < 109; i++) difat.push(dv.getUint32(0x4c + i * 4, true));
    let proximo = dv.getUint32(0x44, true);
    for (let n = dv.getUint32(0x48, true); n > 0 && proximo < FIM_CADEIA; n--) {
      const base = setor(proximo);
      for (let i = 0; i < tamSetor / 4 - 1; i++) difat.push(dv.getUint32(base + i * 4, true));
      proximo = dv.getUint32(base + tamSetor - 4, true);
    }
    const fat = [];
    for (const s of difat.slice(0, dv.getUint32(0x2c, true))) {
      const base = setor(s);
      for (let i = 0; i < tamSetor / 4; i++) fat.push(dv.getUint32(base + i * 4, true));
    }
    const cadeia = (inicio, tabela) => {
      const out = [];
      for (let s = inicio; s < FIM_CADEIA && out.length <= tabela.length; s = tabela[s]) out.push(s);
      return out;
    };
    const lerCadeia = (inicio) => {
      const partes = cadeia(inicio, fat);
      const out = new Uint8Array(partes.length * tamSetor);
      partes.forEach((s, i) => out.set(bytes.subarray(setor(s), setor(s) + tamSetor), i * tamSetor));
      return out;
    };
    const dir = lerCadeia(dv.getUint32(0x30, true));
    const ddv = new DataView(dir.buffer);
    const entradas = [];
    for (let o = 0; o + 128 <= dir.length; o += 128) {
      const len = ddv.getUint16(o + 0x40, true);
      let nome = '';
      for (let i = 0; i < len / 2 - 1; i++) nome += String.fromCharCode(ddv.getUint16(o + i * 2, true));
      entradas.push({ nome, tipo: dir[o + 0x42], inicio: ddv.getUint32(o + 0x74, true), tamanho: ddv.getUint32(o + 0x78, true) });
    }
    const alvo = entradas.find((e) => e.tipo === 2 && nomes.includes(e.nome));
    if (!alvo) throw new Error('A planilha não tem dados do Excel.');
    const corte = dv.getUint32(0x38, true);
    if (alvo.tamanho >= corte) return lerCadeia(alvo.inicio).subarray(0, alvo.tamanho);
    // fluxos pequenos ficam no "mini stream" da entrada raiz
    const raiz = entradas[0];
    const miniStream = lerCadeia(raiz.inicio);
    const minifat = [];
    const mf = lerCadeia(dv.getUint32(0x3c, true));
    const mdv = new DataView(mf.buffer);
    for (let i = 0; i < mf.length / 4; i++) minifat.push(mdv.getUint32(i * 4, true));
    const partes = cadeia(alvo.inicio, minifat);
    const out = new Uint8Array(partes.length * tamMini);
    partes.forEach((s, i) => out.set(miniStream.subarray(s * tamMini, (s + 1) * tamMini), i * tamMini));
    return out.subarray(0, alvo.tamanho);
  }

  // ----------------------------------------------------- Excel 97 (BIFF8)

  const latin1 = (b, ini, fim) => { let s = ''; for (let i = ini; i < fim; i++) s += String.fromCharCode(b[i]); return s; };
  const utf16 = (b, ini, fim) => { let s = ''; for (let i = ini; i + 1 < fim; i += 2) s += String.fromCharCode(b[i] | (b[i + 1] << 8)); return s; };

  /** Número RK: inteiro de 30 bits ou os 30 bits altos de um double, opcionalmente ÷ 100. */
  function rk(v) {
    let n;
    if (v & 2) n = v >> 2;
    else {
      const buf = new DataView(new ArrayBuffer(8));
      buf.setUint32(4, v & 0xfffffffc, true);
      n = buf.getFloat64(0, true);
    }
    return v & 1 ? n / 100 : n;
  }

  /** Tabela de textos compartilhados (SST), que pode continuar em registros CONTINUE. */
  function lerSST(segmentos) {
    let seg = 0;
    let pos = 8; // total de textos (4) + únicos (4)
    const out = [];
    const total = new DataView(segmentos[0].buffer, segmentos[0].byteOffset).getUint32(4, true);
    const byte = () => {
      if (pos >= segmentos[seg].length) { seg++; pos = 0; }
      return segmentos[seg][pos++];
    };
    const u16 = () => byte() | (byte() << 8);
    const u32 = () => (u16() | (u16() << 16)) >>> 0;
    const pular = (n) => { for (let i = 0; i < n; i++) byte(); };
    for (let k = 0; k < total && seg < segmentos.length; k++) {
      const cch = u16();
      let flags = byte();
      const runs = flags & 0x08 ? u16() : 0;
      const ext = flags & 0x04 ? u32() : 0;
      let s = '';
      for (let i = 0; i < cch; i++) {
        // ao cruzar um CONTINUE, o primeiro byte informa se os caracteres são de 1 ou 2 bytes
        if (pos >= segmentos[seg].length) { seg++; pos = 0; flags = byte(); }
        s += String.fromCharCode(flags & 1 ? u16() : byte());
      }
      pular(runs * 4 + ext);
      out.push(s);
    }
    return out;
  }

  function lerXLS(bytes) {
    const wb = fluxoCFB(bytes, ['Workbook', 'Book']);
    const dv = new DataView(wb.buffer, wb.byteOffset, wb.byteLength);
    let sst = [];
    let abas = [];
    // 1ª passada: textos compartilhados e posição das abas
    for (let o = 0; o + 4 <= wb.length;) {
      const tipo = dv.getUint16(o, true);
      const len = dv.getUint16(o + 2, true);
      const ini = o + 4;
      if (tipo === 0x0085) abas.push({ pos: dv.getUint32(ini, true), visivel: wb[ini + 4] === 0, tipo: wb[ini + 5] });
      if (tipo === 0x00fc) {
        const segmentos = [wb.subarray(ini, ini + len)];
        let p = ini + len;
        while (p + 4 <= wb.length && dv.getUint16(p, true) === 0x003c) {
          const l = dv.getUint16(p + 2, true);
          segmentos.push(wb.subarray(p + 4, p + 4 + l));
          p += 4 + l;
        }
        sst = lerSST(segmentos);
      }
      o = ini + len;
    }
    abas = abas.filter((a) => a.tipo === 0);
    const aba = abas.find((a) => a.visivel) || abas[0];
    if (!aba) throw new Error('A planilha não tem abas de dados.');
    const linhas = [];
    const por = (r, c, v) => { (linhas[r] = linhas[r] || [])[c] = v; };
    let formulaPendente = null;
    for (let o = aba.pos; o + 4 <= wb.length;) {
      const tipo = dv.getUint16(o, true);
      const len = dv.getUint16(o + 2, true);
      const i = o + 4;
      o = i + len;
      if (tipo === 0x000a) break; // EOF da aba
      if (len < 6 && tipo !== 0x0207) continue;
      const r = len >= 4 ? dv.getUint16(i, true) : 0;
      const c = len >= 4 ? dv.getUint16(i + 2, true) : 0;
      if (tipo === 0x00fd) por(r, c, sst[dv.getUint32(i + 6, true)]);
      else if (tipo === 0x0203) por(r, c, dv.getFloat64(i + 6, true));
      else if (tipo === 0x027e) por(r, c, rk(dv.getInt32(i + 6, true)));
      else if (tipo === 0x00bd) {
        const ultima = dv.getUint16(i + len - 2, true);
        for (let k = c; k <= ultima; k++) por(r, k, rk(dv.getInt32(i + 4 + (k - c) * 6 + 2, true)));
      } else if (tipo === 0x0204 || tipo === 0x00d6) {
        const cch = dv.getUint16(i + 6, true);
        por(r, c, wb[i + 8] & 1 ? utf16(wb, i + 9, i + 9 + cch * 2) : latin1(wb, i + 9, i + 9 + cch));
      } else if (tipo === 0x0006) {
        if (dv.getUint16(i + 12, true) === 0xffff) {
          const t = wb[i + 6];
          if (t === 0) formulaPendente = [r, c];
          else if (t === 1) por(r, c, wb[i + 8] ? 1 : 0);
        } else por(r, c, dv.getFloat64(i + 6, true));
      } else if (tipo === 0x0207 && formulaPendente) {
        const cch = dv.getUint16(i, true);
        por(formulaPendente[0], formulaPendente[1], wb[i + 2] & 1 ? utf16(wb, i + 3, i + 3 + cch * 2) : latin1(wb, i + 3, i + 3 + cch));
        formulaPendente = null;
      }
    }
    return normalizar(linhas);
  }

  // ------------------------------------------------------------ Excel (.xlsx)

  async function inflar(bytes) {
    const ds = new DecompressionStream('deflate-raw');
    const fluxo = new Blob([bytes]).stream().pipeThrough(ds);
    return new Uint8Array(await new Response(fluxo).arrayBuffer());
  }

  /** Arquivos do ZIP pelo diretório central. */
  async function lerZip(bytes) {
    const dv = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    let fim = bytes.length - 22;
    while (fim >= 0 && dv.getUint32(fim, true) !== 0x06054b50) fim--;
    if (fim < 0) throw new Error('Arquivo compactado inválido (.xlsx/.docx).');
    const n = dv.getUint16(fim + 10, true);
    let p = dv.getUint32(fim + 16, true);
    const arquivos = {};
    const dec = new TextDecoder();
    for (let k = 0; k < n; k++) {
      const metodo = dv.getUint16(p + 10, true);
      const tam = dv.getUint32(p + 20, true);
      const lnome = dv.getUint16(p + 28, true);
      const lextra = dv.getUint16(p + 30, true);
      const lcom = dv.getUint16(p + 32, true);
      const local = dv.getUint32(p + 42, true);
      const nome = dec.decode(bytes.subarray(p + 46, p + 46 + lnome));
      const ini = local + 30 + dv.getUint16(local + 26, true) + dv.getUint16(local + 28, true);
      arquivos[nome] = { metodo, dados: bytes.subarray(ini, ini + tam) };
      p += 46 + lnome + lextra + lcom;
    }
    return {
      async texto(nome) {
        const a = arquivos[nome];
        if (!a) return null;
        return dec.decode(a.metodo === 8 ? await inflar(a.dados) : a.dados);
      },
      async bytes(nome) {
        const a = arquivos[nome];
        if (!a) return null;
        return a.metodo === 8 ? inflar(a.dados) : a.dados;
      },
      nomes: Object.keys(arquivos),
    };
  }

  const xmlTexto = (s) => s.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&apos;/g, "'")
    .replace(/&#(\d+);/g, (_, n) => String.fromCharCode(Number(n))).replace(/&amp;/g, '&');

  async function lerXLSX(bytes) {
    const zip = await lerZip(bytes);
    const compartilhados = [];
    const sst = await zip.texto('xl/sharedStrings.xml');
    if (sst) {
      for (const m of sst.matchAll(/<si>([\s\S]*?)<\/si>/g)) {
        compartilhados.push(xmlTexto([...m[1].matchAll(/<t[^>]*>([\s\S]*?)<\/t>/g)].map((t) => t[1]).join('')));
      }
    }
    const nomeAba = zip.nomes.filter((n) => /^xl\/worksheets\/sheet\d+\.xml$/.test(n)).sort()[0];
    const xml = nomeAba && await zip.texto(nomeAba);
    if (!xml) throw new Error('A planilha não tem abas de dados.');
    const linhas = [];
    const coluna = (ref) => [...ref.replace(/\d+/g, '')].reduce((t, ch) => t * 26 + ch.charCodeAt(0) - 64, 0) - 1;
    for (const m of xml.matchAll(/<c ([^>]*?)(?:\/>|>([\s\S]*?)<\/c>)/g)) {
      const attr = m[1];
      const ref = (/r="([A-Z]+\d+)"/.exec(attr) || [])[1];
      if (!ref) continue;
      const tipo = (/t="(\w+)"/.exec(attr) || [])[1];
      const corpo = m[2] || '';
      const v = (/<v>([\s\S]*?)<\/v>/.exec(corpo) || [])[1];
      let valor = null;
      if (tipo === 's') valor = compartilhados[Number(v)];
      else if (tipo === 'inlineStr') valor = xmlTexto([...corpo.matchAll(/<t[^>]*>([\s\S]*?)<\/t>/g)].map((t) => t[1]).join(''));
      else if (tipo === 'str' || tipo === 'e') valor = v == null ? null : xmlTexto(v);
      else if (v != null) valor = Number(v);
      const r = Number(ref.replace(/[A-Z]+/, '')) - 1;
      (linhas[r] = linhas[r] || [])[coluna(ref)] = valor;
    }
    return normalizar(linhas);
  }

  // ---------------------------------------------------------------- texto

  function lerCSV(texto) {
    const linhas = String(texto || '').replace(/^﻿/, '').split(/\r?\n/);
    const primeira = linhas.find((l) => l.trim()) || '';
    const sep = primeira.includes('\t') ? '\t' : primeira.includes(';') ? ';' : ',';
    return normalizar(linhas.map((linha) => {
      const out = [];
      let atual = '';
      let aspas = false;
      for (let i = 0; i < linha.length; i++) {
        const ch = linha[i];
        if (aspas) {
          if (ch === '"' && linha[i + 1] === '"') { atual += '"'; i++; } else if (ch === '"') aspas = false; else atual += ch;
        } else if (ch === '"') aspas = true;
        else if (ch === sep) { out.push(atual); atual = ''; } else atual += ch;
      }
      out.push(atual);
      return out;
    }));
  }

  /** Linhas densas, textos aparados e células vazias como null. */
  function normalizar(linhas) {
    const out = [];
    for (let r = 0; r < linhas.length; r++) {
      const l = linhas[r] || [];
      const linha = [];
      for (let c = 0; c < l.length; c++) {
        const v = l[c];
        linha.push(v == null ? null : typeof v === 'string' ? (v.trim() === '' ? null : v.trim()) : v);
      }
      out.push(linha);
    }
    return out;
  }

  /** Lê o arquivo (bytes) conforme o conteúdo: .xls, .xlsx ou texto. */
  async function ler(bytes) {
    bytes = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
    if (ASSINATURA_CFB.every((b, i) => bytes[i] === b)) return lerXLS(bytes);
    if (bytes[0] === 0x50 && bytes[1] === 0x4b) return lerXLSX(bytes);
    let texto;
    try {
      texto = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
    } catch (e) {
      texto = new TextDecoder('windows-1252').decode(bytes); // CSV salvo pelo Excel em português
    }
    return lerCSV(texto);
  }

  // --------------------------------------------------------- conversões

  /** Data em dd/mm/aaaa, aaaa-mm-dd ou número de série do Excel -> 'AAAA-MM-DD' ('' se vazia/ inválida). */
  function lerData(v) {
    if (v == null || v === '') return '';
    if (typeof v === 'number') {
      if (v < 1 || v > 80000) return '';
      return new Date(Date.UTC(1899, 11, 30) + Math.floor(v) * 86400000).toISOString().slice(0, 10); // a fração é a hora
    }
    const s = String(v).trim();
    let m = /^(\d{1,2})\/(\d{1,2})\/(\d{4})/.exec(s);
    if (m) return `${m[3]}-${m[2].padStart(2, '0')}-${m[1].padStart(2, '0')}`;
    m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s);
    return m ? `${m[1]}-${m[2]}-${m[3]}` : '';
  }

  /** Texto de célula: números inteiros sem casas decimais (códigos como 0010 vêm como 10). */
  const texto = (v) => (v == null ? '' : typeof v === 'number' ? (Number.isInteger(v) ? String(v) : String(v)) : String(v).trim());

  return { ler, lerXLS, lerXLSX, lerCSV, lerData, texto, lerZip };
});
