"""Deterministic FFmpeg renderer: timeline -> 1080x1920 H.264/AAC MP4.

Stage A: every ``video`` item becomes a normalised 1080x1920 / 30 fps / exact-frame-count intermediate
         (fit: crop or blurred-fill, punch-in zooms via ``zoompan``). Intermediates are cached by content hash.
Stage B: intermediates are concatenated, then fades, image overlays and ASS captions/text are applied,
         and narration + music (looped, faded, sidechain-ducked under narration) + SFX are mixed and
         loudness-normalised.

Determinism: fixed frame counts, single-threaded encodes and filtering, ``+bitexact`` flags and stripped metadata.
The same timeline + sources + FFmpeg build produce byte-identical output (checked by a test).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from .captions import build_ass
from .config import REPO_ROOT, Settings
from .errors import RenderError
from .ffmpeg import ffprobe, run_ffmpeg, summarize_probe
from .logging_setup import get_logger, log_event
from .timeline import timeline_hash, validate_timeline

log = get_logger("render")

W, H, FPS = 1080, 1920, 30
QUALITY = {"draft": {"preset": "veryfast", "crf": "24"}, "final": {"preset": "medium", "crf": "19"}}
# x264 with frame threads produced slightly different pixels between identical runs, so every encode is
# single-threaded (bit-exact) and speed comes from rendering clip intermediates in parallel instead.
ENCODER_THREADS = "1"
PARALLEL_SEGMENTS = max(1, min(4, os.cpu_count() or 1))
FONTS_DIR = REPO_ROOT / "assets" / "fonts"
Progress = Callable[[str, float], None]


def _frames(seconds: float) -> int:
    return max(1, int(round(seconds * FPS)))


def zoom_expr(zooms: list[dict[str, Any]]) -> str:
    """zoompan z-expression: sum of trapezoid envelopes (zooms never overlap)."""
    terms = []
    for z in zooms:
        s, d, k = z["start"], z["duration"], z["scale"]
        r = max(0.05, min(z.get("ramp", 0.2), d / 2))
        terms.append(f"{k - 1:.4f}*min(clip((on/{FPS}-{s:.3f})/{r:.3f},0,1),clip(({s + d:.3f}-on/{FPS})/{r:.3f},0,1))")
    return "1+" + "+".join(terms) if terms else "1"


def segment_filter(item: dict[str, Any], src_w: int, src_h: int, zooms: list[dict[str, Any]]) -> str:
    dur = item["end"] - item["start"]
    head = f"[0:v]fps={FPS},setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration={dur + 1:.3f},setsar=1"
    if item.get("fit", "blur") == "crop":
        fx = float(item.get("focus_x", 0.5))
        graph = f"{head},scale={W}:{H}:force_original_aspect_ratio=increase:flags=bicubic,crop={W}:{H}:(iw-{W})*{fx:.3f}:(ih-{H})/2[base]"
    else:
        aspect = src_w / max(1, src_h)
        if aspect > W / H:
            fg_w = int(round(W * 1.3 / 2) * 2)
            fg_h = max(2, int(round(fg_w / aspect / 2) * 2))
            fg = f"scale={fg_w}:{fg_h}:flags=bicubic,crop={W}:{fg_h}"
        else:
            fg = f"scale={W}:{H}:force_original_aspect_ratio=decrease:flags=bicubic,scale=trunc(iw/2)*2:trunc(ih/2)*2"
        graph = (f"{head},split=2[a][b];"
                 f"[a]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,boxblur=12:2,"
                 f"eq=brightness=-0.10:saturation=0.85,scale={W}:{H}:flags=bilinear[bg];"
                 f"[b]{fg}[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2[base]")
    if zooms:
        graph += (f";[base]zoompan=z='{zoom_expr(zooms)}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                  f":d=1:s={W}x{H}:fps={FPS},format=yuv420p[v]")
    else:
        graph += ";[base]format=yuv420p[v]"
    return graph


def _enc(quality: str) -> list[str]:
    q = QUALITY.get(quality, QUALITY["final"])
    return ["-c:v", "libx264", "-preset", q["preset"], "-crf", q["crf"], "-pix_fmt", "yuv420p", "-profile:v", "high",
            "-g", str(FPS * 2), "-threads", ENCODER_THREADS, "-flags:v", "+bitexact"]


def render_segment(settings: Settings, item: dict[str, Any], zooms: list[dict[str, Any]], seg_dir: Path,
                   quality: str, probe_cache: dict[str, dict[str, Any]]) -> Path:
    src = Path(item["source"])
    if not src.is_file():
        raise RenderError(f"Source footage is missing: {src.name}", hint="Re-import or restore the file, then render again.")
    if str(src) not in probe_cache:
        probe_cache[str(src)] = summarize_probe(ffprobe(settings.ffprobe, src))
    info = probe_cache[str(src)]
    dur = item["end"] - item["start"]
    local_zooms = [{**z, "start": round(z["start"] - item["start"], 3)} for z in zooms
                   if item["start"] <= z["start"] < item["end"]]
    graph = segment_filter(item, int(info["width"] or W), int(info["height"] or H), local_zooms)
    st = src.stat()
    key = hashlib.sha256(json.dumps([str(src), st.st_size, int(st.st_mtime), item["src_in"], dur, graph, quality],
                                    sort_keys=True).encode()).hexdigest()[:24]
    out = seg_dir / f"{key}.mp4"
    if out.is_file() and out.stat().st_size > 0:
        return out
    tmp = seg_dir / f"{key}.{uuid.uuid4().hex[:8]}.tmp.mp4"  # unique: identical clips may render concurrently
    run_ffmpeg(settings.ffmpeg, [
        "-y", "-ss", f"{item['src_in']:.3f}", "-t", f"{dur + 0.5:.3f}", "-i", str(src),
        "-filter_complex", graph, "-map", "[v]", "-an", "-frames:v", str(_frames(dur)), "-r", str(FPS),
        *_enc(quality), "-map_metadata", "-1", "-fflags", "+bitexact", str(tmp),
    ], timeout=settings.ffmpeg_timeout, what=f"Rendering clip {src.name} @ {item['src_in']:.1f}s")
    tmp.replace(out)
    return out


def _audio_chain(label_in: str, extra: str, label_out: str) -> str:
    return f"[{label_in}]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo{(',' + extra) if extra else ''}[{label_out}]"


def final_graph(tl: dict[str, Any], inputs: dict[str, Any]) -> tuple[str, list[str]]:
    """Build the stage-B filter graph. Returns (graph, warnings)."""
    T = tl["duration"]
    parts: list[str] = []
    v = "0:v"
    fades = [i for i in tl["items"] if i["type"] == "fade"]
    fade_f = []
    for f in fades:
        fade_f.append(f"fade=t={f['direction']}:st={f['start']:.3f}:d={f['duration']:.3f}")
    parts.append(f"[{v}]setsar=1{(',' + ','.join(fade_f)) if fade_f else ''}[v0]")
    cur = "v0"
    for n, (idx, img) in enumerate(inputs["images"]):
        fade = float(img.get("fade", 0))
        parts.append(f"[{idx}:v]scale={int(img['width'])}:-2,format=rgba"
                     + (f",fade=t=in:st=0:d={fade:.3f}:alpha=1" if fade else "") + f"[img{n}]")
        parts.append(f"[{cur}][img{n}]overlay=x={int(img['x'])}:y={int(img['y'])}:eof_action=repeat:"
                     f"enable='between(t,{img['start']:.3f},{img['end']:.3f})'[vi{n}]")
        cur = f"vi{n}"
    if inputs["has_text"]:
        parts.append(f"[{cur}]ass=captions.ass:fontsdir=fonts[vc]")
        cur = "vc"
    parts.append(f"[{cur}]format=yuv420p[vout]")
    # audio
    mix: list[str] = []
    narr = inputs.get("narration")
    music = inputs.get("music")
    if narr:
        idx, item = narr
        ms = int(round(item["start"] * 1000))
        vol = float(item.get("volume", 1.0))
        split = ",asplit=2[narr][sc]" if music and music[1].get("duck") else "[narr]"
        parts.append(f"[{idx}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,adelay={ms}|{ms},"
                     f"volume={vol:.3f},apad,atrim=0:{T:.3f}{split}")
        mix.append("narr")
    else:
        parts.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{T:.3f}[narr]")
        mix.append("narr")
    if music:
        idx, m = music
        fi, fo = float(m.get("fade_in", 0.5)), float(m.get("fade_out", 1.0))
        chain = (f"atrim=0:{T:.3f},asetpts=PTS-STARTPTS,volume={float(m.get('volume', 0.2)):.3f},"
                 f"afade=t=in:st=0:d={fi:.3f},afade=t=out:st={max(0.0, T - fo):.3f}:d={fo:.3f}")
        parts.append(_audio_chain(f"{idx}:a", chain, "mus0"))
        if m.get("duck") and narr:
            ratio = max(2.0, min(20.0, 1.0 / max(0.05, float(m.get("duck_to", 0.25)))))
            parts.append(f"[mus0][sc]sidechaincompress=threshold=0.02:ratio={ratio:.2f}:attack=20:release=400[mus]")
        else:
            parts.append("[mus0]anull[mus]")
        mix.append("mus")
    for n, (idx, s) in enumerate(inputs["sfx"]):
        ms = int(round(s["start"] * 1000))
        parts.append(_audio_chain(f"{idx}:a", f"adelay={ms}|{ms},volume={float(s.get('volume', 0.6)):.3f}", f"sfx{n}"))
        mix.append(f"sfx{n}")
    labels = "".join(f"[{m}]" for m in mix)
    parts.append(f"{labels}amix=inputs={len(mix)}:duration=first:dropout_transition=0:normalize=0,"
                 f"loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000,atrim=0:{T:.3f}[aout]")
    return ";".join(parts), []


def render_timeline(settings: Settings, tl: dict[str, Any], out_dir: Path, *, quality: str = "final",
                    progress: Progress | None = None) -> dict[str, Any]:
    validate_timeline(tl)
    if quality not in QUALITY:
        raise RenderError(f"Unknown quality '{quality}'.")
    started = time.monotonic()
    out_dir.mkdir(parents=True, exist_ok=True)
    seg_dir = out_dir / "segments"
    seg_dir.mkdir(exist_ok=True)
    thash = timeline_hash(tl)
    final = out_dir / f"render-{thash}-{quality}.mp4"
    report = out_dir / f"render-{thash}-{quality}.json"
    if final.is_file() and report.is_file():
        info = json.loads(report.read_text(encoding="utf-8"))
        if info.get("ok"):
            return info | {"cached": True}
    videos = sorted((i for i in tl["items"] if i["type"] == "video"), key=lambda i: i["start"])
    zooms = [i for i in tl["items"] if i["type"] == "zoom"]
    probe_cache: dict[str, dict[str, Any]] = {}
    for item in videos:  # probe sequentially so the parallel workers only read the cache
        src = Path(item["source"])
        if src.is_file() and str(src) not in probe_cache:
            probe_cache[str(src)] = summarize_probe(ffprobe(settings.ffprobe, src))
    done = 0
    if progress:
        progress(f"Rendering {len(videos)} clips", 0.0)
    with ThreadPoolExecutor(max_workers=PARALLEL_SEGMENTS) as pool:
        futures = [pool.submit(render_segment, settings, item, zooms, seg_dir, quality, probe_cache) for item in videos]
        for fut in as_completed(futures):
            fut.result()  # surface the first error
            done += 1
            if progress:
                progress(f"Rendered clip {done}/{len(videos)}", done / (len(videos) + 1))
        seg_files = [f.result() for f in futures]
    work = out_dir / "work"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir()
    (work / "concat.txt").write_text("".join(f"file '../segments/{p.name}'\n" for p in seg_files), encoding="utf-8")
    shutil.copytree(FONTS_DIR, work / "fonts")
    text_items = [i for i in tl["items"] if i["type"] in ("caption", "text")]
    (work / "captions.ass").write_text(build_ass(text_items, tl.get("caption_style", {}), tl.get("title_style", {})),
                                       encoding="utf-8")
    args: list[str] = ["-y", "-f", "concat", "-safe", "0", "-i", "concat.txt"]
    inputs: dict[str, Any] = {"images": [], "sfx": [], "has_text": bool(text_items)}
    idx = 1
    for item in tl["items"]:
        if item["type"] in ("narration", "music", "sfx", "image"):
            src = Path(item["source"])
            if not src.is_file():
                raise RenderError(f"{item['type'].capitalize()} file is missing: {src.name}")
            if item["type"] == "music" and item.get("loop", True):
                args += ["-stream_loop", "-1"]
            args += ["-i", str(src)]
            if item["type"] == "narration":
                inputs["narration"] = (idx, item)
            elif item["type"] == "music":
                inputs["music"] = (idx, item)
            elif item["type"] == "sfx":
                inputs["sfx"].append((idx, item))
            else:
                inputs["images"].append((idx, item))
            idx += 1
    graph, _ = final_graph(tl, inputs)
    (work / "filter_graph.txt").write_text(graph, encoding="utf-8")
    tmp = work / "final.mp4"
    if progress:
        progress("Compositing captions, audio and effects", len(videos) / (len(videos) + 1))
    res = run_ffmpeg(settings.ffmpeg, [
        *args, "-filter_complex_threads", "1", "-filter_complex", graph, "-map", "[vout]", "-map", "[aout]",
        *_enc(quality), "-r", str(FPS), "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-flags:a", "+bitexact",
        "-t", f"{tl['duration']:.3f}", "-movflags", "+faststart", "-map_metadata", "-1", "-fflags", "+bitexact", str(tmp.name),
    ], timeout=settings.ffmpeg_timeout, what="Final composition", cwd=work)
    tmp.replace(final)
    info = {
        "ok": True, "path": str(final), "timeline_hash": thash, "quality": quality,
        "seconds": round(time.monotonic() - started, 2), "segments": len(seg_files),
        "ffmpeg_warnings": [ln for ln in res.stderr.splitlines() if "warning" in ln.lower()][-10:],
    }
    report.write_text(json.dumps(info, indent=2), encoding="utf-8")
    shutil.rmtree(work, ignore_errors=True)
    log_event(log, "render complete", path=str(final), seconds=info["seconds"], quality=quality)
    if progress:
        progress("Done", 1.0)
    return info | {"cached": False}
