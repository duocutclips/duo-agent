"""Transcription of narration into word-level timestamps.

Order of preference (first available wins, the method is recorded on the narration):
1. ``whisper-api``   — any Whisper-compatible HTTP endpoint (OpenAI, Groq, self-hosted faster-whisper-server...)
                       configured by WHISPER_API_URL (+ WHISPER_API_KEY).
2. ``faster-whisper`` — local model, if the optional ``faster-whisper`` package is installed.
3. ``tts-alignment`` — exact character timings returned by the TTS provider (ElevenLabs).
4. ``estimated-alignment`` — offline fallback: script words spread over the detected speech regions,
                       weighted by syllables. This is an *estimate*, clearly labelled as such.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

import httpx

from .config import Settings
from .db import Database
from .errors import ConfigurationError, ExternalServiceError
from .ffmpeg import detect_silence
from .logging_setup import get_logger, log_event
from .textutil import count_syllables

log = get_logger("transcription")


def status(settings: Settings) -> dict[str, Any]:
    try:
        import faster_whisper  # noqa: F401

        local = True
    except ImportError:
        local = False
    return {
        "whisper_api": {"configured": bool(settings.whisper_api_url),
                        "message": None if settings.whisper_api_url else "Set WHISPER_API_URL (and WHISPER_API_KEY) for real transcription."},
        "faster_whisper": {"installed": local},
        "fallback": "estimated-alignment (script words spread over detected speech; no API needed)",
    }


def whisper_api(settings: Settings, audio: Path, transport: httpx.BaseTransport | None = None) -> list[dict[str, Any]]:
    if not settings.whisper_api_url:
        raise ConfigurationError("No Whisper endpoint configured.", hint="Set WHISPER_API_URL in .env.")
    headers = {"Authorization": f"Bearer {settings.whisper_api_key}"} if settings.whisper_api_key else {}
    data = {"model": settings.whisper_model, "response_format": "verbose_json", "timestamp_granularities[]": "word"}
    delay = 1.0
    last: Exception | None = None
    for attempt in range(3):
        try:
            with httpx.Client(timeout=max(120.0, settings.http_timeout), transport=transport) as client, audio.open("rb") as f:
                resp = client.post(settings.whisper_api_url, headers=headers, data=data,
                                   files={"file": (audio.name, f, "application/octet-stream")})
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(delay)
                delay *= 2
                continue
            break
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last = exc
            time.sleep(delay)
            delay *= 2
    else:
        raise ExternalServiceError("Could not reach the transcription service.", detail=str(last))
    if resp.status_code == 401:
        raise ConfigurationError("The transcription service rejected the API key.", hint="Check WHISPER_API_KEY.")
    if resp.status_code >= 400:
        raise ExternalServiceError(f"Transcription failed (HTTP {resp.status_code}).", detail=resp.text[:800])
    body = resp.json()
    words = body.get("words")
    if not words:
        for seg in body.get("segments", []):
            words = (words or []) + seg.get("words", [])
    if not words:
        raise ExternalServiceError("The transcription service returned no word timestamps.",
                                   hint="Use an endpoint that supports timestamp_granularities=word.")
    return [{"word": str(w.get("word", "")).strip(), "start": round(float(w["start"]), 3), "end": round(float(w["end"]), 3)}
            for w in words if str(w.get("word", "")).strip()]


def local_whisper(audio: Path) -> list[dict[str, Any]]:
    from faster_whisper import WhisperModel

    model = WhisperModel("base", device="auto", compute_type="int8")
    segments, _ = model.transcribe(str(audio), word_timestamps=True)
    return [{"word": w.word.strip(), "start": round(w.start, 3), "end": round(w.end, 3)}
            for s in segments for w in (s.words or []) if w.word.strip()]


def estimate_alignment(settings: Settings, audio: Path, text: str, duration: float) -> list[dict[str, Any]]:
    words = [w for w in re.findall(r"\S+", text) if re.search(r"[A-Za-z0-9]", w)]
    if not words:
        return []
    silences = detect_silence(settings.ffmpeg, audio, noise_db=-40, min_seconds=0.18, duration=duration)
    speech: list[tuple[float, float]] = []
    t = 0.0
    for s, e in silences:
        if s - t > 0.05:
            speech.append((t, s))
        t = max(t, e)
    if duration - t > 0.05:
        speech.append((t, duration))
    if not speech:
        speech = [(0.0, duration)]
    total_speech = sum(e - s for s, e in speech)
    weights = [count_syllables(w) + 0.6 + (0.5 if w[-1] in ".!?,;:" else 0) for w in words]
    total_w = sum(weights)

    def to_real(x: float) -> tuple[float, int]:
        acc = 0.0
        for i, (s, e) in enumerate(speech):
            if x <= acc + (e - s):
                return s + (x - acc), i
            acc += e - s
        return speech[-1][1], len(speech) - 1

    out = []
    cum = 0.0
    for w, wt in zip(words, weights, strict=False):
        a = cum / total_w * total_speech
        cum += wt
        b = cum / total_w * total_speech
        (start, ra), (end, rb) = to_real(a), to_real(b - 1e-4)
        if ra != rb:
            # A word never spans a pause: keep it in the speech region holding most of it.
            s_a, e_a = speech[ra]
            s_b, _ = speech[rb]
            if e_a - start >= end - s_b:
                end = e_a
            else:
                start = s_b
        if end < start:
            end = start
        out.append({"word": w, "start": round(start, 3), "end": round(max(start + 0.05, end), 3)})
    return out


def transcribe_narration(db: Database, settings: Settings, narration_id: str, *, prefer: str | None = None,
                         transport: httpx.BaseTransport | None = None) -> dict[str, Any]:
    n = db.get("narrations", narration_id)
    script = db.get("scripts", n["script_id"])
    audio = Path(n["audio_path"])
    method, words, note = None, None, None
    order = [prefer] if prefer else ["whisper-api", "faster-whisper", "tts-alignment", "estimated-alignment"]
    for m in order:
        try:
            if m == "whisper-api" and settings.whisper_api_url:
                words, method = whisper_api(settings, audio, transport), m
            elif m == "faster-whisper":
                try:
                    words, method = local_whisper(audio), m
                except ImportError:
                    continue
            elif m == "tts-alignment" and n["words"] and n["alignment_method"] == "tts-alignment":
                words, method = n["words"], m
            elif m == "estimated-alignment":
                words, method = estimate_alignment(settings, audio, script["text"], float(n["duration"])), m
        except (ExternalServiceError, ConfigurationError) as exc:
            note = f"{m} failed: {exc.message}"
            log_event(log, "transcription method failed", level=30, method=m, error=exc.message)
            if prefer:
                raise
            continue
        if words:
            break
    if not words or not method:
        raise ExternalServiceError("No word timestamps could be produced for this narration.", detail=note)
    updated = db.update("narrations", narration_id, {"words": words, "alignment_method": method})
    return updated | {"note": note}
