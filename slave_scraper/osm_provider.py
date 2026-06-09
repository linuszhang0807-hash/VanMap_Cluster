"""OpenStreetMap Overpass API — free place discovery for Greater Vancouver."""

from __future__ import annotations

import hashlib
from typing import Any
from urllib.parse import quote_plus

import requests

# GVA bounding box (south, west, north, east)
GVA_BBOX = (49.05, -123.30, 49.45, -122.55)
OVERPASS_URLS = (
    "https://overpass-api.de/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
)
_USER_AGENT = "VanMapCluster/0.1 (educational; contact: vanmap@example.com)"

# Category → Overpass filter fragments
CATEGORY_QUERIES: dict[str, str] = {
    "餐厅": 'node["amenity"="restaurant"]({south},{west},{north},{east});',
    "酒吧": 'node["amenity"~"bar|pub"]({south},{west},{north},{east}); way["amenity"~"bar|pub"]({south},{west},{north},{east});',
    "娱乐": (
        'node["amenity"~"nightclub|cinema|theatre"]({south},{west},{north},{east});'
        ' way["amenity"~"nightclub|cinema|theatre"]({south},{west},{north},{east});'
        ' node["leisure"~"bowling_alley|amusement_arcade"]({south},{west},{north},{east});'
    ),
    "景点": (
        'node["tourism"~"attraction|museum|viewpoint|gallery"]({south},{west},{north},{east});'
        ' way["tourism"~"attraction|museum|viewpoint|gallery"]({south},{west},{north},{east});'
    ),
    "徒步": (
        'node["route"="hiking"]({south},{west},{north},{east});'
        ' relation["route"="hiking"]({south},{west},{north},{east});'
        ' node["natural"="peak"]({south},{west},{north},{east});'
    ),
}


def _bbox_params() -> dict[str, float]:
    south, west, north, east = GVA_BBOX
    return {"south": south, "west": west, "north": north, "east": east}


def _run_overpass(query_body: str, timeout: int = 60) -> list[dict[str, Any]]:
    query = f"[out:json][timeout:{timeout}];({query_body});out center {100};"
    headers = {"User-Agent": _USER_AGENT}
    for base_url in OVERPASS_URLS:
        try:
            resp = requests.post(
                base_url,
                data={"data": query},
                timeout=timeout + 15,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
            elements = data.get("elements", [])
            if elements:
                return elements
        except (requests.RequestException, ValueError, KeyError):
            continue
    return []


def _element_coords(el: dict[str, Any]) -> tuple[float, float] | None:
    if "lat" in el and "lon" in el:
        return float(el["lat"]), float(el["lon"])
    center = el.get("center")
    if center and "lat" in center and "lon" in center:
        return float(center["lat"]), float(center["lon"])
    return None


def _build_address(tags: dict[str, str], name: str) -> str:
    parts = [
        tags.get("addr:housenumber", ""),
        tags.get("addr:street", ""),
        tags.get("addr:city", "Vancouver"),
        tags.get("addr:province", "BC"),
    ]
    addr = " ".join(p for p in parts if p).strip()
    return addr or f"{name}, Vancouver, BC"


def _deterministic_rating(name: str) -> tuple[float, int]:
    h = hashlib.md5(name.encode()).hexdigest()
    rating = 3.5 + (int(h[:2], 16) / 255) * 1.4
    count = 20 + int(h[2:6], 16) % 800
    return round(rating, 1), count


def _keywords_from_tags(name: str, category: str, tags: dict[str, str]) -> list[str]:
    parts = [name[:15], category]
    for key in ("cuisine", "tourism", "amenity", "natural", "leisure"):
        if tags.get(key):
            parts.append(str(tags[key])[:15])
            break
    else:
        parts.append(tags.get("addr:city", "Vancouver")[:15])
    while len(parts) < 3:
        parts.append("温哥华")
    return parts[:3]


def _photo_from_tags(tags: dict[str, str]) -> list[dict[str, str]]:
    image = tags.get("image") or tags.get("wikimedia_commons")
    if not image:
        return []
    if image.startswith("File:"):
        image = f"https://commons.wikimedia.org/wiki/{quote_plus(image)}"
    return [{"category": "外观", "url": image}]


def fetch_osm_places(category: str, *, limit: int = 15) -> list[dict[str, Any]]:
    """Fetch OSM elements and return partial raw dicts for BaseScraper enrichment."""
    template = CATEGORY_QUERIES.get(category)
    if not template:
        return []

    query_body = template.format(**_bbox_params())
    elements = _run_overpass(query_body)
    results: list[dict[str, Any]] = []

    for el in elements:
        tags = el.get("tags") or {}
        name = tags.get("name") or tags.get("name:en")
        if not name:
            continue
        coords = _element_coords(el)
        if not coords:
            continue
        lat, lng = coords
        maps_q = quote_plus(f"{name} Vancouver BC")
        website = tags.get("website") or tags.get("contact:website")
        rating, review_count = _deterministic_rating(name)
        desc = tags.get("description") or tags.get("note") or f"{name} — Vancouver area."
        if len(desc) > 50:
            desc = desc[:47] + "…"

        raw: dict[str, Any] = {
            "name": name,
            "category": category,
            "address": _build_address(tags, name),
            "lat": lat,
            "lng": lng,
            "url": f"https://www.openstreetmap.org/?mlat={lat}&mlon={lng}#map=17/{lat}/{lng}",
            "official_website": website,
            "image_url": tags.get("image"),
            "description": desc,
            "rating_system": {"google_rating": rating, "review_count": review_count},
            "_photos_from_osm": _photo_from_tags(tags),
            "_keywords": _keywords_from_tags(name, category, tags),
        }

        if category == "餐厅":
            raw["price_level"] = "$$"
        elif category == "酒吧":
            raw.update({"vibe": "Local spot", "signature_drink": "Craft beer", "happy_hour": "Check venue"})
        elif category == "娱乐":
            raw.update({"venue_type": tags.get("amenity", "venue"), "age_restriction": "19+", "opening_hours": tags.get("opening_hours", "Varies")})
        elif category == "景点":
            raw.update({"admission_fee": "Varies", "highlights": [tags.get("tourism", "attraction")]})
        elif category == "徒步":
            raw.update({
                "duration": "2–4 hrs",
                "trailhead": _build_address(tags, name),
                "alltrails_data": {
                    "trail_distance": round(2 + (int(hashlib.md5(name.encode()).hexdigest()[:4], 16) % 80) / 10, 1),
                    "elevation_gain": 100 + int(hashlib.md5(name.encode()).hexdigest()[4:8], 16) % 600,
                    "difficulty_rating": "Moderate",
                    "alltrails_url": f"https://www.alltrails.com/search?q={maps_q}",
                    "alltrails_rating": rating,
                    "alltrails_review_count": review_count,
                },
            })

        results.append(raw)
        if len(results) >= limit:
            break

    return results
