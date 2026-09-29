"""Typed application errors.

Every error carries a stable ``code``, a user-friendly ``message`` and optional technical
``detail``. The API layer turns them into JSON responses; nothing fails silently.
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    code = "app_error"
    status = 500

    def __init__(self, message: str, *, detail: str | None = None, hint: str | None = None, **extra: Any):
        super().__init__(message)
        self.message = message
        self.detail = detail
        self.hint = hint
        self.extra = extra

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.hint:
            d["hint"] = self.hint
        if self.detail:
            d["detail"] = self.detail
        if self.extra:
            d.update(self.extra)
        return d


class ValidationError(AppError):
    code = "validation_error"
    status = 400


class NotFoundError(AppError):
    code = "not_found"
    status = 404


class ConflictError(AppError):
    code = "conflict"
    status = 409


class ConfigurationError(AppError):
    """An integration is not configured (missing API key, missing binary...)."""

    code = "configuration_error"
    status = 424


class ExternalServiceError(AppError):
    code = "external_service_error"
    status = 502


class MediaError(AppError):
    code = "media_error"
    status = 422


class RenderError(AppError):
    code = "render_error"
    status = 500
