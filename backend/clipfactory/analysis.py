"""Gameplay analysis from low-level signals.

What it measures (and all it claims to measure):
* motion / action intensity — mean absolute luma difference between frames sampled at 4 fps
* scene changes — frame differences far above the clip's typical difference
* brightness / black sections and static (frozen) sections
* audio loudness, silence and loud peaks (possible reactions, impacts, dialogue)
* repeated sections — near-identical one-second visual signatures far apart in time

It does NOT recognise objects, items or text. Segment labels describe signals
("High action", "Loud audio peak"), never semantic content ("rare item visible").
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import numpy as np

from .config import Settings
from .db import Database
from .errors import MediaError
from .logging_setup import get_logger, log_event

log = get_logger("analysis")

SAMPLE_FPS = 4
AUDIO_RATE = 8000
WINDOW = 0.25  # seconds per audio window


def _read_frames(settings: Settings, path: Path, width: int, height: int, timeout: float) -> np.ndarray:
    w = 96
    h = max(2, int(round(w * height / max(1, width) / 2)) * 2)
    cmd = [settings.ffmpeg, "-hide_banner", "-nostdin", "-v", "error", "-i", str(path), "-an",
           "-vf", f"fps={SAMPLE_FPS},scale={w}:{h}:flags=area,format=gray", "-f", "rawvideo", "-"]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise MediaError("Frame sampling timed out.") from exc
    if proc.returncode != 0:
        raise MediaError("Could not decode video frames for analysis.", detail=proc.stderr.decode(errors="replace")[-800:])
    buf = np.frombuffer(proc.stdout, dtype=np.uint8)
    n = buf.size // (w * h)
    return buf[: n * w * h].reshape(n, h, w).astype(np.float32)


def _read_audio(settings: Settings, path: Path, timeout: float) -> np.ndarray:
    cmd = [settings.ffmpeg, "-hide_banner", "-nostdin", "-v", "error", "-i", str(path), "-vn", "-ac", "1",
           "-ar", str(AUDIO_RATE), "-f", "s16le", "-"]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise MediaError("Audio sampling timed out.") from exc
    if proc.returncode != 0:
        return np.zeros(0, dtype=np.float32)
    return np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def _spans(mask: np.ndarray, step: float, min_len: float) -> list[tuple[float, float]]:
    spans: list[tuple[float, float]] = []
    start = None
    for i, v in enumerate(list(mask) + [False]):
        if v and start is None:
            start = i
        elif not v and start is not None:
            if (i - start) * step >= min_len:
                spans.append((round(start * step, 2), round(i * step, 2)))
            start = None
    return spans


def signals(settings: Settings, path: Path, width: int, height: int, duration: float, has_audio: bool) -> dict[str, Any]:
    timeout = max(120.0, duration * 4)
    frames = _read_frames(settings, path, width, height, timeout)
    if len(frames) < 2:
        raise MediaError("The video is too short to analyse (needs at least half a second).")
    diffs = np.abs(np.diff(frames, axis=0)).mean(axis=(1, 2))  # len n-1, diff[i] between frame i and i+1
    motion = np.concatenate([[diffs[0]], diffs])
    brightness = frames.mean(axis=(1, 2))
    med = float(np.median(diffs)) if diffs.size else 0.0
    # Scene changes: luma-histogram distance (robust for dark/noisy footage) or a pixel-difference spike.
    hists = np.stack([np.histogram(fr, bins=32, range=(0, 256))[0] for fr in frames]).astype(np.float32)
    hists /= np.maximum(1.0, hists.sum(axis=1, keepdims=True))
    hdiff = np.abs(np.diff(hists, axis=0)).sum(axis=1)  # 0..2
    cut_thr = max(30.0, med * 4.0)
    cuts: list[float] = []
    for i in range(len(diffs)):
        if hdiff[i] > 0.5 or diffs[i] > cut_thr:
            t = round((i + 1) / SAMPLE_FPS, 2)
            if not cuts or t - cuts[-1] >= 0.5:
                cuts.append(t)
    step = 1.0 / SAMPLE_FPS
    black = _spans(brightness < 14, step, 0.5)
    static = _spans(motion < 0.6, step, 2.0)

    # Repeated sections: one-second sequences of 16x16 thumbnails that match an earlier second far more
    # closely than that earlier second matches its own neighbours (so uniform footage is not a "repeat").
    per_sec = SAMPLE_FPS
    h, w = frames.shape[1:]
    hh, ww = h - h % 16, w - w % 16
    thumbs = frames[:, :hh, :ww].reshape(len(frames), 16, hh // 16, 16, ww // 16).mean(axis=(2, 4))
    n_sec = len(frames) // per_sec
    secs = thumbs[: n_sec * per_sec].reshape(n_sec, per_sec, 16, 16)

    def dist(a: int, b: int) -> float:
        return float(np.abs(secs[a] - secs[b]).mean())

    repeats: list[tuple[int, int]] = []
    for j in range(n_sec):
        if motion[j * per_sec:(j + 1) * per_sec].mean() < 1.0 or brightness[j * per_sec] < 14:
            continue  # static/black seconds trivially match each other
        for i in range(0, j - 3):
            d = dist(i, j)
            neighbour = min(dist(i, k) for k in (i - 1, i + 1) if 0 <= k < n_sec and k != j)
            if d < 3.0 and d < 0.35 * neighbour:
                repeats.append((i, j))
                break
    repeat_spans: list[dict[str, float]] = []
    for i, j in repeats:
        last = repeat_spans[-1] if repeat_spans else None
        if last and j == last["repeat_end"] and i == last["first_end"]:
            last["repeat_end"] = j + 1
            last["first_end"] = i + 1
        else:
            repeat_spans.append({"first_start": i, "first_end": i + 1, "repeat_start": j, "repeat_end": j + 1})
    repeat_spans = [r for r in repeat_spans if r["repeat_end"] - r["repeat_start"] >= 2]

    audio_db = np.full(int(np.ceil(duration / WINDOW)), -90.0)
    if has_audio:
        pcm = _read_audio(settings, path, timeout)
        win = int(AUDIO_RATE * WINDOW)
        n = min(len(audio_db), pcm.size // win)
        if n:
            rms = np.sqrt((pcm[: n * win].reshape(n, win) ** 2).mean(axis=1))
            audio_db[:n] = 20 * np.log10(np.maximum(rms, 1e-5))
    silence = _spans(audio_db < -45, WINDOW, 1.0)
    loud_thr = max(-24.0, float(np.percentile(audio_db, 90))) if audio_db.size else 0
    peaks = [round(i * WINDOW, 2) for i in range(1, len(audio_db) - 1)
             if audio_db[i] >= loud_thr and audio_db[i] >= audio_db[i - 1] and audio_db[i] >= audio_db[i + 1]
             and audio_db[i] > float(np.median(audio_db)) + 6
             and audio_db[i] - audio_db[max(0, i - 2)] >= 10]  # sharp onset within 0.5 s, not a slow swell
    return {
        "sample_fps": SAMPLE_FPS, "motion": [round(float(v), 2) for v in motion],
        "brightness": [round(float(v), 1) for v in brightness], "audio_window": WINDOW,
        "audio_db": [round(float(v), 1) for v in audio_db], "cuts": cuts, "black": black, "static": static,
        "silence": silence, "audio_peaks": peaks, "repeats": repeat_spans, "motion_median": round(med, 2),
    }


def _overlap(a: tuple[float, float], spans: list[tuple[float, float]]) -> float:
    return sum(max(0.0, min(a[1], e) - max(a[0], s)) for s, e in spans)


def candidate_segments(sig: dict[str, Any], duration: float, *, min_len: float = 1.5, max_len: float = 4.0) -> list[dict[str, Any]]:
    """Split the clip at scene cuts into windows and score each by signal strength."""
    motion = np.array(sig["motion"])
    audio = np.array(sig["audio_db"])
    boundaries = [0.0, *[c for c in sig["cuts"] if 0.3 < c < duration - 0.3], duration]
    windows: list[tuple[float, float]] = []
    for s, e in zip(boundaries, boundaries[1:], strict=False):
        t = s
        while e - t >= min_len:
            length = min(max_len, e - t)
            if e - (t + length) < min_len:
                length = e - t if e - t <= max_len * 1.5 else length
            windows.append((round(t, 2), round(min(e, t + length), 2)))
            t += length
    med_motion = max(0.5, float(np.median(motion)))
    med_audio = float(np.median(audio)) if audio.size else -90
    bad = [(s, e) for s, e in sig["black"]] + [(s, e) for s, e in sig["static"]]
    repeat_spans = [(r["repeat_start"], r["repeat_end"]) for r in sig["repeats"]]
    segs: list[dict[str, Any]] = []
    for s, e in windows:
        fi, fe = int(s * SAMPLE_FPS), max(int(s * SAMPLE_FPS) + 1, int(e * SAMPLE_FPS))
        ai, ae = int(s / WINDOW), max(int(s / WINDOW) + 1, int(e / WINDOW))
        m = float(motion[fi:fe].mean()) if fe <= len(motion) else float(motion[fi:].mean() if fi < len(motion) else 0)
        a = float(audio[ai:ae].max()) if ai < len(audio) else -90.0
        cuts_in = sum(1 for c in sig["cuts"] if s < c < e)
        peaks_in = sum(1 for p in sig["audio_peaks"] if s <= p < e)
        motion_ratio = m / med_motion
        bad_frac = _overlap((s, e), bad) / (e - s)
        rep_frac = _overlap((s, e), repeat_spans) / (e - s)
        score = (0.55 * min(1.0, motion_ratio / 2.5) + 0.25 * min(1.0, max(0.0, (a - med_audio) / 18))
                 + 0.1 * min(1.0, cuts_in / 2) + 0.1 * min(1.0, peaks_in / 2))
        score *= (1 - bad_frac) * (1 - 0.6 * rep_frac)
        tags: list[str] = []
        if bad_frac > 0.5:
            label, kind = "Static or black (avoid)", "static"
        elif motion_ratio >= 1.6:
            label, kind = "High action", "action"
            tags.append("action")
        elif peaks_in and a - med_audio > 8:
            label, kind = "Sharp loud sound (possible impact/reaction)", "audio_peak"
            tags.append("audio")
        elif motion_ratio < 0.7:
            label, kind = "Calm footage (B-roll)", "broll"
            tags.append("broll")
        else:
            label, kind = "Moderate activity", "moderate"
        if rep_frac > 0.5:
            tags.append("repeated")
            label += " — repeats earlier footage"
        basis = f"motion {motion_ratio:.1f}× clip median, peak audio {a:.0f} dB, {cuts_in} scene change(s)"
        conf = 0.5 + 0.45 * min(1.0, abs(motion_ratio - 1) / 1.5) if kind in ("action", "broll", "moderate") else \
            0.5 + 0.45 * min(1.0, (a - med_audio) / 20) if kind == "audio_peak" else 0.9
        segs.append({"start": s, "end": e, "label": label, "kind": kind, "score": round(score, 3),
                     "confidence": round(min(0.99, conf), 2), "tags": tags, "basis": basis})
    ranked = sorted([x for x in segs if x["kind"] != "static"], key=lambda x: -x["score"])
    for x in ranked[:3]:
        if x["score"] >= 0.35:
            x["tags"].append("hook_candidate")
    return segs


def analyze_media(db: Database, settings: Settings, media_id: str) -> dict[str, Any]:
    m = db.get("media", media_id)
    if m["kind"] != "video":
        raise MediaError("Only video files can be analysed for gameplay moments.")
    path = Path(m["path"])
    if not path.is_file():
        raise MediaError(f"Source file is missing: {path}", hint="Re-import the file or restore it to its original location.")
    sig = signals(settings, path, m["width"] or 16, m["height"] or 9, float(m["duration"] or 0), bool(m["has_audio"]))
    segs = candidate_segments(sig, float(m["duration"] or 0))
    with db._lock:
        db.conn.execute("DELETE FROM segments WHERE media_id = ? AND source = 'auto'", (media_id,))
        db.conn.commit()
    for s in segs:
        db.insert("segments", {"media_id": media_id, "start": s["start"], "end": s["end"], "label": s["label"],
                               "kind": s["kind"], "score": s["score"], "confidence": s["confidence"],
                               "tags": [*s["tags"], f"basis:{s['basis']}"], "source": "auto",
                               "enabled": s["kind"] != "static"})
    summary = {k: sig[k] for k in ("cuts", "black", "static", "silence", "audio_peaks", "repeats", "motion_median")}
    # keep downsampled curves for the UI (2 values / second)
    summary["motion_curve"] = sig["motion"][:: SAMPLE_FPS // 2]
    summary["audio_curve"] = sig["audio_db"][:: int(0.5 / WINDOW)]
    db.update("media", media_id, {"analysis": summary})
    log_event(log, "media analysed", media_id=media_id, segments=len(segs), cuts=len(sig["cuts"]))
    return {"media": db.get("media", media_id), "segments": list_segments(db, media_id)}


def list_segments(db: Database, media_id: str) -> list[dict[str, Any]]:
    return db.list("segments", "media_id = ?", [media_id], order="start")


def format_ts(t: float) -> str:
    return f"{int(t // 60):02d}:{t % 60:05.2f}"
