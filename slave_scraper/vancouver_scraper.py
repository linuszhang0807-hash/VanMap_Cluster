"""
Vancouver Restaurant Intelligence Scraper — v3
------------------------------------------------
Slave Scraper Module — VanMap Cluster
v3 changes:
  · videos[].url  → real platform search query links (YouTube / TikTok)
  · reviews[]     → added source_url field (Google Maps / 小红书 search links)
  · Review Pydantic model updated accordingly
Output: shared_data/restaurants.json
"""

from __future__ import annotations

import json
import os
import statistics
from datetime import datetime, timezone
from typing import Literal

import requests
from pydantic import BaseModel, Field, computed_field, model_validator

# ===========================================================================
# 1. Pydantic Data Models
# ===========================================================================

Platform = Literal["TikTok", "YouTube"]
ReviewPlatform = Literal["Google Review", "小红书"]
# Category is now open str to support future types like "酒吧", "徒步", etc.


class VideoClip(BaseModel):
    platform: Platform
    url: str       # real search-query link — clickable, opens platform search
    summary: str


class Review(BaseModel):
    platform: ReviewPlatform
    text: str
    source_url: str  # clickable deep-link to Google Maps or 小红书 search


class Ratings(BaseModel):
    google: float = Field(ge=0.0, le=5.0)
    xiaohongshu: float = Field(ge=0.0, le=5.0)

    @computed_field
    @property
    def aggregate_score(self) -> float:
        return round(statistics.mean([self.google, self.xiaohongshu]), 2)


class Restaurant(BaseModel):
    name: str
    category: str          # open string — no Literal restriction
    price_level: str       # e.g. "$", "$$", "$$$", "$$$$"
    address: str
    image_url: str
    lat: float = Field(ge=49.0, le=49.4)
    lng: float = Field(ge=-123.3, le=-122.6)
    description: str
    videos: list[VideoClip] = Field(min_length=1)
    reviews: list[Review] = Field(min_length=1)
    keywords: list[str] = Field(min_length=3, max_length=5)
    ratings: Ratings

    @model_validator(mode="after")
    def check_keywords_non_empty(self) -> "Restaurant":
        if any(not kw.strip() for kw in self.keywords):
            raise ValueError("keywords must not contain blank strings")
        return self


# ===========================================================================
# 2. MOCK Intelligence Dataset — 8 Greater Vancouver restaurants
#    videos[].url  : YouTube/TikTok search-query links (real, clickable)
#    reviews[].source_url : Google Maps Places API link / 小红书 search link
# ===========================================================================

