/*
 * Cálculo do distrato de representação comercial (Lei 4.886/1965), conforme a
 * planilha de referência "Cálculo de Comissões":
 *
 *  - cada comissão mensal é atualizada pelo IGP-M acumulado do mês da comissão
 *    (inclusive) até o mês anterior ao do distrato — mesma regra do Cálculo
 *    Exato; se o acumulado for negativo, mantém-se o valor original;
 *  - indenização (art. 27, "j") = (comissões atualizadas + comissões a receber
 *    + comissões sobre títulos pendentes) ÷ 12;
 *  - aviso prévio (art. 34) = soma das comissões atualizadas dos 3 últimos
 *    meses com comissão ÷ 3.
 *
 * Funciona no navegador (window.EscalaDistratoCalculo) e no Node.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.EscalaDistratoCalculo = api;
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const centavos = (v) => Math.round((Number(v) || 0) * 100) / 100;

  function moeda(v) {
    return (Number(v) || 0).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  /** "1.234,56" / "1234,56" / "1234.56" -> 1234.56 ; vazio -> null */
  function lerValor(s) {
    if (s == null) return null;
    if (typeof s === 'number') return Number.isFinite(s) ? s : null;
    let t = String(s).trim().replace(/[R$\s]/g, '');
    if (!t) return null;
    if (/,\d{1,2}$/.test(t)) t = t.replace(/\./g, '').replace(',', '.');
    else if (/^\d{1,3}(\.\d{3})+$/.test(t)) t = t.replace(/\./g, '');
    else t = t.replace(/,/g, '');
    const n = Number(t);
    return Number.isFinite(n) ? n : null;
  }

  // ------------------------------------------------------------------- meses

  const MESES = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];
  const mesDe = (iso) => String(iso).slice(0, 7); // "AAAA-MM"
  function somarMes(mes, n) {
    const [a, m] = mes.split('-').map(Number);
    const t = a * 12 + (m - 1) + n;
    return `${Math.floor(t / 12)}-${String((t % 12) + 1).padStart(2, '0')}`;
  }
  /** Lista de meses "AAAA-MM" de inicio a fim (inclusive). */
  function listarMeses(inicio, fim) {
    const out = [];
    if (!inicio || !fim || inicio > fim) return out;
    for (let m = inicio; m <= fim && out.length < 600; m = somarMes(m, 1)) out.push(m);
    return out;
  }
  const rotuloMes = (mes) => `${MESES[Number(mes.slice(5, 7)) - 1]}/${mes.slice(0, 4)}`;

  /**
   * Fator de atualização pelo índice mensal (variações em %), do mês `de`
   * (inclusive) até o mês anterior a `ate`. Retorna { fator, faltando: [meses] }.
   */
  function fatorIndice(indices, de, ate, desconsiderarDeflacao) {
    let fator = 1;
    const faltando = [];
    for (let m = de; m < ate; m = somarMes(m, 1)) {
      const v = indices[m];
      if (v == null || v === '') { faltando.push(m); continue; }
      fator *= 1 + Number(v) / 100;
    }
    if (desconsiderarDeflacao && fator < 1) fator = 1;
    return { fator, faltando };
  }

  // ------------------------------------------------------------------ cálculo

  /**
   * d: {
   *   dataDistrato: 'AAAA-MM-DD',
   *   comissoes: [{ mes: 'AAAA-MM', valor }],
   *   aReceber: { inicio, fim, valor }, pendentes: { inicio, fim, valor },
   *   pagarAviso (padrão true), pagarIndenizacao (padrão true),
   *   desconsiderarDeflacao (padrão true)
   * }
   * indices: { 'AAAA-MM': variação % do IGP-M }
   */
  function calcular(d, indices) {
    d = d || {};
    indices = indices || {};
    const mesDistrato = d.dataDistrato ? mesDe(d.dataDistrato) : null;
    const deflacao = d.desconsiderarDeflacao !== false;
    const faltando = new Set();
    const validas = (d.comissoes || [])
      .map((c) => ({ mes: c.mes, valor: lerValor(c.valor) }))
      .filter((c) => c.valor != null && c.valor !== 0 && /^\d{4}-\d{2}$/.test(c.mes));
    // comissões de meses posteriores ao distrato não entram no cálculo
    const foraDoPeriodo = validas.filter((c) => mesDistrato && c.mes > mesDistrato).map((c) => c.mes).sort();
    const linhas = validas.filter((c) => !mesDistrato || c.mes <= mesDistrato)
      .sort((a, b) => a.mes.localeCompare(b.mes))
      .map((c) => {
        let fator = 1;
        if (mesDistrato) {
          const r = fatorIndice(indices, c.mes, mesDistrato, deflacao);
          r.faltando.forEach((m) => faltando.add(m));
          fator = r.fator;
        }
        return { mes: c.mes, valor: centavos(c.valor), fator, atualizado: centavos(c.valor * fator) };
      });

    const somaNominal = centavos(linhas.reduce((s, l) => s + l.valor, 0));
    const somaAtualizada = centavos(linhas.reduce((s, l) => s + l.atualizado, 0));
    const aReceber = centavos(lerValor(d.aReceber && d.aReceber.valor) || 0);
    const pendentes = centavos(lerValor(d.pendentes && d.pendentes.valor) || 0);

    const baseIndenizacao = centavos(somaAtualizada + aReceber + pendentes);
    const indenizacao = d.pagarIndenizacao === false ? 0 : centavos(baseIndenizacao / 12);

    const ultimos = linhas.slice(-3);
    const avisoPrevio = d.pagarAviso === false || !ultimos.length ? 0
      : centavos(ultimos.reduce((s, l) => s + l.atualizado, 0) / 3);

    // o total é a soma das parcelas já arredondadas, para fechar com o que o termo lista
    const total = centavos(avisoPrevio + indenizacao + aReceber + pendentes);

    return {
      linhas, somaNominal, somaAtualizada, aReceber, pendentes, baseIndenizacao,
      indenizacao, avisoPrevio, mesesAviso: ultimos.map((l) => l.mes), total,
      totalExtenso: porExtenso(total),
      indicesFaltando: [...faltando].sort(),
      foraDoPeriodo,
    };
  }

  // ------------------------------------------------------------ por extenso

  const UNID = ['', 'um', 'dois', 'três', 'quatro', 'cinco', 'seis', 'sete', 'oito', 'nove', 'dez', 'onze', 'doze',
    'treze', 'quatorze', 'quinze', 'dezesseis', 'dezessete', 'dezoito', 'dezenove'];
  const DEZ = ['', '', 'vinte', 'trinta', 'quarenta', 'cinquenta', 'sessenta', 'setenta', 'oitenta', 'noventa'];
  const CEM = ['', 'cento', 'duzentos', 'trezentos', 'quatrocentos', 'quinhentos', 'seiscentos', 'setecentos',
    'oitocentos', 'novecentos'];

  /** 0 < n < 1000 */
  function centena(n) {
    if (n === 100) return 'cem';
    const c = Math.floor(n / 100);
    const r = n % 100;
    const partes = [];
    if (c) partes.push(CEM[c]);
    if (r) {
      if (r < 20) partes.push(UNID[r]);
      else partes.push(DEZ[Math.floor(r / 10)] + (r % 10 ? ' e ' + UNID[r % 10] : ''));
    }
    return partes.join(' e ');
  }

  /** Inteiro por extenso (até a casa dos bilhões). */
  function inteiroExtenso(n) {
    if (n === 0) return 'zero';
    const grupos = [];
    let x = n;
    while (x > 0) { grupos.push(x % 1000); x = Math.floor(x / 1000); }
    const nomes = [['', ''], ['mil', 'mil'], ['milhão', 'milhões'], ['bilhão', 'bilhões']];
    const partes = [];
    for (let i = grupos.length - 1; i >= 0; i--) {
      const g = grupos[i];
      if (!g) continue;
      let t = i === 1 && g === 1 ? 'mil' : centena(g) + (i ? ' ' + nomes[i][g === 1 ? 0 : 1] : '');
      // "e" antes do último grupo quando ele é menor que cem ou é centena redonda
      const resto = grupos.slice(0, i).reduce((s, v, k) => s + v * 1000 ** k, 0);
      partes.push(t);
      if (i > 0 && resto > 0) {
        const menor = grupos.slice(0, i).reverse().findIndex((v) => v > 0);
        const ultimoGrupo = grupos.slice(0, i).reverse()[menor];
        const unicoRestante = grupos.slice(0, i).filter((v) => v > 0).length === 1;
        if (unicoRestante && (ultimoGrupo < 100 || ultimoGrupo % 100 === 0)) partes.push('e');
      }
    }
    return partes.join(' ').replace(/\s+/g, ' ');
  }

  /** Valor em reais por extenso, com a primeira letra maiúscula. */
  function porExtenso(valor) {
    const totalCent = Math.round(Math.abs(Number(valor) || 0) * 100);
    const reais = Math.floor(totalCent / 100);
    const cents = totalCent % 100;
    const partes = [];
    if (reais) {
      const ext = inteiroExtenso(reais);
      const de = reais >= 1000000 && reais % 1000000 === 0 ? ' de' : '';
      partes.push(`${ext}${de} ${reais === 1 ? 'real' : 'reais'}`);
    }
    if (cents) partes.push(`${inteiroExtenso(cents)} ${cents === 1 ? 'centavo' : 'centavos'}`);
    const t = partes.length ? partes.join(' e ') : 'zero reais';
    return t.charAt(0).toUpperCase() + t.slice(1);
  }

  return {
    calcular, fatorIndice, porExtenso, inteiroExtenso, moeda, lerValor, centavos,
    listarMeses, somarMes, mesDe, rotuloMes,
  };
});
