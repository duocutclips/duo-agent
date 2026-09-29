"""Ideas, scripts and duration estimation."""

from __future__ import annotations

import pytest

from clipfactory import campaigns as C
from clipfactory.errors import ValidationError
from clipfactory.ideas import CATEGORIES, generate_ideas, regenerate_idea
from clipfactory.samples import DEMO_BRIEF
from clipfactory.scriptgen import TARGETS, analyze_script, generate_script, save_script
from clipfactory.textutil import estimate_speech_seconds, slugify, split_sentences, spoken_words


@pytest.fixture
def campaign(db, llm):
    c = C.create_campaign(db, {"name": "Seed Heist Simulator — Launch Clips (DEMO)"})
    C.add_document(db, c["id"], kind="text", name="brief", text=DEMO_BRIEF)
    C.analyze_campaign(db, llm, c["id"])
    return db.get("campaigns", c["id"])


def test_speech_estimate_scales_with_words():
    ten = "one two three four five six seven eight nine ten."
    assert 3.0 < estimate_speech_seconds(ten) < 5.0
    assert estimate_speech_seconds(ten * 4) > 3.5 * estimate_speech_seconds(ten)
    # numbers are spoken as several words
    assert len(spoken_words("1,500")) > 1


def test_split_sentences_and_slugify():
    assert split_sentences("Hi there. How are you? Great!") == ["Hi there.", "How are you?", "Great!"]
    assert slugify("Seed Heist — Launch Clips (DEMO)!") == "seed-heist-launch-clips-demo"


def test_ten_distinct_ideas_with_scores(db, llm, campaign):
    res = generate_ideas(db, llm, campaign["id"])
    ideas = res["ideas"]
    assert len(ideas) == 10
    assert {i["category"] for i in ideas} == set(CATEGORIES)
    assert len({i["hook"] for i in ideas}) == 10
    for i in ideas:
        assert 0 <= i["novelty_score"] <= 1 and 0 <= i["compliance_score"] <= 1
        assert i["generator"] == "offline-heuristic"
        assert "HEIST50" in i["cta"]
        assert 20 <= i["est_duration"] <= 40  # respects the confirmed campaign length
    assert res["warning"]


def test_regenerate_replaces_one_idea_with_a_different_one(db, llm, campaign):
    ideas = generate_ideas(db, llm, campaign["id"])["ideas"]
    old = ideas[3]
    new = regenerate_idea(db, llm, old["id"])["idea"]
    assert new["category"] == old["category"]
    assert new["hook"] != old["hook"]
    assert len(db.list("ideas", "campaign_id = ?", [campaign["id"]])) == 10


@pytest.mark.parametrize("target", TARGETS)
def test_scripts_fit_each_target(db, llm, campaign, target):
    idea = generate_ideas(db, llm, campaign["id"])["ideas"][0]
    s = generate_script(db, llm, idea["id"], target)["script"]
    assert s["text"].startswith(idea["hook"])
    assert "HEIST50" in s["text"] and "Seed Heist Simulator" in s["text"]
    assert s["est_seconds"] <= target * 1.05 + 1
    assert not any(w.startswith("Too long") for w in s["warnings"])


def test_script_warnings():
    rules = {"required_phrases": ["HEIST50", "#SeedHeist"], "banned_terms": ["free Robux"], "max_seconds": 20, "min_seconds": None}
    long_text = " ".join(["This sentence keeps going and going with many many words that nobody wants to hear aloud today."] * 6)
    info = analyze_script(long_text + " Get free Robux now.", 15, rules)
    text = " ".join(info["warnings"])
    assert "Too long" in text and "longer than 16 words" in text
    assert "HEIST50" in text and "#SeedHeist" not in text  # hashtags belong in the caption
    assert "free Robux" in text and "campaign maximum" in text


def test_invalid_target_and_edit_recomputes(db, llm, campaign):
    idea = generate_ideas(db, llm, campaign["id"])["ideas"][0]
    with pytest.raises(ValidationError):
        generate_script(db, llm, idea["id"], 25)
    s = generate_script(db, llm, idea["id"], 30)["script"]
    edited = save_script(db, s["id"], "Short line. Use code HEIST50 in Seed Heist Simulator.")
    assert edited["est_seconds"] < s["est_seconds"]
    assert any("Short" in w for w in edited["warnings"])
