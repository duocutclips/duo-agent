"""Runtime configuration.

All secrets come from environment variables (optionally loaded from a local ``.env`` file that
is git-ignored). Nothing secret is ever written to the database or the logs.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Variables whose values must never be logged or returned by the API.
SECRET_ENV_VARS = (
    "ANTHROPIC_API_KEY",
    "ELEVENLABS_API_KEY",
    "WHISPER_API_KEY",
    "YOUTUBE_ACCESS_TOKEN",
    "CLIP_FACTORY_API_TOKEN",
)


def load_dotenv(path: Path) -> None:
    """Minimal .env loader (KEY=VALUE lines). Existing environment variables win."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass
class Settings:
    data_dir: Path
    logs_dir: Path
    exports_dir: Path
    templates_dir: Path
    ffmpeg: str
    ffprobe: str
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-5-5"
    anthropic_fallback: str = "default"
    elevenlabs_api_key: str = ""
    elevenlabs_default_voice_id: str = ""
    elevenlabs_model_id: str = "eleven_multilingual_v2"
    whisper_api_url: str = ""
    whisper_api_key: str = ""
    whisper_model: str = "whisper-1"
    youtube_access_token: str = ""
    api_token: str = ""
    host: str = "127.0.0.1"
    port: int = 8765
    http_timeout: float = 60.0
    ffmpeg_timeout: float = 900.0
    extra: dict[str, str] = field(default_factory=dict)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "clipfactory.sqlite3"

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def renders_dir(self) -> Path:
        return self.data_dir / "renders"

    @property
    def user_templates_dir(self) -> Path:
        return self.data_dir / "templates"

    def ensure_dirs(self) -> None:
        for d in (
            self.data_dir,
            self.logs_dir,
            self.exports_dir,
            self.media_dir,
            self.cache_dir,
            self.renders_dir,
            self.user_templates_dir,
            self.media_dir / "thumbnails",
            self.media_dir / "imported",
            self.cache_dir / "tts",
        ):
            d.mkdir(parents=True, exist_ok=True)


def _find_binary(env_name: str, name: str) -> str:
    explicit = _env(env_name)
    if explicit:
        return explicit
    found = shutil.which(name)
    return found or name


def load_settings(data_dir: Path | None = None) -> Settings:
    load_dotenv(REPO_ROOT / ".env")
    if data_dir is not None:
        base = Path(data_dir).expanduser().resolve()
    else:
        base = Path(_env("CLIP_FACTORY_DATA_DIR") or (REPO_ROOT / "data")).expanduser().resolve()
    default_layout = base == (REPO_ROOT / "data").resolve()
    # In the repository layout logs/ and exports/ sit at the repo root (as the spec asks);
    # with a custom data dir (packaged app, tests) they live inside it.
    logs = Path(_env("CLIP_FACTORY_LOGS_DIR") or (REPO_ROOT / "logs" if default_layout else base / "logs"))
    exports = Path(_env("CLIP_FACTORY_EXPORTS_DIR") or (REPO_ROOT / "exports" if default_layout else base / "exports"))
    if data_dir is not None:
        logs, exports = base / "logs", base / "exports"
    s = Settings(
        data_dir=base,
        logs_dir=logs.resolve(),
        exports_dir=exports.resolve(),
        templates_dir=Path(_env("CLIP_FACTORY_TEMPLATES_DIR") or (REPO_ROOT / "templates")).resolve(),
        ffmpeg=_find_binary("FFMPEG_PATH", "ffmpeg"),
        ffprobe=_find_binary("FFPROBE_PATH", "ffprobe"),
        anthropic_api_key=_env("ANTHROPIC_API_KEY"),
        anthropic_model=_env("ANTHROPIC_MODEL", "claude-opus-5-5"),
        anthropic_fallback=_env("ANTHROPIC_REFUSAL_FALLBACK", "default"),
        elevenlabs_api_key=_env("ELEVENLABS_API_KEY"),
        elevenlabs_default_voice_id=_env("ELEVENLABS_VOICE_ID"),
        elevenlabs_model_id=_env("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2"),
        whisper_api_url=_env("WHISPER_API_URL"),
        whisper_api_key=_env("WHISPER_API_KEY"),
        whisper_model=_env("WHISPER_MODEL", "whisper-1"),
        youtube_access_token=_env("YOUTUBE_ACCESS_TOKEN"),
        api_token=_env("CLIP_FACTORY_API_TOKEN"),
        host=_env("CLIP_FACTORY_HOST", "127.0.0.1"),
        port=int(_env("CLIP_FACTORY_PORT", "8765") or 8765),
        http_timeout=float(_env("CLIP_FACTORY_HTTP_TIMEOUT", "60") or 60),
        ffmpeg_timeout=float(_env("CLIP_FACTORY_FFMPEG_TIMEOUT", "900") or 900),
    )
    s.ensure_dirs()
    return s


def secret_values() -> list[str]:
    """Current values of secret environment variables (used by the log redactor)."""
    return [v for v in (os.environ.get(k, "") for k in SECRET_ENV_VARS) if len(v) >= 6]
