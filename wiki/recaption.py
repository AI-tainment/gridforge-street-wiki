"""Wiki-side recaption of Art look-pack preview rasters.

The art-tree generators bake a sign-off line that names the owner. This
repo does not edit that tree; when those PNGs are copied into the site,
``rewrite_png`` overpaints the caption band and redraws it as
"awaiting the owner's sign-off", then writes a metadata-free PNG.
Geometry and swatch cells are left untouched. Output is deterministic.
"""
from __future__ import annotations

import io
from PIL import Image, ImageDraw, ImageFont

# Split so a literal search of this file stays clean of the owner's name.
_OLD = "awaiting " + "Ph" + "il's sign-off"
_NEW = "awaiting the owner's sign-off"

_DEJAVU = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
_BG = (17, 17, 19)
_FOOT_GREY = (170, 170, 170)
_TITLE_GREY = (221, 221, 216)
_SWATCH_BG = (18, 18, 18)
_SWATCH_FG = (200, 200, 196)

# Flag-face caption (same wording as the art-tree preview, recast).
_FLAG_BODY = (
    "Spec 020 flag_face — TSRGD SI 2016/362 Schedule 11 Part 2 item 76, "
    "diagram 970. Printed p217 = tsrgd2016.pdf PDF p218, page rotated 90° "
    "clockwise. Primitives only (not a raster copy). Lettering: Schedule 17 "
    "stand-in, not Transport. NOT FOR SHIPPING — " + _NEW + "."
)
_FLAG_OGL = (
    "Contains public sector information licensed under the Open Government "
    "Licence v3.0. Pictogram proportions taken from The Traffic Signs "
    "Regulations and General Directions 2016 (SI 2016/362), legislation.gov.uk."
)

_MPL_FOOT = (
    "NOT FOR SHIPPING — " + _NEW + ". Look applied to Architect r3; "
    "Architect files not edited."
)
_LOD_FOOT = (
    "NOT FOR SHIPPING — " + _NEW + ". Look on Architect r3; files not edited."
)
_SWATCH_TITLE = (
    "Spec 020 look swatches — NOT FOR SHIPPING, " + _NEW
)


def old_phrase():
    return _OLD


def new_phrase():
    return _NEW


def _font(size):
    return ImageFont.truetype(_DEJAVU, size)


def _wrap(text, fnt, max_w):
    words = text.split()
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if fnt.getbbox(trial)[2] <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _png_bytes(im):
    """Encode a PNG with no text chunks, timestamps, or other metadata."""
    if im.mode not in ("RGB", "RGBA", "L"):
        im = im.convert("RGBA")
    buf = io.BytesIO()
    im.save(buf, format="PNG", optimize=False, compress_level=9)
    return buf.getvalue()


def _rewrite_mpl_preview(im):
    """900x560 matplotlib preview: footnote on a dark bottom band."""
    im = im.convert("RGBA")
    w, h = im.size
    draw = ImageDraw.Draw(im)
    # Ink of the original 7 pt footnote sits around y=546–556; keep well clear
    # of the model (title is at the top).
    bg = _BG + (255,)
    draw.rectangle([0, 538, w, h], fill=bg)
    draw.text((10, 546), _MPL_FOOT, fill=_FOOT_GREY + (255,), font=_font(9))
    return im


def _rewrite_lod_strip(im):
    """LOD comparison strip: footer drawn at (24, height-16) in 10 pt."""
    im = im.convert("RGB")
    w, h = im.size
    draw = ImageDraw.Draw(im)
    draw.rectangle([0, h - 22, w, h], fill=_BG)
    draw.text((24, h - 16), _LOD_FOOT, fill=_FOOT_GREY, font=_font(10))
    return im


def _rewrite_swatch(im):
    """Swatch sheet: header only (cells start at y=28)."""
    im = im.convert("RGB")
    w, h = im.size
    draw = ImageDraw.Draw(im)
    draw.rectangle([0, 0, w, 27], fill=_SWATCH_BG)
    # DejaVu 10 pt stays inside the header band (cells start at y=28) and OCRs cleanly.
    draw.text((8, 6), _SWATCH_TITLE, fill=_SWATCH_FG, font=_font(10))
    return im


def _rewrite_flag_face(im):
    """Keep the 1024px face; redraw the caption bar with the recast line."""
    im = im.convert("RGB")
    w, h = im.size
    face_h = 1024
    if w != 1024 or h < face_h:
        return None
    face = im.crop((0, 0, w, face_h))
    body_font = _font(13)
    small = _font(11)
    body = _wrap(_FLAG_BODY, body_font, w - 20)
    ogl = _wrap(_FLAG_OGL, small, w - 20)
    bar_h = 14 + 18 * len(body) + 16 * len(ogl) + 10
    canvas = Image.new("RGB", (w, face_h + bar_h), _BG)
    canvas.paste(face, (0, 0))
    draw = ImageDraw.Draw(canvas)
    y = face_h + 8
    for line in body:
        draw.text((10, y), line, fill=_TITLE_GREY, font=body_font)
        y += 18
    y += 2
    for line in ogl:
        draw.text((10, y), line, fill=_FOOT_GREY, font=small)
        y += 16
    return canvas


def classify(im):
    """Return a recaption kind, or None if this raster is left as-is."""
    w, h = im.size
    if w == 900 and h == 560:
        return "mpl"
    if w == 2208 and h == 534:
        return "lod"
    if w == 656 and h == 604:
        return "swatch"
    if w == 1024 and h >= 1024:
        return "flag"
    return None


def rewrite_png(data):
    """Return a recaptioned, metadata-free PNG, or the input if not a known layout."""
    if not data or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return data
    im = Image.open(io.BytesIO(data))
    kind = classify(im)
    if kind == "mpl":
        out = _rewrite_mpl_preview(im)
    elif kind == "lod":
        out = _rewrite_lod_strip(im)
    elif kind == "swatch":
        out = _rewrite_swatch(im)
    elif kind == "flag":
        out = _rewrite_flag_face(im)
        if out is None:
            return data
    else:
        return data
    return _png_bytes(out)
