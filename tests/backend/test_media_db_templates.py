"""Media ingestion, persistence, templates and export naming."""

from __future__ import annotations

import json
import shutil

import pytest

from clipfactory.db import Database
from clipfactory.errors import MediaError, NotFoundError, ValidationError
from clipfactory.media import delete_media, import_media
from clipfactory.projects import safe_export_path
from clipfactory.templates import (
    delete_template,
    get_template,
    list_templates,
    save_template,
    validate_template,
)
from conftest import ffmpeg_gen


def test_video_metadata_thumbnail_and_dedupe(db, settings, clip, tmp_path):
    m = import_media(db, settings, clip)
    assert m["kind"] == "video" and not m["deduplicated"]
    assert (m["width"], m["height"]) == (1280, 720) and m["orientation"] == "landscape"
    assert abs(m["duration"] - 6.0) < 0.1 and abs(m["fps"] - 30) < 0.01 and m["has_audio"]
    assert m["codec"] == "h264" and m["audio_codec"] == "aac"
    assert m["path"] == str(clip.resolve()), "imported by reference, not copied"
    assert m["thumbnail"] and (tmp_path / "data").as_posix() in m["thumbnail"]
    # same content under another name -> same record
    dup = tmp_path / "copy-of-clip.mp4"
    shutil.copy(clip, dup)
    again = import_media(db, settings, dup)
    assert again["id"] == m["id"] and again["deduplicated"]
    assert db.scalar("SELECT COUNT(*) FROM media") == 1


def test_formats_images_audio_and_errors(db, settings, tmp_path):
    webm = ffmpeg_gen(settings, ["-f", "lavfi", "-i", "testsrc2=size=720x1280:rate=30:duration=2", "-c:v", "libvpx-vp9",
                                 "-deadline", "realtime", "-b:v", "300k"], tmp_path / "v.webm")
    mov = ffmpeg_gen(settings, ["-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=2", "-c:v", "libx264",
                                "-preset", "ultrafast", "-pix_fmt", "yuv420p"], tmp_path / "v.mov")
    png = ffmpeg_gen(settings, ["-f", "lavfi", "-i", "color=red:size=200x100", "-frames:v", "1"], tmp_path / "logo.png")
    wav = ffmpeg_gen(settings, ["-f", "lavfi", "-i", "sine=duration=1"], tmp_path / "hit.wav")
    assert import_media(db, settings, webm)["orientation"] == "portrait"
    assert import_media(db, settings, mov)["fps"] == 25
    assert import_media(db, settings, png)["kind"] == "image"
    sfx = import_media(db, settings, wav, kind="sfx", category="impact")
    assert sfx["kind"] == "sfx" and sfx["category"] == "impact"
    with pytest.raises(ValidationError, match="license"):
        import_media(db, settings, wav, kind="music")
    with pytest.raises(ValidationError):
        import_media(db, settings, wav, kind="sfx", category="laser")
    bad = tmp_path / "broken.mp4"
    bad.write_bytes(b"not a video")
    with pytest.raises((MediaError, ValidationError)):
        import_media(db, settings, bad)
    with pytest.raises(ValidationError):
        import_media(db, settings, tmp_path / "missing.mp4")


def test_delete_never_removes_user_originals(db, settings, clip):
    m = import_media(db, settings, clip)
    delete_media(db, settings, m["id"])
    assert clip.exists()
    copied = import_media(db, settings, clip, copy=True)
    assert settings.media_dir.as_posix() in copied["path"]
    delete_media(db, settings, copied["id"])
    assert not list((settings.media_dir / "imported").glob("*.mp4")), "managed copy is removed"
    assert clip.exists()


def test_persistence_survives_reopen(settings):
    db = Database(settings.db_path)
    c = db.insert("campaigns", {"name": "Persist", "slug": "persist", "platforms": ["TikTok"], "codes": ["A1"]})
    db.set_setting("preferences", {"default_quality": "draft"})
    db.close()
    db2 = Database(settings.db_path)
    got = db2.get("campaigns", c["id"])
    assert got["platforms"] == ["TikTok"] and got["codes"] == ["A1"]
    assert db2.get_setting("preferences") == {"default_quality": "draft"}
    assert db2.schema_version >= 1
    with pytest.raises(NotFoundError):
        db2.get("campaigns", "nope")
    db2.close()


def test_builtin_templates_are_valid_and_distinct(settings):
    ts = list_templates(settings)
    assert len(ts) >= 5 and all(t["builtin"] for t in ts)
    for t in ts:
        validate_template(dict(t))
    assert len({json.dumps({k: t[k] for k in ("pacing", "zoom", "captions")}, sort_keys=True) for t in ts}) == len(ts)


def test_user_templates_override_and_validate(settings):
    base = get_template(settings, "roblox_story")
    with pytest.raises(ValidationError) as e:
        save_template(settings, base | {"id": "mine", "fit": "stretch", "captions": base["captions"] | {"primary": "red"}})
    assert any("fit" in m for m in e.value.extra["errors"]) and any("primary" in m for m in e.value.extra["errors"])
    mine = save_template(settings, base | {"id": "mine", "name": "Mine", "zoom": base["zoom"] | {"intensity": 0.3}})
    assert mine["zoom"]["intensity"] == 0.3 and not mine["builtin"]
    override = save_template(settings, base | {"music": base["music"] | {"volume": 0.1}})
    assert override["overrides_builtin"]
    delete_template(settings, "roblox_story")
    assert get_template(settings, "roblox_story")["music"]["volume"] == base["music"]["volume"]
    with pytest.raises(ValidationError):
        delete_template(settings, "roblox_story")  # built-ins are read-only


def test_export_names_never_overwrite(tmp_path):
    src = tmp_path / "render.mp4"
    src.write_bytes(b"A" * 100)
    folder = tmp_path / "exports" / "camp"
    folder.mkdir(parents=True)
    first = safe_export_path(folder, "concept-01-discovery", ".mp4", src)
    assert first.name == "concept-01-discovery.mp4"
    first.write_bytes(b"B" * 100)  # different content with the same name
    second = safe_export_path(folder, "concept-01-discovery", ".mp4", src)
    assert second.name == "concept-01-discovery-v2.mp4"
    second.write_bytes(src.read_bytes())
    # identical content re-uses its existing file instead of creating v3
    assert safe_export_path(folder, "concept-01-discovery", ".mp4", src) == second
