"""External services with mocked HTTP transports (no network, no real keys)."""

from __future__ import annotations

import base64
import dataclasses
import json

import httpx
import pytest

from clipfactory.db import Database
from clipfactory.errors import ConfigurationError, ExternalServiceError, ValidationError
from clipfactory.publishing import ManualPublisher, YouTubePublisher
from clipfactory.transcription import estimate_alignment, transcribe_narration, whisper_api
from clipfactory.voice import ElevenLabs, cache_key, chars_to_words, create_voice_profile, generate_narration
from conftest import ffmpeg_gen


@pytest.fixture
def script(db: Database):
    c = db.insert("campaigns", {"name": "C", "slug": "c"})
    return db.insert("scripts", {"campaign_id": c["id"], "target_seconds": 15, "text": "Hi there. Use code AB12.",
                                 "est_seconds": 2.0, "warnings": [], "generator": "test"})


def test_chars_to_words():
    chars = list("Hi you")
    starts = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]
    ends = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]
    assert chars_to_words(chars, starts, ends) == [{"word": "Hi", "start": 0.0, "end": 0.2},
                                                  {"word": "you", "start": 0.3, "end": 0.6}]


def test_elevenlabs_narration_with_timestamps_and_cache(db, settings, script, tmp_path):
    mp3 = ffmpeg_gen(settings, ["-f", "lavfi", "-i", "sine=duration=2", "-c:a", "libmp3lame"], tmp_path / "tts.mp3")
    calls: list[httpx.Request] = []
    text = "Hi there. Use code AB12."

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        assert req.headers["xi-api-key"] == "test-eleven-key"
        body = json.loads(req.content)
        assert body["text"] == text and req.url.path.endswith("/with-timestamps")
        n = len(text)
        return httpx.Response(200, json={"audio_base64": base64.b64encode(mp3.read_bytes()).decode(),
                                         "alignment": {"characters": list(text),
                                                       "character_start_times_seconds": [i * 0.07 for i in range(n)],
                                                       "character_end_times_seconds": [i * 0.07 + 0.07 for i in range(n)]}})

    s = dataclasses.replace(settings, elevenlabs_api_key="test-eleven-key")
    eleven = ElevenLabs(s, transport=httpx.MockTransport(handler))
    voice = create_voice_profile(db, {"provider": "elevenlabs", "voice_id": "v123", "authorized": True})
    n = generate_narration(db, s, script["id"], voice["id"], eleven=eleven)
    assert n["alignment_method"] == "tts-alignment" and [w["word"] for w in n["words"]][:2] == ["Hi", "there."]
    assert abs(n["duration"] - 2.0) < 0.1 and not n["cached"]
    again = generate_narration(db, s, script["id"], voice["id"], eleven=eleven)
    assert again["cached"] and again["id"] == n["id"] and len(calls) == 1  # cache hit, no second API call


def test_voice_authorisation_is_required(db, settings, script):
    v = create_voice_profile(db, {"provider": "elevenlabs", "voice_id": "clone1"})
    assert not v["authorized"]
    with pytest.raises(ValidationError, match="authoris"):
        generate_narration(db, settings, script["id"], v["id"])


def test_elevenlabs_errors_are_clear(settings):
    with pytest.raises(ConfigurationError):
        ElevenLabs(settings).list_voices()
    s = dataclasses.replace(settings, elevenlabs_api_key="bad-key-123")
    unauthorized = ElevenLabs(s, transport=httpx.MockTransport(lambda r: httpx.Response(401, json={})))
    with pytest.raises(ConfigurationError, match="rejected"):
        unauthorized.list_voices()


def test_cache_key_changes_with_inputs():
    a = cache_key("elevenlabs", "v", "m", {"speed": 1.0}, "hello")
    assert a == cache_key("elevenlabs", "v", "m", {"speed": 1.0}, "hello")
    assert a != cache_key("elevenlabs", "v", "m", {"speed": 1.1}, "hello")
    assert a != cache_key("elevenlabs", "v", "m", {"speed": 1.0}, "hello!")


