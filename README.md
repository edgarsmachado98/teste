# VigIA – Monitoramento Industrial com IA

Sistema de monitoramento de câmeras de segurança que usa visão computacional para detectar
**situações de risco na indústria**. Ele salva a evidência (foto marcada) e envia alertas por
**e-mail**, **WhatsApp** e **na tela do sistema** em tempo real.

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

Na primeira vez ele instala tudo (alguns minutos) e cria o `.env` com tokens aleatórios. Depois,
abre o painel no navegador já autenticado. Servidor e detector rodam juntos na mesma janela;
para encerrar, feche a janela ou pressione Ctrl+C.

No Linux ou Mac, o equivalente é:

```bash
python3 vigia.py
```

### Com Docker (servidor da empresa)

```bash
cp .env.example .env
```

Edite o `.env` (tokens, SMTP, WhatsApp) e suba os serviços:

```bash
docker compose up -d --build
```

Acesse http://localhost:8000 e informe o `API_TOKEN` quando for pedido. Depois:

1. **Câmeras**: cadastre a URL RTSP, por exemplo `rtsp://usuario:senha@192.168.0.10:554/stream1`.
   Para testar sem câmera, coloque um vídeo em `./videos/` e use `videos/teste.mp4` como fonte.
2. **Ao vivo**: confira se o detector está recebendo a imagem.
3. **Regras**: escolha o tipo, desenhe a zona sobre a imagem e salve.
4. **Painel**: os alertas chegam em tempo real, com som. Marque cada um como *Confirmar* ou *Falso alarme*.

### Desenvolvimento sem Docker

```bash
cd backend && pip install -r requirements.txt && uvicorn app.main:app --reload
```

```bash
cd detector && pip install -r requirements.txt && python -m vigia_detector.main
```

Sem `DATABASE_URL`, o backend usa SQLite em `backend/data/`.

### Windows sem Docker (PowerShell)

Use **Python 3.12** ([python.org](https://www.python.org/downloads/release/python-3128/)): a
biblioteca de IA (PyTorch) ainda não tem versão para o Python mais recente. Os dois serviços leem
o `.env` da raiz do projeto.

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

- As evidências são apagadas após `RETENTION_DAYS` (padrão: 30 dias).
- O painel e a API exigem token (`API_TOKEN`). O detector usa uma chave própria (`DETECTOR_API_KEY`).
- As senhas nas URLs RTSP aparecem mascaradas no painel.
- Sinalize as áreas monitoradas e defina uma política interna de uso das imagens.

## Próximos passos sugeridos

- Gravar um clipe de vídeo de alguns segundos antes e depois de cada evento
- Usuários com perfis (operador, supervisor, administrador) no lugar do token único
- Rastreamento de pessoas (ByteTrack) para contar violações por pessoa
- Detecção de queda de pessoa e pessoa próxima a empilhadeira em movimento
- Relatórios por turno e setor, com exportação em PDF ou Excel
- Execução na borda (NVIDIA Jetson) para plantas com pouca internet
