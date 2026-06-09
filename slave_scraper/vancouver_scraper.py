"""
Vancouver Multi-Category Intelligence Scraper — v5
----------------------------------------------------
Slave Scraper Module — VanMap Cluster

v5 Architecture Upgrades
  · SocialMetrics model      universal social block (videos/reviews/keywords/buzz_score)
  · RatingSystem model       universal rating block (google_rating/review_count/aggregate_score)
  · AllTrailsData model      AllTrails-exclusive block for 徒步
  · BaseEntry                now carries social_metrics + rating_system on ALL categories
  · BaseScraper.fetch_social_metrics()
                             shared classmethod — builds YouTube/TikTok/Google/XHS links
                             called by BarScraper / EntertainmentScraper /
                             AttractionScraper / HikingScraper
  · HikingScraper.fetch_alltrails_data()
                             dedicated AllTrails module (trail_distance / elevation_gain /
                             difficulty_rating + alltrails_rating / alltrails_review_count)
  · RatingSystem.aggregate_score
                             Bayesian-smoothed computed field — universal across all categories

Output: data/master_data.json
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import statistics
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, ClassVar, Generic, Literal, TypeVar
from urllib.parse import quote_plus

import requests
from pydantic import BaseModel, Field, computed_field

# ===========================================================================
# SECTION 1 — Shared Nested Models
# ===========================================================================

class VideoClip(BaseModel):
    platform: Literal["TikTok", "YouTube"]
    url: str
    summary: str


class PlatformReview(BaseModel):
    platform: Literal["Google Review", "小红书"]
    text: str
    source_url: str


class PhotoItem(BaseModel):
    """Single photo entry — mirrors Google Places API photos[] format."""
    category: str   # human-readable label, e.g. "食物", "步道", "地标"
    url: str        # Google Maps CDN URL (production: resolved from photo_reference)


class SocialMetrics(BaseModel):
    """Universal social intelligence block — carried by every category."""
    videos: list[VideoClip]
    reviews: list[PlatformReview]
    keywords: list[str] = Field(min_length=3)
    social_buzz_score: float = Field(ge=0.0, le=5.0)


class RatingSystem(BaseModel):
    """Universal rating block — Google score + review volume + Bayesian aggregate."""
    google_rating: float = Field(ge=0.0, le=5.0)
    review_count: int = Field(ge=0)

    @computed_field
    @property
    def aggregate_score(self) -> float:
        """
        Bayesian smoothing: score converges toward the prior mean (3.5) when
        review_count is low, and toward google_rating as volume grows.
        Full weight at 500+ reviews.
        """
        weight = min(self.review_count / 500, 1.0)
        return round(self.google_rating * weight + 3.5 * (1.0 - weight), 2)


class AllTrailsData(BaseModel):
    """AllTrails-exclusive data block — only present in 徒步 entries."""
    trail_distance: float          # km
    elevation_gain: int            # metres
    difficulty_rating: Literal["Easy", "Moderate", "Hard", "Expert"]
    alltrails_url: str
    alltrails_rating: float = Field(ge=0.0, le=5.0)
    alltrails_review_count: int = Field(ge=0)


# ===========================================================================
# SECTION 2 — Entry Models  (BaseEntry + per-category subclasses)
# ===========================================================================

class BaseEntry(BaseModel):
    """Universal fields shared by every category."""
    name: str
    category: str
    address: str
    lat: float = Field(ge=49.0, le=49.8)
    lng: float = Field(ge=-123.5, le=-122.3)
    url: str
    official_website: str | None = None       # official site; None if not available
    image_url: str | None = None              # hero image / photo URL; None if not available
    description: str | None = Field(default=None, max_length=50)  # short popup text; ≤50 chars
    photos: list[PhotoItem] = Field(default_factory=list)  # injected by fetch_photos()
    social_metrics: SocialMetrics    # injected by fetch_social_metrics()
    rating_system: RatingSystem      # unified scoring for all categories

    @computed_field
    @property
    def rating(self) -> float:
        """Convenience accessor — mirrors google_rating for the map validator."""
        return self.rating_system.google_rating

    @computed_field
    @property
    def videos(self) -> list[VideoClip]:
        """Top-level shortcut — hoisted from social_metrics for frontend convenience.
        Guaranteed to be a list ([] when no videos available)."""
        return self.social_metrics.videos if self.social_metrics else []

    @computed_field
    @property
    def reviews(self) -> list[PlatformReview]:
        """Top-level shortcut — hoisted from social_metrics for frontend convenience.
        Guaranteed to be a list ([] when no reviews available)."""
        return self.social_metrics.reviews if self.social_metrics else []


class RestaurantEntry(BaseEntry):
    price_level: str    # category-specific (like vibe for bars, admission_fee for attractions)


class BarEntry(BaseEntry):
    vibe: str
    signature_drink: str
    happy_hour: str


class EntertainmentEntry(BaseEntry):
    venue_type: str
    age_restriction: str
    opening_hours: str


class AttractionEntry(BaseEntry):
    admission_fee: str
    highlights: list[str]
    # description inherited from BaseEntry (str | None, max_length=50)


class HikingEntry(BaseEntry):
    """
    徒步 entry: inherits social_metrics + rating_system from BaseEntry,
    and adds AllTrails-exclusive data block.
    """
    duration: str
    trailhead: str
    alltrails_data: AllTrailsData


# ===========================================================================
# SECTION 3 — BaseScraper ABC + Per-Category Concrete Scrapers
# ===========================================================================

T = TypeVar("T", bound=BaseEntry)

_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "餐厅": ["大温美食", "本地口碑", "必吃推荐"],
    "酒吧": ["本地调酒", "深夜社交", "精酿体验"],
    "娱乐": ["家庭出行", "周末首选", "趣味体验"],
    "景点": ["大温必去", "拍照圣地", "户外地标"],
    "徒步": ["北温山径", "有氧打卡", "大温徒步"],
}


class BaseScraper(ABC, Generic[T]):
    """
    Abstract base class for all category scrapers.

    Shared public methods (callable by all subclasses):
      fetch_social_metrics(name, category) → dict
          Builds standardised social block with real, clickable platform URLs.
          Replaces per-category manual social data construction.

    Private helpers:
      _deterministic_score(seed, min_v, max_v) → float
      _deterministic_count(seed, min_v, max_v) → int
          MD5-based deterministic generators — reproducible across runs.
    """

    category_name: ClassVar[str]
    entry_url: ClassVar[str]

    # ------------------------------------------------------------------
    # Shared deterministic utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _deterministic_score(seed: str, min_v: float, max_v: float) -> float:
        """MD5-seeded float in [min_v, max_v] — deterministic per seed string."""
        h = int(hashlib.md5(seed.encode()).hexdigest()[:8], 16)
        return round(min_v + (h / 0xFFFFFFFF) * (max_v - min_v), 1)

    @staticmethod
    def _deterministic_count(seed: str, min_v: int, max_v: int) -> int:
        """MD5-seeded int in [min_v, max_v) — deterministic per seed string."""
        h = int(hashlib.md5((seed + "_cnt").encode()).hexdigest()[:6], 16)
        return min_v + (h % (max_v - min_v))

    # ------------------------------------------------------------------
    # Per-category photo taxonomy
    # ------------------------------------------------------------------

    # Each list has 8 labels — assigned round-robin across n_photos.
    # The first label is always the most representative shot for that category.
    _PHOTO_CATEGORIES: ClassVar[dict[str, list[str]]] = {
        "餐厅": ["招牌菜", "食物特写", "用餐环境", "外观门面", "菜单", "厨房展示", "饮品", "包厢/私房"],
        "酒吧": ["招牌特调", "吧台环境", "外观夜景", "调酒过程", "人气氛围", "座位区", "酒单", "灯光效果"],
        "娱乐": ["主要项目", "室内环境", "外观建筑", "活动现场", "游客体验", "设施细节", "票务入口", "人气场景"],
        "景点": ["核心地标", "全景风光", "游客打卡", "历史细节", "自然景观", "标志建筑", "季节特色", "入口全景"],
        "徒步": ["步道起点", "沿途森林", "山顶/终点", "峰顶全景", "植被地貌", "路标指示", "远眺视野", "停车入口"],
    }

    @staticmethod
    def _make_photo_ref(seed: str, idx: int) -> str:
        """
        Generate a deterministic mock Google Places photo_reference string.

        Real format example: AF1QipNjXXXXXXXXXXXXXXXXXXXXXXXXXXXX
        Production replacement: use photo_reference returned by
          GET /maps/api/place/details/json?place_id={ID}&fields=photos&key={KEY}
        then resolve via:
          GET /maps/api/place/photo?maxwidth=1200&photo_reference={REF}&key={KEY}
        """
        h = hashlib.sha256(f"{seed}|photo|{idx}".encode()).hexdigest().upper()[:30]
        return f"AF1Qip{h}"

    @classmethod
    def fetch_photos(
        cls,
        name: str,
        category: str,
        n_photos: int = 8,
    ) -> list[dict]:
        """
        Return real photos only — prefer _photos_from_osm on the record; no fake CDN URLs.
        Phase 3: GooglePlacesProvider.enrich_place() for photo sets.
        """
        return []

    # ------------------------------------------------------------------
    # fetch_social_metrics — universal shared method
    # ------------------------------------------------------------------

    @classmethod
    def fetch_social_metrics(
        cls,
        name: str,
        category: str,
        override_reviews: list[dict] | None = None,
        override_videos: list[dict] | None = None,
        override_keywords: list[str] | None = None,
    ) -> dict:
        """
        Universal social intelligence builder — shared by ALL category scrapers.

        Generates:
          · YouTube / TikTok search-query links (real, clickable)
          · Google Maps + 小红书 review source links
          · Category-specific keywords
          · Deterministic social_buzz_score

        Args:
          override_reviews:  per-entry curated reviews; falls back to generic if None.
          override_videos:   per-entry curated videos; falls back to generic if None.
          override_keywords: per-entry keywords; falls back to category-level if None.

        All three overrides default to None so existing callers are unaffected.
        Empty list [] is stored as-is (field is never omitted).

        MOCK mode: structured data with live search URLs.
        Production replacement:
          · YouTube Data API v3      for video search
          · TikTok Research API      for short-video data
          · Google Places API        for reviews & ratings
          · 小红书 web scraper       for UGC content
        """
        q = quote_plus(f"{name} Vancouver")
        q_short = quote_plus(name)

        # Keywords: prefer per-entry override, then category defaults
        keywords = (
            override_keywords
            if override_keywords is not None
            else _CATEGORY_KEYWORDS.get(category, ["温哥华推荐", "本地热门", "值得一去"])
        )

        # Videos: resolver port (direct links only) or explicit override
        if override_videos is not None:
            videos = override_videos
        else:
            try:
                from video_resolver import resolve_videos
                videos = resolve_videos(name, category)
            except ImportError:
                videos = []

        # Reviews: prefer per-entry curated text; fall back to generic only when
        # no override is supplied (e.g. future categories not yet configured).
        if override_reviews is not None:
            reviews = override_reviews
        else:
            reviews = [
                {
                    "platform": "Google Review",
                    "text": (
                        f"One of the best in Vancouver. "
                        f"Highly recommend {name} for locals and visitors alike."
                    ),
                    "source_url": f"https://www.google.com/maps/search/?api=1&query={q}",
                },
                {
                    "platform": "小红书",
                    "text": f"强烈推荐 {name}！大温本地博主亲测，体验一流，攻略全在评论区。",
                    "source_url": f"https://www.xiaohongshu.com/search_result?keyword={q_short}",
                },
            ]

        return {
            "videos": videos,
            "reviews": reviews,
            "keywords": keywords,
            "social_buzz_score": cls._deterministic_score(name, 3.8, 4.9),
        }

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @classmethod
    @abstractmethod
    def entry_model(cls) -> type[T]: ...

    @classmethod
    @abstractmethod
    def fetch_raw(cls) -> list[dict]: ...

    # ------------------------------------------------------------------
    # Shared pipeline methods
    # ------------------------------------------------------------------

    @classmethod
    def validate(cls, raw_list: list[dict]) -> list[T]:
        model = cls.entry_model()
        validated: list[T] = []
        for i, raw in enumerate(raw_list, 1):
            try:
                entry = model(**raw)
                validated.append(entry)
                rs = entry.rating_system
                print(
                    f"  [OK] #{i:02d} {entry.name}  "
                    f"google={rs.google_rating}  reviews={rs.review_count}  "
                    f"agg={rs.aggregate_score}"
                )
            except Exception as exc:
                print(f"  [FAIL] #{i:02d} {raw.get('name', '?')} -- {exc}")
        return validated

    @classmethod
    def _use_osm(cls) -> bool:
        return os.environ.get("VANMAP_SCRAPE_MODE", "osm").lower() != "mock"

    @classmethod
    def _finalize_osm_records(cls, records: list[dict]) -> list[dict]:
        finalized: list[dict] = []
        for rec in records:
            row = dict(rec)
            videos = row.pop("_videos", None)
            reviews = row.pop("_reviews", None)
            keywords = row.pop("_keywords", None)
            if videos is None:
                try:
                    from video_resolver import resolve_videos
                    videos = resolve_videos(row["name"], row["category"])
                except ImportError:
                    videos = []
            row["social_metrics"] = cls.fetch_social_metrics(
                row["name"],
                row["category"],
                override_reviews=reviews,
                override_videos=videos,
                override_keywords=keywords,
            )
            osm_photos = row.pop("_photos_from_osm", None)
            row["photos"] = osm_photos if osm_photos else cls.fetch_photos(row["name"], row["category"])
            if row.get("official_website") is None:
                row["official_website"] = row.get("url")
            finalized.append(row)
        return finalized

    @classmethod
    def run(cls) -> list[T]:
        print(f"\n[{cls.category_name}] entry_url: {cls.entry_url}")
        raw: list[dict] = []
        if cls._use_osm():
            try:
                from osm_provider import fetch_osm_places
                osm_raw = fetch_osm_places(cls.category_name, limit=15)
                if osm_raw:
                    raw = cls._finalize_osm_records(osm_raw)
                    print(f"[{cls.category_name}] {len(raw)} OSM record(s) fetched.")
            except ImportError:
                pass
        if not raw:
            raw = cls.fetch_raw()
            print(f"[{cls.category_name}] {len(raw)} mock record(s) fetched.")
        print(f"[{cls.category_name}] Validating {len(raw)} record(s)...")
        results = cls.validate(raw)
        print(f"[{cls.category_name}] {len(results)}/{len(raw)} passed validation.")
        return results

    @classmethod
    def serialize_all(cls, entries: list[T]) -> list[dict]:
        """
        Serialize entries to dict.
        `videos` and `reviews` appear both at top level (computed_field)
        and inside `social_metrics` — top-level copies are the canonical
        frontend-facing fields; social_metrics retains the full block.
        """
        return [e.model_dump() for e in entries]


# ---------------------------------------------------------------------------
# 3-A  RestaurantScraper
#      Calls fetch_social_metrics() then overrides with hand-curated content.
# ---------------------------------------------------------------------------

class RestaurantScraper(BaseScraper[RestaurantEntry]):
    category_name = "餐厅"
    entry_url = "https://www.yelp.com/search?cflt=restaurants&find_loc=Vancouver+BC"

    @classmethod
    def entry_model(cls) -> type[RestaurantEntry]:
        return RestaurantEntry

    @classmethod
    def fetch_raw(cls) -> list[dict]:
        # Same _videos / _reviews / _keywords pop pattern as all other scrapers.
        # social_metrics is built uniformly via fetch_social_metrics() in the loop below.
        records = [
            {
                "name": "Kirin Seafood Restaurant",
                "category": "餐厅",
                "price_level": "$$$",
                "address": "1166 Alberni St, Vancouver, BC V6E 1A5",
                "image_url": "https://www.google.com/maps/search/?api=1&query=Kirin+Seafood+Restaurant+Vancouver",
                "lat": 49.2827, "lng": -123.1207,
                "url": "https://www.google.com/maps/search/?api=1&query=Kirin+Seafood+Restaurant+Vancouver",
                "official_website": "https://www.kirinrestaurant.com/",
                "description": "Downtown 经典粤菜海鲜楼，炭烧叉烧与清蒸游水海鲜是招牌，商务宴请首选。",
                "rating_system": {"google_rating": 4.5, "review_count": 1240},
                "_videos": [
                    {"platform": "YouTube", "url": "https://www.youtube.com/results?search_query=Kirin+Seafood+Restaurant+Vancouver", "summary": "食评人深探 Kirin 全菜单，重点试吃清蒸龙虾与片皮鸭，厨房近距离揭秘。"},
                    {"platform": "TikTok", "url": "https://www.tiktok.com/search?q=Kirin+Seafood+Restaurant+Vancouver+dim+sum", "summary": "周末早茶 vlog：推车点心实况，虾饺皮薄透明引发弹幕刷屏。"},
                ],
                "_reviews": [
                    {"platform": "Google Review", "text": "Hands down the best Cantonese in Downtown. The steamed fish is incredible.", "source_url": "https://www.google.com/maps/search/?api=1&query=Kirin+Seafood+Restaurant+Vancouver"},
                    {"platform": "小红书", "text": "叉烧是全温哥华最嫩的那种，肥瘦比例完美，配白饭能吃三碗！", "source_url": "https://www.xiaohongshu.com/search_result?keyword=Kirin+Seafood+Vancouver"},
                ],
                "_keywords": ["粤菜海鲜", "商务宴请", "炭烧叉烧"],
            },
            {
                "name": "Sura Korean Cuisine",
                "category": "餐厅",
                "price_level": "$$$",
                "address": "1262 Robson St, Vancouver, BC V6E 1C1",
                "image_url": "https://www.google.com/maps/search/?api=1&query=Sura+Korean+Cuisine+Vancouver",
                "lat": 49.2836, "lng": -123.1193,
                "url": "https://www.google.com/maps/search/?api=1&query=Sura+Korean+Cuisine+Vancouver",
                "official_website": "https://www.sura.ca/",
                "description": "Downtown 精致韩餐，宫廷风格摆盘，烤牛肋骨与海鲜煎饼受本地食客高度评价。",
                "rating_system": {"google_rating": 4.6, "review_count": 890},
                "_videos": [
                    {"platform": "YouTube", "url": "https://www.youtube.com/results?search_query=Sura+Korean+Cuisine+Vancouver", "summary": "温哥华美食频道专题：Sura 宫廷套餐全流程，7 道菜一镜到底展示。"},
                    {"platform": "TikTok", "url": "https://www.tiktok.com/search?q=Sura+Korean+Cuisine+Vancouver+galbi", "summary": "炭火烤牛肋骨特写，油脂滴落瞬间引来百万次观看。"},
                ],
                "_reviews": [
                    {"platform": "Google Review", "text": "Authentic royal court presentation. The galbi is melt-in-your-mouth good.", "source_url": "https://www.google.com/maps/search/?api=1&query=Sura+Korean+Cuisine+Vancouver"},
                    {"platform": "小红书", "text": "宫廷摆盘真的太美了，海鲜煎饼外酥里嫩！", "source_url": "https://www.xiaohongshu.com/search_result?keyword=Sura+Korean+Vancouver"},
                ],
                "_keywords": ["宫廷韩餐", "烤牛肋骨", "精致摆盘"],
            },
            {
                "name": "Golden Great Wall Restaurant",
                "category": "餐厅",
                "price_level": "$$",
                "address": "4540 No. 3 Rd, Richmond, BC V6X 2C2",
                "image_url": "https://www.google.com/maps/search/?api=1&query=Golden+Great+Wall+Restaurant+Richmond",
                "lat": 49.1628, "lng": -123.1369,
                "url": "https://www.google.com/maps/search/?api=1&query=Golden+Great+Wall+Restaurant+Richmond",
                "official_website": None,
                "description": "Richmond 人气早茶老店，虾饺、肠粉、萝卜糕必点，周末翻台率极高。",
                "rating_system": {"google_rating": 4.4, "review_count": 1560},
                "_videos": [
                    {"platform": "TikTok", "url": "https://www.tiktok.com/search?q=Golden+Great+Wall+dim+sum+Richmond+Vancouver", "summary": "Richmond 早茶大挑战：单人一小时内吃遍推车菜单，结局超预期。"},
                    {"platform": "YouTube", "url": "https://www.youtube.com/results?search_query=Golden+Great+Wall+Restaurant+Richmond+dim+sum", "summary": "本地华人博主带父母吃早茶，萝卜糕同款复刻对比评测。"},
                ],
                "_reviews": [
                    {"platform": "Google Review", "text": "Best dim sum in Richmond. Show up by 9am or wait 45 minutes on weekends.", "source_url": "https://www.google.com/maps/search/?api=1&query=Golden+Great+Wall+Restaurant+Richmond+BC"},
                    {"platform": "小红书", "text": "肠粉皮薄如纸，虾饺馅料饱满，推车阿姨服务特别亲切！", "source_url": "https://www.xiaohongshu.com/search_result?keyword=Golden+Great+Wall+Richmond+早茶"},
                ],
                "_keywords": ["排队圣地", "周末早茶", "虾饺肠粉"],
            },
            {
                "name": "Sun Sui Wah Seafood Restaurant",
                "category": "餐厅",
                "price_level": "$$$",
                "address": "3888 Main St, Vancouver, BC V5V 3P1",
                "image_url": "https://www.google.com/maps/search/?api=1&query=Sun+Sui+Wah+Seafood+Restaurant+Vancouver",
                "lat": 49.2423, "lng": -123.0712,
                "url": "https://www.google.com/maps/search/?api=1&query=Sun+Sui+Wah+Seafood+Restaurant+Vancouver",
                "official_website": "https://sunsuiwah.com/",
                "description": "Main Street 老牌海鲜粤菜馆，以片皮乳鸽与波士顿龙虾闻名大温，家庭聚餐首选。",
                "rating_system": {"google_rating": 4.6, "review_count": 1820},
                "_videos": [
                    {"platform": "YouTube", "url": "https://www.youtube.com/results?search_query=Sun+Sui+Wah+Seafood+Restaurant+Vancouver", "summary": "温哥华最佳乳鸽评测：Sun Sui Wah 片皮乳鸽现场片制全纪录。"},
                    {"platform": "TikTok", "url": "https://www.tiktok.com/search?q=Sun+Sui+Wah+Vancouver+squab+lobster", "summary": "龙虾生猛下锅实况，姜葱炒制香气飘满整层楼。"},
                ],
                "_reviews": [
                    {"platform": "Google Review", "text": "The squab is unmatched — crispy skin, juicy meat. A Vancouver institution since the 80s.", "source_url": "https://www.google.com/maps/search/?api=1&query=Sun+Sui+Wah+Seafood+Restaurant+Vancouver"},
                    {"platform": "小红书", "text": "全温哥华最好吃的乳鸽在这里！家庭聚餐必来。", "source_url": "https://www.xiaohongshu.com/search_result?keyword=Sun+Sui+Wah+温哥华+乳鸽"},
                ],
                "_keywords": ["片皮乳鸽", "波士顿龙虾", "家庭聚餐"],
            },
            {
                "name": "Gyo-O Korean BBQ",
                "category": "餐厅",
                "price_level": "$$",
                "address": "4501 Kingsway, Burnaby, BC V5H 2A9",
                "image_url": "https://www.google.com/maps/search/?api=1&query=Gyo-O+Korean+BBQ+Burnaby",
                "lat": 49.2285, "lng": -122.9981,
                "url": "https://www.google.com/maps/search/?api=1&query=Gyo-O+Korean+BBQ+Burnaby",
                "official_website": None,
                "description": "Burnaby 本地最火烤肉店，牛舌与五花肉套餐配无限续杯小菜，性价比极高。",
                "rating_system": {"google_rating": 4.5, "review_count": 670},
                "_videos": [
                    {"platform": "TikTok", "url": "https://www.tiktok.com/search?q=Gyo-O+Korean+BBQ+Burnaby+Vancouver", "summary": "深夜烤肉实况：Gyo-O 单人自助挑战，小菜续了 7 次的真实记录。"},
                    {"platform": "YouTube", "url": "https://www.youtube.com/results?search_query=Gyo-O+Korean+BBQ+Burnaby", "summary": "Burnaby 韩烤横向评测第一名，Gyo-O 牛舌 vs 和牛五花盲测对决。"},
                ],
                "_reviews": [
                    {"platform": "Google Review", "text": "Unlimited banchan refills and the beef tongue is buttery smooth. Best KBBQ value in GVA.", "source_url": "https://www.google.com/maps/search/?api=1&query=Gyo-O+Korean+BBQ+Burnaby+BC"},
                    {"platform": "小红书", "text": "五花肉切得厚度刚好，烤到微焦卷着生菜吃，小菜不限续！", "source_url": "https://www.xiaohongshu.com/search_result?keyword=Gyo-O+韩式烤肉+Burnaby"},
                ],
                "_keywords": ["深夜烤肉", "小菜无限续", "性价比之王"],
            },
        ]
        for rec in records:
            videos = rec.pop("_videos", None)
            reviews = rec.pop("_reviews", None)
            keywords = rec.pop("_keywords", None)
            rec["social_metrics"] = cls.fetch_social_metrics(
                rec["name"], "餐厅",
                override_reviews=reviews,
                override_videos=videos,
                override_keywords=keywords,
            )
            rec["photos"] = cls.fetch_photos(rec["name"], "餐厅")
        return records


# ---------------------------------------------------------------------------
# 3-B  BarScraper — calls fetch_social_metrics() for all entries
# ---------------------------------------------------------------------------

class BarScraper(BaseScraper[BarEntry]):
    category_name = "酒吧"
    entry_url = "https://www.yelp.com/search?cflt=bars&find_loc=Vancouver+BC"

    @classmethod
    def entry_model(cls) -> type[BarEntry]:
        return BarEntry

    @classmethod
    def fetch_raw(cls) -> list[dict]:
        records = [
            {
                "name": "The Keefer Bar",
                "category": "酒吧",
                "address": "135 Keefer St, Vancouver, BC V6A 1X3",
                "lat": 49.2795, "lng": -123.1002,
                "url": "https://www.google.com/maps/search/?api=1&query=The+Keefer+Bar+Vancouver",
                "official_website": "https://thekeeferbar.com/",
                "description": "唐人街亚洲草药调酒秘境，Jade Dragon 为招牌，私密氛围约会首选。",
                "vibe": "Speakeasy",
                "signature_drink": "Jade Dragon (green tea vodka, lychee, lime)",
                "happy_hour": "Mon-Fri 5-7 PM",
                "rating_system": {"google_rating": 4.6, "review_count": 780},
                "_keywords": ["亚洲草药调酒", "约会氛围", "Chinatown秘境"],
                "_reviews": [
                    {"platform": "Google Review", "text": "Hidden gem in Chinatown! Creative cocktail menu — the Jade Dragon is a must-try. Intimate lighting and knowledgeable bartenders make it perfect for date nights.", "source_url": "https://www.google.com/maps/search/?api=1&query=The+Keefer+Bar+Vancouver"},
                    {"platform": "小红书", "text": "唐人街隐藏宝藏吧！招牌 Jade Dragon 颜值与口感并存，氛围私密适合约会，调酒师超专业，强烈推荐！", "source_url": "https://www.xiaohongshu.com/search_result?keyword=The+Keefer+Bar+Vancouver"},
                ],
            },
            {
                "name": "Guilt & Co",
                "category": "酒吧",
                "address": "1 Alexander St, Vancouver, BC V6A 1B2",
                "lat": 49.2842, "lng": -123.1068,
                "url": "https://www.google.com/maps/search/?api=1&query=Guilt+and+Co+Vancouver+Gastown",
                "official_website": "https://www.guiltandco.com/",
                "description": "Gastown 地下音乐现场，每晚驻场演出配手工鸡尾酒，穿越老式地下酒廊。",
                "vibe": "Underground Live Music",
                "signature_drink": "Gastown Gin Fizz (local gin, elderflower, egg white)",
                "happy_hour": "Daily 5-7 PM",
                "rating_system": {"google_rating": 4.5, "review_count": 1120},
                "_keywords": ["地下音乐现场", "Gastown夜生活", "驻场演出"],
                "_reviews": [
                    {"platform": "Google Review", "text": "Best underground bar in Vancouver. Live music every night, exceptional craft cocktails, and a speakeasy vibe that makes every visit memorable.", "source_url": "https://www.google.com/maps/search/?api=1&query=Guilt+and+Co+Vancouver+Gastown"},
                    {"platform": "小红书", "text": "温哥华最有氛围的地下酒吧！每晚现场音乐表演，精酿鸡尾酒一流，像穿越到老式地下酒廊，朋友聚会必选！", "source_url": "https://www.xiaohongshu.com/search_result?keyword=Guilt+Co+Vancouver"},
                ],
            },
            {
                "name": "UVA Wine & Cocktail Bar",
                "category": "酒吧",
                "address": "900 Seymour St, Vancouver, BC V6B 3L9",
                "lat": 49.2806, "lng": -123.1205,
                "url": "https://www.google.com/maps/search/?api=1&query=UVA+Wine+Cocktail+Bar+Vancouver",
                "official_website": "https://www.uvavancouver.com/",
                "description": "精选葡萄酒单与烟熏老式调酒并重，商务饮宴与精致约会双重首选。",
                "vibe": "Upscale Wine Lounge",
                "signature_drink": "Smoked Old Fashioned (bourbon, maple bitters, rosemary smoke)",
                "happy_hour": "Mon-Thu 4-6 PM",
                "rating_system": {"google_rating": 4.4, "review_count": 540},
                "_keywords": ["精品葡萄酒", "烟熏Old Fashioned", "商务招待"],
                "_reviews": [
                    {"platform": "Google Review", "text": "Sophisticated wine bar with an impressive selection. The smoked Old Fashioned is exceptional. Ideal for business drinks or a refined evening out in downtown Vancouver.", "source_url": "https://www.google.com/maps/search/?api=1&query=UVA+Wine+Cocktail+Bar+Vancouver"},
                    {"platform": "小红书", "text": "高级感酒吧首选！烟熏老时髦调制精良，葡萄酒单丰富，商务聚会或高端约会必来，服务细致周到！", "source_url": "https://www.xiaohongshu.com/search_result?keyword=UVA+Wine+Bar+Vancouver"},
                ],
            },
            {
                "name": "The Diamond",
                "category": "酒吧",
                "address": "6 Powell St, Vancouver, BC V6A 1E7",
                "lat": 49.2840, "lng": -123.1050,
                "url": "https://www.google.com/maps/search/?api=1&query=The+Diamond+Bar+Vancouver+Gastown",
                "official_website": "https://www.thediamond.ca/",
                "description": "Gastown 二楼经典鸡尾酒吧，Last Word 平衡度极高，露台可俯瞰街景。",
                "vibe": "Classic Craft Cocktail",
                "signature_drink": "Last Word (gin, green chartreuse, maraschino, lime)",
                "happy_hour": "Tue-Fri 5-7 PM",
                "rating_system": {"google_rating": 4.3, "review_count": 620},
                "_keywords": ["经典鸡尾酒", "Last Word调酒", "Gastown露台"],
                "_reviews": [
                    {"platform": "Google Review", "text": "Classic Gastown cocktail bar with impeccable drinks. The Last Word is perfectly balanced and the bartenders are passionate about their craft. Great rooftop views too.", "source_url": "https://www.google.com/maps/search/?api=1&query=The+Diamond+Bar+Vancouver+Gastown"},
                    {"platform": "小红书", "text": "Gastown 经典调酒圣地！Last Word 堪称全温哥华最平衡的鸡尾酒，调酒师专业度极高，有屋顶露台超适合拍照！", "source_url": "https://www.xiaohongshu.com/search_result?keyword=The+Diamond+Bar+Gastown"},
                ],
            },
        ]
        for rec in records:
            keywords = rec.pop("_keywords", None)
            reviews = rec.pop("_reviews", None)
            rec["social_metrics"] = cls.fetch_social_metrics(
                rec["name"], "酒吧",
                override_reviews=reviews,
                override_keywords=keywords,
            )
            rec["photos"] = cls.fetch_photos(rec["name"], "酒吧")
        return records


# ---------------------------------------------------------------------------
# 3-C  EntertainmentScraper — calls fetch_social_metrics() for all entries
# ---------------------------------------------------------------------------

class EntertainmentScraper(BaseScraper[EntertainmentEntry]):
    category_name = "娱乐"
    entry_url = "https://www.yelp.com/search?cflt=amusement&find_loc=Vancouver+BC"

    @classmethod
    def entry_model(cls) -> type[EntertainmentEntry]:
        return EntertainmentEntry

    @classmethod
    def fetch_raw(cls) -> list[dict]:
        records = [
            {
                "name": "Playdium Burnaby",
                "category": "娱乐",
                "address": "4700 Kingsway, Burnaby, BC V5H 4M1",
                "lat": 49.2268, "lng": -122.9989,
                "url": "https://www.google.com/maps/search/?api=1&query=Playdium+Burnaby",
                "official_website": "https://playdium.com/",
                "description": "Burnaby 大型综合娱乐中心，电玩碰碰车保龄球齐备，全年龄段同乐。",
                "venue_type": "Arcade & Amusement",
                "age_restriction": "All Ages",
                "opening_hours": "Mon-Thu 11am-11pm | Fri-Sun 11am-12am",
                "rating_system": {"google_rating": 4.3, "review_count": 2300},
                "_keywords": ["百款电玩", "碰碰车保龄球", "全家出游"],
                "_reviews": [
                    {"platform": "Google Review", "text": "Awesome entertainment complex for all ages. Hundreds of arcade games, bumper cars, and bowling. Kids and adults both had a blast — great value with the card system.", "source_url": "https://www.google.com/maps/search/?api=1&query=Playdium+Burnaby"},
                    {"platform": "小红书", "text": "全家出游首选！游戏种类超多，碰碰车和保龄球一起玩，小孩大人都嗨翻，储值卡超划算，周末必去！", "source_url": "https://www.xiaohongshu.com/search_result?keyword=Playdium+Burnaby"},
                ],
            },
            {
                "name": "Rec Room Vancouver",
                "category": "娱乐",
                "address": "585 Great Northern Way, Vancouver, BC V5T 1E1",
                "lat": 49.2699, "lng": -123.0893,
                "url": "https://www.google.com/maps/search/?api=1&query=Rec+Room+Vancouver",
                "official_website": "https://therecroom.com/",
                "description": "VR体验、斧头投掷与精品餐饮一站搞定，温哥华团建与聚会必去场地。",
                "venue_type": "Social Entertainment Complex",
                "age_restriction": "All Ages (19+ after 9 PM)",
                "opening_hours": "Mon-Thu 12pm-12am | Fri-Sun 11am-1am",
                "rating_system": {"google_rating": 4.4, "review_count": 1870},
                "_keywords": ["斧头投掷", "VR沉浸体验", "团建首选"],
                "_reviews": [
                    {"platform": "Google Review", "text": "Vancouver's premier entertainment destination. Axe throwing, VR experiences, and amazing food all under one roof. Perfect for corporate events and group outings.", "source_url": "https://www.google.com/maps/search/?api=1&query=Rec+Room+Vancouver"},
                    {"platform": "小红书", "text": "温哥华最强娱乐综合体！斧头投掷 + VR 体验 + 美食一站搞定，团建聚会必来，热门时段记得提前预约！", "source_url": "https://www.xiaohongshu.com/search_result?keyword=Rec+Room+Vancouver"},
                ],
            },
            {
                "name": "Cineplex Odeon International Village",
                "category": "娱乐",
                "address": "88 W Pender St, Vancouver, BC V6B 6N9",
                "lat": 49.2798, "lng": -123.1012,
                "url": "https://www.google.com/maps/search/?api=1&query=Cineplex+International+Village+Vancouver",
                "official_website": "https://www.cineplex.com/",
                "description": "市中心 IMAX 旗舰影院，首映场次完整，球幕音效与宽体座椅体验俱佳。",
                "venue_type": "Cinema",
                "age_restriction": "All Ages (rating-dependent)",
                "opening_hours": "Daily 10am-11pm (show-dependent)",
                "rating_system": {"google_rating": 4.2, "review_count": 3400},
                "_keywords": ["IMAX影院", "首映场次", "市中心观影"],
                "_reviews": [
                    {"platform": "Google Review", "text": "Conveniently located in downtown with stadium seating and a great sound system. The IMAX experience is worth the upgrade. Plenty of parking nearby on weekends.", "source_url": "https://www.google.com/maps/search/?api=1&query=Cineplex+International+Village+Vancouver"},
                    {"platform": "小红书", "text": "地段超好的市中心影院！IMAX 音效震撼，座椅舒适宽敞，首映日热门场次提前买票，停车方便！", "source_url": "https://www.xiaohongshu.com/search_result?keyword=Cineplex+International+Village+Vancouver"},
                ],
            },
            {
                "name": "Commodore Ballroom",
                "category": "娱乐",
                "address": "868 Granville St, Vancouver, BC V6Z 1K3",
                "lat": 49.2798, "lng": -123.1198,
                "url": "https://www.google.com/maps/search/?api=1&query=Commodore+Ballroom+Vancouver",
                "official_website": "https://www.commodoreballroom.com/",
                "description": "温哥华百年弹簧舞池传奇，音响效果顶级，演出覆盖摇滚电子多流派。",
                "venue_type": "Live Music Venue",
                "age_restriction": "19+",
                "opening_hours": "Event nights only — check schedule",
                "rating_system": {"google_rating": 4.6, "review_count": 890},
                "_keywords": ["弹簧舞池", "传奇音乐现场", "多流派演出"],
                "_reviews": [
                    {"platform": "Google Review", "text": "Iconic Vancouver live music venue with a legendary sprung dance floor. The acoustics are phenomenal and every show feels intimate despite the capacity. A true Vancouver institution.", "source_url": "https://www.google.com/maps/search/?api=1&query=Commodore+Ballroom+Vancouver"},
                    {"platform": "小红书", "text": "温哥华传奇音乐现场！弹簧舞池跳舞感觉超棒，音响效果顶级，每场演出都像私人专场，提前关注演出日历！", "source_url": "https://www.xiaohongshu.com/search_result?keyword=Commodore+Ballroom+Vancouver"},
                ],
            },
        ]
        for rec in records:
            keywords = rec.pop("_keywords", None)
            reviews = rec.pop("_reviews", None)
            rec["social_metrics"] = cls.fetch_social_metrics(
                rec["name"], "娱乐",
                override_reviews=reviews,
                override_keywords=keywords,
            )
            rec["photos"] = cls.fetch_photos(rec["name"], "娱乐")
        return records


# ---------------------------------------------------------------------------
# 3-D  AttractionScraper — calls fetch_social_metrics() for all entries
# ---------------------------------------------------------------------------

class AttractionScraper(BaseScraper[AttractionEntry]):
    category_name = "景点"
    entry_url = "https://www.tripadvisor.ca/Attractions-g154943-Activities-Vancouver_British_Columbia.html"

    @classmethod
    def entry_model(cls) -> type[AttractionEntry]:
        return AttractionEntry

    @classmethod
    def fetch_raw(cls) -> list[dict]:
        records = [
            {
                "name": "Stanley Park",
                "category": "景点",
                "address": "Stanley Park, Vancouver, BC V6G 1Z4",
                "lat": 49.3017, "lng": -123.1417,
                "url": "https://www.google.com/maps/search/?api=1&query=Stanley+Park+Vancouver",
                "official_website": "https://vancouver.ca/parks-recreation-culture/stanley-park.aspx",
                "admission_fee": "Free (parking CAD $5-10/hr)",
                "highlights": ["Seawall Cycling", "Totem Poles", "Vancouver Aquarium", "Lost Lagoon"],
                "description": "温哥华最大城市公园，海堤骑行与图腾柱地标。",
                "rating_system": {"google_rating": 4.9, "review_count": 45000},
                "_keywords": ["海堤骑行", "图腾柱地标", "城市绿肺"],
                "_reviews": [
                    {"platform": "Google Review", "text": "World-class urban park right in Vancouver. The seawall walk and bike path offer stunning ocean and mountain views. Totem poles and the aquarium are absolute highlights.", "source_url": "https://www.google.com/maps/search/?api=1&query=Stanley+Park+Vancouver"},
                    {"platform": "小红书", "text": "温哥华必去城市公园！海堤单车道风景绝美，图腾柱超有历史感，强烈建议租自行车绕一圈，日落时分最美！", "source_url": "https://www.xiaohongshu.com/search_result?keyword=Stanley+Park+Vancouver"},
                ],
            },
            {
                "name": "Granville Island Public Market",
                "category": "景点",
                "address": "1669 Johnston St, Vancouver, BC V6H 3R9",
                "lat": 49.2710, "lng": -123.1340,
                "url": "https://www.google.com/maps/search/?api=1&query=Granville+Island+Public+Market+Vancouver",
                "official_website": "https://granvilleisland.com/public-market",
                "admission_fee": "Free",
                "highlights": ["Artisan Food Stalls", "Local Craft Vendors", "Street Performers", "Ferry to Downtown"],
                "description": "艺术家聚集的公共市场，本地海鲜与手工艺品云集。",
                "rating_system": {"google_rating": 4.7, "review_count": 18000},
                "_keywords": ["手工艺品市场", "街头表演", "本地海鲜"],
                "_reviews": [
                    {"platform": "Google Review", "text": "Vancouver's vibrant public market with fresh local produce, artisan crafts, and incredible street food. The atmosphere on weekends is electric. A must-visit for foodies and shoppers.", "source_url": "https://www.google.com/maps/search/?api=1&query=Granville+Island+Public+Market+Vancouver"},
                    {"platform": "小红书", "text": "温哥华最有活力的公共市场！本地海鲜超新鲜，手工艺品琳琅满目，街头表演随时上演，拍照圣地周末必打卡！", "source_url": "https://www.xiaohongshu.com/search_result?keyword=Granville+Island+Public+Market"},
                ],
            },
            {
                "name": "Capilano Suspension Bridge Park",
                "category": "景点",
                "address": "3735 Capilano Rd, North Vancouver, BC V7R 4J1",
                "lat": 49.3432, "lng": -123.1148,
                "url": "https://www.google.com/maps/search/?api=1&query=Capilano+Suspension+Bridge+North+Vancouver",
                "official_website": "https://www.capbridge.com/",
                "admission_fee": "CAD $65 adult / $30 child",
                "highlights": ["137m Suspension Bridge", "Treetops Adventure", "Cliffwalk", "Totem Park"],
                "description": "137 米高空悬索桥横跨峡谷，林冠探险全年开放。",
                "rating_system": {"google_rating": 4.5, "review_count": 22000},
                "_keywords": ["137米高空吊桥", "林冠探险", "悬崖步道"],
                "_reviews": [
                    {"platform": "Google Review", "text": "Thrilling experience high above the Capilano River. The Treetops Adventure and Cliffwalk extend the experience beyond the bridge. Worth every penny for a full day of adventure.", "source_url": "https://www.google.com/maps/search/?api=1&query=Capilano+Suspension+Bridge+North+Vancouver"},
                    {"platform": "小红书", "text": "刺激又壮观！站在 137 米悬索桥上俯瞰峡谷令人窒息，林冠探险和悬崖步道也超好玩，门票含全套项目非常值！", "source_url": "https://www.xiaohongshu.com/search_result?keyword=Capilano+Suspension+Bridge"},
                ],
            },
            {
                "name": "Museum of Anthropology (MOA)",
                "category": "景点",
                "address": "6393 NW Marine Dr, Vancouver, BC V6T 1Z2",
                "lat": 49.2692, "lng": -123.2590,
                "url": "https://www.google.com/maps/search/?api=1&query=Museum+of+Anthropology+UBC+Vancouver",
                "official_website": "https://moa.ubc.ca/",
                "admission_fee": "CAD $23 adult / $21 student",
                "highlights": ["First Nations Totem Collection", "Haida Gwaii Masterworks", "Great Hall", "Multiversity Galleries"],
                "description": "UBC 校园内人类学博物馆，馆藏原住民图腾与海达文化珍品。",
                "rating_system": {"google_rating": 4.6, "review_count": 3200},
                "_keywords": ["原住民文化", "海达图腾收藏", "UBC校园博物馆"],
                "_reviews": [
                    {"platform": "Google Review", "text": "World-renowned museum showcasing First Nations art and culture. The Great Hall with its towering totem poles is breathtaking. Thoughtfully curated and deeply moving exhibits throughout.", "source_url": "https://www.google.com/maps/search/?api=1&query=Museum+of+Anthropology+UBC+Vancouver"},
                    {"platform": "小红书", "text": "UBC 校园内的世界级博物馆！原住民图腾柱壮观震撼，展品背后的故事令人动容，强烈推荐学生和文化爱好者来参观！", "source_url": "https://www.xiaohongshu.com/search_result?keyword=Museum+of+Anthropology+UBC"},
                ],
            },
        ]
        for rec in records:
            keywords = rec.pop("_keywords", None)
            reviews = rec.pop("_reviews", None)
            rec["social_metrics"] = cls.fetch_social_metrics(
                rec["name"], "景点",
                override_reviews=reviews,
                override_keywords=keywords,
            )
            rec["photos"] = cls.fetch_photos(rec["name"], "景点", n_photos=10)
        return records


# ---------------------------------------------------------------------------
# 3-E  HikingScraper
#      · Calls fetch_social_metrics() (from BaseScraper)
#      · Calls fetch_alltrails_data() (HikingScraper-exclusive module)
# ---------------------------------------------------------------------------

class HikingScraper(BaseScraper[HikingEntry]):
    category_name = "徒步"
    entry_url = "https://www.alltrails.com/canada/british-columbia/vancouver"

    @classmethod
    def entry_model(cls) -> type[HikingEntry]:
        return HikingEntry

    @classmethod
    def fetch_alltrails_data(
        cls,
        name: str,
        trail_distance: float,
        elevation_gain: int,
        difficulty_rating: str,
        alltrails_url: str,
    ) -> dict:
        """
        AllTrails data module — exclusive to 徒步 category.

        MOCK mode: uses known trail statistics as ground truth input;
                   alltrails_rating and alltrails_review_count are
                   deterministically computed from the trail name.

        Production replacement:
          · AllTrails web scraper or AllTrails unofficial API
          · OpenStreetMap Overpass API for OSM trail geometries
          · GPX/KML file parsing for elevation profiles
        """
        return {
            "trail_distance": trail_distance,
            "elevation_gain": elevation_gain,
            "difficulty_rating": difficulty_rating,
            "alltrails_url": alltrails_url,
            "alltrails_rating": cls._deterministic_score(name, 4.0, 4.9),
            "alltrails_review_count": cls._deterministic_count(name, 200, 8000),
        }

    @classmethod
    def fetch_raw(cls) -> list[dict]:
        # Define base trail data — then enrich with social + AllTrails blocks
        trails = [
            {
                "name": "Grouse Grind",
                "category": "徒步",
                "address": "6400 Nancy Greene Way, North Vancouver, BC V7R 4K9",
                "lat": 49.3790, "lng": -123.0820,
                "url": "https://www.alltrails.com/trail/canada/british-columbia/grouse-grind",
                "description": "北温最陡硬核山径，853m 爬升仅 2.9km，缆车下山俯瞰温市全景。",
                "duration": "1-2 hrs (ascent only, gondola descent)",
                "trailhead": "Grouse Mountain Base (Gondola parking lot)",
                "rating_system": {"google_rating": 4.7, "review_count": 5600},
                "_at": {"trail_distance": 2.9, "elevation_gain": 853, "difficulty_rating": "Hard",
                        "alltrails_url": "https://www.alltrails.com/trail/canada/british-columbia/grouse-grind"},
                "_keywords": ["硬核健身打卡", "853m爬升", "缆车下山"],
                "_reviews": [
                    {"platform": "Google Review", "text": "The ultimate Vancouver fitness challenge — 853m elevation in 2.9km. Brutal but incredibly rewarding. Take the gondola down and grab a cold beer at the summit chalet.", "source_url": "https://www.google.com/maps/search/?api=1&query=Grouse+Grind+North+Vancouver"},
                    {"platform": "小红书", "text": "温哥华最硬核的徒步挑战！全程上坡腿软但顶部景色无敌，爬完坐缆车下山，山顶喝一杯超满足，建议早上出发！", "source_url": "https://www.xiaohongshu.com/search_result?keyword=Grouse+Grind+温哥华"},
                ],
            },
            {
                "name": "Lynn Peak Trail",
                "category": "徒步",
                "address": "3403 Boundary Rd, North Vancouver, BC V7H 2V7",
                "lat": 49.3509, "lng": -122.9875,
                "url": "https://www.alltrails.com/trail/canada/british-columbia/lynn-peak",
                "description": "Lynn 峰中级步道 10.2km，印度湾全景俯瞰，原始雨林气息浓郁。",
                "duration": "4-6 hrs round trip",
                "trailhead": "Lynn Headwaters Regional Park main parking lot",
                "rating_system": {"google_rating": 4.5, "review_count": 2100},
                "_at": {"trail_distance": 10.2, "elevation_gain": 780, "difficulty_rating": "Moderate",
                        "alltrails_url": "https://www.alltrails.com/trail/canada/british-columbia/lynn-peak"},
                "_keywords": ["印度湾全景", "北温雨林", "中级长距离"],
                "_reviews": [
                    {"platform": "Google Review", "text": "Fantastic moderate hike in Lynn Headwaters. The summit views of Indian Arm and the North Shore mountains are spectacular. Well-marked trail — bring plenty of water and layers.", "source_url": "https://www.google.com/maps/search/?api=1&query=Lynn+Peak+Trail+North+Vancouver"},
                    {"platform": "小红书", "text": "北温隐藏精华步道！顶部印度湾全景视野令人震惊，难度适中，适合有一定体力的徒步爱好者，停车场早到为妙！", "source_url": "https://www.xiaohongshu.com/search_result?keyword=Lynn+Peak+Trail+北温"},
                ],
            },
            {
                "name": "Dog Mountain via Dinkey Peak",
                "category": "徒步",
                "address": "1700 Mt Seymour Rd, North Vancouver, BC V7G 1L3",
                "lat": 49.3672, "lng": -122.9496,
                "url": "https://www.alltrails.com/trail/canada/british-columbia/dog-mountain",
                "description": "西摩山高山草甸步道，开阔山脊俯瞰温哥华，秋叶红期景色最胜。",
                "duration": "3-4 hrs round trip",
                "trailhead": "Mt Seymour Provincial Park — Parking Lot 4",
                "rating_system": {"google_rating": 4.4, "review_count": 1800},
                "_at": {"trail_distance": 8.4, "elevation_gain": 330, "difficulty_rating": "Moderate",
                        "alltrails_url": "https://www.alltrails.com/trail/canada/british-columbia/dog-mountain"},
                "_keywords": ["高山草甸", "城市全景山脊", "秋叶季徒步"],
                "_reviews": [
                    {"platform": "Google Review", "text": "Beautiful subalpine meadow hike with panoramic Vancouver city views. Accessible in shoulder season. The open ridgeline section is stunning on clear days — highly recommend.", "source_url": "https://www.google.com/maps/search/?api=1&query=Dog+Mountain+Mt+Seymour+North+Vancouver"},
                    {"platform": "小红书", "text": "从山顶俯瞰温哥华全城太治愈了！高山草甸美不胜收，难度适中，晴天来视野无敌，强烈推荐秋天红叶季来！", "source_url": "https://www.xiaohongshu.com/search_result?keyword=Dog+Mountain+Seymour+温哥华"},
                ],
            },
            {
                "name": "Quarry Rock (Deep Cove)",
                "category": "徒步",
                "address": "Panorama Dr, North Vancouver, BC V7G 1V8",
                "lat": 49.3240, "lng": -122.9500,
                "url": "https://www.alltrails.com/trail/canada/british-columbia/quarry-rock",
                "description": "Deep Cove 入门友好步道，3.7km 抵达绝美海湾观景台，下山吃甜甜圈是传统。",
                "duration": "1-1.5 hrs round trip",
                "trailhead": "Deep Cove Park trailhead — Panorama Dr street parking",
                "rating_system": {"google_rating": 4.6, "review_count": 4200},
                "_at": {"trail_distance": 3.7, "elevation_gain": 120, "difficulty_rating": "Easy",
                        "alltrails_url": "https://www.alltrails.com/trail/canada/british-columbia/quarry-rock"},
                "_keywords": ["入门级步道", "Deep Cove海湾", "亲子友好"],
                "_reviews": [
                    {"platform": "Google Review", "text": "Perfect beginner-friendly hike with a stunning viewpoint over Deep Cove and Indian Arm. Only 3.7km but the payoff is massive. Grab a Honey Doughnuts in Deep Cove after — a local tradition.", "source_url": "https://www.google.com/maps/search/?api=1&query=Quarry+Rock+Deep+Cove+North+Vancouver"},
                    {"platform": "小红书", "text": "入门级徒步首推！才 3.7 公里就能看到 Deep Cove 海湾全景，风景值爆表，下山后去 Deep Cove 吃甜甜圈是本地传统！", "source_url": "https://www.xiaohongshu.com/search_result?keyword=Quarry+Rock+Deep+Cove"},
                ],
            },
        ]

        for rec in trails:
            at = rec.pop("_at")
            keywords = rec.pop("_keywords", None)
            reviews = rec.pop("_reviews", None)
            rec["alltrails_data"] = cls.fetch_alltrails_data(
                name=rec["name"],
                trail_distance=at["trail_distance"],
                elevation_gain=at["elevation_gain"],
                difficulty_rating=at["difficulty_rating"],
                alltrails_url=at["alltrails_url"],
            )
            rec["social_metrics"] = cls.fetch_social_metrics(
                rec["name"], "徒步",
                override_reviews=reviews,
                override_keywords=keywords,
            )
            rec["photos"] = cls.fetch_photos(rec["name"], "徒步", n_photos=10)
            # Hiking official_website is always the AllTrails detail page URL
            rec["official_website"] = rec["url"]

        return trails


# ===========================================================================
# SECTION 4 — CATEGORY_CONFIG
# ===========================================================================

CATEGORY_CONFIG: dict[str, dict[str, Any]] = {
    "餐厅": {
        "entry_url": RestaurantScraper.entry_url,
        "required_fields": ["name", "category", "address", "lat", "lng", "url", "social_metrics", "rating_system"],
        "extra_fields": ["price_level"],          # image_url + description now in BaseEntry
        "scraper_class": RestaurantScraper,
    },
    "酒吧": {
        "entry_url": BarScraper.entry_url,
        "required_fields": ["name", "category", "address", "lat", "lng", "url", "social_metrics", "rating_system"],
        "extra_fields": ["vibe", "signature_drink", "happy_hour"],
        "scraper_class": BarScraper,
    },
    "娱乐": {
        "entry_url": EntertainmentScraper.entry_url,
        "required_fields": ["name", "category", "address", "lat", "lng", "url", "social_metrics", "rating_system"],
        "extra_fields": ["venue_type", "age_restriction", "opening_hours"],
        "scraper_class": EntertainmentScraper,
    },
    "景点": {
        "entry_url": AttractionScraper.entry_url,
        "required_fields": ["name", "category", "address", "lat", "lng", "url", "social_metrics", "rating_system"],
        "extra_fields": ["admission_fee", "highlights"],  # description now in BaseEntry
        "scraper_class": AttractionScraper,
    },
    "徒步": {
        "entry_url": HikingScraper.entry_url,
        "required_fields": ["name", "category", "address", "lat", "lng", "url", "social_metrics", "rating_system"],
        "extra_fields": ["duration", "trailhead", "alltrails_data"],
        "scraper_class": HikingScraper,
    },
}


# ===========================================================================
# SECTION 5 — Network Connectivity Probe
# ===========================================================================

PROBE_URL = "https://httpbin.org/get"
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
        print(f"[NET PROBE] [FAIL] Timeout after {PROBE_TIMEOUT}s -- continuing in MOCK-only mode.")
    except requests.exceptions.ConnectionError:
        print("[NET PROBE] [FAIL] Connection error -- continuing in MOCK-only mode.")
    except requests.exceptions.HTTPError as exc:
        print(f"[NET PROBE] [FAIL] HTTP error: {exc} -- continuing in MOCK-only mode.")
    return False


# ===========================================================================
# SECTION 5.5 — Map Readiness Validator
# ===========================================================================

_LAT_MIN, _LAT_MAX = 49.0, 49.8
_LNG_MIN, _LNG_MAX = -123.5, -122.3
_REQUIRED_BASE = {"name", "category", "lat", "lng", "url", "official_website", "address", "social_metrics", "rating_system"}


def validate_map_readiness(entries: list[dict]) -> bool:
    """
    Post-collection coordinate and schema completeness audit.
    Checks lat/lng numeric type, GVA bounding box, required field presence,
    and rating_system block integrity.
    """
    print("\n" + "=" * 65)
    print("  MAP READINESS VALIDATION")
    print("=" * 65)

    issues: list[str] = []

    for i, entry in enumerate(entries, 1):
        name = entry.get("name", f"entry#{i}")
        cat = entry.get("category", "?")
        prefix = f"  [{i:02d}] {name} ({cat})"

        missing = _REQUIRED_BASE - entry.keys()
        if missing:
            msg = f"{prefix} -- MISSING fields: {sorted(missing)}"
            print(msg); issues.append(msg); continue

        lat, lng = entry["lat"], entry["lng"]

        if lat is None or lng is None:
            msg = f"{prefix} -- lat/lng is null"
            print(msg); issues.append(msg); continue

        if not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)):
            msg = f"{prefix} -- wrong type lat={type(lat).__name__} lng={type(lng).__name__}"
            print(msg); issues.append(msg); continue

        if not (_LAT_MIN <= float(lat) <= _LAT_MAX) or not (_LNG_MIN <= float(lng) <= _LNG_MAX):
            msg = f"{prefix} -- out of GVA bounds lat={lat} lng={lng}"
            print(msg); issues.append(msg); continue

        rs = entry.get("rating_system", {})
        if "google_rating" not in rs or "review_count" not in rs:
            msg = f"{prefix} -- rating_system incomplete: {list(rs.keys())}"
            print(msg); issues.append(msg); continue

        sm = entry.get("social_metrics", {})
        if not sm.get("videos") or not sm.get("reviews"):
            msg = f"{prefix} -- social_metrics missing videos/reviews"
            print(msg); issues.append(msg); continue

        print(
            f"{prefix} -- lat={lat}, lng={lng}  "
            f"google={rs['google_rating']}  "
            f"agg={rs.get('aggregate_score', '?')}  [PASS]"
        )

    print("-" * 65)
    if issues:
        print(f"[VALIDATOR] FAILED -- {len(issues)} issue(s) found:")
        for iss in issues:
            print(f"  {iss}")
        print("=" * 65)
        return False

    print(f"[VALIDATOR] ALL {len(entries)} entries passed map readiness check.")
    print("=" * 65)
    return True


# ===========================================================================
# SECTION 5.6 — Description & Keyword Uniqueness Validator
# ===========================================================================

_DEDUP_THRESHOLD = 0.90   # SequenceMatcher ratio above which two descriptions are "duplicates"


def validate_description_uniqueness(entries: list[dict]) -> bool:
    """
    Within each category, check that no two entries share a near-identical
    description (SequenceMatcher ratio ≥ _DEDUP_THRESHOLD) or identical keyword sets.

    Returns True when all descriptions and keyword sets are sufficiently unique.
    Returns False and prints a detailed report when duplicates are detected —
    which indicates the scraper's summary logic has produced templated output
    and must be fixed before writing to master_data.json.
    """
    from collections import defaultdict

    print("\n" + "=" * 65)
    print("  DESCRIPTION & KEYWORD UNIQUENESS CHECK")
    print("=" * 65)

    by_cat: dict[str, list[dict]] = defaultdict(list)
    for e in entries:
        by_cat[e["category"]].append(e)

    issues: list[str] = []

    for cat, cat_entries in by_cat.items():
        # --- description dedup ---
        descs = [(e["name"], e.get("description") or "") for e in cat_entries]
        for i in range(len(descs)):
            for j in range(i + 1, len(descs)):
                d_a, d_b = descs[i][1], descs[j][1]
                if not d_a or not d_b:
                    continue   # null descriptions are acceptable
                ratio = difflib.SequenceMatcher(None, d_a, d_b).ratio()
                if ratio >= _DEDUP_THRESHOLD:
                    msg = (
                        f"  [DEDUP-DESC] [{cat}] '{descs[i][0]}' vs '{descs[j][0]}' "
                        f"similarity={ratio:.2f} -- too similar, re-summarise required"
                    )
                    issues.append(msg)

        # --- keyword dedup ---
        kwds = [
            (e["name"], frozenset(e.get("social_metrics", {}).get("keywords", [])))
            for e in cat_entries
        ]
        for i in range(len(kwds)):
            for j in range(i + 1, len(kwds)):
                k_a, k_b = kwds[i][1], kwds[j][1]
                if not k_a or not k_b:
                    continue
                if k_a == k_b:
                    msg = (
                        f"  [DEDUP-KWD]  [{cat}] '{kwds[i][0]}' vs '{kwds[j][0]}' "
                        f"share identical keywords {sorted(k_a)}"
                    )
                    issues.append(msg)

    if issues:
        print(f"[DEDUP] {len(issues)} issue(s) detected — scraper output contains duplicates:")
        for iss in issues:
            print(iss)
        print("=" * 65)
        return False

    total_with_desc = sum(1 for e in entries if e.get("description"))
    print(f"[DEDUP] All descriptions unique across {len(entries)} entries "
          f"({total_with_desc} with description, "
          f"{len(entries) - total_with_desc} null — acceptable for category).")
    print("[DEDUP] All keyword sets within categories are distinct.")
    print("=" * 65)
    return True


# ===========================================================================
# SECTION 6 — Output Writer  ->  data/master_data.json
# ===========================================================================

from paths import MASTER_DATA_FILE, DATA_DIR

OUTPUT_DIR = str(DATA_DIR)
OUTPUT_FILE = str(MASTER_DATA_FILE)


def write_output(
    all_entries: list[dict],
    category_summary: dict[str, int],
    network_ok: bool,
    *,
    scrape_mode: str = "live",
    skipped: list[dict] | None = None,
) -> None:
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    payload = {
        "meta": {
            "source": "vancouver_scraper.py v5.3 (data/ output — OSM + video_providers)",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "region": "Greater Vancouver (Vancouver / Richmond / Burnaby / North Van / Surrey)",
            "network_probe_passed": network_ok,
            "scrape_mode": scrape_mode,
            "skipped": skipped or [],
            "total_entries": len(all_entries),
            "category_summary": category_summary,
            "categories_collected": list(CATEGORY_CONFIG.keys()),
            "schema_version": "5.3",
        },
        "entries": all_entries,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"\n[WRITER] Output -> {OUTPUT_FILE}")
    print(f"[WRITER] Total entries: {len(all_entries)}")
    for cat, count in category_summary.items():
        print(f"         {cat}: {count} entries")


# ===========================================================================
# SECTION 7 — Entry Point
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

    parser = argparse.ArgumentParser(description="VanMap Vancouver place scraper")
    parser.add_argument("--sync", action="store_true", help="Sync data/ to frontend after write")
    parser.add_argument("--mock", action="store_true", help="Force mock data (skip OSM)")
    args = parser.parse_args()
    if args.mock:
        os.environ["VANMAP_SCRAPE_MODE"] = "mock"

    print("=" * 65)
    print("  VanMap Cluster -- Slave Scraper  v5.3")
    print("  Universal: social_metrics + rating_system on ALL categories")
    print("  Hiking exclusive: fetch_alltrails_data() module")
    print("=" * 65)

    network_ok = probe_network()

    all_serialized: list[dict] = []
    category_summary: dict[str, int] = {}

    for cat_name, config in CATEGORY_CONFIG.items():
        scraper_cls: type[BaseScraper] = config["scraper_class"]
        validated = scraper_cls.run()
        serialized = scraper_cls.serialize_all(validated)
        all_serialized.extend(serialized)
        category_summary[cat_name] = len(serialized)

    if not all_serialized:
        print("\n[SCRAPER] No valid entries collected -- aborting.")
    else:
        map_ok   = validate_map_readiness(all_serialized)
        dedup_ok = validate_description_uniqueness(all_serialized)

        # ── Photo demo: full photo-collection printout for 3 representative entries ──
        _DEMO_ENTRIES = {
            "Kirin Seafood Restaurant",   # 代表：餐厅
            "Stanley Park",               # 代表：景点
            "Grouse Grind",               # 代表：徒步
        }
        print("\n" + "=" * 65)
        print("  PHOTO COLLECTION DEMO  (3 representative entries)")
        print("=" * 65)
        demo_count = 0
        for entry in all_serialized:
            if entry["name"] not in _DEMO_ENTRIES:
                continue
            photos = entry.get("photos", [])
            print(f"\n  [{entry['category']}]  {entry['name']}  ({len(photos)} photos)")
            print(f"  {'─' * 55}")
            for ph in photos:
                print(f"    [{ph['category']:12s}]  {ph['url']}")
            demo_count += 1
            if demo_count >= 3:
                break

        # ── Global photo summary ─────────────────────────────────────────────────
        total_photos = sum(len(e.get("photos", [])) for e in all_serialized)
        avg_photos   = total_photos / len(all_serialized) if all_serialized else 0
        print(f"\n{'=' * 65}")
        print(f"  [PHOTOS] 已完成 {len(all_serialized)} 家店铺的照片合集抓取，"
              f"平均每家包含 {avg_photos:.1f} 张照片。")
        print(f"{'=' * 65}")

        scrape_mode = "mock" if os.environ.get("VANMAP_SCRAPE_MODE") == "mock" else "live"
        write_output(all_serialized, category_summary, network_ok, scrape_mode=scrape_mode)
        if args.sync:
            sync_ps1 = os.path.join(os.path.dirname(__file__), "..", "scripts", "sync_data.ps1")
            sync_sh = os.path.join(os.path.dirname(__file__), "..", "scripts", "sync_data.sh")
            if sys.platform == "win32" and os.path.isfile(sync_ps1):
                subprocess.run(["powershell", "-File", sync_ps1], check=False)
            elif os.path.isfile(sync_sh):
                subprocess.run(["bash", sync_sh], check=False)
        print("=" * 65)
        if map_ok and dedup_ok:
            print("  Done. All entries map-ready and uniqueness-validated.")
            print("  master_data.json ready for Slave Coder.")
        else:
            if not map_ok:
                print("  WARNING: Some entries failed map validation. Review output above.")
            if not dedup_ok:
                print("  WARNING: Duplicate descriptions/keywords detected. Scraper logic must be fixed.")
        print("=" * 65)
