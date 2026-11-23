from pathlib import Path
from datetime import datetime
import ast
import shutil
import sys

ROOT = Path(__file__).resolve().parent
PAYLOAD = ROOT / "lot_consultation_taches"


def read(path):
    return path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")


def once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError("Repère absent ou ambigu : " + old[:100])
    return text.replace(old, new, 1)


def main():
    path = ROOT / "backend/assistant/views.py"
    if not (ROOT / "backend/manage.py").is_file():
        raise RuntimeError("Extrais le ZIP dans la racine MIA, à côté de backend et desktop.")
    views = read(path)
    if "build_task_answer" in views:
        raise RuntimeError("Ce lot semble déjà installé. Aucun fichier modifié.")
    if "def _create_proposal_turn(" not in views or "def _run_action_analysis(" not in views:
        raise RuntimeError("Le lot de tâches avec confirmation doit être installé d'abord.")
    views = once(views,
        "from .task_rules import InvalidTaskRequest, parse_task_request",
        "from .task_rules import InvalidTaskRequest, parse_task_request\nfrom .task_queries import build_task_answer")
    anchor = "\n    analysis = _run_action_analysis(message)"
    views = once(views, anchor, """
    task_reply = build_task_answer(message)
    if task_reply is not None:
        _save_messages(conversation, message, task_reply)
        return Response({"conversation_id": conversation.pk, "reply": task_reply})
""" + anchor)
    anchor = "\n            analysis = _run_action_analysis(message)"
    views = once(views, anchor, """
            task_reply = build_task_answer(message)
            if task_reply is not None:
                _save_messages(conversation, message, task_reply)
                yield _encode_stream_event("delta", content=task_reply)
                yield _encode_stream_event("done", conversation_id=conversation_id)
                return
""" + anchor)
    changes = {
        "backend/assistant/views.py": views,
        "backend/assistant/task_queries.py": read(PAYLOAD / "task_queries.py"),
        "backend/assistant/test_task_queries.py": read(PAYLOAD / "test_task_queries.py"),
    }
    new_files = list(changes)[1:]
    for relative in new_files:
        if (ROOT / relative).exists():
            raise RuntimeError("Le nouveau fichier existe déjà : " + relative)
    for relative, content in changes.items():
        ast.parse(content, filename=relative)
    backup = ROOT / "sauvegardes" / ("avant-consultation-taches-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
    backup.mkdir(parents=True)
    destination = backup / "backend/assistant/views.py"
    destination.parent.mkdir(parents=True)
    shutil.copy2(path, destination)
    original = path.read_bytes()
    (backup / "nouveaux-fichiers.txt").write_text("\n".join(new_files), encoding="utf-8")
    written = []
    try:
        for relative, content in changes.items():
            written.append(relative)
            (ROOT / relative).write_text(content, encoding="utf-8")
    except Exception:
        path.write_bytes(original)
        for relative in new_files:
            if relative in written:
                (ROOT / relative).unlink(missing_ok=True)
        raise
    print("Consultation des tâches installée :", len(changes), "fichiers.")
    print("Sauvegarde :", backup)
    print("Aucune migration, aucune modification de l'interface.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("INSTALLATION INTERROMPUE :", exc, file=sys.stderr)
        sys.exit(1)
