# Changelog

All notable changes to VanMap Cluster are documented here.
Format based on [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added
- Canonical `data/` directory as single source of truth
- `scripts/sync_data` for one-way sync to frontend
- Version management: `VERSION`, `docs/FEATURES.md`, `data/SCHEMA.md`
- Events data loaded in map UI (`events_data.json`)
- OSM Overpass live place scraping
- Nominatim geocoding cache for events
- `video_providers` port architecture for YouTube/TikTok direct links
- GitHub Pages deploy workflow + weekly events refresh cron
- Mobile responsive sidebar + Leaflet marker clustering
- Google Places provider stub (Phase 3)
- Master Hermes `task_runner` + Discord bot skeleton (Phase 4)

### Changed
- Scraper output path: `data/` instead of `slave_scraper/shared_data/`
- Frontend loads `master_data.json` + `events_data.json` only (removed `restaurants.json`)
- Video URLs must be direct watch links, not search pages

### Removed
- Redundant `slave_coder/shared_data/` business data copies
- Archived `restaurants.json` to `data/_archive/`

## [0.1.0] - 2026-06-09

Initial structured release — Phase 0 foundation.
