"""RSS parsing with Podcasting 2.0 <podcast:transcript> support.

Only the standard library XML parser is used; namespaces are matched by local
name so feeds that use an unusual namespace URI for `podcast:` still work.
"""
from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Iterable

from .util import log


@dataclass
class TranscriptRef:
    url: str
    type: str = ""
    language: str = ""
    rel: str = ""

    @property
    def kind(self) -> str:
        t = (self.type or "").lower()
        u = self.url.lower()
        if "vtt" in t or u.endswith(".vtt") or "format=webvtt" in u:
            return "vtt"
        if "srt" in t or "subrip" in t or u.endswith(".srt") or "format=subrip" in u:
            return "srt"
        if "json" in t or u.endswith(".json"):
            return "json"
        if "html" in t:
            return "html"
        if "text/plain" in t or "textwithtimestamps" in u or u.endswith(".txt"):
            return "text"
        return "unknown"


# Preferred order: cue files with timestamps first.
KIND_RANK = {"vtt": 0, "srt": 1, "json": 2, "text": 3, "html": 4, "unknown": 9}


@dataclass
class Episode:
    guid: str
    title: str
    published_at: datetime
    duration_sec: int | None
    audio_url: str | None
    audio_type: str | None
    link: str | None
    description_html: str
    image_url: str | None
    episode_number: str | None
    transcripts: list[TranscriptRef] = field(default_factory=list)

    @property
    def best_transcript(self) -> TranscriptRef | None:
        if not self.transcripts:
            return None
        return sorted(self.transcripts, key=lambda t: KIND_RANK.get(t.kind, 9))[0]

    @property
    def published_iso(self) -> str:
        return self.published_at.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _child_text(item: ET.Element, *names: str) -> str | None:
    """First non-empty text among children whose local name is in `names` (in order)."""
    wanted = [n.lower() for n in names]
    found: dict[str, str] = {}
    for child in item:
        name = _local(child.tag)
        if name in wanted and child.text and child.text.strip() and name not in found:
            found[name] = child.text.strip()
    for n in wanted:
        if n in found:
            return found[n]
    return None


def parse_duration(raw: str | None) -> int | None:
    if not raw:
        return None
    raw = raw.strip()
    if re.fullmatch(r"\d+(\.\d+)?", raw):
        return int(float(raw))
    parts = raw.split(":")
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        return None
    if len(nums) == 3:
        return int(nums[0] * 3600 + nums[1] * 60 + nums[2])
    if len(nums) == 2:
        return int(nums[0] * 60 + nums[1])
    return None


def parse_pubdate(raw: str | None) -> datetime:
    if raw:
        try:
            dt = parsedate_to_datetime(raw.strip())
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (TypeError, ValueError):
            pass
        try:
            dt = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _description(item: ET.Element) -> str:
    # Prefer the richest HTML body available.
    for name in ("encoded", "description", "summary", "subtitle"):
        for child in item:
            if _local(child.tag) == name and child.text and child.text.strip():
                return child.text.strip()
    return ""


def parse_feed(xml_text: str) -> tuple[dict, list[Episode]]:
    """Return (channel_meta, episodes newest-first)."""
    # Some feeds carry stray control characters that ElementTree rejects.
    xml_text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", xml_text)
    root = ET.fromstring(xml_text)
    channel = root.find("channel")
    if channel is None:
        raise ValueError("not an RSS 2.0 feed (no <channel>)")

    meta = {
        "title": _child_text(channel, "title") or "",
        "link": _child_text(channel, "link") or "",
        "description": _description(channel),
        "image": None,
    }
    for child in channel:
        if _local(child.tag) == "image":
            href = child.get("href")
            if href:
                meta["image"] = href
            else:
                url = _child_text(child, "url")
                if url:
                    meta["image"] = url

    episodes: list[Episode] = []
    for item in channel.findall("item"):
        title = _child_text(item, "title") or "(untitled)"
        guid = _child_text(item, "guid")
        enclosure_url = enclosure_type = None
        transcripts: list[TranscriptRef] = []
        image_url = None
        for child in item:
            name = _local(child.tag)
            if name == "enclosure":
                enclosure_url = child.get("url")
                enclosure_type = child.get("type")
            elif name == "transcript":
                url = child.get("url")
                if url:
                    transcripts.append(
                        TranscriptRef(
                            url=html.unescape(url),
                            type=child.get("type") or "",
                            language=child.get("language") or "",
                            rel=child.get("rel") or "",
                        )
                    )
            elif name == "image" and child.get("href"):
                image_url = child.get("href")
        if not guid:
            guid = enclosure_url or f"{title}|{_child_text(item, 'pubDate')}"
        episodes.append(
            Episode(
                guid=guid,
                title=html.unescape(title),
                published_at=parse_pubdate(_child_text(item, "pubDate")),
                duration_sec=parse_duration(_child_text(item, "duration")),
                audio_url=enclosure_url,
                audio_type=enclosure_type,
                link=_child_text(item, "link"),
                description_html=_description(item),
                image_url=image_url or meta["image"],
                episode_number=_child_text(item, "episode"),
                transcripts=transcripts,
            )
        )
    episodes.sort(key=lambda e: e.published_at, reverse=True)
    log.debug("parsed feed %r: %d items, %d with transcripts", meta["title"], len(episodes),
              sum(1 for e in episodes if e.transcripts))
    return meta, episodes


def strip_html(text: str, limit: int | None = None) -> str:
    text = re.sub(r"<br\s*/?>|</p>|</li>|</div>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    if limit and len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] + "…"
    return text


def iter_eligible(episodes: Iterable[Episode], max_minutes: int | None) -> Iterable[Episode]:
    for ep in episodes:
        if max_minutes and ep.duration_sec and ep.duration_sec > max_minutes * 60:
            continue
        yield ep
