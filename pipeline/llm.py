"""Study-pack generation with the Claude API (structured JSON output), plus a mock mode.

Two calls per episode:
  1. generate_study_pack  → summary, speakers, chapters, expressions, vocab, discussion questions,
                            shadowing picks (one JSON object following STUDY_SCHEMA)
  2. translate_segments   → Korean rendering of every transcript segment (chunked)
"""
from __future__ import annotations

import json
import os
import random
import re
import time
from typing import Any

from .transcript import Segment
from .util import fmt_clock, log

DEFAULT_MODEL = os.environ.get("STUDY_MODEL") or "claude-sonnet-5-5"
TRANSLATE_MODEL = os.environ.get("TRANSLATE_MODEL") or DEFAULT_MODEL
INTRO_MODEL = os.environ.get("INTRO_MODEL") or "claude-haiku-5-5"      # one-line Korean intros (cheap)

# ---------------------------------------------------------------------------
# JSON schemas (Claude structured outputs: every property required, no min/max)
# ---------------------------------------------------------------------------

def _str_list() -> dict:
    return {"type": "array", "items": {"type": "string"}}


STUDY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "speakers", "speaker_assignments", "one_liner_ko", "summary_ko", "summary_en",
        "chapters", "expressions", "vocab", "discussion", "shadowing", "difficulty", "tags",
    ],
    "properties": {
        "speakers": {
            "type": "array",
            "description": "Who the publisher's speaker labels refer to (for generic labels like 'Speaker 1'). Empty if the transcript has no labels.",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["label", "name", "role"],
                "properties": {
                    "label": {"type": "string", "description": "Label exactly as in the transcript, e.g. 'Speaker 2'"},
                    "name": {"type": "string", "description": "Person's name if identifiable from context, else a short stand-in like 'Guest (economist)' or 'Announcer' — at most 4 words"},
                    "role": {"type": "string", "description": "host | reporter | guest | narrator | ad | other"},
                },
            },
        },
        "speaker_assignments": {
            "type": "array",
            "description": "ONLY when the transcript has NO speaker labels: for every segment id, who is speaking. Otherwise empty.",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["segment_id", "speaker"],
                "properties": {
                    "segment_id": {"type": "string"},
                    "speaker": {"type": "string", "description": "Short display name, e.g. 'Matt Abrahams (host)' or 'Daniel Lubetzky'"},
                },
            },
        },
        "one_liner_ko": {"type": "string", "description": "에피소드를 한 문장(한국어)으로"},
        "summary_ko": {"type": "array", "description": "핵심 내용 4~6개 불릿(한국어, 각 1~2문장)", "items": {"type": "string"}},
        "summary_en": {"type": "string", "description": "80-120 word English summary in natural spoken register the learner could say aloud"},
        "chapters": {
            "type": "array",
            "description": "4-7 chapters that follow the episode's structure",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["title_en", "title_ko", "segment_id"],
                "properties": {
                    "title_en": {"type": "string"},
                    "title_ko": {"type": "string"},
                    "segment_id": {"type": "string", "description": "id of the segment where the chapter starts"},
                },
            },
        },
        "expressions": {
            "type": "array",
            "description": "high-value spoken expressions actually used in the episode (how many: see the instructions)",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["expression", "type", "segment_id", "quote", "meaning_ko", "nuance_ko", "examples", "similar"],
                "properties": {
                    "expression": {"type": "string", "description": "The expression in its base/dictionary form, e.g. 'blow one's mind'"},
                    "type": {"type": "string", "enum": ["idiom", "collocation", "phrasal_verb", "discourse_marker", "pattern", "vocabulary"]},
                    "segment_id": {"type": "string", "description": "segment where it occurs"},
                    "quote": {"type": "string", "description": "EXACT substring copied from that segment's text containing the expression (<= 15 words, keep original casing/punctuation)"},
                    "meaning_ko": {"type": "string", "description": "뜻(한국어), 간결하게"},
                    "nuance_ko": {"type": "string", "description": "뉘앙스·격식 수준·언제 쓰는지·주의점(한국어 2~3문장)"},
                    "examples": {"type": "array", "description": "3 natural spoken English example sentences in varied everyday/business contexts", "items": {"type": "string"}},
                    "similar": {
                        "type": "array",
                        "description": "2 alternative expressions with similar meaning, each with its own example",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["expression", "example"],
                            "properties": {"expression": {"type": "string"}, "example": {"type": "string"}},
                        },
                    },
                },
            },
        },
        "vocab": {
            "type": "array",
            "description": "single words worth learning (C1+), not already covered in expressions (how many: see the instructions)",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["word", "ipa", "pos", "meaning_ko", "example"],
                "properties": {
                    "word": {"type": "string"},
                    "ipa": {"type": "string", "description": "pronunciation in IPA between slashes, General American, e.g. /ˈɪn.də.ɡoʊ/"},
                    "pos": {"type": "string", "description": "part of speech, e.g. n., v., adj."},
                    "meaning_ko": {"type": "string"},
                    "example": {"type": "string"},
                },
            },
        },
        "discussion": {
            "type": "object",
            "additionalProperties": False,
            "required": ["warmup", "opinion", "debate", "roleplay", "useful_phrases"],
            "properties": {
                "warmup": {
                    "type": "array",
                    "description": "3 comprehension questions answerable from the episode",
                    "items": {"type": "object", "additionalProperties": False, "required": ["q", "hint_ko"],
                              "properties": {"q": {"type": "string"}, "hint_ko": {"type": "string", "description": "답변 포인트 힌트(한국어)"}}},
                },
                "opinion": {
                    "type": "array",
                    "description": "3 open questions asking for the learner's own view/experience",
                    "items": {"type": "object", "additionalProperties": False, "required": ["q", "hint_ko"],
                              "properties": {"q": {"type": "string"}, "hint_ko": {"type": "string"}}},
                },
                "debate": {
                    "type": "array",
                    "description": "2 debatable propositions with one strong argument for each side",
                    "items": {"type": "object", "additionalProperties": False, "required": ["q", "for", "against"],
                              "properties": {"q": {"type": "string"}, "for": {"type": "string"}, "against": {"type": "string"}}},
                },
                "roleplay": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["scenario", "your_role", "partner_role", "goals"],
                    "properties": {
                        "scenario": {"type": "string"},
                        "your_role": {"type": "string"},
                        "partner_role": {"type": "string"},
                        "goals": {"type": "array", "description": "2-3 things the learner must accomplish in the conversation", "items": {"type": "string"}},
                    },
                },
                "useful_phrases": {
                    "type": "array",
                    "description": "8 sentence starters / discourse moves for discussing this topic, with Korean gloss",
                    "items": {"type": "object", "additionalProperties": False, "required": ["phrase", "ko"],
                              "properties": {"phrase": {"type": "string"}, "ko": {"type": "string"}}},
                },
            },
        },
        "shadowing": {
            "type": "array",
            "description": "3 segments that are ideal for shadowing (clear, rhythmic, idiomatic)",
            "items": {"type": "object", "additionalProperties": False, "required": ["segment_id", "reason_ko"],
                      "properties": {"segment_id": {"type": "string"}, "reason_ko": {"type": "string"}}},
        },
        "difficulty": {
            "type": "object",
            "additionalProperties": False,
            "required": ["cefr", "note_ko"],
            "properties": {"cefr": {"type": "string", "enum": ["B2", "C1", "C2"]}, "note_ko": {"type": "string"}},
        },
        "tags": {"type": "array", "description": "3-6 short topic tags in English", "items": {"type": "string"}},
    },
}

TRANSLATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["translations"],
    "properties": {
        "translations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "ko"],
                "properties": {"id": {"type": "string"}, "ko": {"type": "string"}},
            },
        }
    },
}

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

SYSTEM_STUDY = """You are an elite English-speaking coach preparing study material for ONE learner.

Learner profile
- Korean professional (finance/economics/international affairs) living abroad; English is already advanced (C1).
- Goal: "weapon-level" spoken English for panels, meetings and sharp conversation — natural idiom, crisp
  argument framing, confident register control. Not test prep.
- Explanations are written in Korean (concise, 존댓말 없이 간결한 설명체, e.g. "~라는 뜻", "~할 때 쓴다").
  All English examples are in natural SPOKEN English (what people actually say), not textbook prose.

Hard rules
1. Expressions and quotes must come from the transcript. `quote` is an EXACT substring of the segment text
   you cite (copy characters verbatim; <= 15 words). `segment_id` must be that segment's id.
2. Prefer expressions a professional would reuse in conversation: idioms, collocations, discourse markers,
   phrasal verbs, rhetorical patterns ("the fact that…", "it's not X, it's Y"). Skip proper nouns, slang
   that doesn't travel, and anything a C1 learner already knows (e.g. "in order to").
3. Example sentences: everyday life, workplace, meetings, travel, news, friends — vary them. NEVER use
   development-finance, ODA, aid-agency or development-bank contexts in examples.
4. Ignore sponsor reads / ads / intro-outro boilerplate when summarizing and selecting expressions.
5. Discussion questions should be answerable by speaking for 1-3 minutes; `hint_ko` gives content hints,
   not sample answers. Debate items need a real tension. The roleplay should let the learner practice the
   episode's expressions.
6. Korean summaries explain the content to someone who hasn't listened; summary_en should sound like the
   learner retelling the episode to a colleague.
7. Output ONLY the JSON object that matches the schema."""


