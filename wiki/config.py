"""Default source paths (all read-only) and fixed render settings."""
DEFAULTS = {
    "atlas": "/workspace/signage-atlas-work/signage-atlas",
    "matrix": "/workspace/signage-atlas-art/kit/street_furniture/sign/matrix",
    "art_placeholders": "/workspace/signage-atlas-art/placeholders",
    "kit020": "/workspace/gridforge-art/020/gf.module.bus_stop_ref.gfkit",
    "kit020_dir": "/workspace/gridforge-art/020",
    "look": "/workspace/signage-atlas-art/kit/street_furniture/bus_stop/look",
}
# 3D preview camera (degrees) and image size; fixed so output is deterministic.
CAM_AZIMUTH = 35.0
CAM_ELEVATION = 24.0
PREVIEW_W, PREVIEW_H, SUPERSAMPLE = 480, 360, 2
