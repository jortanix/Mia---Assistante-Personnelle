"""Commandes explicites uniquement ; aucun appel IA supplémentaire."""
import re


class InvalidTaskRequest(ValueError):
    pass


def parse_task_request(message):
    if not isinstance(message, str):
        return {"action": "none"}
    text = message.strip()
    text = re.sub(r"^mia\s*,\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^peux-tu\s+", "", text, flags=re.IGNORECASE)
    prefixes = (
        r"^(?:ajoute|ajouter|crée|créer|cree|creer|note|enregistre)\s+(?:une\s+)?t[âa]che(?=\s|:|$)",
        r"^(?:ajoute|ajouter)\s+[àa]\s+mes\s+t[âa]ches(?=\s|:|$)",
    )
    for prefix in prefixes:
        match = re.match(prefix, text, flags=re.IGNORECASE)
        if match:
            title = text[match.end():].strip().lstrip(':').strip()
            title = title.rstrip('.').strip()
            if not title:
                raise InvalidTaskRequest("Précise le titre : Ajoute une tâche : ranger mon bureau.")
            if len(title) > 200:
                raise InvalidTaskRequest("Le titre de la tâche doit faire au maximum 200 caractères.")
            if '\n' in title or '\r' in title:
                raise InvalidTaskRequest("Pour ce premier mode, dicte ou écris une seule tâche sur une ligne.")
            return {"action": "create_task", "data": {"title": title, "description": ""}}
    return {"action": "none"}
