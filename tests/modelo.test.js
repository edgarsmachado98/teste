const test = require('node:test');
const assert = require('node:assert');
const zlib = require('node:zlib');
const M = require('../js/modelo-preenchido.js');
const DOCX = require('../js/contrato-docx.js');
const P = require('../js/planilha.js');

/** ZIP com compressão deflate, como o Word grava. */
function zipDeflate(arquivos) {
  const partes = [];
  const central = [];
  let pos = 0;
  for (const a of arquivos) {
    const nome = Buffer.from(a.nome);
    const dados = Buffer.from(a.dados);
    const comp = zlib.deflateRawSync(dados);
    const crc = DOCX.crc32(new Uint8Array(dados));
    const loc = Buffer.alloc(30);
    loc.writeUInt32LE(0x04034b50, 0); loc.writeUInt16LE(20, 4); loc.writeUInt16LE(8, 8);
    loc.writeUInt32LE(crc, 14); loc.writeUInt32LE(comp.length, 18); loc.writeUInt32LE(dados.length, 22); loc.writeUInt16LE(nome.length, 26);
    partes.push(loc, nome, comp);
    const cen = Buffer.alloc(46);
    cen.writeUInt32LE(0x02014b50, 0); cen.writeUInt16LE(20, 4); cen.writeUInt16LE(20, 6); cen.writeUInt16LE(8, 10);
    cen.writeUInt32LE(crc, 16); cen.writeUInt32LE(comp.length, 20); cen.writeUInt32LE(dados.length, 24);
    cen.writeUInt16LE(nome.length, 28); cen.writeUInt32LE(pos, 42);
    central.push(cen, nome);
    pos += 30 + nome.length + comp.length;
  }
  const tc = central.reduce((s, b) => s + b.length, 0);
  const fim = Buffer.alloc(22);
  fim.writeUInt32LE(0x06054b50, 0); fim.writeUInt16LE(arquivos.length, 8); fim.writeUInt16LE(arquivos.length, 10);
  fim.writeUInt32LE(tc, 12); fim.writeUInt32LE(pos, 16);
  return new Uint8Array(Buffer.concat([...partes, ...central, fim]));
}

const REP = { razao: 'Rep & Filhos Ltda', cnpj: '29356095000162', responsavel: 'Ana Souza', cpf: '52998224725',
  endereco: 'Rua A, 10', bairro: 'Centro', cidade: 'Lages', uf: 'SC', cep: '88500000', estados: 'SC', dataContrato: '2026-10-21' };
const EMP = { razao: 'Nova Representada Ltda', cnpj: '11.222.333/0001-81', cidade: 'Joinville', uf: 'SC' };

test('modelo Word: marcadores trocados mesmo quando o Word divide o texto', async () => {
  const doc = '<?xml version="1.0"?><w:document xmlns:w="x"><w:body>' +
    '<w:p><w:r><w:t>Contratada: {Razão </w:t></w:r><w:r><w:rPr><w:b/></w:rPr><w:t>social}</w:t></w:r>' +
    '<w:r><w:t xml:space="preserve">, CNPJ {cnpj}, responsável {RESPONSAVEL} (CPF {CPF}).</w:t></w:r></w:p>' +
    '<w:p><w:r><w:t>Atuação: {estado de atuação}. {empresa razão social}, {data do contrato por extenso}. {RG} {xpto}</w:t></w:r></w:p>' +
    '</w:body></w:document>';
  const cab = '<w:hdr xmlns:w="x"><w:p><w:r><w:t>{empresa CNPJ}</w:t></w:r></w:p></w:hdr>';
  const modelo = zipDeflate([
    { nome: '[Content_Types].xml', dados: '<Types/>' }, { nome: 'word/document.xml', dados: doc },
    { nome: 'word/header1.xml', dados: cab }, { nome: 'word/media/a.png', dados: Buffer.from([1, 2, 3]) }]);
  const r = await M.preencher(modelo, REP, EMP);
  const z = await P.lerZip(r.bytes);
  const xml = await z.texto('word/document.xml');
  const texto = xml.replace(/<[^>]+>/g, '');
  assert.match(texto, /Contratada: REP &amp; FILHOS LTDA, CNPJ 29\.356\.095\/0001-62, responsável ANA SOUZA \(CPF 529\.982\.247-25\)\./);
  assert.match(texto, /Atuação: Santa Catarina\. Nova Representada Ltda, 21 de outubro de 2026\. __________ \{xpto\}/);
  assert.match(await z.texto('word/header1.xml'), /11\.222\.333\/0001-81/);
  assert.deepStrictEqual([...(await z.bytes('word/media/a.png'))], [1, 2, 3]);
  assert.deepStrictEqual(r.desconhecidos, ['{xpto}']);
  assert.deepStrictEqual(r.vazios, ['RG']);
  await assert.rejects(M.preencher(new Uint8Array([1, 2, 3]), REP, EMP), /Word \(\.docx\) válido/);
});