def _speaker_instruction(speaker_mode: str) -> str:
    if speaker_mode == "generic":
        return (
            "Speaker labels are generic ('Speaker 1'…). Fill `speakers` by inferring each label's real name/role "
            "from context (self-introductions, how others address them). Keep `speaker_assignments` EMPTY."
        )
    if speaker_mode == "none":
        return (
            "The transcript has NO speaker labels. Fill `speaker_assignments` with one entry for EVERY segment id "
            "(host vs guest, by content and turn-taking; monologue episodes are all host). Keep `speakers` EMPTY."
        )
    return "Speaker labels are real names; keep `speakers` and `speaker_assignments` EMPTY."


def render_transcript(segments: list[Segment]) -> str:
    lines = []
    for s in segments:
        spk = f" ({s.speaker})" if s.speaker else ""
        lines.append(f"{s.id} [{fmt_clock(s.start)}]{spk}: {s.text}")
    return "\n".join(lines)


def study_counts(duration_sec: float | None) -> tuple[int, int]:
    """How many expressions and words to pick: grows gently with the episode's length, 30 at most.
    6 min → 10/7, 20 min → 14/11, 30 → 17/14, 45 → 22/18, 60 → 26/23, 70+ → 29/26."""
    m = max(0.0, (duration_sec or 0) / 60)
    return min(30, max(8, round(8 + 0.3 * m))), min(30, max(6, round(5 + 0.3 * m)))


def build_study_prompt(meta: dict, show: dict, segments: list[Segment], speaker_mode: str) -> str:
    desc = (meta.get("description_text") or "").strip()
    n_expr, n_vocab = study_counts(meta.get("duration_sec") or (segments[-1].end if segments else 0))
    level_line = (f" Target level of the show: {show['level']} — still pick the most useful natural expressions "
                  f"for an advanced learner, and say in difficulty.note_ko who this episode suits." if show.get("level") else "")
    return (
        f"PODCAST: {show['name']} ({show.get('publisher', '')}). {show.get('style', '')}{level_line}\n"
        f"EPISODE: {meta['title']} — published {meta['published_at'][:10]}, {fmt_clock(meta.get('duration_sec') or 0)} long.\n"
        f"SHOW NOTES: {desc[:1200]}\n\n"
        f"SPEAKERS: {_speaker_instruction(speaker_mode)}\n\n"
        "TRANSCRIPT (one segment per line: id [mm:ss] (speaker): text)\n"
        "-----\n"
        f"{render_transcript(segments)}\n"
        "-----\n\n"
        f"Produce the study pack JSON now. Aim for {n_expr} expressions and {n_vocab} vocab (spread across the whole episode), 4-7 chapters, 3 shadowing picks.\n\n"
        "Return ONE JSON object with exactly this shape (keys and types; strings in <> describe the content):\n"
        f"{schema_skeleton(STUDY_SCHEMA)}\n"
        "No markdown fences, no commentary before or after the JSON."
    )


def schema_skeleton(schema: dict) -> str:
    """Render a JSON-schema as a compact example document the model can mirror."""

    def walk(node: dict):
        t = node.get("type")
        if t == "object":
            return {k: walk(v) for k, v in node.get("properties", {}).items()}
        if t == "array":
            items = dict(node.get("items", {"type": "string"}))
            if node.get("description") and not items.get("description") and items.get("type") != "object":
                items["description"] = node["description"]
            return [walk(items)]
        if "enum" in node:
            return "|".join(str(e) for e in node["enum"])
        desc = node.get("description")
        return f"<{desc}>" if desc else f"<{t or 'string'}>"

    return json.dumps(walk(schema), ensure_ascii=False, indent=1)


