# Sistema de Orçamentos

Orçamentos para infraestrutura de rede, câmeras (CFTV), alarme e equipamentos de TI.
Roda no seu computador; os dados ficam na pasta `data/` (banco SQLite).

## Como iniciar

Precisa do [Python 3.10 ou mais novo](https://www.python.org/downloads/) instalado
(no Windows, marque "Add Python to PATH" na instalação).

- **Windows:** dê dois cliques em `iniciar.bat`.
- **Linux / macOS:** rode `./iniciar.sh`.

Na primeira vez o script instala o que falta. Depois abra <http://127.0.0.1:5000> no navegador.
Para encerrar, feche a janela do terminal.

## O que já faz

- **Orçamentos:** escolha um ou mais tipos; as seções e os itens sugeridos já vêm montados.
- **Proposta ao cliente:** capa, apresentação, escopo, itens por seção, opcionais, resumo,
  condições, o que não está incluso e aceite. Preços item a item, por seção ou só o total.
- **Lista para cotação:** materiais agrupados por categoria, sem preços nem nome do cliente;
  marque os itens ou categorias que vão para cada fornecedor.
- **Catálogo, Clientes e Empresa:** produtos e serviços com custo e margem, cadastro de
  clientes, dados e logotipo da empresa.

Os botões "Exportar PDF" abrem a impressão do navegador: escolha "Salvar como PDF".

## Ainda não faz

Importação de plantas e marcação de equipamentos, mapa de pontos para a equipe de
instalação, registro dos pedidos de cotação enviados e importação das cotações recebidas.

## Cópia de segurança

Copie a pasta `data/` para outro lugar. Ela contém todos os orçamentos e o logotipo.

## Testes

```bash
.venv/bin/python -m pytest
```
