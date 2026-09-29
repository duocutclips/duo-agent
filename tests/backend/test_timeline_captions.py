"""Captions, cut points, timeline schema validation and SFX recommendations."""

from __future__ import annotations

import copy

import pytest

from clipfactory.captions import build_ass, build_caption_items
from clipfactory.errors import ValidationError
from clipfactory.templates import get_template
from clipfactory.timeline import (
    NARRATION_OFFSET,
    build_timeline,
    cut_points,
    timeline_hash,
    validate_timeline,
)

WORDS = [{"word": w, "start": i * 0.4, "end": i * 0.4 + 0.35} for i, w in enumerate(
    ["Nobody", "knows", "this", "trick.", "Use", "code", "HEIST50", "in", "Seed", "Heist", "now,", "it", "takes", "five", "seconds.", "Try", "it", "before", "everyone", "else!"])]


def test_caption_grouping_breaks_on_punctuation_and_max_words():
    items = build_caption_items(WORDS, max_words=3, emphasis_terms=["Seed Heist"])
    assert all(len(i["words"]) <= 3 for i in items)
    assert items[0]["text"] == "Nobody knows this"
    assert any(i["text"].endswith("trick.") for i in items)
    # contiguous, non-overlapping phrases
    for a, b in zip(items, items[1:], strict=False):
        assert a["end"] <= b["start"] + 1e-6
    emph = {w["text"] for i in items for w in i["words"] if w["emphasis"]}
    assert {"HEIST50", "Seed", "Heist"} <= emph


def test_caption_offset_and_pause_split():
    words = [{"word": "a", "start": 0, "end": 0.2}, {"word": "b", "start": 1.5, "end": 1.7}]
    items = build_caption_items(words, max_words=3, offset=0.15)
    assert len(items) == 2 and items[0]["start"] == 0.15


def test_ass_contains_styles_and_highlight(settings):
    t = get_template(settings, "roblox_story")
    items = build_caption_items(WORDS, max_words=3)
    ass = build_ass([*items, {"type": "text", "role": "title", "start": 0, "end": 1.5, "text": "Title {x}"}], t["captions"], t["title"])
    assert "[V4+ Styles]" in ass and "Style: Caption" in ass and "Style: Title" in ass
    assert ass.count("Dialogue:") >= len(WORDS)  # one event per active word
    assert "\\fscx112" in ass
    assert "{x}" not in ass  # braces from user text are escaped


def test_cut_points_respect_min_and_max(settings):
    total = NARRATION_OFFSET + WORDS[-1]["end"] + 0.8
    cuts = cut_points(WORDS, total, 1.4, 3.2, NARRATION_OFFSET)
    assert cuts[0] == 0 and abs(cuts[-1] - total) < 1e-6
    gaps = [b - a for a, b in zip(cuts, cuts[1:], strict=False)]
    assert all(g <= 3.2 + 1e-6 for g in gaps)
    assert all(g >= 1.4 - 1e-6 for g in gaps[:-1])


def _timeline(settings, seed=1):
    media = [{"id": "m1", "path": "/x/a.mp4", "filename": "a.mp4", "duration": 30.0}]
    segments = [{"id": f"s{i}", "media_id": "m1", "start": i * 3.0, "end": i * 3.0 + 2.5, "score": 0.5 + i / 20,
                 "label": "High action", "tags": [], "enabled": True, "kind": "action"} for i in range(8)]
    sfx = [{"id": f"x{c}", "path": f"/x/{c}.wav", "category": c} for c in ("impact", "whoosh", "pop", "success")]
    narration = {"duration": WORDS[-1]["end"], "words": WORDS, "audio_path": "/x/n.wav"}
    return build_timeline(template=get_template(settings, "roblox_story"), narration=narration, script_text="x", media=media,
                          segments=segments, sfx_library=sfx, music=None, hook_text="Nobody knows this trick",
                          cta_text="Use code HEIST50", emphasis_terms=["HEIST50"], seed=seed)


def test_build_timeline_is_valid_contiguous_and_seeded(settings):
    tl = _timeline(settings)
    validate_timeline(tl)
    types = {i["type"] for i in tl["items"]}
    assert {"video", "caption", "narration", "sfx", "fade", "text"} <= types
    assert tl["width"] == 1080 and tl["height"] == 1920
    assert timeline_hash(tl) == timeline_hash(_timeline(settings))  # deterministic for a seed
    other = _timeline(settings, seed=2)
    assert [i.get("src_in") for i in other["items"] if i["type"] == "video"] != \
        [i.get("src_in") for i in tl["items"] if i["type"] == "video"] or timeline_hash(other) != timeline_hash(tl)


def test_validate_rejects_gaps_and_bad_items(settings):
    tl = _timeline(settings)
    broken = copy.deepcopy(tl)
    vids = [i for i in broken["items"] if i["type"] == "video"]
    vids[1]["start"] += 0.5
    with pytest.raises(ValidationError, match="contiguous"):
        validate_timeline(broken)
    bad = copy.deepcopy(tl)
    bad["items"].append({"type": "laser", "start": 0})
    with pytest.raises(ValidationError):
        validate_timeline(bad)
    no_video = copy.deepcopy(tl)
    no_video["items"] = [i for i in no_video["items"] if i["type"] != "video"]
    with pytest.raises(ValidationError):
        validate_timeline(no_video)