SYSTEM_TRANSLATE = """You translate podcast transcript lines from English into natural Korean for an advanced learner.
- Each line is one sentence (or a short group of sentences) in order; use the surrounding lines for context,
  but translate each line on its own so the learner can read English and Korean sentence by sentence.
- Preserve meaning and tone; use 자연스러운 구어체 (대화체) rather than stiff 문어체.
- Keep names, companies and numbers as in the source. Do not add notes or brackets.
- Return one translation per line id, same ids, nothing else."""


def build_translate_prompt(items: list[tuple[str, str]]) -> str:
    lines = [f"{i}: {t}" for i, t in items]
    return "LINES\n" + "\n".join(lines) + "\n\nTranslate each line into Korean."


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class StudyGenerator:
    def __init__(self, mock: bool = False, model: str = DEFAULT_MODEL, translate_model: str = TRANSLATE_MODEL):
        self.mock = mock
        self.model = model
        self.translate_model = translate_model
        self._client_obj = None

    @property
    def _client(self):
        """Create the API client on first use so offline/mock runs never need a key."""
        if self._client_obj is None:
            import anthropic  # imported lazily so tests run without the SDK

            api_key = os.environ.get("ANTHROPIC_API_KEY")
            if not api_key:
                raise RuntimeError("ANTHROPIC_API_KEY is not set (use --mock for a dry run)")
            self._client_obj = anthropic.Anthropic(api_key=api_key)
        return self._client_obj

    # -- public ---------------------------------------------------------------
    def generate_study_pack(self, meta: dict, show: dict, segments: list[Segment], speaker_mode: str) -> dict:
        if self.mock:
            return mock_study_pack(meta, segments, speaker_mode)
        prompt = build_study_prompt(meta, show, segments, speaker_mode)
        # The study-pack schema is too large for the API's constrained-decoding grammar, so this call
        # asks for plain JSON (shape given in the prompt) and validates/repairs the result itself.
        data = self._call_json(self.model, SYSTEM_STUDY, prompt, STUDY_SCHEMA, max_tokens=21000, strict=False)   # up to 30+30 items (above ~21k the SDK insists on streaming)
        return postprocess_study_pack(data, segments)

    def translate_items(self, items: list[tuple[str, str]], chunk: int = 40) -> dict[str, str]:
        """Korean for each (id, english) line — used for cues (sentences) and, formerly, segments."""
        if self.mock:
            return {i: f"[번역 자리표시자] {t[:60]}…" for i, t in items}
        out: dict[str, str] = {}
        parts = [items[k:k + chunk] for k in range(0, len(items), chunk)]
        call = lambda part: self._call_json(self.translate_model, SYSTEM_TRANSLATE, build_translate_prompt(part),  # noqa: E731
                                            TRANSLATION_SCHEMA, max_tokens=16000)
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=4) as pool:                     # chunks in parallel
            results = list(pool.map(call, parts))
        for data in results:
            for row in data.get("translations", []):
                if row.get("id") and row.get("ko"):
                    out[str(row["id"])] = row["ko"].strip()
        missing = [i for i, _ in items if i not in out]
        if missing:
            log.warning("translation missing for %d lines (%s…)", len(missing), ", ".join(missing[:5]))
        return out

    def short_intros(self, items: list[tuple[str, str]], what: str) -> dict[str, str]:
        """One short Korean line per item (a show or an episode), from its title + publisher description."""
        if self.mock:
            return {i: f"[소개 자리표시자] {t[:30]}" for i, t in items}
        limit = "40자" if what == "show" else "45자"
        system = (f"You write very short Korean introductions for English podcast {'shows' if what == 'show' else 'episodes'} "
                  f"in a Korean English-learning app. For each item write ONE natural Korean line (at most {limit}) saying what it is "
                  "about, so a learner can decide whether to listen. No hype, no emoji, no quotes, no English unless it is a name. "
                  "Use only facts in the given text; skip ads, sponsor reads and calls to subscribe.")
        user = "\n\n".join(f"[{i}]\n{t[:700]}" for i, t in items)
        schema = {"type": "object", "additionalProperties": False, "required": ["items"],
                  "properties": {"items": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                 "required": ["id", "ko"], "properties": {"id": {"type": "string"}, "ko": {"type": "string"}}}}}}
        data = self._call_json(INTRO_MODEL, system, user, schema, max_tokens=8000)
        return {str(r["id"]): r["ko"].strip() for r in data.get("items", []) if r.get("id") and r.get("ko")}

    def ipa(self, words: list[str]) -> dict[str, str]:
        """IPA (General American, between slashes) for words in packs made before vocab had it."""
        if self.mock or not words:
            return {w: "/…/" for w in words}
        schema = {"type": "object", "additionalProperties": False, "required": ["items"],
                  "properties": {"items": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                 "required": ["word", "ipa"], "properties": {"word": {"type": "string"}, "ipa": {"type": "string"}}}}}}
        data = self._call_json(INTRO_MODEL, "Give the IPA pronunciation (General American, between slashes, with stress marks) "
                               "of each English word.", "\n".join(words), schema, max_tokens=4000)
        return {r["word"]: r["ipa"].strip() for r in data.get("items", []) if r.get("word") and r.get("ipa")}

    def translate_segments(self, segments: list[Segment]) -> dict[str, str]:
        return self.translate_items([(s.id, s.text) for s in segments])

    def translate_sentences(self, cues, sentences: list[list[int]]) -> dict[str, str]:
        """{"from-to": Korean} for each sentence (a run of cues), for the interleaved transcript view."""
        by_i = {(c.i if hasattr(c, "i") else c["i"]): (c.t if hasattr(c, "t") else c["t"]) for c in cues}
        items = [(f"{a}-{b}", " ".join(by_i[i] for i in range(a, b + 1) if i in by_i)) for a, b in sentences]
        return self.translate_items(items)

    # -- internals ------------------------------------------------------------
    _plain_schemas: set[int] = set()  # schemas the API refused to compile → plain JSON from then on

    def _call_json(self, model: str, system: str, user: str, schema: dict, max_tokens: int, strict: bool = True) -> dict:
        """One JSON-producing call. strict=True uses the API's JSON-schema output; if the API rejects the
        schema (grammar too large) or strict=False, the model is asked for plain JSON which is parsed,
        validated against `schema` and repaired once if needed."""
        import anthropic

        use_strict = strict and id(schema) not in self._plain_schemas
        messages = [{"role": "user", "content": user}]
        delay = 5.0
        last_err: Exception | None = None
        for attempt in range(1, 6):
            try:
                kwargs = dict(model=model, max_tokens=max_tokens, system=system, messages=messages)
                if use_strict:
                    kwargs["output_config"] = {"format": {"type": "json_schema", "schema": schema}}
                resp = self._client.messages.create(**kwargs)
                if resp.stop_reason == "max_tokens":
                    raise RuntimeError("response truncated (max_tokens); will retry next run")
                if resp.stop_reason == "refusal":
                    raise RuntimeError("model refused the request")
                text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
                usage = getattr(resp, "usage", None)
                if usage:
                    log.info("  %s: %s in / %s out tokens%s", model, usage.input_tokens, usage.output_tokens,
                             "" if use_strict else " (plain JSON)")
                data = extract_json(text)
                problems = validate(schema, data)
                if problems and not use_strict:
                    if len(messages) >= 3:
                        raise RuntimeError("JSON still invalid after repair: " + "; ".join(problems[:5]))
                    log.warning("  JSON shape problems (%d) — asking the model to repair: %s", len(problems), problems[:3])
                    messages = messages + [
                        {"role": "assistant", "content": text},
                        {"role": "user", "content": "Your JSON has these problems:\n- " + "\n- ".join(problems[:20])
                         + "\nReturn the complete corrected JSON object only."},
                    ]
                    continue
                return data
            except (anthropic.RateLimitError, anthropic.APIConnectionError, anthropic.InternalServerError) as e:
                last_err = e
                log.warning("  API transient error (attempt %d): %s — retrying in %.0fs", attempt, e, delay)
                time.sleep(delay)
                delay = min(delay * 2, 60)
            except anthropic.APIStatusError as e:
                msg = str(e.message)
                if use_strict and e.status_code == 400 and ("grammar" in msg.lower() or "schema" in msg.lower()):
                    log.warning("  API rejected the JSON schema (%s) — switching this call to plain JSON", msg[:80])
                    self._plain_schemas.add(id(schema))
                    use_strict = False
                    continue
                raise RuntimeError(f"API error {e.status_code}: {msg}") from e
            except ValueError as e:  # JSON could not be parsed at all
                if use_strict or len(messages) >= 3:
                    raise RuntimeError(f"unparseable JSON from model: {e}") from e
                log.warning("  unparseable JSON — asking the model to resend valid JSON")
                messages = messages + [{"role": "assistant", "content": text},
                                       {"role": "user", "content": "That was not valid JSON. Return the complete JSON object only."}]
                continue
        raise RuntimeError(f"API failed after retries: {last_err}")


