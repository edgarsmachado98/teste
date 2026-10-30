# VigIA – Gestão de Segurança e Comportamento Industrial

Plataforma de gestão de SST que usa visão computacional nas câmeras da planta para detectar
**atos e condições inseguras**: EPI ausente, pessoa em zona de risco, fogo/fumaça e excesso de pessoas.
Cada desvio vira uma **ocorrência** com evidência (foto marcada), passa por triagem e classificação,
gera um **plano de ação** com responsáveis e prazos e alimenta **indicadores** (conformidade de EPI,
desvios por área, turno e horário, mapa de calor) e o **relatório mensal** para CIPA, PGR e auditorias.
Os alertas chegam por **e-mail**, **WhatsApp** e **na tela**, em tempo real.

## Módulos

| Módulo | O que faz |
|---|---|
| **Painel** | Pendências de triagem, conformidade de EPI, desvios do mês, ações atrasadas e câmeras com problema |
| **Ocorrências** | Fluxo nova → em tratamento (ou falso alarme) → encerrada, com classificação (ato inseguro, condição insegura, quase acidente, acidente), observações e histórico completo |
| **Plano de ação** | Ações corretivas/preventivas com responsável e prazo. O responsável recebe e-mail e registra a evidência ao concluir. Uma ocorrência só é encerrada sem ações abertas |
| **Indicadores** | Conformidade de EPI (pessoas observadas × sem EPI), desvios por dia, turno, área, câmera, tipo, classificação e hora, taxa de falso alarme, tempo de triagem, ações no prazo e mapa de calor, com comparação ao período anterior |
| **Relatório** | Relatório em PDF (pelo navegador), com campos para a análise do SESMT e assinaturas |
| **Saúde das câmeras** | Alerta quando a câmera fica sem sinal, escura, obstruída/desfocada ou congelada |
| **Usuários e auditoria** | Perfis de acesso e registro de quem fez o quê, quando e de onde |

### Perfis de acesso

| Perfil | Pode |
|---|---|
| **Operador** | Ver tudo e fazer a triagem (confirmar/falso alarme, classificar); concluir ações atribuídas a ele |
| **Técnico de segurança** | Tudo do operador, mais tratar e encerrar ocorrências, criar ações, câmeras e regras, gerar relatório |
| **Gestor** | Tudo do técnico, mais excluir câmeras |
| **Administrador** | Tudo, mais usuários e auditoria |

## O que detecta (MVP)

| Regra | Exemplo de uso | Modelo necessário |
|---|---|---|
| **EPI ausente** | Pessoa sem capacete, colete, óculos, luvas ou máscara | Modelo de EPI |
| **Zona restrita** | Pessoa perto de prensa, robô, área de empilhadeira | `yolov8n.pt` (padrão) |
| **Fogo / fumaça** | Princípio de incêndio em galpão ou almoxarifado | Modelo de fogo/fumaça |
| **Excesso de pessoas** | Mais de N pessoas em área de risco ou plataforma | `yolov8n.pt` (padrão) |

Cada regra pode ter:
- **Zona** desenhada sobre a imagem da câmera (polígono)
- **Horário** de funcionamento (inclusive turnos que passam da meia-noite)
- **Duração mínima**: só alerta se a situação persistir por X segundos, o que reduz falsos alarmes
- **Intervalo entre alertas**, para não repetir o mesmo alerta
- **Confiança mínima** e **severidade**

## Arquitetura

```
Câmeras IP (RTSP) ─► detector/ (YOLO + motor de regras) ──HTTP──► backend/ (FastAPI)
                         │ uma thread por câmera                     │
                         └─ envia evidência + quadro ao vivo         ├─ PostgreSQL (eventos, regras)
                                                                     ├─ evidências (JPEG)
                                                                     ├─ e-mail (SMTP) / WhatsApp (Meta)
                                                                     └─ painel web + WebSocket (tempo real)
```

- **`backend/`**: API REST, painel web (em `app/static`), WebSocket de alertas, envio de
  notificações e limpeza automática das evidências antigas (LGPD).
- **`detector/`**: lê as câmeras, roda um ou mais modelos YOLO, aplica as regras
  (`vigia_detector/rules.py`) e envia os eventos ao backend. Busca câmeras e regras novas a
  cada 15 s, sem precisar reiniciar.

## Como rodar

### Jeito mais fácil (Windows)