RAW_INTELLIGENCE: list[dict] = [
    # -----------------------------------------------------------------------
    {
        "name": "Kirin Seafood Restaurant",
        "category": "中餐",
        "price_level": "$$$",
        "address": "1166 Alberni St, Vancouver, BC V6E 1A5",
        "image_url": "https://www.google.com/maps/search/?api=1&query=Kirin+Seafood+Restaurant+Vancouver",
        "lat": 49.2827,
        "lng": -123.1207,
        "description": "Downtown 经典粤菜海鲜楼，炭烧叉烧与清蒸游水海鲜是招牌，商务宴请首选。",
        "videos": [
            {
                "platform": "YouTube",
                "url": "https://www.youtube.com/results?search_query=Kirin+Seafood+Restaurant+Vancouver",
                "summary": "食评人深探 Kirin 全菜单，重点试吃清蒸龙虾与片皮鸭，厨房近距离揭秘。",
            },
            {
                "platform": "TikTok",
                "url": "https://www.tiktok.com/search?q=Kirin+Seafood+Restaurant+Vancouver+dim+sum",
                "summary": "周末早茶 vlog：推车点心实况，虾饺皮薄透明引发弹幕刷屏。",
            },
        ],
        "reviews": [
            {
                "platform": "Google Review",
                "text": "Hands down the best Cantonese in Downtown. The steamed fish is incredible — perfectly seasoned.",
                "source_url": "https://www.google.com/maps/search/?api=1&query=Kirin+Seafood+Restaurant+Vancouver",
            },
            {
                "platform": "小红书",
                "text": "叉烧是全温哥华最嫩的那种，肥瘦比例完美，配白饭能吃三碗！强烈推荐给第一次来的朋友。",
                "source_url": "https://www.xiaohongshu.com/search_result?keyword=Kirin+Seafood+Vancouver",
            },
        ],
        "keywords": ["粤菜海鲜", "商务宴请", "炭烧叉烧"],
        "ratings": {"google": 4.5, "xiaohongshu": 4.7},
    },
    # -----------------------------------------------------------------------
    {
        "name": "Sura Korean Cuisine",
        "category": "韩餐",
        "price_level": "$$$",
        "address": "1262 Robson St, Vancouver, BC V6E 1C1",
        "image_url": "https://www.google.com/maps/search/?api=1&query=Sura+Korean+Cuisine+Vancouver",
        "lat": 49.2836,
        "lng": -123.1193,
        "description": "Downtown 精致韩餐，宫廷风格摆盘，烤牛肋骨与海鲜煎饼受本地食客高度评价。",
        "videos": [
            {
                "platform": "YouTube",
                "url": "https://www.youtube.com/results?search_query=Sura+Korean+Cuisine+Vancouver",
                "summary": "温哥华美食频道专题：Sura 宫廷套餐全流程，7 道菜一镜到底展示。",
            },
            {
                "platform": "TikTok",
                "url": "https://www.tiktok.com/search?q=Sura+Korean+Cuisine+Vancouver+galbi",
                "summary": "炭火烤牛肋骨特写，油脂滴落瞬间引来百万次观看。",
            },
        ],
        "reviews": [
            {
                "platform": "Google Review",
                "text": "Authentic royal court presentation. The galbi is melt-in-your-mouth good and the banchan variety is impressive.",
                "source_url": "https://www.google.com/maps/search/?api=1&query=Sura+Korean+Cuisine+Vancouver",
            },
            {
                "platform": "小红书",
                "text": "宫廷摆盘真的太美了，拍照出片率极高！海鲜煎饼外酥里嫩，配막걸리一绝。",
                "source_url": "https://www.xiaohongshu.com/search_result?keyword=Sura+Korean+Vancouver",
            },
        ],
        "keywords": ["宫廷韩餐", "烤牛肋骨", "精致摆盘"],
        "ratings": {"google": 4.6, "xiaohongshu": 4.9},
    },
    # -----------------------------------------------------------------------
    {
        "name": "Golden Great Wall Restaurant",
        "category": "中餐",
        "price_level": "$$",
        "address": "4540 No. 3 Rd, Richmond, BC V6X 2C2",
        "image_url": "https://www.google.com/maps/search/?api=1&query=Golden+Great+Wall+Restaurant+Richmond",
        "lat": 49.1628,
        "lng": -123.1369,
        "description": "Richmond 人气早茶老店，虾饺、肠粉、萝卜糕必点，周末翻台率极高。",
        "videos": [
            {
                "platform": "TikTok",
                "url": "https://www.tiktok.com/search?q=Golden+Great+Wall+dim+sum+Richmond+Vancouver",
                "summary": "Richmond 早茶大挑战：单人一小时内吃遍推车菜单，结局超预期。",
            },
            {
                "platform": "YouTube",
                "url": "https://www.youtube.com/results?search_query=Golden+Great+Wall+Restaurant+Richmond+dim+sum",
                "summary": "本地华人博主带父母吃早茶，萝卜糕做法同款复刻对比评测。",
            },
        ],
        "reviews": [
            {
                "platform": "Google Review",
                "text": "Best dim sum in Richmond, period. Show up by 9am or prepare to wait 45 minutes on weekends.",
                "source_url": "https://www.google.com/maps/search/?api=1&query=Golden+Great+Wall+Restaurant+Richmond+BC",
            },
            {
                "platform": "小红书",
                "text": "肠粉皮薄如纸，虾饺馅料饱满，推车阿姨会粤语、普通话随时切换，服务特别亲切！",
                "source_url": "https://www.xiaohongshu.com/search_result?keyword=Golden+Great+Wall+Richmond+早茶",
            },
        ],
        "keywords": ["排队圣地", "周末早茶", "虾饺肠粉"],
        "ratings": {"google": 4.4, "xiaohongshu": 4.6},
    },
    # -----------------------------------------------------------------------
    {
        "name": "New Town Bakery & Restaurant",
        "category": "中餐",
        "price_level": "$",
        "address": "148 E Pender St, Vancouver, BC V6A 1T3",
        "image_url": "https://www.google.com/maps/search/?api=1&query=New+Town+Bakery+Restaurant+Vancouver",
        "lat": 49.2800,
        "lng": -123.1017,
        "description": "Chinatown 老字号，蜜糖叉烧包与鸡尾包是几十年不变的招牌，下午茶必去。",
        "videos": [
            {
                "platform": "YouTube",
                "url": "https://www.youtube.com/results?search_query=New+Town+Bakery+Restaurant+Vancouver+Chinatown",
                "summary": "温哥华 Chinatown 消失中的老字号系列第一集：New Town 半世纪的烘焙故事。",
            },
            {
                "platform": "TikTok",
                "url": "https://www.tiktok.com/search?q=New+Town+Bakery+Vancouver+BBQ+pork+bun",
                "summary": "叉烧包现烤出炉慢动作，蜜糖焦面瞬间点击量超 50 万。",
            },
        ],
        "reviews": [
            {
                "platform": "Google Review",
                "text": "A Chinatown institution. The BBQ pork buns are legendary — crispy top, sweet-savory filling, timeless.",
                "source_url": "https://www.google.com/maps/search/?api=1&query=New+Town+Bakery+Restaurant+Vancouver",
            },
            {
                "platform": "小红书",
                "text": "鸡尾包是真的被低估！酥皮配椰蓉馅，甜度刚好，配一杯港式奶茶完美收尾。",
                "source_url": "https://www.xiaohongshu.com/search_result?keyword=New+Town+Bakery+温哥华+叉烧包",
            },
        ],
        "keywords": ["Chinatown老字号", "蜜糖叉烧包", "下午茶情怀"],
        "ratings": {"google": 4.3, "xiaohongshu": 4.5},
    },
    # -----------------------------------------------------------------------
    {
        "name": "Gyo-O Korean BBQ",
        "category": "韩餐",
        "price_level": "$$",
        "address": "4501 Kingsway, Burnaby, BC V5H 2A9",
        "image_url": "https://www.google.com/maps/search/?api=1&query=Gyo-O+Korean+BBQ+Burnaby",
        "lat": 49.2285,
        "lng": -122.9981,
        "description": "Burnaby 本地最火烤肉店，牛舌与五花肉套餐配无限续杯小菜，性价比极高。",
        "videos": [
            {
                "platform": "TikTok",
                "url": "https://www.tiktok.com/search?q=Gyo-O+Korean+BBQ+Burnaby+Vancouver",
                "summary": "深夜烤肉实况：Gyo-O 单人自助挑战，小菜续了 7 次的真实记录。",
            },
            {
                "platform": "YouTube",
                "url": "https://www.youtube.com/results?search_query=Gyo-O+Korean+BBQ+Burnaby",
                "summary": "Burnaby 韩烤横向评测第一名，Gyo-O 牛舌 vs 和牛五花盲测对决。",
            },
        ],
        "reviews": [
            {
                "platform": "Google Review",
                "text": "Unlimited banchan refills and the beef tongue is buttery smooth. Best KBBQ value in Greater Vancouver.",
                "source_url": "https://www.google.com/maps/search/?api=1&query=Gyo-O+Korean+BBQ+Burnaby+BC",
            },
            {
                "platform": "小红书",
                "text": "五花肉切得厚度刚好，烤到微焦卷着生菜吃，再喝口啤酒，这就是幸福的味道。小菜不限续，强烈推荐！",
                "source_url": "https://www.xiaohongshu.com/search_result?keyword=Gyo-O+韩式烤肉+Burnaby",
            },
        ],
        "keywords": ["深夜烤肉", "小菜无限续", "性价比之王"],
        "ratings": {"google": 4.5, "xiaohongshu": 4.8},
    },
    # -----------------------------------------------------------------------
    {
        "name": "Hanwoori Korean Restaurant",
        "category": "韩餐",
        "price_level": "$$",
        "address": "8460 Hazelbridge Way, Richmond, BC V6X 3L9",
        "image_url": "https://www.google.com/maps/search/?api=1&query=Hanwoori+Korean+Restaurant+Richmond",
        "lat": 49.1664,
        "lng": -123.1338,
        "description": "Richmond 韩餐代表，石锅拌饭与部队锅正宗，辣白菜自家腌制，口碑稳定。",
        "videos": [
            {
                "platform": "TikTok",
                "url": "https://www.tiktok.com/search?q=Hanwoori+Korean+Restaurant+Richmond+bibimbap",
                "summary": "石锅拌饭揭盖瞬间蒸汽升腾，锅底锅巴声音 ASMR 级爽感。",
            },
            {
                "platform": "YouTube",
                "url": "https://www.youtube.com/results?search_query=Hanwoori+Korean+Restaurant+Richmond+Vancouver",
                "summary": "Richmond 韩餐对决：部队锅哪家强？Hanwoori 自家腌制泡菜评分最高。",
            },
        ],
        "reviews": [
            {
                "platform": "Google Review",
                "text": "The kimchi is housemade and you can taste the difference. Dolsot bibimbap with the crispy rice bottom is perfection.",
                "source_url": "https://www.google.com/maps/search/?api=1&query=Hanwoori+Korean+Restaurant+Richmond+BC",
            },
            {
                "platform": "小红书",
                "text": "部队锅里的泡菜是自己腌的，发酵味道特别正，和超市罐头不是一个次元，Richmond 韩餐首选！",
                "source_url": "https://www.xiaohongshu.com/search_result?keyword=Hanwoori+Korean+Richmond+部队锅",
            },
        ],
        "keywords": ["自制泡菜", "石锅拌饭", "部队锅正宗"],
        "ratings": {"google": 4.4, "xiaohongshu": 4.7},
    },
    # -----------------------------------------------------------------------
    {
        "name": "Sun Sui Wah Seafood Restaurant",
        "category": "中餐",
        "price_level": "$$$",
        "address": "3888 Main St, Vancouver, BC V5V 3P1",
        "image_url": "https://www.google.com/maps/search/?api=1&query=Sun+Sui+Wah+Seafood+Restaurant+Vancouver",
        "lat": 49.2423,
        "lng": -123.0712,
        "description": "Main Street 老牌海鲜粤菜馆，以片皮乳鸽与波士顿龙虾闻名大温，家庭聚餐首选。",
        "videos": [
            {
                "platform": "YouTube",
                "url": "https://www.youtube.com/results?search_query=Sun+Sui+Wah+Seafood+Restaurant+Vancouver",
                "summary": "温哥华最佳乳鸽评测：Sun Sui Wah 片皮乳鸽现场片制全纪录，皮脆肉嫩令人叫绝。",
            },
            {
                "platform": "TikTok",
                "url": "https://www.tiktok.com/search?q=Sun+Sui+Wah+Vancouver+squab+lobster",
                "summary": "龙虾生猛下锅实况，姜葱炒制香气飘满整层楼，评论区全是口水。",
            },
        ],
        "reviews": [
            {
                "platform": "Google Review",
                "text": "The squab is unmatched — crispy skin, juicy meat, worth every penny. A Vancouver institution since the 80s.",
                "source_url": "https://www.google.com/maps/search/?api=1&query=Sun+Sui+Wah+Seafood+Restaurant+Vancouver",
            },
            {
                "platform": "小红书",
                "text": "全温哥华最好吃的乳鸽在这里！片皮技术一流，皮酥肉嫩，配上酱料直接封神，家庭聚餐必来。",
                "source_url": "https://www.xiaohongshu.com/search_result?keyword=Sun+Sui+Wah+温哥华+乳鸽",
            },
        ],
        "keywords": ["片皮乳鸽", "波士顿龙虾", "家庭聚餐"],
        "ratings": {"google": 4.6, "xiaohongshu": 4.8},
    },
    # -----------------------------------------------------------------------
    {
        "name": "Jang Mo Jib Korean Restaurant",
        "category": "韩餐",
        "price_level": "$",
        "address": "7428 120 St, Surrey, BC V3W 3M5",
        "image_url": "https://www.google.com/maps/search/?api=1&query=Jang+Mo+Jib+Korean+Restaurant+Surrey",
        "lat": 49.1772,
        "lng": -122.8490,
        "description": "Surrey 韩国社区人气家庭餐馆，海鲜辣汤面与嫩豆腐锅是周末必点招牌。",
        "videos": [
            {
                "platform": "TikTok",
                "url": "https://www.tiktok.com/search?q=Jang+Mo+Jib+Korean+Restaurant+Surrey+Vancouver",
                "summary": "辣度挑战：海鲜辣汤面最高等级实测，主播脸红全程，弹幕笑翻。",
            },
            {
                "platform": "YouTube",
                "url": "https://www.youtube.com/results?search_query=Jang+Mo+Jib+Korean+Restaurant+Surrey+BC",
                "summary": "Surrey 韩国移民社区探店：Jang Mo Jib 老板娘分享 30 年家传汤底秘方。",
            },
        ],
        "reviews": [
            {
                "platform": "Google Review",
                "text": "Feels like eating at a Korean grandma's house. The soft tofu stew is silky smooth and the broth is deeply flavored.",
                "source_url": "https://www.google.com/maps/search/?api=1&query=Jang+Mo+Jib+Korean+Restaurant+Surrey+BC",
            },
            {
                "platform": "小红书",
                "text": "嫩豆腐锅豆腐嫩到颤抖，汤底鲜辣平衡感极好，老板娘会说普通话，接待华人超贴心！",
                "source_url": "https://www.xiaohongshu.com/search_result?keyword=Jang+Mo+Jib+Surrey+嫩豆腐锅",
            },
        ],
        "keywords": ["家庭式韩餐", "嫩豆腐锅", "海鲜辣汤面"],
        "ratings": {"google": 4.3, "xiaohongshu": 4.6},
    },
]

