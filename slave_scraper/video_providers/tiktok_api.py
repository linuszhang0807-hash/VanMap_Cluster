"""TikTok API provider — Stub for Phase 3; interface ready for implementation."""

from __future__ import annotations

import os

from .base import ResolvedVideo, VideoProviderPort


class TikTokApiProvider(VideoProviderPort):
    platform = "TikTok"

    @property
    def provider_id(self) -> str:
        return "tiktok_api"

    def is_available(self) -> bool:
        return bool(os.environ.get("TIKTOK_API_KEY", "").strip())

    def resolve(self, name: str, category: str, *, address: str | None = None) -> ResolvedVideo | None:
        if not self.is_available():
            return None
        # Phase 3: implement official/compliant TikTok search here.
        # Signature and return type must match production provider.
        if os.environ.get("VIDEO_PROVIDER_DEBUG", "0") == "1":
            print(f"[TikTokApiProvider] Stub: API key set but resolve() not implemented for '{name}'")
        return None
