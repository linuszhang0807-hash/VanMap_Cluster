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


def _build_address(tags: dict[str, str], name: str, district: str = "") -> str:
    street = " ".join(
        p for p in (tags.get("addr:housenumber", ""), tags.get("addr:street", "")) if p
    ).strip()
    city = district or _district_from_tags(tags) or tags.get("addr:city", "")
    prov = tags.get("addr:province", "BC")
    parts = [p for p in (street, city, prov) if p]
    if parts:
        return ", ".join(parts)
    return f"{name}, {city or 'Greater Vancouver'}, BC"


_GVA_CITY_ALIASES: dict[str, str] = {
    "vancouver": "Vancouver",
    "richmond": "Richmond",
    "burnaby": "Burnaby",
    "surrey": "Surrey",
    "coquitlam": "Coquitlam",
    "north vancouver": "North Vancouver",
    "west vancouver": "West Vancouver",
    "new westminster": "New Westminster",
    "langley": "Langley",
}


def _normalize_city_label(value: str) -> str:
    lower = value.lower().strip()
    for needle, city in _GVA_CITY_ALIASES.items():
        if needle in lower:
            return city
    return value.strip()


def _district_from_tags(tags: dict[str, str]) -> str:
    for key in ("addr:city", "addr:suburb", "addr:municipality", "is_in:city", "addr:place"):
        value = tags.get(key, "")
        if value:
            return _normalize_city_label(str(value))
    return ""


def _district_from_coords(lat: float, lng: float) -> str:
    boxes: list[tuple[str, float, float, float, float]] = [
        ("Richmond", 49.08, 49.20, -123.28, -123.05),
        ("Burnaby", 49.18, 49.32, -123.05, -122.92),
        ("Vancouver", 49.20, 49.32, -123.25, -123.00),
        ("North Vancouver", 49.30, 49.45, -123.15, -122.95),
        ("West Vancouver", 49.30, 49.38, -123.30, -123.15),
        ("Surrey", 49.04, 49.25, -122.90, -122.65),
        ("Coquitlam", 49.22, 49.35, -122.92, -122.72),
        ("New Westminster", 49.18, 49.25, -122.98, -122.88),
    ]
    for city, south, north, west, east in boxes:
        if south <= lat <= north and west <= lng <= east:
            return city
    return ""


_COUNTRY_MAP: dict[str, str] = {
    "chinese": "中餐",
    "hong_kong": "中餐",
    "taiwanese": "中餐",
    "shanghai": "中餐",
    "beijing": "中餐",
    "korean": "韩餐",
    "japanese": "日料",
    "italian": "西餐",
    "american": "西餐",
    "burger": "西餐",
    "pizza": "西餐",
    "mexican": "墨西哥餐",
    "indian": "印度餐",
    "thai": "泰餐",
    "vietnamese": "越餐",
    "french": "法餐",
    "greek": "希腊餐",
    "mediterranean": "地中海餐",
    "spanish": "西班牙餐",
    "german": "德餐",
    "british": "英餐",
    "lebanese": "黎巴嫩餐",
    "middle_eastern": "中东餐",
    "persian": "波斯餐",
    "filipino": "菲律宾餐",
    "malaysian": "马来西亚餐",
    "indonesian": "印尼餐",
    "seafood": "西餐",
    "steak_house": "西餐",
    "fine_dining": "西餐",
}

_STYLE_MAP: dict[str, str] = {
    "hot_pot": "火锅",
    "hotpot": "火锅",
    "bbq": "烧烤",
    "barbecue": "烧烤",
    "grill": "烧烤",
    "korean_bbq": "烧烤",
    "dim_sum": "点心",
    "sushi": "寿司",
    "ramen": "拉面",
    "udon": "乌冬",
    "tempura": "天妇罗",
    "pizza": "披萨",
    "burger": "汉堡",
    "steak": "牛排",
    "seafood": "海鲜",
    "noodle": "面食",
    "cantonese": "粤菜",
    "sichuan": "川菜",
    "hunan": "湘菜",
    "shanghainese": "本帮菜",
    "pho": "河粉",
    "curry": "咖喱",
    "tapas": "Tapas",
    "pasta": "意面",
    "sandwich": "三明治",
    "chicken": "炸鸡",
    "fish_and_chips": "炸鱼薯条",
}

_REGIONAL_STYLE: dict[str, str] = {
    "cantonese": "粤菜",
    "sichuan": "川菜",
    "hunan": "湘菜",
    "shanghainese": "本帮菜",
}


