#!/usr/bin/env bash
# Sauvegarde de la base de données SQLite de Mia dans ./backups/ (horodatée).
# À lancer en cron si tu veux (ex. chaque nuit) :
#   15 3 * * * cd /home/ubuntu/mia/deploy/oracle && ./backup.sh
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p backups
stamp="$(date +%Y%m%d-%H%M%S)"
docker compose exec -T backend python manage.py dumpdata --indent 2 \
  > "backups/mia-${stamp}.json"
echo "Sauvegarde OK : backups/mia-${stamp}.json"
