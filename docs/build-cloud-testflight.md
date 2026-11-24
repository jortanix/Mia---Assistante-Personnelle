# Build dans le cloud (GitHub Actions) + TestFlight

Ton Mac est un Air A1466 de 2013 : il ne peut pas exécuter un Xcode assez
récent (il s'arrête à Big Sur / Xcode 13 / SDK iOS 15, alors que Mia cible
iOS 17). Pour contourner ça **sans rien changer au code**, les builds sont
faits sur les macs de GitHub Actions et l'app arrive sur ton iPhone par
**TestFlight** — sans câble et sans ton Mac.

```
git push (PC) ──> GitHub Actions (macOS, Xcode 16)
                       │ build + signature (compte développeur)
                       ▼
                App Store Connect / TestFlight
                       │
                       ▼
              iPhone (TestFlight) ──Tailscale──> PC (API Mia)
```

## Répartition des fichiers

- `.github/workflows/ios-compile.yml` — **vérifie que l'app compile** à chaque
  push (aucune clé requise). C'est le premier à lancer : il valide le code
  Swift que j'ai écrit.
- `.github/workflows/ios-testflight.yml` — compile **et** pousse sur
  TestFlight (exige les secrets ci-dessous), déclenché à la main.
- `mobile/ios/scripts/build.sh` — devenu facultatif (build local sur un Mac
  qui en est capable), conservé pour retrouver le contrôle local plus tard.

## Étape 1 — Créer ton dépôt GitHub

1. Compte sur https://github.com (gratuit).
2. https://github.com/new → nom par ex. `mia` → **Public ou Privé** :
   - **Public** : les builds macOS sont **gratuits**, les logs visibles.
   - **Privé** : builds macOS comptent pour des minutes (quota mensuel puis
     facturées ~×2 la minute). Coût réel : ~10-20 min par build.
3. Depuis le PC (PowerShell, dans `C:\Users\lmoret1\MIA`) :
   ```powershell
   git remote add origin https://github.com/<toi>/mia.git
   git branch -M main
   git push -u origin main
   ```
   (les secrets iCloud n'ont jamais franchi le dépôt ; les fichiers ne
   contiennent aucune clé).

## Étape 2 — Compte développeur Apple ($99/an)

1. https://developer.apple.com/programs/enroll/ → active ton compte.
2. **App ID** : à la première utilisation de la signature cloud, Xcode la
   crée automatiquement (bundle `fr.mia.app`) quand un build signé est
   demandé.
3. **App Store Connect** → https://appstoreconnect.apple.com → **Mes apps** →
   **+** → *Nouvelle app* : name `Mia`, platform **iOS**, bundle ID
   `fr.mia.app` (par déroulé si absent), SKU `mia01`. Pas besoin de remplir
   les captures d'écran ni le reste pour l'instant.

## Étape 3 — Créer la clé API App Store Connect (une seule fois)

1. App Store Connect → **Utilisateurs et accès** → onglet **Clés
   d'intégration** (ou *Keys*) → **+**.
2. Nom `GitHub Actions`, rôle **Administrateur** (ou **Gestionnaire d'app**),
   accès **Toutes les apps**.
3. Télécharger le fichier `AuthKey_<ID>.p8` (**il n'est affiché qu'une
   fois**) et noter :
   - **Key ID** (ex. `ABCD123456`)
   - **Issuer ID** (en haut de la page)
   - **Team ID** → https://developer.apple.com/account → *Membership details*
     (ex. `ABCDE12345`).

## Étape 4 — Ajouter les secrets GitHub

Sur la page du dépôt → **Settings → Secrets and variables → Actions →
New repository secret** :

| Nom | Valeur |
| --- | --- |
| `APPLE_TEAM_ID` | Team ID (`ABCDE12345`) |
| `ASC_API_KEY_ID` | Key ID de la clé |
| `ASC_API_ISSUER_ID` | Issuer ID |
| `ASC_API_KEY` | **contenu entier** du fichier `.p8` (à l'identique) |

## Étape 5 — Premier lancement : vérifier que ça compile

1. **Actions → iOS — Compile check → Run workflow**.
2. Le build Mac dur ~10 min. Si le log se termine par `** BUILD SUCCEEDED **`,
   le code Swift est bon. Sinon, télécharge l'artefact `build-log` et colle
   les erreurs ici — je corrige.

## Étape 6 — Pousser sur TestFlight

1. **Actions → iOS — TestFlight → Run workflow** (changelog facultatif).
2. Attendre fin du workflow, puis App Store Connect → *TestFlight* → l'onglet
   **Builds : iOS** montre le build en **Traitement** (~5-20 min), puis
   **Prêt à tester**.
3. Ouvrir l'onglet *Testeurs et groupes* : créer un groupe (ex. « Moi ») qui
   te contient (ton Apple ID). Le build doit lui être assigné (bouton **+**).

## Étape 7 — Installer sur l'iPhone

1. Installer l'app **TestFlight** depuis l'App Store sur l'iPhone, te
   connecter avec le même Apple ID, accepter l'invitation par e-mail /
   directement dans TestFlight.
2. Mia s'installe (valable **90 jours** ; à chaque nouvelle version, relancer
   le workflow Étape 6).
3. **iPhone sous Tailscale** (même compte que le PC). Premier lancement :
   - Autoriser notifications, micro, reconnaissance vocale.
   - *Réglages* de Mia : URL `http://<IP.tailscale>:8000`, coller
     `MIA_API_KEY` et `BRIEFING_API_KEY`.
4. Tester : message au chat, point sur la journée, un rappel (notification
   locale). Siri : *Réglages → Siri et Recherche → Raccourcis de Siri* →
   « Demander à Mia … ».

## Astuces et limites

- **Builds TestFlight** : conservés 90 jours ; 1 build/minute max de raison ;
  il faut incrémenter `CURRENT_PROJECT_VERSION` dans `mobile/ios/project.yml`
  avant chaque nouvel envoi (sinon « build already exists »).
- **Pas besoin de l'UDID de l'iPhone** pour TestFlight (contrairement au
  câble) : l'invitation s'occupe de tout.
- **APNs (push)** reste différé : c'est le prochain chantier une fois l'app
  en main, si tu le souhaites.
- Pour repasser en build local (nouveau Mac, ou OCLP) : `scripts/build.sh`.
