#!/usr/bin/env bash
# Operação das instâncias dos clientes na nuvem.
#   ./clientes.sh listar                      situação de todos (container, HTTPS, Edges, disco)
#   ./clientes.sh atualizar-todos             nova imagem do servidor e recria um cliente por vez
#   ./clientes.sh publicar-edge <pacote.zip>  disponibiliza a versão do Edge (assinada) a todos os clientes
#   ./clientes.sh backup <cliente|todos>      backup pelo próprio sistema (banco + anexos)
#   ./clientes.sh parar|iniciar <cliente>
#   ./clientes.sh remover <cliente>           desativa (os dados são arquivados, não apagados)
set -euo pipefail
cd "$(dirname "$0")"

clients() { find clientes -mindepth 1 -maxdepth 1 -type d ! -name '.*' -printf '%f\n' 2>/dev/null | sort; }
domain_of() { head -n1 "proxy/sites/$1.caddy" 2>/dev/null | awk '{print $1}'; }
need() { [[ -d "clientes/${1:-}" ]] || { echo "cliente '${1:-}' não existe"; exit 1; }; }
reload_proxy() { docker compose -f proxy/docker-compose.yml exec -T caddy caddy reload --config /etc/caddy/Caddyfile >/dev/null; }

cmd="${1:-}"; shift || true
case "$cmd" in
  listar)
    printf "%-24s %-10s %-6s %-10s %s\n" CLIENTE CONTAINER HTTPS DADOS ENDEREÇO
    for c in $(clients); do
      state=$(docker inspect -f '{{.State.Status}}' "vigia-$c-backend" 2>/dev/null || echo "ausente")
      dom=$(domain_of "$c")
      code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "https://$dom/api/health" || true)
      size=$(du -sh "clientes/$c/dados" 2>/dev/null | cut -f1)
      printf "%-24s %-10s %-6s %-10s https://%s\n" "$c" "$state" "${code:-–}" "${size:-–}" "$dom"
    done ;;

  atualizar-todos)
    docker build -t vigia-backend:latest ../../backend
    for c in $(clients); do
      echo "→ $c"
      (cd "clientes/$c" && docker compose -p "vigia-$c" up -d --force-recreate)
      dom=$(domain_of "$c")
      for _ in $(seq 1 30); do
        [[ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "https://$dom/api/health")" == "200" ]] && break; sleep 2
      done
      echo "  $(curl -s -o /dev/null -w 'HTTPS %{http_code}' --max-time 5 "https://$dom/api/health")"
    done ;;

  publicar-edge)
    zip="${1:?informe o pacote: deploy/assinatura/pacotes/vigia-edge-X.Y.Z.zip}"
    sig="${zip%.zip}.sig"
    [[ -f "$zip" && -f "$sig" ]] || { echo "faltam $zip e/ou $sig (gere com deploy/assinatura/fornecedor.py empacotar)"; exit 1; }
    for c in $(clients); do
      mkdir -p "clientes/$c/dados/pacotes-edge"
      cp "$zip" "$sig" "clientes/$c/dados/pacotes-edge/"
      echo "✔ $c"
    done
    echo "Os Edges com atualização automática instalam em até 6 h; os demais pelo botão Atualizar em Configurações." ;;

  backup)
    alvo="${1:?informe o cliente ou 'todos'}"
    lista=$([[ "$alvo" == "todos" ]] && clients || { need "$alvo"; echo "$alvo"; })
    for c in $lista; do
      docker exec "vigia-$c-backend" python -c \
        "from app.backup import run_backup; r = run_backup(label='nuvem'); print('$c:', r.get('name'), r.get('size_bytes', ''))"
    done ;;

  parar)   need "${1:-}"; (cd "clientes/$1" && docker compose -p "vigia-$1" stop) ;;
  iniciar) need "${1:-}"; (cd "clientes/$1" && docker compose -p "vigia-$1" up -d) ;;

  remover)
    c="${1:-}"; need "$c"
    read -r -p "Digite o nome do cliente ($c) para confirmar a desativação: " ok
    [[ "$ok" == "$c" ]] || { echo "cancelado"; exit 1; }
    (cd "clientes/$c" && docker compose -p "vigia-$c" down)
    rm -f "proxy/sites/$c.caddy"
    reload_proxy || true
    mkdir -p clientes/.removidos
    mv "clientes/$c" "clientes/.removidos/$c-$(date +%Y%m%d-%H%M%S)"
    echo "Cliente desativado. Dados arquivados em clientes/.removidos/ – apague conforme o contrato e a LGPD." ;;

  *) sed -n '2,9p' "$0"; exit 1 ;;
esac
