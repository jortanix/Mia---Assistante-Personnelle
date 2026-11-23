"""Consultation déterministe des tâches ; aucune action de modification."""
import re
import unicodedata

from .models import Task


def _normalize(message):
    if not isinstance(message, str):
        return ""
    text = unicodedata.normalize("NFKD", message.casefold())
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.replace("’", "'").replace("‑", "-").replace("–", "-")
    text = " ".join(text.split()).rstrip(".?! ")
    return re.sub(r"^mia\s*,\s*", "", text)


def detect_task_query(message):
    text = _normalize(message)
    groups = (
        ("choose", (
            r"aide-moi a choisir une tache",
            r"propose-moi une tache(?: a faire)?",
            r"par quelle tache commencer",
        )),
        ("count", (
            r"combien de taches (?:me reste-t-il|ai-je)(?: a faire)?",
            r"combien (?:est-ce que )?j'ai de taches(?: a faire)?",
            r"combien ai-je de taches(?: a faire)?",
        )),
        ("all", (
            r"(?:liste|affiche|montre)(?:-moi)? toutes (?:mes|les) taches",
        )),
        ("done", (
            r"quelles sont mes taches (?:terminees|faites)",
            r"(?:liste|affiche|montre)(?:-moi)? (?:mes|les) taches (?:terminees|faites)",
            r"mes taches terminees",
        )),
        ("todo", (
            r"quelles sont mes taches(?: a faire)?",
            r"(?:liste|affiche|montre)(?:-moi)? (?:mes|les) taches(?: a faire)?",
            r"mes taches(?: a faire)?",
            r"que me reste-t-il a faire",
            r"qu'est-ce qu'il me reste a faire",
            r"qu'est-ce que j'ai a faire",
        )),
    )
    for kind, patterns in groups:
        if any(re.fullmatch(pattern, text) for pattern in patterns):
            return kind
    return None


def build_task_answer(message):
    kind = detect_task_query(message)
    if kind is None:
        return None
    tasks = Task.objects.order_by("created_at", "id")
    if kind == "count":
        total = tasks.filter(status=Task.Status.TODO).count()
        return f"Il te reste {total} tâche{'s' if total != 1 else ''} à faire."
    if kind == "choose":
        task = tasks.filter(status=Task.Status.TODO).first()
        if task is None:
            return "Tu n'as aucune tâche à faire enregistrée."
        return f"Je te propose ta tâche à faire la plus ancienne : {task.title}"
    if kind == "todo":
        selected = tasks.filter(status=Task.Status.TODO)
        limit = 3
        empty = "Tu n'as aucune tâche à faire enregistrée."
        label = "à faire"
    elif kind == "done":
        selected = tasks.filter(status=Task.Status.DONE)
        limit = 3
        empty = "Tu n'as aucune tâche terminée enregistrée."
        label = "terminée"
    else:
        selected = tasks
        limit = 10
        empty = "Tu n'as aucune tâche enregistrée."
        label = "enregistrée"
    total = selected.count()
    if total == 0:
        return empty
    plural = "s" if total != 1 else ""
    label_plural = label + (plural if kind != "todo" else "")
    lines = [f"Tu as {total} tâche{plural} {label_plural}."]
    for task in selected[:limit]:
        status = "À faire" if task.status == Task.Status.TODO else "Terminée"
        lines.append(f"- {task.title}" + (f" — {status}" if kind == "all" else ""))
    if total > limit:
        lines.append(f"J'en affiche {limit}. La liste complète est dans Mes tâches.")
    return "\n".join(lines)
