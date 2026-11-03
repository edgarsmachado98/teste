# VigIA na nuvem – uma instância por cliente

```
                    Internet (443)
 Planta do cliente ─────────────────────► Caddy (HTTPS automático)
  VigIA Edge                                 ├─ cliente-a.seudominio → instância A (banco A)
  └ imagens no storage do cliente            └─ cliente-b.seudominio → instância B (banco B)
```

- Cada cliente tem **servidor, banco, chaves e backups próprios** (`clientes/<cliente>/`). Um cliente não
  enxerga dados de outro mesmo em caso de falha de programação.
- As **imagens das pessoas não saem da planta**: ficam no storage do cliente, gravadas pelo VigIA Edge.
  A nuvem guarda os dados da ocorrência e uma miniatura (~15 KB). Imagem completa, clipe e ao vivo vêm
  pelo túnel do Edge só quando alguém abre a ocorrência.

## Servidor na nuvem (uma vez)

Requisitos: Linux com Docker, DNS `*.seudominio` apontando para o servidor, portas 80 e 443 abertas.

```bash
cd deploy/nuvem/proxy
echo "ACME_EMAIL=ti@suaempresa.com.br" > .env
docker compose up -d
```

## Novo cliente

```bash
cd deploy/nuvem
./novo_cliente.sh metalurgica-abc vigia.suaempresa.com.br
```

Abra `https://metalurgica-abc.vigia.suaempresa.com.br`, crie o administrador do cliente e, em
**Configurações → VigIA Edge**, gere o código de instalação (vale 24 h, uso único).

Atualizar a versão de todos os clientes: `docker build -t vigia-backend:latest ../../backend` e, em cada
`clientes/<cliente>`, `docker compose -p vigia-<cliente> up -d`.

## Na planta (VigIA Edge)

Máquina na rede das câmeras (mini PC i5/16 GB atende ~8–12 câmeras; mais que isso, GPU/Jetson).
Copie a pasta do VigIA e rode `edge\iniciar_planta.bat`: na primeira vez ele pede o endereço da nuvem,
o código e a pasta do storage do cliente (ex.: `\\nas\vigia` ou `D:\vigia`), e depois mantém Edge e
detector rodando.

### O que pedir à TI do cliente

| Item | Necessário |
|---|---|
| Saída HTTPS (TCP 443) para `<cliente>.seudominio` | Sim – é a única conexão com a internet |
| Portas de entrada, VPN, redirecionamento no roteador | **Não** |
| Acesso RTSP às câmeras a partir da máquina do Edge | Sim (rede local) |
| Pasta no storage com usuário exclusivo do VigIA (leitura e escrita) | Sim |

### Segurança

- Túnel iniciado pelo Edge (saída 443, TLS). O Edge recusa endereço sem HTTPS.
- **mTLS**: no cadastro o Edge gera a própria chave (que não sai da máquina) e a CA do cliente assina o
  certificado dele. O Caddy valida o certificado e o servidor só aceita o Edge com o certificado certo
  (`EDGE_REQUIRE_MTLS=true`, ativado por `novo_cliente.sh`). Cada cliente tem a sua CA.
- **Imagens criptografadas no storage do cliente** (AES-256-GCM). Uma cópia da chave fica na nuvem,
  cifrada com a chave da instância, para um Edge substituto continuar lendo as imagens antigas.
  Guarde o `.env` e a pasta `dados/` do cliente: sem eles as imagens antigas não podem ser lidas.
- Credencial própria por Edge, guardada só como hash na nuvem; revogável em Configurações (a conexão cai na hora).
- Código de instalação de uso único, 24 h, com bloqueio após tentativas erradas.
- O túnel só entrega imagens de dentro da pasta do storage (nada de caminhos fora dela).
- Retenção (LGPD): a nuvem informa o prazo e o próprio Edge apaga a mídia vencida, mesmo sem internet.
- Sem internet, o Edge continua detectando e guarda as ocorrências numa fila em disco; reenvia depois, sem duplicar.
