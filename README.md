# Carteira de Aportes

Sistema web para **gerenciar aportes** em investimentos e **analisar o mercado financeiro**.
Feito em Python (Flask + SQLite), com interface em português e gráficos via Chart.js (incluído no projeto, funciona offline).

## Funcionalidades

**Usuários, carteiras e controle de acesso**
- Login por e-mail e senha. No primeiro acesso o sistema pede para criar o **administrador**; os dados
  já existentes passam a ser da carteira dele.
- Várias carteiras (ex.: *Carteira Edgar Machado* e *Carteira Eliandra*), alternadas pelo seletor no topo.
- Permissões por carteira e por usuário, em *Acessos e conta*:

  | Permissão | O que permite |
  |---|---|
  | Visualizar | ver carteira, aportes, proventos e análises (somente leitura) |
  | Controlar | registrar e excluir aportes, ativos e proventos |
  | Gerenciar acessos | conceder e revogar acessos de outras pessoas à carteira |

  O dono da carteira e os administradores têm acesso total. Administradores também cadastram
  usuários, redefinem senhas e desativam contas.
- Segurança: senhas com hash, sessão em cookie `HttpOnly`/`SameSite`, proteção contra CSRF e
  bloqueio de 5 minutos após 5 tentativas de login erradas.

**Gestão da carteira**
- Cadastro de ativos (ações, FIIs, ETFs, BDRs, renda fixa, cripto, exterior) com **meta de alocação** (%).
- Registro de compras e vendas com taxas; cálculo de **preço médio**, resultado **realizado** e **não realizado**.
- Painel com patrimônio, alocação atual vs. meta, alocação por classe e evolução mensal dos aportes.
- Validação: não permite vender mais do que se possui (nem excluir um aporte que deixaria uma venda descoberta).

**Fluxo financeiro**
- Visão geral de **compras, vendas e proventos recebidos** por período (12 meses, ano, ano anterior,
  desde o início ou datas personalizadas): totais, aporte líquido, lucro realizado nas vendas,
  gráfico mensal, resumo por ativo e extrato unificado com filtro.

**Importação de extratos e relatórios** (Excel .xlsx/.xls, CSV, PDF)
- Além dos extratos da B3, aceita relatórios de posição de bancos e corretoras (ex.: extrato de
  investimentos do Banco do Brasil) em PDF ou Excel: o sistema procura uma tabela com ativo/produto e
  quantidade ou saldo. Fundos, previdência e aplicações informados só pelo saldo entram como 1 unidade.
  Arquivos ".xls" que são HTML (comum em bancos) também são lidos. PDFs escaneados não são suportados.

**Importação de extratos da B3**
- **Patrimônio completo**: envie juntos os extratos de **Posição** + **Negociação** + **Movimentação**.
  O sistema calcula a *posição inicial* de cada ativo (o que você já tinha antes do período dos
  extratos), usa o valor aplicado da B3 como preço médio de Tesouro/renda fixa, sugere a cotação
  da data para os demais (substitua pelo preço médio real), corrige a classe dos ativos pela aba do
  extrato e mostra divergências para conferir.
- Em *Aportes → Importar extrato da B3*, envie os extratos da Área do Investidor em Excel/CSV:
  **Negociação** (compras e vendas de ações, FIIs, ETFs, BDRs), **Eventos** (proventos) e **Movimentação** (dividendos, JCP,
  rendimentos, amortizações e Tesouro Direto). O sistema mostra uma prévia, marca o que já foi lançado
  e importa só o que você selecionar.
- Não são importados: opções/termo/futuros, eventos corporativos (desdobramento, bonificação,
  grupamento, subscrição — ajuste manual) e taxas de corretagem (não constam no extrato).
- Fora da B3 (cadastre manualmente, com preço manual): fundos de investimento não listados,
  previdência (PGBL/VGBL), poupança, criptomoedas e investimentos no exterior.

