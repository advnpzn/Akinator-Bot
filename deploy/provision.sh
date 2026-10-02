#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
if [[ "${1:-}" != "" && "${1:-}" != "--solver" ]]; then
    echo 'Usage: ./deploy/provision.sh [--solver]'
    exit 1
fi
if [[ ! -f .env ]]; then
    (umask 077; cp .env.example .env)
    echo 'Created .env. Set BOT_TOKEN and ADMIN_IDS locally, then rerun this script.'
    exit 1
fi
compose=(docker compose)
if [[ "${1:-}" == "--solver" ]]; then
    compose+=(-f docker-compose.yml -f deploy/compose.solver.yaml)
fi
docker compose version >/dev/null
# Validate configuration without printing expanded environment/credentials.
"${compose[@]}" config --quiet
"${compose[@]}" up -d --build --wait --wait-timeout 180
echo 'Bot deployed. Check health with: docker compose ps'
echo 'Check logs with: docker compose logs --tail=50 bot'
