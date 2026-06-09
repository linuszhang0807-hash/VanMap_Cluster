#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$ROOT/slave_coder/src/shared_data"
cp "$ROOT/data/master_data.json" "$ROOT/data/events_data.json" "$ROOT/slave_coder/src/shared_data/"
echo "Synced data/*.json -> slave_coder/src/shared_data/ at $(date -Iseconds)"
