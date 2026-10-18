#!/usr/bin/env bash
# Build the distributable release zip for the BDK mitigation model.
#
# Runs `npm run build:single`, then packages:
#   - dist-single/index.html   (the self-contained app)
#   - README.md
#   - LICENSE                 (only if present — license choice pending)
# into release/bdk-mitigation-model-<version>.zip, with <version> read
# from package.json. Files are stored at the archive root, so users can
# unzip anywhere and open index.html directly — no server needed.
#
# Usage: tools/make_release.sh   (from anywhere; the script cds to the repo root)

set -euo pipefail

cd "$(dirname "$0")/.."

VERSION=$(node -p "require('./package.json').version")
ZIP="release/bdk-mitigation-model-${VERSION}.zip"

echo "==> Building single-file app (npm run build:single)"
npm run build:single

echo "==> Packaging ${ZIP}"
mkdir -p release
rm -f "$ZIP"

# -j: store files at the archive root (no dist-single/ prefix).
zip -q -j "$ZIP" dist-single/index.html README.md
if [ -f LICENSE ]; then
  zip -q -j "$ZIP" LICENSE
else
  echo "    (no LICENSE file — skipping; license choice still pending)"
fi

echo "==> Done: ${ZIP} ($(du -h "$ZIP" | cut -f1))"
unzip -l "$ZIP"
