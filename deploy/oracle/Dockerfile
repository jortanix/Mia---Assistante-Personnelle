# MIA — image backend de production.
# Base alignée avec le dev : Python 3.14 (cf. pyproject.toml).
# Cible typique : VM Oracle Cloud Always Free (Ampere ARM 64), mais fonctionne
# sur n'importe quelle VM Linux x86_64/arm64.
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    # Cache du modèle Whisper (téléchargé au premier /api/transcribe) :
    # placé sur le volume /app/data pour survivre aux reconstructions.
    HF_HOME=/app/data/hf

# curl sert à l'entrée (attente d'Ollama) ; supprimé de la liste des paquets
# juste après pour garder l'image légère.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dépendances d'abord : ce layer n'est reconstruit que si le fichier change
# (cache Docker efficace lors des mises à jour de code).
COPY backend/requirements-prod.txt ./backend/requirements-prod.txt
RUN pip install --no-cache-dir -r backend/requirements-prod.txt

# Code de l'application + script de démarrage.
COPY backend ./backend
COPY deploy/oracle/backend-entrypoint.sh ./backend-entrypoint.sh
RUN chmod +x /app/backend-entrypoint.sh

WORKDIR /app/backend
EXPOSE 8000
ENTRYPOINT ["/app/backend-entrypoint.sh"]
