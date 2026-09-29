"""Projects (one project = one video): workflow stages, pipeline steps, approval state machine, export."""

from __future__ import annotations

import filecmp
import re
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .campaigns import campaign_rules
from .config import Settings
from .db import Database, now_iso
from .errors import ConflictError, ValidationError
from .ideas import CATEGORY_TEMPLATE
from .llm import ClaudeClient
from .logging_setup import get_logger, log_event
from .qa import run_qa
from .render import render_timeline
from .scriptgen import TARGETS, generate_script
from .templates import get_template
from .textutil import slugify
from .timeline import build_timeline, validate_timeline
from .transcription import transcribe_narration
from .voice import generate_narration

log = get_logger("projects")

STATUSES = ("DRAFT", "REVIEW", "APPROVED", "REJECTED", "EXPORTED", "POSTED", "SUBMITTED")
TRANSITIONS = {
    "DRAFT": {"REVIEW"},
    "REVIEW": {"APPROVED", "REJECTED", "DRAFT"},
    "REJECTED": {"DRAFT"},
    "APPROVED": {"EXPORTED", "DRAFT", "REJECTED"},
    "EXPORTED": {"POSTED", "DRAFT"},
    "POSTED": {"SUBMITTED"},
    "SUBMITTED": set(),
}
STAGES = ("Campaign", "Idea", "Script", "Voice", "Footage", "Timeline", "Preview", "QA", "Export", "Publishing", "Analytics")
PLATFORM_URLS = {"TikTok": "https://www.tiktok.com/upload", "Instagram": "https://www.instagram.com/",
                 "YouTube": "https://studio.youtube.com/", "X": "https://x.com/compose/post",
                 "Snapchat": "https://my.snapchat.com/", "Facebook": "https://www.facebook.com/reels/create"}
Progress = Callable[[str, float], None]


def stages(db: Database, p: dict[str, Any]) -> list[dict[str, Any]]:
    narration = db.find("narrations", p["narration_id"]) if p["narration_id"] else None
    subs = db.list("submissions", "project_id = ?", [p["id"]])
    done = {
        "Campaign": True,
        "Idea": bool(p["idea_id"]),
        "Script": bool(p["script_id"]),
        "Voice": bool(narration),
        "Footage": bool(p["media_ids"]),
        "Timeline": bool(p["timeline"]),
        "Preview": bool(p["render_path"] and Path(p["render_path"]).is_file()),
        "QA": bool(p["qa"] and p["qa"].get("overall") == "READY"),
        "Export": bool(p["export_path"]),
        "Publishing": p["status"] in ("POSTED", "SUBMITTED"),
        "Analytics": any(s["views"] > 0 for s in subs),
    }
    out, current_set = [], False
    for name in STAGES:
        state = "done" if done[name] else "todo"
        if not done[name] and not current_set:
            state, current_set = "current", True
        out.append({"name": name, "state": state})
    return out


def project_detail(db: Database, project_id: str) -> dict[str, Any]:
    p = db.get("projects", project_id)
    p["stages"] = stages(db, p)
    p["campaign"] = {k: v for k, v in db.get("campaigns", p["campaign_id"]).items() if k in ("id", "name", "slug", "game", "platforms")}
    p["idea"] = db.find("ideas", p["idea_id"]) if p["idea_id"] else None
    p["script"] = db.find("scripts", p["script_id"]) if p["script_id"] else None
    p["narration"] = db.find("narrations", p["narration_id"]) if p["narration_id"] else None
    p["ready"] = bool(p["qa"] and p["qa"].get("overall") == "READY")
    return p


def _history(p: dict[str, Any], event: str, **extra: Any) -> list[dict[str, Any]]:
    return [*p.get("history", []), {"at": now_iso(), "event": event, **extra}]


def create_project(db: Database, campaign_id: str, *, idea_id: str | None = None, title: str | None = None,
                   template_id: str | None = None, media_ids: list[str] | None = None, seed: int | None = None) -> dict[str, Any]:
    campaign = db.get("campaigns", campaign_id)
    idea = db.get("ideas", idea_id) if idea_id else None
    if idea and idea["campaign_id"] != campaign_id:
        raise ValidationError("That idea belongs to a different campaign.")
    if media_ids is None:
        media_ids = [m["id"] for m in db.list("media", "campaign_id = ? AND kind = 'video'", [campaign_id], order="created_at")]
    count = int(db.scalar("SELECT COUNT(*) FROM projects WHERE campaign_id = ?", [campaign_id]))
    p = db.insert("projects", {
        "campaign_id": campaign_id, "idea_id": idea_id,
        "title": title or (idea["title"] if idea else f"{campaign['name']} video {count + 1}"),
        "template_id": template_id or (CATEGORY_TEMPLATE.get(idea["category"], "roblox_story") if idea else "roblox_story"),
        "media_ids": media_ids, "seed": seed if seed is not None else count,
        "caption_text": idea["title"] if idea else "", "hashtags": default_hashtags(campaign),
        "history": [{"at": now_iso(), "event": "created"}],
    })
    return project_detail(db, p["id"])


