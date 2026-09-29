"""Shared fixtures. Tests never use real API keys: every secret env var is blanked first."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

SECRETS = ("ANTHROPIC_API_KEY", "ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID", "WHISPER_API_URL", "WHISPER_API_KEY",
           "YOUTUBE_ACCESS_TOKEN", "CLIP_FACTORY_API_TOKEN", "CLIP_FACTORY_DATA_DIR", "CLIP_FACTORY_LOGS_DIR",
           "CLIP_FACTORY_EXPORTS_DIR")
for _k in SECRETS:
    os.environ[_k] = ""  # blank (not unset) so a developer's .env cannot fill them in

from clipfactory.config import Settings, load_settings  # noqa: E402
from clipfactory.db import Database  # noqa: E402
from clipfactory.llm import ClaudeClient  # noqa: E402


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return load_settings(tmp_path / "data")


@pytest.fixture
def db(settings: Settings) -> Database:
    d = Database(settings.db_path)
    yield d
    d.close()


@pytest.fixture
def llm(settings: Settings) -> ClaudeClient:
    return ClaudeClient(settings)


def ffmpeg_gen(settings: Settings, args: list[str], out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([settings.ffmpeg, "-y", "-v", "error", *args, str(out)], check=True, timeout=120)
    return out


@pytest.fixture
def clip(settings: Settings, tmp_path: Path) -> Path:
    """6 s 1280x720 30 fps H.264 clip with a moving pattern and a tone."""
    return ffmpeg_gen(settings, ["-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30:duration=6",
                                 "-f", "lavfi", "-i", "sine=frequency=330:duration=6",
                                 "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest"],
                      tmp_path / "src" / "clip.mp4")


@pytest.fixture
def voice_wav(settings: Settings, tmp_path: Path) -> Path:
    """4 s 'speech-like' audio: tone bursts separated by short pauses."""
    return ffmpeg_gen(settings, ["-f", "lavfi", "-i",
                                 "aevalsrc=0.4*sin(2*PI*220*t)*gt(sin(2*PI*1.5*t)\\,-0.6):s=44100:d=4", "-ac", "1"],
                      tmp_path / "src" / "voice.wav")


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "slow: renders video with FFmpeg (seconds to minutes)")
