"""Détection volontairement limitée à des préférences non sensibles explicites."""
import re
import unicodedata

_PATTERNS = (
    r"je prefere (?:des |les )?reponses (?:courtes|breves)",
    r"je prefere (?:des |les )?reponses (?:detaillees|longues)",
    r"je prefere (?:avancer|qu'on avance|que l'on avance) une etape a la fois",
    r"je prefere (?:une seule|une) (?:petite )?action a la fois",
    r"je prefere (?:des |les )?reponses sans emojis?",
    r"je prefere (?:le tutoiement|le vouvoiement)",
    # Ajout de nouvelles formulations pour une meilleure reconnaissance
    r"je prefere (?:des |les )?reponses (?:courtes|breves|simples)",
    r"je prefere (?:des |les )?reponses (?:detaillees|longues|completes)",
    r"je prefere (?:une seule|une) (?:petite )?action a la fois",
    r"je prefere (?:des |les )?reponses sans emojis?",
    r"je prefere (?:le tutoiement|le vouvoiement)",
    r"je prefere (?:une seule|une) (?:petite )?action a la fois",
    r"je prefere (?:que l'on avance|qu'on avance) (?:pas trop vite|sans trop se presser)",
    r"je prefere (?:que l'on avance|qu'on avance) (?:progressivement|avec calme)",
    r"je prefere (?:des |les )?reponses (?:simples|claires|directes)",
    r"je prefere (?:des |les )?reponses (?:courtes|brèves|concises)",
)

def detect_memory_preference(message):
    if not isinstance(message, str):
        return None
    content = message.strip()
    if not content or len(content) > 500:
        return None
    normalized = unicodedata.normalize('NFKD', content.casefold())
    normalized = ''.join(c for c in normalized if not unicodedata.combining(c))
    normalized = normalized.replace('’', "'")
    normalized = ' '.join(normalized.split()).rstrip('.! ')
    if any(re.fullmatch(pattern, normalized) for pattern in _PATTERNS):
        return content
    return None