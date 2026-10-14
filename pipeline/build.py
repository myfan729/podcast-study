"""Write per-episode JSON and the site index consumed by docs/*.html.

Access model: individual episode pages are public (shareable links whose ids carry an unguessable token),
the episode LIST is private — docs/data/index.enc.json is encrypted with SITE_PASSWORD (AES-256-GCM,
PBKDF2-SHA256) and decrypted in the browser after the owner types the password.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from pathlib import Path

from .util import read_json, utcnow_iso, write_json, write_json_if_changed

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
DATA = DOCS / "data"
EPISODES_DIR = DATA / "episodes"
INDEX_PATH = DATA / "index.json"
INDEX_ENC_PATH = DATA / "index.enc.json"
PBKDF2_ITER = 250_000


def site_password() -> str | None:
    return os.environ.get("SITE_PASSWORD") or None


def id_token(key: str) -> str:
    """7 unguessable characters appended to an episode id, stable across runs (HMAC of the episode key)."""
    pw = site_password()
    if not pw:
        return ""
    digest = hmac.new(pw.encode("utf-8"), ("id:" + key).encode("utf-8"), hashlib.sha256).digest()
    return base64.b32encode(digest).decode("ascii").lower().rstrip("=")[:7]


def episode_path(episode_id: str) -> Path:
    return EPISODES_DIR / f"{episode_id}.json"


def write_episode(doc: dict) -> Path:
    path = episode_path(doc["id"])
    write_json(path, doc, compact=True)
    return path


def encrypt_json(obj, password: str) -> dict:
    import json
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    salt, iv = secrets.token_bytes(16), secrets.token_bytes(12)
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=PBKDF2_ITER).derive(password.encode("utf-8"))
    ct = AESGCM(key).encrypt(iv, json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), None)
    b64 = lambda b: base64.b64encode(b).decode("ascii")  # noqa: E731
    return {"v": 1, "kdf": "PBKDF2-SHA256", "iter": PBKDF2_ITER, "salt": b64(salt), "iv": b64(iv), "ct": b64(ct)}


def rebuild_index(shows: list[dict]) -> dict:
    """Scan docs/data/episodes/*.json and regenerate the index (newest first) — encrypted when a site
    password is configured, plain otherwise."""
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
            "has_translation": bool(study.get("translations") or study.get("translations_sent")),
            "mock": bool(study.get("mock")),
            "demo": bool(doc.get("demo")),
        })
    items.sort(key=lambda x: x["published_at"], reverse=True)
    index = {
        "generated_at": utcnow_iso(),
        "shows": [
            {"slug": s["slug"], "name": s["name"], "publisher": s.get("publisher", ""),
             "color": s.get("color", "#555"), "homepage": s.get("homepage", "")}
            for s in shows if s.get("enabled", True)
        ],
        "episodes": items,
    }
    pw = site_password()
    if pw:
        # the ciphertext differs on every run (fresh salt/IV): rewrite only when the content changed
        # (keyed by the password too, so changing the password re-encrypts)
        src = hmac.new(pw.encode("utf-8"), json.dumps({k: v for k, v in index.items() if k != "generated_at"},
                       ensure_ascii=False, sort_keys=True).encode("utf-8"), hashlib.sha256).hexdigest()[:16]
        old = read_json(INDEX_ENC_PATH, None) if INDEX_ENC_PATH.exists() else None
        if not old or old.get("src") != src:
            write_json(INDEX_ENC_PATH, dict(encrypt_json(index, pw), src=src), compact=True)
        if INDEX_PATH.exists():
            INDEX_PATH.unlink()
    else:
        write_json_if_changed(INDEX_PATH, index)
        if INDEX_ENC_PATH.exists():
            INDEX_ENC_PATH.unlink()
    return index
