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
| Custos de pessoal | Em breve | Custo por funcionário com INSS, FGTS e provisões de férias e 13º salário |
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

### Backup

Todos os dados ficam no arquivo `dados/escala.db`. Faça cópia desse arquivo periodicamente
(com o servidor parado, ou usando `sqlite3 dados/escala.db ".backup copia.db"`).
O administrador também pode exportar e restaurar um backup em JSON pela própria tela.

## Acesso e usuários

| Perfil | Pode fazer |
|--------|-----------|
| Administrador | Tudo: usuários, histórico de alterações, backup/restauração e apagar dados |
| Operador | Cadastrar setores e colaboradores, ajustar regras e gerar/editar escalas |
| Consulta | Apenas visualizar as escalas |

Segurança:

- Senhas com no mínimo 8 caracteres, com letras e números, guardadas apenas como hash **scrypt** com sal individual.
- Sessão em cookie `HttpOnly` e `SameSite=Strict`, válida por 8 horas; o token é guardado no banco somente como hash.
- 5 senhas erradas bloqueiam o usuário por 5 minutos (o administrador pode desbloquear);
  além disso, cada endereço IP tem limite de 20 tentativas de login a cada 15 minutos.
- Desativar um usuário ou redefinir sua senha encerra imediatamente as sessões abertas dele.
- Todas as permissões são verificadas no servidor; proteção contra CSRF e cabeçalhos de segurança (CSP, X-Frame-Options).
- O sistema exige sempre ao menos um administrador ativo.
- **Histórico de alterações**: quem fez o quê e quando (logins, cadastros, geração e ajustes de escala).

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
4. **Escalas de trabalho › Escala** — escolha o período (até 3 meses) e clique em *Gerar escala*. Clique em qualquer
   célula para trocar trabalho ↔ folga; a validação é refeita na hora. Exporte em CSV (Excel) ou imprima.

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
js/distratos.js      tela de distratos
js/documento-html.js prévia, impressão (PDF) e Word compartilhados pelos documentos
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
