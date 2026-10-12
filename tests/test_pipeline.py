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
