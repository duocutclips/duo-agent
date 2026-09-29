"""Rendering (real FFmpeg), determinism, QA, and one full end-to-end run through the HTTP API."""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from clipfactory.ffmpeg import ffprobe, summarize_probe
from clipfactory.media import import_media
from clipfactory.qa import run_qa
from clipfactory.render import render_timeline
from clipfactory.server import create_app
from clipfactory.templates import get_template
from clipfactory.timeline import build_timeline
from clipfactory.transcription import estimate_alignment
from conftest import ffmpeg_gen

pytestmark = pytest.mark.slow
SCRIPT = "Nobody knows this trick. Use code HEIST50 now."


def _sha(p) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


@pytest.fixture
def short_timeline(db, settings, clip, voice_wav, tmp_path):
    m = import_media(db, settings, clip)
    hit = ffmpeg_gen(settings, ["-f", "lavfi", "-i", "sine=frequency=900:duration=0.2"], tmp_path / "pop.wav")
    music = ffmpeg_gen(settings, ["-f", "lavfi", "-i", "sine=frequency=110:duration=2"], tmp_path / "music.wav")
    sfx = import_media(db, settings, hit, kind="sfx", category="pop")
    mus = import_media(db, settings, music, kind="music", license_note="generated")
    words = estimate_alignment(settings, voice_wav, SCRIPT, 4.0)
    narration = {"duration": 4.0, "words": words, "audio_path": str(voice_wav)}
    return build_timeline(template=get_template(settings, "roblox_story"), narration=narration, script_text=SCRIPT, media=[m],
                          segments=[], sfx_library=[sfx | {"category": c} for c in ("pop", "impact", "whoosh", "success")],
                          music=mus, hook_text="Nobody knows this trick", cta_text="Use code HEIST50",
                          emphasis_terms=["HEIST50"], seed=3)


def test_render_output_spec_qa_and_determinism(settings, short_timeline, tmp_path):
    a = render_timeline(settings, short_timeline, tmp_path / "r1", quality="draft")
    info = summarize_probe(ffprobe(settings.ffprobe, a["path"]))
    assert (info["width"], info["height"]) == (1080, 1920)
    assert info["codec"] == "h264" and info["audio_codec"] == "aac" and info["pix_fmt"] == "yuv420p"
    assert abs(info["duration"] - short_timeline["duration"]) < 0.25
    assert abs(info["fps"] - 30) < 0.01

    qa = run_qa(settings, Path(a["path"]),
                short_timeline, script_text=SCRIPT, rules={"required_phrases": ["HEIST50"], "banned_terms": [],
                                                           "min_seconds": None, "max_seconds": None, "codes": []})
    assert qa["overall"] == "READY", qa["failed"]

    # cached re-render of the same timeline is instant and identical
    t = time.monotonic()
    again = render_timeline(settings, short_timeline, tmp_path / "r1", quality="draft")
    assert again["cached"] and time.monotonic() - t < 2
    # a fresh render in another folder is byte-identical (deterministic pipeline)
    b = render_timeline(settings, short_timeline, tmp_path / "r2", quality="draft")
    assert _sha(Path(a["path"])) == _sha(Path(b["path"]))


def test_qa_catches_wrong_output(settings, short_timeline, tmp_path):
    bad = ffmpeg_gen(settings, ["-f", "lavfi", "-i", "color=black:size=640x360:rate=30:duration=2", "-c:v", "libx264",
                                "-pix_fmt", "yuv420p"], tmp_path / "bad.mp4")
    qa = run_qa(settings, bad, short_timeline, script_text=SCRIPT)
    assert qa["overall"] == "NOT READY"
    failed = " ".join(qa["failed"])
    for name in ("Resolution", "Aspect ratio", "Duration", "Audio"):
        assert name in failed, name


def _wait(c: TestClient, job: dict, timeout: float = 900) -> dict:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        j = c.get(f"/api/jobs/{job['id']}").json()
        if j["status"] == "succeeded":
            return j
        assert j["status"] != "failed", j["error"]
        time.sleep(0.5)
    raise AssertionError("job timed out")


def test_end_to_end_campaign_to_tracked_post(settings):
    """Demo brief -> analysis -> ideas -> script -> voice -> edit -> render -> QA -> approve -> export -> post -> analytics."""
    with TestClient(create_app(settings)) as c:
        demo = _wait(c, c.post("/api/demo").json(), 300)["result"]
        cid = demo["campaign_id"]
        camp = c.get(f"/api/campaigns/{cid}").json()
        assert camp["analysis"]["generator"] == "offline-heuristic" and "HEIST50" in camp["codes"]
        media = c.get(f"/api/media?campaign_id={cid}&kind=video").json()
        assert len(media) == 3 and all(m["segment_count"] > 0 for m in media)

        ideas = c.post(f"/api/campaigns/{cid}/ideas", json={}).json()["ideas"]
        assert len(ideas) == 10
        p = c.post("/api/projects", json={"campaign_id": cid, "idea_id": ideas[1]["id"]}).json()
        assert p["status"] == "DRAFT" and len(p["media_ids"]) == 3

        _wait(c, c.post(f"/api/projects/{p['id']}/pipeline", json={"quality": "draft"}).json())
        p = c.get(f"/api/projects/{p['id']}").json()
        assert p["qa"]["overall"] == "READY", p["qa"]["failed"]
        assert p["status"] == "REVIEW"  # QA READY moves it to review, never further on its own
        assert c.post(f"/api/projects/{p['id']}/export").status_code == 409  # needs human approval

        assert c.post(f"/api/projects/{p['id']}/status", json={"status": "APPROVED"}).status_code == 200
        p = c.post(f"/api/projects/{p['id']}/export").json()
        assert p["status"] == "EXPORTED" and p["export_path"].endswith("concept-02-secret.mp4")
        assert f"/exports/{camp['slug']}/" in p["export_path"].replace("\\", "/")

        kit = c.get(f"/api/projects/{p['id']}/publish-kit").json()
        assert "#SeedHeist" in kit["hashtags"] and kit["platforms"]
        # YouTube API upload is not configured and needs explicit confirmation anyway
        assert c.post(f"/api/projects/{p['id']}/publish", json={"provider": "youtube", "confirm": True}).status_code == 409

        r = c.post(f"/api/projects/{p['id']}/mark-posted", json={"platform": "TikTok", "post_url": "https://www.tiktok.com/@x/video/1"})
        assert r.json()["project"]["status"] == "POSTED"
        sub = r.json()["submission"]
        c.patch(f"/api/submissions/{sub['id']}", json={"status": "SUBMITTED", "views": 4000, "likes": 300})
        assert c.get(f"/api/projects/{p['id']}").json()["status"] == "SUBMITTED"
        a = c.get(f"/api/analytics?campaign_id={cid}").json()
        assert a["totals"]["views"] == 4000 and a["totals"]["earnings"] == 6.0  # $1.50 CPM from the brief
        assert a["sample_note"]
        dash = c.get("/api/dashboard").json()
        assert dash["videos_posted"] == 1 and dash["total_views"] == 4000
