"""Publishing providers.

``SocialPublisher`` is the abstraction (publish / get_status / get_metrics).

* ``ManualPublisher`` (default, always available): prepares copy-caption / copy-hashtags / open-platform /
  open-file actions. Nothing is posted automatically. The user posts and then records the post URL.
* ``YouTubePublisher``: the official YouTube Data API v3 (resumable upload), enabled only when
  YOUTUBE_ACCESS_TOKEN is configured. Uploads are **private** by default.

Deliberately NOT implemented: browser automation of social sites, CAPTCHA bypass, fingerprint spoofing,
stealth automation, fake accounts, credential scraping, or any undocumented/private API.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import httpx

from .config import Settings
from .errors import ConfigurationError, ConflictError, ExternalServiceError, ValidationError

YT_UPLOAD = "https://www.googleapis.com/upload/youtube/v3/videos"
YT_VIDEOS = "https://www.googleapis.com/youtube/v3/videos"


class SocialPublisher(ABC):
    name = "base"
    platform = ""

    @abstractmethod
    def available(self) -> tuple[bool, str | None]: ...

    @abstractmethod
    def publish(self, video: Path, caption: str, hashtags: list[str], options: dict[str, Any] | None = None) -> dict[str, Any]: ...

    @abstractmethod
    def get_status(self, post_id: str) -> dict[str, Any]: ...

    @abstractmethod
    def get_metrics(self, post_id: str) -> dict[str, Any]: ...


class ManualPublisher(SocialPublisher):
    name = "manual"

    def __init__(self, platform: str, url: str):
        self.platform = platform
        self.url = url

    def available(self) -> tuple[bool, str | None]:
        return True, None

    def publish(self, video: Path, caption: str, hashtags: list[str], options: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"mode": "manual", "platform": self.platform, "open_url": self.url, "file": str(video),
                "caption": caption, "hashtags": " ".join(hashtags),
                "instructions": "Post the file yourself, then paste the post URL into the submission tracker."}

    def get_status(self, post_id: str) -> dict[str, Any]:
        return {"mode": "manual", "status": "unknown", "message": "Manual posts have no status API; update it in the tracker."}

    def get_metrics(self, post_id: str) -> dict[str, Any]:
        return {"mode": "manual", "message": "Enter views, likes, comments, shares and saves manually in the tracker."}


class YouTubePublisher(SocialPublisher):
    name = "youtube"
    platform = "YouTube"

    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        self.settings = settings
        self.transport = transport

    def available(self) -> tuple[bool, str | None]:
        if not self.settings.youtube_access_token:
            return False, "Set YOUTUBE_ACCESS_TOKEN (OAuth 2.0 token with the youtube.upload scope) to enable API uploads."
        return True, None

    def _headers(self) -> dict[str, str]:
        ok, msg = self.available()
        if not ok:
            raise ConfigurationError("YouTube publishing is not configured.", hint=msg)
        return {"Authorization": f"Bearer {self.settings.youtube_access_token}"}

    def _client(self) -> httpx.Client:
        return httpx.Client(timeout=max(300.0, self.settings.http_timeout), transport=self.transport)

    def publish(self, video: Path, caption: str, hashtags: list[str], options: dict[str, Any] | None = None) -> dict[str, Any]:
        opts = options or {}
        if not video.is_file():
            raise ValidationError("Export the video before publishing.")
        privacy = opts.get("privacy", "private")
        if privacy not in ("private", "unlisted", "public"):
            raise ValidationError("privacy must be private, unlisted or public.")
        title = (opts.get("title") or caption or video.stem)[:100]
        body = {"snippet": {"title": title, "description": f"{caption}\n\n{' '.join(hashtags)}".strip(),
                            "tags": [h.lstrip("#") for h in hashtags][:15], "categoryId": "20"},
                "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": bool(opts.get("made_for_kids", False))}}
        headers = self._headers()
        with self._client() as c:
            init = c.post(YT_UPLOAD, params={"uploadType": "resumable", "part": "snippet,status"},
                          headers=headers | {"Content-Type": "application/json; charset=UTF-8",
                                             "X-Upload-Content-Type": "video/mp4",
                                             "X-Upload-Content-Length": str(video.stat().st_size)},
                          content=json.dumps(body))
            self._raise(init)
            location = init.headers.get("Location")
            if not location:
                raise ExternalServiceError("YouTube did not return an upload URL.")
            with video.open("rb") as f:
                up = c.put(location, headers=headers | {"Content-Type": "video/mp4"}, content=f.read())
            self._raise(up)
        data = up.json()
        return {"mode": "api", "platform": "YouTube", "post_id": data.get("id"),
                "post_url": f"https://youtube.com/shorts/{data.get('id')}", "privacy": privacy}

    def get_status(self, post_id: str) -> dict[str, Any]:
        with self._client() as c:
            r = c.get(YT_VIDEOS, params={"part": "status,processingDetails", "id": post_id}, headers=self._headers())
        self._raise(r)
        items = r.json().get("items", [])
        if not items:
            raise ExternalServiceError("Video not found on YouTube.")
        return {"mode": "api", "status": items[0].get("status", {}), "processing": items[0].get("processingDetails", {})}

    def get_metrics(self, post_id: str) -> dict[str, Any]:
        with self._client() as c:
            r = c.get(YT_VIDEOS, params={"part": "statistics", "id": post_id}, headers=self._headers())
        self._raise(r)
        items = r.json().get("items", [])
        if not items:
            raise ExternalServiceError("Video not found on YouTube.")
        st = items[0].get("statistics", {})
        return {"mode": "api", "views": int(st.get("viewCount", 0)), "likes": int(st.get("likeCount", 0)),
                "comments": int(st.get("commentCount", 0))}

    @staticmethod
    def _raise(r: httpx.Response) -> None:
        if r.status_code == 401:
            raise ConfigurationError("YouTube rejected the access token (expired or missing scope).",
                                     hint="Create a fresh OAuth token with the youtube.upload scope.")
        if r.status_code >= 400:
            raise ExternalServiceError(f"YouTube API error (HTTP {r.status_code}).", detail=r.text[:800])


def publishers(settings: Settings, platform_urls: dict[str, str]) -> dict[str, SocialPublisher]:
    pubs: dict[str, SocialPublisher] = {f"manual:{p}": ManualPublisher(p, u) for p, u in platform_urls.items()}
    pubs["youtube"] = YouTubePublisher(settings)
    return pubs


def require_exported(project: dict[str, Any]) -> Path:
    if project["status"] not in ("EXPORTED", "POSTED", "SUBMITTED"):
        raise ConflictError("Only approved and exported videos can be published.",
                            hint="Review → Approve → Export first. Nothing is published automatically.")
    path = Path(project["export_path"] or "")
    if not path.is_file():
        raise ConflictError("The exported file is missing. Export again.")
    return path
