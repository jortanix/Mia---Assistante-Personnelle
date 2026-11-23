from pathlib import Path
from datetime import datetime
import ast
import shutil
import sys

ROOT = Path(__file__).resolve().parent
PAYLOAD = ROOT / "lot_edition_taches"


def read(path):
    return path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")


def once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError("Repère absent ou ambigu : " + old[:100])
    return text.replace(old, new, 1)


def main():
    if not (ROOT / "backend/manage.py").is_file():
        raise RuntimeError("Extrais le ZIP dans MIA, à côté de backend et desktop.")
    views_path = ROOT / "backend/assistant/views.py"
    panel_path = ROOT / "desktop/src/TaskPanel.tsx"
    views = read(views_path)
    panel = read(panel_path)
    if "expected_updated_at" in views or "expected_updated_at" in panel:
        raise RuntimeError("Ce lot semble déjà installé, ou ces fichiers ont été modifiés. Aucun fichier modifié.")
    if "build_task_answer" not in views:
        raise RuntimeError("Installe d'abord le lot de consultation des tâches dans le chat.")
    for marker in ("notifyTasks", "export function TaskPanel", "Mes tâches"):
        if marker not in panel:
            raise RuntimeError("TaskPanel.tsx ne correspond pas au lot précédent.")
    views = once(views, read(PAYLOAD / "task_detail_original.txt"), read(PAYLOAD / "task_detail_nouveau.txt"))
    views = once(views, "from django.shortcuts import get_object_or_404",
        "from django.shortcuts import get_object_or_404\nfrom django.utils import timezone\nfrom django.utils.dateparse import parse_datetime")
    changes = {
        "backend/assistant/views.py": views,
        "backend/assistant/test_task_editing.py": read(PAYLOAD / "test_task_editing.py"),
        "desktop/src/TaskPanel.tsx": read(PAYLOAD / "TaskPanel.tsx"),
    }
    new_file = "backend/assistant/test_task_editing.py"
    if (ROOT / new_file).exists():
        raise RuntimeError("Le fichier de tests existe déjà. Aucun fichier modifié.")
    for relative, content in changes.items():
        if relative.endswith(".py"):
            ast.parse(content, filename=relative)
    backup = ROOT / "sauvegardes" / ("avant-edition-taches-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
    backup.mkdir(parents=True)
    originals = {}
    for relative in changes:
        target = ROOT / relative
        originals[relative] = target.read_bytes() if target.exists() else None
        if target.exists():
            destination = backup / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, destination)
    (backup / "nouveaux-fichiers.txt").write_text(new_file, encoding="utf-8")
    written = []
    try:
        for relative, content in changes.items():
            written.append(relative)
            (ROOT / relative).write_text(content, encoding="utf-8")
    except Exception:
        for relative in reversed(written):
            if originals[relative] is None:
                (ROOT / relative).unlink(missing_ok=True)
            else:
                (ROOT / relative).write_bytes(originals[relative])
        raise
    print("Édition des tâches installée :", len(changes), "fichiers.")
    print("Sauvegarde :", backup)
    print("Aucune migration nécessaire. Lance les tests et npm run build.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("INSTALLATION INTERROMPUE :", exc, file=sys.stderr)
        sys.exit(1)
