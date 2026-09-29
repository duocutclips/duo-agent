"""Content idea generator.

Ideas are forced to vary: each one is assigned a different concept category, and each category
has its own hook structure, script angle, footage needs and template. Novelty and compliance
scores are computed locally (not self-reported by the model) so they are comparable across
the offline and Claude generators.
"""

from __future__ import annotations

import random
import re
from typing import Any

from pydantic import BaseModel

from .campaigns import campaign_rules
from .db import Database
from .errors import ValidationError
from .llm import ClaudeClient
from .textutil import contains_phrase, jaccard, tokens

CATEGORIES = [
    "discovery", "secret", "challenge", "progression", "mistake",
    "tutorial", "rare_item", "funny_moment", "comparison", "surprising_mechanic",
]

CATEGORY_TEMPLATE = {
    "discovery": "roblox_story", "secret": "roblox_secret", "challenge": "roblox_challenge",
    "progression": "roblox_story", "mistake": "roblox_explainer", "tutorial": "roblox_explainer",
    "rare_item": "roblox_secret", "funny_moment": "roblox_story", "comparison": "roblox_top5",
    "surprising_mechanic": "roblox_secret",
}

# Several variants per category so "regenerate" produces something genuinely new.
PATTERNS: dict[str, list[dict[str, Any]]] = {
    "discovery": [
        {"title": "I found something weird in {game}", "hook": "Nobody told me {game} had this.",
         "concept": "Show the moment you stumble onto something new ({focus}), then reveal why it matters.",
         "angle": "First-person discovery. Build curiosity, reveal at the end.", "dur": 25,
         "gameplay": ["exploration footage", "the reveal moment", "reaction beat"]},
        {"title": "Exploring {game} until I found this", "hook": "I kept walking in {game} and this happened.",
         "concept": "A mini journey through the map that ends at {focus}.",
         "angle": "Travel log with a payoff at the destination.", "dur": 30,
         "gameplay": ["walking/travel shots", "landmark", "final reveal"]},
    ],
    "secret": [
        {"title": "The {game} secret most players miss", "hook": "Most players walk right past this in {game}.",
         "concept": "Point out a hidden detail related to {focus} and show how to use it.",
         "angle": "Insider tip. Tease the secret, then show it clearly.", "dur": 20,
         "gameplay": ["close-up of the hidden detail", "using it successfully"]},
        {"title": "Don't tell anyone this {game} trick", "hook": "I probably shouldn't share this {game} trick.",
         "concept": "A conspiratorial tip about {focus} with proof on screen.",
         "angle": "Whispered secret, fast proof, quick CTA.", "dur": 20,
         "gameplay": ["setup shot", "trick in action", "result"]},
    ],
    "challenge": [
        {"title": "The 60-second {game} challenge", "hook": "I gave myself sixty seconds to win in {game}.",
         "concept": "Timed challenge built around {focus}, with a countdown feel and a clear win or fail.",
         "angle": "Stakes first, fast cuts, reveal the result at the end.", "dur": 30,
         "gameplay": ["start of the attempt", "close calls", "final result"]},
        {"title": "{game} but I can't stop moving", "hook": "New rule: in {game} I'm not allowed to stop.",
         "concept": "Self-imposed rule challenge built around {focus}.",
         "angle": "Rule, attempt, twist, result.", "dur": 30,
         "gameplay": ["continuous movement", "near-fail moment", "outcome"]},
    ],
    "progression": [
        {"title": "From zero to pro in {game}", "hook": "Here's how fast you can go from nothing to pro in {game}.",
         "concept": "Before/after progression montage; call out {focus} as the turning point.",
         "angle": "Speed-run style progression, each step a new visual.", "dur": 30,
         "gameplay": ["starting state", "upgrade moments", "end state"]},
        {"title": "Day 1 vs Day 7 in {game}", "hook": "This is what one week of {game} looks like.",
         "concept": "Compare the early game to a later state focused on {focus}.",
         "angle": "Then vs now, emphasise the jump.", "dur": 25,
         "gameplay": ["early game", "late game", "side-by-side moment"]},
    ],
    "mistake": [
        {"title": "The beginner mistake that ruins your {game} run", "hook": "Stop doing this in {game}.",
         "concept": "Show the common mistake around {focus}, then the better approach.",
         "angle": "Problem, consequence, fix.", "dur": 25,
         "gameplay": ["the mistake", "what goes wrong", "the correct way"]},
        {"title": "I wasted hours in {game} because of this", "hook": "I wish someone warned me about this in {game}.",
         "concept": "Personal regret story about {focus} with a lesson.",
         "angle": "Confession, lesson, CTA.", "dur": 25,
         "gameplay": ["wasted effort", "realisation", "better result"]},
    ],
    "tutorial": [
        {"title": "{game} tutorial: {focus} made easy", "hook": "If you're new to {game}, do this first.",
         "concept": "Three quick steps covering {focus}, each shown on screen.",
         "angle": "Numbered steps, one clear visual per step.", "dur": 30,
         "gameplay": ["step one", "step two", "step three", "result"]},
        {"title": "{game} in 20 seconds: everything you need", "hook": "Here's {game} explained in twenty seconds.",
         "concept": "Rapid-fire explainer of the core loop and {focus}.",
         "angle": "Dense, fast, every sentence a new clip.", "dur": 20,
         "gameplay": ["core loop", "key mechanic", "goal"]},
    ],
    "rare_item": [
        {"title": "The rarest thing I've found in {game}", "hook": "I could not believe what I just got in {game}.",
         "concept": "Build up to showing a rare find related to {focus}.",
         "angle": "Anticipation, reveal, why it's rare.", "dur": 20,
         "gameplay": ["the search", "the rare moment", "showing it off"]},
        {"title": "Everyone wants this in {game}", "hook": "This is the one thing every {game} player wants.",
         "concept": "Show off a sought-after item or result tied to {focus} and how you got it.",
         "angle": "Flex first, then the how.", "dur": 25,
         "gameplay": ["item close-up", "how it was obtained"]},
    ],
    "funny_moment": [
        {"title": "{game} did NOT go as planned", "hook": "This was supposed to be easy.",
         "concept": "A confident plan involving {focus} that falls apart in a funny way.",
         "angle": "Confident setup, chaos, punchline.", "dur": 20,
         "gameplay": ["confident start", "things going wrong", "punchline moment"]},
        {"title": "POV: your first time playing {game}", "hook": "Your first five minutes in {game} be like.",
         "concept": "Relatable newbie moments with {focus}.",
         "angle": "POV humour, quick beats.", "dur": 20,
         "gameplay": ["confused moment", "fail", "small win"]},
    ],
    "comparison": [
        {"title": "Top 3 tips for {focus} in {game}", "hook": "Ranking my three best {game} tips.",
         "concept": "Ranked list, number three to number one, each with a clip.",
         "angle": "Countdown with the best saved for last.", "dur": 30,
         "gameplay": ["option three", "option two", "option one"]},
        {"title": "Slow way vs fast way in {game}", "hook": "There's a slow way and a fast way to play {game}.",
         "concept": "Side-by-side comparison of two approaches to {focus}.",
         "angle": "A versus B, clear winner.", "dur": 25,
         "gameplay": ["slow method", "fast method", "result comparison"]},
    ],
    "surprising_mechanic": [
        {"title": "{game} has a mechanic nobody talks about", "hook": "Wait, you can actually do this in {game}?",
         "concept": "Demonstrate a surprising interaction involving {focus}.",
         "angle": "Disbelief, demonstration, practical use.", "dur": 20,
         "gameplay": ["the mechanic in action", "practical use"]},
        {"title": "This {game} feature changes everything", "hook": "One feature in {game} changes how you should play.",
         "concept": "Explain how a feature around {focus} changes strategy.",
         "angle": "Claim, proof, implication.", "dur": 25,
         "gameplay": ["feature close-up", "before/after using it"]},
    ],
}


