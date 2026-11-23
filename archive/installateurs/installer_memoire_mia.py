from pathlib import Path
import ast
import hashlib
import shutil
import sys
from datetime import datetime

ROOT = Path(__file__).resolve().parent
PAYLOAD = ROOT / "lot_memoire"
EXPECTED = {'desktop/src/App.tsx': 'efcfb48ff96bcea071c940134f9c93fcc81c633c6e8d732b18ecbac7895cc1d5', 'desktop/src/stream.ts': '08a00d90e076f1392d9fea1c029d2ca12960614d9e917eacad6764de889606e2'}


def read(path):
    return path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")


def digest(text):
    return hashlib.sha256(text.lstrip("\ufeff").rstrip().encode("utf-8")).hexdigest()


def once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError("Repère absent ou ambigu : " + old[:90])
    return text.replace(old, new, 1)


def main():
    if not (ROOT / "backend" / "manage.py").is_file():
        raise RuntimeError("Extrais le contenu du ZIP dans la racine MIA, à côté de backend et desktop.")
    for relative, expected in EXPECTED.items():
        if digest(read(ROOT / relative)) != expected:
            raise RuntimeError("Le fichier a changé depuis la pièce jointe : " + relative +
                               ". Aucun fichier modifié. Fournis une nouvelle copie.")
    views_path = ROOT / "backend/assistant/views.py"
    views = read(views_path)
    for required in ("def _resolve_confirm(", "def _resolve_cancel(",
                     "def action_proposal_confirm(", "def action_proposal_cancel("):
        if required not in views:
            raise RuntimeError("Fonction préalable manquante : " + required)
    if "_create_memory_proposal_turn" in views:
        raise RuntimeError("Le lot semble déjà installé. Aucun fichier modifié.")
    views = once(views, "from .transcription import (",
                 "from .memory_rules import detect_memory_preference\nfrom .transcription import (")
    anchor = "        try:\n            for event_type, value in generate_reply_stream(message, history=history):"
    views = once(views, anchor,
                 "        try:\n" + read(PAYLOAD / "view_branch.txt") +
                 "            for event_type, value in generate_reply_stream(message, history=history):")
    views += read(PAYLOAD / "view_helper.txt")
    changes = {
        "backend/assistant/views.py": views,
        "backend/assistant/memory_rules.py": read(PAYLOAD / "memory_rules.py"),
        "backend/assistant/test_memory_proposals.py": read(PAYLOAD / "test_memory_proposals.py"),
        "desktop/src/App.tsx": read(PAYLOAD / "App.tsx"),
        "desktop/src/stream.ts": read(PAYLOAD / "stream.ts"),
        "desktop/src/MemoryProposalCard.tsx": read(PAYLOAD / "MemoryProposalCard.tsx"),
    }
    new_files = (
        "backend/assistant/memory_rules.py",
        "backend/assistant/test_memory_proposals.py",
        "desktop/src/MemoryProposalCard.tsx",
    )
    for relative in new_files:
        if (ROOT / relative).exists():
            raise RuntimeError("Le nouveau fichier existe déjà : " + relative)
    for relative, content in changes.items():
        if relative.endswith(".py"):
            ast.parse(content, filename=relative)
    backup = ROOT / "sauvegardes" / ("avant-lot-memoire-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
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
            target = ROOT / relative
            written.append(relative)
            target.write_text(content, encoding="utf-8")
    except Exception:
        for relative in reversed(written):
            target = ROOT / relative
            if originals[relative] is None:
                target.unlink(missing_ok=True)
            else:
                target.write_bytes(originals[relative])
        raise
    print("Lot installé :", len(changes), "fichiers. Aucune migration nécessaire.")
    print("Sauvegarde :", backup)
    print("Lance maintenant les tests Django et npm run build.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("INSTALLATION INTERROMPUE :", exc, file=sys.stderr)
        sys.exit(1)
