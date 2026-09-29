"""Short-form narration script generator and duration checker."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from .campaigns import campaign_rules
from .db import Database
from .errors import ValidationError
from .llm import ClaudeClient
from .textutil import contains_phrase, estimate_speech_seconds, split_sentences

TARGETS = (15, 20, 30, 45)

# Body beats per category. {game}/{focus} are filled in; lines are short and spoken-style.
BODY: dict[str, list[str]] = {
    "discovery": ["I was just exploring.", "Then I noticed something off in the corner.", "I got closer.",
                  "And it turned out to be {focus}.", "It changes how you play the whole map.",
                  "I've played for hours and never saw it before.",
                  "So I tested it again, just to be sure.", "Same result every time."],
    "secret": ["Look right here.", "Most people run straight past it.", "But if you stop and look closer,",
               "you'll find the trick behind {focus}.", "It takes five seconds.", "And it saves you so much time.",
               "I use it every single session now.", "Try it before everyone else finds out."],
    "challenge": ["The rules are simple.", "No restarts.", "I start with nothing.", "The clock is running.",
                  "This part almost ended it.", "Then I found a shortcut to {focus}.",
                  "Ten seconds left.", "One last push."],
    "progression": ["This is where I started.", "Nothing. Zero.", "First upgrade. Already faster.",
                    "Then I focused on {focus}.", "That's when it snowballed.", "Now look at this.",
                    "Every upgrade made the next one faster.", "And I'm still going."],
    "mistake": ["Almost every new player does this.", "They rush ahead.", "And they lose everything they built.",
                "Instead, slow down and think about {focus} first.", "It feels slower.", "But you end up way ahead.",
                "I learned that the hard way.", "You don't have to."],
    "tutorial": ["Step one. Learn the core loop.", "Step two. Focus on {focus}.", "Step three. Upgrade before you explore.",
                 "That's it.", "Do those three things.", "You'll be ahead of most players by tonight.",
                 "Skip any of them and it takes twice as long.", "Trust me on this one."],
    "rare_item": ["I've been grinding for this.", "Hours of nothing.", "Then this happened.", "Look at that.",
                  "It's tied to {focus}.", "Barely anyone has one.",
                  "And yes, I'm keeping it.", "Here's one more look."],
    "funny_moment": ["I had a perfect plan.", "Step one went great.", "Step two. Not so much.",
                     "I went all in on {focus}.", "The game had other ideas.", "Honestly, I deserved that.",
                     "I tried again.", "Somehow it got worse."],
    "comparison": ["Number three. The safe option.", "It works, but it's slow.", "Number two. Riskier, but faster.",
                   "Number one. Go straight for {focus}.", "It's the best return for your time.", "Nothing else comes close.",
                   "I tested all three myself.", "The difference is huge."],
    "surprising_mechanic": ["You can actually do this.", "Watch closely.", "Most players don't know it exists.",
                            "It makes {focus} way easier.", "Try it once.", "You won't play the old way again.",
                            "I wish I knew this on day one.", "Now you do."],
}
PAYOFF = {
    "discovery": "Now you know where to look.", "secret": "Now you know the secret.", "challenge": "Challenge complete.",
    "progression": "That's the fastest route I've found.", "mistake": "Don't make my mistake.",
    "tutorial": "Simple as that.", "rare_item": "Worth every minute.", "funny_moment": "Never again.",
    "comparison": "Number one wins every time.", "surprising_mechanic": "Game changer.",
}


class ScriptModel(BaseModel):
    sentences: list[str]


def analyze_script(text: str, target_seconds: int, rules: dict[str, Any] | None = None) -> dict[str, Any]:
    est = estimate_speech_seconds(text)
    warnings: list[str] = []
    if est > target_seconds * 1.05:
        warnings.append(f"Too long: about {est:.1f}s of speech for a {target_seconds}s target. Cut about "
                        f"{max(1, round((est - target_seconds) * 2.75))} words.")
    elif est < target_seconds * 0.6:
        warnings.append(f"Short: about {est:.1f}s of speech for a {target_seconds}s target. Visual moments must fill the rest.")
    sentences = split_sentences(text)
    long = [s for s in sentences if len(s.split()) > 16]
    if long:
        warnings.append(f"{len(long)} sentence(s) are longer than 16 words; shorter lines read better aloud.")
    if rules:
        for phrase in rules.get("required_phrases", []):
            if phrase.startswith("#"):
                continue  # hashtags belong in the post caption, not the narration
            if not contains_phrase(text, phrase):
                warnings.append(f"Missing required wording: “{phrase}”.")
        for term in rules.get("banned_terms", []):
            if contains_phrase(text, term):
                warnings.append(f"Contains restricted term: “{term}”.")
        if rules.get("max_seconds") and est > rules["max_seconds"]:
            warnings.append(f"Longer than the campaign maximum of {rules['max_seconds']}s.")
        if rules.get("min_seconds") and est + 1.0 < rules["min_seconds"]:
            warnings.append(f"About {est:.0f}s of speech; the campaign minimum is {rules['min_seconds']}s. Add a line or two.")
    return {"est_seconds": est, "warnings": warnings, "sentences": sentences,
            "word_count": len(text.split())}


def heuristic_script(campaign: dict[str, Any], idea: dict[str, Any], target: int, focus: str) -> str:
    game = campaign.get("game") or "this game"
    fmt = {"game": game, "focus": focus}
    body = [b.format(**fmt) for b in BODY.get(idea["category"], BODY["discovery"])]
    hook = idea["hook"]
    payoff = PAYOFF.get(idea["category"], "")
    cta = idea["cta"]
    # Add body beats until the estimate reaches the target (minus hook/payoff/CTA).
    chosen: list[str] = []
    for beat in body:
        candidate = " ".join([hook, *chosen, beat, payoff, cta])
        if estimate_speech_seconds(candidate) > target * 0.98 and len(chosen) >= 2:
            break
        chosen.append(beat)
    if target >= 45:
        chosen.append(f"And that's just one part of {game}.")
        chosen.append("There's a lot more to find if you keep playing.")
    return " ".join([hook, *chosen, payoff, cta]).strip()


SCRIPT_SYSTEM = """You write spoken narration for vertical Roblox gameplay clips.
Rules: open with the hook immediately (no greetings, no "in this video"); short sentences (max ~12 words);
natural spoken English; clear progression and a payoff; end with the CTA when one is given; include every
required phrase exactly; never use restricted terms; don't invent statistics. Return one sentence per item."""


