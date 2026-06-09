"""Provider registry and default resolution chains."""

from __future__ import annotations

import os

from .base import VideoProviderPort
from .tiktok_api import TikTokApiProvider
from .tiktok_override import ManualOverrideProvider, TikTokOverrideProvider
from .youtube_api import YouTubeApiProvider

DEFAULT_CHAINS: dict[str, list[str]] = {
    "YouTube": ["youtube_api", "manual_override"],
    "TikTok": ["tiktok_api", "tiktok_override"],
}

_PROVIDERS: dict[str, VideoProviderPort] = {
    "youtube_api": YouTubeApiProvider(),
    "manual_override": ManualOverrideProvider(),
    "tiktok_api": TikTokApiProvider(),
    "tiktok_override": TikTokOverrideProvider(),
}


def get_provider(provider_id: str) -> VideoProviderPort | None:
    return _PROVIDERS.get(provider_id)


def chain_for_platform(platform: str) -> list[str]:
    mode = os.environ.get("TIKTOK_PROVIDER_MODE", "auto").lower()
    if platform == "TikTok" and mode == "override_only":
        return ["tiktok_override"]
    if platform == "TikTok" and mode == "api_only":
        return ["tiktok_api"]
    return DEFAULT_CHAINS.get(platform, [])
