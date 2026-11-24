# MIA — assistant personnel local

Assistant IA local : conversations par chat (texte, voix, transcription),
gestion de tâches, mémoire, minuteur de concentration et **point sur la
journée** (agenda + mails iCloud, lecture seule).

## Structure

```
MIA/
├── archive/            Historique préservé (voir plus bas)
├── backend/            API Django (127.0.0.1:8000)
│   ├── config/         Réglages et URLs Django
│   ├── assistant/      Application principale (chat, voix, tâches, mémoire)
│   └── briefing/       Point sur la journée iCloud (CalDAV + IMAP, lecture seule)
├── desktop/            Interface React + TypeScript + Vite (127.0.0.1:5173)
│   └── src/            App, panneaux (Tâches, Mémoire, Concentration), `taskApi.ts`, `stream.ts`
└── mobile/             App iPhone native (SwiftUI) + docs
```

- `pyproject.toml` / `uv.lock` — projet Python géré par [uv](https://docs.astral.sh/uv/), venv dans `.venv/`.
- Le dossier `desktop/` est le seul projet npm (son `package-lock.json` fait foi).

## Démarrage

**Backend** (dans `backend/`), venv au niveau de la racine :

```powershell
Set-Location C:\Users\lmoret1\MIA\backend
..\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

**Frontend** (dans `desktop/`) :

```powershell
Set-Location C:\Users\lmoret1\MIA\desktop
npm install
npm run dev        # http://127.0.0.1:5173, proxy /api → backend
```

## Tests

```powershell
# Backend (toute la suite, y compris briefing)
Set-Location C:\Users\lmoret1\MIA\backend
..\.venv\Scripts\python.exe manage.py test

# Frontend
Set-Location C:\Users\lmoret1\MIA\desktop
npm test
```

## Point sur la journée (briefing iCloud)

Commande en chat : **« Fais-moi le point sur ma journée »**. Lecture seule
strictement (jamais de mail marqué lu, jamais d'écriture agenda). Le calendrier
s'authentifie avec l'identifiant Apple, la messagerie avec **l'adresse iCloud
Mail** ; voir `backend/briefing/README.md`.

Variables d'environnement (jamais de secret dans le code ni les journaux) :

| Variable | Rôle |
| --- | --- |
| `ICLOUD_APPLE_ID` | Identifiant Apple pour CalDAV (ex. `prenom.nom@gmail.com`) |
| `ICLOUD_MAIL_LOGIN` | Adresse iCloud Mail pour IMAP (ex. `prenom_nom@icloud.com`) |
| `ICLOUD_APP_PASSWORD` | **Mot de passe applicatif** (jamais le mot de passe du compte) |
| `BRIEFING_API_KEY` | Protège `GET/POST /api/briefing/` quand elle est définie |

## Sécurité

- Aucun secret versionné ; identifiants et mots de passe applicatifs en
  environnement uniquement.
- iCloud : toujours un **mot de passe applicatif** dédié (révocable), jamais le
  mot de passe du compte.
- L'API `/api/briefing/` n'est jamais exposée directement sur Internet (un
  futur accès iPhone passerait par un reverse proxy TLS).

## `archive/` — historique préservé

Contient tous les reliquats des étapes d'installation de MIA, conservés pour
documentation et retour arrière, mais hors du chemin de développement :

- `lots/` — instantanés des lots d'installation (tâches, mémoire, concentration…)
- `installateurs/` — scripts d'installation ponctuels
- `sauvegardes-anciennes/` — sauvegardes réalisées avant chaque changement
- `backups-fichiers/` — copies de sauvegarde `*.backup-*` des fichiers
- `logs/`, `db-backups/` — journaux et sauvegardes de base de données
- `racine-orphelins/` — ancien `LIRE-MOI.txt`, `main.py`, `package-lock.json`

Le projet est sous git depuis le nettoyage : l'historique des changements est
désormais suivi proprement, les sauvegardes ponctuelles ne sont plus nécessaires.
