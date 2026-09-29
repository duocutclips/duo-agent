"""Structured JSON-lines logging with secret redaction."""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from .config import secret_values

_TOKEN_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{8,}"),
    re.compile(r"(?i)(xi-api-key[\"']?\s*[:=]\s*[\"']?)[A-Za-z0-9_\-]{8,}"),
    re.compile(r"(?i)((?:api[_-]?key|token|password|secret|cookie)[\"']?\s*[:=]\s*[\"']?)[^\s\"',;&]{6,}"),
    re.compile(r"(?i)([?&](?:token|key|access_token)=)[^&\s]+"),
]


def redact(text: str) -> str:
    """Remove secrets from a string. Applied to every log record."""
    if not text:
        return text
    for value in secret_values():
        text = text.replace(value, "[REDACTED]")
    for pat in _TOKEN_PATTERNS:
        if pat.groups:
            text = pat.sub(lambda m: m.group(1) + "[REDACTED]", text)
        else:
            text = pat.sub("[REDACTED]", text)
    return text


def _redact_obj(obj: Any) -> Any:
    if isinstance(obj, str):
        return redact(obj)
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if re.search(r"(?i)(api[_-]?key|token|password|secret|cookie|authorization)", str(k)):
                out[k] = "[REDACTED]"
            else:
                out[k] = _redact_obj(v)
        return out
    if isinstance(obj, (list, tuple)):
        return [_redact_obj(v) for v in obj]
    return obj


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact(record.getMessage()),
        }
        ctx = getattr(record, "ctx", None)
        if isinstance(ctx, dict):
            payload["ctx"] = _redact_obj(ctx)
        if record.exc_info:
            payload["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False, default=str)


_configured: set[str] = set()


def setup_logging(logs_dir: Path, level: int = logging.INFO) -> None:
    key = str(logs_dir)
    root = logging.getLogger("clipfactory")
    if key in _configured:
        return
    logs_dir.mkdir(parents=True, exist_ok=True)
    for h in list(root.handlers):
        root.removeHandler(h)
    fh = RotatingFileHandler(logs_dir / "clipfactory.jsonl", maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    fh.setFormatter(JsonFormatter())
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(JsonFormatter())
    root.addHandler(fh)
    root.addHandler(sh)
    root.setLevel(level)
    root.propagate = False
    _configured.clear()
    _configured.add(key)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"clipfactory.{name}")


def log_event(logger: logging.Logger, msg: str, level: int = logging.INFO, **ctx: Any) -> None:
    logger.log(level, msg, extra={"ctx": ctx})
