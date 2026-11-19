"""Source paths and fixed render settings.

Source paths are resolved in this order (first wins):
  1. command-line flags (--atlas, --matrix, ...)
  2. environment variables (GFWIKI_ATLAS, GFWIKI_MATRIX, ...)
  3. wiki/local_config.json (gitignored; copy wiki/local_config.json.example)
  4. the relative placeholder defaults below (relative to the repo root)
All sources are read-only. Missing sources stop the build with a clear message.
"""
import json, os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCAL_CONFIG = os.path.join(REPO, "wiki", "local_config.json")

# key -> (placeholder default relative to the repo root, what it is)
SOURCES = {
    "atlas": ("sources/signage-atlas", "Signage Atlas checkout"),
    "matrix": ("sources/signage-atlas-art/kit/street_furniture/sign/matrix", "Art's matrix glyph grids"),
    "art_placeholders": ("sources/signage-atlas-art/placeholders", "Art's batches 10-12"),
    "kit020": ("sources/gridforge-art/020/gf.module.bus_stop_ref.gfkit", "Spec 020 bus stop kit (.gfkit)"),
    "kit020_dir": ("sources/gridforge-art/020", "Spec 020 kit folder"),
    "look": ("sources/signage-atlas-art/kit/street_furniture/bus_stop/look", "Art's look pack"),
}
DEFAULTS = {k: v[0] for k, v in SOURCES.items()}


def env_name(key):
    return "GFWIKI_" + key.upper()


def resolve(overrides=None):
    """Absolute source paths after flags > env > local_config.json > defaults."""
    local = {}
    if os.path.exists(LOCAL_CONFIG):
        with open(LOCAL_CONFIG, encoding="utf-8") as f:
            local = json.load(f)
    out = {}
    for k, (default, _) in SOURCES.items():
        v = (overrides or {}).get(k) or os.environ.get(env_name(k)) or local.get(k) or default
        out[k] = os.path.abspath(os.path.join(REPO, os.path.expanduser(v)))
    return out


def require(paths):
    missing = [(k, p) for k, p in sorted(paths.items()) if not os.path.exists(p)]
    if missing:
        lines = ["error: source path(s) not found:"]
        for k, p in missing:
            lines.append("  %-17s %s  (%s; set --%s, %s or wiki/local_config.json)"
                         % (k, p, SOURCES[k][1], k.replace("_", "-"), env_name(k)))
        raise SystemExit("\n".join(lines))
    return paths


# 3D preview camera (degrees) and image size; fixed so output is deterministic.
CAM_AZIMUTH = 35.0
CAM_ELEVATION = 24.0
PREVIEW_W, PREVIEW_H, SUPERSAMPLE = 480, 360, 2
