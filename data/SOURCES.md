# Approved Data Sources

VanMap MVP uses only sources with permissive access or official APIs.

## Active (Phase 1)

| Source | Use | ToS / License |
|--------|-----|---------------|
| [OpenStreetMap Overpass API](https://wiki.openstreetmap.org/wiki/overpass_api) | Restaurants, bars, attractions, trails | ODbL — attribution required |
| [Nominatim](https://nominatim.org/release-docs/develop/api/Search/) | Address → coordinates | Max 1 req/s; cache required |
| [Destination Vancouver](https://www.destinationvancouver.com/events/) | Events calendar | Public event listings; respect robots.txt |
| [Daily Hive Vancouver](https://dailyhive.com/vancouver/events) | Events roundup | Public listings; respect robots.txt |
| [YouTube Data API v3](https://developers.google.com/youtube/v3) | Video direct links | API ToS; free tier |

## Manual / Override

| Source | Use |
|--------|-----|
| `data/video_overrides.json` | Curated YouTube/TikTok direct links |

## Planned (Phase 3+)

| Source | Use |
|--------|-----|
| Google Places API (New) | Photos, ratings, hours |
| TikTok API | Automated TikTok direct links |

## Prohibited (MVP)

- Yelp scraping
- TripAdvisor scraping
- AllTrails scraping
- Google Maps scraping (use Places API instead)
