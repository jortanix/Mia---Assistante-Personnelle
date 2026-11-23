# Mia sur iPhone — architecture et procédure

Mia est hébergée sur le PC. L'iPhone l'atteint via **Tailscale** (réseau privé
chiffré, HTTPS, aucun port exposé sur Internet). L'app cliente est une app
**native Swift** (`mobile/ios/`), qui se compile **sur un Mac avec Xcode**.

## Ce que Siri permet (limites honnêtes)

Apple n'autorise pas une app tierce à remplacer *Hey Siri* ni le bouton latéral.
Mia exploite en revanche tout ce qu'Apple laisse faire :

| Fonction | Mise en œuvre |
| --- | --- |
| **« Hey Siri, demande à Mia … »** | App Intents exposés par l'app (`AskMiaIntent`, `BriefingIntent`) → Siri transcrit, Mia répond, Siri lit la réponse |
| **Bouton écran d'accueil** | Mia installée comme app normale |
| **Raccourcis** | Chaque App Intent devient un raccourci réutilisable |
| **Widget / accès rapides** | Ajoutables plus tard en extension WidgetKit |
| **Rappels poussés** | Notifications locales planifiées par l'app depuis les rappels du backend (fonctionne sans APNs ni serveur toujours allumé) |

## Topologie réseau

```
iPhone ── Tailscale ──> PC (100.x.y.z)
                         │
                         ├── Django 0.0.0.0:8000  (API /api/…)
                         └── Ollama local (reformulation)
```

- L'API sort **jamais** sur Internet : elle n'écoute que sur le réseau
  Tailscale (et loopback local).
- Deux clés optionnelles dans l'environnement du backend :
  - `MIA_API_KEY` : exigée pour **tout client distant** (`/api/*`) via le
    middleware `config/middleware.py`. Les requêtes locales (PC) passent sans
    clé ; l'iPhone présente `Authorization: Bearer <MIA_API_KEY>`.
  - `BRIEFING_API_KEY` : clé dédiée du briefing (inchangée).
- `ALLOWED_HOSTS` : les hôtes locaux par défaut + ceux de
  `DJANGO_ALLOWED_HOSTS` (IP/hostname Tailscale du PC).

## Étape 1 — Tailscale (10 min)

1. Installer Tailscale sur le PC (Windows) : https://tailscale.com/download.
   Ouvrir une session et appuyer sur **Connexion**.
2. Installer Tailscale sur l'iPhone depuis l'App Store, se connecter au
   même compte.
3. Côté PC, noter l'IP Tailscale (souvent `100.x.y.z`) et/ou le nom
   `mia-pc.tailXXXX.ts.net` :
   ```powershell
   tailscale ip -4
   ```
4. Configurer le backend :
   ```powershell
   # dans l'environnement du backend
   $env:ICLOUD_APPLE_ID   = "…"
   $env:ICLOUD_MAIL_LOGIN = "…@icloud.com"
   $env:ICLOUD_APP_PASSWORD = "…"
   $env:MIA_API_KEY       = "une-clé-choisie"
   $env:BRIEFING_API_KEY  = "une-autre-clé"
   $env:DJANGO_ALLOWED_HOSTS = "mia-pc,<IP.tailscale>,<nom>.ts.net"
   & ..\.venv\Scripts\python.exe manage.py runserver 0.0.0.0:8000
   ```
5. Depuis l'iPhone (Safari → `http://<IP.tailscale>:8000/api/briefing//`
   avec l'en-tête manquant, tu dois recevoir `401 {"error":"Accès MIA
   refusé."}` si `MIA_API_KEY` est définie — c'est le comportement attendu).

## Étape 2 — Compilation de l'app sur Mac (Xcode)

Prérequis : un Mac récent, Xcode 16+ (App Store), `brew` avec
[XcodeGen](https://github.com/yonaskolb/XcodeGen) (`brew install xcodegen`).

```bash
cd mobile/ios
xcodegen generate        # génère Mia.xcodeproj depuis project.yml
open Mia.xcodeproj
```

- Dans Xcode : *Target Mia → Signing & Capabilities* → cocher ton *Team*
  (compte Apple personnel suffit pour tests sur appareil signé 7 jours, ou
  compte développeur pour ~90 jours / TestFlight).
- Choisir ton iPhone comme destination et *Run*.
- Dans l'app, *Réglages* : renseigner
  - URL du backend : `http://<IP.tailscale>:8000` (ou `https://…ts.net`)
  - Clés `MIA_API_KEY` et `BRIEFING_API_KEY` (stockées dans le trousseau).

Transport (ATS) : l'`Info.plist` générée par XcodeGen autorise le **réseau
local** (`NSAllowsLocalNetworking`, donc les IP Tailscale 100.x en HTTP), et
refuse tout chargement arbitraire sur Internet (`NSAllowsArbitraryLoads: NO`).
SSL toujours préféré : avec `https://<nom>.ts.net`, Tailscale fournit un
certificat valide sur l'iPhone (via l'app Tailscale), chiffrement de bout en
bout.

## Étape 3 — Les fonctions Siri

Une fois l'app installée et lancée une fois :

1. *Réglages  → Siri et Recherche → Raccourcis de Siri* : les App Intents
   « Demander à Mia », « Point sur la journée », « Nouveau rappel » y
   apparaissent.
2. Dire « Hey Siri, Demander à Mia, que dit mon agenda ? ».
3. Ou *App Shortcuts* : les mêmes intents sont disponibles comme raccourcis.

Les notifications : à la première ouverture Mia demande l'autorisation de
« notifier »; elle synchronise ensuite les rappels du backend et planifie les
notifications locales (pas besoin du PC allumé au moment de la notification,
uniquement pour la synchronisation).

## Étape 4 — Déploiement à long terme

- App Store : compte développeur ($99/an). Signé, l'app gagne APNs (push hors
  synchronisation), widgets, etc.
- Ou distribution interne via TestFlight.
- Jamais d'exposition directe de `/api/` sur Internet : Tailscale reste la
  frontière (ou un reverse proxy TLS auto-hébergé pour un accès hors réseau).

## Tests

- Backend : `cd backend; ..\.venv\Scripts\python.exe manage.py test`
  (la garde `MIA_API_KEY` et les rappels sont couverts).
- App iOS : nécessite un Mac (test unitaire Xcode hors périmètre initial).
