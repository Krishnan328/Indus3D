#!/usr/bin/env bash
# backend/tools/download_caxton_dataset.sh
# ----------------------------------------
# Helper script to download Cambridge CAXTON dataset shards (193 parts total).
# CAUTION: The full dataset is ~1.27M images and >100 GB.
# Usage:
#   ./download_caxton_dataset.sh [num_shards] [target_dir]
# Example (download first 2 shards for local testing):
#   ./download_caxton_dataset.sh 2 ./caxton_data

set -euo pipefail

NUM_SHARDS=${1:-2}
TARGET_DIR=${2:-"./caxton_data"}
LINKS_FILE="/Users/krishnanh/Projects/Indus3D/research_repos/wirely_caxton/src/data-retrieval/all-links.txt"

if [ ! -f "$LINKS_FILE" ]; then
    echo "🔴 Could not find all-links.txt at $LINKS_FILE"
    exit 1
fi

mkdir -p "$TARGET_DIR"
echo "📥 Downloading first $NUM_SHARDS shards to $TARGET_DIR..."

head -n "$NUM_SHARDS" "$LINKS_FILE" | while read -r url; do
    echo "⬇️  Downloading $url..."
    curl -L -O --output-dir "$TARGET_DIR" "$url"
done

echo "✅ Download finished. Extract archives using: tar -xf <archive> -C $TARGET_DIR"