def default_hashtags(campaign: dict[str, Any]) -> list[str]:
    rules_tags = [p for p in campaign_rules(campaign)["required_phrases"] if p.startswith("#")]
    game_tag = "#" + re.sub(r"[^A-Za-z0-9]", "", campaign.get("game") or "") if campaign.get("game") else None
    tags = [*rules_tags, *([game_tag] if game_tag and len(game_tag) > 1 else []), "#roblox", "#robloxclips", "#gaming"]
    return list(dict.fromkeys(tags))


def invalidate(db: Database, p: dict[str, Any], reason: str, clear: tuple[str, ...]) -> dict[str, Any]:
    """Changing inputs clears downstream results and drops approval back to DRAFT."""
    upd: dict[str, Any] = dict.fromkeys(clear)
    if p["status"] in ("REVIEW", "APPROVED", "REJECTED"):
        upd["status"] = "DRAFT"
        upd["history"] = _history(p, "reset to DRAFT", reason=reason)
    return db.update("projects", p["id"], upd)


def update_project(db: Database, project_id: str, data: dict[str, Any]) -> dict[str, Any]:
    p = db.get("projects", project_id)
    allowed = {"title", "template_id", "media_ids", "music_id", "caption_text", "hashtags", "notes", "seed"}
    upd = {k: v for k, v in data.items() if k in allowed}
    if p["status"] in ("EXPORTED", "POSTED", "SUBMITTED") and set(upd) & {"template_id", "media_ids", "music_id", "seed"}:
        raise ConflictError("This video was already exported. Duplicate the project to make changes.")
    db.update("projects", project_id, upd)
    if set(upd) & {"template_id", "media_ids", "music_id", "seed"}:
        invalidate(db, db.get("projects", project_id), "edit inputs", ("timeline", "render_path", "qa"))
    return project_detail(db, project_id)


def step_script(db: Database, llm: ClaudeClient, project_id: str, target_seconds: int | None = None, use_ai: bool = True) -> dict[str, Any]:
    p = db.get("projects", project_id)
    if not p["idea_id"]:
        raise ValidationError("Pick an idea for this project first.")
    idea = db.get("ideas", p["idea_id"])
    target = target_seconds or pick_target(idea["est_duration"], campaign_rules(db.get("campaigns", p["campaign_id"])))
    res = generate_script(db, llm, p["idea_id"], target, use_ai=use_ai)
    db.update("projects", project_id, {"script_id": res["script"]["id"]})
    invalidate(db, db.get("projects", project_id), "new script", ("narration_id", "timeline", "render_path", "qa"))
    return res


def pick_target(est_duration: int, rules: dict[str, Any]) -> int:
    """Nearest supported target that respects the campaign's confirmed length limits."""
    lo = float(rules.get("min_seconds") or 0)
    hi = float(rules.get("max_seconds") or 999)
    allowed = [t for t in TARGETS if t >= lo + 2 and t <= hi] or list(TARGETS)
    return min(allowed, key=lambda t: (abs(t - est_duration), -t))


def set_script(db: Database, project_id: str, script_id: str) -> dict[str, Any]:
    p = db.get("projects", project_id)
    s = db.get("scripts", script_id)
    if s["campaign_id"] != p["campaign_id"]:
        raise ValidationError("That script belongs to a different campaign.")
    db.update("projects", project_id, {"script_id": script_id})
    invalidate(db, db.get("projects", project_id), "script changed", ("narration_id", "timeline", "render_path", "qa"))
    return project_detail(db, project_id)


def step_voice(db: Database, settings: Settings, project_id: str, voice_profile_id: str | None = None) -> dict[str, Any]:
    p = db.get("projects", project_id)
    if not p["script_id"]:
        raise ValidationError("Write or generate a script first.")
    narration = generate_narration(db, settings, p["script_id"], voice_profile_id)
    narration = transcribe_narration(db, settings, narration["id"]) | {"cached": narration["cached"]}
    db.update("projects", project_id, {"narration_id": narration["id"]})
    invalidate(db, db.get("projects", project_id), "new narration", ("timeline", "render_path", "qa"))
    return narration


