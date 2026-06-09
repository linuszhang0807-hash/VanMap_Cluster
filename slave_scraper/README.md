# 数据工厂 (Slave Scraper)

本模块负责大温地区多类目情报的采集、清洗、标准化与 JSON 输出，供 `slave_coder` 前端直接渲染。

## 脚本一览

| 脚本 | 版本 | 输出文件 | 说明 |
|---|---|---|---|
| `vancouver_scraper.py` | v5.2 | `shared_data/master_data.json` | 餐厅 / 酒吧 / 娱乐 / 景点 / 徒步 |
| `events_scraper.py` | v1.0 | `shared_data/events_data.json` | 活动专题（多源采集 + 指纹去重） |

历史遗留文件 `shared_data/restaurants.json` 已不再作为主输出，请以 `master_data.json` 为准。

## 快速运行

```bash
# 1. 激活环境（如有 conda 环境）
conda activate scraper_env

# 2. 采集主数据（5 类目，21 条）
python vancouver_scraper.py

# 3. 采集活动数据（8 条去重后活动）
python events_scraper.py

# 4. 同步到前端（浏览器实际读取 slave_coder/src/shared_data/）
cp shared_data/master_data.json  ../slave_coder/src/shared_data/
cp shared_data/events_data.json  ../slave_coder/src/shared_data/
```

Windows PowerShell 示例：

```powershell
cd e:\AI_Project1_Web\VanMap_Cluster\slave_scraper
python vancouver_scraper.py
python events_scraper.py
Copy-Item shared_data\master_data.json  ..\slave_coder\src\shared_data\
Copy-Item shared_data\events_data.json  ..\slave_coder\src\shared_data\
```

## 架构概览

### `vancouver_scraper.py`（v5.2）

```
BaseScraper (ABC)
├── RestaurantScraper   → 餐厅（5 条）
├── BarScraper          → 酒吧（4 条）
├── EntertainmentScraper→ 娱乐（4 条）
├── AttractionScraper   → 景点（4 条）
└── HikingScraper       → 徒步（4 条）+ fetch_alltrails_data()
```

**共享能力（所有类目）：**

- `fetch_social_metrics()` — YouTube / TikTok / Google Review / 小红书
- `fetch_photos()` — 按类目标签生成照片合集（Google Places 风格 URL）
- `RatingSystem` — `google_rating` + `review_count` + Bayesian `aggregate_score`
- `validate_map_readiness()` — 坐标类型、GVA 边界、必填字段
- `validate_description_uniqueness()` — 同类目 description / keywords 去重校验

**徒步专属：** `fetch_alltrails_data()` — `trail_distance` / `elevation_gain` / `difficulty_rating`

### `events_scraper.py`（v1.0）

```
DestinationVancouverScraper  → destinationvancouver.com/events/
DailyHiveScraper             → dailyhive.com/vancouver/events
         ↓
EventDeduplicator            → MD5(name + date + location) 指纹去重
         ↓
events_data.json             → 8 条唯一活动
```

- 真实 HTTP + BeautifulSoup4 解析；失败时自动降级 Mock 数据
- 跨源重复活动合并为一条，保留最长 `long_description`
- 条目 schema 与 `master_data.json` 的 `BaseEntry` 完全兼容

启用真实爬虫：

```bash
pip install beautifulsoup4 lxml
python events_scraper.py
```

## 输出统计（当前）

| 文件 | 条目数 | 类目 |
|---|---|---|
| `master_data.json` | 21 | 餐厅 5 / 酒吧 4 / 娱乐 4 / 景点 4 / 徒步 4 |
| `events_data.json` | 8 | 活动（含 2 条跨源合并） |

照片合集：全量 21 条均已注入 `photos[]`，平均每家 **8.8** 张（餐厅/酒吧/娱乐 8 张，景点/徒步 10 张）。

## 数据 Schema

### 通用字段（`BaseEntry`，所有类目共享）

