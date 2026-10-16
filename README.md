# Gerador de Escala de Trabalho (CLT)

Sistema web para montar escalas de trabalho respeitando a legislação trabalhista brasileira.
Cadastre **setores** e **colaboradores** (nome, matrícula, sexo, setor, jornada e horário de entrada),
gere a escala do período e confira o relatório de conformidade legal.

Não precisa de servidor nem instalação: basta abrir `index.html` no navegador.
Os dados ficam salvos no próprio navegador (localStorage) e podem ser exportados/importados em JSON.

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

Clique em **Carregar exemplo** para ver o sistema funcionando com dados fictícios.

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
index.html        interface
css/estilo.css    estilos (inclui layout de impressão em A4 paisagem)
js/motor.js       geração, feriados e validação legal (sem dependências; roda no Node também)
js/app.js         telas, cadastro, importação/exportação
tests/            testes automatizados (node --test)
```

## Testes

```
npm test
```