# ===========================================================================
# 3. Network Connectivity Probe
# ===========================================================================

PROBE_URL = "https://httpbin.org/get"
PROBE_TIMEOUT = 8  # seconds


def probe_network() -> bool:
    """
    Fire a real HTTP GET to a public echo endpoint.
    Returns True if the pipeline is live, False on any failure.
    In production this would be replaced with actual API calls.
    """
    print(f"[NET PROBE] Sending GET -> {PROBE_URL}")
    try:
        resp = requests.get(PROBE_URL, timeout=PROBE_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        origin_ip = data.get("origin", "unknown")
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
# 4. Pydantic Validation Pipeline
# ===========================================================================

def validate_records(raw_list: list[dict]) -> list[Restaurant]:
    print(f"\n[PIPELINE] Validating {len(raw_list)} raw records with Pydantic v2...")
    validated: list[Restaurant] = []
    for i, raw in enumerate(raw_list, start=1):
        try:
            restaurant = Restaurant(**raw)
            validated.append(restaurant)
            print(f"  [OK] #{i:02d} {restaurant.name}  "
                  f"({restaurant.category})  "
                  f"aggregate={restaurant.ratings.aggregate_score}")
        except Exception as exc:
            print(f"  [FAIL] #{i:02d} {raw.get('name', '?')} -- {exc}")
    print(f"[PIPELINE] {len(validated)}/{len(raw_list)} records passed Pydantic validation.\n")
    return validated


# ===========================================================================
# 5. Output Writer
# ===========================================================================

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shared_data")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "restaurants.json")


def write_output(records: list[Restaurant], network_ok: bool) -> None:
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    category_counts: dict[str, int] = {}
    for r in records:
        category_counts[r.category] = category_counts.get(r.category, 0) + 1

    all_scores = [r.ratings.aggregate_score for r in records]
    avg_score = round(statistics.mean(all_scores), 2) if all_scores else 0.0

    payload = {
        "meta": {
            "source": "vancouver_scraper.py v3 (Pydantic + requests + clickable URLs)",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "region": "Greater Vancouver (Vancouver / Richmond / Burnaby / Surrey)",
            "network_probe_passed": network_ok,
            "total_records": len(records),
            "category_breakdown": category_counts,
            "avg_aggregate_score": avg_score,
        },
        "restaurants": [
            {
                "name": r.name,
                "category": r.category,
                "price_level": r.price_level,
                "address": r.address,
                "image_url": r.image_url,
                "lat": r.lat,
                "lng": r.lng,
                "description": r.description,
                "videos": [v.model_dump() for v in r.videos],
                "reviews": [rv.model_dump() for rv in r.reviews],
                "keywords": r.keywords,
                "ratings": r.ratings.model_dump(),
            }
            for r in records
        ],
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"[WRITER] Output -> {OUTPUT_FILE}")
    print(f"[WRITER] {len(records)} restaurants  |  avg aggregate score: {avg_score}")


# ===========================================================================
# 6. Entry Point
# ===========================================================================

if __name__ == "__main__":
    print("=" * 65)
    print("  VanMap Cluster -- Slave Scraper  v3")
    print("  Clickable URLs: YouTube / TikTok / Google Maps / XHS")
    print("=" * 65)

    network_ok = probe_network()

    validated = validate_records(RAW_INTELLIGENCE)

    if not validated:
        print("[SCRAPER] No valid records -- aborting.")
    else:
        write_output(validated, network_ok)
        print("=" * 65)
        print("  Done. shared_data/restaurants.json ready for Slave Coder.")
        print("=" * 65)
