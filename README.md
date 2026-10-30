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
| **Clipe da ocorrência** | Vídeo de alguns segundos antes e depois de cada desvio, além da foto |
| **Relatório automático** | PDF mensal ou semanal enviado por e-mail aos gestores |
| **Armazenamento de rede (NAS)** | Fotos, clipes, backups e relatórios no storage de rede, com fila quando o NAS está fora do ar |
| **Saúde das câmeras** | Alerta quando a câmera fica sem sinal, escura, obstruída/desfocada ou congelada |
| **Usuários e auditoria** | Perfis de acesso e registro de quem fez o quê, quando e de onde |
| **Parâmetros** (administradores) | Retenção de imagens e logs, uso do sistema (CPU, memória, disco) com limites de alerta, canais de alerta (e-mail, WhatsApp) e severidade por canal, com envio de teste, e dimensionamento de recursos |
| **Configurações** (administradores) | Conexão com storage de rede (NAS), backup (agendado ou manual, com ou sem evidências) e restauração |

### Perfis de acesso

| Perfil | Pode |
|---|---|
| **Operador** | Ver tudo e fazer a triagem (confirmar/falso alarme, classificar); concluir ações atribuídas a ele |
| **Técnico de segurança** | Tudo do operador, mais tratar e encerrar ocorrências, criar ações, câmeras e regras, gerar relatório |
| **Gestor** | Tudo do técnico, mais excluir câmeras |
| **Administrador** | Tudo, mais usuários, auditoria, Parâmetros e Configurações |

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

### Instalação definitiva na empresa (Windows)

1. **Iniciar com o computador**: clique com o botão direito em `instalar_servico.bat` →
   *Executar como administrador*. O VigIA passa a iniciar com o Windows, mesmo sem ninguém logado,
   e reinicia sozinho se algo falhar. Log em `logs/vigia.log`. Para desfazer: `remover_servico.bat`.
   O serviço roda como SYSTEM: prefira câmeras IP (RTSP); webcams USB podem não ser acessíveis.
2. **HTTPS** (obrigatório se o painel for acessado por outros computadores):

   ```powershell
   python vigia.py --gerar-certificado --nome vigia.empresa.local
   ```

   Isso cria uma autoridade certificadora própria da instalação e o certificado do servidor em
   `certs/`. Instale `certs/vigia-ca.crt` nos computadores que acessam o painel (duplo clique →
   Instalar certificado → Máquina local → Autoridades de Certificação Raiz Confiáveis), ajuste
   `PUBLIC_URL=https://...` e `HOST=0.0.0.0` no `.env` e reinicie. Se a empresa tiver certificado
   próprio, use `SSL_CERTFILE`/`SSL_KEYFILE`.
3. **Backup**: automático todo dia (padrão 2h), guardando os 14 últimos em `backend/data/backups`.
   Configure `BACKUP_COPY_DIR` com uma pasta de rede para ter uma cópia fora do computador.
   Na tela **Sistema** é possível fazer e baixar backups. Para restaurar: pare o VigIA e copie o
   backup por cima de `backend/data/vigia.db`.
4. **Relatório automático**: configure SMTP e `REPORT_EMAILS`. Por padrão, todo dia 1 sai o PDF do
   mês anterior (`REPORT_FREQUENCY=semanal` para toda segunda-feira). Na tela **Sistema** dá para
   enviar um relatório na hora.

### Parâmetros e Configurações pelo painel

Os administradores ajustam o sistema pelas guias **Parâmetros** e **Configurações**, sem editar o
`.env`. O que for salvo no painel tem prioridade, e cada campo mostra a origem do valor (painel, `.env`
ou padrão). Senhas e tokens ficam criptografados no banco com a `SECRET_KEY` (gerada pelo iniciador;
sem `.env`, num arquivo `backend/data/secret.key`) e nunca voltam para a tela.

**Backup e restauração** (guia Configurações):

- O backup é um `.zip` com o banco de dados e um manifesto. Marcando *Incluir fotos e clipes*, leva
  também as evidências. O backup automático diário leva só o banco.
- A restauração aceita um backup da lista ou um arquivo enviado (`.zip` ou `.db` de versões
  anteriores). O sistema confere a integridade do arquivo, faz antes um **backup de segurança do estado
  atual** (que permite desfazer) e exige digitar `RESTAURAR`. Backups de versões antigas são
  atualizados automaticamente.
- A `SECRET_KEY` não vai no backup: ao restaurar em outro computador, digite de novo as senhas (NAS,
  SMTP, WhatsApp) ou copie a `SECRET_KEY` do `.env` antigo.
- Com PostgreSQL, use `pg_dump`/`pg_restore`.

### Dimensionamento de recursos (implantação)

Na guia **Parâmetros → Dimensionamento e capacidade**:

- **Planejar implantação**: informe câmeras, ocorrências por câmera/dia, retenção, duração do clipe,
  modo de armazenamento e RAID. O sistema calcula o disco local (SSD) e o NAS necessários (com perda
  do RAID e folga), sugere discos e baias, estima CPU/GPU, memória e banda de rede e, opcionalmente, o
  volume de gravação contínua do NVR. O resultado pode ser impresso para a proposta.
- **Situação atual**: com os dados reais da instalação (tamanho médio das ocorrências e volume
  diário), projeta o uso com a retenção atual, em quantos dias o disco atinge o limite de alerta e a
  retenção máxima que cabe. Exige ao menos 3 dias e 20 ocorrências de amostra.

