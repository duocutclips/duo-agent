"""AI voice (text-to-speech) with a content-addressed cache.

Providers:
* ``elevenlabs`` — ElevenLabs API (needs ELEVENLABS_API_KEY). Uses the ``with-timestamps`` endpoint so
  character alignment comes back with the audio.
* ``system`` — offline OS voice: espeak-ng on Linux, ``say`` on macOS, SAPI (System.Speech) on Windows.
  Intended for drafts and the offline demo.

Identical requests (provider, voice, model, settings, text, format) are served from the cache and never
regenerated. Voices marked as cloned/custom must be confirmed as authorised before use.
"""

from __future__ import annotations

import base64
import hashlib
import json
import platform
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx

from .config import Settings
from .db import Database
from .errors import ConfigurationError, ExternalServiceError, ValidationError
from .ffmpeg import ffprobe, summarize_probe
from .logging_setup import get_logger, log_event

log = get_logger("voice")

ELEVEN_BASE = "https://api.elevenlabs.io/v1"
ELEVEN_FORMATS = ("mp3_44100_128", "mp3_44100_192", "pcm_44100", "mp3_22050_32")
DEFAULT_SETTINGS = {"stability": 0.45, "similarity_boost": 0.75, "style": 0.2, "use_speaker_boost": True,
                    "speed": 1.05, "output_format": "mp3_44100_128"}


def system_voice_available() -> dict[str, Any]:
    sysname = platform.system()
    if sysname == "Windows":
        ok = shutil.which("powershell") is not None or shutil.which("powershell.exe") is not None
        return {"available": ok, "engine": "Windows SAPI (System.Speech)",
                "message": None if ok else "PowerShell not found."}
    if sysname == "Darwin":
        return {"available": shutil.which("say") is not None, "engine": "macOS say", "message": None}
    ok = shutil.which("espeak-ng") is not None or shutil.which("espeak") is not None
    return {"available": ok, "engine": "espeak-ng",
            "message": None if ok else "Install espeak-ng (e.g. `sudo apt install espeak-ng`) for the offline draft voice."}


def providers_status(settings: Settings) -> dict[str, Any]:
    return {
        "elevenlabs": {"configured": bool(settings.elevenlabs_api_key),
                       "message": None if settings.elevenlabs_api_key else "Set ELEVENLABS_API_KEY in .env to enable ElevenLabs voices."},
        "system": system_voice_available(),
    }


