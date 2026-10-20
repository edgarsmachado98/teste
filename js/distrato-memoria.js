/*
 * Memória de cálculo do distrato: comissões mês a mês com a correção pelo IGP-M,
 * comissões a receber e sobre títulos pendentes, indenização (1/12), aviso
 * prévio e total. Sai em HTML (impressão/PDF) e em planilha Excel (.xlsx) com
 * fórmulas, para a conferência de quem recebe o distrato.
 *
 * Funciona no navegador (window.EscalaDistratoMemoria) e no Node.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory(require('./distrato-calculo.js'), require('./contrato-docx.js'));
  } else {
    root.EscalaDistratoMemoria = factory(root.EscalaDistratoCalculo, root.EscalaContratoDocx);
  }
})(typeof self !== 'undefined' ? self : this, function (K, DOCX) {
  'use strict';

  const dataBR = (iso) => (iso ? iso.split('-').reverse().join('/') : '');
  const pct = (v, casas = 2) => `${(Number(v) || 0).toLocaleString('pt-BR', { minimumFractionDigits: casas, maximumFractionDigits: casas })}%`;
  const fator = (v) => (Number(v) || 0).toLocaleString('pt-BR', { minimumFractionDigits: 6, maximumFractionDigits: 6 });
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (ch) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));

  /**
   * Reúne os dados da memória.
   * @param contrato  contrato do representante (razao, cnpj, dataContrato)
   * @param d         dados do distrato (datas, comissões, períodos, opções)
   * @param r         resultado de K.calcular(d, indices)
   * @param indices   variação mensal do IGP-M ('AAAA-MM' -> %)
   * @param empresa   empresa representada ({ nome, cnpj })
   */
  function montar(contrato, d, r, indices, empresa) {
    const aviso = new Set(r.mesesAviso);
    const mesDistrato = K.mesDe(d.dataDistrato);
    const ultimoIndice = K.somarMes(mesDistrato, -1);
    return {
      empresa: empresa || {},
      representante: { razao: contrato.razao, cnpj: contrato.cnpj },
      dataInicio: d.dataInicio, dataDistrato: d.dataDistrato, dataAviso: d.dataAviso || d.dataDistrato,
      ultimoIndice,
      linhas: r.linhas.map((l) => ({
        ...l, rotulo: K.rotuloMes(l.mes), igpmMes: indices && indices[l.mes] != null ? Number(indices[l.mes]) : null,
        // acumulado real do índice; o fator aplicado pode ser 1 quando o acumulado é negativo
        acumulado: (K.fatorIndice(indices || {}, l.mes, mesDistrato, false).fator - 1) * 100,
        aviso: aviso.has(l.mes) && d.pagarAviso !== false,
      })),
      pendentes: { inicio: d.pendentes && d.pendentes.inicio, fim: d.pendentes && d.pendentes.fim, valor: r.pendentes },
      aReceber: { inicio: d.aReceber && d.aReceber.inicio, fim: d.aReceber && d.aReceber.fim, valor: r.aReceber },
      pagarIndenizacao: d.pagarIndenizacao !== false, pagarAviso: d.pagarAviso !== false,
      desconsiderarDeflacao: d.desconsiderarDeflacao !== false,
      r,
    };
  }

  const periodo = (p) => (p.inicio && p.fim ? `${dataBR(p.inicio)} a ${dataBR(p.fim)}` : '—');

  function notas(m) {
    return [
      `Correção pelo IGP-M (FGV) acumulado do mês de cada comissão (inclusive) até ${K.rotuloMes(m.ultimoIndice)}, ` +
        'mês anterior ao do distrato.' + (m.desconsiderarDeflacao ? ' Quando o acumulado é negativo, mantém-se o valor original (fator 1).' : ''),
      'Indenização: 1/12 do total das comissões atualizadas, das comissões a receber e das comissões sobre títulos pendentes ' +
        '(Lei 4.886/1965, art. 27, "j").',
      'Aviso prévio: média das comissões atualizadas dos 3 últimos meses com comissão (Lei 4.886/1965, art. 34).',
      'Os valores são arredondados ao centavo em cada parcela; o total é a soma das parcelas arredondadas.',
    ];
  }

  // ------------------------------------------------------------ HTML (PDF)

  function html(m) {
    const r = m.r;
    const linhas = m.linhas.map((l) => `<tr class="${l.aviso ? 'mc-aviso' : ''}">
        <td>${esc(l.rotulo)}</td><td class="num">${K.moeda(l.valor)}</td>
        <td class="num">${l.igpmMes == null ? '—' : pct(l.igpmMes)}</td><td class="num">${pct(l.acumulado, 4)}</td>
        <td class="num">${fator(l.fator)}${l.acumulado < 0 && l.fator === 1 ? '*' : ''}</td><td class="num">${K.moeda(l.atualizado)}</td><td>${l.aviso ? 'aviso' : ''}</td></tr>`).join('');
    const avisoTxt = m.pagarAviso && r.mesesAviso.length
      ? `(${m.linhas.filter((l) => l.aviso).map((l) => K.moeda(l.atualizado)).join(' + ')}) ÷ 3` : 'não pago';
    return `<div class="mc">
      <header class="mc-cab">
        <h1>Memória de cálculo do distrato</h1>
        <p>Representação comercial — Lei 4.886/1965</p>
      </header>
      <table class="mc-dados"><tbody>
        <tr><th>Representada</th><td>${esc(m.empresa.nome || '')}${m.empresa.cnpj ? ` · CNPJ ${esc(m.empresa.cnpj)}` : ''}</td></tr>
        <tr><th>Representante</th><td>${esc(m.representante.razao)} · CNPJ ${esc(m.representante.cnpj)}</td></tr>
        <tr><th>Início do contrato</th><td>${dataBR(m.dataInicio)}</td></tr>
        <tr><th>Data do distrato</th><td>${dataBR(m.dataDistrato)}</td></tr>
        <tr><th>Data do aviso prévio</th><td>${dataBR(m.dataAviso)}</td></tr>
        <tr><th>Índice</th><td>IGP-M (FGV), série 189 do Banco Central, até ${K.rotuloMes(m.ultimoIndice)}</td></tr>
      </tbody></table>

      <h2>1. Comissões recebidas e correção monetária</h2>
      <table class="mc-tabela">
        <thead><tr><th>Mês</th><th class="num">Comissão (R$)</th><th class="num">IGP-M do mês</th><th class="num">IGP-M acumulado</th>
          <th class="num">Fator</th><th class="num">Atualizada (R$)</th><th></th></tr></thead>
        <tbody>${linhas}
        <tr class="mc-total"><th>Total (${m.linhas.length} meses)</th><th class="num">${K.moeda(r.somaNominal)}</th><th></th><th></th><th></th>
          <th class="num">${K.moeda(r.somaAtualizada)}</th><th></th></tr></tbody>
      </table>

      <h2>2. Comissões a receber e sobre títulos pendentes</h2>
      <table class="mc-tabela">
        <thead><tr><th>Item</th><th>Período</th><th class="num">Valor (R$)</th></tr></thead>
        <tbody>
          <tr><td>Comissões a receber</td><td>${periodo(m.aReceber)}</td><td class="num">${K.moeda(r.aReceber)}</td></tr>
          <tr><td>Comissões sobre títulos pendentes</td><td>${periodo(m.pendentes)}</td><td class="num">${K.moeda(r.pendentes)}</td></tr>
        </tbody>
      </table>

      <h2>3. Cálculo do distrato</h2>
      <table class="mc-tabela mc-resumo">
        <thead><tr><th>Parcela</th><th>Cálculo</th><th class="num">Valor (R$)</th></tr></thead>
        <tbody>
          <tr><td>Base da indenização</td><td>${K.moeda(r.somaAtualizada)} + ${K.moeda(r.aReceber)} + ${K.moeda(r.pendentes)}</td>
            <td class="num">${K.moeda(r.baseIndenizacao)}</td></tr>
          <tr><td>Indenização (1/12) — art. 27, "j"</td><td>${m.pagarIndenizacao ? `${K.moeda(r.baseIndenizacao)} ÷ 12` : 'não paga'}</td>
            <td class="num">${K.moeda(r.indenizacao)}</td></tr>
          <tr><td>Aviso prévio — art. 34</td><td>${avisoTxt}</td><td class="num">${K.moeda(r.avisoPrevio)}</td></tr>
          <tr><td>Comissões a receber</td><td>${periodo(m.aReceber)}</td><td class="num">${K.moeda(r.aReceber)}</td></tr>
          <tr><td>Comissões sobre títulos pendentes</td><td>${periodo(m.pendentes)}</td><td class="num">${K.moeda(r.pendentes)}</td></tr>
          <tr class="mc-total"><th colspan="2">Total a pagar</th><th class="num">${K.moeda(r.total)}</th></tr>
        </tbody>
      </table>
      <p class="mc-extenso">${esc(r.totalExtenso)}</p>
      ${m.linhas.some((l) => l.acumulado < 0 && l.fator === 1) ? '<p class="mc-nota-fator">* IGP-M acumulado negativo: mantido o valor original (fator 1).</p>' : ''}
      ${r.indicesFaltando.length ? `<p class="mc-alerta">Atenção: faltam índices do IGP-M de ${r.indicesFaltando.map(K.rotuloMes).join(', ')}; os fatores podem estar incompletos.</p>` : ''}
      <ol class="mc-notas">${notas(m).map((n) => `<li>${esc(n)}</li>`).join('')}</ol>
    </div>`;
  }

  // ------------------------------------------------------------- Excel (.xlsx)

  const xml = (s) => String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  const colLetra = (i) => String.fromCharCode(65 + i);

  // estilos: 0 normal, 1 negrito, 2 moeda, 3 moeda negrito, 4 fator, 5 percentual, 6 título, 7 cabeçalho de tabela, 8 texto quebrando
  const ESTILOS = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<numFmts count="3"><numFmt numFmtId="164" formatCode="#,##0.00"/><numFmt numFmtId="165" formatCode="0.000000"/><numFmt numFmtId="166" formatCode="0.0000"/></numFmts>
