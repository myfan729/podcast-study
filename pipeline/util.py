"""Small shared helpers: HTTP session, slugs, time formatting, JSON IO."""
from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

log = logging.getLogger("podcast-study")

USER_AGENT = "podcast-study/1.0 (+https://github.com/; personal English-study tool)"


def http_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept": "*/*"})
    return s


def http_get_text(session: requests.Session, url: str, timeout: int = 40) -> str:
    """GET a text resource following redirects. Raises for HTTP errors."""
    r = session.get(url, timeout=timeout, allow_redirects=True)
    r.raise_for_status()
    # Transcript files are usually UTF-8 but servers rarely say so.
    if not r.encoding or r.encoding.lower() in ("iso-8859-1", "ascii"):
        r.encoding = "utf-8"
    return r.text


def resolve_final_url(session: requests.Session, url: str, timeout: int = 30) -> str:
    """Follow the tracking-redirect chain (podtrac → swap.fm → CDN) and return the final URL.

    Falls back to the original URL when the chain cannot be resolved; the browser
    will follow redirects itself in that case.
    """
    try:
        r = session.head(url, timeout=timeout, allow_redirects=True)
        if r.status_code < 400 and r.url:
            return r.url
    except requests.RequestException:
        pass
    try:
        with session.get(url, timeout=timeout, allow_redirects=True, stream=True) as r:
            if r.status_code < 400 and r.url:
                return r.url
    except requests.RequestException:
        pass
    return url


def slugify(text: str, max_len: int = 70) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    if len(text) > max_len:
        text = text[:max_len].rsplit("-", 1)[0]
    return text or "episode"


def fmt_clock(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: Any, compact: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        if compact:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        else:
            json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def write_json_if_changed(path: Path, data: Any, compact: bool = False, ignore: tuple = ("generated_at", "updated_at")) -> bool:
    """Write only when something other than the timestamps changed (idle runs then have nothing to commit)."""
    def strip(d):
        return {k: v for k, v in d.items() if k not in ignore} if isinstance(d, dict) else d
    old = read_json(path, None) if path.exists() else None
    if old is not None and strip(old) == strip(json.loads(json.dumps(data, ensure_ascii=False))):
        return False
    write_json(path, data, compact=compact)
    return True


def setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
