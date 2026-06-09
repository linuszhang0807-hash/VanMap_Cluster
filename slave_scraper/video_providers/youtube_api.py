"""YouTube Data API v3 — resolve direct watch URLs."""

from __future__ import annotations

import os
from urllib.parse import quote_plus

import requests

from .base import ResolvedVideo, VideoProviderPort


class YouTubeApiProvider(VideoProviderPort):
    platform = "YouTube"

    @property
    def provider_id(self) -> str:
        return "youtube_api"

    def is_available(self) -> bool:
        return bool(os.environ.get("YOUTUBE_API_KEY", "").strip())

    def resolve(self, name: str, category: str, *, address: str | None = None) -> ResolvedVideo | None:
        api_key = os.environ.get("YOUTUBE_API_KEY", "").strip()
        if not api_key:
            return None
        q = quote_plus(f"{name} {category} Vancouver")
        url = "https://www.googleapis.com/youtube/v3/search"
        params = {
            "part": "snippet",
            "q": q,
            "type": "video",
            "maxResults": 1,
            "key": api_key,
        }
        try:
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            items = resp.json().get("items", [])
            if not items:
                return None
            vid = items[0]["id"]["videoId"]
            title = items[0]["snippet"].get("title", f"{name} on YouTube")
            watch = f"https://www.youtube.com/watch?v={vid}"
            return ResolvedVideo(
                platform="YouTube",
                url=watch,
                summary=title[:80],
                video_id=vid,
                source=self.provider_id,
            )
        except (requests.RequestException, KeyError, TypeError):
            return None
