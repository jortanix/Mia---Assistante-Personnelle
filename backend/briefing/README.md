# Briefing iCloud pour MIA

Lecture **seule** de l'agenda et des mails iCloud, à la demande.

- Commande en chat : **« Fais-moi le point sur ma journée »** (voir
  `assistant/views.py`) → réponse texte avec les événements du jour (fuseau
  de l'utilisateur) et quelques mails récents.
- API structurée : `GET /api/briefing/` (données) et `POST /api/briefing/`
  (texte), base du futur accès iPhone.

Le package `backend/briefing/` est **séparé** d'OpenJarvis (aucun connecteur
OpenJarvis n'est appelé) et n'utilise que des bibliothèques Python standard
plus `requests` :

- `caldav.py` — client CalDAV iCloud (`https://caldav.icloud.com`) ;
- `imap.py` — client IMAP iCloud (`imap.mail.me.com:993`) ;
- `collect.py` — orchestration et états de disponibilité ;
- `render.py` — rendu français **déterministe** (référence) ;
- `detect.py` — détection de la commande (sans LLM) ;
- `llm.py` — reformulation facultative via Ollama (le texte déterministe
  reste la référence si le moteur est indisponible) ;
- `service.py` — flux complet utiliser par les vues et la commande chat.

## Garanties de lecture seule

- **CalDAV** : uniquement `PROPFIND` (découverte) et `REPORT`
  `calendar-query` (lecture). Aucune écriture n'est jamais émise, même en cas
  d'erreur. Les événements sont filtrés sur la journée du briefing.
- **IMAP** : `select("INBOX", readonly=True)` et `FETCH BODY.PEEK[]` —
  ouvrir ou résumer un mail ne le marque jamais lu. Aucune commande
  d'écriture (`STORE`, `APPEND`, `EXPUNGE`, `COPY`, `MOVE`…). Lecture bornée
  (`BRIEFING_SINCE_DAYS` puis `BRIEFING_MAX_EMAILS`) : la boîte n'est pas
  indexée.
- Les identifiants ne sont **jamais** journalisés ni inclus dans les erreurs.
- On distingue toujours « aucun événement » (source `ok`, liste vide) d'une
  source **inaccessible** ou **non configurée** ; le briefing est alors
  partiel et l'indique.

## Configuration

Tout vient de l'environnement du processus (jamais de secret en dur) :

| Variable | Rôle | Défaut |
| --- | --- | --- |
| `ICLOUD_APPLE_ID` | Identifiant Apple pour CalDAV (souvent `@gmail.com`) | vide |
| `ICLOUD_APP_PASSWORD` | Mot de passe applicatif (voir plus bas) | vide |
| `ICLOUD_MAIL_LOGIN` | Adresse iCloud Mail pour IMAP (ex. `prenom_nom@icloud.com`) ; sinon l'Apple ID | vide |
| `BRIEFING_TIME_ZONE` | Fuseau du jour (ex. `Europe/Paris`) | `Europe/Paris` |
| `BRIEFING_MAX_EMAILS` | Nombre max de mails récents | `6` |
| `BRIEFING_SINCE_DAYS` | Fenêtre de recherche des mails (jours) | `2` |
| `BRIEFING_CALENDAR_LIMIT` | Nombre max d'événements demandés au serveur | `200` |
| `BRIEFING_USE_LLM` | Active la reformulation Ollama (`1`) | désactivé |
| `OLLAMA_BASE_URL` / `OLLAMA_MODEL` | Moteur local de reformulation | — |
| `BRIEFING_API_KEY` | Clé obligatoire pour `/api/briefing/` (sinon ouverte en dev) | vide |

### Mot de passe applicatif iCloud

1. Active l'authentification à double facteur sur le compte Apple.
2. Sur https://account.apple.com → *Authentification* → *Mots de passe
   applicatifs* → génère un mot de passe dédié à Mia (par exemple « MIA –
   briefing »).
3. Place-le dans `ICLOUD_APP_PASSWORD` (jamais dans du code ou un commit).

Sans `ICLOUD_APPLE_ID`/`ICLOUD_APP_PASSWORD`, la commande répond que la source
n'est pas configurée (aucun plantage).

**Deux identifiants pour un même compte.** Le calendrier (CalDAV) s'authentifie
avec l'identifiant Apple (`ICLOUD_APPLE_ID`, parfois une adresse non-iCloud
comme `prenom.nom@gmail.com`), alors que la messagerie (IMAP) s'authentifie
avec l'adresse **iCloud Mail** (`prenom_nom@icloud.com`). Si les deux
diffèrent, renseigne `ICLOUD_MAIL_LOGIN` ; sinon l'IMAP reprend l'Apple ID.

## API

```
GET  /api/briefing/   → JSON structuré (agenda + mails + statuts + ``partial``)
POST /api/briefing/   → {"text": "…"} (même rendu que la commande chat)
```

Si `BRIEFING_API_KEY` est définie, ces routes exigent
`Authorization: Bearer <clé>` (ou `X-Briefing-Key: <clé>`). Sinon, comme le
reste de l'API de développement, elles restent ouvertes en local.

## Sécurité du contenu (anti-« prompt injection »)

- Le texte des mails est uniquement une **source à résumer** ; il n'est
  jamais traité comme une instruction.
- Le prompt de reformulation (`llm.py`) le stipule explicitement, et la
  reformulation est strictement optionnelle : le rendu déterministe ne dépend
  jamais du contenu des mails pour sa structure.

## Futur accès iPhone (privé et authentifié)

L'API `/api/briefing/` sert de base à un client iPhone. Conduite recommandée :

1. **Ne jamais exposer** le serveur de dev ni l'API directement sur Internet.
2. Publier uniquement derrière un **reverse proxy TLS** (Caddy, nginx…)
   hébergé soi-même, qui ne relaie que `/api/briefing/`.
3. Imposer `BRIEFING_API_KEY` et transmettre la clé via le portefeuille de la
   clé du téléphone : le moyeur du client construit l'en-tête
   `Authorization` au moment de la requête, sans stocker la clé en clair.
4. Utiliser un mot de passe applicatif distinct pour l'iPhone et, si
   nécessaire, un compte iCloud dédié au briefing pour borner le périmètre.
5. Enregistrer les accès et surveiller les tentatives d'authentification
   refusées (les clients imap/caldav ne loggent aucun secret).

## Tests

```
cd backend
..\.venv\Scripts\python.exe manage.py test briefing
```

Les tests n'utilisent aucune connexion réelle : sessions CalDAV factices,
connexion IMAP simulée et API Django patchée. Un test de bout en bout réel
nécessite un compte iCloud de test avec mot de passe applicatif
(`ICLOUD_APPLE_ID`/`ICLOUD_APP_PASSWORD` dans l'environnement).
