'use strict';
/**
 * Empresas já existentes no sistema, cadastradas na primeira inicialização com os modelos
 * que o CORE RH gera hoje (campos do representante em branco) e os logotipos.
 */
const fs = require('node:fs');
const path = require('node:path');
const C = require('../js/contrato-modelo.js');
const DOCX = require('../js/contrato-docx.js');
const M = require('../js/distrato-modelo.js');
const MEM = require('../js/distrato-memoria.js');

const IMG = path.join(__dirname, '..', 'img');
const bytes = (f) => new Uint8Array(fs.readFileSync(path.join(IMG, f)));

module.exports = function empresasPadrao() {
  const imagens = {
    moinho: { bytes: bytes('logo-moinho.png'), largura: 261, altura: 111 },
    antoniazzi: { bytes: bytes('logo-antoniazzi.png'), largura: 286, altura: 244 },
  };
  const contrato = (estados, documentos) => {
    const d = { estados, documentos };
    return DOCX.gerar(C.montar(d), C.valores(d), imagens);
  };
  const distrato = (representada) => {
    const d = { representada };
    const docs = M.montar({}, d);
    return DOCX.gerar(docs, M.valores({}, d, null), imagens);
  };
  const planilha = () => MEM.tabelaXlsx({
    titulo: 'Comissões para distrato',
    subtitulo: 'Representante:                                   CNPJ:',
    cabecalho: ['Mês', 'Comissão (R$)', 'IGP-M do mês (%)', 'IGP-M acumulado (%)', 'Fator de correção', 'Atualizada (R$)', 'Aviso prévio'],
    linhas: Array.from({ length: 24 }, () => ['', '', '', '', '', '', '']),
    larguras: [14, 16, 16, 18, 16, 16, 12],
    logo: { bytes: bytes('logo-moinho-santa-maria.png'), largura: 170, altura: 198 },
    nomeAba: 'Comissões',
  });

  return [
    {
      razao: 'ANTONIAZZI & CIA LTDA', cnpj: '95.597.647/0001-59', fantasia: 'Moinho Santa Maria',
      endereco: 'Rua Aristides Lobo, 290, Bairro Rosário', cidade: 'Santa Maria', uf: 'RS', cep: '97010-050',
      arquivos: [
        { tipo: 'contrato', nome: 'Contrato_Representante_SP.docx', dados: contrato('SP', ['contratoCia', 'politica', 'aditivo', 'termo']) },
        { tipo: 'contrato', nome: 'Contrato_Representante_RS_SC.docx', dados: contrato('RS') },
        { tipo: 'distrato', nome: 'Distrato_e_Aviso_Antoniazzi_Cia.docx', dados: distrato('cia') },
        { tipo: 'planilha', nome: 'Planilha_Comissoes_Distrato.xlsx', dados: planilha() },
        { tipo: 'logo', nome: 'logo-moinho.png', dados: imagens.moinho.bytes },
      ],
    },
    {
      razao: 'ANTONIAZZI INDÚSTRIA E COMÉRCIO DE ALIMENTOS LTDA', cnpj: '11.780.083/0001-03', fantasia: 'Antoniazzi Alimentos',
      endereco: 'Rua Castro Alves, 88, Vila Fernandes', cidade: 'Canoas', uf: 'RS', cep: '92114-430',
      arquivos: [
        { tipo: 'contrato', nome: 'Contrato_Representante_SP_Antoniazzi_Alimentos.docx', dados: contrato('SP', ['contratoAlimentos', 'politica', 'termo']) },
        { tipo: 'distrato', nome: 'Distrato_e_Aviso_Antoniazzi_Alimentos.docx', dados: distrato('alimentos') },
        { tipo: 'planilha', nome: 'Planilha_Comissoes_Distrato.xlsx', dados: planilha() },
        { tipo: 'logo', nome: 'logo-antoniazzi.png', dados: imagens.antoniazzi.bytes },
      ],
    },
  ];
};