def step_timeline(db: Database, settings: Settings, project_id: str) -> dict[str, Any]:
    p = db.get("projects", project_id)
    if not p["narration_id"]:
        raise ValidationError("Generate the voiceover first.")
    narration = db.get("narrations", p["narration_id"])
    script = db.get("scripts", p["script_id"])
    campaign = db.get("campaigns", p["campaign_id"])
    idea = db.find("ideas", p["idea_id"]) if p["idea_id"] else None
    template = get_template(settings, p["template_id"])
    media = [m for m in (db.find("media", mid) for mid in p["media_ids"]) if m and m["kind"] == "video"]
    if not media:
        raise ValidationError("Select at least one gameplay video for this project.")
    segments = [s for m in media for s in db.list("segments", "media_id = ? AND enabled = 1", [m["id"]], order="start")]
    used: dict[str, int] = {}
    for other in db.list("projects", "campaign_id = ? AND id != ? AND timeline IS NOT NULL", [p["campaign_id"], project_id]):
        for it in (other["timeline"] or {}).get("items", []):
            if it.get("segment_id"):
                used[it["segment_id"]] = used.get(it["segment_id"], 0) + 1
    sfx = db.list("media", "kind = 'sfx'", order="created_at")
    music = db.find("media", p["music_id"]) if p["music_id"] else None
    if music is None:
        musics = db.list("media", "kind = 'music'", order="created_at")
        music = musics[p["seed"] % len(musics)] if musics else None
    rules = campaign_rules(campaign)
    cta = idea["cta"] if idea else (rules.get("cta") or "")
    tl = build_timeline(template=template, narration=narration, script_text=script["text"], media=media, segments=segments,
                        sfx_library=sfx, music=music, hook_text=idea["hook"] if idea else "", cta_text=cta,
                        emphasis_terms=[*rules["codes"], campaign.get("game") or ""], seed=int(p["seed"]), used_elsewhere=used)
    db.update("projects", project_id, {"timeline": tl})
    invalidate(db, db.get("projects", project_id), "new timeline", ("render_path", "qa"))
    return tl


def save_timeline(db: Database, project_id: str, timeline: dict[str, Any]) -> dict[str, Any]:
    """Manual timeline edits from the UI (validated against the schema)."""
    p = db.get("projects", project_id)
    if p["status"] in ("EXPORTED", "POSTED", "SUBMITTED"):
        raise ConflictError("This video was already exported. Duplicate the project to edit it.")
    validate_timeline(timeline)
    db.update("projects", project_id, {"timeline": timeline})
    invalidate(db, db.get("projects", project_id), "timeline edited", ("render_path", "qa"))
    return timeline


def step_render(db: Database, settings: Settings, project_id: str, quality: str = "final",
                progress: Progress | None = None) -> dict[str, Any]:
    p = db.get("projects", project_id)
    if not p["timeline"]:
        raise ValidationError("Build the timeline first.")
    info = render_timeline(settings, p["timeline"], settings.renders_dir / project_id, quality=quality, progress=progress)
    db.update("projects", project_id, {"render_path": info["path"], "qa": None,
                                       "history": _history(p, "rendered", quality=quality, cached=info["cached"])})
    return info


def step_qa(db: Database, settings: Settings, project_id: str) -> dict[str, Any]:
    p = db.get("projects", project_id)
    if not p["render_path"]:
        raise ValidationError("Render the video first.")
    campaign = db.get("campaigns", p["campaign_id"])
    script = db.get("scripts", p["script_id"]) if p["script_id"] else {"text": ""}
    prefs = db.get_setting("preferences", {})
    options = {"max_silence_seconds": float(prefs["max_silence_seconds"])} if "max_silence_seconds" in prefs else None
    qa = run_qa(settings, Path(p["render_path"]), p["timeline"], script_text=script["text"], rules=campaign_rules(campaign),
                options=options)
    upd: dict[str, Any] = {"qa": qa}
    if qa["overall"] == "READY" and p["status"] == "DRAFT":
        upd["status"] = "REVIEW"
        upd["history"] = _history(p, "QA passed → REVIEW")
    db.update("projects", project_id, upd)
    log_event(log, "qa", project_id=project_id, overall=qa["overall"], failed=qa["failed"])
    return qa


def run_pipeline(db: Database, settings: Settings, llm: ClaudeClient, project_id: str, *, target_seconds: int | None = None,
                 use_ai: bool = True, voice_profile_id: str | None = None, quality: str = "final",
                 progress: Progress | None = None) -> dict[str, Any]:
    """Idea → Script → Voice → Transcription → Timeline → Render → QA for one project."""
    def report(msg: str, frac: float) -> None:
        if progress:
            progress(msg, frac)
    p = db.get("projects", project_id)
    if not p["script_id"]:
        report("Writing script", 0.05)
        step_script(db, llm, project_id, target_seconds, use_ai)
    if not db.get("projects", project_id)["narration_id"]:
        report("Generating voiceover", 0.15)
        step_voice(db, settings, project_id, voice_profile_id)
    if not db.get("projects", project_id)["timeline"]:
        report("Building timeline", 0.25)
        step_timeline(db, settings, project_id)
    report("Rendering", 0.3)
    step_render(db, settings, project_id, quality, lambda m, f: report(m, 0.3 + 0.6 * f))
    report("Running QA", 0.92)
    step_qa(db, settings, project_id)
    report("Done", 1.0)
    return project_detail(db, project_id)


