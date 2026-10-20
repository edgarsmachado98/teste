# CORE RH

Um só lugar para as rotinas do departamento pessoal. Cadastre colaboradores e setores, monte escalas
de trabalho que respeitam a CLT, acompanhe o custo de cada funcionário com encargos e provisões, e
administre os contratos de representantes comerciais do início ao distrato.

O sistema roda em um **servidor com banco de dados** (SQLite): várias pessoas acessam pelo navegador,
cada uma com seu login e perfil, e todas as alterações ficam registradas no histórico.

## Módulos

| Módulo | Situação | O que faz |
|--------|----------|-----------|
| Cadastros | Disponível | Colaboradores (nome, matrícula, sexo, setor, jornada e horário) e setores. Base de todos os módulos |
| Escalas de trabalho | Disponível | Gera escalas 6x1, 5x2 e 12x36 com rodízio de domingos, feriados e validação legal |
| Custos de pessoal | Disponível | Folha mensal com encargos, provisões e benefícios, e 12 relatórios de custos, benefícios, turnover e produtividade |
| Contratos de representantes | Disponível | Contratos de representação comercial (Lei 4.886/1965) no modelo da empresa, em PDF e Word |
| Distratos | Disponível | Cálculo do distrato com correção pelo IGP-M e termo de distrato e aviso prévio em PDF e Word |

## Instalação e execução

