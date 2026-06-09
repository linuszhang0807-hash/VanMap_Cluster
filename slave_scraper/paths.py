"""Repository path constants — single source for data/ output."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
FRONTEND_DATA_DIR = REPO_ROOT / "slave_coder" / "src" / "shared_data"

GEOCODE_CACHE_FILE = DATA_DIR / "geocode_cache.json"
VIDEO_CACHE_FILE = DATA_DIR / "video_cache.json"
VIDEO_OVERRIDES_FILE = DATA_DIR / "video_overrides.json"
MASTER_DATA_FILE = DATA_DIR / "master_data.json"
EVENTS_DATA_FILE = DATA_DIR / "events_data.json"
