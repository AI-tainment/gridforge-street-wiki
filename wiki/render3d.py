"""Headless flat-shaded preview of a glTF 2.0 binary (GLB).

Software painter's-algorithm rasteriser: numpy for geometry, Pillow for polygon
fill. No GPU, no Blender, no randomness. Same input -> same PNG bytes.
"""
from __future__ import annotations
import io, json, math, struct
import numpy as np
from PIL import Image

CT = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
NC = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}

def parse_glb(b: bytes):
    magic, ver, length = struct.unpack("<4sII", b[:12])
    assert magic == b"glTF", "not a GLB"
    off, js, binc = 12, None, b""
    while off < length:
        clen, ctype = struct.unpack("<II", b[off:off + 8])
        chunk = b[off + 8: off + 8 + clen]
        if ctype == 0x4E4F534A:
            js = json.loads(chunk)
        elif ctype == 0x004E4942:
            binc = chunk
        off += 8 + clen
    return js, binc

def _acc(js, binc, i):
    a = js["accessors"][i]
    bv = js["bufferViews"][a["bufferView"]]
    n = NC[a["type"]]
    dt = np.dtype(CT[a["componentType"]])
    start = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    stride = bv.get("byteStride", 0)
    if stride and stride != n * dt.itemsize:
        raw = np.frombuffer(binc, np.uint8, count=stride * a["count"], offset=start).reshape(a["count"], stride)
        arr = raw[:, : n * dt.itemsize].copy().view(dt)
    else:
        arr = np.frombuffer(binc, dt, count=a["count"] * n, offset=start)
    return arr.reshape(a["count"], n) if n > 1 else arr