def extract_json(text: str) -> dict:
    """Parse a JSON object from model text, tolerating code fences and stray prose around it."""
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    start, end = t.find("{"), t.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object found")
    try:
        return json.loads(t[start:end + 1])
    except json.JSONDecodeError as e:
        raise ValueError(str(e)) from e


def validate(schema: dict, data, path: str = "$") -> list[str]:
    """Minimal JSON-schema check (types, required keys, enums). Returns a list of problems."""
    problems: list[str] = []
    t = schema.get("type")
    if t == "object":
        if not isinstance(data, dict):
            return [f"{path}: expected object"]
        for key in schema.get("required", []):
            if key not in data:
                problems.append(f"{path}.{key}: missing")
        for key, sub in schema.get("properties", {}).items():
            if key in data:
                problems += validate(sub, data[key], f"{path}.{key}")
    elif t == "array":
        if not isinstance(data, list):
            return [f"{path}: expected array"]
        for i, item in enumerate(data[:200]):
            problems += validate(schema.get("items", {}), item, f"{path}[{i}]")
    elif t == "string":
        if not isinstance(data, str):
            problems.append(f"{path}: expected string")
        elif "enum" in schema and data.lower() not in [str(e).lower() for e in schema["enum"]]:
            problems.append(f"{path}: must be one of {schema['enum']}")
    elif t in ("number", "integer"):
        if not isinstance(data, (int, float)) or isinstance(data, bool):
            problems.append(f"{path}: expected number")
    elif t == "boolean":
        if not isinstance(data, bool):
            problems.append(f"{path}: expected boolean")
    return problems