```json
{
  "name": "Kirin Seafood Restaurant",
  "category": "餐厅",
  "address": "1166 Alberni St, Vancouver, BC V6E 1A5",
  "lat": 49.2827,
  "lng": -123.1207,
  "url": "https://www.google.com/maps/search/?api=1&query=...",
  "official_website": "https://www.kirinrestaurant.com/",
  "image_url": "https://...",
  "description": "Downtown 经典粤菜海鲜楼...",
  "photos": [
    { "category": "招牌菜", "url": "https://lh5.googleusercontent.com/p/AF1Qip...=w1200-h800-k-no" },
    { "category": "食物特写", "url": "https://..." }
  ],
  "social_metrics": {
    "videos": [{ "platform": "YouTube", "url": "...", "summary": "..." }],
    "reviews": [{ "platform": "Google Review", "text": "...", "source_url": "..." }],
    "keywords": ["粤菜海鲜", "商务宴请", "炭烧叉烧"],
    "social_buzz_score": 4.2
  },
  "rating_system": {
    "google_rating": 4.5,
    "review_count": 1240,
    "aggregate_score": 4.5
  },
  "rating": 4.5,
  "videos": [],
  "reviews": []
}
```

> `videos` / `reviews` 为顶层快捷字段（`computed_field`），与 `social_metrics` 内数据一致，方便前端直接读取。

### 类目专属扩展字段

| 类目 | 额外字段 |
|---|---|
| 餐厅 | `price_level` |
| 酒吧 | `vibe`, `signature_drink`, `happy_hour` |
| 娱乐 | `venue_type`, `age_restriction`, `opening_hours` |
| 景点 | `admission_fee`, `highlights` |
| 徒步 | `duration`, `trailhead`, `alltrails_data` |
| 活动 | `event_date`, `event_time`, `venue_name`, `ticket_price`, `long_description`, `source`, `fingerprint` |

### 照片分类标签（`fetch_photos`）

| 类目 | 标签序列（轮播分配） |
|---|---|
| 餐厅 | 招牌菜 → 食物特写 → 用餐环境 → 外观门面 → 菜单 → 厨房展示 → 饮品 → 包厢/私房 |
| 酒吧 | 招牌特调 → 吧台环境 → 外观夜景 → 调酒过程 → 人气氛围 → 座位区 → 酒单 → 灯光效果 |
| 娱乐 | 主要项目 → 室内环境 → 外观建筑 → 活动现场 → 游客体验 → 设施细节 → 票务入口 → 人气场景 |
| 景点 | 核心地标 → 全景风光 → 游客打卡 → 历史细节 → 自然景观 → 标志建筑 → 季节特色 → 入口全景 |
| 徒步 | 步道起点 → 沿途森林 → 山顶/终点 → 峰顶全景 → 植被地貌 → 路标指示 → 远眺视野 → 停车入口 |

### `official_website` 来源规则

- 餐厅 / 酒吧 / 娱乐 / 景点：从 Google Maps 商家信息提取；无官网则为 `null`
- 徒步：自动赋值为 AllTrails 详情页 URL（与 `url` 相同）

## 校验流水线

运行 `vancouver_scraper.py` 时依次执行：

1. **网络探测** — `GET https://httpbin.org/get`
2. **Pydantic 校验** — 每条原始记录通过模型验证
3. **地图就绪校验** — 坐标数值类型、GVA 边界、必填字段完整性
4. **描述去重校验** — 同类目 `description` 相似度 < 90%，`keywords` 集合不重复
5. **照片合集报告** — 控制台输出抓取汇总与 3 家示范条目详情

控制台汇总示例：

```
[PHOTOS] 已完成 21 家店铺的照片合集抓取，平均每家包含 8.8 张照片。
```

## 生产环境替换说明

当前为 **MOCK 模式**，所有数据在脚本内预置，URL 为可点击的搜索链接或确定性生成的占位 ID。

| 能力 | 生产替换方案 |
|---|---|
| 社交数据 | YouTube Data API v3 / TikTok Research API / Google Places API / 小红书爬虫 |
| 照片 | Google Places `photos[]` → `photo_reference` → `/place/photo?maxwidth=1200` |
| 活动 | Destination Vancouver + Daily Hive 真实 HTML 解析（需 `beautifulsoup4`） |
| 徒步 | AllTrails 爬虫 / OpenStreetMap Overpass API |

## 目录结构

```
slave_scraper/
├── vancouver_scraper.py      # 主采集脚本 v5.2
├── events_scraper.py         # 活动采集脚本 v1.0
├── README.md
└── shared_data/
    ├── master_data.json      # 主输出（21 条）
    ├── events_data.json      # 活动输出（8 条）
    └── restaurants.json      # 历史遗留，不再更新
```
