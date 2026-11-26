"""Classify animated items and emit sourced SVG/CSS playback.

Timing is taken only from atlas records (never invented). A range is
played at its lower end and the range is quoted on the page. Items that
look animated in life but have no rate in the atlas get an UNVERIFIED
badge and no playback.
"""
from __future__ import annotations
import json, os, re

# Lower end of the sourced Sch 15 Pt 4 range. The page must quote the range.
PLAY_PER_MIN = 60
# Period of one flash (on+off) at the play rate, in seconds.
PERIOD_S = 60.0 / PLAY_PER_MIN

# Families / ids that are animated in use, even if the atlas has no rate.
ANIMATED_SIGN_FAMILIES = {"SignalHead", "MatrixMS4"}
ANIMATED_SIGN_IDS = {"3014", "BELISHA", "4007", "XING_PAR", "MS4"}
ANIMATED_FURNITURE_IDS = {
    "lane-signal", "verge-ms", "vms-text", "vms-pictogram", "belisha",
}
# Pedestrian signal heads that change aspect (not instruction plates).
ANIMATED_ID_PREFIXES = ("3000", "3001", "3013", "3014", "4002", "4003")


def _is_animated_sign(it):
    i = it.get("id") or ""
    if i in ANIMATED_SIGN_IDS or it.get("sub") in ANIMATED_SIGN_FAMILIES:
        return True
    if it.get("cat") == "signs" and any(i == p or i.startswith(p + ".") or i.startswith(p + "-") for p in ANIMATED_ID_PREFIXES):
        return True
    name = (it.get("name") or "") + " " + (it.get("what") or "")
    if re.search(r"\b(flash|wig-?wag|belisha)\b", name, re.I):
        return True
    return False


def load_furniture_timing(atlas):
    """Read flash-timing citations already recorded in furniture.json."""
    path = os.path.join(atlas, "countries/uk/furniture.json")
    data = json.load(open(path, encoding="utf-8"))
    items = data if isinstance(data, list) else list(data.values())
    out = {}
    for rec in items:
        rid = rec.get("id")
        if not rid:
            continue
        blob = json.dumps(rec)
        info = {}
        # Explicit 60-90 range and alternating pairs (AMI / Sch 15 Pt 4).
        m = re.search(r"Sch 15 Pt 4 \(60-90 per minute, pairs alternate\)", blob)
        if m:
            info["range"] = (60, 90)
            info["pairs_alternate"] = True
            info["part"] = "TSRGD 2016 Sch 15 Pt 4 (60-90 flashes/min, pairs alternate)"
        # Verified para 3 citation (post-mounted flashing lamps).
        srcs = rec.get("sources_needed") or rec.get("sources") or []
        if isinstance(srcs, str):
            srcs = [srcs]
        for s in srcs:
            if re.search(r"Sch 15 Pts?\s+[0-9 and]+", s) or "Sch 15 Pt 4" in s:
                info.setdefault("sources", []).append(s)
                if "verified" in s.lower():
                    info["verified"] = True
        todo = rec.get("todo") or ""
        if "Sch 15 Pt 4" in todo and "sources" not in info:
            info.setdefault("notes", []).append(todo)
        if info:
            info["licence_note"] = rec.get("licence") or rec.get("license")
            out[rid] = info
    return out


def classify(it, furniture_timing):
    """Return animation metadata or None if the item is not an animated type."""
    cat, i = it.get("cat"), it.get("id")
    animated = False
    if cat == "signs" and _is_animated_sign(it):
        animated = True
    if cat == "furniture" and i in ANIMATED_FURNITURE_IDS:
        animated = True
    if cat == "furniture3d":
        return None
    if not animated:
        return None

    rec = furniture_timing.get(i, {})
    sourced = bool(rec.get("range") or rec.get("sources"))
    # Only play a rate when the atlas recorded one.
    play = None
    rng = rec.get("range")
    if rng:
        play = min(rng)  # lower end; never a value outside the source
    # verge-ms cites verified Sch 15 Pt 4 para 3 at p522; the same Part
    # records 60-90 and alternating pairs on the AMI row. Only then may
    # verge-ms inherit the Part 4 rate, and the page must cite both.
    if i == "verge-ms" and rec.get("sources") and not rng:
        ami = furniture_timing.get("lane-signal") or {}
        if ami.get("range"):
            rng = ami["range"]
            play = min(rng)
            rec = dict(rec)
            rec["range"] = rng
            rec["pairs_alternate"] = True
            rec["inherited_from"] = "lane-signal Sch 15 Pt 4 rate (same Part, printed p522)"
            sourced = True

    if not sourced or not play:
        return {
            "id": i,
            "sourced": False,
            "play": False,
            "badge": "UNVERIFIED",
            "reason": "Animated in use, but no flash rate is recorded in the atlas data. No playback is shown, so a rate is not invented.",
            "source": None,
        }

    sources = list(rec.get("sources") or [])
    if rec.get("part") and rec["part"] not in sources:
        sources.insert(0, rec["part"])
    if rec.get("inherited_from"):
        sources.append("Rate quoted from " + rec["inherited_from"])
    return {
        "id": i,
        "sourced": True,
        "play": True,
        "badge": None,
        "range": rng,
        "play_per_min": play,
        "period_s": 60.0 / play,
        "pairs_alternate": bool(rec.get("pairs_alternate")),
        "source": "; ".join(sources),
        "reason": "Sourced atlas timing",
        "verified": bool(rec.get("verified")),
    }


def lamp_pair_svg(meta):
    """Deterministic SVG of two lamps. Period comes from meta['period_s']."""
    period = meta["period_s"]
    half = period / 2.0
    alt = meta.get("pairs_alternate", True)
    # Amber lamps, as the atlas describes flashing amber or red lamps on AMI.
    on = "#F5D000"
    off = "#2A2A28"
    delay_b = half if alt else 0.0
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 90" width="240" height="90" role="img" class="anim-svg">
<title>Lamp-pair playback</title>
<style>
.anim-svg .lamp {{ stroke:#141414; stroke-width:2; }}
.anim-svg .a {{ fill:{on}; animation:sw-flash {period:.4f}s steps(1,end) infinite; }}
.anim-svg .b {{ fill:{on}; animation:sw-flash {period:.4f}s steps(1,end) infinite; animation-delay:{delay_b:.4f}s; }}
@keyframes sw-flash {{
  0%,49.9% {{ fill:{on}; }}
  50%,100% {{ fill:{off}; }}
}}
@media (prefers-reduced-motion: reduce) {{
  .anim-svg .a, .anim-svg .b {{ animation: none; fill:{on}; }}
}}
</style>
<rect x="1" y="1" width="238" height="88" rx="8" fill="#1a1a1c" stroke="#6E6C66" stroke-width="2"/>
<circle class="lamp a" cx="80" cy="45" r="22"/>
<circle class="lamp b" cx="160" cy="45" r="22"/>
</svg>
'''


def caption(meta):
    if not meta.get("play"):
        return meta["reason"]
    lo, hi = meta["range"]
    parts = [
        "Playback at %d flashes/min, the lower end of the sourced range %d–%d flashes/min."
        % (meta["play_per_min"], lo, hi)
    ]
    if meta.get("pairs_alternate"):
        parts.append("Pairs alternate.")
    parts.append("Source: %s." % meta["source"])
    parts.append("If the system requests reduced motion, the lamps stay lit and the animation is paused.")
    return " ".join(parts)
