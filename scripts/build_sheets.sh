#!/usr/bin/env bash
# Rebuild the pre-generated quick-play unit sheets in docs/sheets/ (PDF).
# Needs uv and a Chromium/Chrome binary (override with CHROME=...).
set -euo pipefail
cd "$(dirname "$0")/.."
chrome=${CHROME:-$(command -v google-chrome-stable || command -v chromium || command -v google-chrome)}
out=docs/sheets
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

render() {  # render <html> <pdf>
    "$chrome" --headless=new --disable-gpu --no-pdf-header-footer \
        --print-to-pdf="$2" "file://$1" >/dev/null 2>&1
}

uv run foosim-sheet --seed 1 --pages 64 --out "$tmp/squads.html" >/dev/null
render "$tmp/squads.html" "$out/squads.pdf"
uv run foosim-sheet --blank --pages 1 --out "$tmp/blank.html" >/dev/null
render "$tmp/blank.html" "$out/blank.pdf"
ls -l "$out"
