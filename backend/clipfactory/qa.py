"""Automated quality control for rendered videos."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from .config import Settings
from .errors import MediaError
from .ffmpeg import detect_black, detect_silence, ffprobe, summarize_probe
from .textutil import contains_phrase

DEFAULTS = {"max_silence_seconds": 1.5, "silence_db": -50.0, "duration_tolerance": 0.25, "black_min_seconds": 0.1}


def _check(name: str, ok: bool | None, detail: str) -> dict[str, Any]:
    return {"name": name, "status": "N/A" if ok is None else ("PASS" if ok else "FAIL"), "detail": detail}


def run_qa(settings: Settings, video: Path, timeline: dict[str, Any], *, script_text: str = "",
           rules: dict[str, Any] | None = None, render_ok: bool = True, options: dict[str, Any] | None = None) -> dict[str, Any]:
    opt = {**DEFAULTS, **(options or {})}
    checks: list[dict[str, Any]] = []
    exists = video.is_file() and video.stat().st_size > 1000
    checks.append(_check("File exists", exists, str(video) if exists else "Output file is missing or empty."))
    checks.append(_check("FFmpeg completed", render_ok, "Render finished with exit code 0." if render_ok else "Render failed."))
    if not exists:
        return _finish(checks)
    try:
        info = summarize_probe(ffprobe(settings.ffprobe, video))
    except MediaError as exc:
        checks.append(_check("Encoding", False, f"ffprobe could not read the file: {exc.message}"))
        return _finish(checks)
    # corruption: full decode must produce no errors
    proc = subprocess.run([settings.ffmpeg, "-v", "error", "-nostdin", "-i", str(video), "-f", "null", "-"],
                          capture_output=True, timeout=600)
    decode_err = proc.stderr.decode(errors="replace").strip()
    checks.append(_check("No corruption (full decode)", proc.returncode == 0 and not decode_err,
                         "Decoded every frame without errors." if not decode_err else decode_err[:300]))
    w, h = info["width"], info["height"]
    checks.append(_check("Resolution", (w, h) == (1080, 1920), f"{w}x{h} (expected 1080x1920)"))
    checks.append(_check("Aspect ratio", bool(w and h and abs(w / h - 9 / 16) < 0.001), f"{w}:{h} = 9:16" if w and h else "unknown"))
    enc_ok = info["codec"] == "h264" and info["audio_codec"] == "aac" and info["pix_fmt"] == "yuv420p"
    checks.append(_check("Encoding", enc_ok, f"video {info['codec']} ({info['pix_fmt']}), audio {info['audio_codec']}, "
                                             f"{info['fps']} fps"))
    dur = float(info["duration"] or 0)
    expected = float(timeline["duration"])
    dur_ok = dur > 0 and abs(dur - expected) <= opt["duration_tolerance"]
    detail = f"{dur:.2f}s (timeline {expected:.2f}s)"
    if rules and rules.get("max_seconds") and dur > rules["max_seconds"] + 0.5:
        dur_ok, detail = False, detail + f"; campaign maximum is {rules['max_seconds']}s"
    if rules and rules.get("min_seconds") and dur < rules["min_seconds"] - 0.5:
        dur_ok, detail = False, detail + f"; campaign minimum is {rules['min_seconds']}s"
    checks.append(_check("Duration", dur_ok, detail))
    checks.append(_check("Audio", bool(info["has_audio"]), "Audio stream present." if info["has_audio"] else "No audio stream."))
    narr = [i for i in timeline["items"] if i["type"] == "narration"]
    narr_ok = bool(narr) and all(Path(n["source"]).is_file() for n in narr)
    checks.append(_check("Narration", narr_ok, "Narration track rendered." if narr_ok else "Timeline has no narration."))
    if info["has_audio"]:
        silences = detect_silence(settings.ffmpeg, video, noise_db=opt["silence_db"], min_seconds=opt["max_silence_seconds"],
                                  duration=dur)
        checks.append(_check(f"No silence > {opt['max_silence_seconds']}s", not silences,
                             "None found." if not silences else ", ".join(f"{s:.1f}–{e:.1f}s" for s, e in silences)))
    caps = [i for i in timeline["items"] if i["type"] == "caption"]
    narr_end = max((n["start"] for n in narr), default=0) + 0.5
    cover = caps and caps[0]["start"] <= narr_end + 1.5
    checks.append(_check("Captions", bool(caps) and bool(cover),
                         f"{len(caps)} caption phrases on the timeline." if caps else "No captions on the timeline."))
    blacks = detect_black(settings.ffmpeg, video, min_seconds=opt["black_min_seconds"])
    # a fade-in/out may legitimately start or end on black; ignore spans inside the fade windows
    fades = [(f["start"], f["start"] + f["duration"]) for f in timeline["items"] if f["type"] == "fade"]
    real_blacks = [(s, e) for s, e in blacks if not any(s >= fs - 0.05 and e <= fe + 0.1 for fs, fe in fades)]
    checks.append(_check("No accidental black frames", not real_blacks,
                         "None found." if not real_blacks else ", ".join(f"{s:.2f}–{e:.2f}s" for s, e in real_blacks)))
    if rules is not None:
        problems = []
        for phrase in rules.get("required_phrases", []):
            if phrase.startswith("#"):
                continue
            if not contains_phrase(script_text, phrase):
                problems.append(f"missing “{phrase}”")
        for term in rules.get("banned_terms", []):
            if contains_phrase(script_text, term):
                problems.append(f"contains restricted “{term}”")
        n_rules = len([p for p in rules.get("required_phrases", []) if not p.startswith("#")]) + len(rules.get("banned_terms", []))
        if n_rules == 0 and not rules.get("max_seconds") and not rules.get("min_seconds"):
            checks.append(_check("Campaign requirements", None, "No confirmed, machine-checkable requirements (analyse the campaign)."))
        else:
            checks.append(_check("Campaign requirements", not problems,
                                 "Required wording present; no restricted terms; duration within limits."
                                 if not problems else "; ".join(problems)))
            checks.append(_check("Required phrases", not any(p.startswith("missing") for p in problems),
                                 ", ".join(p for p in rules.get("required_phrases", []) if not p.startswith("#")) or "none"))
    return _finish(checks, info)


def _finish(checks: list[dict[str, Any]], info: dict[str, Any] | None = None) -> dict[str, Any]:
    failed = [c for c in checks if c["status"] == "FAIL"]
    return {"overall": "READY" if not failed else "NOT READY", "checks": checks, "failed": [c["name"] for c in failed],
            "probe": info}


def format_report(qa: dict[str, Any]) -> str:
    lines = ["VIDEO QA", ""]
    lines += [f"{c['name']}: {c['status']}" for c in qa["checks"]]
    lines += ["", "Overall:", qa["overall"]]
    return "\n".join(lines)
