#!/usr/bin/env bash
# Build Mia (iOS) sur Mac — en une commande.
#
# Usage :
#   ./scripts/build.sh            # build "generic" (simulateur ou appareil, sans signature)
#   ./scripts/build.sh device     # build pour ton iPhone branché (team sélectionnée dans Xcode)
#
# Prérequis : xcodegen installé (brew install xcodegen), Xcode 16+, iPhone branché
# en USB + "Developer Mode" activé pour la cible device.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "→ Génération du projet Xcode depuis project.yml"
xcodegen generate

if [[ "${1:-}" == "device" ]]; then
    echo "→ Périphériques détectés :"
    xcrun xctrace list devices | grep -i iphone || true
    echo "→ Build pour iPhone (signature = Team choisie dans Xcode, sinon en local)."
    xcodebuild \
        -project Mia.xcodeproj \
        -scheme Mia \
        -derivedDataPath build \
        -destination 'generic/platform=iOS' \
        -allowProvisioningUpdates \
        build
else
    echo "→ Build pour simulateur."
    xcodebuild \
        -project Mia.xcodeproj \
        -scheme Mia \
        -derivedDataPath build \
        -destination 'platform=iOS Simulator,name=iPhone 16' \
        build
fi

echo "✅ Build terminé (artefacts dans build/Build/Products/)."
echo "   Pour lancer sur l'iPhone, ouvre Mia.xcodeproj, choisis ton iPhone et Run."