def test_whisper_api_word_timestamps(settings, tmp_path):
    audio = ffmpeg_gen(settings, ["-f", "lavfi", "-i", "sine=duration=1"], tmp_path / "a.wav")

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.headers["authorization"] == "Bearer wk-123456"
        assert b'name="timestamp_granularities[]"' in req.content
        return httpx.Response(200, json={"words": [{"word": " Hello", "start": 0.0, "end": 0.4},
                                                   {"word": "world", "start": 0.5, "end": 0.9}]})

    s = dataclasses.replace(settings, whisper_api_url="https://stt.example/v1/audio/transcriptions", whisper_api_key="wk-123456")
    words = whisper_api(s, audio, transport=httpx.MockTransport(handler))
    assert words == [{"word": "Hello", "start": 0.0, "end": 0.4}, {"word": "world", "start": 0.5, "end": 0.9}]
    with pytest.raises(ExternalServiceError):
        whisper_api(s, audio, transport=httpx.MockTransport(lambda r: httpx.Response(400, text="bad")))


def test_transcription_falls_back_to_estimated_alignment(db, settings, script, voice_wav):
    n = db.insert("narrations", {"script_id": script["id"], "provider": "system", "cache_key": "k", "audio_path": str(voice_wav),
                                 "duration": 4.0, "words": [], "alignment_method": "none"})
    out = transcribe_narration(db, settings, n["id"])
    assert out["alignment_method"] == "estimated-alignment"
    words = out["words"]
    assert [w["word"] for w in words] == ["Hi", "there.", "Use", "code", "AB12."]
    assert all(0 <= w["start"] < w["end"] <= 4.0 for w in words)
    assert all(a["end"] <= b["start"] + 1e-6 for a, b in zip(words, words[1:], strict=False))


def test_estimated_alignment_avoids_silence(settings, tmp_path):
    # 1 s tone, 1 s silence, 1 s tone: no word should be placed in the gap
    audio = ffmpeg_gen(settings, ["-f", "lavfi", "-i", "aevalsrc=0.5*sin(2*PI*300*t)*(lt(t\\,1)+gt(t\\,2)):s=16000:d=3"],
                       tmp_path / "gap.wav")
    words = estimate_alignment(settings, audio, "one two. three four.", 3.0)
    for w in words:
        mid = (w["start"] + w["end"]) / 2
        assert not 1.1 < mid < 1.9, w


def test_youtube_publisher_private_upload_and_metrics(settings, tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"\x00" * 64)
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(f"{req.method} {req.url.host}{req.url.path}")
        assert req.headers["authorization"] == "Bearer yt-token-123"
        if req.method == "POST":
            body = json.loads(req.content)
            assert body["status"]["privacyStatus"] == "private"
            return httpx.Response(200, headers={"Location": "https://upload.example/session/1"})
        if req.method == "PUT":
            return httpx.Response(200, json={"id": "abc123"})
        return httpx.Response(200, json={"items": [{"statistics": {"viewCount": "1500", "likeCount": "90", "commentCount": "4"}}]})

    s = dataclasses.replace(settings, youtube_access_token="yt-token-123")
    yt = YouTubePublisher(s, transport=httpx.MockTransport(handler))
    res = yt.publish(video, "caption", ["#a"])
    assert res == {"mode": "api", "platform": "YouTube", "post_id": "abc123",
                   "post_url": "https://youtube.com/shorts/abc123", "privacy": "private"}
    assert yt.get_metrics("abc123") == {"mode": "api", "views": 1500, "likes": 90, "comments": 4}
    assert len(seen) == 3


def test_publishers_without_configuration(settings, tmp_path):
    ok, msg = YouTubePublisher(settings).available()
    assert not ok and "YOUTUBE_ACCESS_TOKEN" in msg
    with pytest.raises(ConfigurationError):
        YouTubePublisher(settings).get_metrics("x")
    manual = ManualPublisher("TikTok", "https://www.tiktok.com/upload")
    r = manual.publish(tmp_path / "v.mp4", "cap", ["#x"])
    assert r["mode"] == "manual" and r["open_url"].startswith("https://")
