#!/usr/bin/env bash
# Cria a instância de um cliente: banco próprio, chaves próprias e endereço HTTPS próprio.
#   ./novo_cliente.sh <cliente> <dominio>        ex.: ./novo_cliente.sh metalurgica-abc vigia.suaempresa.com.br
# Resultado: https://metalurgica-abc.vigia.suaempresa.com.br
set -euo pipefail
cd "$(dirname "$0")"

CLIENTE="${1:?informe o identificador do cliente (letras minúsculas, números e hífen)}"
DOMINIO="${2:?informe o domínio base, ex.: vigia.suaempresa.com.br}"
[[ "$CLIENTE" =~ ^[a-z0-9][a-z0-9-]{1,40}$ ]] || { echo "identificador inválido: use a-z, 0-9 e hífen"; exit 1; }
DIR="clientes/$CLIENTE"
[[ -e "$DIR" ]] && { echo "o cliente $CLIENTE já existe em $DIR"; exit 1; }

docker network inspect vigia_proxy >/dev/null 2>&1 || docker network create vigia_proxy >/dev/null
docker image inspect vigia-backend:latest >/dev/null 2>&1 || docker build -t vigia-backend:latest ../../backend

mkdir -p "$DIR/dados"
cp cliente/docker-compose.yml "$DIR/"
umask 077
cat > "$DIR/.env" <<ENV
CLIENTE=$CLIENTE
SECRET_KEY=$(openssl rand -hex 32)
DETECTOR_API_KEY=$(openssl rand -hex 24)
EDGE_REQUIRE_MTLS=true
COMPANY_NAME=
TIMEZONE=America/Sao_Paulo
ENV

(cd "$DIR" && docker compose -p "vigia-$CLIENTE" up -d)

# A instância cria a CA dos Edges na primeira inicialização; o proxy passa a confiar nela
for _ in $(seq 1 30); do [[ -f "$DIR/dados/edge-ca.crt" ]] && break; sleep 1; done
[[ -f "$DIR/dados/edge-ca.crt" ]] || { echo "a instância não criou dados/edge-ca.crt – veja: docker logs vigia-$CLIENTE-backend"; exit 1; }

cat > "proxy/sites/$CLIENTE.caddy" <<SITE
$CLIENTE.$DOMINIO {
	import seguranca
	# mTLS: navegadores entram sem certificado; os Edges apresentam o certificado emitido pela CA do cliente
	tls {
		client_auth {
			mode verify_if_given
			trust_pool file /clientes/$CLIENTE/dados/edge-ca.crt
		}
	}
	reverse_proxy vigia-$CLIENTE-backend:8000 {
		# impressão digital do certificado validado (substitui qualquer valor enviado pelo cliente)
		header_up X-Client-Cert-Sha256 {http.request.tls.client.fingerprint}
	}
}
SITE
docker compose -f proxy/docker-compose.yml exec -T caddy caddy reload --config /etc/caddy/Caddyfile 2>/dev/null \
  || echo "aviso: suba o proxy com: (cd proxy && docker compose up -d)"

echo
echo "✔ Cliente $CLIENTE criado: https://$CLIENTE.$DOMINIO"
echo "  1) Abra o endereço e crie o administrador do cliente."
echo "  2) Em Configurações → VigIA Edge, gere o código e instale o Edge na planta (edge/iniciar_planta.bat)."
