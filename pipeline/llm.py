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
                    "name": {"type": "string", "description": "Person's name if identifiable from context, else a descriptive stand-in like 'Guest (economist)'"},
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
            "description": "10-14 high-value spoken expressions actually used in the episode",
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
            "description": "6-10 single words worth learning (C1+), not already covered in expressions",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["word", "pos", "meaning_ko", "example"],
                "properties": {
                    "word": {"type": "string"},
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


def build_study_prompt(meta: dict, show: dict, segments: list[Segment], speaker_mode: str) -> str:
    desc = (meta.get("description_text") or "").strip()
    return (
        f"PODCAST: {show['name']} ({show.get('publisher', '')}). {show.get('style', '')}\n"
        f"EPISODE: {meta['title']} — published {meta['published_at'][:10]}, {fmt_clock(meta.get('duration_sec') or 0)} long.\n"
        f"SHOW NOTES: {desc[:1200]}\n\n"
        f"SPEAKERS: {_speaker_instruction(speaker_mode)}\n\n"
        "TRANSCRIPT (one segment per line: id [mm:ss] (speaker): text)\n"
        "-----\n"
        f"{render_transcript(segments)}\n"
        "-----\n\n"
        "Produce the study pack JSON now. Aim for 12 expressions, 8 vocab, 4-7 chapters, 3 shadowing picks."
    )


SYSTEM_TRANSLATE = """You translate podcast transcript segments from English into natural Korean for an advanced learner.
- Preserve meaning and tone; use 자연스러운 구어체 (대화체) rather than stiff 문어체. Keep sentence-level structure
  so the learner can map Korean to English.
- Keep names, companies and numbers as in the source. Do not add notes or brackets.
- Return one translation per segment id, same ids, nothing else."""


def build_translate_prompt(segments: list[Segment]) -> str:
    lines = [f"{s.id}: {s.text}" for s in segments]
    return "SEGMENTS\n" + "\n".join(lines) + "\n\nTranslate each segment into Korean."


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
        data = self._call_json(self.model, SYSTEM_STUDY, prompt, STUDY_SCHEMA, max_tokens=18000)
        return postprocess_study_pack(data, segments)

    def translate_segments(self, segments: list[Segment], chunk: int = 45) -> dict[str, str]:
        if self.mock:
            return {s.id: f"[번역 자리표시자] {s.text[:60]}…" for s in segments}
        out: dict[str, str] = {}
        for i in range(0, len(segments), chunk):
            part = segments[i:i + chunk]
            data = self._call_json(self.translate_model, SYSTEM_TRANSLATE, build_translate_prompt(part),
                                   TRANSLATION_SCHEMA, max_tokens=12000)
            for row in data.get("translations", []):
                if row.get("id") and row.get("ko"):
                    out[row["id"]] = row["ko"].strip()
        missing = [s.id for s in segments if s.id not in out]
        if missing:
            log.warning("translation missing for %d segments (%s…)", len(missing), ", ".join(missing[:5]))
        return out

    # -- internals ------------------------------------------------------------
    def _call_json(self, model: str, system: str, user: str, schema: dict, max_tokens: int) -> dict:
        import anthropic

        delay = 5.0
        last_err: Exception | None = None
        for attempt in range(1, 5):
            try:
                resp = self._client.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                    output_config={"format": {"type": "json_schema", "schema": schema}},
                )
                if resp.stop_reason == "max_tokens":
                    raise RuntimeError("response truncated (max_tokens); will retry next run")
                if resp.stop_reason == "refusal":
                    raise RuntimeError("model refused the request")
                text = next(b.text for b in resp.content if getattr(b, "type", "") == "text")
                usage = getattr(resp, "usage", None)
                if usage:
                    log.info("  %s: %s in / %s out tokens", model, usage.input_tokens, usage.output_tokens)
                return json.loads(text)
            except (anthropic.RateLimitError, anthropic.APIConnectionError, anthropic.InternalServerError) as e:
                last_err = e
                log.warning("  API transient error (attempt %d): %s — retrying in %.0fs", attempt, e, delay)
                time.sleep(delay)
                delay = min(delay * 2, 60)
            except anthropic.APIStatusError as e:
                # 4xx other than rate limit: no point retrying
                raise RuntimeError(f"API error {e.status_code}: {e.message}") from e
        raise RuntimeError(f"API failed after retries: {last_err}")


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
