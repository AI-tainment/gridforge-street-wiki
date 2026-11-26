"""Classify animated items and emit sourced SVG/CSS playback.

Timing is taken from the governing regulation or from atlas records
(never invented). A range recorded only in the atlas is played at its
lower end. A range taken from the regulation for verge-ms or 3014 is
played at the midpoint of that range. The page quotes the range and
the choice.
Items that look animated in life but have no sourced rate get an
UNVERIFIED badge and no playback.
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
    # Post-mounted verge message signs: cite Sch 15 Pt 4 para 3 directly
    # (item 12, diagram 6022, lamps on a post). Do not inherit the AMI
    # / gantry rate from para 2. The regulation gives a range; play the
    # midpoint and say so in the caption.
    if i == "verge-ms":
        lo, hi = 60, 90
        play = (lo + hi) // 2
        return {
            "id": i,
            "sourced": True,
            "play": True,
            "badge": None,
            "range": (lo, hi),
            "play_per_min": play,
            "period_s": 60.0 / play,
            "pairs_alternate": True,
            "play_choice": "midpoint",
            "source": (
                "TSRGD 2016 (SI 2016/362) Schedule 15 Part 4 paragraph 3, "
                "printed page 522 (item 12, diagram 6022, flashing amber "
                "lamps for display on a post)"
            ),
            "reason": "Sourced from the governing regulation",
            "verified": True,
        }

    # Wig-wag (diagram 3014): Sch 14 Pt 1 para 8, printed page 430.
    # Steady amber (3 s at level crossings, 5 s otherwise), then
    # alternating reds at 60-90 flashes/min. Play the midpoint and
    # show the amber step; the caption states both amber durations.
    if i == "3014":
        lo, hi = 60, 90
        play = (lo + hi) // 2
        return {
            "id": i,
            "sourced": True,
            "play": True,
            "badge": None,
            "kind": "wigwag",
            "range": (lo, hi),
            "play_per_min": play,
            "period_s": 60.0 / play,
            "pairs_alternate": True,
            "play_choice": "midpoint",
            "amber_s": 3.0,
            "amber_s_other": 5.0,
            "red_cycles": 8,
            "svg_title": "Wig-wag playback",
            "source": (
                "TSRGD 2016 (SI 2016/362) Schedule 14 Part 1 paragraph 8, "
                "printed page 430 (item 5, diagram 3014)"
            ),
            "reason": "Sourced from the governing regulation",
            "verified": True,
        }

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

def playback_svg(meta):
    """Emit the playback SVG for this item (wig-wag or lamp pair)."""
    if meta.get("kind") == "wigwag":
        return wigwag_svg(meta)
    return lamp_pair_svg(meta)


def _fill_steps(segments, total):
    """Deterministic CSS keyframe stops for a stepped fill animation."""
    merged = []
    for t0, t1, color in segments:
        if merged and merged[-1][2] == color and abs(merged[-1][1] - t0) < 1e-12:
            merged[-1] = (merged[-1][0], t1, color)
        else:
            merged.append((t0, t1, color))
    blocks = []
    eps = 0.0001
    for i, (t0, t1, color) in enumerate(merged):
        p0 = 100.0 * t0 / total
        p1 = 100.0 * t1 / total
        p1_hold = 100.0 if i == len(merged) - 1 else max(p0, p1 - eps)
        blocks.append("  %.4f%%, %.4f%% { fill:%s; }" % (p0, p1_hold, color))
    return "\n".join(blocks)


def wigwag_svg(meta):
    """Wig-wag playback: steady amber, then alternating reds.

    The red-phase length of the page loop is not specified in the
    regulation (in use the reds continue until the sequence ends). It
    is only long enough for the sourced flash rate to be seen.
    """
    amber_s = meta["amber_s"]
    period = meta["period_s"]
    n = int(meta.get("red_cycles") or 8)
    total = amber_s + n * period
    red = "#CC1A1A"
    amber = "#F29E14"
    off = "#2A2A28"
    amber_seg = [(0.0, amber_s, amber), (amber_s, total, off)]
    red_a, red_b = [(0.0, amber_s, off)], [(0.0, amber_s, off)]
    for i in range(n):
        a0 = amber_s + i * period
        mid = a0 + period / 2.0
        a1 = a0 + period
        red_a.extend([(a0, mid, red), (mid, a1, off)])
        red_b.extend([(a0, mid, off), (mid, a1, red)])
    kf_am = _fill_steps(amber_seg, total)
    kf_a = _fill_steps(red_a, total)
    kf_b = _fill_steps(red_b, total)
    title = meta.get("svg_title") or "Wig-wag playback"
    dur = "%.4f" % total
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 150"'
        ' width="240" height="150" role="img" class="anim-svg">\n'
        "<title>" + title + "</title>\n"
        "<style>\n"
        ".anim-svg .lamp { stroke:#141414; stroke-width:2; }\n"
        ".anim-svg .amber { animation:ww-amber " + dur + "s steps(1,end) infinite; }\n"
        ".anim-svg .red-a { animation:ww-red-a " + dur + "s steps(1,end) infinite; }\n"
        ".anim-svg .red-b { animation:ww-red-b " + dur + "s steps(1,end) infinite; }\n"
        "@keyframes ww-amber {\n" + kf_am + "\n}\n"
        "@keyframes ww-red-a {\n" + kf_a + "\n}\n"
        "@keyframes ww-red-b {\n" + kf_b + "\n}\n"
        "@media (prefers-reduced-motion: reduce) {\n"
        "  .anim-svg .amber, .anim-svg .red-a, .anim-svg .red-b { animation: none; }\n"
        "  .anim-svg .amber { fill:" + amber + "; }\n"
        "  .anim-svg .red-a, .anim-svg .red-b { fill:" + red + "; }\n"
        "}\n"
        "</style>\n"
        '<rect x="1" y="1" width="238" height="148" rx="8" fill="#141414" stroke="#6E6C66" stroke-width="2"/>\n'
        '<circle class="lamp red-a" cx="70" cy="52" r="22" fill="' + off + '"/>\n'
        '<circle class="lamp red-b" cx="170" cy="52" r="22" fill="' + off + '"/>\n'
        '<circle class="lamp amber" cx="120" cy="108" r="22" fill="' + off + '"/>\n'
        "</svg>\n"
    )


def caption(meta):
    if not meta.get("play"):
        return meta["reason"]
    if meta.get("kind") == "wigwag":
        lo, hi = meta["range"]
        return (
            "Playback starts with a steady amber for 3 s (the duration at level crossings; "
            "5 s applies at swing or lifting bridges, airfields and emergency-vehicle premises), "
            "then the red lights flash at %d flashes/min, the midpoint of the sourced range "
            "%d–%d flashes/min, alternating so one is shown when the other is not. "
            "The sequence then loops for the page. Source: %s. "
            "If the system requests reduced motion, the lamps stay lit and the animation is paused."
            % (meta["play_per_min"], lo, hi, meta["source"])
        )
    lo, hi = meta["range"]
    play = meta["play_per_min"]
    if meta.get("play_choice") == "midpoint":
        rate = (
            "Playback at %d flashes/min, the midpoint of the sourced range %d–%d flashes/min."
            % (play, lo, hi)
        )
    else:
        rate = (
            "Playback at %d flashes/min, the lower end of the sourced range %d–%d flashes/min."
            % (play, lo, hi)
        )
    parts = [rate]
    if meta.get("pairs_alternate"):
        parts.append("Pairs alternate.")
    parts.append("Source: %s." % meta["source"])
    parts.append("If the system requests reduced motion, the lamps stay lit and the animation is paused.")
    return " ".join(parts)
