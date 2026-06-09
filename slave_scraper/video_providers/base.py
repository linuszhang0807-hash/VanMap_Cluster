"""Video provider port — abstract base."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal


@dataclass
class ResolvedVideo:
    platform: Literal["YouTube", "TikTok"]
    url: str
    summary: str
    video_id: str | None = None
    resolved_at: str = field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    source: str = ""

    def to_dict(self) -> dict:
        d: dict = {
            "platform": self.platform,
            "url": self.url,
            "summary": self.summary,
            "resolved_at": self.resolved_at,
            "source": self.source,
        }
        if self.video_id:
            d["video_id"] = self.video_id
        return d


class VideoProviderPort(ABC):
    platform: Literal["YouTube", "TikTok"]

    @property
    @abstractmethod
    def provider_id(self) -> str: ...

    def is_available(self) -> bool:
        return True

    @abstractmethod
    def resolve(self, name: str, category: str, *, address: str | None = None) -> ResolvedVideo | None:
        """Return direct video URL or None. Must NOT return search/index pages."""

    @staticmethod
    def is_direct_url(url: str, platform: str) -> bool:
        u = url.lower()
        if "search" in u or "search_query" in u or "/results?" in u:
            return False
        if platform == "YouTube":
            return "watch?v=" in u or "youtu.be/" in u
        if platform == "TikTok":
            return "/video/" in u or "vm.tiktok.com" in u
        return False
