"""Nominatim geocoding with local file cache (1 req/s rate limit)."""

from __future__ import annotations

import json
import time
from typing import Any

import requests

from paths import GEOCODE_CACHE_FILE

_NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
_NOMINATIM_REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
_USER_AGENT = "VanMapCluster/0.1 (local dev; contact: vanmap@example.com)"
_LAST_REQUEST = 0.0

_GVA_CITIES = (
    "North Vancouver",
    "West Vancouver",
    "New Westminster",
    "Vancouver",
    "Richmond",
    "Burnaby",
    "Surrey",
    "Coquitlam",
    "Langley",
)


def _load_cache() -> dict[str, Any]:
    if not GEOCODE_CACHE_FILE.exists():
        return {}
    try:
        with open(GEOCODE_CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_cache(cache: dict[str, Any]) -> None:
    GEOCODE_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(GEOCODE_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def _rate_limit() -> None:
    global _LAST_REQUEST
    elapsed = time.monotonic() - _LAST_REQUEST
    if elapsed < 1.05:
        time.sleep(1.05 - elapsed)
    _LAST_REQUEST = time.monotonic()


def geocode(query: str, *, region: str = "Greater Vancouver, BC, Canada") -> tuple[float, float] | None:
    """Return (lat, lng) for a free-text address or venue name."""
    key = f"{query}|{region}".strip().lower()
    cache = _load_cache()
    if key in cache:
        hit = cache[key]
        if hit is None:
            return None
        return float(hit["lat"]), float(hit["lng"])

    _rate_limit()
    params = {
        "q": f"{query}, {region}",
        "format": "json",
        "limit": 1,
    }
    headers = {"User-Agent": _USER_AGENT}
    try:
        resp = requests.get(_NOMINATIM_SEARCH_URL, params=params, headers=headers, timeout=15)
        resp.raise_for_status()
        results = resp.json()
        if not results:
            cache[key] = None
            _save_cache(cache)
            return None
        lat = float(results[0]["lat"])
        lng = float(results[0]["lon"])
        cache[key] = {"lat": lat, "lng": lng}
        _save_cache(cache)
        return lat, lng
    except (requests.RequestException, KeyError, ValueError, TypeError):
        cache[key] = None
        _save_cache(cache)
        return None


def district_from_address(address: str) -> str:
    """Extract a known GVA city name from a free-text address."""
    if not address:
        return ""
    lower = address.lower()
    for city in _GVA_CITIES:
        if city.lower() in lower:
            return city
    return ""


def reverse_geocode_district(lat: float, lng: float) -> str | None:
    """Reverse-geocode coordinates to a GVA district name (cached)."""
    key = f"rev:{round(lat, 4)},{round(lng, 4)}"
    cache = _load_cache()
    if key in cache:
        hit = cache[key]
        return None if hit is None else str(hit.get("district") or "")

    _rate_limit()
    params = {
        "lat": lat,
        "lon": lng,
        "format": "json",
        "zoom": 14,
        "addressdetails": 1,
    }
    headers = {"User-Agent": _USER_AGENT}
    try:
        resp = requests.get(_NOMINATIM_REVERSE_URL, params=params, headers=headers, timeout=15)
        resp.raise_for_status()
        payload = resp.json()
        addr = payload.get("address") or {}
        for field in ("city", "town", "municipality", "suburb", "county"):
            value = addr.get(field)
            if not value:
                continue
            matched = district_from_address(str(value))
            if matched:
                cache[key] = {"district": matched}
                _save_cache(cache)
                return matched
        display = payload.get("display_name", "")
        matched = district_from_address(display)
        cache[key] = {"district": matched} if matched else None
        _save_cache(cache)
        return matched or None
    except (requests.RequestException, KeyError, ValueError, TypeError):
        cache[key] = None
        _save_cache(cache)
        return None
