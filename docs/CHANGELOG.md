# Changelog

All notable changes to VanMap Cluster are documented here.
Format based on [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

## [0.2.0] - 2026-06-09

### Added
- OSM Overpass live place scraping (`osm_provider.py`) with User-Agent and mirror fallback
- Nominatim geocoding cache for events (`geocoder.py`)
- `video_providers` port: YouTube API, TikTok override, TikTok API stub
- `video_resolver.py` — direct video links only (no search pages)
- `requirements.txt`, `.env.example`
- Google Places provider stub (`places_providers/`)

### Changed
- `vancouver_scraper.py`: OSM-first pipeline, empty photos (no fake Google CDN), relaxed video validation
- `events_scraper.py`: geocoding on build, video resolver integration
- `data/master_data.json`: 53+ live OSM entries; `scrape_mode: live`

### Fixed
- Overpass API requires User-Agent (was returning 0 results)
- Validator no longer requires videos; forbids search-page video URLs

## [0.1.0] - 2026-06-09

Initial structured release — Phase 0 foundation.
