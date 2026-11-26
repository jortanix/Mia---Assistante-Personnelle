# MIA sur Oracle Cloud (Always Free) — pack de déploiement

Migre Mia de ton PC (backend + Ollama locaux, accès via Tailscale) vers une
machine virtuelle **Oracle Cloud Always Free** : Mia tourne 24/7, accessible de
n'importe où en **HTTPS réel** (Let's Encrypt), sans PC allumé ni VPN.

## Ce que fait le pack

| Fichier | Rôle |
|---|---|
| `Dockerfile` | Image backend : Python 3.14, dépendances, infernal combo Django + Whisper |
| `docker-compose.yml` | Stack en 3 conteneurs : **ollama** (ARM natif, réseau interne) + **backend** (gunicorn) + **caddy** (HTTPS) |
| `Caddyfile` | Serveur HTTP/HTTPS : certs auto, statiques, API + flux SSE non tamponnés |
| `backend-entrypoint.sh` | Attente d'Ollama, migrations, collectstatic, gunicorn |
| `.env.example` | Toutes les variables à remplir |
| `setup.sh` | Build + démarrage + téléchargement du modèle Ollama |
| `backup.sh` | Sauvegarde horodatée de la base (`dumpdata`) |

Côté app iOS : **aucune recompilation**. L'URL du serveur et la clé API se
règlent dans **Réglages** de l'app (déjà en place via `AppConfig`).
`NSAllowsArbitraryLoads` reste `false` : un certificat HTTPS public est même
plus conforme ATS que l'actuel HTTP Tailscale.

---

## 1. Créer la VM (10 min)

1. **Oracle Cloud Console** → Compute → *Instances* → *Create instance*.
2. Image : **Ubuntu 24.04** (ARM), **Shape : Ampere A1**.
   - L'Always Free propose jusqu'à **4 OCPU / 24 Go RAM / 200 Go disque** —
     prends le maximum si la capacité est dispo dans ta région (sinon 1 OCPU /
     6 Go suffit avec `qwen3:4b-instruct`).
3. Ajoute ta **clé SSH** (ou laisse Oracle en générer une, télécharge le `.pem`).
4. Crée : `Instance → VNIC → Subnet → Security List → Add Ingress Rules` :
   - Source `0.0.0.0/0`, **TCP 80** (HTTP, pour le challenge Let's Encrypt)
   - Source `0.0.0.0/0`, **TCP 443** (HTTPS)
   - *(pas de 8000 ni 11434 : tout passe par Caddy)*
5. Lance l'instance, note son **IP publique** (ex. `146.235.40.12`).

## 2. Installer Docker

```bash
ssh ubuntu@146.235.40.12
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# se reconnecter pour prendre le groupe docker :
exit && ssh ubuntu@146.235.40.12
```

## 3. Récupérer MIA et configurer

```bash
git clone https://github.com/jortanix/Mia---Assistante-Personnelle.git mia
cd mia/deploy/oracle
cp .env.example .env
nano .env
```

À remplir dans `.env` :
- **`DOMAIN`** : soit ton domaine (`mia.exemple.com`, DNS A → IP publique),
  soit, sans domaine, `mia.<IP>.sslip.io` → ex. `mia.146.235.40.12.sslip.io`
  (résout déjà ; Caddy obtiendra un certificat Let's Encrypt tout seul).
- **`DJANGO_SECRET_KEY`** : `python3 -c "import secrets; print(secrets.token_urlsafe(50))"`
- **`MIA_API_KEY`** : ta clé actuelle ou une neuve (elle ira dans Réglages de
  l'app). **Ne laisse jamais vide** : sans elle l'API serait ouverte au monde.
- **`OLLAMA_MODEL`** : `qwen3:4b-instruct` (défaut) ou `qwen3:8b` (recommandé
  si tu as 4 OCPU — Mia est nettement plus « capable »).
- **`ICLOUD_*` / `BRIEFING_API_KEY`** : optionnels (briefing hors ligne sinon).

## 4. Déployer

```bash
./setup.sh        # build + up + téléchargement du modèle (1re fois : ~10 min)
```

Vérifier :

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://$DOMAIN/            # 404 = OK, l'API vit
curl -s https://$DOMAIN/api/briefing/ -H "X-Briefing-Api-Key: <BRIEFING_API_KEY>" | head
docker compose ps    # 3 services "Up" ; ollama "healthy"
```

## 5. Brancher l'app iOS

1. **Réglages** de l'app Mia :
   - **URL du serveur** : `https://$DOMAIN`
   - **Clé API** : celle de `MIA_API_KEY` dans `.env`
2. Teste une commande (« Rappelle-moi de… dans 1 minute », une tâche, le
   briefing). Les simples requêtes de statut restent fonctionnelles mais ça
   confirmera tout le chemin (Caddy → backend → Ollama).

---

## Maintenance

- **Mise à jour** : `git pull` dans `mia/` puis `./setup.sh` (les volumes
  `mia-data` / `ollama-models` conservent base, statiques et modèle).
- **Sauvegarde** : `./backup.sh` → JSON horodaté dans `deploy/oracle/backups/`.
  Cron conseillé : `15 3 * * * cd /home/ubuntu/mia/deploy/oracle && ./backup.sh`.
- **Changer de modèle** : édite `OLLAMA_MODEL` dans `.env` puis
  `docker compose up -d backend && docker compose exec -T ollama ollama pull <modele>`.
- **Basculer vers un vrai domaine** : change `DOMAIN` dans `.env` (+ DNS),
  `docker compose up -d` — Caddy renouvelle le certificat seul.
- **Limite du plan Always Free** : si « *Out of capacity* » à la création de
  la VM, retente dans une autre région ou plus tard — l'allocation Ampere se
  libère par vagues.

## Sécurité (résumé)

- Seuls les ports **80/443** sont ouverts ; Ollama et le backend restent sur
  le réseau Docker interne.
- `DJANGO_DEBUG=false` + `ALLOWED_HOSTS` limité + `DJANGO_SECRET_KEY` fort.
- Clé `MIA_API_KEY` obligatoire pour tout client distant (middleware
  `MiaApiKeyMiddleware` — la VM n'est pas loopback).
- HTTPS forcé (HSTS) + en-têtes durcis par Caddy.
- Si un secret de `.env` contient un `$`, double-le (`$$`) pour docker compose.

## Notes techniques

- **Python 3.14 + ARM** : les wheels `faster-whisper`/`av` (aarch64) couvrent
  le cas nominal. Si `av==18.1.0` n'avait pas de wheel pour ta combinaison,
  l'image passera en `python:3.14-bookworm` (compilation) — à signaler le cas
  échéant.
- **Whisper** : le modèle `base` (`WHISPER_MODEL`) se télécharge au premier
  `/api/transcribe` dans le volume `mia-data/hf` (persistant). Préchargeable :
  `docker compose exec backend python -c "from assistant.transcription import transcribe_audio; print('ok')"`.
- **SSE chat** : gunicorn (workers synchrones) + Caddy `flush_interval -1`
  gardent le flux `start→delta→done` sans tampon.
- **SQLite monousager** : parfait pour un assistant personnel ; la base vit sur
  le volume `mia-data` (mêmes réglages `timeout`/`IMMEDIATE` qu'en local).
