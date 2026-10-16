# Gerador de Escala de Trabalho (CLT)

Sistema web para montar escalas de trabalho respeitando a legislação trabalhista brasileira.
Cadastre **setores** e **colaboradores** (nome, matrícula, sexo, setor, jornada e horário de entrada),
gere a escala do período e confira o relatório de conformidade legal.

O sistema tem um **servidor com banco de dados** (SQLite): várias pessoas acessam pelo navegador,
cada uma com seu login, e todas veem os mesmos dados.

## Instalação e execução

Requisito: [Node.js](https://nodejs.org) **22.13 ou mais recente**. Não há dependências para instalar.

```
npm start
```

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

## Como usar

1. **Setores** — nome, mínimo de pessoas por dia, dias de funcionamento e se funciona em feriados.
2. **Colaboradores** — nome, matrícula (única), sexo, setor, jornada e horário de entrada.
   Também é possível importar um CSV:
   ```
   nome;matricula;sexo;setor;jornada;entrada
   Maria Silva;1001;F;Vendas;6x1;08:00
   José Santos;1002;M;Portaria;12x36;19:00
   ```
3. **Regras e feriados** — escolha a regra de folga dominical masculina (comércio ou demais
   atividades) e cadastre feriados estaduais/municipais. Feriados nacionais são automáticos.
4. **Escala** — escolha o período (até 3 meses) e clique em *Gerar escala*. Clique em qualquer
   célula para trocar trabalho ↔ folga; a validação é refeita na hora. Exporte em CSV (Excel) ou imprima.

Clique em **Carregar exemplo** para ver o sistema funcionando com dados fictícios (substitui os dados atuais).

## Jornadas disponíveis

| Código   | Jornada                                   | Intervalo        |
|----------|-------------------------------------------|------------------|
| `6x1`    | 7h20/dia, 6 dias por semana (44h)         | 1h               |
| `5x2`    | 8h48/dia, 5 dias (44h, compensa o sábado) | 1h               |
| `5x2-40` | 8h/dia, 5 dias (40h)                      | 1h               |
| `6x1-6h` | 6h/dia, 6 dias (36h)                      | 15 min           |
| `12x36`  | 12h de trabalho por 36h de descanso       | indenizado       |

## Regras legais verificadas

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
js/app.js            telas de setores, colaboradores, regras e escala
js/acesso.js         login, primeiro acesso, usuários e histórico
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
