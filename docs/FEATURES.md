# VanMap Feature Registry

Track active, planned, and deprecated features. Update before adding or removing capabilities.

## Data Categories

| Category | Scraper | Data File | Status | Since |
|----------|---------|-----------|--------|-------|
| 餐厅 | RestaurantScraper | master_data.json | active | 0.1.0 |
| 餐厅菜系分级 | index.html + osm_provider | master_data.json | active | 0.3.0 |
| 餐厅地区筛选 | index.html + geocoder | master_data.json | active | 0.3.0 |
| 酒吧 | BarScraper | master_data.json | active | 0.1.0 |
| 娱乐 | EntertainmentScraper | master_data.json | active | 0.1.0 |
| 景点 | AttractionScraper | master_data.json | active | 0.1.0 |
| 徒步 | HikingScraper | master_data.json | active | 0.1.0 |
| 活动 | events_scraper | events_data.json | active | 0.1.0 |
| 日料 | — | — | planned | — |

## UI Features

| Feature | File | Status | Since |
|---------|------|--------|-------|
| Category portal | index_home.html | active | 0.1.0 |
| Map + sidebar | index.html | active | 0.1.0 |
| Lightbox | index.html | active | 0.1.0 |
| Events filter | index.html | active | 0.1.0 |
| Marker cluster | index.html | active | 0.3.0 |
| Mobile overlay sidebar | index.html | active | 0.3.0 |
| Cuisine two-tier filter | index.html | active | 0.3.0 |
| Category marker icons | index.html | active | 0.3.0 |
| GitHub Pages CI | .github/workflows/deploy.yml | active | 0.3.0 |
| Weekly events cron | .github/workflows/refresh-events.yml | active | 0.3.0 |

## External Dependencies

| Dependency | Purpose | Provider | Phase | Status |
|------------|---------|----------|-------|--------|
| OSM Overpass | Place coordinates | osm_provider | 1 | active |
| Nominatim | Event geocoding | geocoder | 1 | active |
| YouTube Data API | Video direct links | YouTubeApiProvider | 1 | active |
| video_overrides.json | Manual video curation | TikTokOverrideProvider | 1 | active |
| TikTok API | Video direct links | TikTokApiProvider | 3 | planned (Stub ready) |
| Google Places API | Photos/ratings | GooglePlacesProvider | 3 | planned (Stub ready) |

## Orchestration

| Component | File | Status | Since |
|-----------|------|--------|-------|
| Task contract | master_hermes/order_box/task.json | active | 0.1.0 |
| Task runner | master_hermes/task_runner.py | active | 1.0.0 |
| Discord bot | master_hermes/discord_bot.py | active | 1.0.0 |