class IdeaModel(BaseModel):
    category: str
    title: str
    hook: str
    concept: str
    script_angle: str
    estimated_duration_seconds: int
    required_gameplay: list[str]
    cta: str


class IdeasResult(BaseModel):
    ideas: list[IdeaModel]


def _focus_terms(campaign: dict[str, Any]) -> list[str]:
    analysis = campaign.get("analysis") or {}
    terms = [*campaign.get("content_goals", []), *analysis.get("game_mechanics", [])]
    cleaned = []
    for t in terms:
        t = re.sub(r"^(show|showcase|highlight|feature|promote)\s+", "", t.strip(), flags=re.I).rstrip(".")
        if 2 < len(t) < 60:
            cleaned.append(t[0].lower() + t[1:])
    return cleaned or ["upgrades", "rare items", "fast progression"]


AFFINITY = {"mistake": ("mistake", "avoid"), "rare_item": ("rare", "drop", "legendary"), "progression": ("progress", "level", "fast"),
            "tutorial": ("strategy", "guide", "how"), "secret": ("secret", "hidden", "strategy"), "challenge": ("challenge", "speed"),
            "comparison": ("strategy", "best"), "discovery": ("rare", "new", "hidden")}


def focus_for(category: str, focus: list[str], index: int) -> str:
    """Pick the content goal that best fits a category, falling back to round-robin."""
    for kw in AFFINITY.get(category, ()):
        for f in focus:
            if kw in f.lower():
                return f
    return focus[index % len(focus)]