def cache_key(provider: str, voice_id: str, model: str, settings: dict[str, Any], text: str) -> str:
    payload = json.dumps({"p": provider, "v": voice_id, "m": model, "s": settings, "t": text.strip()}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def chars_to_words(chars: list[str], starts: list[float], ends: list[float]) -> list[dict[str, Any]]:
    words: list[dict[str, Any]] = []
    cur, cs, ce = "", None, None
    for ch, s, e in zip(chars, starts, ends, strict=False):
        if ch.isspace():
            if cur:
                words.append({"word": cur, "start": round(cs or 0, 3), "end": round(ce or 0, 3)})
            cur, cs, ce = "", None, None
            continue
        if cs is None:
            cs = s
        cur += ch
        ce = e
    if cur:
        words.append({"word": cur, "start": round(cs or 0, 3), "end": round(ce or 0, 3)})
    return words


class ElevenLabs:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        self.settings = settings
        self.transport = transport

    def _client(self) -> httpx.Client:
        if not self.settings.elevenlabs_api_key:
            raise ConfigurationError("ElevenLabs is not configured.",
                                     hint="Add ELEVENLABS_API_KEY to .env (see .env.example) and restart.")
        return httpx.Client(base_url=ELEVEN_BASE, timeout=self.settings.http_timeout, transport=self.transport,
                            headers={"xi-api-key": self.settings.elevenlabs_api_key})

    def _request(self, method: str, url: str, **kw: Any) -> httpx.Response:
        delay = 1.0
        last: Exception | None = None
        for attempt in range(3):
            try:
                with self._client() as c:
                    resp = c.request(method, url, **kw)
                if resp.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                    log_event(log, "elevenlabs retry", level=30, status=resp.status_code, attempt=attempt + 1)
                    time.sleep(delay)
                    delay *= 2
                    continue
                return resp
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last = exc
                time.sleep(delay)
                delay *= 2
        raise ExternalServiceError("Could not reach ElevenLabs.", detail=str(last))

    @staticmethod
    def _raise(resp: httpx.Response) -> None:
        if resp.status_code == 401:
            raise ConfigurationError("ElevenLabs rejected the API key.", hint="Check ELEVENLABS_API_KEY.")
        if resp.status_code >= 400:
            try:
                detail = json.dumps(resp.json())[:800]
            except ValueError:
                detail = resp.text[:800]
            raise ExternalServiceError(f"ElevenLabs returned HTTP {resp.status_code}.", detail=detail)

    def list_voices(self) -> list[dict[str, Any]]:
        resp = self._request("GET", "/voices")
        self._raise(resp)
        return [{"voice_id": v.get("voice_id"), "name": v.get("name"), "category": v.get("category"),
                 "labels": v.get("labels", {})} for v in resp.json().get("voices", [])]

    def synthesize(self, text: str, voice_id: str, settings: dict[str, Any], out_base: Path) -> tuple[Path, list[dict[str, Any]]]:
        fmt = settings.get("output_format", "mp3_44100_128")
        if fmt not in ELEVEN_FORMATS:
            raise ValidationError(f"Unsupported ElevenLabs output format '{fmt}'.")
        body = {
            "text": text,
            "model_id": settings.get("model_id") or self.settings.elevenlabs_model_id,
            "voice_settings": {k: settings[k] for k in ("stability", "similarity_boost", "style", "use_speaker_boost", "speed")
                               if k in settings},
        }
        resp = self._request("POST", f"/text-to-speech/{voice_id}/with-timestamps", params={"output_format": fmt}, json=body)
        self._raise(resp)
        data = resp.json()
        audio = base64.b64decode(data["audio_base64"])
        if fmt.startswith("pcm"):
            raw = out_base.with_suffix(".pcm")
            raw.write_bytes(audio)
            out = out_base.with_suffix(".wav")
            subprocess.run([self.settings.ffmpeg, "-y", "-v", "error", "-f", "s16le", "-ar", "44100", "-ac", "1",
                            "-i", str(raw), str(out)], check=True, timeout=120)
            raw.unlink()
        else:
            out = out_base.with_suffix(".mp3")
            out.write_bytes(audio)
        al = data.get("normalized_alignment") or data.get("alignment") or {}
        words = chars_to_words(al.get("characters", []), al.get("character_start_times_seconds", []),
                               al.get("character_end_times_seconds", []))
        return out, words


def system_synthesize(settings: Settings, text: str, voice: str, speed: float, out_base: Path) -> Path:
    status = system_voice_available()
    if not status["available"]:
        raise ConfigurationError("No offline system voice is available.", hint=status.get("message"))
    out = out_base.with_suffix(".wav")
    sysname = platform.system()
    rate_wpm = int(160 * speed)
    try:
        if sysname == "Windows":
            txt = out_base.with_suffix(".txt")
            txt.write_text(text, encoding="utf-8")
            rate = max(-10, min(10, int(round((speed - 1.0) * 10))))
            def q(v: object) -> str:  # PowerShell single-quoted literal
                return "'" + str(v).replace("'", "''") + "'"
            ps = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                  f"$s.Rate = {rate}; " + (f"$s.SelectVoice({q(voice)}); " if voice else "")
                  + f"$s.SetOutputToWaveFile({q(out)}); $s.Speak([IO.File]::ReadAllText({q(txt)})); $s.Dispose()")
            subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, capture_output=True, timeout=180)
            txt.unlink(missing_ok=True)
        elif sysname == "Darwin":
            aiff = out_base.with_suffix(".aiff")
            cmd = ["say", "-r", str(rate_wpm), "-o", str(aiff)] + (["-v", voice] if voice else []) + [text]
            subprocess.run(cmd, check=True, capture_output=True, timeout=180)
            subprocess.run([settings.ffmpeg, "-y", "-v", "error", "-i", str(aiff), str(out)], check=True, timeout=120)
            aiff.unlink(missing_ok=True)
        else:
            binary = shutil.which("espeak-ng") or shutil.which("espeak") or "espeak-ng"
            cmd = [binary, "-v", voice or "en-us", "-s", str(rate_wpm), "-w", str(out), text]
            subprocess.run(cmd, check=True, capture_output=True, timeout=180)
    except subprocess.CalledProcessError as exc:
        raise ExternalServiceError("The offline voice failed.", detail=(exc.stderr or b"").decode(errors="replace")[-500:]) from exc
    except subprocess.TimeoutExpired as exc:
        raise ExternalServiceError("The offline voice timed out.") from exc
    return out


