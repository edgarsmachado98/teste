/*
 * Modelo do pacote de contrato de representação comercial (Lei 4.886/1965).
 *
 * O texto reproduz o modelo da empresa. Os dados do REPRESENTANTE entram como
 * campos ⟦nome⟧, substituídos pelos valores do formulário. A mesma estrutura
 * gera a prévia na tela, o PDF (impressão) e o arquivo Word (.docx).
 *
 * Marcações no texto: **negrito**, //itálico//, __sublinhado__, {v}vermelho{/v}.
 *
 * Funciona no navegador (window.EscalaContrato) e no Node (module.exports).
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.EscalaContrato = api;
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  // ------------------------------------------------------ empresas representadas

  const SOCIO = 'neste ato representada por seu sócio JOSÉ CELESTINO MONTAGNER ANTONIAZZI, brasileiro, ' +
    'casado, empresário, com inscrição no CPF sob o n.º 303.268.850-72, residente e domiciliado na Rua Vinte de ' +
    'Setembro, 140 – Apto 302, em Santa Maria, RS';

  const REPRESENTADAS = {
    cia: {
      nome: 'ANTONIAZZI & CIA LTDA',
      sede: 'com sede e foro na Rua Aristides Lobo, 290, em Santa Maria, inscrita no CNPJ/MF sob o nº 95.597.647/0001-59',
      assinatura: ['ANTONIAZZI E CIA LTDA', 'CNPJ: 95.597.647/0001-59'],
      cidade: 'Santa Maria/RS',
    },
    alimentos: {
      nome: 'ANTONIAZZI IND E COM DE ALIMENTOS LTDA',
      sede: 'com sede e foro na Rua Castro Alves, 88, Vila Fernandes, Canoas RS, CEP 92114-430, inscrita no ' +
        'CNPJ/MF sob o nº 11.780.083/0001-03',
      assinatura: ['ANTONIAZZI IND E COM', 'DE ALIMENTOS LTDA', 'CNPJ: 11.780.083/0001-03'],
      cidade: 'Canoas/RS',
    },
  };

  // ------------------------------------------------------------------ campos

  const UFS = ['AC', 'AL', 'AP', 'AM', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA', 'MT', 'MS', 'MG', 'PA', 'PB', 'PR',
    'PE', 'PI', 'RJ', 'RN', 'RS', 'RO', 'RR', 'SC', 'SP', 'SE', 'TO'];

  /** Campos do formulário (dados do REPRESENTANTE). */
  const CAMPOS = [
    { id: 'codigo', grupo: 'empresa', rotulo: 'Código do representante', max: 20, dica: 'Opcional; código usado no sistema da empresa' },
    { id: 'razao', grupo: 'empresa', rotulo: 'Razão social', obrig: true, max: 150 },
    { id: 'cnpj', grupo: 'empresa', rotulo: 'CNPJ', obrig: true, tipo: 'cnpj' },
    { id: 'fantasia', grupo: 'empresa', rotulo: 'Nome fantasia', max: 150, dica: 'Em branco, o contrato mostra ***' },
    { id: 'endereco', grupo: 'empresa', rotulo: 'Endereço (rua, número e complemento)', obrig: true, max: 200 },
    { id: 'bairro', grupo: 'empresa', rotulo: 'Bairro', obrig: true, max: 100 },
    { id: 'cidade', grupo: 'empresa', rotulo: 'Cidade', obrig: true, max: 100 },
    { id: 'uf', grupo: 'empresa', rotulo: 'UF', obrig: true, tipo: 'uf' },
    { id: 'cep', grupo: 'empresa', rotulo: 'CEP', obrig: true, tipo: 'cep' },

    { id: 'responsavel', grupo: 'responsavel', rotulo: 'Nome completo', obrig: true, max: 150 },
    { id: 'sexo', grupo: 'responsavel', rotulo: 'Sexo', obrig: true, tipo: 'sexo' },
    { id: 'nacionalidade', grupo: 'responsavel', rotulo: 'Nacionalidade', obrig: true, max: 40 },
    { id: 'nascimento', grupo: 'responsavel', rotulo: 'Data de nascimento', obrig: true, tipo: 'data' },
    { id: 'rg', grupo: 'responsavel', rotulo: 'RG (número)', obrig: true, max: 30 },
    { id: 'rgOrgao', grupo: 'responsavel', rotulo: 'Órgão emissor/UF', obrig: true, max: 20, dica: 'Ex.: SSP/SP' },
    { id: 'cpf', grupo: 'responsavel', rotulo: 'CPF', obrig: true, tipo: 'cpf' },
    { id: 'mesmoEndereco', grupo: 'responsavel', rotulo: 'Reside no endereço da empresa', tipo: 'check' },
    { id: 'resEndereco', grupo: 'residencia', rotulo: 'Endereço residencial (rua, número e complemento)', obrigSe: 'residencia', max: 200 },
    { id: 'resBairro', grupo: 'residencia', rotulo: 'Bairro', obrigSe: 'residencia', max: 100 },
    { id: 'resCidade', grupo: 'residencia', rotulo: 'Cidade', obrigSe: 'residencia', max: 100 },
    { id: 'resUf', grupo: 'residencia', rotulo: 'UF', obrigSe: 'residencia', tipo: 'uf' },
    { id: 'resCep', grupo: 'residencia', rotulo: 'CEP', obrigSe: 'residencia', tipo: 'cep' },

    // só para o cadastro (não aparece no contrato): define o modelo do pacote de documentos
    { id: 'estados', grupo: 'contrato', rotulo: 'Estado de atuação do representante', obrig: true, tipo: 'estados' },
    { id: 'zona', grupo: 'contrato', rotulo: 'Zona de influência/clientes (Anexo I)', obrig: true, tipo: 'texto', max: 2000 },
    { id: 'dataContrato', grupo: 'contrato', rotulo: 'Data do contrato', obrig: true, tipo: 'data' },
  ];

  /** Documentos do pacote, na ordem do modelo. */
  const DOCUMENTOS = [
    { id: 'contratoCia', nome: 'Contrato de representação — Antoniazzi & Cia Ltda (com Anexos I a IV)', regioes: ['sp', 'rssc'] },
    { id: 'contratoAlimentos', nome: 'Contrato de representação — Antoniazzi Ind. e Com. de Alimentos Ltda (com Anexos I a IV)', regioes: ['sp'] },
    { id: 'politica', nome: 'Política de Privacidade Geral', regioes: ['sp', 'rssc'] },
    { id: 'aditivo', nome: 'Termo Aditivo (comissão diferenciada)', regioes: ['sp', 'rssc'] },
    { id: 'termo', nome: 'Termo de Ciência e Adesão à Política de Privacidade', regioes: ['sp', 'rssc'] },
  ];

  /** Estados de atuação possíveis e o modelo de contrato de cada um. */
  const ESTADOS_ATUACAO = [
    { uf: 'RS', nome: 'Rio Grande do Sul' }, { uf: 'SC', nome: 'Santa Catarina' }, { uf: 'SP', nome: 'São Paulo' },
  ];
  const REGIOES = {
    sp: 'Modelo São Paulo (Antoniazzi & Cia e Antoniazzi Alimentos)',
    rssc: 'Modelo Rio Grande do Sul e Santa Catarina (Antoniazzi & Cia)',
  };
  const listaEstados = (v) => String(v || '').split(/[,;\s]+/).map((x) => x.toUpperCase())
    .filter((x, i, a) => ESTADOS_ATUACAO.some((e) => e.uf === x) && a.indexOf(x) === i);

  /** 'sp', 'rssc', 'conflito' (SP junto com RS/SC) ou '' (nenhum estado). */
  function regiao(d) {
    const e = listaEstados(d && d.estados);
    const sul = e.includes('RS') || e.includes('SC');
    if (e.includes('SP') && sul) return 'conflito';
    if (e.includes('SP')) return 'sp';
    return sul ? 'rssc' : '';
  }

  /** Documentos do pacote disponíveis para o estado de atuação (sem estado: os do modelo São Paulo). */
  const documentosDaRegiao = (d) => {
    const r = regiao(d);
    return DOCUMENTOS.filter((x) => x.regioes.includes(r === 'rssc' ? 'rssc' : 'sp'));
  };

  // ------------------------------------------------------------ utilidades

  const soDigitos = (s) => String(s || '').replace(/\D/g, '');

  function validarCPF(cpf) {
    const d = soDigitos(cpf);
    if (d.length !== 11 || /^(\d)\1+$/.test(d)) return false;
    for (const n of [9, 10]) {
      let soma = 0;
      for (let i = 0; i < n; i++) soma += Number(d[i]) * (n + 1 - i);
      const dv = ((soma * 10) % 11) % 10;
      if (dv !== Number(d[n])) return false;
    }
    return true;
  }

  function validarCNPJ(cnpj) {
    const d = soDigitos(cnpj);
    if (d.length !== 14 || /^(\d)\1+$/.test(d)) return false;
    const calc = (n) => {
      const pesos = n === 12 ? [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2] : [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2];
      const soma = pesos.reduce((s, p, i) => s + p * Number(d[i]), 0);
      const r = soma % 11;
      return r < 2 ? 0 : 11 - r;
    };
    return calc(12) === Number(d[12]) && calc(13) === Number(d[13]);
  }

  const formatarCPF = (s) => soDigitos(s).slice(0, 11)
    .replace(/(\d{3})(\d)/, '$1.$2').replace(/(\d{3})(\d)/, '$1.$2').replace(/(\d{3})(\d{1,2})$/, '$1-$2');
  const formatarCNPJ = (s) => soDigitos(s).slice(0, 14)
    .replace(/^(\d{2})(\d)/, '$1.$2').replace(/^(\d{2})\.(\d{3})(\d)/, '$1.$2.$3')
    .replace(/\.(\d{3})(\d)/, '.$1/$2').replace(/(\d{4})(\d{1,2})$/, '$1-$2');
  /** CEP no formato do modelo: 00.000-000 */
  const formatarCEP = (s) => soDigitos(s).slice(0, 8).replace(/^(\d{2})(\d)/, '$1.$2').replace(/\.(\d{3})(\d)/, '.$1-$2');

  const MESES = ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho', 'julho', 'agosto', 'setembro',
    'outubro', 'novembro', 'dezembro'];

  function dataExtenso(iso) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(String(iso || ''))) return '';
    const [a, m, d] = iso.split('-');
    return `${d} de ${MESES[Number(m) - 1]} de ${a}`;
  }

  const dataBR = (iso) => (/^\d{4}-\d{2}-\d{2}$/.test(String(iso || '')) ? iso.split('-').reverse().join('/') : '');

  const enderecoCompleto = (end, bairro, cidade, uf, cep) => {
    if (!end && !bairro && !cidade) return '';
    return `${end}, BAIRRO ${bairro}, ${cidade}-${uf}, CEP ${formatarCEP(cep)}`.toUpperCase();
  };

  /** Valores exibidos no documento para cada campo ⟦nome⟧. Vazio = campo não preenchido. */
  function valores(d) {
    d = d || {};
    const t = (v) => String(v == null ? '' : v).trim();
    const endEmpresa = enderecoCompleto(t(d.endereco), t(d.bairro), t(d.cidade), t(d.uf), t(d.cep));
    return {
      razao: t(d.razao).toUpperCase(),
      cnpj: t(d.cnpj) ? formatarCNPJ(d.cnpj) : '',
      fantasia: t(d.fantasia) ? t(d.fantasia).toUpperCase() : '***',
      endEmpresa,
      responsavel: t(d.responsavel).toUpperCase(),
      nacionalidade: t(d.nacionalidade).toLowerCase(),
      nascimento: dataBR(d.nascimento),
      rg: t(d.rg) ? `${t(d.rg)} ${t(d.rgOrgao).toUpperCase()}`.trim() : '',
      cpf: t(d.cpf) ? formatarCPF(d.cpf) : '',
      endResidencial: d.mesmoEndereco !== false ? endEmpresa
        : enderecoCompleto(t(d.resEndereco), t(d.resBairro), t(d.resCidade), t(d.resUf), t(d.resCep)),
      zona: t(d.zona).toUpperCase(),
      data: dataExtenso(d.dataContrato),
    };
  }

  /** Campo do formulário a destacar quando o usuário clica num valor do documento. */
  const ALVO = {
    endEmpresa: 'endereco', endResidencial: 'resEndereco', rg: 'rg', data: 'dataContrato',
  };

  /** Rótulos mostrados no documento quando o campo está vazio. */
  const VAZIO = {
    razao: 'razão social', cnpj: 'CNPJ', endEmpresa: 'endereço da empresa', responsavel: 'nome do responsável',
    nacionalidade: 'nacionalidade', nascimento: 'data de nascimento', rg: 'RG', cpf: 'CPF',
    endResidencial: 'endereço residencial', zona: 'zona de influência', data: 'data do contrato',
  };

  /** Lista de problemas que impedem gerar o documento (campos obrigatórios e dígitos). */
  function pendencias(d) {
    d = d || {};
    const out = [];
    for (const c of CAMPOS) {
      const v = d[c.id];
      const obrig = c.obrig || (c.obrigSe === 'residencia' && d.mesmoEndereco === false);
      if (obrig && (v == null || String(v).trim() === '')) out.push({ campo: c.id, mensagem: `Preencha: ${c.rotulo}.` });
    }
    if (regiao(d) === 'conflito') {
      out.push({ campo: 'estados', mensagem: 'Estado de atuação: São Paulo usa um modelo de contrato e RS/SC usam outro. ' +
        'Marque São Paulo ou Rio Grande do Sul/Santa Catarina (para os dois, cadastre contratos separados).' });
    }
    if (d.cpf && !validarCPF(d.cpf)) out.push({ campo: 'cpf', mensagem: 'CPF inválido (confira os dígitos).' });
    if (d.cnpj && !validarCNPJ(d.cnpj)) out.push({ campo: 'cnpj', mensagem: 'CNPJ inválido (confira os dígitos).' });
    for (const id of ['cep', 'resCep']) {
      if (d[id] && soDigitos(d[id]).length !== 8 && !(id === 'resCep' && d.mesmoEndereco !== false)) {
        out.push({ campo: id, mensagem: 'CEP deve ter 8 dígitos.' });
      }
    }
    for (const id of ['uf', 'resUf']) {
      if (d[id] && !UFS.includes(String(d[id]).toUpperCase()) && !(id === 'resUf' && d.mesmoEndereco !== false)) {
        out.push({ campo: id, mensagem: 'UF inválida.' });
      }
    }
    return out;
  }

  // --------------------------------------------------- texto com marcações

  /**
   * Converte texto com marcações em trechos:
   * [{ texto, b, i, u, v, campo?, vazio? }]
   */
  function trechos(texto, vals) {
    const out = [];
    const est = { b: false, i: false, u: false, v: false };
    const partes = String(texto).split(/(\*\*|\/\/|__|\{v\}|\{\/v\}|⟦[a-zA-Z]+⟧)/);
    for (const p of partes) {
      if (!p) continue;
      if (p === '**') est.b = !est.b;
      else if (p === '//') est.i = !est.i;
      else if (p === '__') est.u = !est.u;
      else if (p === '{v}') est.v = true;
      else if (p === '{/v}') est.v = false;
      else if (p[0] === '⟦') {
        const campo = p.slice(1, -1);
        const valor = vals ? vals[campo] : '';
        out.push({ ...est, campo, texto: valor || `[${VAZIO[campo] || campo}]`, vazio: !valor });
      } else out.push({ ...est, texto: p });
    }
    return out;
  }

  // ------------------------------------------------------------ o modelo

  const c = (nome) => `⟦${nome}⟧`;

  function generos(d) {
    const f = d && d.sexo === 'F';
    return { nascido: f ? 'nascida' : 'nascido', portador: f ? 'portadora' : 'portador', inscrito: f ? 'inscrita' : 'inscrito' };
  }

  /** Qualificação do REPRESENTANTE, igual nos contratos e no aditivo. */
  function qualificacao(g) {
    return `**${c('razao')},** pessoa jurídica de direito privado, de nome fantasia **${c('fantasia')},** ` +
      `estabelecida no endereço ${c('endEmpresa')}, inscrita no CNPJ ${c('cnpj')}, representada neste por ` +
      `**${c('responsavel')},** ${c('nacionalidade')}, ${g.nascido} em ${c('nascimento')}, ${g.portador} da cédula ` +
      `de identidade de nº ${c('rg')}, ${g.inscrito} no CPF sob nº ${c('cpf')}, residente ao endereço ` +
      `${c('endResidencial')}, ora denominada simplesmente **REPRESENTANTE**, em conformidade com a Lei nº 4.886/65 ` +
      'e alterações introduzidas pela Lei nº 8.420/92, tem entre si justo e contratado o seguinte:';
  }

  /** Percentuais de comissão do Anexo II conforme o modelo (São Paulo ou RS/SC). */
  function comissoesAnexoII(reg) {
    if (reg === 'rssc') return [['pc', '{v}**2% Vendas de Farinha de Trigo**{/v}']];
    return [
      ['pc', '{v}**1% Clientes especiais – desde que especificadamente citado sua razão social neste anexo ou adendo ' +
        'comercial deste contrato.**{/v}'],
      ['pc', '{v}**2% Padarias Indústrias e Supermercados – e demais clientes desde que saia para entrega da cidade ' +
        'de Santa Maria e/ou Canoas RS**{/v}'],
      ['pc', '{v}**3% Padarias, Indústrias e Supermercados – e demais clientes desde que saia do CD ' +
        '(Guarulhos/SP).**{/v}'],
    ];
  }

  function contrato(rd, g, reg) {
    const R = '**REPRESENTANTE**';
    const D = '**REPRESENTADA**';
    return [
      ['titulo', 'CONTRATO DE REPRESENTAÇÃO COMERCIAL'],
      ['p', `Pelo presente instrumento particular de contrato de representação comercial, que firmam de um lado ` +
        `**${rd.nome}**., pessoa jurídica de direito privado, ${rd.sede}, ${SOCIO}, doravante denominada ${D}, e de ` +
        `outro lado ${qualificacao(g)}`],
      ['n', '1.', `Por força do presente instrumento, a ${R} compromete-se junto a ${D}, a realizar mediações, ` +
        'contratos de intermediação e promoção de negócios mercantis/comerciais, sem exclusividade, de produtos da ' +
        `linha de fabricação e/ou comercialização da **REPRESENTADA.**`],
      ['n', '1.1', `Os produtos objeto da presente representação, bem como as comissões a serem pagas para a ${R}, ` +
        'encontram-se arrolados no **Anexo II - PRODUTOS REPRESENTADOS/COMISSÕES;**'],
      ['n', '1.2', 'A área de atuação e/ou clientes objeto da presente representação, estão especificadas no ' +
        '**Anexo I - ZONA DE INFLUÊNCIA/CLIENTES;**'],
      ['n', '1.3', 'A representação comercial ora pactuada, será regida pelas normas e condições estabelecidas por ' +
        'este instrumento e pelos Anexos I, II e III, sendo que este último disciplina as **CONDIÇÕES GERAIS DE ' +
        'REPRESENTAÇÃO.**'],
      ['n', '2.', 'Este contrato é celebrado sob o caráter da não exclusividade de zona de influência e/ou de ' +
        `clientes, assim como de produtos, não fazendo jus, portanto a ${R} à comissões sobre vendas que não ` +
        'participe diretamente.'],
      ['n', '3.', `Estabelecem as partes que o fato da ${R} atuar em zonas de influência onde não houver outras ` +
        `representantes, não gera para esta o direito à exclusividade. Fica facultado à ${D} o direito de ` +
        'realização de vendas diretas e a atribuição de vendas a outras representantes na zona a que se refere o ' +
        'Anexo I, face o caráter não exclusivo no exercício da representação comercial aqui formalizada.'],
      ['n', '4.', `A ${D}, durante a vigência deste contrato, poderá nomear outra ${R} para atuar na área a que ` +
        'se refere o Anexo I.'],
      ['n', '5.', `Fica reservado à ${R} o direito de exercer atividades para outras empresas ou efetuar negócios ` +
        'em seu nome ou por conta própria, desde que não se trate de produtos e atividades que direta ou ' +
        'indiretamente concorram com a **REPRESENTADA.**'],
      ['n', '6.', `Será devido à ${R}, a título de retribuição, as comissões estipuladas no Anexo II, calculadas ` +
        'sobre o valor líquido das duplicatas ou triplicatas efetivamente quitadas, cujas vendas ocorrerem dentro ' +
        'da área de atuação e/ou clientes a que se refere o Anexo I.'],
      ['n', '6.1', 'As comissões acima referidas serão apuradas observando as condições praticadas, em ' +
        'conformidade com os Anexos II e III.'],
      ['n', '6.2', 'Acordam as partes que serão deduzidas deste valor líquido eventuais abatimentos concedidos.'],
      ['n', '7.', `Nenhuma retribuição será devida à ${R} se: a falta de pagamento resultar da insolvência do ` +
        `comprador; o negócio vier a ser desfeito pelo comprador; for sustada, pela ${D}, a entrega de mercadorias ` +
        'devido à situação comercial do comprador, capaz de comprometer ou tornar duvidosa a liquidação da fatura, ' +
        `a critério da ${D}; o comprador rejeitar ou devolver a mercadoria.`],
      ['n', '8.', `O ${R} e seus prepostos não poderão dar quitação, abatimentos ou descontos, sem prévia ` +
        `autorização por escrito da ${D}.`],
      ['n', '8.1', `Os atos praticados pelos prepostos serão de inteira responsabilidade do ${R}, o qual fica ` +
        'responsável pela indenização/ressarcimento dos prejuízos causados, ainda que sem a participação deste ' +
        'último.', { semNegrito: true }],
      ['n', '9.', `São obrigações da ${R}, dentre outras:`],
      ['n', '9.1', 'Cumprir integralmente as disposições deste instrumento contratual;'],
      ['n', '9.2', `Dedicar-se a Representação Comercial ora contratada, expandindo os negócios da ${D} e ` +
        'promovendo seus produtos e artigos objeto desta REPRESENTAÇÃO COMERCIAL;'],
      ['n', '9.3', `Fornecer à ${D} informações sobre o andamento dos negócios e condições da atuação na zona onde ` +
        'exerce a atividade, sobre a situação dos clientes, do comércio em geral e outras, visando a melhor forma ' +
        'de exercer a representação.'],
      ['n', '9.4', 'Manter sigilo sobre as atividades da Representação;'],
      ['n', '9.5', `Prestar contas à ${D} do produto de suas atividades e dos documentos que esta lhe remeter;`],
      ['n', '9.6', `Não conceder abatimentos, descontos ou dilações sem expressa autorização da ${D};`],
      ['n', '9.7', 'Apresentar os devidos pedidos assinados para o recebimento das comissões;'],
      ['n', '9.8', `Comunicar à ${D} eventuais alterações no quadro societário de sua empresa, por escrito e com ` +
        'aviso de recebimento;'],
      ['n', '9.9', 'Responsabilizar-se por todas as despesas necessárias ao exercício da Representação, tais como, ' +
        'locomoção, hospedagem, telefone, fax, telegrama, telex, correio, alimentação e outras.'],
      ['n', '9.10', 'Zelar pela conservação do mostruário, catálogos, prospectos, listas de preços e outros ' +
        'instrumentos de venda;'],
      ['n', '9.11', 'Pagar todos os tributos, contribuições sociais, encargos trabalhistas e outros encargos ' +
        'indispensáveis ao legal exercício de sua atividade;'],
      ['n', '9.12', 'Manter, na vigência deste contrato, o respectivo registro regular no Conselho Regional de ' +
        'Representantes Comerciais sob pena de, se ocorrer o cancelamento de seu registro, por qualquer razão, este ' +
        'contrato se considerar rescindido. No caso de não ser registrado, o representante fica obrigado a ' +
        'regularizar a situação no período de 06 (seis) meses a contar da assinatura do presente contrato, sob pena ' +
        'de rescisão do presente contrato.'],
      ['n', '9.13', 'Efetuar a colocação das cotas de produtos condensadas no mercado se houver;'],
      ['n', '9.14', 'Apresentar nota fiscal de serviços de sua emissão, para o recebimento das comissões.'],
      ['n', '9.15', 'Apresentar alvará de funcionamento, expedido pela Prefeitura local, atualizado;'],
      ['n', '9.16', 'Apresentar inscrição do INSS da pessoa física responsável pela empresa;'],
      ['n', '10.', `Por força do presente instrumento, a ${D} obriga-se a respeitar os prazos de pagamento das ` +
        'comissões, passar as instruções gerais para auxiliar a comercialização dos produtos relacionados no Anexo ' +
        'II, bem como fornecer listas de preços, prazos e condições de pagamentos e entregas de produtos.'],
      ['n', '11.', `A ${R} não poderá sub-rogar o presente contrato, sem consentimento prévio e por escrito da ` +
        '**REPRESENTADA.**'],
      ['n', '12.', 'Consideram-se, dentre outros, motivos para rescindir por justa causa o presente contrato: o ' +
        'descumprimento de quaisquer das cláusulas contratuais ora pactuadas; a cessão a quem quer que seja da ' +
        'representação ora contratada ou a alteração da composição societária ou administrativa da ' +
        `${R}, sem a anuência da ${D}; a inércia ou a falta de ação da ${R}, resultando a ausência de vendas ` +
        'ou vendas insuficientes frente às possibilidades oferecidas pela área e clientes conferidos a esta; os ' +
        'casos definidos nos artigos 35 e 36 da Lei nº. 4.886/65 e posteriores alterações; a prática por parte da ' +
        `${R} de atos contrários aos interesses da ${D}, tais como, a falta de prestação de contas, a ausência ` +
        'reiterada a consultas formuladas; ou qualquer procedimento que demonstre desleixo ou desinteresse da ' +
        `${R} no exercício da representação.`],
      ['n', '13.', `Ocorrendo motivo justo para a rescisão do presente instrumento, poderá a ${D} reter comissões ` +
        `devidas à ${R}, com o fim de ressarcir-se de danos ou prejuízos por esta causados, a título de compensação.`],
      ['n', '14.', 'Consideram-se motivos para a extinção do presente contrato: a morte do titular efetivo da ' +
        `${R}; ou qualquer forma de alienação de sua participação societária.`],
      ['n', '15.', 'O presente contrato terá prazo indeterminado, sendo, portanto, facultado a qualquer das ' +
        'partes, rescindi-lo em qualquer momento, mediante prévia comunicação por escrito, com antecedência mínima ' +
        'de 30 (trinta) dias.'],
      ['n', '16.', 'Quando a rescisão for imotivada e provocada pela REPRESENTADA, será devido a REPRESENTANTE ' +
        'indenização legal de 1/12 avos sobre as comissões auferidas. A REPRESENTADA terá o prazo de 30 (trinta) ' +
        'dias após formalizada a rescisão para apresentar os cálculos, bem como pagará o representante no prazo de ' +
        '12 (doze) meses.'],
      ['n', '17.', 'Celebram as partes, que os Anexos citados de números I, II e III, constituem partes integrantes ' +
        'do presente contrato de representação, devendo, portanto, serem rigorosamente observados.'],
      ['n', '17.1', 'Os Anexos acima referidos, podem ser, a qualquer tempo, alterados, modificados ou substituídos ' +
        'de comum acordo, sendo que a alteração se dará mediante substituição do Anexo.'],
      ['n', '18.', 'Para dirimir qualquer questão originada pelo presente instrumento, as partes elegem o foro da ' +
        'Comarca de Santa Maria (RS), renunciando a qualquer outro por mais privilegiado que seja.'],
      ['p', 'E, por estarem justos e contratados, firmam o presente em duas vias de igual teor e forma, na presença ' +
        'das testemunhas que também o subscrevem.'],
      ['data', rd.cidade],
      ['ass2', rd, 'abaixo'],

      ['quebra'],
      ['secao', 'ANEXO I - QUADRO DE INFLUÊNCIA/CLIENTES'],
      ['p', 'Fica estipulada a seguinte ZONA DE INFLUÊNCIA/CLIENTES:'],
      ['zona'],
      ['p', 'Para fins de relação de clientes considerar-se-ão aqueles que a REPRESENTADA aprovar por escrito após ' +
        'o envio do pedido e respectivo cadastro dos mesmos. Consideram-se automaticamente excluídos da relação de ' +
        'clientes aqueles que:'],
      ['item', 'Tiverem decretada concordata ou falência;'],
      ['item', 'Forem considerados inativos pela REPRESENTADA, e imediatamente comunicado por escrito a REPRESENTANTE.'],
      ['item', 'As empresas filiadas, subsidiárias, coligadas e controladas pela REPRESENTADA, as quais serão ' +
        'atendidas diretamente pela REPRESENTADA.'],
      ['data', rd.cidade],
      ['ass2', rd, 'linha'],

      ['quebra'],
      ['secao', 'ANEXO II - PRODUTOS REPRESENTADOS/ COMISSÕES'],
      ['pc', 'As comissões serão sempre calculadas sobre o valor líquido das mercadorias vendidas pela ' +
        'REPRESENTANTE, constantes das Notas Fiscais emitidas pela REPRESENTADA, após o recebimento do pagamento das ' +
        'duplicatas e/ou triplicatas.'],
      ['pc', 'As comissões relativas ao pagamento das duplicatas e/ou triplicatas, serão creditadas a REPRESENTANTE ' +
        'conforme as condições seguintes:'],
      ['rotulo', 'PRODUTOS COMISSÃO'],
      ['p', '**O CONTRATADO a título de prestação de serviços, vindo a promover vendas por seu intermédio/indicação, ' +
        'receberá sua contraprestação financeira de modo variável, conforme abaixo descrito:**'],
      ...comissoesAnexoII(reg),
      ['p', '**Clausula1:** A análise do potencial do cliente é feita primeiramente na abertura do mesmo, baseada na ' +
        'análise comercial de compra total do cliente no mês (supervisor de vendas) e pelo departamento financeiro ' +
        'que analisa o serasa do mesmo. Da mesma forma, periodicamente poderá ser reavaliado o cliente pelo setor ' +
        'financeiro, então baseado no histórico de compra do mesmo."'],
      ['pc', '1.1 A comissão será apurada e creditada à REPRESENTANTE até o dia 05 do mês subsequente ao do ' +
        'pagamento da mercadoria pelo cliente.'],
      ['pc', '2. Produtos novos e produtos especiais, cujo agenciamento de vendas será repassado para a ' +
        'REPRESENTANTE a critério da REPRESENTADA, terão comissão e condições de venda definidas em alteração ' +
        'contratual própria.'],
      ['pc', '3. Nos casos em que houver a concessão de descontos nos títulos em cobrança, além ou diferentes dos ' +
        'determinados nas circulares e instruções de vendas, a comissão incidirá sobre o valor efetivamente recebido ' +
        'pela REPRESENTADA.'],
      ['pc', '4. A comissão deixará de ser creditada a REPRESENTANTE nos seguintes casos:'],
      ['pc', 'I - Se o cliente desfizer o negócio ou cancelar o pedido;'],
      ['pc', 'II- Se a REPRESENTADA recusar o pedido;'],
      ['pc', 'III- Se o cliente se tornar insolvente ou for sustada a entrega da mercadoria por iniciativa da ' +
        'REPRESENTADA, quando esta julgar duvidosa a liquidação;'],
      ['pc', '5. A comissão que o REPRESENTANTE já tenha movimentado e venha a ser indevida pelos motivos retros ' +
        'apontados, ou outros que justifiquem, será debitada em conta corrente da mesma;'],
      ['pc', '6. A comissão relativa a créditos da REPRESENTADA junto a clientes concordatários será creditada a ' +
        'REPRESENTANTE quando do seu efetivo recebimento.'],
      ['pc', '7. Quando uma representante realizar negócios com clientes em sua matriz e o produto da venda for ' +
        'entregue na filial situada na zona de influência de outra representante, a comissão será creditada a ' +
        'representante que realizou o negócio;'],
      ['pc', '8. Para fechamento de negócios especiais, geralmente de valores elevados, transacionados entre a ' +
        'REPRESENTANTE e o CLIENTE, ou REPRESENTANTE/ REPRESENTADA/CLIENTE, de comum acordo entre REPRESENTADA e ' +
        'REPRESENTANTE, poderão negociar a redução da comissão da REPRESENTANTE, condição esta que deverá constar ' +
        'no neste anexo ou em adendo a este contrato, especificando a razão social do cliente e suas coligadas ou ' +
        'filiais.'],
      ['pc', '9. A REPRESENTANTE renuncia expressamente ao direito as comissões referentes as vendas efetuadas pela ' +
        'REPRESENTADA, as empresas filiadas, coligadas e controladas da REPRESENTADA, bem como nas revendas ' +
        'efetuadas por essas empresas a clientes e consumidores em geral, situados na área de atuação da ' +
        'REPRESENTANTE.'],
      ['pc', '10. Inobstante, o previsto na Legislação da Representação Comercial, as partes, tendo em vista as ' +
        'características dos produtos transacionados, acordam que em caso de rescisão contratual, sem justa causa, ' +
        'de iniciativa da REPRESENTADA, as comissões relativas a pedidos já extraídos pela REPRESENTANTE receberão ' +
        'o seguinte tratamento:'],
      ['pc', 'a. As comissões referentes aos pedidos já faturados e pagas pelo cliente serão pagas no ato da rescisão;'],
      ['pc', 'b. As comissões referentes a pedidos a serem faturados, serão pagas quando da respectiva liquidação ' +
        'pelo cliente.'],
      ['p', '11. Compromete-se a Representante, quando solicitada, auxiliar a Representada na cobrança de valores ' +
        'e/ou juros e outras taxas resultante de vendas que agenciar, sem que isto lhe dê direito a qualquer ' +
        'remuneração adicional ou comissão.'],
      ['data', rd.cidade],
      ['ass1'],

      ['quebra'],
      ['secao', 'ANEXO III - CONDIÇÕES GERAIS DE REPRESENTAÇÃO'],
      ['pc', 'Fixam-se a seguir as normas básicas que deverão ser observadas pela REPRESENTANTE:'],
      ['pc', '1. RETORNO DE CAPITAIS'],
      ['pc', 'Em razão das circunstâncias econômicas atuais, deverá ser reduzido o índice de atraso de retorno de ' +
        'capitais, tendo-se como política em vigor, não atender clientes que ultrapassem os atrasos permitidos.'],
      ['p', 'A redução do prazo de retorno de capitais da REPRESENTADA deverá constituir-se em uma constante ' +
        'preocupação da REPRESENTANTE.'],
      ['pc', '2. CADASTRAMENTO DE CLIENTES'],
      ['pc', 'a) Clientes novos deverão preencher ficha cadastral, nos moldes de formulários da REPRESENTADA, ' +
        'incluindo informações adicionais tais como bancárias e pessoais dos clientes, a critério da REPRESENTADA.'],
      ['pc', 'b) Os cadastros serão apreciados pela REPRESENTADA, que fará suas análises e consultas, sendo que após ' +
        'a aprovação cadastral é que serão atendidos os pedidos formulados;'],
      ['pc', 'c) A REPRESENTADA solicitará periódicas revisões cadastrais, a seu critério, cuja renovação será ' +
        'condicional para aceitação de novos fornecimentos aos clientes;'],
      ['pc', 'd) A REPRESENTANTE se responsabilizará pelo correto preenchimento das fichas cadastrais, bem como pela ' +
        'veracidade dos dados apresentados;'],
      ['pc', 'e) Em razão do alto volume de vendas, poderá a REPRESENTADA solicitar maiores detalhes para análise ' +
        'cadastral, tais como balanços, balancetes, etc... ;'],
      ['p', 'Poderão também ser solicitadas fianças particulares, fianças bancárias e outras garantias.'],
      ['pc', '3. COBRANÇAS'],
      ['pc', 'a) Poderão ser entregues a REPRESENTANTE os seguintes títulos/documentos:'],
      ['pc', '- duplicatas'],
      ['pc', '- instrumento de protesto;'],
      ['pc', '- cheques devolvidos pelo banco'],
      ['pc', '- recibos de despesas financeiras'],
      ['pc', 'b) A REPRESENTANTE poderá efetuar cobranças em nome da REPRESENTADA mediante prévia autorização, ' +
        'devendo os valores serem recebidos em cheques nominais e cruzados a REPRESENTADA. Todos os valores ' +
        'recebidos deverão ser remetidos a REPRESENTADA até 48 horas, contados do recebimento pela REPRESENTANTE;'],
      ['p', 'c) Salvo autorização expressa, não poderá a REPRESENTANTE conceder abatimentos, descontos ou dilatações ' +
        'nos títulos em cobrança, emitidos pela REPRESENTADA.'],
      ['p', '4. A REPRESENTANTE se diz empresa legalmente constituída e civilmente responsável por seus atos, ' +
        'responsabilizando-se também por todas as obrigações fiscais, tributárias, previdenciárias e trabalhistas ' +
        'de si e de seus empregados ou prepostos, dos quais também se diz responsável por atos danosos praticados ' +
        'contra a REPRESENTADA ou terceiros.'],
      ['pc', '5. PRAZOS DE PAGAMENTOS'],
      ['p', 'a) Os prazos de pagamento serão estabelecidos em circular própria, e deverão ser rigorosamente observados.'],
      ['p', 'b) Os custos das despesas financeiras decorrentes da não observância da circular vigente, pela ' +
        'REPRESENTANTE, serão debitadas na conta corrente da REPRESENTANTE.'],
      ['p', '6. A REPRESENTANTE se compromete a visitar periodicamente, de 15 em 15 dias, sem exceções, os clientes ' +
        'de sua área de atuação, levando ao conhecimento da REPRESENTADA o que se oferecer a respeito de cada um ou uma.'],
      ['data', rd.cidade],
      ['ass2', rd, 'linha'],

      ['quebra'],
      ['secao', 'ANEXO IV – POLÍTICA DE PRIVACIDADE'],
      ['p', 'As Partes declaram e concordam, de maneira livre, informada e inequívoca, que os dados pessoais gerais e ' +
        'os dados pessoais sensíveis compartilhados, disponibilizados, remetidos, pela CONTRATANTE para a CONTRATADA ' +
        'devem ser coletados, armazenados, tratados e utilizados somente para as finalidades pertinentes ao CONTRATO ' +
        'e legalmente previstas/autorizadas, em cumprimento à legislação vigente, principalmente a Lei 13.709/2018.'],
      ['data', rd.cidade],
      ['ass2', rd, 'linha'],
    ];
  }

  /** Política só da Antoniazzi & Cia (modelo RS/SC): tira a Antoniazzi Alimentos do texto. */
  const SO_CIA = [
    [/, em Santa Maria\/RS, e a \*\*ANTONIAZZI INDÚSTRIA E COMÉRCIO DE ALIMENTOS LTDA\*\*.*?em Canoas\/RS, disponibilizam/, ', em Santa Maria/RS, disponibiliza'],
    [/ e a ANTONIAZZI INDÚSTRIA E COMÉRCIO DE ALIMENTOS LTDA poderão/g, ' poderá'],
    [/, da ANTONIAZZI INDÚSTRIA E COMÉRCIO DE ALIMENTOS LTDA e do/g, ' e do'],
    [/ (e|ou) (da|pela) ANTONIAZZI INDÚSTRIA E COMÉRCIO DE ALIMENTOS LTDA/g, ''],
  ];
  const soCia = (t) => SO_CIA.reduce((x, [de, para]) => x.replace(de, para), t);

  function politica(reg) {
    const blocos = politicaBlocos();
    if (reg !== 'rssc') return blocos;
    return blocos.map((b) => {
      if (b[0] === 'versoes') return ['versoes', VERSOES.slice(0, 1)];
      if (b[0] === 'assPolitica') return ['assPolitica', [['ANTONIAZZI & CIA LTDA'], ['⟦razao⟧', 'CNPJ: ⟦cnpj⟧', 'Representante: ⟦responsavel⟧']]];
      return b.map((x) => (typeof x === 'string' ? soCia(x) : x));
    });
  }

  function politicaBlocos() {
    return [
      ['tituloCentro', 'POLÍTICA DE PRIVACIDADE GERAL'],
      ['versoes'],
      ["pp", "A **ANTONIAZZI & CIA LTDA** pessoa jurídica de direito privado, inscrita no CNPJ sob o nº 95.597.647/0001-59, com sede na Rua Aristides Lobo, nº 290, CEP 97010-050, no Bairro Rosário, em Santa Maria/RS, e a **ANTONIAZZI INDÚSTRIA E COMÉRCIO DE ALIMENTOS LTDA**, pessoa jurídica de direito privado, inscrita no CNPJ sob o nº 11.780.083/0001-03, com sede na Rua Castro Alves, nº 88, Bairro Vila Fernandes, CEP 92.110-430, em Canoas/RS, disponibilizam a presente **Política de Privacidade Geral.**"],
      ["secaoPol", "1. QUAIS OS OBJETIVOS DESTA POLÍTICA DE PRIVACIDADE GERAL?"],
      ["pp", "Os objetivos da presente Política de Privacidade Geral são:"],
      ["item", "Garantir que você compreenda as razões pelas quais coletamos e utilizamos os seus dados pessoais e de que forma são compartilhados;"],
      ["item", "Explicar a forma na qual utilizamos os seus dados pessoais, com o fim de proporcionar a você uma excelente experiência de uso dos nossos serviços; e"],
      ["item", "Explicar os seus direitos e opções de escolha referentes aos seus dados pessoais que coletamos e processamos e de que forma preservamos sua privacidade."],
      ["pp", "Esta Política de Privacidade demonstra o compromisso da ANTONIAZZI & CIA LTDA e da ANTONIAZZI INDÚSTRIA E COMÉRCIO DE ALIMENTOS LTDA com a privacidade e a proteção dos dados pessoais coletados em razão da prestação de nossos serviços e das relações contratuais estabelecidas."],
      ["secaoPol", "2. QUAIS OS DADOS PESSOAIS QUE COLETAMOS A SEU RESPEITO E COMO NÓS OS COLETAMOS"],
      ["pp", "Coletamos, armazenamos e usamos determinadas categorias de dados pessoais, livre, esclarecida e validamente fornecidos por você, apenas para os propósitos LEGÍTIMOS, ESPECÍFICOS, EXPLÍCITOS E INFORMADOS AO TITULAR, mantendo-os e tratando-os sempre com base legal apropriada na LGPD e em respeito aos princípios da legislação incidente sobre a matéria da proteção de dados pessoais. Dentre os dados pessoais coletados, incluem-se:"],
      ["pp", "**Dados de identificação.** Informações como o nome, sobrenome, data de nascimento, nacionalidade, número de documentos de identificação."],
      ["pp", "**Dados de Contato.** Informações como número de telefone, endereço, e-mail."],
      ["pp", "**Dados Curriculares.** Informações como histórico escolar e profissional, cursos realizados e situação profissional."],
      ["pp", "**Dados de Pagamento:** Informações referentes ao pagamento dos colaboradores, número de identificação bancária."],
      ["pp", "**Dados de Som e Imagem.** Informações como fotografias e vídeos."],
      ["pp", "**Dados Biométricos.** Informações que permitem a identificação individual, única e exclusiva de um indivíduo, como a impressão digital."],
      ["pp", "**Dados de Acesso.** Informações necessárias para dar acesso ao correio eletrônico e ao servidor."],
      ["pp", "**Dados Comerciais.** Histórico de consumo, dados de compra e de utilização de produtos."],
      ["pp", "**Dados de saúde**. Informações de saúde dos colaboradores serão obtidas para fins de cumprimento da legislação, principalmente trabalhista, previdenciária e tributária, em decorrência, por exemplo, da realização de exame admissional, exames periódicos, exame demissional, da coleta e armazenamento de atestados médicos, entre outros. Informações de saúde de colaboradores, prestadores de serviços e clientes poderão ser necessárias para cumprir normas legais e/ou infralegais, como se verifica com a medição de temperatura durante a pandemia de COVID-19 e a coleta de dados de estado de saúde quando uma pessoa sofre algum incidente ou problema de saúde nas instalações da empresa e precisa de atendimento. Informações de saúde também poderão ser coletadas para fins de abonamento de faltas, mediante o recebimento de atestados médicos, odontológicos, etc, sempre respeitando os princípios da necessidade, razoabilidade, e outros incidentes da LGPD."],
      ["pp", "**Dados Pessoais Sensíveis.** Nós sempre buscamos tratar o mínimo possível de dados pessoais sensíveis, como dados de saúde, biométricos, sindicais, religiosos, de filiação política, referentes à vida sexual, e à origem racial/étnica, entre outros. Quando for necessário tratar seus dados pessoais sensíveis, informaremos a finalidade pretendida e nos apoiaremos em base legal legítima prevista na LGPD, inclusive, caso seja exigível, em seu prévio, livre, informado, inequívoco, destacado e expresso consentimento."],
      ["pp", "**Dados Pessoais de crianças e de adolescentes:** Nós buscamos coletar dados de crianças e de adolescentes apenas em situações de absoluta necessidade e com o consentimento expresso de um dos pais ou responsáveis legais. Caso você permita a coleta dos Dados Pessoais do seu filho ou da criança por quem é responsável, será informado de forma clara a respeito de quais dados serão coletados e qual a finalidade da coleta em cada caso específico, sempre respeitando o melhor interesse da criança/adolescente."],
      ["secaoPol", "3. PARA QUAIS FINALIDADES TRATAMOS OS SEUS DADOS PESSOAIS?"],
      ["pp", "Nós tratamos seus dados pessoais, principalmente, para que seja possível viabilizar a nossa relação, cumprir obrigações contratuais e legais, bem como prestar, desenvolver e melhorar nossos serviços e produtos. Dentre as finalidades, incluem-se:."],
      ["pp", "**Gestão Administrativa.** Usamos suas informações pessoais para assegurar a regularidade da empresa, como apoio à tomada de decisão e à melhoria contínua dos processos internos, controle e gestão e utilização de serviços, processamento de pagamentos, apreciação de reclamações, requerimentos e procedimentos similares."],
      ["pp", "**Cumprimento de obrigações legais.** Certas informações pessoais são utilizadas para o cumprimento de obrigações legais, como por exemplo, dados necessários para o cumprimento de obrigações trabalhistas, tributárias, previdenciárias, cíveis, consumeristas, entre outras, tanto com colaboradores, quanto com prestadores de serviços, clientes e outros titulares de dados pessoais."],
      ["pp", "**Cumprimento de obrigações específicas com colaboradores.** Informações pessoais dos colaboradores, tanto sob o regime de CLT quanto sob outros regimes jurídicos (//e. g.//, prestação de serviços), serão coletadas para o atendimento das obrigações derivadas de cada regime jurídico, sejam elas previstas em lei, em contrato, em convenção coletiva, ou em norma regulatória."],
      ["pp", "No regime celetista, os dados pessoais serão utilizados, exemplificativamente, para: (a) viabilizar a assinatura do contrato de trabalho e de todos os procedimentos, processos e atos necessários para formalizá-lo juridicamente e registrá-lo perante os órgãos públicos competentes; (b) possibilitar os procedimentos, processos e controles dos registros inerentes ao vínculo empregatício; (c) possibilitar os procedimentos e atos relativos à execução do contrato de emprego; (d) viabilizar o pagamento da remuneração ajustada e demais obrigações (FGTS, etc); (e) atender solicitações do empregado; (f) fornecer benefícios; (g) contratar seguros, com o devido consentimento, se necessário; (h) remeter dados pessoais a entidade de representação da categoria, com o devido consentimento; (i) possibilitar o cumprimento dos deveres legais e infralegais vinculados à saúde laboral; (j) viabilizar o contato com o empregado, como número telefônico, e-mail, WhatsApp, entre outros."],
      ["pp", "Nos demais regimes jurídicos de contratação de colaboradores, os dados pessoais serão utilizados, exemplificativamente, para: (a) viabilizar a assinatura do contrato e de todos os procedimentos, processos e atos necessários para formalizá-lo juridicamente e, se necessário, registrá-lo perante órgãos públicos competentes; (b) possibilitar os procedimentos, processos e controles dos registros inerentes ao contrato; (c) possibilitar os procedimentos e atos relativos à execução do contrato; (d) viabilizar o pagamento da remuneração ajustada e demais obrigações; (e) atender solicitações do contratado; (f) fornecer benefícios; (g) contratar seguros, com o devido consentimento, se necessário; (h) viabilizar o contato com o contratado, mediante coleta do número telefônico, e-mail, WhatsApp, entre outros."],
      ["pp", "**Prevenção de fraude e riscos de crédito.** Tratamos informações pessoais para impedir e detectar fraude e abuso a fim de proteger a segurança de nossa empresa, de nossos colaboradores e de nossos clientes."],
      ["pp", "**Videovigilância.** Usamos Sistemas de Videovigilância em vários pontos de nossas instalações para zelar pela sua segurança de todos aqueles que se relacionam com a empresa, bem como dos bens que se situam no nosso perímetro."],
      ["pp", "**Comunicações institucionais.** Usamos suas informações para nos comunicarmos com você, para divulgar notícias e atividades ordinárias e extraordinárias desenvolvidas pela nossa empresa, bem como informá-lo sobre ofertas e oportunidades que possam ser de seu interesse."],
      ["pp", "**Eventos e outras iniciativas.** Podemos solicitar, no âmbito de iniciativas promovidas pela empresa, alguns dos seus dados pessoais para efeitos de gestão da organização do evento/palestra e afins."],
      ["pp", "**Captação de fotografias e/ou vídeos.** Usamos seus dados para fins de divulgação e promoção em canais de comunicação internos e externos."],
      ["pp", "**Infraestruturas tecnológicas.** A utilização de infraestruturas tecnológicas da empresa implica o tratamento de dados pessoais necessários para seu funcionamento, bem como para a elaboração de senha e o compartilhamento de dados realizados por meio de correio eletrônico e utilização dos softwares administrativos."],
      ["pp", "**Finalidades para as quais pedimos seu consentimento.** Também podemos pedir o seu consentimento para tratar suas informações pessoais para uma finalidade específica que comunicarmos a você. Quando você concorda com o tratamento de suas informações pessoais para uma finalidade específica, você pode revogar o seu consentimento a qualquer momento e nós encerraremos o tratamento de seus dados para essa finalidade específica. Além disso, importante ressaltar que:"],
      ["pp", "a) Não somos responsáveis pela precisão, veracidade ou falta dela nas informações fornecidas ou pela sua desatualização, quando é de sua responsabilidade prestá-las com exatidão ou atualizá-las."],
      ["pp", "b) Todas as tecnologias utilizadas respeitarão sempre a legislação vigente e os termos desta Política de Privacidade."],
      ["pp", "c) A base de dados formada por meio da coleta feita pela ANTONIAZZI & CIA LTDA e pela ANTONIAZZI INDÚSTRIA E COMÉRCIO DE ALIMENTOS LTDA é de nossa propriedade e responsabilidade, sendo que seu uso, acesso e compartilhamento, quando necessários, serão feitos dentro dos limites, suportes legais e propósitos dos nossos negócios e descritos nesta Política de Privacidade."],
      ["pp", "d) Informações de identificação pessoal não serão vendidas, alugadas ou indevidamente transferidas pela ANTONIAZZI & CIA LTDA e pela ANTONIAZZI INDÚSTRIA E COMÉRCIO DE ALIMENTOS LTDA."],
      ["pp", "e) Você é corresponsável pelo sigilo de seus dados pessoais. O compartilhamento de senhas, //logins, itokens// e dados de acesso viola esta Política de Privacidade."],
      ["pp", "f) O serviço de pós-vendas poderá solicitar informações pessoais relevantes para auxílio na operação e manutenção dos produtos vendidos;"],
      ["pp", "g) Internamente, os dados de que coletamos são acessados somente por profissionais devidamente autorizados, respeitando os princípios de proporcionalidade, necessidade e relevância para os objetivos da prestação dos nossos serviços, além do compromisso de confidencialidade e preservação da privacidade nos termos desta Política de Privacidade."],
      ["pp", "h) O Tratamento dos Dados Pessoais e dos Dados Pessoais Sensíveis é promovido com observância da boa-fé e dos princípios elencados no artigo 6º da Lei nº 13.709/2018."],
      ["pp", "i) O Tratamento dos Dados Pessoais e dos Dados Pessoais Sensíveis é realizado em conformidade com as normas da Lei nº 13.709/2018, em especial os artigos 7º, 8º, 9º, 10, 11, 12, 13, 14, 15 e 16."],
      ["secaoPol", "4. COM QUEM COMPARTILHAMOS SEUS DADOS PESSOAIS?"],
      ["pp", "Durante nosso relacionamento, a ANTONIAZZI & CIA LTDA e a ANTONIAZZI INDÚSTRIA E COMÉRCIO DE ALIMENTOS LTDA poderão realizar o compartilhamento das suas informações com as seguintes entidades:"],
      ["pp", "**Prestadores de serviços.** Empresas externas que nos auxiliam a operacionalizar a gestão da empresa. Nesses casos, somente colaboradores selecionados e devidamente treinados estarão autorizados a acessar seus dados pessoais em nome da ANTONIAZZI & CIA LTDA e da ANTONIAZZI INDÚSTRIA E COMÉRCIO DE ALIMENTOS LTDA, para as tarefas específicas que forem requisitadas a eles, com base em nossas instruções. Além disso, os prestadores com os quais compartilhamos os seus dados pessoais são obrigados a mantê-los confidenciais, seguros e em conformidade com os princípios, regras e obrigações previstas pela LGPD."],
      ["pp", "**Empresas parceiras comerciais da ANTONIAZZI & CIA LTDA e da ANTONIAZZI INDÚSTRIA E COMÉRCIO DE ALIMENTOS LTDA.** Compartilharemos seus dados pessoais com empresas parceiras comerciais, especialmente revendedoras e transportadoras."],
      ["pp", "**Agências de análise de crédito/cobrança de dívidas:** Empresas externas que usamos para nos auxiliarem a verificar a situação do seu crédito."],
      ["pp", "**Autoridades judiciais, administrativas ou governamentais competentes.** Compartilharemos seus dados pessoais sempre que houver determinação legal, requerimento, requisição ou ordem judicial."],
      ["pp", "**Movimentações societárias, como fusão, aquisição e incorporação.** Compartilharemos seus dados pessoais no contexto de uma fusão, aquisição ou incorporação."],
      ["pp", "O compartilhamento de dados ocorrerá, sempre que possível, através de servidores protegidos, por API dos próprios fornecedores, inclusive com perfis de acesso que restringem o nível de informação acessada e mediante criptografia."],
      ["pp", "Portanto, o compartilhamento dos dados ocorrerá a partir de uma integração segura entre o banco de dados da ANTONIAZZI & CIA LTDA, da ANTONIAZZI INDÚSTRIA E COMÉRCIO DE ALIMENTOS LTDA e do nosso fornecedor, bem como com instituições, empresas e pessoas que sigam as diretrizes legais e mercadológicas de segurança da informação."],
      ["secaoPol", "5. QUAIS SÃO OS DIREITOS DOS TITULARES DE DADOS"],
      ["pp", "Garantimos aos titulares dos dados pessoais, o pleno e efetivo exercício dos direitos previstos na Lei 13.709/2018 (LGPD), na medida em que aplicáveis conforme as circunstâncias, tais como:"],
      ["pp", "a) Confirmação da existência de tratamento e o acesso aos dados pessoais que possuímos de você;"],
      ["pp", "b) Correção de dados pessoais incompletos, inexatos ou desatualizados;"],
      ["pp", "c) Anonimização, bloqueio ou eliminação de dados desnecessários, excessivos ou tratados em desconformidade com o disposto nesta Lei;"],
      ["pp", "e) Portabilidade de seus dados pessoais num formato estruturado, de uso corrente e de leitura automática, a outro fornecedor de serviço ou produto, mediante sua solicitação, com fulcro na regulamentação e nos padrões estabelecidos pela ANPD;"],
      ["pp", "f) Eliminação dos dados pessoais tratados com o consentimento do titular, exceto nas hipóteses previstas no art. 16 da Lei Geral de Proteção de Dados Pessoais;"],
      ["pp", "g) Informação das entidades públicas e privadas com as quais o controlador realizou uso compartilhado de dados;"],
      ["pp", "h) Informação sobre a possibilidade de não fornecer consentimento e sobre as consequências da negativa;"],
      ["pp", "i) Revogação do consentimento (nos casos específicos em que os dados pessoais são tratados com base no consentimento do titular)."],
      ["pp", "Outros direitos eventualmente previstos na LGPD e noutros Diplomas Legais também poderão ser exercidos em face da ANTONIAZZI & CIA LTDA e da ANTONIAZZI INDÚSTRIA E COMÉRCIO DE ALIMENTOS LTDA, nos termos da legislação vigente e dessa Política de Privacidade."],
      ["secaoPol", "6. COMO O TITULAR DE DADOS PESSOAIS PODE EXERCER OS SEUS DIREITOS?"],
      ["pp", "Para exercer seus direitos em relação às suas informações pessoais ou se tiver alguma dúvida sobre como usamos suas informações pessoais, entre em contato conosco por meio dos canais de atendimento apontados a seguir:"],
      ["contato", "**CONTATO: através do endereço de e-mail <dpo@moinhosantamaria.com.br>, no qual você será atendido pelo nosso Encarregado pelo Tratamento de Dados Pessoais (//Data Protection Officer; DPO//).**"],
      ["secaoPol", "7. PERÍODO DE USO DOS DADOS PESSOAIS"],
      ["pp", "Os dados pessoais que coletamos poderão ser utilizados pela ANTONIAZZI & CIA LTDA e pela ANTONIAZZI INDÚSTRIA E COMÉRCIO DE ALIMENTOS LTDA:"],
      ["pp", "a) quando realizarmos operações vinculadas às nossas atividades fim, em especial de venda de produtos e eventuais prestações de serviços, que necessitem destes dados pessoais do titular; ou"],
      ["pp", "b) durante prazo estabelecido legalmente ou em normas infralegais; ou"],
      ["pp", "c) dentro do período garantido pelo legítimo interesse da ANTONIAZZI & CIA LTDA e da ANTONIAZZI INDÚSTRIA E COMÉRCIO DE ALIMENTOS LTDA; ou"],
      ["pp", "d) durante o período em que recebeu consentimento para tanto;"],
      ["pp", "e) durante período em que haja outros fundamentos e hipóteses legítimos."],
      ["secaoPol", "8. TRANSFERÊNCIA INTERNACIONAL DOS DADOS PESSOAIS"],
      ["pp", "Podemos realizar a transferência internacional de dados pessoais, em especial para armazenamento em servidores ou bancos de dados estrangeiros, inclusive para backup, e que possuam segurança técnica e jurídica apropriada, respeito às boas práticas e governança, bem como grau de proteção em matéria de dados adequado à da legislação brasileira, tudo nos termos da LGPD, principalmente no seu art. 33, e noutros normativos infralegais aplicáveis."],
      ["secaoPol", "9. MEDIDAS DE SEGURANÇA"],
      ["pp", "Adotamos medidas de segurança, tanto de ordem técnica quanto administrativa, aptas a proteger, dentro do possível e viável, os dados pessoais de acessos não autorizados e de situações acidentais ou ilícitas de destruição, perda, alteração, comunicação ou qualquer forma de tratamento inadequado ou ilícito, em conformidade com as normas da Lei 13.709/2018."],
      ["secaoPol", "10. DISPOSIÇÕES GERAIS"],
      ["pp", "a) Temos o direito de alterar o teor desta Política de Privacidade a qualquer momento, conforme a finalidade ou necessidade, tal qual para adequação e conformidade legal de disposição de lei ou norma que tenha força jurídica equivalente;"],
      ["pp", "b) Ocorrendo atualizações neste documento e que demandem nova coleta de consentimento, serão notificadas por meio dos contatos fornecidos;"],
      ["pp", "c) Em caso de qualquer dúvida com relação às disposições constantes desta Política de Privacidade, você poderá entrar em contato por meio dos canais de atendimento apontados a seguir:"],
      ["contato", "CONTATO: através do endereço de e-mail <dpo@moinhosantamaria.com.br>, no qual você será atendido pelo nosso Encarregado pelo Tratamento de Dados Pessoais (//Data Protection Officer; DPO//)."],
      ["pp", "d) Caso empresas terceirizadas realizem o processamento de quaisquer dados que coletamos, as mesmas deverão respeitar as condições aqui estipuladas e nossas normas de Segurança da Informação, obrigatoriamente."],
      ["pp", "e) Caso alguma disposição desta Política de Privacidade seja considerada ilegal ou ilegítima por autoridade da localidade em que resida ou da sua conexão à Internet, as demais condições permanecerão em pleno vigor e efeito."],
      ["pp", "f) Você reconhece que toda comunicação realizada por e-mail, SMS, aplicativos de comunicação instantânea ou qualquer outra forma digital, virtual e digital também são válidas, eficazes e suficientes para a divulgação de qualquer assunto que se refira aos serviços que prestamos, bem como às condições de sua prestação ou a qualquer outro assunto nele abordado, ressalvadas as disposições expressamente diversas previstas nesta Política de Privacidade."],
      ["secaoPol", "11. FORO E LEGISLAÇÃO APLICÁVEL"],
      ["pp", "A presente Política de Privacidade será regida e interpretada segundo a legislação brasileira, no idioma português, sendo eleito o Foro da Comarca de domicílio da ANTONIAZZI & CIA LTDA ou da ANTONIAZZI INDÚSTRIA E COMÉRCIO DE ALIMENTOS LTDA, para dirimir qualquer litígio ou controvérsia envolvendo a presente Política de Privacidade Geral, renunciando expressamente as partes a qualquer outro por mais privilegiado que seja."],
      ["secaoPol", "12. VIGÊNCIA"],
      ["pp", "A presente Política de Privacidade entra em vigor no dia 19 de agosto de 2021, dando continuidade ao Código de Conduta, Boas Práticas, Segurança e Governança em Matéria de Proteção de Dados Pessoais."],
      ["secaoPol", "13. COMO ENTRAR EM CONTATO CONOSTO"],
      ["pp", "//**Para dúvidas, sugestões ou solicitações que envolvam este documento, entre em contato com o nosso DPO (Data Protection Officer) através do endereço de e-mail: <dpo@moinhosantamaria.com.br>.**//"],
      ["secaoPol", "14. GLOSSÁRIO"],
      ["pp", "a) **DADO PESSOAL.** Informação relacionada a pessoa natural identificada ou identificável;"],
      ["pp", "b) **DADO PESSOAL SENSÍVEL**. Dado pessoal sobre origem racial ou étnica, convicção religiosa, opinião política, filiação a sindicato ou a organização de caráter religioso, filosófico ou político, dado referente à saúde ou à vida sexual, dado genético ou biométrico, quando vinculado a uma pessoa natural;"],
      ["pp", "c) **DADO ANONIMIZADO.** Dado relativo a titular que não possa ser identificado, considerando a utilização de meios técnicos razoáveis e disponíveis na ocasião de seu tratamento;"],
      ["pp", "d) **BANCO DE DADOS**. Conjunto estruturado de dados pessoais, estabelecido em um ou em vários locais, em suporte eletrônico ou físico;"],
      ["pp", "e) **TITULAR.** Pessoa natural a quem se referem os dados pessoais que são objeto de tratamento;"],
      ["pp", "f) **CONTROLADOR.** Pessoa natural ou jurídica, de direito público ou privado, a quem competem as decisões referentes ao tratamento de dados pessoais;"],
      ["pp", "g) **OPERADOR.** Pessoa natural ou jurídica, de direito público ou privado, que realiza o tratamento de dados pessoais em nome do controlador;"],
      ["pp", "h) **ENCARREGADO**. Pessoa indicada pelo controlador e operador para atuar como canal de comunicação entre o controlador, os titulares dos dados e a Autoridade Nacional de Proteção de Dados (ANPD);"],
      ["pp", "i) **TRATAMENTO.** Toda operação realizada com dados pessoais, como as que se referem a coleta, produção, recepção, classificação, utilização, acesso, reprodução, transmissão, distribuição, processamento, arquivamento, armazenamento, eliminação, avaliação ou controle da informação, modificação, comunicação, transferência, difusão ou extração;"],
      ["pp", "j) **CONSENTIMENTO.** Manifestação livre, informada e inequívoca pela qual o titular concorda com o tratamento de seus dados pessoais para uma finalidade determinada;"],
      ["pp", "k) **ELIMINAÇÃO.** Exclusão de dado ou de conjunto de dados armazenados em banco de dados, independentemente do procedimento empregado;"],
      ["pp", "l) **USO COMPARTILHADO DE DADOS.** Comunicação, difusão, transferência internacional, interconexão de dados pessoais ou tratamento compartilhado de bancos de dados pessoais por órgãos e entidades públicos no cumprimento de suas competências legais, ou entre esses e entes privados, reciprocamente, com autorização específica, para uma ou mais modalidades de tratamento permitidas por esses entes públicos, ou entre entes privados;"],
      ["pp", "m) **RELATÓRIO DE IMPACTO À PROTEÇÃO DE DADOS PESSOAIS**. Documentação do controlador que contém a descrição dos processos de tratamento de dados pessoais que podem gerar riscos às liberdades civis e aos direitos fundamentais, bem como medidas, salvaguardas e mecanismos de mitigação de risco;"],
      ["pp", "n) **AUTORIDADE NACIONAL**. Órgão da administração pública responsável por zelar, implementar e fiscalizar o cumprimento desta Lei em todo o território nacional;"],
      ["pp", "o) **VIOLAÇÃO DE DADOS PESSOAIS**. Uma violação da segurança que provoque, de modo acidental ou ilícito, a destruição, a perda, a alteração, a divulgação ou o acesso, não autorizados, a dados pessoais transmitidos, conservados ou sujeitos a qualquer outro tipo de tratamento."],
      ['assPolitica'],
    ];
  }

  function aditivo(g, reg) {
    const rd = REPRESENTADAS.cia;
    return [
      ['titulo', 'TERMO ADITIVO AO CONTRATO DE REPRESENTAÇÃO COMERCIAL', { centro: true }],
      ['p', 'Pelo presente instrumento particular de TERMO ADITIVO AO CONTRATO DE REPRESENTAÇÃO COMERCIAL, de um lado ' +
        `**${rd.nome}**., pessoa jurídica de direito privado, ${rd.sede}, ${SOCIO.replace('neste ato', 'nesta ato')}, ` +
        `doravante denominada **REPRESENTADA**, e de outro lado ${qualificacao(g)}`],
      ['p', '**CONSIDERANDO** que as partes mantêm entre si Contrato de Representação Comercial vigente, regido pela ' +
        'Lei nº 4.886/65 e alterações posteriores e demais legislação aplicável;'],
      ['p', '**CONSIDERANDO** que as partes, de comum acordo, identificaram a necessidade de ajuste pontual e ' +
        'específico na política de comissões aplicável a determinados produtos de alto valor agregado e baixo giro, ' +
        'sem alteração da sistemática geral de apuração e pagamento das comissões já prevista contratualmente;'],
      ['p', 'Resolvem as partes, de comum acordo, firmar o presente **TERMO ADITIVO**, que se regerá pelas cláusulas ' +
        'e condições a seguir:'],
      ['secao', 'CLÁUSULA PRIMEIRA – DO OBJETO'],
      ['n', '1.', 'O presente Termo Aditivo tem por objeto estabelecer comissão diferenciada para determinados ' +
        'produtos específicos, sem prejuízo das demais disposições contratuais vigentes, especialmente quanto à base ' +
        'de cálculo, momento de exigibilidade e demais condições gerais de representação.'],
      ['secao', 'CLÁUSULA SEGUNDA – DOS PRODUTOS COM COMISSÃO DIFERENCIADA'],
      ['n', '2.', 'As disposições ora pactuadas passam a integrar o Anexo II – Produtos Representados/Comissões do ' +
        'Contrato de Representação Comercial, prevalecendo, no que couber e apenas nas alterações especificadas, ' +
        'sobre as condições anteriormente previstas para os produtos aqui abaixo referidos.'],
      ['n', '3.', 'Fica ajustado que os produtos abaixo relacionados passarão a observar comissão diferenciada, nos ' +
        'percentuais e condições estabelecidos neste Termo Aditivo:'],
      ['item', 'Produtos linha varejo – embalagens de 1 kg e misturas especiais: Pizza 1 kg; Multigrãos 1 kg; Maria ' +
        'Inês Sêmola 1 kg; Maria Inês com Fermento 1 kg; Maria Inês Integral 1 kg; Mistura com Fibras 5 kg; Mistura ' +
        'Centeio 5 kg; Mistura Multigrãos 5 kg.'],
      ['item', 'Produtos linha especial: Montagner Pequenas Produções; Mistura Montagner Pequenas Produções.'],
      ['secao', 'CLÁUSULA TERCEIRA – DOS PERCENTUAIS DE COMISSÃO'],
      ['n', '4.', 'Para os produtos descritos na cláusula anterior, ficam estabelecidos os seguintes percentuais de ' +
        'comissão:'],
      ['item', reg === 'rssc'
        ? 'Para representantes com atuação nos Estados do Rio Grande do Sul e Santa Catarina: comissão total de 4% ' +
          '(quatro por cento) sobre o valor líquido efetivamente recebido pela REPRESENTADA.'
        : 'Para representantes com atuação no Estado de São Paulo: comissão total de 5% sobre o valor líquido ' +
          'efetivamente recebido pela REPRESENTADA.'],
      ['item', 'Para os produtos “Montagner Pequenas Produções” e “Mistura Montagner Pequenas Produções”: comissão ' +
        'total de 3% sobre o valor líquido efetivamente recebido, aplicável a todas as regiões.'],
      ['secao', 'CLÁUSULA QUARTA – DA FORMA DE APURAÇÃO E PAGAMENTO COMPLEMENTAR'],
      ['n', '5.', 'As partes ajustam que, para fins operacionais e de compatibilidade com o sistema de comissões ' +
        'atualmente utilizado pela REPRESENTADA, os produtos indicados neste Termo Aditivo serão inicialmente ' +
        'comissionados pelos percentuais ordinários já previstos no contrato principal.'],
      ['n', '6.', 'A diferença entre a comissão ordinária paga e a comissão total prevista neste Termo Aditivo será ' +
        'apurada trimestralmente, mediante levantamento do volume de vendas efetivamente recebidas no período, ' +
        'consideradas eventuais devoluções, cancelamentos ou abatimentos.'],
      ['n', '7.', 'Apurada a diferença, a REPRESENTADA encaminhará ao REPRESENTANTE relatório detalhado das vendas ' +
        'contempladas, para fins de emissão de nota fiscal complementar, correspondente exclusivamente ao valor ' +
        'adicional da comissão devida. Havendo alguma contestação às informações constantes no referido relatório, ' +
        'o REPRESENTANTE terá 5 (cinco) dias para apresentar resposta formal, indicando a ' +
        'contestação/inconsistência. Não havendo contestação, considerar-se-ão aceitas/válidas as informações e ' +
        'valores do relatório.'],
      ['secao', 'CLÁUSULA QUINTA – DA NATUREZA COMPLEMENTAR DO AJUSTE'],
      ['n', '8.', 'O presente Termo Aditivo não altera a base de cálculo das comissões, que permanece vinculada ao ' +
        'efetivo recebimento dos valores pela REPRESENTADA, nem modifica as regras relativas à inadimplência, ' +
        'devoluções, rescisão contratual ou demais condições previstas no contrato original e seus anexos.'],
      ['n', '9.', 'As alterações constantes no presente aditivo, foram previamente discutidas entre as Partes, tendo ' +
        'como objetivo ampliar os ganhos de ambas.'],
      ['secao', 'CLÁUSULA SEXTA – DA RATIFICAÇÃO'],
      ['n', '10.', 'Permanecem inalteradas e integralmente ratificadas todas as demais cláusulas e condições do ' +
        'Contrato de Representação Comercial original e de seus anexos, que não conflitarem com o presente Termo ' +
        'Aditivo.'],
      ['secao', 'CLÁUSULA SÉTIMA – DA VIGÊNCIA'],
      ['n', '11.', 'O presente Termo Aditivo passa a vigorar a partir de sua assinatura pelas partes, aplicando-se às ' +
        'vendas realizadas a partir desta data.'],
      ['n', '12.', 'E, por estarem justas e acordadas, firmam as partes o presente Termo Aditivo em duas vias de igual ' +
        'teor e forma, juntamente com duas testemunhas.'],
      ['data', rd.cidade],
      ['ass2', rd, 'abaixo'],
    ];
  }

  function termo(reg) {
    const empresas = reg === 'rssc' ? 'da empresa __Antoniazzi & Cia Ltda__'
      : 'das empresas __Antoniazzi & Cia Ltda__ e __Antoniazzi Indústria e Comércio de Alimentos Ltda__';
    return [
      ['tituloCentro', '__TERMO DE CIÊNCIA E ADESÃO À POLÍTICA DE PRIVACIDADE GERAL__'],
      ['pt', `Por meio deste Termo, Eu, **__${c('responsavel')}__**, inscrito(a) no CPF sob nº **${c('cpf')}**, ` +
        `declaro que **li, compreendi e me comprometo a cumprir integralmente a Política de Privacidade Geral** ${empresas}. Declaro que fui ` +
        'devidamente orientado sobre as regras, deveres, requisitos e responsabilidades decorrentes da Lei nº 13.709, ' +
        'de 14 de agosto de 2018, Lei Geral de Proteção de Dados Pessoais – LGPD, sobre as operações de coleta, ' +
        'armazenamento, compartilhamento e tratamento em geral de dados pessoais a que tiver acesso, bem como ' +
        'respectivas responsabilidades. Declaro que adotarei as medidas de segurança, técnicas e administrativas, ' +
        'necessárias para viabilizar a proteção dos dados pessoais de acessos não autorizados e de situações ' +
        'acidentais ou ilícitas de destruição, perda, alteração, comunicação ou qualquer forma de tratamento ' +
        'inadequado ou ilícito.'],
      ['data', 'Santa Maria/RS'],
      ['assTermo'],
    ];
  }

  /**
   * Monta os documentos escolhidos. Cada documento:
   * { id, nome, cabecalho: 'logo'|'dados'|'nenhum'|'logos', fonte: 'contrato'|'politica', blocos }
   * O tipo de cabeçalho segue o modelo: contratos com o logotipo do Moinho e os dados do
   * representante; política só com os dados; aditivo sem cabeçalho; termo com os dois logotipos.
   */
  function montar(d) {
    d = d || {};
    const g = generos(d);
    // modelo pelo estado de atuação: RS/SC usa o pacote só da Antoniazzi & Cia; os demais casos, o de São Paulo
    const reg = regiao(d) === 'rssc' ? 'rssc' : 'sp';
    const disponiveis = documentosDaRegiao(d);
    const escolhidos = Array.isArray(d.documentos) && d.documentos.length ? d.documentos : disponiveis.map((x) => x.id);
    const todos = {
      contratoCia: { cabecalho: 'logo', fonte: 'contrato', blocos: () => contrato(REPRESENTADAS.cia, g, reg) },
      contratoAlimentos: { cabecalho: 'logo', fonte: 'contrato', blocos: () => contrato(REPRESENTADAS.alimentos, g, reg) },
      politica: { cabecalho: 'dados', fonte: 'politica', blocos: () => politica(reg) },
      aditivo: { cabecalho: 'nenhum', fonte: 'contrato', blocos: () => aditivo(g, reg) },
      // no modelo RS/SC o termo leva só o logotipo do Moinho (sem o da Antoniazzi Alimentos)
      termo: { cabecalho: reg === 'rssc' ? 'logo' : 'logos', fonte: 'termo', blocos: () => termo(reg) },
    };
    return disponiveis.filter((x) => escolhidos.includes(x.id)).map((x) => ({
      id: x.id, nome: x.nome, cabecalho: todos[x.id].cabecalho, fonte: todos[x.id].fonte, blocos: todos[x.id].blocos(),
    }));
  }

  /** Linhas do cabeçalho com os dados do representante (texto com marcações). */
  const CABECALHO = [
    `**RAZÃO SOCIAL: ${c('razao')}**`,
    `**CNPJ: ${c('cnpj')}**`,
    `**NOME FANTASIA: ${c('fantasia')}**`,
    `**Representante: __${c('responsavel')}__**`,
  ];

  const VERSOES = [
    ['31/07/2020', '1.0', 'Conclusão da primeira versão da Política de Privacidade Geral – à época denominada ' +
      '“Código de Conduta, Boas Práticas, Segurança e Governança em Matéria de Proteção de Dados Pessoais.”',
    'Antoniazzi & Cia'],
    ['19/08/2021', '2.0', 'Conclusão da segunda versão da Política de Privacidade Geral',
      'Antoniazzi & Cia e Antoniazzi Alimentos'],
  ];

  /** Nome de arquivo sugerido. */
  function nomeArquivo(d, ext) {
    const base = String((d && (d.razao || d.responsavel)) || 'representante')
      .normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^\w]+/g, '_').replace(/^_|_$/g, '').slice(0, 60);
    return `Contrato_Representante_${base}.${ext}`;
  }

  return {
    REPRESENTADAS, CAMPOS, DOCUMENTOS, ESTADOS_ATUACAO, REGIOES, regiao, documentosDaRegiao, listaEstados, UFS, CABECALHO, VERSOES, ALVO,
    validarCPF, validarCNPJ, formatarCPF, formatarCNPJ, formatarCEP, soDigitos, dataExtenso, dataBR,
    valores, pendencias, trechos, montar, nomeArquivo,
  };
});