<fonts count="3"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="14"/><name val="Calibri"/></font></fonts>
<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FFE8EAF6"/></patternFill></fill></fills>
<borders count="2"><border/><border><bottom style="thin"><color rgb="FF999999"/></bottom></border></borders>
<cellStyleXfs count="1"><xf/></cellStyleXfs>
<cellXfs count="9">
<xf/>
<xf fontId="1" applyFont="1"/>
<xf numFmtId="164" applyNumberFormat="1"/>
<xf numFmtId="164" fontId="1" applyNumberFormat="1" applyFont="1"/>
<xf numFmtId="165" applyNumberFormat="1"/>
<xf numFmtId="166" applyNumberFormat="1"/>
<xf fontId="2" applyFont="1"/>
<xf fontId="1" fillId="2" borderId="1" applyFont="1" applyFill="1" applyBorder="1"/>
<xf applyAlignment="1"><alignment wrapText="1" vertical="top"/></xf>
</cellXfs>
</styleSheet>`;

  /** Planilha com uma aba; células: { v, f, s } (v = texto ou número; f = fórmula). */
  function planilha(linhas, larguras, mesclas) {
    const corpo = linhas.map((l, i) => {
      if (!l) return '';
      const cels = l.map((c, j) => {
        if (c == null) return '';
        const ref = `${colLetra(j)}${i + 1}`;
        const cel = typeof c === 'object' ? c : { v: c };
        const s = cel.s ? ` s="${cel.s}"` : '';
        if (cel.f) return `<c r="${ref}"${s}><f>${xml(cel.f)}</f>${typeof cel.v === 'number' ? `<v>${cel.v}</v>` : ''}</c>`;
        if (typeof cel.v === 'number') return `<c r="${ref}"${s}><v>${cel.v}</v></c>`;
        if (cel.v == null || cel.v === '') return cel.s ? `<c r="${ref}"${s}/>` : '';
        return `<c r="${ref}"${s} t="inlineStr"><is><t xml:space="preserve">${xml(cel.v)}</t></is></c>`;
      }).join('');
      return `<row r="${i + 1}">${cels}</row>`;
    }).join('');
    const cols = larguras.map((w, i) => `<col min="${i + 1}" max="${i + 1}" width="${w}" customWidth="1"/>`).join('');
    const merge = mesclas.length ? `<mergeCells count="${mesclas.length}">${mesclas.map((m) => `<mergeCell ref="${m}"/>`).join('')}</mergeCells>` : '';
    return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetPr><pageSetUpPr fitToPage="1"/></sheetPr>
<cols>${cols}</cols><sheetData>${corpo}</sheetData>${merge}
<pageMargins left="0.5" right="0.5" top="0.6" bottom="0.6" header="0.3" footer="0.3"/>
<pageSetup paperSize="9" orientation="portrait" fitToWidth="1" fitToHeight="0"/></worksheet>`;
  }

  /** Gera o .xlsx (bytes). As colunas de valor atualizado, totais, indenização e aviso são fórmulas. */
  function xlsx(m) {
    const r = m.r;
    const L = [];
    const mesclas = [];
    const add = (linha) => { L.push(linha); return L.length; };
    add([{ v: 'Memória de cálculo do distrato', s: 6 }]);
    add(['Representação comercial — Lei 4.886/1965']);
    add(null);
    const dados = [
      ['Representada', `${m.empresa.nome || ''}${m.empresa.cnpj ? ` · CNPJ ${m.empresa.cnpj}` : ''}`],
      ['Representante', `${m.representante.razao} · CNPJ ${m.representante.cnpj}`],
      ['Início do contrato', dataBR(m.dataInicio)], ['Data do distrato', dataBR(m.dataDistrato)],
      ['Data do aviso prévio', dataBR(m.dataAviso)],
      ['Índice', `IGP-M (FGV), série 189 do Banco Central, até ${K.rotuloMes(m.ultimoIndice)}`],
    ];
    for (const [a, b] of dados) add([{ v: a, s: 1 }, b]);
    add(null);
    add([{ v: '1. Comissões recebidas e correção monetária', s: 1 }]);
    add(['Mês', 'Comissão (R$)', 'IGP-M do mês (%)', 'IGP-M acumulado (%)', 'Fator de correção', 'Atualizada (R$)', 'Aviso prévio']
      .map((v) => ({ v, s: 7 })));
    const primeira = L.length + 1;
    for (const l of m.linhas) {
      const n = L.length + 1;
      add([l.rotulo, { v: l.valor, s: 2 }, l.igpmMes == null ? '' : { v: l.igpmMes, s: 5 }, { v: l.acumulado, s: 5 },
        { v: l.fator, s: 4 }, { f: `ROUND(B${n}*E${n},2)`, v: l.atualizado, s: 2 }, l.aviso ? 'sim' : '']);
    }
    const ultima = L.length;
    const temLinhas = ultima >= primeira;
    const linhaTotal = add([{ v: `Total (${m.linhas.length} meses)`, s: 1 },
      { f: temLinhas ? `SUM(B${primeira}:B${ultima})` : '0', v: r.somaNominal, s: 3 }, null, null, null,
      { f: temLinhas ? `SUM(F${primeira}:F${ultima})` : '0', v: r.somaAtualizada, s: 3 }]);
    add(null);
    add([{ v: '2. Comissões a receber e sobre títulos pendentes', s: 1 }]);
    add(['Item', 'Período', 'Valor (R$)'].map((v) => ({ v, s: 7 })));
    const linhaReceber = add(['Comissões a receber', periodo(m.aReceber), { v: r.aReceber, s: 2 }]);
    const linhaPendentes = add(['Comissões sobre títulos pendentes', periodo(m.pendentes), { v: r.pendentes, s: 2 }]);
    add(null);
    add([{ v: '3. Cálculo do distrato', s: 1 }]);
    add(['Parcela', 'Cálculo', 'Valor (R$)'].map((v) => ({ v, s: 7 })));
    const linhaBase = add(['Base da indenização', 'atualizadas + a receber + pendentes',
      { f: `F${linhaTotal}+C${linhaReceber}+C${linhaPendentes}`, v: r.baseIndenizacao, s: 2 }]);
    const linhaInden = add(['Indenização (1/12) — art. 27, "j"', m.pagarIndenizacao ? 'base ÷ 12' : 'não paga',
      m.pagarIndenizacao ? { f: `ROUND(C${linhaBase}/12,2)`, v: r.indenizacao, s: 2 } : { v: 0, s: 2 }]);
    const refsAviso = [];
    m.linhas.forEach((l, i) => { if (l.aviso) refsAviso.push(`F${primeira + i}`); });
    const linhaAviso = add(['Aviso prévio — art. 34', refsAviso.length ? `média de ${m.linhas.filter((l) => l.aviso).map((l) => l.rotulo).join(', ')}` : 'não pago',
      refsAviso.length ? { f: `ROUND((${refsAviso.join('+')})/3,2)`, v: r.avisoPrevio, s: 2 } : { v: 0, s: 2 }]);
    const linhaRec2 = add(['Comissões a receber', periodo(m.aReceber), { f: `C${linhaReceber}`, v: r.aReceber, s: 2 }]);
    const linhaPen2 = add(['Comissões sobre títulos pendentes', periodo(m.pendentes), { f: `C${linhaPendentes}`, v: r.pendentes, s: 2 }]);
    add([{ v: 'Total a pagar', s: 1 }, null,
      { f: `C${linhaInden}+C${linhaAviso}+C${linhaRec2}+C${linhaPen2}`, v: r.total, s: 3 }]);
    add([{ v: r.totalExtenso, s: 8 }]);
    mesclas.push(`A${L.length}:G${L.length}`);
    add(null);
    for (const n of notas(m)) {
      add([{ v: n, s: 8 }]);
      mesclas.push(`A${L.length}:G${L.length}`);
    }
    const aba = planilha(L, [24, 30, 16, 18, 16, 16, 12], mesclas);
    const arquivos = [
      { nome: '[Content_Types].xml', dados: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>` },
      { nome: '_rels/.rels', dados: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>` },
      { nome: 'xl/workbook.xml', dados: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<sheets><sheet name="Memória de cálculo" sheetId="1" r:id="rId1"/></sheets><calcPr calcId="191029" fullCalcOnLoad="1"/></workbook>` },
      { nome: 'xl/_rels/workbook.xml.rels', dados: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>` },
      { nome: 'xl/styles.xml', dados: ESTILOS },
      { nome: 'xl/worksheets/sheet1.xml', dados: aba },
    ];
    return DOCX.zip(arquivos);
  }

  return { montar, html, xlsx };
});