# ---------------------------------------------------------------------------
# Post-processing & mock
# ---------------------------------------------------------------------------

_QUOTE_MAP = str.maketrans({"\u2019": "'", "\u2018": "'", "\u201c": '"', "\u201d": '"', "\u2013": "-", "\u2014": "-"})


def find_exact(haystack: str, needle: str) -> str | None:
    """Return the exact substring of `haystack` that matches `needle` ignoring case,
    quote style and whitespace differences; None if absent."""
    if not needle:
        return None
    pattern = r"\s+".join(re.escape(w) for w in needle.translate(_QUOTE_MAP).split())
    # allow either straight or curly apostrophes/quotes in the source
    pattern = pattern.replace("'", "['\u2019\u2018]").replace('"', '["\u201c\u201d]')
    m = re.search(pattern, haystack, re.I)
    return m.group(0) if m else None


def postprocess_study_pack(data: dict, segments: list[Segment]) -> dict:
    """Validate ids/quotes against the transcript so the page can rely on them."""
    seg_by_id = {s.id: s for s in segments}
    valid_ids = set(seg_by_id)

    def fix_segment_id(sid: str, quote: str | None = None) -> str:
        if sid in valid_ids and (not quote or find_exact(seg_by_id[sid].text, quote)):
            return sid
        if quote:
            for s in segments:
                if find_exact(s.text, quote):
                    return s.id
        return sid if sid in valid_ids else (segments[0].id if segments else sid)

    for ex in data.get("expressions", []):
        quote = (ex.get("quote") or "").strip()
        ex["segment_id"] = fix_segment_id(ex.get("segment_id", ""), quote)
        seg = seg_by_id.get(ex["segment_id"])
        exact = find_exact(seg.text, quote) if seg else None
        if exact:
            ex["quote"] = exact
        elif seg:
            # Fall back to the expression itself if the quote drifted.
            exact = find_exact(seg.text, ex.get("expression", ""))
            if exact:
                ex["quote"] = exact
            else:
                ex["quote_unmatched"] = True
    for ch in data.get("chapters", []):
        ch["segment_id"] = fix_segment_id(ch.get("segment_id", ""))
    for sh in data.get("shadowing", []):
        sh["segment_id"] = fix_segment_id(sh.get("segment_id", ""))
    data["speaker_assignments"] = [a for a in data.get("speaker_assignments", []) if a.get("segment_id") in valid_ids]
    return data


