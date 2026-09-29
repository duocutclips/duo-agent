"""Submission tracker and analytics."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from .db import Database, now_iso
from .errors import ValidationError

SUBMISSION_STATUSES = ("PENDING", "SUBMITTED", "APPROVED", "REJECTED", "PAID")
METRICS = ("views", "likes", "comments", "shares", "saves")
MIN_SAMPLE = 5  # below this, comparisons are reported as "not enough data"


def _clean(data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in ("platform", "post_url", "submitted_at", "status", "notes", "project_id", "campaign_id", "metrics_source"):
        if k in data and data[k] is not None:
            out[k] = data[k]
    for k in METRICS:
        if k in data and data[k] is not None:
            try:
                v = int(data[k])
            except (TypeError, ValueError) as exc:
                raise ValidationError(f"{k} must be a whole number.") from exc
            if v < 0:
                raise ValidationError(f"{k} cannot be negative.")
            out[k] = v
    if "earnings" in data:
        out["earnings"] = None if data["earnings"] in (None, "") else float(data["earnings"])
    if "approved" in data:
        out["approved"] = None if data["approved"] is None else int(bool(data["approved"]))
    if "status" in out and out["status"] not in SUBMISSION_STATUSES:
        raise ValidationError(f"Status must be one of {', '.join(SUBMISSION_STATUSES)}.")
    if out.get("post_url") and not str(out["post_url"]).startswith(("http://", "https://")):
        raise ValidationError("Post URL must start with http:// or https://")
    return out


def create_submission(db: Database, data: dict[str, Any]) -> dict[str, Any]:
    d = _clean(data)
    if not d.get("platform"):
        raise ValidationError("Platform is required.")
    project = db.get("projects", d["project_id"]) if d.get("project_id") else None
    if project:
        d.setdefault("campaign_id", project["campaign_id"])
    if not d.get("campaign_id"):
        raise ValidationError("Campaign is required.")
    db.get("campaigns", d["campaign_id"])
    if d.get("post_url") and not d.get("submitted_at"):
        d["submitted_at"] = now_iso()
    sub = db.insert("submissions", d)
    if project and project["status"] == "POSTED" and d.get("status", "PENDING") != "PENDING":
        db.update("projects", project["id"], {"status": "SUBMITTED",
                                              "history": [*project["history"], {"at": now_iso(), "event": "POSTED → SUBMITTED"}]})
    return sub


def update_submission(db: Database, sub_id: str, data: dict[str, Any]) -> dict[str, Any]:
    sub = db.update("submissions", sub_id, _clean(data))
    if sub["project_id"] and sub["status"] in ("SUBMITTED", "APPROVED", "PAID"):
        p = db.get("projects", sub["project_id"])
        if p["status"] == "POSTED":
            db.update("projects", p["id"], {"status": "SUBMITTED",
                                            "history": [*p["history"], {"at": now_iso(), "event": "POSTED → SUBMITTED"}]})
    return sub


def estimated_earnings(sub: dict[str, Any], cpm: float | None) -> float | None:
    if sub.get("earnings") is not None:
        return float(sub["earnings"])
    if cpm is None:
        return None
    return round(sub["views"] / 1000.0 * cpm, 2)


def analytics(db: Database, campaign_id: str | None = None) -> dict[str, Any]:
    where, params = ("campaign_id = ?", [campaign_id]) if campaign_id else ("", [])
    subs = db.list("submissions", where, params, order="created_at")
    campaigns = {c["id"]: c for c in db.list("campaigns")}
    projects = {p["id"]: p for p in db.list("projects")}
    ideas = {i["id"]: i for i in db.list("ideas")}
    rows = []
    for s in subs:
        c = campaigns.get(s["campaign_id"], {})
        p = projects.get(s["project_id"] or "", {})
        idea = ideas.get(p.get("idea_id") or "", {})
        est = estimated_earnings(s, c.get("payout_cpm"))
        rows.append(s | {"campaign_name": c.get("name"), "template_id": p.get("template_id"), "hook": idea.get("hook"),
                         "category": idea.get("category"), "estimated_earnings": est,
                         "effective_cpm": round(est / s["views"] * 1000, 2) if est is not None and s["views"] else None,
                         "engagement_rate": round(sum(s[k] for k in ("likes", "comments", "shares", "saves")) / s["views"], 4)
                         if s["views"] else None})
    total_views = sum(r["views"] for r in rows)
    earn = [r["estimated_earnings"] for r in rows if r["estimated_earnings"] is not None]
    videos = {r["project_id"] for r in rows if r["project_id"]}

    def group(key: str) -> list[dict[str, Any]]:
        g: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for r in rows:
            if r.get(key):
                g[r[key]].append(r)
        out = [{"key": k, "posts": len(v), "total_views": sum(x["views"] for x in v),
                "avg_views": round(sum(x["views"] for x in v) / len(v), 1)} for k, v in g.items()]
        return sorted(out, key=lambda x: -x["avg_views"])

    by_hook, by_template, by_category = group("hook"), group("template_id"), group("category")
    enough = len(rows) >= MIN_SAMPLE
    note = None if enough else (f"Only {len(rows)} post(s) tracked. Rankings below are descriptive, not evidence "
                                f"that a hook or template causes more views (need at least {MIN_SAMPLE}, ideally many more).")
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "totals": {
            "posts": len(rows), "videos": len(videos), "views": total_views,
            "likes": sum(r["likes"] for r in rows), "comments": sum(r["comments"] for r in rows),
            "shares": sum(r["shares"] for r in rows), "saves": sum(r["saves"] for r in rows),
            "earnings": round(sum(earn), 2) if earn else 0.0,
            "avg_views_per_post": round(total_views / len(rows), 1) if rows else 0,
            "avg_views_per_video": round(total_views / len(videos), 1) if videos else 0,
            "effective_cpm": round(sum(earn) / total_views * 1000, 2) if earn and total_views else None,
        },
        "best_hook": by_hook[0] if by_hook and enough else None,
        "best_template": by_template[0] if by_template and enough else None,
        "by_hook": by_hook, "by_template": by_template, "by_category": by_category,
        "sample_note": note, "rows": rows,
    }


def dashboard(db: Database) -> dict[str, Any]:
    a = analytics(db)
    recent = db.list("projects", order="updated_at DESC")[:8]
    return {
        "active_campaigns": db.scalar("SELECT COUNT(*) FROM campaigns"),
        "videos_generated": db.scalar("SELECT COUNT(*) FROM projects WHERE render_path IS NOT NULL"),
        "videos_ready": db.scalar("SELECT COUNT(*) FROM projects WHERE status IN ('REVIEW','APPROVED','EXPORTED')"),
        "videos_posted": db.scalar("SELECT COUNT(*) FROM projects WHERE status IN ('POSTED','SUBMITTED')"),
        "total_views": a["totals"]["views"],
        "estimated_earnings": a["totals"]["earnings"],
        "recent_projects": [{k: p[k] for k in ("id", "title", "status", "campaign_id", "updated_at", "template_id")}
                            | {"ready": bool(p["qa"] and p["qa"].get("overall") == "READY")} for p in recent],
    }
