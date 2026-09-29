"""Local media library: import (by reference or upload), metadata, thumbnails, dedupe."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any

from .config import Settings
from .db import Database
from .errors import MediaError, ValidationError
from .ffmpeg import ffprobe, run_ffmpeg, summarize_probe
from .logging_setup import get_logger, log_event

log = get_logger("media")

VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
AUDIO_EXT = {".wav", ".mp3", ".ogg", ".m4a", ".aac", ".flac", ".opus"}
SFX_EXT = {".wav", ".mp3", ".ogg"}
KINDS = ("video", "image", "audio", "sfx", "music")
SFX_CATEGORIES = ("impact", "whoosh", "click", "pop", "success", "fail", "transition", "notification",
                  "comedic", "gameplay")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def kind_for(path: Path, requested: str | None = None) -> str:
    ext = path.suffix.lower()
    if requested:
        if requested not in KINDS:
            raise ValidationError(f"Unknown media kind '{requested}'.")
        if requested == "sfx" and ext not in SFX_EXT:
            raise ValidationError("Sound effects must be WAV, MP3 or OGG.")
        if requested in ("music", "audio") and ext not in AUDIO_EXT:
            raise ValidationError("Music must be an audio file (WAV, MP3, OGG, M4A, AAC, FLAC).")
        if requested == "video" and ext not in VIDEO_EXT:
            raise ValidationError("Video must be MP4, MOV, WEBM, MKV or M4V.")
        if requested == "image" and ext not in IMAGE_EXT:
            raise ValidationError("Images must be PNG, JPG, WEBP, GIF or BMP.")
        return requested
    if ext in VIDEO_EXT:
        return "video"
    if ext in IMAGE_EXT:
        return "image"
    if ext in AUDIO_EXT:
        return "audio"
    raise ValidationError(f"Unsupported file type '{ext}'. Supported: MP4, MOV, WEBM, images and common audio formats.")


def make_thumbnail(settings: Settings, media_id: str, path: Path, kind: str, duration: float | None) -> str | None:
    out = settings.media_dir / "thumbnails" / f"{media_id}.jpg"
    try:
        if kind == "video":
            at = max(0.0, (duration or 0) * 0.1)
            run_ffmpeg(settings.ffmpeg, ["-y", "-ss", f"{at:.3f}", "-i", str(path), "-frames:v", "1",
                                         "-vf", "scale=320:-2", "-q:v", "4", str(out)],
                       timeout=60, what="Thumbnail", error_cls=MediaError)
        elif kind == "image":
            run_ffmpeg(settings.ffmpeg, ["-y", "-i", str(path), "-frames:v", "1", "-vf", "scale=320:-2", str(out)],
                       timeout=60, what="Thumbnail", error_cls=MediaError)
        else:
            run_ffmpeg(settings.ffmpeg, ["-y", "-i", str(path), "-filter_complex",
                                         "aformat=channel_layouts=mono,showwavespic=s=320x80:colors=0x7c5cff",
                                         "-frames:v", "1", str(out)], timeout=60, what="Waveform", error_cls=MediaError)
    except MediaError as exc:
        log_event(log, "thumbnail failed", level=30, media_id=media_id, error=exc.message)
        return None
    return str(out)


def import_media(db: Database, settings: Settings, path: Path, *, kind: str | None = None, copy: bool = False,
                 campaign_id: str | None = None, category: str | None = None, tags: list[str] | None = None,
                 license_note: str = "", display_name: str | None = None) -> dict[str, Any]:
    """Register a media file. By default the file is referenced in place (no duplication).

    ``copy=True`` stores a managed copy (used for uploads). Content already in the library
    (same SHA-256 and kind) is returned instead of creating a duplicate.
    """
    path = Path(path).expanduser()
    if not path.is_file():
        raise ValidationError(f"File not found: {path}")
    media_kind = kind_for(path, kind)
    if media_kind == "sfx" and category and category not in SFX_CATEGORIES:
        raise ValidationError(f"Unknown sound-effect category '{category}'.")
    if media_kind == "music" and not license_note.strip():
        raise ValidationError("Confirm the music is royalty-cleared or that you are authorised to use it (license note).")
    digest = sha256_file(path)
    existing = db.list("media", "sha256 = ? AND kind = ?", [digest, media_kind])
    if existing:
        rec = existing[0]
        upd: dict[str, Any] = {}
        if campaign_id and not rec["campaign_id"]:
            upd["campaign_id"] = campaign_id
        if not Path(rec["path"]).is_file():
            upd["path"] = str(path.resolve())
        if upd:
            rec = db.update("media", rec["id"], upd)
        return rec | {"deduplicated": True}
    info = summarize_probe(ffprobe(settings.ffprobe, path))
    if media_kind == "video" and not info["width"]:
        raise MediaError(f"{path.name} has no video stream.")
    if media_kind in ("audio", "sfx", "music") and not info["has_audio"]:
        raise MediaError(f"{path.name} has no audio stream.")
    stored = path.resolve()
    if copy:
        dest = settings.media_dir / "imported" / f"{digest[:16]}{path.suffix.lower()}"
        if not dest.exists():
            shutil.copy2(path, dest)
        stored = dest
    rec = db.insert("media", {
        "kind": media_kind, "path": str(stored), "filename": display_name or path.name, "sha256": digest,
        "size": stored.stat().st_size, "duration": info["duration"], "width": info["width"], "height": info["height"],
        "fps": info["fps"], "has_audio": info["has_audio"], "codec": info["codec"], "audio_codec": info["audio_codec"],
        "orientation": info["orientation"], "category": category, "tags": tags or [], "license_note": license_note,
        "campaign_id": campaign_id,
    })
    thumb = make_thumbnail(settings, rec["id"], stored, media_kind, info["duration"])
    if thumb:
        rec = db.update("media", rec["id"], {"thumbnail": thumb})
    log_event(log, "media imported", media_id=rec["id"], kind=media_kind, size=rec["size"], copied=copy)
    return rec | {"deduplicated": False}


def delete_media(db: Database, settings: Settings, media_id: str) -> None:
    rec = db.get("media", media_id)
    db.delete("media", media_id)
    managed = settings.media_dir / "imported"
    p = Path(rec["path"])
    # Only delete files the app itself manages; never delete the user's original files.
    if managed in p.parents and p.exists() and not db.list("media", "path = ?", [str(p)]):
        p.unlink()
    if rec.get("thumbnail") and Path(rec["thumbnail"]).exists():
        Path(rec["thumbnail"]).unlink()
