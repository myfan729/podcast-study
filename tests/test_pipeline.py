import json
from pathlib import Path

import pytest

from pipeline.feeds import parse_duration, parse_feed, strip_html
from pipeline.llm import STUDY_SCHEMA, TRANSLATION_SCHEMA, build_study_prompt, mock_study_pack, postprocess_study_pack
from pipeline.transcript import parse_srt, parse_timestamp, parse_transcript, parse_vtt, segment_cues, transcript_stats

FIX = Path(__file__).parent / "fixtures"


def test_parse_timestamp_variants():
    assert parse_timestamp("0:00:02.759") == pytest.approx(2.759)
    assert parse_timestamp("00:01:04.900") == pytest.approx(64.9)
    assert parse_timestamp("01:02:03,450") == pytest.approx(3723.45)
    assert parse_timestamp("12:34.5") == pytest.approx(754.5)


def test_parse_duration_variants():
    assert parse_duration("988") == 988
    assert parse_duration("00:01:05") == 65
    assert parse_duration("24:03") == 1443
    assert parse_duration(None) is None


def test_omny_feed_parsing():
    meta, eps = parse_feed((FIX / "omny_feed.xml").read_text())
    assert meta["title"] == "Demo Take"
    assert [e.title[:8] for e in eps] == ["Weekend ", "Why Airl", "An Episo"]  # newest first
    ep = eps[1]
    assert ep.duration_sec == 212
    assert ep.episode_number == "412"
    assert ep.audio_url.startswith("https://podtrac.com/")
    kinds = [t.kind for t in ep.transcripts]
    assert kinds == ["srt", "vtt", "text"]
    assert ep.best_transcript.kind == "vtt"
    assert "&t=" in ep.best_transcript.url and "&amp;" not in ep.best_transcript.url
    assert eps[2].best_transcript is None
    assert "Overbooking looks like" in strip_html(ep.description_html)


def test_transistor_feed_parsing():
    meta, eps = parse_feed((FIX / "transistor_feed.xml").read_text())
    assert eps[0].duration_sec == 65
    assert eps[0].best_transcript.kind == "vtt"
    assert eps[0].best_transcript.rel == "captions"
    assert eps[0].published_iso == "2026-10-08T13:00:00Z"


def test_vtt_with_voice_tags():
    cues = parse_vtt((FIX / "omny_demo.vtt").read_text())
    assert len(cues) == 46
    assert cues[0].spk == "Speaker 1" and cues[0].t == "Demo Audio Studios."
    assert cues[0].s == pytest.approx(1.2)
    assert all(c.spk for c in cues)
    assert cues[-1].t.endswith("see you tomorrow.")


def test_vtt_without_speakers_and_srt():
    cues = parse_vtt((FIX / "transistor_demo.vtt").read_text())
    assert len(cues) == 11
    assert all(c.spk is None for c in cues)
    # "Welcome to Demo Talk." must not be mistaken for a 'Name:' speaker prefix
    assert cues[3].t.startswith("Welcome to Demo Talk")

    srt = parse_srt((FIX / "sample.srt").read_text())
    assert [c.spk for c in srt] == ["Speaker 1", "Speaker 2", "Speaker 2", "Speaker 2"]
    assert srt[2].t.startswith("News. The fact that") and "big banks" in srt[2].t  # multi-line cue joined
    assert "$9.38 billion." in srt[3].t  # ASR spacing cleanup


def test_segmentation_and_stats():
    cues = parse_transcript((FIX / "omny_demo.vtt").read_text(), "vtt")
    segs = segment_cues(cues)
    stats = transcript_stats(cues, segs)
    assert stats["has_speakers"] and stats["speakers"] == ["Speaker 1", "Speaker 2", "Speaker 3"]
    # speaker changes always start a new segment
    for a, b in zip(segs, segs[1:]):
        assert a.cue_to + 1 == b.cue_from
        assert a.end <= b.start + 0.01
    assert all(s.speaker for s in segs)
    assert max(s.words for s in segs) <= 170
    ids = [s.id for s in segs]
    assert ids == [f"s{i + 1}" for i in range(len(segs))]


def test_mock_pack_matches_schema_shape_and_postprocess():
    cues = parse_transcript((FIX / "omny_demo.vtt").read_text(), "vtt")
    segs = segment_cues(cues)
    meta = {"title": "Why Airlines Sell More Seats Than They Have", "published_at": "2026-10-09T20:14:51Z", "duration_sec": 212}
    pack = mock_study_pack(meta, segs, "generic")
    for key in STUDY_SCHEMA["required"]:
        assert key in pack
    pack = postprocess_study_pack(pack, segs)
    seg_by_id = {s.id: s for s in segs}
    for ex in pack["expressions"]:
        assert ex["quote"].lower() in seg_by_id[ex["segment_id"]].text.lower()
    # a drifted segment id gets repaired from the quote
    bad = {"expressions": [{"expression": "x", "quote": "we're looking for volunteers", "segment_id": "s999"}],
           "chapters": [], "shadowing": [], "speaker_assignments": [{"segment_id": "nope", "speaker": "x"}]}
    fixed = postprocess_study_pack(bad, segs)
    assert "volunteers" in seg_by_id[fixed["expressions"][0]["segment_id"]].text
    assert fixed["speaker_assignments"] == []


