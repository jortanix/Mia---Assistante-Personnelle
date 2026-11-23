from pathlib import Path
from datetime import datetime
import ast
import hashlib
import shutil
import sys

ROOT = Path(__file__).resolve().parent
PAYLOAD = ROOT / "lot_gestion_memoire"
EXPECTED_SERVICES = "e512ef6adb641cbe87ed362b937697578cbf73147ae3d1f568fd9c432260b377"


def read(path):
    return path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")


def once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError("Repère absent ou ambigu : " + old[:100])
    return text.replace(old, new, 1)


def main():
    if not (ROOT / "backend/manage.py").is_file():
        raise RuntimeError("Extrais le contenu du ZIP dans MIA, à côté de backend et desktop.")
    paths = {
        "services": "backend/assistant/services.py",
        "views": "backend/assistant/views.py",
        "serializers": "backend/assistant/serializers.py",
        "urls": "backend/assistant/urls.py",
        "app": "desktop/src/App.tsx",
        "card": "desktop/src/MemoryProposalCard.tsx",
    }
    source = {key: read(ROOT / relative) for key, relative in paths.items()}
    if "MemoryPanel" in source["app"] or "def memory_list(" in source["views"]:
        raise RuntimeError("Ce lot semble déjà installé. Aucun fichier modifié.")
    if hashlib.sha256(source["services"].lstrip("\ufeff").rstrip().encode()).hexdigest() != EXPECTED_SERVICES:
        raise RuntimeError("services.py a changé depuis la pièce jointe. Fournis sa version actuelle.")
    if "_create_memory_proposal_turn" not in source["views"]:
        raise RuntimeError("Le premier lot de propositions doit être installé avant celui-ci.")
    services = source["services"]
    start = services.index("def build_messages(")
    end = services.index("class InvalidActionAnalysis", start)
    services = services[:start] + read(PAYLOAD / "build_messages.txt") + "\n\n" + services[end:]
    services = once(services,
        "def generate_reply(message: str, history: list[dict] | None = None) -> str:",
        "def generate_reply(message: str, history: list[dict] | None = None, *, use_memory: bool = False) -> str:")
    services = once(services,
        "def generate_reply_stream(message: str, history: list[dict] | None = None):",
        "def generate_reply_stream(message: str, history: list[dict] | None = None, *, use_memory: bool = False):")
    if services.count("messages = build_messages(message, history)") != 2:
        raise RuntimeError("Les appels de build_messages ont changé.")
    services = services.replace("messages = build_messages(message, history)",
        "messages = build_messages(message, history, use_memory=use_memory)")
    views = once(source["views"], "    ActionProposalSerializer,", "    ActionProposalSerializer,\n    MemorySerializer,")
    views = once(views, "generate_reply(message, history=history)",
        'generate_reply(message, history=history, use_memory=data.get("use_memory", False))')
    views = once(views, "generate_reply_stream(message, history=history)",
        'generate_reply_stream(message, history=history, use_memory=data.get("use_memory", False))')
    views += read(PAYLOAD / "memory_views.txt")
    serializers = once(source["serializers"],
        "class ChatRequestSerializer(serializers.Serializer):",
        "class ChatRequestSerializer(serializers.Serializer):\n    use_memory = serializers.BooleanField(required=False, default=False)")
    urls = once(source["urls"], "from .views import (", "from .views import (\n    memory_list,\n    memory_detail,")
    urls = once(urls, "\n]", '\n    path("memories/", memory_list, name="memory-list"),\n    path("memories/<int:memory_id>/", memory_detail, name="memory-detail"),\n]')
    app = once(source["app"], "import { useDictation } from './useDictation'",
        "import { useDictation } from './useDictation'\nimport { MemoryPanel } from './MemoryPanel'")
    app = once(app, "const [autoSpeak, setAutoSpeak] = useState(false)",
        "const [autoSpeak, setAutoSpeak] = useState(false)\n  const [useMemory, setUseMemory] = useState(false)")
    app = once(app, "          message: content,", "          message: content,\n          use_memory: useMemory,")
    app = once(app, "<h1>MIA</h1>", """<h1>MIA</h1>
            <MemoryPanel
              enabled={useMemory}
              onEnabledChange={setUseMemory}
              disabled={isLoading || dictation.isBusy}
            />""")
    changes = {
        paths["services"]: services, paths["views"]: views,
        paths["serializers"]: serializers, paths["urls"]: urls,
        paths["app"]: app, paths["card"]: read(PAYLOAD / "MemoryProposalCard.tsx"),
        "desktop/src/MemoryPanel.tsx": read(PAYLOAD / "MemoryPanel.tsx"),
        "backend/assistant/test_memory_management.py": read(PAYLOAD / "test_memory_management.py"),
    }
    new_files = ["desktop/src/MemoryPanel.tsx", "backend/assistant/test_memory_management.py"]
    for relative in new_files:
        if (ROOT / relative).exists():
            raise RuntimeError("Nouveau fichier déjà présent : " + relative)
    for relative, content in changes.items():
        if relative.endswith(".py"):
            ast.parse(content, filename=relative)
    backup = ROOT / "sauvegardes" / ("avant-gestion-memoire-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
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
            (ROOT / relative).write_text(content, encoding="utf-8")
    except Exception:
        for relative in reversed(written):
            if originals[relative] is None:
                (ROOT / relative).unlink(missing_ok=True)
            else:
                (ROOT / relative).write_bytes(originals[relative])
        raise
    print("Lot installé :", len(changes), "fichiers. Aucune migration nécessaire.")
    print("Sauvegarde :", backup)
    print("L'utilisation des préférences reste décochée par défaut dans l'interface.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("INSTALLATION INTERROMPUE :", exc, file=sys.stderr)
        sys.exit(1)