def build_cta(campaign: dict[str, Any]) -> str:
    rules = campaign_rules(campaign)
    game = campaign.get("game") or "the game"
    parts = [f"Play {game} on Roblox"]
    if rules["codes"]:
        parts.append(f"and use code {rules['codes'][0]}")
    return " ".join(parts) + "."


def compliance(campaign: dict[str, Any], idea: dict[str, Any]) -> tuple[float, list[str]]:
    rules = campaign_rules(campaign)
    text = " ".join([idea["title"], idea["hook"], idea["concept"], idea["script_angle"], idea["cta"]])
    checks: list[tuple[bool, str]] = [(bool(idea["cta"].strip()), "Has a call to action")]
    if rules["codes"]:
        ok = any(contains_phrase(idea["cta"], c) for c in rules["codes"])
        checks.append((ok, f"CTA mentions code {rules['codes'][0]}"))
    for term in rules["banned_terms"]:
        checks.append((not contains_phrase(text, term), f"Avoids banned term '{term}'"))
    if rules["max_seconds"]:
        checks.append((idea["est_duration"] <= rules["max_seconds"], f"≤ {rules['max_seconds']}s"))
    if rules["min_seconds"]:
        checks.append((idea["est_duration"] >= rules["min_seconds"], f"≥ {rules['min_seconds']}s"))
    game = campaign.get("game")
    if game:
        checks.append((contains_phrase(text, game), f"Names the game ({game})"))
    passed = sum(1 for ok, _ in checks if ok)
    notes = [("PASS " if ok else "FAIL ") + label for ok, label in checks]
    return round(passed / len(checks), 2), notes


def _novelty(ideas: list[dict[str, Any]]) -> None:
    toks = [tokens(" ".join([i["title"], i["hook"], i["concept"], i["script_angle"]])) for i in ideas]
    for idx, idea in enumerate(ideas):
        others = [jaccard(toks[idx], t) for j, t in enumerate(toks) if j != idx]
        idea["novelty_score"] = round(1 - max(others), 2) if others else 1.0


def _fit_duration(dur: int, rules: dict[str, Any]) -> int:
    if rules["max_seconds"]:
        dur = min(dur, int(rules["max_seconds"]))
    if rules["min_seconds"]:
        dur = max(dur, int(rules["min_seconds"]))
    return dur


def heuristic_idea(campaign: dict[str, Any], category: str, variant: int, focus: str) -> dict[str, Any]:
    patterns = PATTERNS[category]
    p = patterns[variant % len(patterns)]
    game = campaign.get("game") or campaign.get("name") or "this game"
    fmt = {"game": game, "focus": focus}
    return {
        "category": category,
        "title": p["title"].format(**fmt),
        "hook": p["hook"].format(**fmt),
        "concept": p["concept"].format(**fmt),
        "script_angle": p["angle"],
        "est_duration": _fit_duration(p["dur"], campaign_rules(campaign)),
        "required_gameplay": p["gameplay"],
        "cta": build_cta(campaign),
        "generator": "offline-heuristic",
        "variant": variant,
    }


IDEAS_SYSTEM = """You create short-form (TikTok/Reels/Shorts) video concepts for Roblox clipping campaigns.
Every concept must be meaningfully different: different category, hook structure, footage and ending.
Respect the campaign's confirmed requirements and restrictions exactly. Do not invent statistics or claims
about the game you cannot verify from the material. Hooks must work in the first 2 seconds, spoken aloud."""