# ------------------------------------------------------------------ voice profiles
def create_voice_profile(db: Database, data: dict[str, Any]) -> dict[str, Any]:
    provider = data.get("provider", "system")
    if provider not in ("system", "elevenlabs"):
        raise ValidationError("Voice provider must be 'system' or 'elevenlabs'.")
    if provider == "elevenlabs" and not str(data.get("voice_id", "")).strip():
        raise ValidationError("An ElevenLabs voice ID is required.")
    settings = {**DEFAULT_SETTINGS, **(data.get("settings") or {})}
    return db.insert("voice_profiles", {
        "name": data.get("name") or ("Offline draft voice" if provider == "system" else "ElevenLabs voice"),
        "provider": provider, "voice_id": str(data.get("voice_id", "")).strip(), "settings": settings,
        "authorized": bool(data.get("authorized", provider == "system")), "notes": data.get("notes", ""),
    })


def ensure_default_voice(db: Database) -> dict[str, Any]:
    existing = db.list("voice_profiles", order="created_at")
    if existing:
        return existing[0]
    return create_voice_profile(db, {"provider": "system", "name": "Offline draft voice", "settings": {"speed": 1.0}})


def generate_narration(db: Database, settings: Settings, script_id: str, voice_profile_id: str | None = None,
                       eleven: ElevenLabs | None = None) -> dict[str, Any]:
    script = db.get("scripts", script_id)
    profile = db.get("voice_profiles", voice_profile_id) if voice_profile_id else ensure_default_voice(db)
    if not profile["authorized"]:
        raise ValidationError(
            "This voice is not marked as authorised.",
            hint="Only use voices you own or have permission to use. Confirm authorisation on the Voice page.",
        )
    text = script["text"].strip()
    vs = profile["settings"]
    model = vs.get("model_id") or (settings.elevenlabs_model_id if profile["provider"] == "elevenlabs" else "system")
    key = cache_key(profile["provider"], profile["voice_id"], model, vs, text)
    base = settings.cache_dir / "tts" / key
    meta = base.with_suffix(".json")
    cached = False
    if meta.is_file():
        m = json.loads(meta.read_text(encoding="utf-8"))
        audio = Path(m["audio"])
        if audio.is_file():
            words, cached = m.get("words", []), True
    if not cached:
        if profile["provider"] == "elevenlabs":
            audio, words = (eleven or ElevenLabs(settings)).synthesize(text, profile["voice_id"], vs, base)
        else:
            audio, words = system_synthesize(settings, text, profile["voice_id"], float(vs.get("speed", 1.0)), base), []
        meta.write_text(json.dumps({"audio": str(audio), "words": words, "provider": profile["provider"]}), encoding="utf-8")
    duration = float(summarize_probe(ffprobe(settings.ffprobe, audio))["duration"] or 0)
    existing = db.list("narrations", "script_id = ? AND cache_key = ?", [script_id, key])
    if existing:
        rec = existing[0]
    else:
        rec = db.insert("narrations", {
            "script_id": script_id, "voice_profile_id": profile["id"], "provider": profile["provider"], "cache_key": key,
            "audio_path": str(audio), "duration": duration, "words": words,
            "alignment_method": "tts-alignment" if words else "none",
        })
    log_event(log, "narration", script_id=script_id, provider=profile["provider"], cached=cached, seconds=duration)
    return rec | {"cached": cached}
