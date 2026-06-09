"""TikTok direct links from data/video_overrides.json."""

from __future__ import annotations

import json
from typing import Any

from paths import VIDEO_OVERRIDES_FILE

from .base import ResolvedVideo, VideoProviderPort


class TikTokOverrideProvider(VideoProviderPort):
    platform = "TikTok"

    @property
    def provider_id(self) -> str:
        return "tiktok_override"

    def _load_overrides(self) -> dict[str, Any]:
        if not VIDEO_OVERRIDES_FILE.exists():
            return {}
        try:
            with open(VIDEO_OVERRIDES_FILE, encoding="utf-8") as f:
                data = json.load(f)
            return data.get("entries", data)
        except (json.JSONDecodeError, OSError):
            return {}

    def resolve(self, name: str, category: str, *, address: str | None = None) -> ResolvedVideo | None:
        entries = self._load_overrides()
        entry = entries.get(name, {})
        tt = entry.get("TikTok") or entry.get("tiktok")
        if not tt or not isinstance(tt, dict):
            return None
        url = tt.get("url", "")
        if not url or not self.is_direct_url(url, "TikTok"):
            return None
        return ResolvedVideo(
            platform="TikTok",
            url=url,
            summary=tt.get("summary", f"{name} on TikTok"),
            video_id=tt.get("video_id"),
            source=self.provider_id,
        )


class ManualOverrideProvider(VideoProviderPort):
    """YouTube (and optional TikTok) from overrides — fallback for both platforms."""

    platform = "YouTube"

    @property
    def provider_id(self) -> str:
        return "manual_override"

    def _load_overrides(self) -> dict[str, Any]:
        if not VIDEO_OVERRIDES_FILE.exists():
            return {}
        try:
            with open(VIDEO_OVERRIDES_FILE, encoding="utf-8") as f:
                data = json.load(f)
            return data.get("entries", data)
        except (json.JSONDecodeError, OSError):
            return {}

    def resolve(self, name: str, category: str, *, address: str | None = None) -> ResolvedVideo | None:
        entries = self._load_overrides()
        entry = entries.get(name, {})
        yt = entry.get("YouTube") or entry.get("youtube")
        if not yt or not isinstance(yt, dict):
            return None
        url = yt.get("url", "")
        if not url or not self.is_direct_url(url, "YouTube"):
            return None
        if not self.validate_playable_url(url, "YouTube"):
            return None
        return ResolvedVideo(
            platform="YouTube",
            url=url,
            summary=yt.get("summary", f"{name} on YouTube"),
            video_id=yt.get("video_id"),
            source=self.provider_id,
        )