def _local(node):
    if "matrix" in node:
        return np.array(node["matrix"], float).reshape(4, 4).T
    t = np.array(node.get("translation", [0, 0, 0]), float)
    x, y, z, w = node.get("rotation", [0, 0, 0, 1])
    s = np.array(node.get("scale", [1, 1, 1]), float)
    r = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                  [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                  [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
    m = np.eye(4)
    m[:3, :3] = r * s
    m[:3, 3] = t
    return m

def triangles(js, binc):
    """List of (tri[3,3] world coords, material name, alpha, base rgba)."""
    out = []
    mats = js.get("materials", [])
    def walk(ni, parent):
        node = js["nodes"][ni]
        m = parent @ _local(node)
        if "mesh" in node:
            for prim in js["meshes"][node["mesh"]]["primitives"]:
                if prim.get("mode", 4) != 4:
                    continue
                pos = _acc(js, binc, prim["attributes"]["POSITION"]).astype(float)
                idx = _acc(js, binc, prim["indices"]).astype(int) if "indices" in prim else np.arange(len(pos))
                pw = (np.c_[pos, np.ones(len(pos))] @ m.T)[:, :3]
                mat = mats[prim["material"]] if "material" in prim else {}
                rgba = mat.get("pbrMetallicRoughness", {}).get("baseColorFactor", [0.7, 0.7, 0.7, 1])
                if mat.get("alphaMode", "OPAQUE") != "BLEND":
                    rgba = list(rgba[:3]) + [1.0]
                for t in idx.reshape(-1, 3):
                    out.append((pw[t], mat.get("name", ""), list(rgba)))
        for c in node.get("children", []):
            walk(c, m)
    scene = js["scenes"][js.get("scene", 0)]
    for n in scene["nodes"]:
        walk(n, np.eye(4))
    return out

def render(glb: bytes, palette=None, az=35.0, el=24.0, size=(480, 360), ss=2) -> bytes:
    """PNG bytes. palette: {material name: rgba} overrides glTF base colours."""
    js, binc = parse_glb(glb)
    tris = triangles(js, binc)
    W, H = size[0] * ss, size[1] * ss
    a, e = math.radians(az), math.radians(el)
    # glTF +Y up. View direction (from camera to target).
    fwd = np.array([math.sin(a) * math.cos(e), -math.sin(e), math.cos(a) * math.cos(e)])
    right = np.cross(fwd, [0, 1, 0]); right /= np.linalg.norm(right)
    up = np.cross(right, fwd)
    light = np.array([0.4, 0.85, -0.35]); light /= np.linalg.norm(light)
    allp = np.concatenate([t[0] for t in tris]) if tris else np.zeros((1, 3))
    lo, hi = allp.min(0), allp.max(0)
    # ground plate under the model
    pad = 0.25 + 0.08 * float(max(hi - lo))
    g = [np.array([[lo[0] - pad, 0, lo[2] - pad], [hi[0] + pad, 0, lo[2] - pad], [hi[0] + pad, 0, hi[2] + pad]]),
         np.array([[lo[0] - pad, 0, lo[2] - pad], [hi[0] + pad, 0, hi[2] + pad], [lo[0] - pad, 0, hi[2] + pad]])]
    ground = [(t, "_ground", [0.80, 0.80, 0.78, 1.0]) for t in g]
    allp = np.concatenate([allp] + g)
    px, py = allp @ right, allp @ up
    sc = 0.9 * min(W / max(np.ptp(px), 1e-6), H / max(np.ptp(py), 1e-6))
    cx, cy = (px.max() + px.min()) / 2, (py.max() + py.min()) / 2
    def proj(P):
        return np.stack([W / 2 + (P @ right - cx) * sc, H / 2 - (P @ up - cy) * sc, P @ fwd], 1)
    img = np.empty((H, W, 3), float); img[:] = (246 / 255, 246 / 255, 242 / 255)
    zbuf = np.full((H, W), np.inf)
    opaque, blend = [], []
    for P, name, rgba in ground + tris:
        if palette and name in palette:
            rgba = list(palette[name][:3]) + [rgba[3]]
        n = np.cross(P[1] - P[0], P[2] - P[0]); ln = np.linalg.norm(n)
        if ln < 1e-12:
            continue
        shade = 0.55 + 0.45 * abs(float((n / ln) @ light)) if name != "_ground" else 1.0
        col = np.clip(np.array(rgba[:3], float) * shade, 0, 1)
        q = proj(P)
        (blend if rgba[3] < 1.0 else opaque).append((float(q[:, 2].mean()), q, col, float(rgba[3])))
    def raster(q, col, alpha):
        x0, x1 = int(max(0, np.floor(q[:, 0].min()))), int(min(W - 1, np.ceil(q[:, 0].max())))
        y0, y1 = int(max(0, np.floor(q[:, 1].min()))), int(min(H - 1, np.ceil(q[:, 1].max())))
        if x1 < x0 or y1 < y0:
            return
        ys, xs = np.mgrid[y0:y1 + 1, x0:x1 + 1]
        px_, py_ = xs + 0.5, ys + 0.5
        (ax, ay, az_), (bx, by, bz), (qx, qy, qz) = q
        den = (by - qy) * (ax - qx) + (qx - bx) * (ay - qy)
        if abs(den) < 1e-12:
            return
        w0 = ((by - qy) * (px_ - qx) + (qx - bx) * (py_ - qy)) / den
        w1 = ((qy - ay) * (px_ - qx) + (ax - qx) * (py_ - qy)) / den
        w2 = 1 - w0 - w1
        inside = (w0 >= -1e-9) & (w1 >= -1e-9) & (w2 >= -1e-9)
        z = w0 * az_ + w1 * bz + w2 * qz - (1e-4 if alpha < 1 else 0)
        zb = zbuf[y0:y1 + 1, x0:x1 + 1]
        m = inside & (z < zb)
        sub = img[y0:y1 + 1, x0:x1 + 1]
        if alpha >= 1.0:
            sub[m] = col; zb[m] = z[m]
        else:
            sub[m] = sub[m] * (1 - alpha) + col * alpha
    for _, q, col, al in opaque:
        raster(q, col, al)
    for _, q, col, al in sorted(blend, key=lambda t: (-t[0], tuple(t[2]))):
        raster(q, col, al)
    im = Image.fromarray(np.round(img * 255).astype(np.uint8), "RGB").resize(size, Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=False)
    return buf.getvalue()