def test_prompt_contains_segments_and_schema_is_strict():
    cues = parse_transcript((FIX / "omny_demo.vtt").read_text(), "vtt")
    segs = segment_cues(cues)
    prompt = build_study_prompt({"title": "T", "published_at": "2026-10-09T20:14:51Z", "duration_sec": 212,
                                 "description_text": "d"}, {"name": "Demo", "publisher": "X"}, segs, "generic")
    assert "s1 [0:01] (Speaker 1): Demo Audio Studios." in prompt

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node.get("additionalProperties") is False
                assert set(node["required"]) == set(node["properties"])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    walk(STUDY_SCHEMA)
    walk(TRANSLATION_SCHEMA)
    json.dumps(STUDY_SCHEMA)


def test_vtt_without_blank_lines_and_identifiers():
    from pipeline.transcript import parse_vtt
    raw = "WEBVTT\n\n1\n00:00:01.000 --> 00:00:02.000\nHello there.\n2\n00:00:02.500 --> 00:00:03.000\nSecond cue\ncontinues here.\n00:00:03.500 --> 00:00:04.000\nThird.\n"
    cues = parse_vtt(raw)
    assert [c.t for c in cues] == ["Hello there.", "Second cue continues here.", "Third."]


def test_find_exact_tolerates_quote_styles():
    from pipeline.llm import find_exact
    assert find_exact("That’s the auction at the gate.", "that's the auction") == "That’s the auction"
    assert find_exact("nine  times out of ten", "Nine times out of ten") == "nine  times out of ten"
    assert find_exact("nothing here", "absent phrase") is None


def test_plain_json_helpers():
    from pipeline.llm import STUDY_SCHEMA, extract_json, schema_skeleton, validate
    sk = json.loads(schema_skeleton(STUDY_SCHEMA))
    assert set(sk) == set(STUDY_SCHEMA["properties"])
    assert sk["summary_ko"] == ["<핵심 내용 4~6개 불릿(한국어, 각 1~2문장)>"]
    assert extract_json('Here you go:\n```json\n{"x": [1, 2]}\n```\nDone.') == {"x": [1, 2]}
    good = {"translations": [{"id": "s1", "ko": "안녕"}]}
    assert validate({"type": "object", "required": ["translations"], "properties": {"translations": {"type": "array", "items": {"type": "object", "required": ["id", "ko"], "properties": {"id": {"type": "string"}, "ko": {"type": "string"}}}}}}, good) == []
    assert "$.speakers: expected array" in validate(STUDY_SCHEMA, {"speakers": "nope"})


class _FakeAsr:
    """Pretends to transcribe: emits the transcript's own words shifted by a piecewise ad offset, with noise."""
    name = "fake"

    def __init__(self, cues, pre, mids):
        self._w = []
        import random
        rnd = random.Random(1)
        for c in cues:
            toks = [t for t in __import__("pipeline.sync", fromlist=["tokens"]).tokens(c["t"])]
            span = max(0.2, c["e"] - c["s"])
            for i, tok in enumerate(toks):
                ct = c["s"] + span * i / len(toks)
                off = pre + sum(length for pos, length in mids if ct >= pos)
                if rnd.random() < 0.12:
                    tok = "um"  # ASR error
                self._w.append((tok, ct + off, ct + off + 0.2))
        # ad speech that must not be matched
        for t in range(0, int(pre), 1):
            self._w.append(("buy", float(t), t + 0.3))
        self._w.sort(key=lambda w: w[1])

    def words_in(self, lo, hi):
        return [w for w in self._w if lo <= w[1] <= hi]

    def words(self, pcm16, t_lo, t_hi):  # noqa: D102 — same signature as sync.Asr.words
        return self.words_in(t_lo, t_hi)


def test_sync_content_map_with_known_and_unknown_markers():
    from pipeline.sync import content_map, cue_tokens, locate
    cues = parse_transcript((FIX / "omny_demo.vtt").read_text(), "vtt")
    cues = [{"s": c.s, "e": c.e, "t": c.t} for c in cues]
    pre, mids = 31.0, [(60.0, 92.0)]
    fake = _FakeAsr(cues, pre, mids)
    content_dur = cues[-1]["e"]
    dur = content_dur + pre + 92.0 + 20.0  # + post-roll
    import numpy as np
    pcm = np.zeros(int(dur * 16000), dtype=np.float32)
    # known markers (Omny)
    breaks, ad_total = content_map(fake, cues, pcm, dur, content_dur, markers=[60.0])
    assert [b["c"] for b in breaks] == [0.0, 60.0]
    assert abs(breaks[0]["a"] - 31.0) < 0.6 and abs(breaks[1]["a"] - (60 + 31 + 92)) < 0.6
    # unknown markers (Transistor-style)
    breaks2, _ = content_map(fake, cues, pcm, dur, content_dur, markers=None)
    assert len(breaks2) == 2
    assert abs((breaks2[0]["a"] - breaks2[0]["c"]) - 31.0) < 0.6
    assert 60.0 <= breaks2[1]["c"] <= 75.0 and abs((breaks2[1]["a"] - breaks2[1]["c"]) - 123.0) < 0.6
    # locate() refuses when the text is absent
    assert locate(cue_tokens(cues, 0.0), fake.words_in(0, 20), 0, 20) is None