def generate_script(db: Database, llm: ClaudeClient, idea_id: str, target_seconds: int, *, use_ai: bool = True) -> dict[str, Any]:
    if target_seconds not in TARGETS:
        raise ValidationError(f"Target duration must be one of {', '.join(map(str, TARGETS))} seconds.")
    idea = db.get("ideas", idea_id)
    campaign = db.get("campaigns", idea["campaign_id"])
    rules = campaign_rules(campaign)
    warning = None
    if use_ai and llm.available:
        words = int(target_seconds * 2.6)
        required = [p for p in rules["required_phrases"] if not p.startswith("#")]
        prompt = (f"Game: {campaign['game']}\nConcept: {idea['title']}\nHook: {idea['hook']}\nConcept detail: {idea['concept']}\n"
                  f"Angle: {idea['script_angle']}\nCTA: {idea['cta']}\nRequired phrases: {required}\n"
                  f"Restricted terms: {rules['banned_terms']}\nTarget: {target_seconds} seconds spoken (about {words} words).")
        text = " ".join(s.strip() for s in llm.structured(system=SCRIPT_SYSTEM, prompt=prompt, schema=ScriptModel).sentences)
        generator = f"anthropic:{llm.settings.anthropic_model}"
    else:
        if use_ai:
            warning = "Claude is not configured (ANTHROPIC_API_KEY missing); script written by the offline template generator."
        from .ideas import _focus_terms, focus_for

        focus = focus_for(idea["category"], _focus_terms(campaign), idea["position"])
        text = heuristic_script(campaign, idea, target_seconds, focus)
        generator = "offline-heuristic"
    info = analyze_script(text, target_seconds, rules)
    script = db.insert("scripts", {
        "idea_id": idea_id, "campaign_id": campaign["id"], "target_seconds": target_seconds, "text": text,
        "est_seconds": info["est_seconds"], "warnings": info["warnings"], "generator": generator,
    })
    db.update("ideas", idea_id, {"selected": True})
    return {"script": script | {"sentences": info["sentences"]}, "warning": warning}


def save_script(db: Database, script_id: str, text: str, target_seconds: int | None = None) -> dict[str, Any]:
    script = db.get("scripts", script_id)
    target = target_seconds or script["target_seconds"]
    if target not in TARGETS:
        raise ValidationError(f"Target duration must be one of {', '.join(map(str, TARGETS))} seconds.")
    if not text.strip():
        raise ValidationError("Script text cannot be empty.")
    campaign = db.get("campaigns", script["campaign_id"])
    info = analyze_script(text, target, campaign_rules(campaign))
    updated = db.update("scripts", script_id, {"text": text.strip(), "target_seconds": target,
                                               "est_seconds": info["est_seconds"], "warnings": info["warnings"],
                                               "generator": script["generator"] if text.strip() == script["text"] else "edited"})
    return updated | {"sentences": info["sentences"]}
