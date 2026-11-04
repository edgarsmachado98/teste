/*
 * Modelos de Termo de Distrato e Aviso Prévio de representação comercial, um
 * par para cada empresa representada (Antoniazzi & Cia e Antoniazzi Alimentos),
 * reproduzindo os documentos da empresa. Os dados do representante vêm do
 * contrato cadastrado; os valores, do cálculo do distrato.
 *
 * Usa as mesmas marcações e campos ⟦nome⟧ do modelo do contrato.
 */
(function (root, factory) {
  const api = factory(
    root.EscalaContrato || (typeof require === 'function' ? require('./contrato-modelo.js') : null),
    root.EscalaDistratoCalculo || (typeof require === 'function' ? require('./distrato-calculo.js') : null));
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.EscalaDistrato = api;
})(typeof self !== 'undefined' ? self : this, function (C, K) {
  'use strict';

  const EMPRESAS = {
    cia: {
      nome: 'Antoniazzi & Cia Ltda',
      cnpj: '95.597.647/0001-59',
      distratoParte: '**ANTONIAZZI & CIA LTDA.**, inscrita no CNPJ sob o nº 95.597.647/0001-59, empresa estabelecida ' +
        'na Rua Aristides Lobo, 290, Bairro Rosário, Santa Maria/RS, neste ato representada por seu sócio, ' +
        'Sr. José Celestino Montagner Antoniazzi, doravante designada **REPRESENTADA**, e de outro',
      avisoContratante: '**CONTRATANTE: ANTONIAZZI & CIA LTDA.**, inscrita no CNPJ nº 95.597.647/0001-59, localizada ' +
        'na Rua Aristides Lobo, na cidade de Santa Maria/RS, neste ato representada por seu sócio, ' +
        'Sr. José Celestino Montagner Antoniazzi.',
      assinatura: 'ANTONIAZZI & CIA LTDA',
      cidadeDistrato: 'Santa Maria/RS',
      logo: false,
      assinaturasLado: true,
    },
    alimentos: {
      nome: 'Antoniazzi Ind. e Com. de Alimentos Ltda',
      cnpj: '11.780.083/0001-03',
      distratoParte: '**ANTONIAZZI INDUSTRIA E COMERCIO DE ALIMENTOS LTDA.**, inscrita no CNPJ sob o nº ' +
        '11.780.083/0001-03, empresa estabelecida na Rua Castro Alves, 88, Vila Fernandes - Canoas/RS, neste ato ' +
        'representada por seu sócio, Sr. José Celestino Montagner Antoniazzi, doravante designada ' +
        '**REPRESENTADA**, e de outro lado a empresa,',
      avisoContratante: '**CONTRATANTE: ANTONIAZZI IND E COM. DE ALIMENTOS LTDA**, pessoa jurídica de direito ' +
        'privado, com sede e foro na Rua Castro Alves, 88, Vila Fernandes, Canoas RS, CEP 92114-430, inscrita no ' +
        'CNPJ/MF sob o nº 11.780.083/0001-03, neste ato representada por seu sócio **JOSÉ CELESTINO MONTAGNER ' +
        'ANTONIAZZI**, brasileiro, casado, empresário, com inscrição no CPF sob o n.º 303.268.850-72.',
      assinatura: 'ANTONIAZZI IND. E COM. DE ALIM. LTDA',
      assinaturaAviso: 'ANTONIAZZI IND E COM. DE ALIMENTOS LTDA',
      cidadeDistrato: 'Canoas/RS',
      logo: true,
      assinaturasLado: false,
    },
  };

  const DOCUMENTOS = [
    { id: 'distrato', nome: 'Termo de distrato' },
    { id: 'aviso', nome: 'Aviso prévio' },
  ];

  const c = (nome) => `⟦${nome}⟧`;
  const dataBR = (iso) => (iso ? iso.split('-').reverse().join('/') : '');

  /** Valores dos campos ⟦…⟧: dados do representante (contrato) + distrato + cálculo. */
  function valores(contrato, distrato, resultado) {
    const v = C.valores(contrato || {});
    const d = distrato || {};
    const t = (x) => String(x == null ? '' : x).trim();
    const r = resultado || K.calcular(d, {});
    const periodo = (p) => (p && p.inicio && p.fim ? `${dataBR(p.inicio)} a ${dataBR(p.fim)}` : '');
    return Object.assign(v, {
      profissao: t(d.profissao).toLowerCase(),
      estadoCivil: t(d.estadoCivil).toLowerCase(),
      naturalidade: t(d.naturalidade),
      dataInicio: C.dataExtenso(d.dataInicio),
      dataDistrato: C.dataExtenso(d.dataDistrato),
      dataAviso: C.dataExtenso(d.dataAviso || d.dataDistrato),
      // a cláusula segunda traz a quantia líquida (igual ao total quando não há retenção de IR)
      total: K.moeda(r.liquido),
      totalExtenso: r.liquidoExtenso,
      totalBruto: K.moeda(r.total),
      baseComissoesIR: K.moeda(r.avisoPrevio + r.aReceber + r.pendentes),
      irComissoes: K.moeda(r.ir.comissoes),
      irIndenizacao: K.moeda(r.ir.indenizacao),
      irTotal: K.moeda(r.ir.total),
      aviso: K.moeda(r.avisoPrevio),
      indenizacao: K.moeda(r.indenizacao),
      aReceber: K.moeda(r.aReceber),
      pendentes: K.moeda(r.pendentes),
      periodoReceber: periodo(d.aReceber),
      periodoPendentes: periodo(d.pendentes),
    });
  }

  /** Qualificação do representante, com profissão, estado civil e naturalidade quando informados. */
  function qualificacao(contrato, distrato) {
    const f = contrato && contrato.sexo === 'F';
    const d = distrato || {};
    const partes = [`**${c('responsavel')}**`, c('nacionalidade')];
    if (String(d.profissao || '').trim()) partes.push(c('profissao'));
    if (String(d.estadoCivil || '').trim()) partes.push(c('estadoCivil'));
    let nasc = `${f ? 'nascida' : 'nascido'} em ${c('nascimento')}`;
    if (String(d.naturalidade || '').trim()) nasc += `, natural de ${c('naturalidade')}`;
    partes.push(nasc);
    return `**${c('razao')}**, pessoa jurídica de direito privado, de nome fantasia **${c('fantasia')}**, ` +
      `estabelecida no endereço ${c('endEmpresa')}, inscrita no CNPJ ${c('cnpj')}, representada neste por ` +
      `${partes.join(', ')}, ${f ? 'portadora' : 'portador'} da cédula de identidade de nº ${c('rg')}, ` +
      `${f ? 'inscrita' : 'inscrito'} no CPF sob nº ${c('cpf')}, residente ao endereço ${c('endResidencial')}`;
  }

  function distratoBlocos(e, contrato, d, r) {
    const itens = [];
    if (r.avisoPrevio) itens.push(`**- Ref. Aviso prévio: R$ ${c('aviso')}**`);
    if (r.indenizacao) itens.push(`**- Ref. Indenização 1/12 avos: R$ ${c('indenizacao')}**`);
    if (r.aReceber) itens.push(`**- Comissões a receber de ${c('periodoReceber')}: R$ ${c('aReceber')}**`);
    if (r.pendentes) itens.push(`**- Comissões sobre títulos pendentes de ${c('periodoPendentes')}: R$ ${c('pendentes')}**`);
    // representante não optante do Simples: demonstra o IR retido e o líquido
    if (r.reterIR && r.ir.total) {
      itens.push(`**Valor bruto: R$ ${c('totalBruto')}**`);
      if (r.ir.comissoes) {
        itens.push(`**(-) IRRF de 1,5% sobre aviso prévio, comissões a receber e títulos pendentes (base R$ ${c('baseComissoesIR')}): ` +
          `R$ ${c('irComissoes')}**`);
      }
      if (r.ir.indenizacao) itens.push(`**(-) IRRF de 15% sobre a indenização 1/12 avos (base R$ ${c('indenizacao')}): R$ ${c('irIndenizacao')}**`);
      itens.push(`**Valor líquido: R$ ${c('total')}**`);
    }
    const ass = e.assinaturasLado
      ? [['assLado', [[e.assinatura, 'REPRESENTADA'], ['⟦razao⟧', 'REPRESENTANTE']]]]
      : [['assPilha', [e.assinatura, 'REPRESENTADA']], ['assPilha', ['⟦razao⟧', 'REPRESENTANTE']]];
    return [
      ['tituloCentro', 'TERMO DE DISTRATO DO CONTRATO DE REPRESENTAÇÃO COMERCIAL'],
      ['p', `Que entre si firmam, de um lado a ${e.distratoParte} ${qualificacao(contrato, d)}, aqui designado ` +
        '**REPRESENTANTE**, representada na forma do seu Contrato Social, tem entre si justo e avençado o que segue:'],
      ['clausula', 'PRIMEIRA'],
      ['p', 'Tendo em vista a manifestada intenção da **REPRESENTADA** em rescindir o contrato de representação ' +
        `comercial que mantém firmado com a **REPRESENTANTE** desde ${c('dataInicio')} em comum acordo convencionam ` +
        'as partes o distrato do Contrato de Representação Comercial, para que seus efeitos se operem a partir ' +
        'desta data.'],
      ['clausula', 'SEGUNDA'],
      ['pc', 'Paga neste ato a **REPRESENTADA** ao **REPRESENTANTE**, a quantia líquida de:'],
      ['p', `__**R$ ${c('total')} (${c('totalExtenso')}).**__`],
      ...itens.map((t) => ['p', t]),
      ['clausula', 'TERCEIRA'],
      ['pc', 'Declarando-se plenamente satisfeitas, as partes dão-se mutuamente ampla e geral quitação no tocante a ' +
        'qualquer parcela que eventualmente pudesse ser reclamada da extinta contratualidade, para mais nada ' +
        'reclamarem, no presente ou no futuro, seja a que título for.'],
      ['p', 'Declaram ainda, que pelo pagamento supra discriminado, ficam quitados todos os direitos da representante ' +
        'comercial, seus sócios ou empregados referentes a honorários, comissões de qualquer espécie e despesas de ' +
        'qualquer natureza, dando por plenamente rescindida a relação comercial entre as partes, para todos os fins ' +
        'legais e de direito, especialmente quanto à indenização de 1/12 (um doze avos) de que trata art. 27, "j", ' +
        'da Lei 4.886/65, nada mais tendo a representante e seus sócios a reclamar a qualquer título.'],
      ['clausula', 'QUARTA'],
      ['p', 'Elegem o foro da comarca de Santa Maria (RS) para dirimir qualquer controvérsia oriunda do presente ' +
        'termo, com renúncia a qualquer outro por mais privilegiado que possa ser.'],
      ['p', 'E por assim, se acharem devidamente avençados, firmam o presente em duas vias de igual teor e forma.'],
      ['dataLivre', `${e.cidadeDistrato}, ${c('dataDistrato')}.`, { direita: true }],
      ...ass,
      ['testNum'],
    ];
  }

  function avisoBlocos(e, contrato, d) {
    const contratada = ['⟦razao⟧', 'CONTRATADA'];
    const contratante = [e.assinaturaAviso || e.assinatura, 'CONTRATANTE'];
    return [
      ['tituloCentro', 'AVISO PRÉVIO DE REPRESENTAÇÃO COMERCIAL'],
      ['p', e.avisoContratante],
      ['p', `**CONTRATADA:** ${qualificacao(contrato, d)}.`],
      ['p', 'À Contratada;'],
      ['pp', 'Pelo presente instrumento particular, comunicamos que, a partir dessa data a CONTRATANTE distrata com a ' +
        'CONTRATADA a relação de representação comercial existente entre as partes.'],
      ['pp', 'Com o devido distrato, as partes desobrigam-se das previsões determinadas no contrato de representação ' +
        'comercial.'],
      ['pp', 'Em havendo valores a serem acertados, esses deverão ser acertados no momento do distrato.'],
      ['pp', 'A contratada deverá devolver os materiais de trabalho de propriedade da CONTRATANTE para o Gerente de ' +
        'negócios da empresa.'],
      ['dataLivre', `Santa Maria, ${c('dataAviso')}.`, { recuo: true }],
      ...(e.assinaturasLado ? [['assLado', [contratada, contratante]]] : [['assPilha', contratada], ['assPilha', contratante]]),
    ];
  }

  /**
   * Monta os documentos escolhidos para a empresa representada.
   * Retorna [{ id, nome, cabecalho, fonte: 'distrato', blocos }].
   */
  function montar(contrato, distrato, resultado) {
    const d = distrato || {};
    const e = EMPRESAS[d.representada] || EMPRESAS.cia;
    const r = resultado || K.calcular(d, {});
    const escolhidos = Array.isArray(d.documentos) && d.documentos.length ? d.documentos : DOCUMENTOS.map((x) => x.id);
    const out = [];
    if (escolhidos.includes('distrato')) {
      out.push({ id: 'distrato', nome: `Termo de distrato — ${e.nome}`, cabecalho: e.logo ? 'antoniazzi' : 'nenhum',
        fonte: 'distrato', blocos: distratoBlocos(e, contrato, d, r) });
    }
    if (escolhidos.includes('aviso')) {
      out.push({ id: 'aviso', nome: `Aviso prévio — ${e.nome}`, cabecalho: 'nenhum', fonte: 'distrato', blocos: avisoBlocos(e, contrato, d) });
    }
    return out;
  }

  function nomeArquivo(contrato, distrato, ext) {
    const base = String((contrato && contrato.razao) || 'representante')
      .normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^\w]+/g, '_').replace(/^_|_$/g, '').slice(0, 50);
    const emp = distrato && distrato.representada === 'alimentos' ? 'Antoniazzi_Alimentos' : 'Antoniazzi_Cia';
    return `Distrato_${emp}_${base}.${ext}`;
  }

  return { EMPRESAS, DOCUMENTOS, valores, montar, nomeArquivo, qualificacao };
});
