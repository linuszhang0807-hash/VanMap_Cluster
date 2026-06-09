"""
Vancouver Events Intelligence Scraper — v1.0
--------------------------------------------
Slave Scraper Module — VanMap Cluster

Sources
  · https://www.destinationvancouver.com/  (Tourism Vancouver events calendar)
  · https://dailyhive.com/vancouver         (Daily Hive Vancouver events roundup)

Architecture
  · Real HTTP requests with BeautifulSoup4 parsing (graceful fallback to MOCK data
    when bs4 is unavailable, the site is unreachable, or HTML structure has changed)
  · Fingerprint deduplication: MD5(normalised_name + date + location) as unique ID;
    cross-source duplicates are merged — longest description is kept, source list merged
  · Output schema mirrors master_data.json exactly for frontend component reuse

Output: data/events_data.json
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote_plus

import requests
from pydantic import BaseModel, Field, computed_field

# ---------------------------------------------------------------------------
# Optional: BeautifulSoup4 for real HTML scraping
# ---------------------------------------------------------------------------
try:
    from bs4 import BeautifulSoup
    _BS4_AVAILABLE = True
except ImportError:
    BeautifulSoup = None          # type: ignore[assignment,misc]
    _BS4_AVAILABLE = False


# ===========================================================================
# SECTION 1 — Pydantic Models  (schema-compatible with master_data.json)
# ===========================================================================

class VideoClip(BaseModel):
    platform: str   # "YouTube" | "TikTok"
    url: str
    summary: str


class PlatformReview(BaseModel):
    platform: str   # "Google Review" | "小红书"
    text: str
    source_url: str


class SocialMetrics(BaseModel):
    """Universal social block — identical schema to master_data.json."""
    videos: list[VideoClip]
    reviews: list[PlatformReview]
    keywords: list[str] = Field(min_length=3)
    social_buzz_score: float = Field(ge=0.0, le=5.0)


class RatingSystem(BaseModel):
    """Universal rating block — identical schema to master_data.json."""
    google_rating: float = Field(ge=0.0, le=5.0)
    review_count: int = Field(ge=0)

    @computed_field
    @property
    def aggregate_score(self) -> float:
        """Bayesian-smoothed score (same formula as master_data.json)."""
        weight = min(self.review_count / 500, 1.0)
        return round(self.google_rating * weight + 3.5 * (1.0 - weight), 2)


class EventEntry(BaseModel):
    """
    Event entry — fully schema-compatible with master_data.json BaseEntry.

    Mandatory top-level fields (name / category / address / lat / lng / url /
    official_website / image_url / description / social_metrics / rating_system /
    rating / videos / reviews) are identical to BaseEntry so the frontend can
    render events with the same component as places.

    Event-specific extras (event_date, venue_name, ticket_price, …) are
    additive and do not break existing renderers.
    """

    # ── BaseEntry-compatible fields ─────────────────────────────────────────
    name: str                             # event name (shown on map marker)
    category: str = "活动"
    address: str                          # venue full address
    lat: float = Field(ge=49.0, le=49.8)
    lng: float = Field(ge=-123.5, le=-122.3)
    url: str                              # canonical event detail page
    official_website: str | None = None
    image_url: str | None = None          # event poster / hero image
    description: str | None = Field(default=None, max_length=50)  # map-popup text
    social_metrics: SocialMetrics
    rating_system: RatingSystem

    # ── Event-specific extras ────────────────────────────────────────────────
    event_date: str                       # e.g. "2026-07-26" or "Jul 26 – Aug 8, 2026"
    event_time: str | None = None         # e.g. "10:00 AM – 11:00 PM"
    venue_name: str | None = None         # human-readable venue name
    ticket_price: str | None = None       # e.g. "Free" / "CAD $25–$120"
    long_description: str | None = None   # full event description (no length limit)
    source: list[str] = Field(default_factory=list)   # which sites contributed data
    fingerprint: str = ""                 # MD5 dedup key — populated post-collection

    # ── Computed mirror fields (frontend shortcut, same as BaseEntry) ────────
    @computed_field
    @property
    def rating(self) -> float:
        return self.rating_system.google_rating

    @computed_field
    @property
    def videos(self) -> list[VideoClip]:
        return self.social_metrics.videos if self.social_metrics else []

    @computed_field
    @property
    def reviews(self) -> list[PlatformReview]:
        return self.social_metrics.reviews if self.social_metrics else []


# ===========================================================================
# SECTION 2 — Utility Functions
# ===========================================================================

def make_fingerprint(name: str, date: str, location: str) -> str:
    """
    Deduplication fingerprint: MD5 of (normalised_name | date | normalised_location).

    Normalisation rules are deliberately aggressive so that the same event
    listed on two sites with slightly different address wording still matches:
      · lowercase + collapse whitespace
      · strip year tokens  ("Jazz Festival 2026" → "jazz festival")
      · strip Canadian postal codes  (V6B 1X2 → "")
      · strip province abbreviation  ("BC" → "")
      · strip implied city names     ("Vancouver", "Richmond", "Burnaby")
      · keep only the first meaningful address segment (venue/neighbourhood name)
        so "English Bay Beach, Vancouver, BC V6E" and
           "English Bay Beach, Vancouver, BC"  both → "english bay beach"
    """
    def norm(s: str) -> str:
        s = s.lower().strip()
        s = re.sub(r"\b20\d{2}\b", "", s)          # strip year
        s = re.sub(r"\s+", " ", s).strip()
        return s

    def norm_loc(s: str) -> str:
        s = s.lower()
        s = re.sub(r"\b[a-z]\d[a-z]\s?\d[a-z]\d\b", "", s)   # Canadian postal code
        s = re.sub(r"\b(bc|ab|on|qc|ns|nb|mb|sk)\b", "", s)   # province
        s = re.sub(r"\b(vancouver|richmond|burnaby|north vancouver|"
                   r"west vancouver|surrey|coquitlam)\b", "", s)
        s = re.sub(r",\s*,+", ",", s)              # collapse empty segments
        s = re.sub(r"\s+", " ", s).strip().strip(",").strip()
        # Keep only the first non-empty segment (venue / area name)
        parts = [p.strip() for p in s.split(",") if p.strip()]
        return parts[0] if parts else s

    raw = f"{norm(name)}|{norm(date)}|{norm_loc(location)}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]


def _det_float(seed: str, lo: float, hi: float) -> float:
    """Deterministic float in [lo, hi] from MD5 seed — reproducible across runs."""
    h = int(hashlib.md5(seed.encode()).hexdigest()[:8], 16)
    return round(lo + (h / 0xFFFFFFFF) * (hi - lo), 1)


def _det_int(seed: str, lo: int, hi: int) -> int:
    """Deterministic int in [lo, hi) from MD5 seed."""
    h = int(hashlib.md5((seed + "_cnt").encode()).hexdigest()[:6], 16)
    return lo + (h % (hi - lo))


def build_social_metrics(name: str, keywords: list[str], review_texts: list[dict]) -> dict:
    """Construct social_metrics with direct video links via video_resolver port."""
    buzz = _det_float(name, 3.8, 4.9)
    try:
        from video_resolver import resolve_videos
        videos = resolve_videos(name, "活动")
    except ImportError:
        videos = []
    return {
        "videos": videos,
        "reviews": review_texts,
        "keywords": keywords,
        "social_buzz_score": buzz,
    }


# ===========================================================================
# SECTION 3 — Mock Data Banks
# ===========================================================================
#
# MOCK events are used when:
#   · BeautifulSoup4 is not installed
#   · The target site is unreachable / returns non-200
#   · The HTML structure no longer matches the selectors (site redesign)
#
# Dataset: 5 events from each source, with 2 intentional cross-source duplicates
# to demonstrate the fingerprint-dedup + merge pipeline.
#
# Duplicate pairs (same fingerprint → merge):
#   "Celebration of Light"          (both sites)
#   "Vancouver International Jazz Festival"  (both sites)
# ---------------------------------------------------------------------------

_MOCK_DV: list[dict] = [
    # DV-1 ── Jazz Festival (will be merged with DH-1)
    {
        "name": "Vancouver International Jazz Festival",
        "event_date": "2026-06-19",
        "event_time": "Noon – Midnight (varies by venue)",
        "address": "Various Venues, Downtown Vancouver, BC V6B",
        "venue_name": "David Lam Park, Roundhouse, Orpheum & More",
        "lat": 49.2727, "lng": -123.1209,
        "url": "https://coastaljazz.ca/",
        "official_website": "https://coastaljazz.ca/",
        "image_url": "https://coastaljazz.ca/wp-content/uploads/2026/03/vjf2026-hero.jpg",
        "description": "年度爵士盛典，Downtown 多场地免费与售票演出并举。",
        "long_description": (
            "Vancouver's premier jazz festival returns for its 40th edition, "
            "spanning 10 days across 40+ venues. Over 1,800 musicians from 25 countries "
            "perform across free outdoor stages at David Lam Park and ticketed headline "
            "shows at the Orpheum and the Roundhouse. Genres range from traditional jazz "
            "to Afrobeat, Latin jazz, and experimental improvisation."
        ),
        "ticket_price": "Free (outdoor) – CAD $120 (headline shows)",
        "keywords": ["年度爵士盛典", "免费户外演出", "多国音乐人"],
        "rating_system": {"google_rating": 4.8, "review_count": 3200},
        "_reviews": [
            {"platform": "Google Review", "text": "One of the best free outdoor festivals in North America. The David Lam Park stage had incredible energy — world-class musicians in a beautiful setting.", "source_url": "https://www.google.com/maps/search/?api=1&query=Vancouver+Jazz+Festival"},
            {"platform": "小红书", "text": "免费户外舞台堪称温哥华夏天最划算的活动！David Lam Park 草地躺着看顶级爵士演出，氛围太治愈了！", "source_url": "https://www.xiaohongshu.com/search_result?keyword=温哥华爵士音乐节"},
        ],
        "source": ["destinationvancouver.com"],
    },
    # DV-2 ── Celebration of Light (will be merged with DH-2)
    {
        "name": "Celebration of Light",
        "event_date": "2026-07-25",
        "event_time": "10:00 PM fireworks (gates open 5:00 PM)",
        "address": "English Bay Beach, Vancouver, BC V6E 1V6",
        "venue_name": "English Bay Beach",
        "lat": 49.2871, "lng": -123.1455,
        "url": "https://hondacelebrationoflight.com/",
        "official_website": "https://hondacelebrationoflight.com/",
        "image_url": "https://hondacelebrationoflight.com/wp-content/uploads/2026/01/col2026-banner.jpg",
        "description": "英吉利湾年度国际烟花大赛，三国轮番绽放夏夜。",
        "long_description": (
            "The Honda Celebration of Light is Canada's largest offshore fireworks competition. "
            "Teams from three countries compete across three nights (Jul 25, Aug 1, Aug 8, 2026), "
            "each delivering a 25-minute choreographed show set to music over English Bay. "
            "Over 300,000 spectators gather along the Stanley Park seawall and Kitsilano Beach."
        ),
        "ticket_price": "Free (public beach) – CAD $50 (premium viewing areas)",
        "keywords": ["国际烟花大赛", "英吉利湾夏夜", "三国烟火对决"],
        "rating_system": {"google_rating": 4.9, "review_count": 8700},
        "_reviews": [
            {"platform": "Google Review", "text": "Absolutely spectacular. The music-synchronised fireworks over English Bay are breathtaking. Arrive early to claim your spot on the seawall — worth every minute of the wait.", "source_url": "https://www.google.com/maps/search/?api=1&query=Celebration+of+Light+Vancouver"},
            {"platform": "小红书", "text": "英吉利湾三场烟花🎆简直是温哥华夏天的巅峰！配乐烟火同步太震撼了，提前两小时占位，带上毯子和零食，完美夜晚！", "source_url": "https://www.xiaohongshu.com/search_result?keyword=温哥华烟花+Celebration+of+Light"},
        ],
        "source": ["destinationvancouver.com"],
    },
    # DV-3 ── Folk Music Festival
    {
        "name": "Vancouver Folk Music Festival",
        "event_date": "2026-07-17",
        "event_time": "Noon – 10:30 PM (Fri); 10:00 AM – 10:30 PM (Sat-Sun)",
        "address": "Jericho Beach Park, Vancouver, BC V6R 4K1",
        "venue_name": "Jericho Beach Park",
        "lat": 49.2743, "lng": -123.1989,
        "url": "https://thefestival.bc.ca/",
        "official_website": "https://thefestival.bc.ca/",
        "image_url": "https://thefestival.bc.ca/wp-content/uploads/2026/04/vfmf2026-hero.jpg",
        "description": "Jericho 海滩三日民谣盛宴，山海背景下的世界音乐节。",
        "long_description": (
            "The Vancouver Folk Music Festival is a beloved 3-day outdoor music celebration "
            "set against the stunning backdrop of Jericho Beach, with the North Shore mountains "
            "and ocean as the stage backdrop. The 2026 edition features 60+ artists across 8 stages, "
            "spanning folk, world music, roots, blues, and storytelling. "
            "The workshop stage format — where artists collaborate live — is unique to this festival."
        ),
        "ticket_price": "CAD $65 (day) – $175 (weekend pass)",
        "keywords": ["海滩民谣音乐节", "世界音乐工坊", "Jericho户外舞台"],
        "rating_system": {"google_rating": 4.7, "review_count": 1850},
        "_reviews": [
            {"platform": "Google Review", "text": "The workshop stages are what make this festival unique — watching artists from different genres collaborate spontaneously is magical. One of Vancouver's best summer traditions.", "source_url": "https://www.google.com/maps/search/?api=1&query=Vancouver+Folk+Music+Festival+Jericho+Beach"},
            {"platform": "小红书", "text": "Jericho 海滩背对北温群山看民谣演出，这辈子没见过这么美的音乐节场景！工坊舞台的跨界合作超惊喜，强烈推荐！", "source_url": "https://www.xiaohongshu.com/search_result?keyword=温哥华民谣音乐节+Folk"},
        ],
        "source": ["destinationvancouver.com"],
    },
    # DV-4 ── Pride Week
    {
        "name": "Vancouver Pride Week 2026",
        "event_date": "2026-07-31",
        "event_time": "Events throughout the week; Parade: Aug 2, 12:00 PM",
        "address": "Robson Square & West End, Vancouver, BC V6Z",
        "venue_name": "Robson Square, Davie Village & English Bay",
        "lat": 49.2820, "lng": -123.1215,
        "url": "https://vancouverpride.ca/",
        "official_website": "https://vancouverpride.ca/",
        "image_url": "https://vancouverpride.ca/wp-content/uploads/2026/02/pride2026-hero.jpg",
        "description": "温哥华年度骄傲周，游行与百场活动席卷 West End。",
        "long_description": (
            "Vancouver Pride Week 2026 (Jul 31 – Aug 2) is one of Canada's largest LGBTQ+ "
            "celebrations. The week includes more than 100 events: art shows, film screenings, "
            "community gatherings, the Sunset Beach Party, and the iconic Pride Parade on Sunday, "
            "Aug 2 — attracting 650,000+ spectators along Robson and Denman Streets. "
            "The festival celebrates diversity, inclusion, and community across the West End."
        ),
        "ticket_price": "Free (most events) – CAD $30 (ticketed parties)",
        "keywords": ["骄傲游行", "West End彩虹周", "包容多元盛典"],
        "rating_system": {"google_rating": 4.8, "review_count": 5400},
        "_reviews": [
            {"platform": "Google Review", "text": "The Pride Parade is a must-see Vancouver experience — the energy, the costumes, the community spirit along Robson and Denman is genuinely moving and joyful.", "source_url": "https://www.google.com/maps/search/?api=1&query=Vancouver+Pride+Parade"},
            {"platform": "小红书", "text": "骄傲游行从 Robson 走到 Denman 太震撼了！彩虹装束和欢乐氛围让人感受到温哥华最包容的一面，第一次参加就爱上了！", "source_url": "https://www.xiaohongshu.com/search_result?keyword=温哥华骄傲游行+Pride"},
        ],
        "source": ["destinationvancouver.com"],
    },
    # DV-5 ── Khatsahlano
    {
        "name": "Khatsahlano Street Party 2026",
        "event_date": "2026-07-11",
        "event_time": "11:00 AM – 9:00 PM",
        "address": "West 4th Ave, Kitsilano, Vancouver, BC V6K",
        "venue_name": "West 4th Ave (Burrard to MacDonald)",
        "lat": 49.2670, "lng": -123.1719,
        "url": "https://khatsahlano.com/",
        "official_website": "https://khatsahlano.com/",
        "image_url": "https://khatsahlano.com/wp-content/uploads/2026/03/kits2026-hero.jpg",
        "description": "Kitsilano 最大免费街头音乐节，20 个舞台全日无休。",
        "long_description": (
            "Khatsahlano is Vancouver's largest free all-ages street festival, stretching "
            "10 city blocks along West 4th Ave in Kitsilano. The 2026 edition features "
            "20 stages with 100+ live music acts, plus 100+ artisan vendors, local food trucks, "
            "and family activities. Named after Chief Khahtsahlano of the Squamish Nation, "
            "the festival attracts over 100,000 visitors each year."
        ),
        "ticket_price": "Free",
        "keywords": ["免费街头音乐节", "Kitsilano全日派对", "百个本地乐队"],
        "rating_system": {"google_rating": 4.6, "review_count": 2100},
        "_reviews": [
            {"platform": "Google Review", "text": "Best free festival in Vancouver. 20 stages of non-stop music, amazing food trucks and local vendors. Kitsilano comes alive in the best possible way every July.", "source_url": "https://www.google.com/maps/search/?api=1&query=Khatsahlano+Street+Party+Vancouver"},
            {"platform": "小红书", "text": "Kits 街头音乐节太好逛了！20 个舞台全天轮流演出，本地文创摊位和美食车随便逛，最重要的是完全免费！温哥华夏天必去！", "source_url": "https://www.xiaohongshu.com/search_result?keyword=Khatsahlano+Kitsilano+音乐节"},
        ],
        "source": ["destinationvancouver.com"],
    },
]


_MOCK_DH: list[dict] = [
    # DH-1 ── Jazz Festival DUPLICATE (fingerprint will match DV-1)
    # Address normalises to "various venues, downtown" — same as DV listing
    {
        "name": "Vancouver International Jazz Festival",
        "event_date": "2026-06-19",
        "event_time": "Noon onward",
        "address": "Various Venues, Downtown Vancouver, BC",
        "venue_name": "David Lam Park (main outdoor stage)",
        "lat": 49.2727, "lng": -123.1209,
        "url": "https://coastaljazz.ca/schedule",
        "official_website": "https://coastaljazz.ca/",
        "image_url": None,          # poster not available on Daily Hive listing
        "description": "年度爵士盛典，Downtown 多场地免费与售票演出并举。",
        "long_description": (
            "Daily Hive Pick: Don't miss Vancouver's biggest jazz event — "
            "spanning 10 days and 40+ venues, the festival features free stages at "
            "David Lam Park alongside ticketed shows. Perfect for both jazz aficionados "
            "and casual music lovers exploring the Downtown core."
        ),
        "ticket_price": "Free – $120",
        "keywords": ["年度爵士盛典", "免费户外演出", "多国音乐人"],
        "rating_system": {"google_rating": 4.8, "review_count": 3200},
        "_reviews": [
            {"platform": "Google Review", "text": "Free outdoor stages at David Lam Park are a Vancouver summer highlight. The jazz festival transforms the city for 10 amazing days.", "source_url": "https://www.google.com/maps/search/?api=1&query=Vancouver+International+Jazz+Festival"},
            {"platform": "小红书", "text": "爵士节白天 David Lam 免费草坪场超棒，晚上还可以买票进 Orpheum 看压轴演出，十天全都值得！", "source_url": "https://www.xiaohongshu.com/search_result?keyword=Vancouver+Jazz+Festival+2026"},
        ],
        "source": ["dailyhive.com"],
    },
    # DH-2 ── Celebration of Light DUPLICATE (fingerprint will match DV-2)
    {
        "name": "Celebration of Light",
        "event_date": "2026-07-25",
        "event_time": "Fireworks at 10 PM",
        "address": "English Bay Beach, Vancouver, BC",
        "venue_name": "English Bay",
        "lat": 49.2871, "lng": -123.1455,
        "url": "https://hondacelebrationoflight.com/tickets",
        "official_website": "https://hondacelebrationoflight.com/",
        "image_url": "https://hondacelebrationoflight.com/wp-content/uploads/2026/01/col2026-banner.jpg",
        "description": "英吉利湾年度国际烟花大赛，三国轮番绽放夏夜。",
        "long_description": (
            "Daily Hive Guide: Three countries, three nights of world-class fireworks over "
            "English Bay — Jul 25, Aug 1, Aug 8. Grab your blanket and head to the seawall "
            "by 5 PM to secure a good spot. Pro tip: watch from Kitsilano Beach to avoid "
            "the most crowded sections. Live music and food vendors from 6 PM."
        ),
        "ticket_price": "Free (beach access) – $50 (VIP areas)",
        "keywords": ["国际烟花大赛", "英吉利湾夏夜", "三国烟火对决"],
        "rating_system": {"google_rating": 4.9, "review_count": 8700},
        "_reviews": [
            {"platform": "Google Review", "text": "The best free show in Vancouver every summer. English Bay is packed but the atmosphere is electric. Worth the crowded seawall for the most spectacular fireworks you'll ever see.", "source_url": "https://www.google.com/maps/search/?api=1&query=Honda+Celebration+of+Light+Vancouver"},
            {"platform": "小红书", "text": "Celebration of Light 英吉利湾观看攻略：Kitsilano 海滩人相对少但视角超棒！提早到布点，带零食毯子，这是温哥华夏天最完美的夜晚！", "source_url": "https://www.xiaohongshu.com/search_result?keyword=Celebration+of+Light+英吉利湾"},
        ],
        "source": ["dailyhive.com"],
    },
    # DH-3 ── Richmond Night Market (unique to Daily Hive)
    {
        "name": "Richmond Night Market 2026",
        "event_date": "2026-05-02",
        "event_time": "Fri 7–11 PM | Sat-Sun 7 PM – Midnight",
        "address": "8351 River Rd, Richmond, BC V6X 1Y4",
        "venue_name": "Richmond Night Market",
        "lat": 49.1904, "lng": -123.1404,
        "url": "https://richmondnightmarket.com/",
        "official_website": "https://richmondnightmarket.com/",
        "image_url": "https://richmondnightmarket.com/wp-content/uploads/2026/02/rnm2026-hero.jpg",
        "description": "北美最大亚洲夜市，500+ 摊位周末营业至深夜。",
        "long_description": (
            "North America's largest night market runs every Friday through Sunday from "
            "May to October, featuring 500+ vendor stalls with Asian street food, merchandise, "
            "carnival games, and live performances. The 2026 season runs May 2 – Oct 12. "
            "Highlights: bubble tea challenges, stinky tofu, Korean corn dogs, J-pop dance shows, "
            "and an annual Wonton Challenge contest. Free entry; food averaging CAD $4–12 per item."
        ),
        "ticket_price": "Free entry (food at vendor prices)",
        "keywords": ["亚洲夜市文化", "500摊位街头小吃", "周末深夜场"],
        "rating_system": {"google_rating": 4.3, "review_count": 6800},
        "_reviews": [
            {"platform": "Google Review", "text": "The Richmond Night Market is a unique Vancouver experience — hundreds of Asian food stalls, carnival games, and live K-pop performances. Go hungry and bring cash.", "source_url": "https://www.google.com/maps/search/?api=1&query=Richmond+Night+Market"},
            {"platform": "小红书", "text": "列治文夜市真的是必去！臭豆腐、韩式玉米热狗、港式鱼蛋一次满足，摊位超多逛不完，周五晚上人少一点比较舒服！", "source_url": "https://www.xiaohongshu.com/search_result?keyword=列治文夜市+Richmond+Night+Market"},
        ],
        "source": ["dailyhive.com"],
    },
    # DH-4 ── Car Free Day (unique to Daily Hive)
    {
        "name": "Car Free Day Vancouver — Main Street",
        "event_date": "2026-06-21",
        "event_time": "11:00 AM – 7:00 PM",
        "address": "Main St, Vancouver, BC V5T (16th to 30th Ave)",
        "venue_name": "Main Street (16th to 30th Ave)",
        "lat": 49.2508, "lng": -123.1012,
        "url": "https://carfreevancouver.org/",
        "official_website": "https://carfreevancouver.org/",
        "image_url": "https://carfreevancouver.org/wp-content/uploads/2026/01/carfree2026-main.jpg",
        "description": "Main Street 封路派对，本地乐队摊贩与街头艺术全天呈现。",
        "long_description": (
            "Car Free Day transforms Main Street into a pedestrian festival zone for one day, "
            "running from 16th to 30th Ave. The 2026 edition features 6 live music stages, "
            "70+ local artisan and food vendors, face painting, cycling demos, and interactive "
            "art installations. The event celebrates sustainable urban living and neighbourhood "
            "community spirit. Part of a city-wide Car Free Day series on the same weekend "
            "(Commercial Drive, Kitsilano, Main St)."
        ),
        "ticket_price": "Free",
        "keywords": ["Main Street封路嘉年华", "社区文化活动", "可持续城市庆典"],
        "rating_system": {"google_rating": 4.5, "review_count": 980},
        "_reviews": [
            {"platform": "Google Review", "text": "Car Free Day on Main Street is a celebration of everything that makes this neighbourhood great — local shops, art, live music, and community. A perfect Vancouver summer Sunday.", "source_url": "https://www.google.com/maps/search/?api=1&query=Car+Free+Day+Main+Street+Vancouver"},
            {"platform": "小红书", "text": "Main Street 封路节超好逛！本地独立品牌摊位和街头美食让人根本走不动，还有好几个现场音乐舞台，完全免费！", "source_url": "https://www.xiaohongshu.com/search_result?keyword=Car+Free+Day+Vancouver+Main+Street"},
        ],
        "source": ["dailyhive.com"],
    },
    # DH-5 ── PNE (unique to Daily Hive)
    {
        "name": "Pacific National Exhibition (PNE) 2026",
        "event_date": "2026-08-22",
        "event_time": "Daily 11:00 AM – 11:00 PM (weekends to Midnight)",
        "address": "2901 E Hastings St, Vancouver, BC V5K 5J1",
        "venue_name": "Hastings Park / Pacific National Exhibition",
        "lat": 49.2831, "lng": -123.0351,
        "url": "https://www.pne.ca/",
        "official_website": "https://www.pne.ca/",
        "image_url": "https://www.pne.ca/wp-content/uploads/2026/04/pne2026-hero.jpg",
        "description": "PNE 百年嘉年华，游乐设施演唱会与农业展览三合一。",
        "long_description": (
            "The Pacific National Exhibition (PNE) is Vancouver's iconic annual fair, "
            "running Aug 22 – Sep 7, 2026 (Labour Day weekend close). "
            "The fair features over 70 ride attractions including the historic Wooden Roller Coaster, "
            "nightly free concerts on the Rogers stage (past headliners: Shania Twain, The Offspring), "
            "agricultural shows, SuperDogs performances, casino gaming, and 350+ food vendors. "
            "One of Canada's largest annual events, drawing 750,000+ visitors."
        ),
        "ticket_price": "CAD $20 (gate admission) + ride passes from $49",
        "keywords": ["百年嘉年华", "游乐园演唱会", "全家年度盛事"],
        "rating_system": {"google_rating": 4.4, "review_count": 11200},
        "_reviews": [
            {"platform": "Google Review", "text": "The PNE is a Vancouver institution. Free concerts every night, classic fair food (the mini donuts are legendary), and rides for all ages. A summer bucket list must-do.", "source_url": "https://www.google.com/maps/search/?api=1&query=PNE+Pacific+National+Exhibition+Vancouver"},
            {"platform": "小红书", "text": "PNE 嘉年华是温哥华每年必去！小甜甜圈队伍可以排但超值，过山车经典不过时，晚上免费演唱会水准超高，带娃全家出游完美！", "source_url": "https://www.xiaohongshu.com/search_result?keyword=PNE+温哥华+嘉年华"},
        ],
        "source": ["dailyhive.com"],
    },
]


# ===========================================================================
# SECTION 4 — Scrapers
# ===========================================================================

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-CA,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
_TIMEOUT   = 10   # seconds per HTTP request
_RETRY_MAX = 2


class BaseEventScraper(ABC):
    """Abstract scraper — subclasses implement fetch_live() and return the mock bank."""

    source_name: str
    source_url: str

    @classmethod
    @abstractmethod
    def fetch_live(cls) -> list[dict]:
        """Attempt real HTTP scraping. Return list of raw event dicts."""
        ...

    @classmethod
    @abstractmethod
    def mock_data(cls) -> list[dict]:
        """Return the pre-defined mock event bank for this source."""
        ...

    @classmethod
    def fetch(cls) -> list[dict]:
        """
        Dispatch pipeline:
          1. Attempt live scraping.
          2. On any failure (network, parsing, bs4 missing), fall back to mock data.
          3. Attach `source` tag to every record.
        """
        records: list[dict] = []
        live_ok = False

        if not _BS4_AVAILABLE:
            print(f"[{cls.source_name}] BeautifulSoup4 not installed — using MOCK data.")
            print(f"  Install with: pip install beautifulsoup4 lxml")
        else:
            for attempt in range(1, _RETRY_MAX + 1):
                try:
                    print(f"[{cls.source_name}] Attempt {attempt}/{_RETRY_MAX}: GET {cls.source_url}")
                    records = cls.fetch_live()
                    if records:
                        live_ok = True
                        print(f"[{cls.source_name}] Live scrape succeeded — {len(records)} event(s) found.")
                        break
                    print(f"[{cls.source_name}] Live scrape returned 0 events. Retrying…")
                except Exception as exc:
                    print(f"[{cls.source_name}] Scrape error (attempt {attempt}): {exc}")
                    if attempt < _RETRY_MAX:
                        time.sleep(1.5)

        if not live_ok:
            print(f"[{cls.source_name}] Falling back to MOCK data.")
            records = cls.mock_data()

        # Ensure source tag is present
        for rec in records:
            if cls.source_name not in rec.get("source", []):
                rec.setdefault("source", []).append(cls.source_name)

        return records


# ---------------------------------------------------------------------------
# 4-A  Destination Vancouver Scraper
# ---------------------------------------------------------------------------

class DestinationVancouverScraper(BaseEventScraper):
    source_name = "destinationvancouver.com"
    source_url  = "https://www.destinationvancouver.com/events/"

    @classmethod
    def fetch_live(cls) -> list[dict]:
        """
        Scrape the Destination Vancouver events calendar.

        Target HTML structure (as of 2026-06):
          <article class="event-card">
            <h3 class="event-card__title"><a href="…">EVENT NAME</a></h3>
            <time class="event-card__date" datetime="2026-07-26">Jul 26</time>
            <p class="event-card__location">English Bay Beach</p>
            <p class="event-card__description">…</p>
            <img class="event-card__image" src="…">
          </article>

        If the structure has changed, raises ParseError → caller falls back to mock.
        """
        resp = requests.get(cls.source_url, headers=_HEADERS, timeout=_TIMEOUT)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "lxml")
        cards = soup.select("article.event-card, div.event-item, li.event-listing")
        if not cards:
            raise ValueError("No event cards found — HTML structure may have changed.")

        events: list[dict] = []
        for card in cards[:10]:    # cap at 10 per source
            title_el   = card.select_one("h2, h3, .event-title, .event-card__title")
            date_el    = card.select_one("time, .event-date, .event-card__date")
            loc_el     = card.select_one(".event-location, .event-card__location, .location")
            desc_el    = card.select_one("p, .event-description, .event-card__description")
            img_el     = card.select_one("img")
            link_el    = card.select_one("a[href]")

            name = title_el.get_text(strip=True) if title_el else ""
            if not name:
                continue

            events.append({
                "name": name,
                "event_date": date_el.get("datetime") or (date_el.get_text(strip=True) if date_el else "TBA"),
                "address": loc_el.get_text(strip=True) if loc_el else "Vancouver, BC",
                "venue_name": loc_el.get_text(strip=True) if loc_el else None,
                "lat": 49.2827, "lng": -123.1207,   # default: downtown
                "url": link_el.get("href", cls.source_url) if link_el else cls.source_url,
                "official_website": link_el.get("href") if link_el else None,
                "image_url": img_el.get("src") if img_el else None,
                "description": None,
                "long_description": desc_el.get_text(strip=True) if desc_el else None,
                "ticket_price": None,
                "event_time": None,
                "keywords": ["温哥华活动", "本地精选", "旅游推荐"],
                "rating_system": {"google_rating": 4.5, "review_count": 100},
                "_reviews": [],
                "source": [cls.source_name],
            })

        return events

    @classmethod
    def mock_data(cls) -> list[dict]:
        return _MOCK_DV


# ---------------------------------------------------------------------------
# 4-B  Daily Hive Vancouver Scraper
# ---------------------------------------------------------------------------

class DailyHiveScraper(BaseEventScraper):
    source_name = "dailyhive.com"
    source_url  = "https://dailyhive.com/vancouver/events"

    @classmethod
    def fetch_live(cls) -> list[dict]:
        """
        Scrape Daily Hive Vancouver events roundup articles.

        Target HTML structure (as of 2026-06):
          <article class="dh-article">
            <h2 class="dh-article__title"><a href="…">TITLE</a></h2>
            <div class="dh-article__excerpt">…</div>
            <img class="dh-article__image" src="…">
            <span class="dh-article__category">Events</span>
          </article>

        Daily Hive uses article-style listings rather than structured event cards,
        so extraction is best-effort — falls back to mock on missing elements.
        """
        resp = requests.get(cls.source_url, headers=_HEADERS, timeout=_TIMEOUT)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "lxml")
        articles = soup.select("article, .post-card, .article-card, .dh-article")
        if not articles:
            raise ValueError("No articles found — HTML structure may have changed.")

        events: list[dict] = []
        for art in articles[:10]:
            title_el = art.select_one("h1, h2, h3, .post-title, .article-title")
            link_el  = art.select_one("a[href]")
            img_el   = art.select_one("img")
            desc_el  = art.select_one("p, .excerpt, .article-excerpt")

            name = title_el.get_text(strip=True) if title_el else ""
            # Filter to event-related articles
            if not name or not any(kw in name.lower() for kw in
                                   ("event", "festival", "market", "fair", "concert", "show", "parade")):
                continue

            events.append({
                "name": name,
                "event_date": "TBA",
                "address": "Vancouver, BC",
                "venue_name": None,
                "lat": 49.2827, "lng": -123.1207,
                "url": link_el.get("href", cls.source_url) if link_el else cls.source_url,
                "official_website": link_el.get("href") if link_el else None,
                "image_url": img_el.get("src") if img_el else None,
                "description": None,
                "long_description": desc_el.get_text(strip=True) if desc_el else None,
                "ticket_price": None,
                "event_time": None,
                "keywords": ["温哥华活动", "每日精选", "本地动态"],
                "rating_system": {"google_rating": 4.3, "review_count": 50},
                "_reviews": [],
                "source": [cls.source_name],
            })

        return events

    @classmethod
    def mock_data(cls) -> list[dict]:
        return _MOCK_DH


# ===========================================================================
# SECTION 5 — Event Deduplicator
# ===========================================================================

class EventDeduplicator:
    """
    Fingerprint-based deduplication and cross-source merge engine.

    Algorithm:
      1. For each raw event dict, compute fingerprint = MD5(name + date + location).
      2. Maintain a registry {fingerprint: merged_event_dict}.
      3. On collision: keep the longer long_description; merge source lists;
         prefer non-None values for image_url, event_time, ticket_price.
      4. Build SocialMetrics and RatingSystem; validate with Pydantic.
    """

    def __init__(self) -> None:
        self._registry: dict[str, dict] = {}   # fingerprint → merged raw dict
        self._merge_log: list[str] = []

    def ingest(self, raw: dict) -> None:
        """Ingest one raw event dict; merge if fingerprint already known."""
        fp = make_fingerprint(
            raw.get("name", ""),
            raw.get("event_date", ""),
            raw.get("address", ""),
        )
        raw["fingerprint"] = fp

        if fp not in self._registry:
            self._registry[fp] = dict(raw)
            return

        # ── Merge ──
        existing = self._registry[fp]
        merged_sources = sorted(set(existing.get("source", [])) | set(raw.get("source", [])))
        existing["source"] = merged_sources

        # Keep the longer long_description (more complete data)
        ld_old = existing.get("long_description") or ""
        ld_new = raw.get("long_description") or ""
        if len(ld_new) > len(ld_old):
            existing["long_description"] = ld_new

        # Fill in missing nullable fields from the duplicate
        for field in ("image_url", "event_time", "ticket_price", "venue_name",
                      "official_website", "description"):
            if not existing.get(field) and raw.get(field):
                existing[field] = raw[field]

        self._merge_log.append(
            f"  [MERGED] '{raw['name']}' ({raw['event_date']}) "
            f"← sources: {merged_sources}"
        )

    def build_entries(self) -> list[EventEntry]:
        """Convert merged raw dicts → validated EventEntry objects."""
        entries: list[EventEntry] = []
        for i, (fp, raw) in enumerate(self._registry.items(), 1):
            reviews_data = raw.pop("_reviews", [])
            keywords     = raw.pop("keywords", ["温哥华活动", "本地精选", "值得一去"])

            social = build_social_metrics(raw["name"], keywords, reviews_data)
            raw["social_metrics"] = social
            raw["rating_system"]  = raw.get("rating_system", {"google_rating": 4.3, "review_count": 100})

            try:
                from geocoder import geocode
                venue = raw.get("venue_name") or raw.get("address") or raw.get("name", "")
                coords = geocode(str(venue))
                if coords:
                    raw["lat"], raw["lng"] = coords
            except ImportError:
                pass

            try:
                entry = EventEntry(**raw)
                entries.append(entry)
                rs = entry.rating_system
                print(
                    f"  [OK] #{i:02d} {entry.name[:38]:38s}  "
                    f"src={len(entry.source)}  "
                    f"google={rs.google_rating}  agg={rs.aggregate_score}"
                )
            except Exception as exc:
                print(f"  [FAIL] #{i:02d} {raw.get('name', '?')[:38]} -- {exc}")

        return entries

    def print_merge_report(self) -> None:
        if self._merge_log:
            print(f"\n[DEDUP] {len(self._merge_log)} cross-source merge(s) performed:")
            for line in self._merge_log:
                print(line)
        else:
            print("[DEDUP] No duplicates detected across sources.")


# ===========================================================================
# SECTION 6 — Network Probe (reused from main scraper pattern)
# ===========================================================================

PROBE_URL     = "https://httpbin.org/get"
PROBE_TIMEOUT = 8


def probe_network() -> bool:
    print(f"[NET PROBE] Sending GET -> {PROBE_URL}")
    try:
        resp = requests.get(PROBE_URL, timeout=PROBE_TIMEOUT)
        resp.raise_for_status()
        origin_ip = resp.json().get("origin", "unknown")
        print(f"[NET PROBE] [OK] Connection live  |  origin IP: {origin_ip}  |  status: {resp.status_code}")
        return True
    except requests.exceptions.Timeout:
        print(f"[NET PROBE] [FAIL] Timeout after {PROBE_TIMEOUT}s — continuing in MOCK-only mode.")
    except requests.exceptions.ConnectionError:
        print("[NET PROBE] [FAIL] Connection error — continuing in MOCK-only mode.")
    except Exception as exc:
        print(f"[NET PROBE] [FAIL] {exc} — continuing in MOCK-only mode.")
    return False


# ===========================================================================
# SECTION 7 — Output Writer  →  data/events_data.json
# ===========================================================================

from paths import EVENTS_DATA_FILE, DATA_DIR

OUTPUT_DIR  = str(DATA_DIR)
OUTPUT_FILE = str(EVENTS_DATA_FILE)


def write_output(entries: list[EventEntry], source_summary: dict[str, int], network_ok: bool) -> None:
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    payload = {
        "meta": {
            "source": "events_scraper.py v1.0 (multi-source + fingerprint dedup)",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "region": "Greater Vancouver",
            "network_probe_passed": network_ok,
            "total_entries": len(entries),
            "source_summary": source_summary,
            "bs4_available": _BS4_AVAILABLE,
            "scrape_mode": "live" if _BS4_AVAILABLE and network_ok else "mock",
            "schema_version": "1.1",
            "dedup_algorithm": "MD5(normalised_name + date + location)[:16]",
            "schema_note": (
                "Entry schema mirrors master_data.json BaseEntry. "
                "Event extras: event_date, event_time, venue_name, ticket_price, "
                "long_description, source, fingerprint."
            ),
        },
        "entries": [e.model_dump() for e in entries],
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"\n[WRITER] Output -> {OUTPUT_FILE}")
    print(f"[WRITER] Total unique events: {len(entries)}")
    for src, count in source_summary.items():
        print(f"         {src}: {count} raw events ingested")


# ===========================================================================
# SECTION 8 — Entry Point
# ===========================================================================

if __name__ == "__main__":
    import argparse
    import subprocess
    import sys

    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))
    except ImportError:
        pass

    parser = argparse.ArgumentParser(description="VanMap events scraper")
    parser.add_argument("--sync", action="store_true", help="Sync data/ to frontend after write")
    args = parser.parse_args()

    print("=" * 65)
    print("  VanMap Cluster -- Events Scraper  v1.0")
    print("  Sources: Destination Vancouver + Daily Hive")
    print(f"  BeautifulSoup4: {'available (live scraping enabled)' if _BS4_AVAILABLE else 'NOT installed (MOCK-only mode)'}")
    print("=" * 65)

    network_ok = probe_network()

    # ── 1. Collect from each source ────────────────────────────────────────
    print(f"\n[SOURCES] Fetching from {DestinationVancouverScraper.source_url}")
    dv_raw = DestinationVancouverScraper.fetch()

    print(f"\n[SOURCES] Fetching from {DailyHiveScraper.source_url}")
    dh_raw = DailyHiveScraper.fetch()

    source_summary = {
        "destinationvancouver.com": len(dv_raw),
        "dailyhive.com": len(dh_raw),
    }

    # ── 2. Deduplication + merge ────────────────────────────────────────────
    print("\n[DEDUP] Fingerprinting and merging cross-source events…")
    deduplicator = EventDeduplicator()
    for raw in dv_raw + dh_raw:
        deduplicator.ingest(raw)
    deduplicator.print_merge_report()

    # ── 3. Build validated EventEntry objects ──────────────────────────────
    print(f"\n[VALIDATE] Building {len(deduplicator._registry)} unique event entries…")
    entries = deduplicator.build_entries()
    print(f"[VALIDATE] {len(entries)}/{len(deduplicator._registry)} passed Pydantic validation.")

    # ── 4. Write output ────────────────────────────────────────────────────
    if not entries:
        print("\n[SCRAPER] No valid events collected — aborting.")
    else:
        write_output(entries, source_summary, network_ok)
        if args.sync:
            sync_ps1 = os.path.join(os.path.dirname(__file__), "..", "scripts", "sync_data.ps1")
            sync_sh = os.path.join(os.path.dirname(__file__), "..", "scripts", "sync_data.sh")
            if sys.platform == "win32" and os.path.isfile(sync_ps1):
                subprocess.run(["powershell", "-File", sync_ps1], check=False)
            elif os.path.isfile(sync_sh):
                subprocess.run(["bash", sync_sh], check=False)
        print("=" * 65)
        print(f"  Done. {len(entries)} unique events written to events_data.json.")
        print(f"  Cross-source merges: {len(deduplicator._merge_log)}")
        print("  Ready for frontend merge with master_data.json.")
        print("=" * 65)
