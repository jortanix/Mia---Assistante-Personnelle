from pathlib import Path
from datetime import datetime
import shutil
import sys

ROOT = Path(__file__).resolve().parent
PAYLOAD = ROOT / "lot_concentration"


def read(path):
    return path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")


def once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError("Repère absent ou ambigu : " + old[:100])
    return text.replace(old, new, 1)


def main():
    if not (ROOT / "desktop/package.json").is_file() or not (ROOT / "backend/manage.py").is_file():
        raise RuntimeError("Extrais le ZIP dans MIA, à côté de backend et desktop.")
    app = read(ROOT / "desktop/src/App.tsx")
    css = read(ROOT / "desktop/src/App.css")
    if "FocusPanel" in app or "MIA : concentration locale" in css:
        raise RuntimeError("Le lot concentration semble déjà installé. Aucun fichier modifié.")
    if "expected_updated_at" not in read(ROOT / "desktop/src/TaskPanel.tsx"):
        raise RuntimeError("Installe d'abord le lot Édition des tâches.")
    app = once(app, "import { TaskPanel } from './TaskPanel'",
        "import { TaskPanel } from './TaskPanel'\nimport { FocusPanel } from './FocusPanel'")
    marker = "            <TaskPanel disabled={isLoading || dictation.isBusy} />"
    app = once(app, marker, "            <FocusPanel />\n" + marker)
    changes = {
        "desktop/src/App.tsx": app,
        "desktop/src/App.css": css + read(PAYLOAD / "focus.css"),
        "desktop/src/FocusPanel.tsx": read(PAYLOAD / "FocusPanel.tsx"),
        "desktop/src/focusTimer.mjs": read(PAYLOAD / "focusTimer.mjs"),
        "desktop/src/focusTimer.d.mts": read(PAYLOAD / "focusTimer.d.mts"),
        "desktop/scripts/test_focus_timer.mjs": read(PAYLOAD / "test_focus_timer.mjs"),
    }
    new_files = list(changes)[2:]
    for relative in new_files:
        if (ROOT / relative).exists():
            raise RuntimeError("Un nouveau fichier existe déjà : " + relative)
    backup = ROOT / "sauvegardes" / ("avant-concentration-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
    backup.mkdir(parents=True)
    originals = {}
    for relative in changes:
        target = ROOT / relative
        originals[relative] = target.read_bytes() if target.exists() else None
        if target.exists():
            destination = backup / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, destination)
    (backup / "nouveaux-fichiers.txt").write_text("\n".join(new_files), encoding="utf-8")
    written = []
    try:
        for relative, content in changes.items():
            written.append(relative)
            target = ROOT / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
    except Exception:
        for relative in reversed(written):
            target = ROOT / relative
            if originals[relative] is None:
                target.unlink(missing_ok=True)
            else:
                target.write_bytes(originals[relative])
        raise
    print("Lot concentration installé :", len(changes), "fichiers.")
    print("Sauvegarde :", backup)
    print("Aucune modification du backend ni migration. Lance les tests Node et npm run build.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("INSTALLATION INTERROMPUE :", exc, file=sys.stderr)
        sys.exit(1)
