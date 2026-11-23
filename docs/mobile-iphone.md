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

   ⚠️ Les `$env:…` ci-dessus ne valent que pour la **session PowerShell
   courante**. Pour persister (variables utilisateur, présentes dans chaque
   terminal) :

   ```powershell
   # Une fois, puis nouveau terminal
   setx ICLOUD_APPLE_ID "…"
   setx ICLOUD_MAIL_LOGIN "…@icloud.com"
   setx ICLOUD_APP_PASSWORD "…"
   setx MIA_API_KEY "une-clé-choisie"
   setx BRIEFING_API_KEY "une-autre-clé"
   setx DJANGO_ALLOWED_HOSTS "mia-pc,<IP.tailscale>,<nom>.ts.net"
   ```

   (Ou *Paramètres → Système → Informations système → Variables
   d'environnement*. Jamais de secret en dur dans les fichiers du dépôt.)
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

Transport (ATS) : l'`Info.plist` générée par XcodeGen autorise le **réseau
local** (`NSAllowsLocalNetworking`, donc les IP Tailscale 100.x en HTTP), et
refuse tout chargement arbitraire sur Internet (`NSAllowsArbitraryLoads: NO`).
SSL toujours préféré : avec `https://<nom>.ts.net`, Tailscale fournit un
certificat valide sur l'iPhone (via l'app Tailscale), chiffrement de bout en
bout.

### 2bis. Vérifier la chaîne depuis le Mac (avant de lancer l'app)

Sur le Mac (Tailscale allumé des deux côtés), tester que l'API répond et que
la clé est bien exigée :

```bash
# Sans clé → 401 attendu
curl -i "http://<IP.tailscale>:8000/api/reminders/" | head -n 1

# Avec la clé → 200
curl -i -H "Authorization: Bearer <MIA_API_KEY>" \
  "http://<IP.tailscale>:8000/api/reminders/" | head -n 1
```

Si le premier renvoie `401` et le second `200`, la garde distante fonctionne.
En cas d'`ERR_CONNECTION/refused`, vérifier `tailscale status` (les deux
appareils sont-ils en ligne ?) et `DJANGO_ALLOWED_HOSTS` (contient l'IP/hostname).

### 2ter. Lancer l'app sur l'iPhone

1. Dans Xcode : *Target Mia → Signing & Capabilities* → cocher ta *Team*. Un
   compte Apple gratuit signe pour 7 jours sur ton iPhone (réitérer ensuite) ;
   le compte développeur ($99/an) signe ~90 jours et ouvre TestFlight/APNs.
2. iPhone branché en USB (ou même réseau) : *Window → Devices and
   Simulators* -> ton iPhone. iOS 16+ : activer **Developer Mode**
   (*Réglages → Confidentialité et sécurité → Mode développeur*), puis
   autoriser le profil de confiance dans *Réglages → Général → VPN et gestion
   d'appareils* (profil de signature).
3. Choisir l'iPhone comme destination et *Run*. La première compilation
   prend quelques minutes (module cache).
4. Dans l'app, *Réglages* : URL `http://<IP.tailscale>:8000`, coller
   `MIA_API_KEY` et `BRIEFING_API_KEY`. Le premier échange avec le backend
   confirme la chaîne complète.

### Checklist « une fois rentré à la maison »

1. [ ] Mac sous Tailscale (même compte) ; PC et iPhone aussi, les trois en ligne.
2. [ ] `brew install xcodegen` si absent.
3. [ ] `git pull` du dépôt sur le Mac (ou copie de `mobile/ios/`).
4. [ ] Backend lancé sur le PC : `setx` des variables faites, puis
       `& ..\.venv\Scripts\python.exe manage.py runserver 0.0.0.0:8000`.
5. [ ] Depuis le Mac : `curl` sans clé → 401, avec clé → 200 (guide 2bis).
6. [ ] `cd mobile/ios && ./scripts/build.sh device` (ou Xcode via *Run*).
7. [ ] Xcode : *Signing & Capabilities* → ta Team (compte développeur).
8. [ ] iPhone branché en USB : Developer Mode activé, profil de confiance
       accepté, *Run*.
9. [ ] Dans l'app : URL + clés → chat, briefing, rappels OK.
10. [ ] Siri : *Réglages → Siri et Recherche → Raccourcis de Siri* →
    « Demander à Mia … ».

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

## Étape 4 — Déploiement à long terme (compte développeur $99/an)

- **TestFlight** : installe l'app sur l'iPhone **sans câble**, depuis ton
  compte développeur (jusqu'à 90 jours par build, profils de test Apple ID).
  Idéal pour les mises à jour quand tu rentres.
- **APNs (push)** : différé — v1 utilise les notifications locales
  synchronisées depuis `/api/reminders/`. Le push Apple (clic sur
  notification → actions, badges à jour quand l'app est fermée) nécessitera
  une clé APNs et un petit relais backend ; à porter plus tard.
- **Magasin / distribution** : TestFlight pour la famille d'abord ; l'App
  Store reste possible avec ton compte (revue Apple, configuration requise).
- Jamais d'exposition directe de `/api/` sur Internet : Tailscale reste la
  frontière (ou un reverse proxy TLS auto-hébergé pour un accès hors réseau).

## Tests

- Backend : `cd backend; ..\.venv\Scripts\python.exe manage.py test`
  (la garde `MIA_API_KEY` et les rappels sont couverts).
- App iOS : nécessite un Mac (test unitaire Xcode hors périmètre initial).