Requisito: [Node.js](https://nodejs.org) **22.13 ou mais recente**. Não há dependências para instalar.

```
npm start
```

No Windows, também é possível dar dois cliques em **`iniciar.bat`**: ele confere o Node.js, inicia o
servidor e abre o navegador.

Acesse **http://localhost:3000**. No primeiro acesso o sistema pede para criar o usuário administrador.

### Configuração (variáveis de ambiente)

| Variável | Padrão | Para que serve |
|----------|--------|----------------|
| `PORT` | `3000` | Porta do servidor |
| `HOST` | `127.0.0.1` | Use `0.0.0.0` para liberar o acesso a outros computadores da rede |
| `DB_PATH` | `./dados/escala.db` | Arquivo do banco de dados |
| `COOKIE_SECURE` | — | `1` para exigir HTTPS no cookie de sessão |
| `TRUST_PROXY` | — | `1` quando estiver atrás de um proxy reverso (nginx, Caddy etc.) |

Exemplo para a rede da empresa:

```
HOST=0.0.0.0 PORT=8080 npm start
```

Para uso pela internet, coloque o servidor atrás de um proxy com HTTPS (por exemplo Caddy ou nginx)
e use `COOKIE_SECURE=1 TRUST_PROXY=1`.

### Atualizar para uma versão nova sem perder os dados

Os dados ficam na pasta **`dados`** dentro da pasta do sistema (arquivo `dados/escala.db`). O ZIP de uma
versão nova **não traz** essa pasta, então os dados só se perdem se o ZIP for extraído numa pasta nova e o
sistema for aberto de lá.

Forma recomendada (Windows):

1. Feche a janela preta do servidor.
2. Baixe o ZIP da versão nova (fica em Downloads).
3. Dê dois cliques em **`atualizar.bat`** na pasta do sistema (ou arraste o ZIP sobre ele). Ele faz uma cópia da
   pasta `dados` em `backups-atualizacao`, extrai o ZIP e copia os arquivos novos por cima, **sem tocar em `dados`**.
4. Abra o `iniciar.bat` e confira a versão no menu.

Sem o `atualizar.bat`: extraia o ZIP e copie o **conteúdo** da pasta extraída para dentro da pasta do sistema,
substituindo os arquivos, mas nunca apague nem substitua a pasta `dados`.

Além disso, a cada vez que o servidor inicia é feita uma cópia do banco em `dados/backups` (as 20 mais
recentes ficam guardadas). As mudanças de estrutura do banco das versões novas são aplicadas sozinhas.

### Backup

Todos os dados ficam no arquivo `dados/escala.db`. Faça cópia desse arquivo periodicamente
(com o servidor parado, ou usando `sqlite3 dados/escala.db ".backup copia.db"`).
O administrador também pode exportar e restaurar um backup em JSON pela própria tela.

## Acesso e usuários

| Perfil | Pode fazer |
|--------|-----------|
| Administrador | Tudo: usuários, histórico de alterações, backup/restauração e apagar dados |
| Operador | Cadastrar setores e colaboradores, ajustar regras, gerar/editar escalas, lançar a folha e ver os custos |
| Consulta | Apenas visualizar as escalas (não vê salários, benefícios nem o módulo de custos) |

Segurança:

- Senhas com no mínimo 8 caracteres, com letras e números, guardadas apenas como hash **scrypt** com sal individual.
- Sessão em cookie `HttpOnly` e `SameSite=Strict`, válida por 8 horas; o token é guardado no banco somente como hash.
- 5 senhas erradas bloqueiam o usuário por 5 minutos (o administrador pode desbloquear);
  além disso, cada endereço IP tem limite de 20 tentativas de login a cada 15 minutos.
- Desativar um usuário ou redefinir sua senha encerra imediatamente as sessões abertas dele.
- Todas as permissões são verificadas no servidor; proteção contra CSRF e cabeçalhos de segurança (CSP, X-Frame-Options).
- O sistema exige sempre ao menos um administrador ativo.
- **Histórico de alterações**: quem fez o quê e quando (logins, cadastros, geração e ajustes de escala).

## Custos de pessoal

### Cadastro

Na ficha do colaborador (Cadastros › Colaboradores), em **Contrato e custos**: cargo, salário, admissão,
benefícios (custo mensal da empresa: vale-transporte, refeição, alimentação, plano de saúde, seguro
de vida e outros), férias vencidas e **desligamento** (data, tipo, motivo da entrevista de desligamento e
observação). Quem saiu da empresa deve ser **desligado**, não excluído: sai das próximas escalas e
continua nos relatórios. Colaboradores com lançamentos de folha não podem ser excluídos.

Para preencher salário, cargo e admissão de quem já está cadastrado, use **Importar CSV** com o cabeçalho
`matricula;cargo;salario;admissao` (data em dd/mm/aaaa). Antes de importar, uma caixa de diálogo mostra
quantas matrículas são novas e quantas já existem, e você marca se quer **cadastrar as novas** e/ou
**atualizar as já cadastradas**, escolhendo os campos (cargo, salário, admissão, nome, sexo, setor, jornada,
horário). Células vazias na planilha mantêm o valor atual.

### Integração com o sistema de folha (planilhas)

Os cadastros podem ser alimentados e atualizados direto pelos relatórios exportados do sistema de folha,
em **.xls** (Excel 97-2003), **.xlsx** ou **.csv**, sem conversão:

- **Cadastros › Centros de custo › Importar planilha**: relatório "Centros de Custos" (colunas Código e Nome).
  Centros novos são cadastrados e os existentes têm o nome atualizado.
- **Cadastros › Colaboradores › Importar planilha**: relatório "Empregados em Excel". As colunas são
  reconhecidas pelo cabeçalho: Cód Epr (matrícula), Cód eSocial, Nome, Admissão, Salário, Descrição cargo,
  CBO, Cód/Descrição Ccusto, Cód/Descrição Serviço (estabelecimento), Cód/Descrição Dpto, Cód Sind/Sindicato,
  Data nascimento, Sexo e Possui deficiência. O CPF não é importado.
  - Uma caixa de diálogo mostra quantas matrículas são novas e quantas já existem; marque se quer cadastrar
    as novas e quais dados atualizar nas existentes. Para as novas, o setor das escalas vem do departamento
    (ou do centro de custo, à escolha) e a jornada começa em 6x1, 08:00 — ajuste depois na ficha.
  - Centros de custo citados na planilha são criados automaticamente.
  - Ao final, o sistema lista os colaboradores ativos que **não constam na planilha** (possíveis desligamentos).
- Repita a importação sempre que houver admissões, reajustes ou mudanças de centro de custo: é a forma de
  manter os relatórios atualizados.

Os relatórios podem ser **agrupados por setor, centro de custo, departamento ou estabelecimento**, e o
relatório **Perfil do quadro de pessoal** mostra ativos, sexo, PcD (com a cota da Lei 8.213/1991, art. 93),
aprendizes, salário médio, folha contratual, idade média, faixas etárias e tempo de casa.

### Lançamentos (folha mensal)

1. Escolha o mês e clique em **Abrir competência**: o sistema cria um lançamento para cada colaborador com
   vínculo no mês, já com o salário e os benefícios do cadastro.
2. Informe na grade: horas extras 50% e 100%, horas noturnas, outros adicionais (insalubridade,
   periculosidade, comissões), faltas, atrasos e saídas antecipadas (horas), atestados (dias e motivo),
   banco de horas (crédito e compensação) e benefícios do mês. Enter desce para a linha de baixo.
3. Ou traga da planilha: **Colar da planilha** (copiar e colar do Excel) ou **Importar CSV**. A primeira linha
   é o cabeçalho com a coluna `matricula`; só as colunas reconhecidas são alteradas. **Baixar modelo**
   gera a planilha da competência com os nomes das colunas.
4. Informe também a fatura e os **sinistros** do plano de saúde do mês (relatório da operadora).

### Como o custo é calculado

| Item | Regra |
|------|-------|
| Valor-hora | salário ÷ divisor da jornada (220 para 44h, 200 para 40h, 180 para 36h, 210 para 12x36) |
| Horas extras | 50% e 100% (CF art. 7º, XVI), com reflexo no DSR proporcional a domingos e feriados do mês |
| Adicional noturno | 20% da hora (CLT art. 73) |
| Faltas e atrasos | descontados pelo valor-hora; atestados não descontam |
| Encargos | INSS patronal 20%, RAT × FAP, terceiros 5,8% e FGTS 8% (Simples Nacional: só FGTS) |
| Provisões | férias 1/12 + 1/3 e 13º 1/12, com os mesmos encargos |
| Benefícios | valor informado no lançamento (custo da empresa) |

Os percentuais (regime, RAT, FAP, terceiros) e os limites dos alertas ficam em **Encargos e alertas**.

### Relatórios

Todos com filtro de período e setor, impressão/PDF (A4 paisagem) e exportação CSV.

| Grupo | Relatório | O que mostra |
|-------|-----------|--------------|
| Custos e orçamento | Headcount e massa salarial | evolução do número de colaboradores e da remuneração por setor |
| | Horas extras e adicionais | horas e valores por setor e colaborador, horas extras recorrentes e equivalência em contratações |
| | Provisão de férias e 13º | passivo acumulado na data (avos, férias vencidas e em dobro, encargos) e provisão mês a mês |
| | Custo total por colaborador | salário, variáveis, encargos, provisões e benefícios; custo ÷ salário |
| Benefícios | Sinistralidade do plano de saúde | sinistros ÷ prêmio no mês e acumulado de 12 meses, com faixas de alerta (70% e 75%) |
| | Custo per capita de benefícios | custo de cada benefício por vida ativa e por beneficiário |
| | Absenteísmo por motivo médico | dias de atestado por grupo de motivo e setor; afastamentos acima de 15 dias (INSS) |
| Movimentação | Turnover | admissões, desligamentos e taxa ((admissões + desligamentos) ÷ 2 ÷ headcount médio) |
| | Voluntário e involuntário | pedidos de demissão × dispensas, tempo de casa dos desligados |
| | Motivos de desligamento | motivos da entrevista de desligamento e observações |
| Produtividade | Absenteísmo geral | horas perdidas (faltas, atrasos, atestados) ÷ horas previstas |
| | Banco de horas | saldos por colaborador e passivo se pagos como hora extra |

**Carregar exemplo** traz seis meses de folha fictícia para conhecer os relatórios.

## Contratos de representantes

Gera o pacote de contratação de representante comercial a partir do modelo da empresa
(Antoniazzi & Cia e Antoniazzi Alimentos), preenchendo apenas os dados do **REPRESENTANTE**:

- Empresa: razão social, CNPJ, nome fantasia e endereço;
- Responsável legal: nome, sexo (ajusta “nascido/nascida”, “portador/portadora”…), nacionalidade,
  data de nascimento, RG, CPF e endereço residencial (ou o mesmo da empresa);
- Contrato: zona de influência/clientes (Anexo I) e data.

O pacote contém, à escolha: os dois contratos (cada um com os Anexos I a IV), a Política de Privacidade
Geral, o Termo Aditivo de comissão diferenciada e o Termo de Ciência e Adesão à Política de Privacidade.

- A **prévia** mostra o documento completo com os dados do representante destacados; clicar em um
  deles leva ao campo correspondente.
- **Gerar PDF** abre a impressão do navegador (escolha “Salvar como PDF”), com o cabeçalho do
  representante repetido em todas as páginas.
- **Gerar Word (.docx)** baixa o documento editável, com cabeçalhos, logotipos e numeração de páginas.
- CPF e CNPJ são conferidos pelos dígitos verificadores; o documento só é gerado com todos os dados preenchidos.
- Um contrato pode ser salvo incompleto (rascunho). Não é permitido mais de um contrato **ativo** por CNPJ.
- Gerar, criar, alterar e excluir contratos fica registrado no histórico.

O texto fixo do modelo está em `js/contrato-modelo.js` (cláusulas, anexos e dados das empresas
representadas) — alterações no modelo da empresa devem ser feitas ali.

## Distratos

Calcula o encerramento de um contrato de representação e gera o **Termo de Distrato** e o **Aviso
Prévio** no modelo de cada empresa representada (Antoniazzi & Cia ou Antoniazzi Alimentos).

1. **Representante** — busque pelo CNPJ; os dados vêm do cadastro em *Contratos de representantes*.
2. **Empresa representada** — Antoniazzi & Cia ou Antoniazzi Ind. e Com. de Alimentos.
3. **Datas** — início do contrato (vem do contrato), data do distrato e data do aviso prévio.
4. **Comissões recebidas por mês** — um campo para cada mês de vigência; aceita colar direto da
   planilha (mês e valor, ex.: `abr-24  572,76`).
5. **Comissões sobre títulos pendentes** e **comissões a receber** — período (início e fim) e valor.

### Regras do cálculo (planilha “Cálculo de Comissões”)

| Item | Cálculo |
|------|---------|
| Correção de cada comissão | IGP-M acumulado do mês da comissão até o mês anterior ao do distrato (mesma regra do Cálculo Exato). Se o acumulado for negativo, mantém-se o valor original |
| Indenização — Lei 4.886/65, art. 27, “j” | (comissões atualizadas + a receber + títulos pendentes) ÷ 12 |
| Aviso prévio — art. 34 | soma das comissões atualizadas dos 3 últimos meses com comissão ÷ 3 |
| Total líquido | aviso prévio + indenização + comissões a receber + comissões sobre títulos pendentes |

O total é a soma das parcelas já arredondadas em centavos, para fechar com os valores listados no termo.
O valor por extenso é gerado automaticamente.

### Memória de cálculo

No editor do distrato, **Memória de cálculo** gera o demonstrativo para enviar junto com o distrato:

- **Imprimir / PDF**: página A4 com os dados das partes, a lista das comissões mês a mês (comissão, IGP-M do mês,
  IGP-M acumulado, fator e valor atualizado, com os 3 meses do aviso destacados), as comissões a receber e sobre
  títulos pendentes com os períodos, o cálculo da indenização (1/12), do aviso prévio e o total por extenso.
- **Planilha Excel (.xlsx)**: o mesmo conteúdo, com **fórmulas** no valor atualizado (`ROUND(comissão × fator; 2)`),
  nos totais, na base e na indenização (`base ÷ 12`), na média do aviso e no total — para a conferência de quem recebe.

A geração fica registrada no histórico de alterações.

### IGP-M

A tabela do IGP-M (FGV) é obtida da API pública do Banco Central (SGS, série 189) pelo botão
**Atualizar IGP-M** — o servidor precisa de acesso à internet. Se faltar algum mês (por exemplo, o
índice do mês anterior ainda não divulgado), o sistema avisa e permite informar a variação mensal à mão.
O botão **Conferir no Cálculo Exato** abre o site para conferência.

## Escalas de trabalho

### Como usar

1. **Cadastros › Setores** — nome, mínimo de pessoas por dia, dias de funcionamento e se funciona em feriados.
2. **Cadastros › Colaboradores** — nome, matrícula (única), sexo, setor, jornada e horário de entrada.
   Também é possível importar um CSV:
   ```
   nome;matricula;sexo;setor;jornada;entrada
   Maria Silva;1001;F;Vendas;6x1;08:00
   José Santos;1002;M;Portaria;12x36;19:00
   ```
3. **Escalas de trabalho › Regras e feriados** — escolha a regra de folga dominical masculina (comércio ou demais
   atividades) e cadastre feriados estaduais/municipais. Feriados nacionais são automáticos.
4. **Escalas de trabalho › Escala** — escolha o **centro de custo** (ou *Todos os colaboradores*), o período (até 3 meses)
   e clique em *Gerar escala*. Cada centro de custo tem a sua própria escala salva: gerar a de um centro não altera
   as dos outros, e a lista indica quais já têm escala gerada. Dentro da escala, os colaboradores aparecem por setor,
   com a cobertura mínima de cada um. Clique em qualquer célula para trocar trabalho ↔ folga; a validação é refeita
   na hora. Exporte em CSV (Excel), imprima ou exclua a escala do centro de custo.
   Colaboradores **sem controle de jornada** (CLT art. 62: cargos de gestão, atividade externa ou teletrabalho por
   produção) são marcados na ficha e ficam fora da escala enquanto a caixa *Excluir colaboradores sem controle de
   jornada* estiver marcada; desmarque para incluí-los. A lista de colaboradores tem o filtro *Sem controle de jornada*.

Clique em **Carregar exemplo** para ver o sistema funcionando com dados fictícios (substitui os dados atuais).

### Jornadas disponíveis

| Código   | Jornada                                   | Intervalo        |
|----------|-------------------------------------------|------------------|
| `6x1`    | 7h20/dia, 6 dias por semana (44h)         | 1h               |
| `5x2`    | 8h48/dia, 5 dias (44h, compensa o sábado) | 1h               |
| `5x2-40` | 8h/dia, 5 dias (40h)                      | 1h               |
| `6x1-6h` | 6h/dia, 6 dias (36h)                      | 15 min           |
| `12x36`  | 12h de trabalho por 36h de descanso       | indenizado       |

### Regras legais verificadas

| Regra | Base legal |
|-------|------------|
| Máximo de 8h diárias e 44h semanais | CF art. 7º, XIII; CLT art. 58 |
| Jornada diária até 10h (8h + 2h extras) | CLT art. 59 |
| Repouso semanal de 24h; no máximo 6 dias seguidos de trabalho | CF art. 7º, XV; CLT art. 67; OJ 410 SDI-1 TST |
| 11h de descanso entre jornadas | CLT art. 66 |
| Intervalo intrajornada (1h acima de 6h; 15 min de 4h a 6h) | CLT art. 71 |
| Mulheres: folga em domingo ao menos a cada 15 dias | CLT art. 386 |
| Homens (comércio): folga em domingo ao menos 1 vez a cada 3 semanas | Lei 10.101/2000, art. 6º, par. único |
| Homens (demais atividades): folga em domingo a cada 7 semanas | Portaria MTP 671/2021 |
| 12x36 exige acordo escrito/norma coletiva; plantões não podem ser seguidos | CLT art. 59-A |
| Feriado trabalhado: pagamento em dobro ou folga compensatória | Lei 605/1949, art. 9º; Súmula 146 TST |
| Horas noturnas (22h–5h) calculadas para adicional | CLT art. 73 |
| Compensação de 8h48 exige acordo | CLT art. 59, §§ 2º e 6º; Súmula 85 TST |

Feriados nacionais calculados automaticamente: Confraternização Universal, Sexta-feira da Paixão
(data móvel), Tiradentes, Dia do Trabalho, Independência, N. Sra. Aparecida, Finados,
Proclamação da República, Consciência Negra (Lei 14.759/2023) e Natal. Carnaval e Corpus Christi
podem ser tratados como feriado opcionalmente.

### Preferências da empresa

Em **Escalas de trabalho › Regras e feriados** há duas opções (desligadas por padrão):

- **Folga não coincidir com feriado** — nos setores que funcionam em feriados, a folga semanal é marcada
  em outro dia. Folgas exigidas por lei (como o domingo do rodízio) têm prioridade e podem cair num feriado.
- **Folgas seguidas** — limita os dias seguidos sem trabalho (2, 3 ou 4), somando folgas, feriados e
  fechamentos do setor. Sequências causadas apenas por fechamento do setor não são alteradas.

Quando alguma preferência não puder ser cumprida, a escala mostra um alerta (não é violação legal).

### Como o gerador distribui as folgas

- O rodízio de domingos é montado primeiro, equilibrando quantas pessoas folgam em cada domingo.
- As demais folgas são distribuídas ao longo da semana respeitando o mínimo de pessoas do setor.
- Nenhum colaborador ultrapassa 6 dias seguidos de trabalho; quando necessário, uma folga extra é concedida.
- Na escala 12x36 a equipe é dividida em duas turmas alternadas.
- Se não houver gente suficiente para cumprir a lei e o mínimo do setor ao mesmo tempo, a lei
  prevalece e o sistema mostra um **alerta de cobertura**.

> Limitações: o período é gerado sem considerar a escala anterior (dias trabalhados antes do
> início). Convenções coletivas da categoria podem trazer regras próprias (ex.: folgas em domingos,
> feriados do comércio) — confira com o departamento pessoal/jurídico.

## Estrutura

```
index.html           interface
css/estilo.css       estilos (inclui layout de impressão em A4 paisagem)
js/motor.js          geração, feriados e validação legal (usado no navegador e no servidor)
js/api.js            cliente da API
js/app.js            tela inicial, navegação entre módulos, cadastros e escalas
js/acesso.js         login, primeiro acesso, usuários e histórico
js/contrato-modelo.js  texto do contrato de representante e campos do representante
js/contrato-docx.js  gerador do arquivo Word (.docx), sem dependências
js/contratos.js      tela de contratos: cadastro, prévia, PDF e Word
js/distrato-calculo.js  cálculo do distrato (IGP-M, indenização, aviso prévio, valor por extenso)
js/distrato-modelo.js   termos de distrato e aviso prévio das duas empresas
js/distrato-memoria.js  memória de cálculo do distrato (PDF e planilha .xlsx com fórmulas)
js/distratos.js      tela de distratos
js/documento-html.js prévia, impressão (PDF) e Word compartilhados pelos documentos
js/planilha.js       leitura de planilhas .xls, .xlsx e .csv (sem dependências)
js/custos-calculo.js custo mensal, encargos, provisões e relatórios da folha (navegador e servidor)
js/custos.js         tela de custos: lançamentos, relatórios e parâmetros
js/tema.js           modo claro/escuro
img/                 logotipos usados nos contratos
server/server.js     servidor HTTP, rotas da API, sessão e segurança
server/servico.js    regras de negócio e permissões
server/db.js         banco de dados SQLite (esquema)
server/senhas.js     hash de senhas (scrypt)
tests/               testes automatizados
```

## Testes

```
npm test
```
