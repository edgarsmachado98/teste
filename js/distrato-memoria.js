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
      simples: d.simples || {},
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
        <img src="img/logo-moinho-santa-maria.png" alt="" width="60" height="70">
        <div><h1>Memória de cálculo do distrato</h1>
        <p>Representação comercial — Lei 4.886/1965</p></div>
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
        <tr class="mc-total"><th>Total (${m.linhas.length} ${m.linhas.length === 1 ? 'mês' : 'meses'})</th><th class="num">${K.moeda(r.somaNominal)}</th><th></th><th></th><th></th>
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
          <tr class="mc-total"><th colspan="2">${r.reterIR ? 'Total bruto' : 'Total a pagar'}</th><th class="num">${K.moeda(r.total)}</th></tr>
        </tbody>
      </table>
      ${r.reterIR ? htmlIR(m) : `<p class="mc-extenso">${esc(r.totalExtenso)}</p>${m.simples.situacao === 'optante'
    ? '<p class="mc-nota-fator">Representante optante do Simples Nacional: sem retenção de imposto de renda (IN RFB 765/2007).</p>' : ''}`}
      ${m.linhas.some((l) => l.acumulado < 0 && l.fator === 1) ? '<p class="mc-nota-fator">* IGP-M acumulado negativo: mantido o valor original (fator 1).</p>' : ''}
      ${r.indicesFaltando.length ? `<p class="mc-alerta">Atenção: faltam índices do IGP-M de ${r.indicesFaltando.map(K.rotuloMes).join(', ')}; os fatores podem estar incompletos.</p>` : ''}
      <ol class="mc-notas">${notas(m).map((n) => `<li>${esc(n)}</li>`).join('')}</ol>
    </div>`;
  }

  /** Itens da retenção de IR: [rótulo, base, alíquota, imposto]. */
  const itensIR = (r) => [
    ['Aviso prévio', r.avisoPrevio, K.IR_COMISSOES, r.ir.aviso],
    ['Comissões a receber', r.aReceber, K.IR_COMISSOES, r.ir.aReceber],
    ['Títulos pendentes', r.pendentes, K.IR_COMISSOES, r.ir.pendentes],
    ['Indenização (1/12)', r.indenizacao, K.IR_INDENIZACAO, r.ir.indenizacao],
  ];
  const origemSimples = (m) => (m.simples.fonte === 'consulta'
    ? `consulta em ${m.simples.consultadoEm ? new Date(m.simples.consultadoEm).toLocaleDateString('pt-BR') : ''}${m.simples.detalhe ? `: ${m.simples.detalhe}` : ''}`
    : 'informado manualmente');

  function htmlIR(m) {
    const r = m.r;
    return `<h2>4. Retenção de imposto de renda na fonte</h2>
      <p class="mc-nota-fator">Representante não optante do Simples Nacional (${esc(origemSimples(m))}).</p>
      <table class="mc-tabela mc-resumo">
        <thead><tr><th>Parcela</th><th class="num">Base (R$)</th><th class="num">Alíquota</th><th class="num">IR retido (R$)</th></tr></thead>
        <tbody>
          ${itensIR(r).map(([rot, base, aliq, ir]) => `<tr><td>${rot}</td><td class="num">${K.moeda(base)}</td>
            <td class="num">${pct(aliq * 100, 1)}</td><td class="num">${K.moeda(ir)}</td></tr>`).join('')}
          <tr class="mc-total"><th>Total do IR retido</th><th></th><th></th><th class="num">${K.moeda(r.ir.total)}</th></tr>
        </tbody>
      </table>
      <table class="mc-tabela mc-resumo">
        <tbody>
          <tr><td>Total bruto</td><td class="num">${K.moeda(r.total)}</td></tr>
          <tr><td>(−) IR retido na fonte</td><td class="num">${K.moeda(r.ir.total)}</td></tr>
          <tr class="mc-total"><th>Valor líquido a pagar</th><th class="num">${K.moeda(r.liquido)}</th></tr>
        </tbody>
      </table>
      <p class="mc-extenso">${esc(r.liquidoExtenso)}</p>
      <p class="mc-nota-fator">IR de 1,5% sobre comissões pagas a pessoa jurídica (RIR/2018, art. 718) e de 15% sobre a indenização
        por rescisão contratual (Lei 9.430/1996, art. 70).</p>`;
  }

  // ------------------------------------------------------------- Excel (.xlsx)

  const xml = (s) => String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  const colLetra = (i) => String.fromCharCode(65 + i);

  // estilos (índices de cellXfs)
  const S = {
    normal: 0, negrito: 1, moeda: 2, moedaNegrito: 3, fator: 4, pct2: 5, titulo: 6, cabecalho: 7, texto: 8, pct4: 9,
    totalRotulo: 10, totalMoeda: 11, subtitulo: 12, secao: 13, cabecalhoNum: 14, centro: 15,
  };
  const ESTILOS = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<numFmts count="4"><numFmt numFmtId="164" formatCode="#,##0.00"/><numFmt numFmtId="165" formatCode="0.000000"/><numFmt numFmtId="166" formatCode="0.00"/><numFmt numFmtId="167" formatCode="0.0000"/></numFmts>
<fonts count="5"><font><sz val="10"/><name val="Calibri"/></font><font><b/><sz val="10"/><name val="Calibri"/></font><font><b/><sz val="14"/><color rgb="FF2E3192"/><name val="Calibri"/></font><font><sz val="9"/><color rgb="FF555555"/><name val="Calibri"/></font><font><b/><sz val="11"/><color rgb="FF2E3192"/><name val="Calibri"/></font></fonts>
<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FFE8EAF6"/><bgColor indexed="64"/></patternFill></fill></fills>
<borders count="3"><border><left/><right/><top/><bottom/><diagonal/></border><border><left/><right/><top/><bottom style="thin"><color rgb="FF999999"/></bottom><diagonal/></border><border><left/><right/><top style="medium"><color rgb="FF2E3192"/></top><bottom/><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="16">
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>
<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
<xf numFmtId="164" fontId="1" fillId="0" borderId="0" xfId="0" applyNumberFormat="1" applyFont="1"/>
<xf numFmtId="165" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
<xf numFmtId="166" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
<xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1" applyAlignment="1"><alignment vertical="center"/></xf>
<xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment wrapText="1" vertical="center"/></xf>
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment wrapText="1" vertical="top"/></xf>
<xf numFmtId="167" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
<xf numFmtId="0" fontId="1" fillId="0" borderId="2" xfId="0" applyFont="1" applyBorder="1"/>
<xf numFmtId="164" fontId="1" fillId="0" borderId="2" xfId="0" applyNumberFormat="1" applyFont="1" applyBorder="1"/>
<xf numFmtId="0" fontId="3" fillId="0" borderId="0" xfId="0" applyFont="1"/>
<xf numFmtId="0" fontId="4" fillId="0" borderId="0" xfId="0" applyFont="1"/>
<xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="right" wrapText="1" vertical="center"/></xf>
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment horizontal="center"/></xf>
</cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>`;

  /**
   * Planilha com uma aba; células: { v, f, s } (v = texto ou número; f = fórmula).
   * alturas: { linha (1..n): altura em pontos }.
   */
  function planilha(linhas, larguras, mesclas, alturas, desenho, ncols = 7, orientacao = 'portrait') {
    const corpo = linhas.map((l, i) => {
      const ht = alturas[i + 1] ? ` ht="${alturas[i + 1]}" customHeight="1"` : '';
      if (!l) return ht ? `<row r="${i + 1}"${ht}/>` : '';
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
      return `<row r="${i + 1}"${ht}>${cels}</row>`;
    }).join('');
    const cols = larguras.map((w, i) => `<col min="${i + 1}" max="${i + 1}" width="${w}" customWidth="1"/>`).join('');
    const merge = mesclas.length ? `<mergeCells count="${mesclas.length}">${mesclas.map((m) => `<mergeCell ref="${m}"/>`).join('')}</mergeCells>` : '';
    return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<sheetPr><pageSetUpPr fitToPage="1"/></sheetPr><dimension ref="A1:${colLetra(ncols - 1)}${Math.max(1, linhas.length)}"/>
<sheetViews><sheetView showGridLines="0" workbookViewId="0"/></sheetViews><sheetFormatPr defaultRowHeight="15"/>
<cols>${cols}</cols><sheetData>${corpo}</sheetData>${merge}
<pageMargins left="0.5" right="0.5" top="0.6" bottom="0.6" header="0.3" footer="0.3"/>
<pageSetup paperSize="9" orientation="${orientacao}" fitToWidth="1" fitToHeight="0"/>${desenho ? '<drawing r:id="rId1"/>' : ''}</worksheet>`;
  }

  /**
   * Gera o .xlsx (bytes). As colunas de valor atualizado, totais, indenização e aviso são fórmulas.
   * Layout em 7 colunas (A a G); todos os valores em reais ficam na coluna F.
   * logo (opcional): { bytes: Uint8Array PNG, largura, altura } — vai no canto superior esquerdo, ao lado do título.
   */
  function xlsx(m, logo) {
    const r = m.r;
    const L = [];
    const mesclas = [];
    const alturas = {};
    const add = (linha) => { L.push(linha); return L.length; };
    const mesclar = (de, ate) => mesclas.push(`${de}${L.length}:${ate}${L.length}`);
    // linha com texto em A e um texto longo mesclado de B a E, valor em F
    const linhaTexto = (rotulo, texto, valor, estilo = S.moeda) => {
      const n = add([rotulo, texto, null, null, null, valor && typeof valor === 'object' ? { s: estilo, ...valor } : { v: valor, s: estilo }]);
      mesclar('B', 'E');
      return n;
    };
    // com logotipo, ele ocupa a coluna A das 3 primeiras linhas e o título vai para a coluna B
    const c0 = logo ? [null] : [];
    add([...c0, { v: 'Memória de cálculo do distrato', s: S.titulo }]);
    add([...c0, { v: 'Representação comercial — Lei 4.886/1965', s: S.subtitulo }]);
    add(null);
    Object.assign(alturas, logo ? { 1: 28, 2: 18, 3: 14 } : { 1: 24, 3: 10 });
    const dados = [
      ['Representada', `${m.empresa.nome || ''}${m.empresa.cnpj ? ` · CNPJ ${m.empresa.cnpj}` : ''}`],
      ['Representante', `${m.representante.razao} · CNPJ ${m.representante.cnpj}`],
      ['Início do contrato', dataBR(m.dataInicio)], ['Data do distrato', dataBR(m.dataDistrato)],
      ['Data do aviso prévio', dataBR(m.dataAviso)],
      ['Índice', `IGP-M (FGV), série 189 do Banco Central, até ${K.rotuloMes(m.ultimoIndice)}`],
    ];
    for (const [a, b] of dados) { add([{ v: a, s: S.negrito }, b]); mesclar('B', 'E'); }
    add(null);
    add([{ v: '1. Comissões recebidas e correção monetária', s: S.secao }]);
    const cab = add([{ v: 'Mês', s: S.cabecalho }, { v: 'Comissão (R$)', s: S.cabecalhoNum }, { v: 'IGP-M do mês (%)', s: S.cabecalhoNum },
      { v: 'IGP-M acumulado (%)', s: S.cabecalhoNum }, { v: 'Fator de correção', s: S.cabecalhoNum }, { v: 'Atualizada (R$)', s: S.cabecalhoNum },
      { v: 'Aviso prévio', s: S.cabecalho }]);
    alturas[cab] = 30;
    const primeira = L.length + 1;
    for (const l of m.linhas) {
      const n = L.length + 1;
      add([l.rotulo, { v: l.valor, s: S.moeda }, l.igpmMes == null ? '' : { v: l.igpmMes, s: S.pct2 }, { v: l.acumulado, s: S.pct4 },
        { v: l.fator, s: S.fator }, { f: `ROUND(B${n}*E${n},2)`, v: l.atualizado, s: S.moeda }, l.aviso ? { v: 'sim', s: S.centro } : '']);
    }
    const ultima = L.length;
    const temLinhas = ultima >= primeira;
    const linhaTotal = add([{ v: `Total (${m.linhas.length} ${m.linhas.length === 1 ? 'mês' : 'meses'})`, s: S.totalRotulo },
      { f: temLinhas ? `SUM(B${primeira}:B${ultima})` : '0', v: r.somaNominal, s: S.totalMoeda }, { s: S.totalRotulo }, { s: S.totalRotulo },
      { s: S.totalRotulo }, { f: temLinhas ? `SUM(F${primeira}:F${ultima})` : '0', v: r.somaAtualizada, s: S.totalMoeda }, { s: S.totalRotulo }]);
    add(null);
    add([{ v: '2. Comissões a receber e sobre títulos pendentes', s: S.secao }]);
    add([{ v: 'Item', s: S.cabecalho }, { v: 'Período', s: S.cabecalho }, { s: S.cabecalho }, { s: S.cabecalho }, { s: S.cabecalho },
      { v: 'Valor (R$)', s: S.cabecalhoNum }]);
    mesclar('B', 'E');
    const linhaReceber = linhaTexto('Comissões a receber', periodo(m.aReceber), r.aReceber);
    const linhaPendentes = linhaTexto('Títulos pendentes', periodo(m.pendentes), r.pendentes);
    add(null);
    add([{ v: '3. Cálculo do distrato', s: S.secao }]);
    add([{ v: 'Parcela', s: S.cabecalho }, { v: 'Cálculo', s: S.cabecalho }, { s: S.cabecalho }, { s: S.cabecalho }, { s: S.cabecalho },
      { v: 'Valor (R$)', s: S.cabecalhoNum }]);
    mesclar('B', 'E');
    const linhaBase = linhaTexto('Base da indenização', 'comissões atualizadas + a receber + títulos pendentes',
      { f: `F${linhaTotal}+F${linhaReceber}+F${linhaPendentes}`, v: r.baseIndenizacao });
    const linhaInden = linhaTexto('Indenização (1/12)', m.pagarIndenizacao ? 'base ÷ 12 (Lei 4.886/1965, art. 27, "j")' : 'não paga',
      m.pagarIndenizacao ? { f: `ROUND(F${linhaBase}/12,2)`, v: r.indenizacao } : 0);
    const refsAviso = [];
    m.linhas.forEach((l, i) => { if (l.aviso) refsAviso.push(`F${primeira + i}`); });
    const linhaAviso = linhaTexto('Aviso prévio', refsAviso.length
      ? `média de ${m.linhas.filter((l) => l.aviso).map((l) => l.rotulo).join(', ')} (art. 34)` : 'não pago',
    refsAviso.length ? { f: `ROUND((${refsAviso.join('+')})/3,2)`, v: r.avisoPrevio } : 0);
    const linhaRec2 = linhaTexto('Comissões a receber', periodo(m.aReceber), { f: `F${linhaReceber}`, v: r.aReceber });
    const linhaPen2 = linhaTexto('Títulos pendentes', periodo(m.pendentes), { f: `F${linhaPendentes}`, v: r.pendentes });
    const linhaBruto = add([{ v: r.reterIR ? 'Total bruto' : 'Total a pagar', s: S.totalRotulo }, { s: S.totalRotulo }, { s: S.totalRotulo },
      { s: S.totalRotulo }, { s: S.totalRotulo },
      { f: `F${linhaInden}+F${linhaAviso}+F${linhaRec2}+F${linhaPen2}`, v: r.total, s: S.totalMoeda }, { s: S.totalRotulo }]);
    if (r.reterIR) {
      add(null);
      add([{ v: '4. Retenção de imposto de renda na fonte', s: S.secao }]);
      add([{ v: `Representante não optante do Simples Nacional (${origemSimples(m)}).`, s: S.texto }]);
      mesclar('A', 'G');
      add([{ v: 'Parcela', s: S.cabecalho }, { v: 'Base (R$)', s: S.cabecalhoNum }, { v: 'Alíquota (%)', s: S.cabecalhoNum }, { s: S.cabecalho },
        { s: S.cabecalho }, { v: 'IR retido (R$)', s: S.cabecalhoNum }]);
      const bases = { 'Aviso prévio': linhaAviso, 'Comissões a receber': linhaRec2, 'Títulos pendentes': linhaPen2, 'Indenização (1/12)': linhaInden };
      const primeiraIR = L.length + 1;
      for (const [rot, base, aliq, ir] of itensIR(r)) {
        const n = L.length + 1;
        add([rot, { f: `F${bases[rot]}`, v: base, s: S.moeda }, { v: aliq * 100, s: S.pct2 }, null, null,
          { f: `ROUND(B${n}*C${n}/100,2)`, v: ir, s: S.moeda }]);
      }
      const linhaIR = add([{ v: 'Total do IR retido', s: S.totalRotulo }, { s: S.totalRotulo }, { s: S.totalRotulo }, { s: S.totalRotulo },
        { s: S.totalRotulo }, { f: `SUM(F${primeiraIR}:F${L.length})`, v: r.ir.total, s: S.totalMoeda }, { s: S.totalRotulo }]);
      add(null);
      add([{ v: 'Valor líquido a pagar', s: S.totalRotulo }, { s: S.totalRotulo }, { s: S.totalRotulo }, { s: S.totalRotulo },
        { s: S.totalRotulo }, { f: `F${linhaBruto}-F${linhaIR}`, v: r.liquido, s: S.totalMoeda }, { s: S.totalRotulo }]);
    }
    add([{ v: r.reterIR ? r.liquidoExtenso : r.totalExtenso, s: S.texto }]);
    mesclar('A', 'G');
    if (r.reterIR) {
      add([{ v: 'IR de 1,5% sobre comissões pagas a pessoa jurídica (RIR/2018, art. 718) e de 15% sobre a indenização por rescisão contratual (Lei 9.430/1996, art. 70).', s: S.texto }]);
      mesclar('A', 'G');
      alturas[L.length] = 28;
    } else if (m.simples.situacao === 'optante') {
      add([{ v: 'Representante optante do Simples Nacional: sem retenção de imposto de renda (IN RFB 765/2007).', s: S.texto }]);
      mesclar('A', 'G');
    }
    add(null);
    for (const n of notas(m)) {
      add([{ v: n, s: S.texto }]);
      mesclar('A', 'G');
      alturas[L.length] = n.length > 110 ? 28 : 15; // células mescladas não ajustam a altura sozinhas no Excel
    }
    const aba = planilha(L, [22, 15, 14, 16, 14, 16, 11], mesclas, alturas, !!logo);
    return pacote(aba, logo, 'Memória de cálculo');
  }

  /** Monta o arquivo .xlsx (uma aba) com o logotipo opcional no canto superior esquerdo. */
  function pacote(aba, logo, nomeAba) {
    const arquivos = [
      { nome: '[Content_Types].xml', dados: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Default Extension="png" ContentType="image/png"/>
<Override PartName="/xl/drawings/drawing1.xml" ContentType="application/vnd.openxmlformats-officedocument.drawing+xml"/>
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
<sheets><sheet name="${xml(nomeAba)}" sheetId="1" r:id="rId1"/></sheets><calcPr calcId="191029" fullCalcOnLoad="1"/></workbook>` },
      { nome: 'xl/_rels/workbook.xml.rels', dados: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>` },
      { nome: 'xl/styles.xml', dados: ESTILOS },
      { nome: 'xl/worksheets/sheet1.xml', dados: aba },
    ];
    if (logo) {
      // cerca de 1,8 cm de altura, proporcional, no canto superior esquerdo (coluna A, linhas 1 a 3)
      const emu = 9525;
      const alt = 68;
      const larg = Math.round(alt * logo.largura / logo.altura);
      arquivos.push(
        { nome: 'xl/media/image1.png', dados: logo.bytes },
        { nome: 'xl/worksheets/_rels/sheet1.xml.rels', dados: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing" Target="../drawings/drawing1.xml"/>
</Relationships>` },
        { nome: 'xl/drawings/_rels/drawing1.xml.rels', dados: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/image1.png"/>
</Relationships>` },
        { nome: 'xl/drawings/drawing1.xml', dados: `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<xdr:oneCellAnchor><xdr:from><xdr:col>0</xdr:col><xdr:colOff>38100</xdr:colOff><xdr:row>0</xdr:row><xdr:rowOff>19050</xdr:rowOff></xdr:from>
<xdr:ext cx="${larg * emu}" cy="${alt * emu}"/>
<xdr:pic><xdr:nvPicPr><xdr:cNvPr id="2" name="Logotipo"/><xdr:cNvPicPr><a:picLocks noChangeAspect="1"/></xdr:cNvPicPr></xdr:nvPicPr>
<xdr:blipFill><a:blip r:embed="rId1"/><a:stretch><a:fillRect/></a:stretch></xdr:blipFill>
<xdr:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="${larg * emu}" cy="${alt * emu}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></xdr:spPr></xdr:pic>
<xdr:clientData/></xdr:oneCellAnchor></xdr:wsDr>` },
      );
    }
    return DOCX.zip(arquivos);
  }

  /**
   * Planilha de uma tabela simples: título, subtítulo, cabeçalho e linhas (texto ou número; números com 2
   * casas usam o formato de moeda quando a coluna está em `moeda`).
   */
  function tabelaXlsx({ titulo, subtitulo, cabecalho, linhas, larguras, moeda = [], logo = null, nomeAba = 'Lista' }) {
    const c0 = logo ? [null] : [];
    const L = [[...c0, { v: titulo, s: S.titulo }], [...c0, { v: subtitulo || '', s: S.subtitulo }], null];
    const alturas = logo ? { 1: 28, 2: 18, 3: 14 } : { 1: 24 };
    const cab = L.push(cabecalho.map((v) => ({ v, s: S.cabecalho })));
    alturas[cab] = 30;
    for (const l of linhas) L.push(l.map((v, j) => (typeof v === 'number' && moeda.includes(j) ? { v, s: S.moeda } : v == null ? '' : v)));
    const aba = planilha(L, larguras, [], alturas, !!logo, cabecalho.length, 'landscape');
    return pacote(aba, logo, nomeAba);
  }

  return { montar, html, xlsx, tabelaXlsx };
});
