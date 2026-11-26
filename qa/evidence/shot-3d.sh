#!/bin/sh
# Headless Chrome screenshots of interactive 3D viewers.
# Serves site/ over localhost (ES modules and GLB cannot load from file://).
set -e
cd "$(dirname "$0")/../.."
OUT=qa/evidence
mkdir -p "$OUT"
PORT=8765
python3 -m http.server "$PORT" --directory site >/dev/null 2>&1 &
PID=$!
trap 'kill $PID 2>/dev/null || true' EXIT
sleep 0.3
shot() {
  google-chrome --headless=new --no-sandbox --hide-scrollbars \
    --use-gl=angle --use-angle=swiftshader --enable-webgl \
    --window-size=1280,"${3:-1100}" \
    --virtual-time-budget=15000 \
    --screenshot="$OUT/$1.png" \
    "http://127.0.0.1:$PORT/$2" >/dev/null 2>&1
  echo "$OUT/$1.png"
}
shot 3d-01-bay3-cantilever "items/furniture3d/assembled_bay3_cantilever.html?view3d=1" 1300
shot 3d-02-bench-free "items/furniture3d/bench_free.html?view3d=1" 1100
shot 3d-03-flag-plate "items/furniture3d/flag_plate_default.html?view3d=1" 1100
shot 3d-04-category "cat/furniture3d.html?view3d=1" 1400
