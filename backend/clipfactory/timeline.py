"""Automatic editing: SCRIPT + VOICEOVER + GAMEPLAY SEGMENTS -> timeline.

Rules implemented (see docs/VIDEO_PIPELINE.md):
1. The strongest segment (hook candidate) opens the video.
2. Cuts land on narration boundaries (sentence ends first, then phrase/word ends).
3. No shot is longer than the template's ``max_cut`` (no long periods without visual change).
4. Punch-ins every N cuts and on emphasised words, never overlapping.
5. Visual variety: a segment is not reused while alternatives exist; consecutive shots prefer different
   sources; segments used by other videos of the same campaign are penalised (variations differ).
6. Segment windows are kept intact where possible so gameplay context is preserved.
"""

from __future__ import annotations

import json
import random
import re
from pathlib import Path
from typing import Any

import jsonschema

from .captions import build_caption_items
from .config import REPO_ROOT
from .errors import ValidationError

SCHEMA_PATH = REPO_ROOT / "packages" / "timeline-schema" / "timeline.schema.json"
_schema: dict[str, Any] | None = None
NARRATION_OFFSET = 0.15


def schema() -> dict[str, Any]:
    global _schema
    if _schema is None:
        _schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return _schema


def validate_timeline(tl: dict[str, Any]) -> None:
    try:
        jsonschema.validate(tl, schema())
    except jsonschema.ValidationError as exc:
        path = "/".join(str(p) for p in exc.absolute_path)
        raise ValidationError(f"Timeline is invalid at '{path or '(root)'}': {exc.message[:300]}") from exc
    videos = sorted((i for i in tl["items"] if i["type"] == "video"), key=lambda i: i["start"])
    if not videos:
        raise ValidationError("Timeline has no video clips.")
    t = 0.0
    for v in videos:
        if abs(v["start"] - t) > 0.02:
            raise ValidationError(f"Video clips must be contiguous; gap or overlap at {t:.2f}s.")
        if v["end"] - v["start"] < 0.2:
            raise ValidationError(f"Video clip at {v['start']:.2f}s is shorter than 0.2s.")
        t = v["end"]
    if abs(t - tl["duration"]) > 0.05:
        raise ValidationError(f"Video clips end at {t:.2f}s but the timeline lasts {tl['duration']:.2f}s.")
    for i in tl["items"]:
        if "end" in i and "start" in i and i["end"] < i["start"]:
            raise ValidationError(f"{i['type']} item ends before it starts ({i['start']}–{i['end']}).")


def cut_points(words: list[dict[str, Any]], total: float, min_cut: float, max_cut: float, offset: float) -> list[float]:
    """Cut times aligned to narration boundaries, respecting min/max shot length."""
    sentence_ends = [w["end"] + offset for w in words if re.search(r"[.!?]$", str(w.get("word", "")))]
    phrase_ends = [w["end"] + offset for w in words if re.search(r"[,;:]$", str(w.get("word", "")))]
    word_starts = [w["start"] + offset for w in words]
    cuts = [0.0]
    t = 0.0
    target = (min_cut + max_cut) / 2
    while total - t > max_cut:
        lo, hi = t + min_cut, t + max_cut
        chosen = None
        for group in (sentence_ends, phrase_ends, word_starts):
            options = [c for c in group if lo <= c <= hi and total - c >= min_cut * 0.8]
            if options:
                chosen = min(options, key=lambda c: abs(c - (t + target)))
                break
        if chosen is None:
            chosen = min(hi, total - min_cut)
        if chosen <= t + 0.2:
            break
        cuts.append(round(chosen, 3))
        t = chosen
    cuts.append(round(total, 3))
    return cuts


def _pick_segments(segments: list[dict[str, Any]], slots: int, media_by_id: dict[str, dict[str, Any]],
                   used_elsewhere: dict[str, int], rng: random.Random, hook_first: bool) -> list[dict[str, Any]]:
    pool = [s for s in segments if s.get("enabled", True) and s["kind"] != "static"]
    if not pool:
        pool = list(segments)
    picks: list[dict[str, Any]] = []
    use_count: dict[str, int] = {}
    for slot in range(slots):
        def score(s: dict[str, Any], slot: int = slot) -> float:
            v = float(s["score"]) + rng.uniform(0, 0.12)
            v -= 0.8 * use_count.get(s["id"], 0)
            v -= 0.25 * min(3, used_elsewhere.get(s["id"], 0))
            if picks and picks[-1]["media_id"] == s["media_id"] and len(media_by_id) > 1:
                v -= 0.15
            if picks and picks[-1]["id"] == s["id"]:
                v -= 2
            if "repeated" in s.get("tags", []):
                v -= 0.2
            if slot == 0 and hook_first and "hook_candidate" in s.get("tags", []):
                v += 0.5
            return v
        best = max(pool, key=score)
        use_count[best["id"]] = use_count.get(best["id"], 0) + 1
        picks.append(best)
    return picks