**Proventos (dividendos, JCP, rendimentos)**
- Busca os proventos por ação/cota nas fontes e calcula **quanto você recebeu** com base na sua quantidade
  na **data com**. JCP é calculado líquido de 15% de IR. Você revisa e importa com um clique (sem duplicar).
- Lançamento manual, histórico, gráfico mensal por tipo, total e média dos últimos 12 meses,
  **yield on cost** e **dividend yield** da carteira e de cada ativo.

**Próximo aporte (rebalanceamento)**
- Informe quanto vai investir e o sistema sugere **quanto comprar de cada ativo** para aproximar a carteira da meta,
  priorizando os ativos mais defasados, respeitando lotes inteiros (ações/FIIs/ETFs/BDRs) e reaproveitando a sobra.

**Análise de mercado**
- Cotações de **várias fontes com fallback automático** (brapi.dev → Dados de Mercado → Yahoo Finance → HG Brasil), com cache diário. Veja [Fontes de cotação](#fontes-de-cotação).
- Indicadores: médias móveis (20/50/200), bandas de Bollinger, RSI(14), MACD(12,26,9).
- Estatísticas: retornos de 1/3/6/12 meses, volatilidade anualizada, drawdown máximo e índice de Sharpe (taxa livre de risco configurável).
- **Fundamentos**: P/L, P/VP, LPA, VPA, ROE, margem líquida, dívida/PL, liquidez corrente, EV/EBITDA e
  valor de mercado (via brapi), dividend yield dos últimos 12 meses e proventos por ação por ano.
- Leitura automática dos sinais (tendência, sobrecompra/sobrevenda, cruzamentos).
- **Comparação** entre ativos: desempenho em base 100, estatísticas e matriz de correlação.

> As leituras de indicadores são educacionais e **não constituem recomendação de investimento**.

## Como executar

```bash
pip install -r requirements.txt
```

```bash
python app.py
```

Acesse http://localhost:5000. O banco fica em `carteira.db` (altere com a variável `CARTEIRA_DB`).

Na primeira vez, a página pede para criar o administrador. Depois, em **Acessos e conta → Usuários**,
cadastre as outras pessoas (marcando "Criar carteira própria" para gerar a carteira delas).

Para que outras pessoas acessem pela rede local (ex.: celular no mesmo Wi-Fi), use
`http://IP-DO-COMPUTADOR:5000`. Não exponha o sistema na internet sem HTTPS.

### Modo demonstração (sem internet)

Gera cotações **simuladas** e duas carteiras de exemplo (Edgar e Eliandra; senha `demo12345`):

```bash
CARTEIRA_DEMO=1 python seed_demo.py
```

```bash
CARTEIRA_DEMO=1 python app.py
```

### Fontes de cotação

O sistema consulta as fontes na ordem definida em `CARTEIRA_FONTES` e usa a primeira que responder.
Se todas falharem, usa o último histórico salvo (marcado como `cache`). Para configurar, copie
`.env.example` para `.env`, preencha os tokens e reinicie o servidor.

| Fonte | Token | Cobertura | Observações |
|---|---|---|---|
| [brapi.dev](https://brapi.dev) | `BRAPI_TOKEN` (opcional) | Cotações, proventos e fundamentos de ações, FIIs, ETFs e BDRs da B3 | Sem token só PETR4, VALE3, MGLU3 e ITUB4. O período do histórico depende do plano: o sistema tenta 2 anos, 1 ano, 6 meses e 3 meses, nessa ordem. |
| [Dados de Mercado](https://www.dadosdemercado.com.br/api/docs) | `DADOSDEMERCADO_TOKEN` | B3 | Ignorada sem token. |
| [Yahoo Finance](https://finance.yahoo.com) | — | Cotações e dividendos de B3, exterior e cripto | Não oficial; pode mudar sem aviso. |
| [HG Brasil](https://hgbrasil.com) | `HGBRASIL_KEY` | B3 | Só cotação atual (atraso de 15 min a 1 h); acrescenta o preço do dia ao histórico salvo. |

Para proventos o Yahoo informa só a data ex (a data com é o dia útil anterior), sem data de pagamento
e sem separar dividendo de JCP; prefira a brapi para ativos da B3. Indicadores fundamentalistas vêm
apenas da brapi (alguns dependem do plano contratado).

A fonte usada aparece em cada análise e o status de todas fica em *Análise de mercado → Fontes de cotação*.
As APIs da B3 (developers.b3.com.br) exigem contrato B2B e não foram integradas.

### Preço manual

Ativos sem cotação online (ex.: Tesouro Direto, CDBs) ou ambientes sem internet podem usar o campo
**Preço manual** em "Ativos e metas"; ele tem prioridade sobre a cotação de mercado.

## Testes

```bash
python -m pytest
```

## Estrutura

```
app.py                 # servidor Flask e API REST
carteira/db.py         # esquema SQLite, migração e conexão por thread
carteira/auth.py       # usuários, carteiras e permissões
carteira/importacao.py # leitura de extratos/relatórios (xlsx, xls, csv, html, pdf)
carteira/portfolio.py  # posições, preço médio, resumo e sugestão de aporte
carteira/analysis.py   # indicadores técnicos e estatísticas de risco/retorno
carteira/market.py     # cotações (Yahoo Finance), cache e série simulada
templates/, static/    # interface web
tests/                 # testes automatizados
```

### API

Todas as rotas `/api` exigem login. As rotas de dados da carteira usam o cabeçalho
`X-Carteira: <id>`; requisições que alteram dados exigem `X-Requested-With: fetch`.

| Método | Rota | Descrição |
|---|---|---|
| POST | `/auth/setup` · `/auth/login` · `/auth/logout` | configuração inicial, entrar, sair |
| GET | `/api/eu` | usuário logado e carteiras acessíveis |
| POST | `/api/eu/senha` | alterar a própria senha |
| GET/POST/PATCH | `/api/usuarios[/<id>]` | usuários (administrador) |
| POST/PATCH/DELETE | `/api/carteiras[/<id>]` | criar, renomear, excluir carteira |
| GET/PUT | `/api/carteiras/<id>/acessos` | listar / conceder ou alterar permissões |
| DELETE | `/api/carteiras/<id>/acessos/<usuario>` | revogar acesso |
| GET/POST | `/api/ativos` | lista / cria ou atualiza ativo |
| DELETE | `/api/ativos/<ticker>` | remove ativo sem aportes |
| GET/POST | `/api/aportes` | lista / registra compra ou venda |
| DELETE | `/api/aportes/<id>` | remove aporte |
| GET | `/api/carteira` | resumo da carteira |
| POST | `/api/sugestao` | `{"valor": 1000}` → distribuição sugerida |
| GET | `/api/mercado/<ticker>?dias=252&rf=10` | histórico + indicadores |
| GET/POST | `/api/proventos` | lista (com resumo) / lança provento |
| DELETE | `/api/proventos/<id>` | remove provento |
| GET | `/api/proventos/estimar` | proventos calculados a partir das fontes |
| POST | `/api/proventos/importar` | `{"itens": [...]}` importa os selecionados |
| GET | `/api/fundamentos/<ticker>` | indicadores, DY e proventos por ano |
| POST | `/api/importar/b3/previa` | envia o extrato (multipart, campo `arquivo`) e recebe a prévia |
| POST | `/api/importar/b3/confirmar` | `{"aportes": [...], "proventos": [...]}` grava os selecionados |
| GET | `/api/fluxo?inicio=&fim=` | compras, vendas e proventos do período |
| GET | `/api/fontes` | fontes de cotação e status |
| GET | `/api/comparar?tickers=A,B,C&dias=252` | comparação e correlação |
