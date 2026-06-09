# VanMap Data Schema

**Current schema version:** `5.3` (master_data) / `1.1` (events_data)

## Universal BaseEntry Fields

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| name | string | yes | Display name |
| category | string | yes | 餐厅/酒吧/娱乐/景点/徒步/活动 |
| address | string | yes | Full address |
| district | string \| null | no | GVA city (Richmond, Vancouver, …) |
| lat | float | yes | 49.0–49.8 (GVA + surroundings) |
| lng | float | yes | -123.5–-122.3 |
| url | string | yes | Maps navigation link |
| official_website | string \| null | no | |
| image_url | string \| null | no | Real image URL only; empty if none |
| description | string \| null | no | Max 50 chars for places |
| photos | array | no | `[{category, url}]` — real URLs only |
| social_metrics | object | yes | videos, reviews, keywords, social_buzz_score |
| rating_system | object | yes | google_rating, review_count, aggregate_score |
| videos | array | computed | Hoisted from social_metrics |
| reviews | array | computed | Hoisted from social_metrics |

## videos[] — Direct Link Constraint

Each video entry **must** be a playable direct URL:

```json
{
  "platform": "YouTube",
  "url": "https://www.youtube.com/watch?v=VIDEO_ID",
  "summary": "Short title",
  "video_id": "VIDEO_ID",
  "resolved_at": "2026-06-09",
  "source": "youtube_api | tiktok_override | tiktok_api | manual_override"
}
```

**Forbidden URL patterns:** `/search`, `search_query`, `/results?`

## meta Block

| Field | Type | Notes |
|-------|------|-------|
| schema_version | string | Semver MAJOR.MINOR |
| scrape_mode | string | `live` \| `mock` \| `live+fallback` |
| skipped | array | `{name, reason}` for failed geocode/validation |

## Category Extensions

- **餐厅:** price_level, cuisine_country, cuisine_style, cuisine (display: `国家` or `国家-菜系`)
- **酒吧:** vibe, signature_drink, happy_hour
- **娱乐:** venue_type, age_restriction, opening_hours
- **景点:** admission_fee, highlights[]
- **徒步:** alltrails_data, duration, trailhead
- **活动:** event_date, venue_name, ticket_price, fingerprint, source[]

## Migration Notes

### 5.2 → 5.3
- Added optional `video_id`, `resolved_at`, `source` on VideoClip
- Added `meta.scrape_mode`, `meta.skipped`
- Expanded lat/lng bounds for Squamish/Richmond edges
- Output directory moved to repo-root `data/`

### restaurants.json deprecated (0.1.0)
- All restaurant entries live in `master_data.json` only
