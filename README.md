# Carteira de Aportes

Sistema web para **gerenciar aportes** em investimentos e **analisar o mercado financeiro**.
Feito em Python (Flask + SQLite), com interface em português e gráficos via Chart.js (incluído no projeto, funciona offline).

## Funcionalidades

**Gestão da carteira**
- Cadastro de ativos (ações, FIIs, ETFs, BDRs, renda fixa, cripto, exterior) com **meta de alocação** (%).
- Registro de compras e vendas com taxas; cálculo de **preço médio**, resultado **realizado** e **não realizado**.
- Painel com patrimônio, alocação atual vs. meta, alocação por classe e evolução mensal dos aportes.
- Validação: não permite vender mais do que se possui (nem excluir um aporte que deixaria uma venda descoberta).

**Próximo aporte (rebalanceamento)**
- Informe quanto vai investir e o sistema sugere **quanto comprar de cada ativo** para aproximar a carteira da meta,
  priorizando os ativos mais defasados, respeitando lotes inteiros (ações/FIIs/ETFs/BDRs) e reaproveitando a sobra.

**Análise de mercado**
- Cotações históricas do Yahoo Finance (tickers da B3 recebem `.SA` automaticamente: `PETR4` → `PETR4.SA`), com cache diário.
- Indicadores: médias móveis (20/50/200), bandas de Bollinger, RSI(14), MACD(12,26,9).
- Estatísticas: retornos de 1/3/6/12 meses, volatilidade anualizada, drawdown máximo e índice de Sharpe (taxa livre de risco configurável).
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

### Modo demonstração (sem internet)

Gera cotações **simuladas** e uma carteira de exemplo:

```bash
CARTEIRA_DEMO=1 python seed_demo.py
```

```bash
CARTEIRA_DEMO=1 python app.py
```

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
carteira/db.py         # esquema SQLite
carteira/portfolio.py  # posições, preço médio, resumo e sugestão de aporte
carteira/analysis.py   # indicadores técnicos e estatísticas de risco/retorno
carteira/market.py     # cotações (Yahoo Finance), cache e série simulada
templates/, static/    # interface web
tests/                 # testes automatizados
```

### API

| Método | Rota | Descrição |
|---|---|---|
| GET/POST | `/api/ativos` | lista / cria ou atualiza ativo |
| DELETE | `/api/ativos/<ticker>` | remove ativo sem aportes |
| GET/POST | `/api/aportes` | lista / registra compra ou venda |
| DELETE | `/api/aportes/<id>` | remove aporte |
| GET | `/api/carteira` | resumo da carteira |
| POST | `/api/sugestao` | `{"valor": 1000}` → distribuição sugerida |
| GET | `/api/mercado/<ticker>?dias=252&rf=10` | histórico + indicadores |
| GET | `/api/comparar?tickers=A,B,C&dias=252` | comparação e correlação |
