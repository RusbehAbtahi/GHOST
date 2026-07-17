#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

STRICTDOC_SRC="$REPO_ROOT/doc/01-Requirements/strictdoc"
TEMP_OUT="$REPO_ROOT/.strictdoc-html-temp"
PAGES_OUT="$REPO_ROOT/docs"

rm -rf "$TEMP_OUT"
strictdoc export "$STRICTDOC_SRC" --formats=html --output-dir "$TEMP_OUT"

mkdir -p "$PAGES_OUT"
rsync -av --delete "$TEMP_OUT/html/" "$PAGES_OUT/"

touch "$PAGES_OUT/.nojekyll"

rm -rf "$TEMP_OUT"

echo "Done. GitHub Pages HTML updated in docs/"
