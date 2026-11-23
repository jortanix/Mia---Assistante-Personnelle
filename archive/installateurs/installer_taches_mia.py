from pathlib import Path
from datetime import datetime
import ast
import hashlib
import json
import shutil
import sys

ROOT = Path(__file__).resolve().parent
PAYLOAD = ROOT / "lot_taches"


def normalize(raw):
    return raw.decode("utf-8-sig").replace("\r\n", "\n").rstrip()


def main():
    if not (ROOT / "backend/manage.py").is_file():
        raise RuntimeError("Extrais le ZIP dans MIA, à côté de backend et desktop.")
    manifest = json.loads((PAYLOAD / "manifest.json").read_text(encoding="utf-8"))
    for relative, expected in manifest["expected"].items():
        target = ROOT / relative
        if not target.is_file() or hashlib.sha256(normalize(target.read_bytes()).encode()).hexdigest() != expected:
            raise RuntimeError("Version différente de la pièce jointe : " + relative +
                               ". Aucun fichier modifié. Fournis une copie actuelle si nécessaire.")
    changes = {}
    for relative in manifest["files"]:
        target = ROOT / relative
        if relative not in manifest["expected"] and target.exists():
            raise RuntimeError("Un nouveau fichier existe déjà : " + relative + ". Aucun fichier modifié.")
        content = (PAYLOAD / relative).read_text(encoding="utf-8")
        if relative.endswith(".py"):
            ast.parse(content, filename=relative)
        changes[relative] = content
    if "--check" in sys.argv:
        print("Préparation vérifiée :", len(changes), "fichiers. Aucun fichier modifié.")
        return
    backup = ROOT / "sauvegardes" / ("avant-lot-taches-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
    backup.mkdir(parents=True)
    originals = {}
    new_files = []
    for relative in changes:
        target = ROOT / relative
        originals[relative] = target.read_bytes() if target.exists() else None
        if target.exists():
            destination = backup / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, destination)
        else:
            new_files.append(relative)
    (backup / "nouveaux-fichiers.txt").write_text("\n".join(new_files), encoding="utf-8")
    written = []
    try:
        for relative, content in changes.items():
            written.append(relative)
            (ROOT / relative).write_text(content, encoding="utf-8")
    except Exception:
        for relative in reversed(written):
            target = ROOT / relative
            if originals[relative] is None:
                target.unlink(missing_ok=True)
            else:
                target.write_bytes(originals[relative])
        raise
    print("Lot tâches installé :", len(changes), "fichiers.")
    print("Sauvegarde :", backup)
    print("Aucune migration nécessaire. Lance les tests puis npm run build.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("INSTALLATION INTERROMPUE :", exc, file=sys.stderr)
        sys.exit(1)