Premissas usadas (editáveis): ~2 MB por ocorrência (foto de 180 KB + clipe de 10 s a 3 quadros/s com
quadros de 60 KB), banco de ~3 KB por ocorrência, 60 GB de sistema/IA, desempenho de IA por classe de
hardware para o modelo nano (CPU ~15, GPU de entrada ~150, intermediária ~300, alta ~600 inferências/s)
com uso máximo de 70%. São médias: depois do piloto, use **"Usar os valores medidos nesta instalação"**.

### Armazenamento em storage de rede (NAS)

Guarda as evidências (fotos e clipes), os backups e os relatórios mensais em um NAS (Synology,
QNAP, TrueNAS ou qualquer pasta compartilhada da rede).

1. No NAS, crie uma pasta compartilhada (ex.: `vigia`) e um **usuário próprio** com permissão de
   leitura e escrita somente nela.
2. Na guia **Configurações → Conexão com storage de rede**, preencha caminho, usuário e senha, clique
   em **Testar conexão** e salve. Também é possível usar o `.env`:

   ```ini
   STORAGE_NAS_PATH=\\192.168.0.20\vigia
   STORAGE_NAS_USER=vigia
   STORAGE_NAS_PASSWORD=senha-do-usuario-no-nas
   STORAGE_MODE=espelho
   ```

   No Linux, monte o compartilhamento (`/etc/fstab` com `cifs` ou `nfs`) e use o ponto de montagem em
   `STORAGE_NAS_PATH`.
3. Reinicie o VigIA e, na tela **Sistema → Armazenamento de rede**, clique em **Ativar**. Isso grava um
   arquivo marcador na pasta. Sem ele o VigIA não grava nada, para não encher o disco local caso o
   compartilhamento não esteja conectado.

**Modos**

- `espelho` (padrão): tudo continua neste computador e o NAS recebe uma cópia, para redundância.
- `principal`: o NAS é o armazenamento oficial. Este computador guarda só os últimos
  `STORAGE_LOCAL_DAYS` dias e o painel busca o restante no NAS. Use quando o disco local for pequeno.

**Como funciona**

- As evidências são gravadas primeiro no disco local (a detecção nunca espera a rede) e enviadas ao NAS
  a cada `STORAGE_SYNC_INTERVAL` segundos, com cópia atômica e conferência de tamanho.
- Se o NAS ficar fora do ar, nada se perde: os arquivos aguardam na fila e o sistema avisa na tela e por
  e-mail após `STORAGE_OFFLINE_ALERT_MINUTES` minutos. No modo principal, imagens que só existem no NAS
  ficam indisponíveis no painel até ele voltar.
- A retenção (LGPD) apaga as fotos e clipes também no NAS. Se ele estiver fora do ar, a exclusão fica
  pendente e é feita quando ele voltar.
- Também vão para o NAS: os backups diários (pasta `backups/`, guardando `STORAGE_BACKUP_KEEP`) e o PDF
  de cada relatório automático (pasta `relatorios/`), como histórico para auditorias.

### Treinar o modelo com imagens do cliente

A precisão depende de imagens **das câmeras da própria planta** (ângulo, iluminação, uniformes,
modelo de capacete). O fluxo:

1. **Coletar**: no `.env`, defina `DATASET_DIR=C:\vigia-treino\coleta` e reinicie. O detector salva
   imagens quando há pessoas (uma por câmera a cada `DATASET_INTERVAL` segundos) e sempre que há
   desvio, já com as caixas marcadas pela IA atual (formato YOLO, pastas `images/` e `labels/`).
   Deixe coletar alguns dias, em todos os turnos.
2. **Corrigir as marcações** em uma ferramenta gratuita como o [Label Studio](https://labelstud.io)
   ou o [CVAT](https://www.cvat.ai), importando no formato YOLO (o `classes.txt` já vem na pasta).
   Inclua as classes negativas (`no_helmet`, `no_vest`...): elas ensinam o modelo a reconhecer a falta do EPI.
3. **Preparar e treinar** (com GPU é muito mais rápido):

   ```powershell
   cd detector; python -m vigia_detector.dataset preparar --origem C:\vigia-treino\coleta --saida C:\vigia-treino\conjunto
   ```

   ```powershell
   python -m vigia_detector.dataset treinar --dados C:\vigia-treino\conjunto\data.yaml --epocas 100
   ```

4. **Comparar** com o modelo atual e usar o novo só se o mAP50 for maior:

   ```powershell
   python -m vigia_detector.dataset avaliar --modelo ..\modelos\epi.pt --dados C:\vigia-treino\conjunto\data.yaml
   ```

As imagens coletadas mostram trabalhadores: restrinja o acesso à pasta e apague-a depois do treino.

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

- As **imagens e clipes** de evidência são apagados após `RETENTION_DAYS` (padrão: 30 dias). O **registro** da
  ocorrência, sem imagem, fica `EVENT_RETENTION_DAYS` (padrão: 2 anos) para os indicadores históricos.
- Acesso com usuário e senha (senhas com PBKDF2; sessões expiram após `SESSION_HOURS`). O detector usa
  uma chave própria (`DETECTOR_API_KEY`).
- Toda alteração e todo login (inclusive tentativas falhas) ficam na **auditoria**, com IP.
- Os indicadores são por área, turno e câmera, não por pessoa: o foco é o comportamento coletivo.
- As senhas nas URLs RTSP aparecem mascaradas no painel.
- Sinalize as áreas monitoradas e defina uma política interna de uso das imagens.

## Próximos passos sugeridos

- Usar os "falsos alarmes" marcados no painel como exemplos negativos no treinamento
- Exportar o clipe da ocorrência como arquivo de vídeo
- Rastreamento de pessoas (ByteTrack) para contar violações por pessoa
- Detecção de queda de pessoa e pessoa próxima a empilhadeira em movimento
- Exportação dos indicadores em Excel
- Execução na borda (NVIDIA Jetson) para plantas com pouca internet