def transition(db: Database, project_id: str, target: str, note: str = "") -> dict[str, Any]:
    p = db.get("projects", project_id)
    if target not in STATUSES:
        raise ValidationError(f"Unknown status {target}.")
    if target not in TRANSITIONS[p["status"]]:
        raise ConflictError(f"Cannot move a {p['status']} video to {target}.",
                            hint=f"Allowed next states: {', '.join(sorted(TRANSITIONS[p['status']])) or 'none'}.")
    if target == "REVIEW" and not (p["qa"] and p["qa"].get("overall") == "READY"):
        raise ConflictError("Only videos that passed QA can be sent to review.")
    if target == "APPROVED" and not (p["render_path"] and Path(p["render_path"]).is_file()):
        raise ConflictError("There is no rendered video to approve.")
    if target == "REJECTED" and not note.strip():
        raise ValidationError("Add a short reason when rejecting, so the next version can fix it.")
    db.update("projects", project_id, {"status": target, "history": _history(p, f"{p['status']} → {target}", note=note)})
    return project_detail(db, project_id)


def export_project(db: Database, settings: Settings, project_id: str) -> dict[str, Any]:
    p = db.get("projects", project_id)
    if p["status"] != "APPROVED":
        raise ConflictError("Approve the video before exporting it.", hint="Human approval is required before export.")
    src = Path(p["render_path"] or "")
    if not src.is_file():
        raise ConflictError("The rendered file is missing. Render again.")
    campaign = db.get("campaigns", p["campaign_id"])
    idea = db.find("ideas", p["idea_id"]) if p["idea_id"] else None
    folder = settings.exports_dir / campaign["slug"]
    folder.mkdir(parents=True, exist_ok=True)
    base = f"concept-{(idea['position'] + 1) if idea else 0:02d}" + (f"-{slugify(idea['category'])}" if idea else "")
    dest = safe_export_path(folder, base, ".mp4", src)
    if not dest.exists():
        tmp = dest.with_suffix(".partial")
        shutil.copy2(src, tmp)
        tmp.replace(dest)
    sidecar = dest.with_suffix(".txt")
    if not sidecar.exists():
        sidecar.write_text(f"{p['caption_text']}\n\n{' '.join(p['hashtags'])}\n", encoding="utf-8")
    db.update("projects", project_id, {"export_path": str(dest), "status": "EXPORTED",
                                       "history": _history(p, "APPROVED → EXPORTED", path=str(dest))})
    return project_detail(db, project_id)


def safe_export_path(folder: Path, base: str, ext: str, src: Path | None = None) -> Path:
    """First free name: base.mp4, base-v2.mp4, ... Identical content re-uses its existing file; never overwrites."""
    base = slugify(base)
    n = 1
    while True:
        cand = folder / (f"{base}{ext}" if n == 1 else f"{base}-v{n}{ext}")
        if not cand.exists():
            return cand
        if src is not None and cand.stat().st_size == src.stat().st_size and filecmp.cmp(cand, src, shallow=False):
            return cand
        n += 1


def duplicate_project(db: Database, project_id: str) -> dict[str, Any]:
    p = db.get("projects", project_id)
    new = db.insert("projects", {
        k: p[k] for k in ("campaign_id", "idea_id", "script_id", "narration_id", "template_id", "media_ids", "music_id",
                          "caption_text", "hashtags", "notes", "timeline")
    } | {"title": p["title"] + " (copy)", "seed": int(p["seed"]) + 100, "history": [{"at": now_iso(), "event": f"duplicated from {project_id}"}]})
    return project_detail(db, new["id"])


def publish_kit(db: Database, project_id: str) -> dict[str, Any]:
    """Everything needed for fast manual posting (the default, intentional publishing path)."""
    p = db.get("projects", project_id)
    campaign = db.get("campaigns", p["campaign_id"])
    return {
        "caption": p["caption_text"], "hashtags": p["hashtags"], "hashtags_text": " ".join(p["hashtags"]),
        "platforms": [{"name": pl, "url": PLATFORM_URLS.get(pl, "")} for pl in (campaign["platforms"] or ["TikTok", "Instagram", "YouTube"])],
        "file": p["export_path"], "campaign_url": campaign["url"], "status": p["status"],
    }