def fallback_segments(media: list[dict[str, Any]], length: float = 3.0) -> list[dict[str, Any]]:
    """Evenly spaced windows for footage that has not been analysed."""
    out = []
    for m in media:
        dur = float(m.get("duration") or 0)
        t = 0.0
        while dur - t >= 1.0:
            out.append({"id": f"{m['id']}@{t:.1f}", "media_id": m["id"], "start": t, "end": min(dur, t + length),
                        "score": 0.3, "kind": "moderate", "tags": ["unanalysed"], "enabled": True, "label": "Unanalysed window"})
            t += length
    return out


def build_timeline(*, template: dict[str, Any], narration: dict[str, Any], script_text: str, media: list[dict[str, Any]],
                   segments: list[dict[str, Any]], sfx_library: list[dict[str, Any]], music: dict[str, Any] | None,
                   hook_text: str, cta_text: str, emphasis_terms: list[str], seed: int,
                   used_elsewhere: dict[str, int] | None = None, images: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    if not media:
        raise ValidationError("Add at least one gameplay video to this project before building the timeline.")
    words = narration.get("words") or []
    if not words:
        raise ValidationError("The narration has no word timings yet. Run transcription first.")
    rng = random.Random(seed)
    warnings: list[str] = []
    pacing, zoom_t, cta_t, hook_t = (template["pacing"], template["zoom"],
                                            template["cta"], template["hook"])
    narr_dur = float(narration["duration"])
    cta_hold = float(cta_t.get("seconds", 2.0)) * 0.4 if cta_t.get("end_card") else 0.3
    total = round(NARRATION_OFFSET + narr_dur + cta_hold, 3)
    media_by_id = {m["id"]: m for m in media}
    segs = [s for s in segments if s["media_id"] in media_by_id]
    if not segs:
        segs = fallback_segments(media)
        warnings.append("Footage has not been analysed; using evenly spaced windows. Run analysis for better picks.")
    cuts = cut_points(words, total, float(pacing["min_cut"]), float(pacing["max_cut"]), NARRATION_OFFSET)
    picks = _pick_segments(segs, len(cuts) - 1, media_by_id, used_elsewhere or {}, rng, bool(hook_t.get("use_best_segment", True)))
    items: list[dict[str, Any]] = []
    fit = template.get("fit", "blur")
    for i, (a, b) in enumerate(zip(cuts, cuts[1:], strict=False)):
        seg = picks[i]
        m = media_by_id[seg["media_id"]]
        need = b - a
        src_dur = float(m.get("duration") or 0)
        seg_len = seg["end"] - seg["start"]
        # centre the shot on the segment, extending into surrounding footage when the slot is longer
        src_in = seg["start"] + max(0.0, (seg_len - need) / 2) if seg_len >= need else seg["start"] - (need - seg_len) / 2
        src_in = max(0.0, min(src_in, max(0.0, src_dur - need)))
        if src_dur < need:
            warnings.append(f"{m['filename']} is shorter than a {need:.1f}s shot; the last frame will be held.")
        items.append({"type": "video", "source": m["path"], "media_id": m["id"],
                      "segment_id": None if "@" in str(seg["id"]) else seg["id"], "src_in": round(src_in, 3),
                      "start": round(a, 3), "end": round(b, 3), "fit": fit, "label": seg.get("label", "")})
    # --- zooms
    zooms: list[tuple[float, float]] = []
    intensity = float(zoom_t["intensity"])
    ramp, hold = float(zoom_t["ramp"]), float(zoom_t["hold"])

    def add_zoom(at: float, scale: float) -> None:
        dur = ramp * 2 + hold
        if intensity <= 0 or at + dur > total - 0.1:
            return
        if any(not (at + dur + 0.15 <= s or at >= e + 0.15) for s, e in zooms):
            return
        # never let a zoom span a cut (it would restart mid-ramp on the next clip)
        if any(at < c < at + dur for c in cuts[1:-1]):
            return
        zooms.append((at, at + dur))
        items.append({"type": "zoom", "start": round(at, 3), "duration": round(dur, 3), "scale": round(scale, 3), "ramp": ramp})

    if hook_t.get("punch_in") and len(words) > 1:
        add_zoom(round(words[1]["start"] + NARRATION_OFFSET, 3), 1 + intensity * 1.2)
    n = int(zoom_t.get("every_n_cuts", 0) or 0)
    if n:
        for idx, c in enumerate(cuts[1:-1], start=1):
            if idx % n == 0:
                add_zoom(c + 0.12, 1 + intensity)
    if zoom_t.get("on_emphasis"):
        emph = {t.lower() for term in emphasis_terms for t in re.findall(r"\w+", term)}
        for w in words:
            core = re.sub(r"[^\w]", "", str(w.get("word", ""))).lower()
            if core and (core in emph or any(ch.isdigit() for ch in core)):
                add_zoom(round(w["start"] + NARRATION_OFFSET - ramp / 2, 3), 1 + intensity * 0.8)
    # --- captions and text cards
    caption_items = build_caption_items(words, max_words=int(template["captions"]["max_words"]),
                                        offset=NARRATION_OFFSET, emphasis_terms=emphasis_terms)
    items.extend(caption_items)
    if hook_t.get("title_card") and hook_text:
        items.append({"type": "text", "role": "title", "start": 0.0, "end": round(min(total, float(hook_t.get("title_seconds", 1.8))), 3),
                      "text": hook_text})
    if cta_t.get("end_card") and cta_text:
        cs = max(0.0, total - float(cta_t.get("seconds", 2.0)))
        items.append({"type": "text", "role": "cta", "start": round(cs, 3), "end": total, "text": cta_text})
    # --- image overlays (logos, stickers)
    for img in images or []:
        items.append({"type": "image", "source": img["path"], "start": 0.0, "end": total, "x": 60, "y": 60,
                      "width": 220, "fade": 0.3})
    # --- audio
    items.append({"type": "narration", "source": narration["audio_path"], "start": NARRATION_OFFSET, "volume": 1.0})
    mt = template["music"]
    if music and mt.get("enabled", True):
        items.append({"type": "music", "source": music["path"], "volume": float(mt["volume"]), "fade_in": float(mt["fade_in"]),
                      "fade_out": float(mt["fade_out"]), "loop": bool(mt.get("loop", True)), "duck": True,
                      "duck_to": float(mt["duck_to"])})
    elif mt.get("enabled", True):
        warnings.append("No music selected. Import royalty-cleared music on the Media page to add a music bed.")
    items.extend(recommend_sfx(cuts, words, sfx_library, template, rng, total, warnings))
    # --- fades
    tr = template["transitions"]
    if tr.get("fade_in", 0) > 0:
        items.append({"type": "fade", "direction": "in", "start": 0.0, "duration": float(tr["fade_in"])})
    if tr.get("fade_out", 0) > 0:
        items.append({"type": "fade", "direction": "out", "start": round(total - float(tr["fade_out"]), 3),
                      "duration": float(tr["fade_out"])})
    tl = {"version": 1, "width": 1080, "height": 1920, "fps": 30, "duration": total, "template_id": template["id"],
          "seed": seed, "fit": fit, "caption_style": template["captions"], "title_style": template.get("title", {}),
          "warnings": list(dict.fromkeys(warnings)), "items": items}
    validate_timeline(tl)
    return tl


def recommend_sfx(cuts: list[float], words: list[dict[str, Any]], library: list[dict[str, Any]], template: dict[str, Any],
                  rng: random.Random, total: float, warnings: list[str]) -> list[dict[str, Any]]:
    """Recommend sound effects for timeline events (hook, transitions, emphasis, CTA)."""
    by_cat: dict[str, list[dict[str, Any]]] = {}
    for s in library:
        by_cat.setdefault(s.get("category") or "gameplay", []).append(s)
    st = template["sfx"]
    vol = float(st.get("volume", 0.55))
    out: list[dict[str, Any]] = []
    missing: set[str] = set()

    def place(cat: str, at: float, reason: str) -> None:
        options = by_cat.get(cat)
        if not options:
            missing.add(cat)
            return
        if at < 0 or at > total - 0.1 or any(abs(o["start"] - at) < 0.35 for o in out):
            return
        choice = options[rng.randrange(len(options))]
        out.append({"type": "sfx", "source": choice["path"], "media_id": choice["id"], "category": cat,
                    "reason": reason, "start": round(at, 3), "volume": vol})

    hook_sfx = template["hook"].get("sfx")
    if hook_sfx:
        place(hook_sfx, 0.05, "Hook")
    density = float(st.get("density", 0.5))
    for c in cuts[1:-1]:
        if rng.random() < density:
            place(st.get("transition", "whoosh"), max(0.0, c - 0.12), "Transition")
    emph_cat = st.get("emphasis")
    if emph_cat:
        for w in words:
            if any(ch.isdigit() for ch in str(w.get("word", ""))) and rng.random() < density:
                place(emph_cat, w["start"] + NARRATION_OFFSET, "Emphasis")
    cta_sfx = template["cta"].get("sfx")
    if cta_sfx and template["cta"].get("end_card"):
        place(cta_sfx, max(0.0, total - float(template["cta"].get("seconds", 2.0))), "Call to action")
    if missing:
        warnings.append("No sound effects in categories: " + ", ".join(sorted(missing)) + ". Import some on the Media page.")
    return out


def timeline_hash(tl: dict[str, Any]) -> str:
    import hashlib

    def with_mtime(item: dict[str, Any]) -> dict[str, Any]:
        src = item.get("source")
        if src and Path(src).exists():
            st = Path(src).stat()
            return item | {"_src": [st.st_size, int(st.st_mtime)]}
        return item

    data = dict(tl) | {"items": [with_mtime(i) for i in tl["items"]]}
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:20]