def generate_ideas(db: Database, llm: ClaudeClient, campaign_id: str, *, count: int = 10,
                   use_ai: bool = True, replace: bool = True) -> dict[str, Any]:
    campaign = db.get("campaigns", campaign_id)
    if count < 1 or count > 30:
        raise ValidationError("Choose between 1 and 30 ideas.")
    categories = [CATEGORIES[i % len(CATEGORIES)] for i in range(count)]
    focus = _focus_terms(campaign)
    warning = None
    ideas: list[dict[str, Any]] = []
    if use_ai and llm.available:
        prompt = (
            f"Campaign JSON:\n{_campaign_brief(campaign)}\n\nCreate exactly {count} concepts, one per category in this "
            f"order: {', '.join(categories)}. Estimated durations between 15 and 45 seconds."
        )
        result = llm.structured(system=IDEAS_SYSTEM, prompt=prompt, schema=IdeasResult)
        rules = campaign_rules(campaign)
        for cat, m in zip(categories, result.ideas, strict=False):
            ideas.append({
                "category": cat, "title": m.title, "hook": m.hook, "concept": m.concept,
                "script_angle": m.script_angle, "est_duration": _fit_duration(m.estimated_duration_seconds, rules),
                "required_gameplay": m.required_gameplay, "cta": m.cta,
                "generator": f"anthropic:{llm.settings.anthropic_model}",
            })
    else:
        if use_ai:
            warning = "Claude is not configured (ANTHROPIC_API_KEY missing); ideas come from the offline pattern generator."
        for i, cat in enumerate(categories):
            ideas.append(heuristic_idea(campaign, cat, i // len(CATEGORIES), focus_for(cat, focus, i)))
    _novelty(ideas)
    if replace:
        with db._lock:
            db.conn.execute("DELETE FROM ideas WHERE campaign_id = ? AND id NOT IN "
                            "(SELECT idea_id FROM projects WHERE idea_id IS NOT NULL)", (campaign_id,))
            db.conn.commit()
    start = int(db.scalar("SELECT COALESCE(MAX(position), -1) FROM ideas WHERE campaign_id = ?", [campaign_id])) + 1
    saved = []
    for pos, idea in enumerate(ideas, start=start):
        score, notes = compliance(campaign, idea)
        saved.append(db.insert("ideas", {
            "campaign_id": campaign_id, "position": pos, "category": idea["category"], "title": idea["title"],
            "hook": idea["hook"], "concept": idea["concept"], "script_angle": idea["script_angle"],
            "est_duration": idea["est_duration"], "required_gameplay": idea["required_gameplay"], "cta": idea["cta"],
            "novelty_score": idea["novelty_score"], "compliance_score": score, "compliance_notes": notes,
            "generator": idea["generator"],
        }))
    return {"ideas": saved, "warning": warning}


def regenerate_idea(db: Database, llm: ClaudeClient, idea_id: str, *, use_ai: bool = True) -> dict[str, Any]:
    old = db.get("ideas", idea_id)
    campaign = db.get("campaigns", old["campaign_id"])
    siblings = [i for i in db.list("ideas", "campaign_id = ?", [campaign["id"]], order="position") if i["id"] != idea_id]
    warning = None
    new: dict[str, Any] | None = None
    if use_ai and llm.available:
        prompt = (
            f"Campaign JSON:\n{_campaign_brief(campaign)}\n\nExisting concepts (do NOT repeat their hooks or angles):\n"
            + "\n".join(f"- [{s['category']}] {s['title']} | hook: {s['hook']}" for s in siblings)
            + f"\n- REPLACE THIS ONE: [{old['category']}] {old['title']} | hook: {old['hook']}\n\n"
            f"Return exactly 1 new concept in category '{old['category']}'."
        )
        m = llm.structured(system=IDEAS_SYSTEM, prompt=prompt, schema=IdeasResult).ideas[0]
        new = {"category": old["category"], "title": m.title, "hook": m.hook, "concept": m.concept,
               "script_angle": m.script_angle, "est_duration": _fit_duration(m.estimated_duration_seconds, campaign_rules(campaign)),
               "required_gameplay": m.required_gameplay, "cta": m.cta,
               "generator": f"anthropic:{llm.settings.anthropic_model}"}
    else:
        if use_ai:
            warning = "Claude is not configured; used the next offline pattern for this category."
        focus = _focus_terms(campaign)
        rng = random.Random(f"{idea_id}:{old['title']}")
        existing_titles = {s["title"] for s in siblings} | {old["title"]}
        for attempt in range(len(PATTERNS[old["category"]]) * len(focus)):
            cand = heuristic_idea(campaign, old["category"], attempt + 1, focus[(attempt + rng.randint(0, 99)) % len(focus)])
            if cand["title"] not in existing_titles:
                new = cand
                break
        if new is None:
            new = heuristic_idea(campaign, old["category"], 1, focus[0])
            warning = "No new offline variant left for this category; configure Claude for more variety."
    assert new is not None
    all_ideas = [*siblings, new]
    _novelty(all_ideas)
    score, notes = compliance(campaign, new)
    updated = db.update("ideas", idea_id, {
        "title": new["title"], "hook": new["hook"], "concept": new["concept"], "script_angle": new["script_angle"],
        "est_duration": new["est_duration"], "required_gameplay": new["required_gameplay"], "cta": new["cta"],
        "novelty_score": new["novelty_score"], "compliance_score": score, "compliance_notes": notes,
        "generator": new["generator"],
    })
    return {"idea": updated, "warning": warning}


def _campaign_brief(c: dict[str, Any]) -> str:
    import json

    analysis = c.get("analysis") or {}
    return json.dumps({
        "name": c["name"], "game": c["game"], "platforms": c["platforms"], "objective": c["objective"],
        "requirements": c["requirements"], "restrictions": c["restrictions"], "content_goals": c["content_goals"],
        "hook_examples": c["hook_examples"], "codes": c["codes"],
        "confirmed_items": [i for i in analysis.get("items", []) if i.get("status") == "confirmed"],
    }, ensure_ascii=False, indent=1)
