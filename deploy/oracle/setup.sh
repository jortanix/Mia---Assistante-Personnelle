#!/usr/bin/env bash
# Déploiement MIA sur la VM : construit l'image, démarre la stack et
# télécharge le modèle Ollama choisi dans le .env.
#
# Usage (depuis deploy/oracle/) :
#   cp .env.example .env   # puis remplir .env
#   ./setup.sh
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -f .env ]]; then
  echo "Fichier .env absent : cp .env.example .env puis remplis-le, et relance." >&2
  exit 1
fi
# shellcheck disable=SC1091
set -a; source .env; set +a

echo "[mia] build + démarrage de la stack..."
docker compose up -d --build

echo "[mia] téléchargement du modèle Ollama '$OLLAMA_MODEL' (une seule fois)..."
timeout 900 docker compose exec -T ollama ollama pull "$OLLAMA_MODEL"

echo
echo "=== Mia est en ligne : https://$DOMAIN ==="
echo "Dans l'app iOS -> Réglages :"
echo "  URL     : https://$DOMAIN"
echo "  Clé API : celle définie dans .env (MIA_API_KEY)"
