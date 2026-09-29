"""FFmpeg / ffprobe process helpers with timeouts and meaningful errors."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import ConfigurationError, MediaError, RenderError
from .logging_setup import get_logger, log_event

log = get_logger("ffmpeg")


@dataclass
class FFmpegResult:
    args: list[str]
    returncode: int
    stderr: str
    stdout: bytes
    seconds: float


def check_binaries(ffmpeg: str, ffprobe: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, binary in (("ffmpeg", ffmpeg), ("ffprobe", ffprobe)):
        path = shutil.which(binary) or (binary if Path(binary).is_file() else None)
        if not path:
            out[name] = {"available": False, "path": binary}
            continue
        try:
            first = subprocess.run([path, "-version"], capture_output=True, text=True, timeout=20).stdout.splitlines()[0]
        except Exception as exc:  # pragma: no cover - only on broken installs
            out[name] = {"available": False, "path": path, "error": str(exc)}
            continue
        out[name] = {"available": True, "path": path, "version": first}
    return out


def _require(binary: str, name: str) -> str:
    path = shutil.which(binary) or (binary if Path(binary).is_file() else None)
    if not path:
        raise ConfigurationError(
            f"{name} was not found.",
            hint=f"Install FFmpeg and make sure `{name}` is on PATH, or set {name.upper()}_PATH in .env.",
        )
    return path


def run_ffmpeg(ffmpeg: str, args: list[str], *, timeout: float = 900, capture_stdout: bool = False,
               what: str = "FFmpeg command", error_cls: type = RenderError, cwd: Path | None = None) -> FFmpegResult:
    binary = _require(ffmpeg, "ffmpeg")
    full = [binary, "-hide_banner", "-nostdin", *args]
    started = time.monotonic()
    try:
        proc = subprocess.run(full, capture_output=True, timeout=timeout, cwd=str(cwd) if cwd else None)
    except subprocess.TimeoutExpired as exc:
        log_event(log, "ffmpeg timeout", level=40, what=what, timeout=timeout)
        raise error_cls(f"{what} took longer than {int(timeout)} seconds and was stopped.",
                        detail=" ".join(full)[:2000]) from exc
    elapsed = time.monotonic() - started
    stderr = proc.stderr.decode("utf-8", errors="replace")
    if proc.returncode != 0:
        tail = "\n".join(stderr.strip().splitlines()[-25:])
        log_event(log, "ffmpeg failed", level=40, what=what, returncode=proc.returncode, stderr_tail=tail)
        raise error_cls(f"{what} failed (FFmpeg exit code {proc.returncode}).", detail=tail)
    log_event(log, "ffmpeg ok", what=what, seconds=round(elapsed, 2))
    return FFmpegResult(full, proc.returncode, stderr, proc.stdout if capture_stdout else b"", elapsed)


def ffprobe(ffprobe_bin: str, path: Path, timeout: float = 60) -> dict[str, Any]:
    binary = _require(ffprobe_bin, "ffprobe")
    try:
        proc = subprocess.run(
            [binary, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
            capture_output=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise MediaError(f"Reading media information for {path.name} timed out.") from exc
    if proc.returncode != 0:
        raise MediaError(
            f"{path.name} could not be read as media. The file may be corrupt or in an unsupported format.",
            detail=proc.stderr.decode("utf-8", errors="replace")[-1500:],
        )
    data: dict[str, Any] = json.loads(proc.stdout.decode("utf-8", errors="replace") or "{}")
    return data


def _fps(rate: str | None) -> float | None:
    if not rate or rate in ("0/0", "0"):
        return None
    if "/" in rate:
        num, den = rate.split("/", 1)
        try:
            return round(float(num) / float(den), 3) if float(den) else None
        except ValueError:
            return None
    try:
        return float(rate)
    except ValueError:
        return None


def summarize_probe(data: dict[str, Any]) -> dict[str, Any]:
    """Reduce ffprobe output to the metadata the app stores."""
    streams = data.get("streams", [])
    fmt = data.get("format", {})
    video = next((s for s in streams if s.get("codec_type") == "video"
                  and not s.get("disposition", {}).get("attached_pic")), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    duration = None
    for candidate in (fmt.get("duration"), (video or {}).get("duration"), (audio or {}).get("duration")):
        try:
            if candidate is not None:
                duration = round(float(candidate), 3)
                break
        except (TypeError, ValueError):
            continue
    width = height = None
    if video:
        width, height = video.get("width"), video.get("height")
        rotation = 0
        for sd in video.get("side_data_list", []) or []:
            if "rotation" in sd:
                rotation = int(sd["rotation"])
        rotation = int(video.get("tags", {}).get("rotate", rotation) or rotation)
        if abs(rotation) in (90, 270) and width and height:
            width, height = height, width
    orientation = None
    if width and height:
        orientation = "portrait" if height > width else "landscape" if width > height else "square"
    return {
        "duration": duration,
        "width": width,
        "height": height,
        "fps": _fps((video or {}).get("avg_frame_rate")) or _fps((video or {}).get("r_frame_rate")),
        "codec": (video or {}).get("codec_name"),
        "audio_codec": (audio or {}).get("codec_name"),
        "has_audio": audio is not None,
        "orientation": orientation,
        "format_name": fmt.get("format_name"),
        "bit_rate": int(fmt["bit_rate"]) if str(fmt.get("bit_rate", "")).isdigit() else None,
        "audio_sample_rate": int(audio["sample_rate"]) if audio and str(audio.get("sample_rate", "")).isdigit() else None,
        "pix_fmt": (video or {}).get("pix_fmt"),
    }


_SILENCE_START = re.compile(r"silence_start:\s*(-?[\d.]+)")
_SILENCE_END = re.compile(r"silence_end:\s*([\d.]+)\s*\|\s*silence_duration:\s*([\d.]+)")
_BLACK = re.compile(r"black_start:([\d.]+)\s+black_end:([\d.]+)\s+black_duration:([\d.]+)")


def detect_silence(ffmpeg: str, path: Path, *, noise_db: float = -45, min_seconds: float = 0.5,
                   duration: float | None = None, timeout: float = 300) -> list[tuple[float, float]]:
    """Silent spans as (start, end). ``duration`` closes a span that runs to the end of the file."""
    res = run_ffmpeg(ffmpeg, ["-i", str(path), "-vn", "-af", f"silencedetect=noise={noise_db}dB:d={min_seconds}",
                              "-f", "null", "-"], timeout=timeout, what="Silence detection", error_cls=MediaError)
    spans: list[tuple[float, float]] = []
    start: float | None = None
    for line in res.stderr.splitlines():
        m = _SILENCE_START.search(line)
        if m:
            start = max(0.0, float(m.group(1)))
            continue
        m = _SILENCE_END.search(line)
        if m and start is not None:
            spans.append((round(start, 3), round(float(m.group(1)), 3)))
            start = None
    if start is not None:
        spans.append((round(start, 3), round(float(duration if duration is not None else start), 3)))
    return spans


def detect_black(ffmpeg: str, path: Path, *, min_seconds: float = 0.25, pix_th: float = 0.10,
                 timeout: float = 300) -> list[tuple[float, float]]:
    res = run_ffmpeg(ffmpeg, ["-i", str(path), "-an", "-vf", f"blackdetect=d={min_seconds}:pix_th={pix_th}",
                              "-f", "null", "-"], timeout=timeout, what="Black-frame detection", error_cls=MediaError)
    return [(float(m.group(1)), float(m.group(2))) for m in _BLACK.finditer(res.stderr)]
