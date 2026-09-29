"""One campaign -> many meaningfully different videos, plus a report that measures how different they are."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .config import Settings
from .db import Database
from .errors import AppError, ValidationError
from .llm import ClaudeClient
from .projects import create_project, run_pipeline
from .textutil import jaccard, tokens

Progress = Callable[[str, float], None]


def generate_batch(db: Database, settings: Settings, llm: ClaudeClient, campaign_id: str, *, idea_ids: list[str] | None = None,
                   count: int = 3, use_ai: bool = True, quality: str = "final", voice_profile_id: str | None = None,
                   progress: Progress | None = None) -> dict[str, Any]:
    ideas = db.list("ideas", "campaign_id = ?", [campaign_id], order="position")
    chosen = [i for i in ideas if i["id"] in set(idea_ids)] if idea_ids else ideas[:count]
    if not chosen:
        raise ValidationError("Generate ideas for this campaign first.")
    results = []
    for n, idea in enumerate(chosen):
        def sub(msg: str, frac: float, n: int = n) -> None:
            if progress:
                progress(f"Video {n + 1}/{len(chosen)}: {msg}", (n + frac) / len(chosen))
        project = create_project(db, campaign_id, idea_id=idea["id"])
        try:
            p = run_pipeline(db, settings, llm, project["id"], use_ai=use_ai, quality=quality,
                             voice_profile_id=voice_profile_id, progress=sub)
            results.append({"project_id": p["id"], "title": p["title"], "status": p["status"],
                            "qa": p["qa"]["overall"] if p["qa"] else None})
        except AppError as exc:
            results.append({"project_id": project["id"], "title": project["title"], "status": "DRAFT", "error": exc.to_dict()})
    return {"projects": results, "variation_report": variation_report(db, [r["project_id"] for r in results])}


def _features(db: Database, p: dict[str, Any]) -> dict[str, Any]:
    idea = db.find("ideas", p["idea_id"]) if p["idea_id"] else {}
    script = db.find("scripts", p["script_id"]) if p["script_id"] else {}
    items = (p["timeline"] or {}).get("items", [])
    videos = [i for i in items if i["type"] == "video"]
    return {
        "hook": (idea or {}).get("hook", ""),
        "script": tokens((script or {}).get("text", "")),
        "footage": {f"{i['media_id']}@{round(i['src_in'])}" for i in videos},
        "sfx": {f"{i['category']}@{round(i['start'], 1)}" for i in items if i["type"] == "sfx"},
        "template": p["template_id"],
        "cuts": len(videos),
        "ending": (script or {}).get("text", "").split(".")[-2:] if script else [],
    }


def variation_report(db: Database, project_ids: list[str]) -> dict[str, Any]:
    ps = [db.get("projects", pid) for pid in project_ids]
    feats = {p["id"]: _features(db, p) for p in ps}
    pairs = []
    for i, a in enumerate(ps):
        for b in ps[i + 1:]:
            fa, fb = feats[a["id"]], feats[b["id"]]
            pairs.append({
                "a": a["title"], "b": b["title"],
                "same_hook": fa["hook"] == fb["hook"],
                "script_overlap": round(jaccard(fa["script"], fb["script"]), 2),
                "footage_overlap": round(jaccard(fa["footage"], fb["footage"]), 2),
                "sfx_overlap": round(jaccard(fa["sfx"], fb["sfx"]), 2),
                "same_template": fa["template"] == fb["template"],
                "cut_count": [fa["cuts"], fb["cuts"]],
            })
    return {"videos": len(ps), "pairs": pairs,
            "max_script_overlap": max((p["script_overlap"] for p in pairs), default=0),
            "max_footage_overlap": max((p["footage_overlap"] for p in pairs), default=0),
            "duplicate_hooks": sum(1 for p in pairs if p["same_hook"])}
