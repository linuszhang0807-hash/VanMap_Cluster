"""Google Places API provider — Stub for Phase 3 photo/rating enrichment."""

from __future__ import annotations

import os
from typing import Any


class GooglePlacesProvider:
    """Fetch photos, ratings, hours from Google Places API (New)."""

    provider_id = "google_places"

    def is_available(self) -> bool:
        return bool(os.environ.get("GOOGLE_PLACES_API_KEY", "").strip())

    def enrich_place(self, name: str, lat: float, lng: float) -> dict[str, Any]:
        """
        Return optional enrichment: photos[], rating_system, opening_hours.
        Phase 3: implement Places API (New) text search or nearby search.
        """
        if not self.is_available():
            return {}
        if os.environ.get("VIDEO_PROVIDER_DEBUG", "0") == "1":
            print(f"[GooglePlacesProvider] Stub: not implemented for '{name}'")
        return {}
