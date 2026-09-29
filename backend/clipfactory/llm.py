"""Anthropic (Claude) integration for campaign analysis, ideas and scripts.

Uses the official ``anthropic`` Python SDK with structured outputs (``messages.parse`` with a
Pydantic model). When ``ANTHROPIC_API_KEY`` is missing every call raises ``ConfigurationError``
so callers can fall back to the offline heuristics and tell the user why.
"""

from __future__ import annotations

import time
from typing import Any, TypeVar

from pydantic import BaseModel

from .config import Settings
from .errors import ConfigurationError, ExternalServiceError
from .logging_setup import get_logger, log_event

log = get_logger("llm")
T = TypeVar("T", bound=BaseModel)


class ClaudeClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._client: Any = None

    @property
    def available(self) -> bool:
        return bool(self.settings.anthropic_api_key)

    def status(self) -> dict[str, Any]:
        return {
            "provider": "anthropic",
            "configured": self.available,
            "model": self.settings.anthropic_model,
            "message": None if self.available else "Set ANTHROPIC_API_KEY in .env to enable AI analysis, ideas and scripts.",
        }

    def _get(self) -> Any:
        if not self.available:
            raise ConfigurationError(
                "Claude is not configured.",
                hint="Add ANTHROPIC_API_KEY to your .env file (see .env.example) and restart the app.",
            )
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic(
                api_key=self.settings.anthropic_api_key,
                timeout=max(120.0, self.settings.http_timeout * 3),
                max_retries=2,  # SDK retries 408/409/429/5xx and connection errors
            )
        return self._client

    def structured(self, *, system: str, prompt: str, schema: type[T], max_tokens: int = 16000,
                   effort: str = "medium") -> T:
        import anthropic

        client = self._get()
        kwargs: dict[str, Any] = {
            "model": self.settings.anthropic_model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
            "output_format": schema,
            "output_config": {"effort": effort},
        }
        use_fallback = self.settings.anthropic_fallback == "default"
        started = time.monotonic()
        for attempt in (1, 2):
            call = dict(kwargs)
            if use_fallback:
                # Server-side refusal fallback (routes a declined request to Anthropic's recommended model).
                call["extra_headers"] = {"anthropic-beta": "server-side-fallback-2026-07-01"}
                call["extra_body"] = {"fallbacks": "default"}
            try:
                response = client.messages.parse(**call)
                break
            except anthropic.BadRequestError as exc:
                if use_fallback and attempt == 1 and "fallback" in str(exc).lower():
                    log_event(log, "fallback parameter rejected; retrying without it", level=30)
                    use_fallback = False
                    continue
                raise ExternalServiceError("Claude rejected the request.", detail=str(exc)[:1000]) from exc
            except anthropic.AuthenticationError as exc:
                raise ConfigurationError("The Anthropic API key was rejected.",
                                         hint="Check ANTHROPIC_API_KEY in .env.") from exc
            except anthropic.RateLimitError as exc:
                raise ExternalServiceError("Claude rate limit reached. Try again in a minute.",
                                           detail=str(exc)[:500]) from exc
            except anthropic.APIStatusError as exc:
                raise ExternalServiceError(f"Claude returned an error (HTTP {exc.status_code}).",
                                           detail=str(exc)[:1000]) from exc
            except anthropic.APITimeoutError as exc:
                raise ExternalServiceError("Claude did not respond in time.", detail=str(exc)[:500]) from exc
            except anthropic.APIConnectionError as exc:
                raise ExternalServiceError("Could not reach the Anthropic API. Check your internet connection.",
                                           detail=str(exc)[:500]) from exc
        log_event(log, "claude call", model=self.settings.anthropic_model, seconds=round(time.monotonic() - started, 2),
                  stop_reason=getattr(response, "stop_reason", None), schema=schema.__name__)
        if getattr(response, "stop_reason", None) == "refusal":
            raise ExternalServiceError("Claude declined this request.",
                                       detail=str(getattr(response, "stop_details", "")))
        if getattr(response, "stop_reason", None) == "max_tokens":
            raise ExternalServiceError("Claude's answer was cut off (max_tokens). Try a shorter input.")
        parsed = getattr(response, "parsed_output", None)
        if parsed is None:
            raise ExternalServiceError("Claude returned a response that did not match the expected format.")
        return parsed
