#!/bin/sh
# Démarrage du backend MIA en production (conteneur backend, PID 1).
#
#  1. attend qu'Ollama réponde (sinon les premiers échanges échoueraient) ;
#  2. applique les migrations (idempotent) ;
#  3. collecte les statiques (admin Django) vers MIA_STATIC_ROOT ;
#  4. lance gunicorn (WSGI ; le chat stream = Server-Sent Events, supporté).
set -e

echo "[mia] attente d'Ollama ($OLLAMA_BASE_URL)..."
until curl -fsS "${OLLAMA_BASE_URL}/api/tags" >/dev/null 2>&1; do
  sleep 2
done
echo "[mia] Ollama prêt."

python manage.py migrate --noinput
python manage.py collectstatic --noinput

echo "[mia] gunicorn sur 0.0.0.0:8000 (workers=3, timeout=300)."
exec gunicorn config.wsgi:application \
  --bind 0.0.0.0:8000 \
  --workers 3 \
  --timeout 300 \
  --access-logfile - \
  --error-logfile -