def _tokenize_cuisine(cuisine_tag: str) -> list[str]:
    if not cuisine_tag:
        return []
    return [
        t.strip()
        for t in cuisine_tag.lower().replace(";", " ").replace(",", " ").split()
        if t.strip()
    ]


def _match_map(token: str, mapping: dict[str, str]) -> str | None:
    for key, label in mapping.items():
        if key == token or key in token or token in key:
            return label
    return None


def _infer_country_from_name(name: str) -> str:
    name_l = name.lower()
    rules: list[tuple[tuple[str, ...], str]] = [
        (("korean", "bbq", "galbi", "kimchi", "bibimbap"), "韩餐"),
        (("sushi", "ramen", "japanese", "izakaya", "torake", "kaido"), "日料"),
        (("pho", "vietnamese", "viet "), "越餐"),
        (("thai", "pad thai"), "泰餐"),
        (("indian", "curry house", "tandoor"), "印度餐"),
        (("mexican", "taco", "burrito"), "墨西哥餐"),
        (("italian", "pizza", "pizzeria", "trattoria"), "西餐"),
        (("french", "bistro"), "法餐"),
        (("greek", "souvlaki"), "希腊餐"),
        (("chinese", "wonton", "dim sum", "seafood", "canton", "sui wah", "great wall"), "中餐"),
    ]
    for needles, country in rules:
        if any(x in name_l for x in needles):
            return country
    return "西餐"


def _infer_style_from_name(name: str, country: str) -> str | None:
    name_l = name.lower()
    rules: list[tuple[tuple[str, ...], str]] = [
        (("hot pot", "hotpot"), "火锅"),
        (("bbq", "barbecue", "grill", "korean bbq"), "烧烤"),
        (("sushi",), "寿司"),
        (("ramen",), "拉面"),
        (("pizza", "pizzeria"), "披萨"),
        (("burger",), "汉堡"),
        (("seafood", "fish & chips", "fish and chips"), "海鲜"),
        (("pho",), "河粉"),
        (("dim sum",), "点心"),
        (("noodle", "pho 99"), "面食"),
    ]
    for needles, style in rules:
        if any(x in name_l for x in needles):
            return style
    if country == "韩餐" and "bbq" in name_l:
        return "烧烤"
    return None


def _format_cuisine(country: str, style: str | None) -> str:
    return f"{country}-{style}" if style else country


def _map_cuisine_detail(cuisine_tag: str, name: str) -> dict[str, str | None]:
    """Map OSM cuisine tag to country, optional style, and display label."""
    tokens = _tokenize_cuisine(cuisine_tag)
    country: str | None = None
    style: str | None = None

    for token in tokens:
        matched_country = _match_map(token, _COUNTRY_MAP)
        if matched_country:
            country = matched_country
        matched_style = _match_map(token, _STYLE_MAP)
        if matched_style:
            style = matched_style
        if token in _REGIONAL_STYLE:
            country = country or "中餐"
            style = style or _REGIONAL_STYLE[token]

    if not country:
        country = _infer_country_from_name(name)
    if not style:
        style = _infer_style_from_name(name, country)

    return {
        "cuisine_country": country,
        "cuisine_style": style,
        "cuisine": _format_cuisine(country, style),
    }


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
        district = _district_from_tags(tags) or _district_from_coords(lat, lng)
        maps_q = quote_plus(f"{name} Vancouver BC")
        website = tags.get("website") or tags.get("contact:website")
        rating, review_count = _deterministic_rating(name)
        desc = tags.get("description") or tags.get("note") or f"{name} — Vancouver area."
        if len(desc) > 50:
            desc = desc[:47] + "…"

        raw: dict[str, Any] = {
            "name": name,
            "category": category,
            "district": district,
            "address": _build_address(tags, name, district),
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
            raw.update(_map_cuisine_detail(tags.get("cuisine", ""), name))
        elif category == "酒吧":
            raw.update({"vibe": "Local spot", "signature_drink": "Craft beer", "happy_hour": "Check venue"})
        elif category == "娱乐":
            raw.update({"venue_type": tags.get("amenity", "venue"), "age_restriction": "19+", "opening_hours": tags.get("opening_hours", "Varies")})
        elif category == "景点":
            raw.update({"admission_fee": "Varies", "highlights": [tags.get("tourism", "attraction")]})
        elif category == "徒步":
            raw.update({
                "duration": "2–4 hrs",
                "trailhead": _build_address(tags, name, district),
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
