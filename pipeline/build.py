"""Write per-episode JSON and the site index consumed by docs/*.html."""
from __future__ import annotations

from pathlib import Path

from .util import read_json, utcnow_iso, write_json

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
DATA = DOCS / "data"
EPISODES_DIR = DATA / "episodes"
INDEX_PATH = DATA / "index.json"


def episode_path(episode_id: str) -> Path:
    return EPISODES_DIR / f"{episode_id}.json"


def write_episode(doc: dict) -> Path:
    path = episode_path(doc["id"])
    write_json(path, doc, compact=True)
    return path


def rebuild_index(shows: list[dict]) -> dict:
    """Scan docs/data/episodes/*.json and regenerate index.json (newest first)."""
    items = []
    for p in sorted(EPISODES_DIR.glob("*.json")):
        doc = read_json(p, None)
        if not doc or "id" not in doc:
            continue
        study = doc.get("study") or {}
        items.append({
            "id": doc["id"],
            "show": doc["show"]["slug"],
            "title": doc["title"],
            "published_at": doc["published_at"],
            "duration_sec": doc.get("duration_sec"),
            "image": doc.get("image_url"),
            "one_liner_ko": study.get("one_liner_ko", ""),
            "tags": study.get("tags", []),
            "cefr": (study.get("difficulty") or {}).get("cefr", ""),
            "expressions": len(study.get("expressions", [])),
            "words": (doc.get("transcript") or {}).get("stats", {}).get("words"),
            "has_translation": bool(study.get("translations")),
            "mock": bool(study.get("mock")),
            "demo": bool(doc.get("demo")),
        })
    items.sort(key=lambda x: x["published_at"], reverse=True)
    index = {
        "generated_at": utcnow_iso(),
        "shows": [
            {"slug": s["slug"], "name": s["name"], "publisher": s.get("publisher", ""),
             "color": s.get("color", "#555"), "homepage": s.get("homepage", "")}
            for s in shows
        ],
        "episodes": items,
    }
    write_json(INDEX_PATH, index)
    return index