1. Instale o [Python](https://www.python.org/downloads/), marcando **"Add python.exe to PATH"**.
2. Baixe o projeto e dê **dois cliques em `iniciar.bat`**.

Na primeira vez ele instala tudo (alguns minutos), cria o `.env` com uma chave aleatória para o
detector e abre o painel no navegador. **No primeiro acesso, crie o usuário administrador na própria
tela**; depois cadastre os demais usuários em *Usuários*. Servidor e detector rodam juntos na mesma
janela; para encerrar, feche a janela ou pressione Ctrl+C.

No Linux ou Mac, o equivalente é:

```bash
python3 vigia.py
```

### Com Docker (servidor da empresa)

```bash
cp .env.example .env
```

Edite o `.env` (chave do detector, SMTP, WhatsApp, fuso e turnos) e suba os serviços:

```bash
docker compose up -d --build
```

Acesse http://localhost:8000 e crie o administrador. Depois:

1. **Usuários**: cadastre técnicos de segurança, gestores e operadores.
2. **Câmeras**: cadastre a URL RTSP, por exemplo `rtsp://usuario:senha@192.168.0.10:554/stream1`, e a
   **área** de forma padronizada (os indicadores agrupam por ela).
   Para testar sem câmera, coloque um vídeo em `./videos/` e use `videos/teste.mp4` como fonte.
3. **Ao vivo**: confira se o detector está recebendo a imagem.
4. **Regras**: escolha o tipo, desenhe a zona sobre a imagem e salve.
5. **Painel / Ocorrências**: os desvios chegam em tempo real. Faça a triagem, classifique, crie as
   ações e encerre a ocorrência quando as ações forem concluídas.
6. **Indicadores**: acompanhe a evolução e gere o relatório mensal em PDF.

### Dados de demonstração (para apresentar a clientes)

Gera 60 dias de ocorrências, ações e conformidade de EPI realistas, com usuários de exemplo
(`tecnico@demo.com`, `gestor@demo.com`, `operador@demo.com`, senha `demo12345`). **Use um banco
separado** para não misturar com dados reais:

```powershell
cd backend; $env:DATABASE_URL="sqlite:///./data/demo.db"; python -m app.demo --dias 60; uvicorn app.main:app
```

### Desenvolvimento sem Docker

```bash
cd backend && pip install -r requirements.txt && uvicorn app.main:app --reload
```

```bash
cd detector && pip install -r requirements.txt && python -m vigia_detector.main
```

Sem `DATABASE_URL`, o backend usa SQLite em `backend/data/`.

### Windows sem Docker (PowerShell)

Use **Python 3.10 ou superior** ([python.org](https://www.python.org/downloads/)). Se a instalação
falhar em uma versão muito recente do Python, instale também o 3.12 e use `py -3.12` nos comandos.
Os dois serviços leem o `.env` da raiz do projeto.

```powershell
py -3.12 -m venv .venv
```

```powershell
.\.venv\Scripts\Activate.ps1
```

Se o PowerShell bloquear o script, execute antes
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

```powershell
pip install -r backend\requirements.txt -r detector\requirements.txt
```

Terminal 1 (com o ambiente ativado):

```powershell
cd backend; uvicorn app.main:app
```

Terminal 2 (com o ambiente ativado):

```powershell
cd detector; python -m vigia_detector.main
```

### Testes

```bash
cd backend && pytest
```

```bash
cd detector && pytest
```

Os testes do motor de regras não precisam de GPU nem de OpenCV.

## Modelos de IA

O modelo padrão `yolov8n.pt` (COCO) detecta **pessoas** e é baixado automaticamente. Ele já
atende às regras de zona restrita e excesso de pessoas.

Para **EPI** e **fogo/fumaça** é preciso um modelo treinado com essas classes:

1. Use datasets públicos (por exemplo, *Construction Site Safety* ou *Hard Hat Workers* no
   Roboflow Universe) ou, melhor ainda, imagens das suas próprias câmeras.
2. Treine com Ultralytics: `yolo detect train data=epi.yaml model=yolov8s.pt epochs=100`.
3. Copie o `best.pt` para `./modelos/epi.pt` e configure
   `MODEL_PATHS=yolov8n.pt,modelos/epi.pt`.

Os nomes das classes são traduzidos automaticamente (`Hardhat`, `NO-Hardhat`, `Safety Vest`,
`head` e outros: veja `detector/vigia_detector/labels.py`). Para nomes diferentes, use a
variável `LABEL_MAP`.

**Como a regra de EPI decide:** uma pessoa está sem o item se o modelo detectou `no_<item>`
sobre ela, ou se não há detecção do item dentro da caixa da pessoa.

## Alertas

- **Tela**: notificação com som e foto via WebSocket.
- **E-mail**: assunto com severidade, câmera e a foto em anexo (`SMTP_*`, `ALERT_EMAILS`).
- **WhatsApp**: via [WhatsApp Business Cloud API](https://developers.facebook.com/docs/whatsapp/cloud-api).
  - Sem template, envia a foto com legenda. Isso só funciona dentro da janela de 24 h após o
    destinatário enviar uma mensagem ao número.
  - Para produção, crie e aprove na Meta um template com 3 variáveis no corpo, por exemplo
    *"🚨 Alerta VigIA: {{1}} na câmera {{2}} em {{3}}"*, e configure `WHATSAPP_TEMPLATE`.

## LGPD e segurança

- As **imagens** de evidência são apagadas após `RETENTION_DAYS` (padrão: 30 dias). O **registro** da
  ocorrência, sem imagem, fica `EVENT_RETENTION_DAYS` (padrão: 2 anos) para os indicadores históricos.
- Acesso com usuário e senha (senhas com PBKDF2; sessões expiram após `SESSION_HOURS`). O detector usa
  uma chave própria (`DETECTOR_API_KEY`).
- Toda alteração e todo login (inclusive tentativas falhas) ficam na **auditoria**, com IP.
- Os indicadores são por área, turno e câmera, não por pessoa: o foco é o comportamento coletivo.
- As senhas nas URLs RTSP aparecem mascaradas no painel.
- Sinalize as áreas monitoradas e defina uma política interna de uso das imagens.

## Próximos passos sugeridos

- Gravar um clipe de vídeo de alguns segundos antes e depois de cada evento
- Serviço do Windows (iniciar com o computador), HTTPS e backup automático
- Envio automático do relatório mensal por e-mail
- Aprendizado com os "falsos alarmes" para retreinar o modelo
- Rastreamento de pessoas (ByteTrack) para contar violações por pessoa
- Detecção de queda de pessoa e pessoa próxima a empilhadeira em movimento
- Exportação dos indicadores em Excel
- Execução na borda (NVIDIA Jetson) para plantas com pouca internet
