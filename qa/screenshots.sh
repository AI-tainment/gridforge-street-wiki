#!/bin/sh
# Headless Chrome screenshots of key wiki pages (file:// URLs, no server).
set -e
cd "$(dirname "$0")/.."
OUT=qa/screenshots; mkdir -p "$OUT"
shot() { google-chrome --headless=new --no-sandbox --disable-gpu --hide-scrollbars \
  --window-size=1280,${3:-1000} --screenshot="$OUT/$1.png" "file://$PWD/site/$2" >/dev/null 2>&1; echo "$OUT/$1.png"; }
shot 01-home index.html
shot 02-category-warning-signs cat/signs--WarnTriangle.html
shot 03-drawn-sign-670 items/signs/670.html
shot 04-placeholder-sign-2026 items/signs/2026.html
shot 05-3d-bay3-cantilever items/furniture3d/assembled_bay3_cantilever.html 1300
shot 06-matrix-6031.1 items/matrix/auto_red_x_6031_6031.1_ms4_block.html
shot 07-code-build-py code/view/wiki/build.py.html
shot 08-licences licences.html 1300
