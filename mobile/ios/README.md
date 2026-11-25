# Mia iOS

Application **native SwiftUI** qui parle au backend MIA (hébergé sur le PC)
via Tailscale. Elle expose des **App Intents** pour Siri, planifie des
**notifications locales** à partir des rappels du backend, et permet la
dictée vocale locale (framework Speech) avant envoi au chat.

## Structure

```
mobile/ios/
├── project.yml        Configuration XcodeGen (génère Mia.xcodeproj)
└── Mia/
    ├── MiaApp.swift             Point d'entrée + onglets
    ├── Config/                  URL du backend + clés (trousseau)
    ├── Models/                  Décodables JSON (chat, tâches, briefing…)
    ├── Services/                Client API, chat streamé, dictée, notifications
    ├── Views/                   Chat, Briefing, Tâches, Concentration, Mémoire, Rappels, Réglages
    └── Intents/                 App Intents Siri/Shortcuts
```

## Génération du projet (sur Mac)

```bash
brew install xcodegen
cd mobile/ios
xcodegen generate
open Mia.xcodeproj
```

…ou plus simple, en une commande :

```bash
cd mobile/ios
./scripts/build.sh        # build simulateur
./scripts/build.sh device # build pour iPhone branché
```

Sélectionner la team de signature, l'iPhone comme destination, puis Run.
Dans l'app : Réglages → URL du backend (`http://<IP.tailscale>:8000`) + clés.

## App Intents (Siri)

- **Demander à Mia** : `AskMiaIntent` — transcrit ta phrase (Siri) et lit la
  réponse de Mia.
- **Point sur la journée** : `BriefingIntent` — briefing iCloud (lecture seule).
- **Nouveau rappel** : `NewReminderIntent` — crée un rappel et planifie une
  notification locale.

## Build dans le cloud (TestFlight)

Ton Mac actuel (Air 2013) ne peut pas exécuter Xcode récent : on construit sur
GitHub Actions et on livre par TestFlight. Voir `docs/build-cloud-testflight.md`.

- `.github/workflows/ios-compile.yml` : vérifie la compilation (aucune clé).
- `.github/workflows/ios-testflight.yml` : build signé → TestFlight
  (compte développeur + clé API App Store Connect en secrets).
- Incrémenter `CURRENT_PROJECT_VERSION` dans `project.yml` avant chaque
  envoi. `scripts/build.sh` reste utile sur un Mac capable.

## Contrat d'API utilisé

Documenté dans `docs/mobile-iphone.md` et `backend/assistant/` :
`POST /api/chat/` → `{"conversation_id": int, "reply": string}` ;
`POST /api/chat/stream/` → NDJSON `start/delta/done/error` ;
`GET/POST /api/briefing/` ; `GET /api/tasks/`, `PATCH/DELETE /api/tasks/<id>/`
(concurrence optimiste `expected_updated_at`) ;
`GET/POST /api/reminders/`, `PATCH/DELETE /api/reminders/<id>/` ;
`GET/POST /api/focus-sessions/`, `PATCH /api/focus-sessions/<id>/` (phases
`running`/`paused`), `POST /api/focus-sessions/<id>/complete|undo|reset/` ;
les `App Intent` exigent `MIA_API_KEY` pour les clients distants
(`Authorization: Bearer`) et `BRIEFING_API_KEY` pour le briefing.
