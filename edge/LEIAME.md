# VigIA Edge

Roda na planta, junto das câmeras: detector de IA + imagens no storage do cliente. Conversa com o
servidor VigIA (nuvem) por uma conexão de saída segura. Implantação na nuvem: `deploy/nuvem/LEIAME.md`.

## Testar no próprio computador (servidor local fazendo o papel da nuvem)

1. Rode `iniciar.bat` (na pasta principal) como sempre e entre no painel.
2. Em **Configurações → VigIA Edge**, clique em **Gerar código de instalação**, escolha a unidade e anote o código.
3. Rode `edge\iniciar_planta.bat` e responda:
   - Endereço da nuvem: o mesmo do painel, ex.: `http://localhost:8000` (ou `https://localhost:8443` se
     você ativou o HTTPS com `python vigia.py --gerar-certificado` – o certificado local é usado sozinho);
   - Código: o anotado no passo 2;
   - Pasta do storage: ex.: `D:\vigia-teste` (Enter usa `edge\edge-data\midia`).
4. Pronto. As câmeras da unidade escolhida passam a ser analisadas pelo detector do Edge (o detector do
   `iniciar.bat` deixa de analisá-las automaticamente, para não duplicar). Em Configurações o Edge aparece
   como **Conectado**, com espaço livre do storage e fila.

O que observar no teste:

| Teste | Como | Resultado esperado |
|---|---|---|
| Imagem fica na planta | Gere uma ocorrência e abra a pasta do storage | Imagem e clipe na pasta do storage; na nuvem só a miniatura |
| Abrir ocorrência | Clique na ocorrência no painel | Imagem completa e clipe abrem (vêm pelo túnel) |
| Queda de internet | Feche a janela do `iniciar.bat` com o Edge rodando, gere ocorrências e abra de novo | Edge guarda na fila e envia tudo ao voltar, sem duplicar |
| Edge desligado | Feche o `iniciar_planta.bat` | Listas mostram a miniatura; o detalhe avisa que o Edge está desconectado; alerta após alguns minutos |
| Revogar | Configurações → Revogar | Edge desconecta na hora; precisa de novo código para voltar |

Para voltar ao modo sem Edge: revogue o Edge em Configurações (o detector do `iniciar.bat` volta a
analisar as câmeras da unidade) e, se quiser cadastrar de novo, apague a pasta `edge\edge-data`.

## Comandos

```
python -m vigia_edge enroll --cloud <endereço> --code <código> [--media-dir <pasta>]
python -m vigia_edge run
python -m vigia_edge status      # saúde do Edge em execução (fila, storage, túnel)
```

Diagnóstico local: http://127.0.0.1:8100/status (só na própria máquina).