def mock_study_pack(meta: dict, segments: list[Segment], speaker_mode: str) -> dict:
    """Deterministic placeholder content so the site can be built and tested without API access."""
    rnd = random.Random(meta.get("title", ""))
    pick = lambda n: [segments[i] for i in sorted(rnd.sample(range(len(segments)), min(n, len(segments))))]
    exprs = []
    for s in pick(6):
        words = s.text.split()
        k = min(len(words), rnd.randint(2, 4))
        start = rnd.randint(0, max(0, len(words) - k))
        quote = " ".join(words[start:start + k])
        exprs.append({
            "expression": quote.lower().strip(",.?!\"'"),
            "type": rnd.choice(["idiom", "collocation", "phrasal_verb", "discourse_marker", "pattern", "vocabulary"]),
            "segment_id": s.id,
            "quote": quote,
            "meaning_ko": "(mock) 뜻 설명 자리표시자",
            "nuance_ko": "(mock) 뉘앙스·격식·사용 맥락 설명 자리표시자. 실제 실행에서는 Claude API가 채웁니다.",
            "examples": ["(mock) Example sentence one.", "(mock) Example sentence two.", "(mock) Example sentence three."],
            "similar": [{"expression": "(mock) alternative A", "example": "(mock) Example with A."},
                        {"expression": "(mock) alternative B", "example": "(mock) Example with B."}],
        })
    chapters = [{"title_en": f"Chapter {i + 1}", "title_ko": f"챕터 {i + 1}", "segment_id": s.id}
                for i, s in enumerate(pick(4))]
    speakers, assignments = [], []
    labels = sorted({s.speaker for s in segments if s.speaker})
    if speaker_mode == "generic":
        speakers = [{"label": l, "name": f"(mock) Person {n + 1}", "role": "host" if n == 0 else "guest"}
                    for n, l in enumerate(labels)]
    elif speaker_mode == "none":
        assignments = [{"segment_id": s.id, "speaker": "(mock) Host" if i % 2 == 0 else "(mock) Guest"}
                       for i, s in enumerate(segments)]
    return {
        "speakers": speakers,
        "speaker_assignments": assignments,
        "one_liner_ko": f"(mock) '{meta.get('title', '')}' 에피소드 한 줄 요약 자리표시자",
        "summary_ko": ["(mock) 요약 불릿 1", "(mock) 요약 불릿 2", "(mock) 요약 불릿 3", "(mock) 요약 불릿 4"],
        "summary_en": "(mock) English summary placeholder. In a real run this is an 80-120 word retelling of the episode.",
        "chapters": chapters,
        "expressions": exprs,
        "vocab": [{"word": "(mock) word", "pos": "n.", "meaning_ko": "뜻", "example": "(mock) Example."} for _ in range(3)],
        "discussion": {
            "warmup": [{"q": "(mock) What is the episode mainly about?", "hint_ko": "핵심 주제 언급"}] * 2,
            "opinion": [{"q": "(mock) Do you agree with the main argument? Why?", "hint_ko": "본인 경험 연결"}] * 2,
            "debate": [{"q": "(mock) Proposition for debate", "for": "(mock) argument for", "against": "(mock) argument against"}],
            "roleplay": {"scenario": "(mock) scenario", "your_role": "(mock) you", "partner_role": "(mock) partner",
                         "goals": ["(mock) goal 1", "(mock) goal 2"]},
            "useful_phrases": [{"phrase": "(mock) The way I see it, …", "ko": "제가 보기엔 …"}] * 3,
        },
        "shadowing": [{"segment_id": s.id, "reason_ko": "(mock) 리듬이 좋고 표현이 풍부함"} for s in pick(2)],
        "difficulty": {"cefr": "C1", "note_ko": "(mock) 난이도 메모"},
        "tags": ["mock", "placeholder"],
    }
