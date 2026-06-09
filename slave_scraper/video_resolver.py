"""Orchestrate video resolution across providers with file cache."""

from __future__ import annotations

import json
import os
from typing import Any

from paths import VIDEO_CACHE_FILE
from video_providers import chain_for_platform, get_provider
from video_providers.base import ResolvedVideo, VideoProviderPort


def _load_cache() -> dict[str, Any]:
    if not VIDEO_CACHE_FILE.exists():
        return {}
    try:
        with open(VIDEO_CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_cache(cache: dict[str, Any]) -> None:
    VIDEO_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(VIDEO_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def _cache_key(platform: str, name: str) -> str:
    return f"{platform}:{name.strip().lower()}"


def _resolve_platform(name: str, category: str, platform: str) -> ResolvedVideo | None:
    cache = _load_cache()
    key = _cache_key(platform, name)
    if key in cache:
        hit = cache[key]
        if hit is None:
            return None
        return ResolvedVideo(
            platform=platform,  # type: ignore[arg-type]
            url=hit["url"],
            summary=hit.get("summary", ""),
            video_id=hit.get("video_id"),
            resolved_at=hit.get("resolved_at", ""),
            source=hit.get("source", "cache"),
        )

    for provider_id in chain_for_platform(platform):
        provider = get_provider(provider_id)
        if provider is None or not provider.is_available():
            if os.environ.get("VIDEO_PROVIDER_DEBUG") == "1":
                print(f"[video_resolver] skip {provider_id} (unavailable)")
            continue
        if provider.platform != platform and provider_id != "manual_override":
            continue
        result = provider.resolve(name, category)
        if result and VideoProviderPort.is_direct_url(result.url, platform):
            cache[key] = result.to_dict()
            _save_cache(cache)
            return result

    cache[key] = None
    _save_cache(cache)
    return None


def resolve_videos(name: str, category: str) -> list[dict]:
    """Return list of VideoClip dicts with direct URLs only."""
    videos: list[dict] = []
    for platform in ("YouTube", "TikTok"):
        resolved = _resolve_platform(name, category, platform)
        if resolved:
            videos.append(resolved.to_dict())
    return videos


def reject_search_urls(videos: list[dict]) -> list[dict]:
    """Filter out any search-page URLs (CI guard)."""
    clean: list[dict] = []
    for v in videos:
        platform = v.get("platform", "")
        url = v.get("url", "")
        if VideoProviderPort.is_direct_url(url, platform):
            clean.append(v)
    return clean
