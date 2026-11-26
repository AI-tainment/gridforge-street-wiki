#!/usr/bin/env python3
"""Acceptance checks for the wiki.

    python3 tests/check.py [--site site]

(a) builds the wiki twice into fresh temp folders; trees must be byte-identical
    (diff -r and a sha256 manifest), and identical to the committed --site;
(b) link check: every internal href/src in every HTML file resolves to a file;
(c) item counts, taken from the sources independently of wiki/loaders.py,
    must equal the generated item pages (printed as a table).
Plus: no font files / @font-face / web-font hosts, no absolute or file: links,
no former-engine mark in site/ or tracked files (see tests/standalone-allow.txt),
image-text OCR of every tracked PNG/JPG (tesseract required) and a grep of SVG text.
Exit code 0 only if every check passes.
"""
import hashlib, io, json, os, re, shutil, subprocess, sys, tempfile, zipfile
from html.parser import HTMLParser
from urllib.parse import urlsplit, unquote

sys.dont_write_bytecode = True
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "wiki"))
import config  # paths only
import sanitise
D = config.resolve()


def manifest(root):
    out = []
    for dp, dn, fn in os.walk(root):
        dn.sort()
        for f in sorted(fn):
            p = os.path.join(dp, f)
            out.append("%s  %s" % (hashlib.sha256(open(p, "rb").read()).hexdigest(), os.path.relpath(p, root)))
    return "\n".join(sorted(out, key=lambda l: l[66:])) + "\n"


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.refs = []

    def handle_starttag(self, tag, attrs):
        for k, v in attrs:
            if k in ("href", "src") and v is not None:
                self.refs.append(v)


def link_check(root):
    bad, n = [], 0
    for dp, dn, fn in os.walk(root):
        for f in fn:
            if not f.endswith((".html", ".css")):
                continue
            p = os.path.join(dp, f)
            txt = open(p, encoding="utf-8").read()
            if f.endswith(".css"):
                refs = re.findall(r"url\(([^)]+)\)", txt)
            else:
                lp = Links(); lp.feed(txt); refs = lp.refs
            for r in refs:
                u = urlsplit(r)
                if u.scheme in ("http", "https", "mailto"):
                    continue
                n += 1
                if u.scheme or r.startswith("/"):
                    bad.append((os.path.relpath(p, root), r, "absolute/scheme link"))
                    continue
                if not u.path:
                    continue
                tgt = os.path.normpath(os.path.join(dp, unquote(u.path)))
                if not tgt.startswith(os.path.abspath(root)) or not os.path.isfile(tgt):
                    bad.append((os.path.relpath(p, root), r, "missing"))
    return n, bad


def source_counts():
    uk = os.path.join(D["atlas"], "countries/uk")
    signs = json.load(open(os.path.join(uk, "signs.json")))
    c = {
        "signs": len(signs),
        "signs drawn (glyph=true)": sum(1 for r in signs if r.get("glyph")),
        "signs placeholder (glyph=false)": sum(1 for r in signs if not r.get("glyph")),
        "markings": len(json.load(open(os.path.join(uk, "markings.json")))),
        "furniture": len(json.load(open(os.path.join(uk, "furniture.json")))),
        "matrix": sum(1 for dp, dn, fn in os.walk(D["matrix"]) for f in fn if f.endswith(".war")),
    }
    rows = [l for l in open(os.path.join(D["art_placeholders"], "MANIFEST.md"), encoding="utf-8") if re.match(r"\|\s*\d", l)]
    c["artdraft"] = len(rows)
    c["artdraft drawn (Y)"] = sum(1 for l in rows if l.rstrip().rstrip("|").strip().endswith("Y"))
    c["artdraft unverified (U)"] = sum(1 for l in rows if l.rstrip().rstrip("|").strip().endswith("U"))
    slots = json.loads(zipfile.ZipFile(D["kit020"]).read("kit.manifest.json"))["slots"]
    c["furniture3d"] = len(slots) + 1  # + Art look pack page
    return c


def site_counts(site):
    c = {}
    stat = {}
    for cat in sorted(os.listdir(os.path.join(site, "items"))):
        files = [f for f in os.listdir(os.path.join(site, "items", cat)) if f.endswith(".html")]
        c[cat] = len(files)
        for f in files:
            t = open(os.path.join(site, "items", cat, f), encoding="utf-8").read()
            m = re.search(r'<span class="badge [a-z]+">([^<]+)</span>', t)
            stat.setdefault(cat, {}).setdefault(m.group(1), []).append(f[:-5])
    s = stat.get("signs", {})
    ph = len(s.get("Placeholder", [])) + len(s.get("Unverified source", []))
    c["signs drawn (glyph=true)"] = c["signs"] - ph
    c["signs placeholder (glyph=false)"] = ph
    a = stat.get("artdraft", {})
    c["artdraft drawn (Y)"] = len(a.get("Art draft, not yet imported", []))
    c["artdraft unverified (U)"] = len(a.get("Unverified source", []))
    return c, stat


def check_sanitise():
    """Unit cases for the single build-time rewrite of a former engine name."""
    mark = "Grid" + "Forge"
    cases = [
        (mark + " Street Wiki", sanitise.SITE_NAME),
        ("in the " + mark + " sources", "in the project sources"),
        ("CC0-1.0 (" + mark + " original)", "CC0-1.0 (original)"),
        ("CC0-1.0. " + mark + " original placeholder geometry (Spec 020 reference).",
         "CC0-1.0. original placeholder geometry (Spec 020 reference)."),
        ("Evidence: " + mark.lower() + "-reviews/foo.md", "Evidence: reviews/foo.md"),
        ("Copied from " + mark + " docs", "Copied from the project docs"),
        ("like " + mark + "'s cooker", "like the project's cooker"),
        ("silhouettes for " + mark + ".", "silhouettes for the project."),
        ("vendor/" + mark.lower() + "/UkTsrgdCatalogue.cs", "vendor/catalogue/UkTsrgdCatalogue.cs"),
        ("sources/" + mark.lower() + "-art/020", "sources/art-kit/020"),
        ("format: " + mark.lower() + ".kit", "format: kit"),
        (sanitise.SITE_NAME + " \u00a9 2026 AI-tainment", sanitise.SITE_NAME + " \u00a9 2026 AI-tainment"),
    ]
    failures = []
    for src, want in cases:
        got = sanitise.sanitise(src)
        if got != want or sanitise.still_marked(got):
            failures.append((src, want, got))
    return failures


def load_standalone_allow():
    path = os.path.join(REPO, "tests", "standalone-allow.txt")
    allow = {}
    if not os.path.isfile(path):
        return allow, path
    for line in open(path, encoding="utf-8"):
        raw = line.strip()
        if not raw or raw.startswith("#"):
            continue
        if "#" in raw:
            phrase, reason = raw.split("#", 1)
        else:
            phrase, reason = raw, "listed"
        phrase = phrase.strip()
        if phrase:
            allow[phrase.lower()] = reason.strip()
    return allow, path


def scan_standalone_mark(site):
    """Fail if the former engine mark appears in site/ or tracked files."""
    needle = "grid" + "forge"
    pat = re.compile(needle, re.I)
    allow, allow_path = load_standalone_allow()
    hits = []
    tracked = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True).stdout.split("\n")
    paths = [os.path.join(REPO, f) for f in tracked if f and not f.startswith("site/")]
    for dp, dn, fn in os.walk(site):
        paths += [os.path.join(dp, f) for f in fn]
    allow_rel = os.path.relpath(allow_path, REPO) if os.path.isfile(allow_path) else None
    for pth in sorted(set(paths)):
        if not os.path.isfile(pth):
            continue
        rel = os.path.relpath(pth, REPO)
        if allow_rel and rel == allow_rel:
            continue
        b = open(pth, "rb").read()
        if b"\0" in b[:8192]:
            continue
        text = b.decode("utf-8", "replace")
        if pat.search(rel):
            hits.append((pat.sub("***", rel), "path"))
        for m in pat.finditer(text):
            w = re.search(r"\w*$", text[:m.start()]).group(0) + m.group(0) + re.match(r"\w*", text[m.end():]).group(0)
            if w.lower() not in allow:
                hits.append((rel, w[:1] + "*" * (len(w) - 1)))
    return hits, allow


def vendor_manifest():
    return json.load(open(os.path.join(REPO, "wiki/vendor/manifest.json"), encoding="utf-8"))


def check_vendor_hashes():
    man = vendor_manifest()
    bad = []
    for rel, expect in sorted(man["files"].items()):
        p = os.path.join(REPO, "wiki/vendor", rel)
        if not os.path.isfile(p):
            bad.append((rel, "missing"))
            continue
        got = hashlib.sha256(open(p, "rb").read()).hexdigest()
        if got != expect:
            bad.append((rel, "hash mismatch"))
    return man, bad


def check_3d(site, say):
    ok = True
    man, bad = check_vendor_hashes()
    site_bad = []
    for rel, expect in sorted(man["files"].items()):
        sp = os.path.join(site, "assets/vendor", rel)
        if not os.path.isfile(sp):
            site_bad.append((rel, "not copied to site"))
            continue
        got = hashlib.sha256(open(sp, "rb").read()).hexdigest()
        if got != expect:
            site_bad.append((rel, "site hash mismatch"))
    say("    3D vendor: %s %s, %d file hash(es) %s" % (
        man.get("viewer"), man.get("version"),
        len(man["files"]), "OK" if not bad and not site_bad else "FAIL %s %s" % (bad[:3], site_bad[:3])))
    ok &= not bad and not site_bad

    missing = []
    pages = 0
    glb_marked = 0
    cov_path = os.path.join(site, "3d-assets.html")
    cov_html = open(cov_path, encoding="utf-8").read() if os.path.isfile(cov_path) else ""
    item_dir = os.path.join(site, "items/furniture3d")
    if os.path.isdir(item_dir):
        for f in sorted(os.listdir(item_dir)):
            if not f.endswith(".html"):
                continue
            pages += 1
            slug = f[:-5]
            html = open(os.path.join(item_dir, f), encoding="utf-8").read()
            has_viewer = 'class="mv"' in html and "data-src=" in html
            glb_p = os.path.join(site, "media/furniture3d", slug + ".glb")
            poster = os.path.join(site, "media/furniture3d", slug + ".png")
            if has_viewer:
                glb_marked += 1
                if not os.path.isfile(glb_p) or not os.path.isfile(poster):
                    missing.append(slug + " missing glb or poster")
            else:
                if slug not in cov_html:
                    missing.append(slug + " has no viewer and is not listed in 3d-assets.html")
    say("    3D items: %d furniture3d pages, %d interactive, %d missing GLB/poster/listing %s" % (
        pages, glb_marked, len(missing), missing[:5]))
    ok &= pages > 0 and glb_marked > 0 and not missing

    remote = []
    src_re = re.compile(
        r"(?is)<(?:script|img|source|model-viewer|link)\b[^>]+\b(?:src|href)\s*=\s*[\"'](?:https?:)?//"
    )
    for dp, dn, fn in os.walk(site):
        for f in fn:
            if not f.endswith((".html", ".js", ".css")):
                continue
            rel = os.path.relpath(os.path.join(dp, f), site)
            if rel.startswith("code") or rel.startswith("assets/vendor/"):
                continue
            text = open(os.path.join(dp, f), encoding="utf-8", errors="replace").read()
            if f.endswith(".html"):
                if src_re.search(text):
                    remote.append(rel)
                if 'type="importmap"' in text:
                    m = re.search(r'<script type="importmap">(.*?)</script>', text, re.S)
                    if m and re.search(r"https?:", m.group(1)):
                        remote.append(rel + " importmap")
            elif rel == "assets/model-view.js":
                if re.search(r"['\"]https?://", text):
                    remote.append(rel)
    say("    3D remote URLs: %d disallowed resource URL(s) %s" % (len(remote), remote[:5]))
    ok &= not remote

    mark = "grid" + "forge"
    home = "/" + "ho" + "me/" + "p" + "hil"
    dirty = []
    media = os.path.join(site, "media/furniture3d")
    if os.path.isdir(media):
        for f in sorted(os.listdir(media)):
            if not f.endswith(".glb"):
                continue
            b = open(os.path.join(media, f), "rb").read()
            low = b.lower()
            if mark.encode() in low or home.encode() in low:
                dirty.append(f)
    say("    3D GLB metadata: %d dirty file(s) %s" % (len(dirty), dirty[:5]))
    ok &= not dirty
    return ok


def check_animation(site, say):
    ok = True
    # reduced-motion CSS present in the published stylesheet
    css = open(os.path.join(site, "assets/wiki.css"), encoding="utf-8").read()
    rm = "prefers-reduced-motion" in css and "anim-paused" in css
    say("    animation reduced-motion CSS: %s" % ("OK" if rm else "FAIL"))
    ok &= rm
    cov = os.path.join(site, "animation-coverage.html")
    cov_ok = os.path.isfile(cov)
    say("    animation coverage page: %s" % ("OK" if cov_ok else "FAIL"))
    ok &= cov_ok
    # every published playback SVG has a sourced period and a matching item page
    missing, unverified, played = [], 0, 0
    for cat in ("signs", "furniture"):
        d = os.path.join(site, "items", cat)
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if not f.endswith(".html"):
                continue
            html = open(os.path.join(d, f), encoding="utf-8").read()
            slug = f[:-5]
            has_badge = "UNVERIFIED timing" in html
            has_play = "--anim.svg" in html or "Sourced playback" in html
            if has_play:
                played += 1
                anim = os.path.join(site, "media", cat, slug + "--anim.svg")
                if not os.path.isfile(anim):
                    missing.append(slug + " playback page without SVG")
                else:
                    svg = open(anim, encoding="utf-8").read()
                    if "prefers-reduced-motion" not in svg:
                        missing.append(slug + " SVG missing reduced-motion")
                if "Source:" not in html and "Sch 15" not in html:
                    missing.append(slug + " page missing timing source")
                if has_badge:
                    missing.append(slug + " playback also has UNVERIFIED badge")
            elif has_badge:
                unverified += 1
                if os.path.isfile(os.path.join(site, "media", cat, slug + "--anim.svg")):
                    missing.append(slug + " UNVERIFIED item has a playback SVG")
    say("    animation items: %d sourced playback, %d UNVERIFIED, %d problems %s" % (
        played, unverified, len(missing), missing[:5]))
    ok &= played >= 1 and unverified >= 1 and not missing
    # "animation paused" note is in playback captions
    if played:
        # sample one known item
        for sample in ("items/furniture/lane-signal.html", "items/furniture/verge-ms.html"):
            fp = os.path.join(site, sample)
            if os.path.isfile(fp):
                html = open(fp, encoding="utf-8").read()
                if "anim-paused" not in html:
                    say("    animation paused note: FAIL on %s" % sample)
                    ok = False
                else:
                    say("    animation paused note: OK")
                break
    return ok


def _tess_run(args, timeout=60):
    return subprocess.run(args, capture_output=True, timeout=timeout)


def tesseract_version():
    """Return tesseract version string, or None if the binary is missing."""
    exe = shutil.which("tesseract")
    if not exe:
        return None
    r = _tess_run([exe, "--version"])
    text = (r.stdout or b"") + (r.stderr or b"")
    first = text.decode("utf-8", "replace").splitlines()[0].strip() if text else ""
    return first or "tesseract (version unknown)"


# Needles assembled from parts so this file stays clean of the banned mark
# and of the owner's name (the text-only no-name / standalone-mark scans
# would otherwise flag the checker itself).
_MARK = "grid" + "forge"
_FIRST = "ph" + "il"
_LAST = "rob" + "inson"
_HOME = "/" + "ho" + "me" + "/"

# OCR-tolerant mark: optional separators, common glyph confusions (1/l/i, 0/o).
_MARK_RX = re.compile(r"g[\W_]*r[\W_]*[i1l][\W_]*d[\W_]*f[\W_]*[o0][\W_]*r[\W_]*g[\W_]*e", re.I)
_MARK_COLLAPSED_RX = re.compile(r"gr[i1l]df[o0]rge", re.I)
_FIRST_COLLAPSED_RX = re.compile(r"ph[i1l][i1lt]s?(?:sign|$)")
# Owner's first name as a whole word, plus OCR noise (l/t/1) and optional possessive.
# Must not match a compound with a letter immediately before or after.
_FIRST_RX = re.compile(r"(?<![a-z0-9])ph[i1l][i1lt](?:['’`]s)?(?![a-z0-9])", re.I)
_LAST_RX = re.compile(r"(?<![a-z0-9])r[o0]b[i1l]ns[o0]n(?![a-z0-9])", re.I)
_HOME_RX = re.compile(re.escape(_HOME) + r"\s*ph[i1l][i1lt]", re.I)
# Exact-ish forms in SVG / metadata (no OCR noise to forgive).
_MARK_TEXT_RX = re.compile(r"grid[\s._-]*forge", re.I)
_FIRST_TEXT_RX = re.compile(r"(?<![a-z0-9])" + re.escape(_FIRST) + r"(?:['’]s)?(?![a-z0-9])", re.I)
_LAST_TEXT_RX = re.compile(r"(?<![a-z0-9])" + re.escape(_LAST) + r"(?![a-z0-9])", re.I)
_HOME_TEXT_RX = re.compile(re.escape(_HOME) + re.escape(_FIRST), re.I)

_RASTER_EXT = (".png", ".jpg", ".jpeg")
_HIST_COMMIT = "a56e717"
_HIST_SHOTS = [
    "qa/screenshots/01-home.png",
    "qa/screenshots/02-category-warning-signs.png",
    "qa/screenshots/03-drawn-sign-670.png",
    "qa/screenshots/04-placeholder-sign-2026.png",
    "qa/screenshots/05-3d-bay3-cantilever.png",
    "qa/screenshots/06-matrix-6031.1.png",
    "qa/screenshots/07-code-build-py.png",
    "qa/screenshots/08-licences.png",
]
_HIST_LOOK = [
    "site/media/furniture3d/look-pack/previews/bay1_cantilever.png",
    "site/media/furniture3d/look-pack/previews/bay2_cantilever.png",
    "site/media/furniture3d/look-pack/previews/bay3_cantilever.png",
    "site/media/furniture3d/look-pack/previews/bay3_enclosed.png",
    "site/media/furniture3d/look-pack/previews/bench.png",
    "site/media/furniture3d/look-pack/previews/bin.png",
    "site/media/furniture3d/look-pack/previews/flag_face.png",
    "site/media/furniture3d/look-pack/previews/flag_plate.png",
    "site/media/furniture3d/look-pack/previews/lod_strip_bay3_cantilever.png",
    "site/media/furniture3d/look-pack/swatches/swatch_sheet.png",
]


def mask_secret(text):
    """Replace banned mark / name in a snippet so reports stay clean."""
    if not text:
        return text
    def star(m):
        s = m.group(0)
        return s[0] + "*" * (len(s) - 1)
    out = _MARK_RX.sub(star, text)
    out = _MARK_TEXT_RX.sub(star, out)
    out = _FIRST_RX.sub(star, out)
    out = _FIRST_TEXT_RX.sub(star, out)
    out = _LAST_RX.sub(star, out)
    out = _LAST_TEXT_RX.sub(star, out)
    out = _HOME_RX.sub(lambda m: m.group(0)[0] + "*" * (len(m.group(0)) - 1), out)
    out = _HOME_TEXT_RX.sub(lambda m: m.group(0)[0] + "*" * (len(m.group(0)) - 1), out)
    # Cramped OCR that glues the name onto "sign-off".
    out = re.sub(r"ph[i1l][i1lt]s?sign", lambda m: m.group(0)[0] + "*" * (len(m.group(0)) - 1), out, flags=re.I)
    return out


def _collapse(text):
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def find_image_text_hits(text, tolerant=True):
    """Return a list of (kind, masked snippet) hits in text."""
    if not text:
        return []
    hits = []
    mark_rx = _MARK_RX if tolerant else _MARK_TEXT_RX
    first_rx = _FIRST_RX if tolerant else _FIRST_TEXT_RX
    last_rx = _LAST_RX if tolerant else _LAST_TEXT_RX
    home_rx = _HOME_RX if tolerant else _HOME_TEXT_RX
    for rx, kind in ((mark_rx, "mark"), (first_rx, "name"), (last_rx, "name"), (home_rx, "home")):
        for m in rx.finditer(text):
            lo, hi = max(0, m.start() - 20), min(len(text), m.end() + 20)
            snippet = mask_secret(re.sub(r"\s+", " ", text[lo:hi]).strip())
            hits.append((kind, snippet))
    if tolerant:
        collapsed = _collapse(text)
        if _MARK_COLLAPSED_RX.search(collapsed) and not any(k == "mark" for k, _ in hits):
            hits.append(("mark", "[collapsed]"))
        if _FIRST_COLLAPSED_RX.search(collapsed) and not any(k == "name" for k, _ in hits):
            hits.append(("name", "[collapsed]"))
    # unique, stable
    seen, out = set(), []
    for h in hits:
        if h not in seen:
            seen.add(h)
            out.append(h)
    return out


def png_text_chunks(data):
    """Extract tEXt / zTXt / iTXt strings from a PNG, if any."""
    import struct, zlib
    out = []
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return out
    i = 8
    nlen = len(data)
    while i + 8 <= nlen:
        n = struct.unpack(">I", data[i:i + 4])[0]
        typ = data[i + 4:i + 8]
        start = i + 8
        if start + n + 4 > nlen:
            break
        chunk = data[start:start + n]
        i = start + n + 4
        try:
            if typ == b"tEXt":
                out.append(chunk.replace(b"\x00", b"=").decode("latin-1", "replace"))
            elif typ == b"zTXt":
                nul = chunk.find(b"\x00")
                if nul >= 0 and len(chunk) > nul + 2:
                    out.append(chunk[:nul].decode("latin-1", "replace") + "=" +
                               zlib.decompress(chunk[nul + 2:]).decode("utf-8", "replace"))
            elif typ == b"iTXt":
                nul = chunk.find(b"\x00")
                if nul >= 0 and len(chunk) >= nul + 5:
                    rest = chunk[nul + 1:]
                    comp, _meth = rest[0], rest[1]
                    # lang\0 trans\0 text
                    parts = rest[2:].split(b"\x00", 2)
                    body = parts[-1] if parts else b""
                    if comp == 1:
                        body = zlib.decompress(body)
                    out.append(chunk[:nul].decode("latin-1", "replace") + "=" +
                               body.decode("utf-8", "replace"))
            elif typ == b"IEND":
                break
        except Exception:
            continue
    return out


def raster_metadata_text(path):
    parts = []
    data = open(path, "rb").read()
    parts.extend(png_text_chunks(data))
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(data) if False else path)
        if im.info:
            for k, v in im.info.items():
                parts.append("%s=%s" % (k, v))
        exif = getattr(im, "getexif", lambda: None)()
        if exif:
            for k, v in exif.items():
                parts.append("exif:%s=%s" % (k, v))
    except Exception:
        pass
    return "\n".join(str(p) for p in parts)


def ocr_raster(path, exe):
    """OCR a raster with several page-segmentation modes; return combined text."""
    chunks = []
    for psm in ("4", "6", "11"):
        r = _tess_run([exe, path, "stdout", "--psm", psm, "-l", "eng"], timeout=90)
        chunks.append(r.stdout.decode("utf-8", "replace"))
    return "\n".join(chunks)


def list_rasters(site):
    """Tracked PNG/JPG plus every raster under site/, unique and sorted."""
    tracked = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True).stdout.split("\n")
    paths = []
    for f in tracked:
        if f and os.path.splitext(f)[1].lower() in _RASTER_EXT:
            paths.append(os.path.join(REPO, f))
    if os.path.isdir(site):
        for dp, dn, fn in os.walk(site):
            for f in fn:
                if os.path.splitext(f)[1].lower() in _RASTER_EXT:
                    paths.append(os.path.join(dp, f))
    # unique by real path
    out, seen = [], set()
    for p in paths:
        if not os.path.isfile(p):
            continue
        rp = os.path.realpath(p)
        if rp in seen:
            continue
        seen.add(rp)
        out.append(p)
    return sorted(out, key=lambda p: os.path.relpath(p, REPO))


def list_svgs(site):
    tracked = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True).stdout.split("\n")
    paths = [os.path.join(REPO, f) for f in tracked if f.lower().endswith(".svg")]
    if os.path.isdir(site):
        for dp, dn, fn in os.walk(site):
            for f in fn:
                if f.lower().endswith(".svg"):
                    paths.append(os.path.join(dp, f))
    out, seen = [], set()
    for p in paths:
        if not os.path.isfile(p):
            continue
        rp = os.path.realpath(p)
        if rp in seen:
            continue
        seen.add(rp)
        out.append(p)
    return sorted(out, key=lambda p: os.path.relpath(p, REPO))


def _git_show(commit, rel):
    r = subprocess.run(["git", "show", "%s:%s" % (commit, rel)], cwd=REPO,
                       capture_output=True)
    if r.returncode != 0:
        return None
    return r.stdout


def _commit_is_ancestor(commit):
    r = subprocess.run(["git", "merge-base", "--is-ancestor", commit, "HEAD"], cwd=REPO)
    return r.returncode == 0


def _write_unit_png(path, lines, size=(640, 160)):
    from PIL import Image, ImageDraw, ImageFont
    im = Image.new("RGB", size, (17, 17, 19))
    draw = ImageDraw.Draw(im)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 22)
    except Exception:
        font = ImageFont.load_default()
    y = 24
    for line in lines:
        draw.text((16, y), line, fill=(230, 230, 224), font=font)
        y += 36
    im.save(path, format="PNG", optimize=False, compress_level=9)


def check_image_text(site, say):
    """OCR tracked and site rasters, grep SVGs, and scan image metadata."""
    ok = True
    ver = tesseract_version()
    if not ver:
        say("    image-text tesseract: MISSING (required as a dev/test tool; install tesseract-ocr and re-run)")
        return False
    say("    image-text tesseract: %s" % ver)
    exe = shutil.which("tesseract")

    # --- unit: the matcher must flag a synthetic dirty raster and spare a clean one
    unit_bad = []
    with tempfile.TemporaryDirectory() as td:
        dirty = os.path.join(td, "dirty.png")
        clean = os.path.join(td, "clean.png")
        _write_unit_png(dirty, [
            ("G" + "rid" + "F" + "orge") + " Street Wiki",
            "awaiting " + ("Ph" + "il's") + " sign-off.",
            _HOME + _FIRST,
        ])
        _write_unit_png(clean, [
            "Street Wiki",
            "awaiting the owner's sign-off.",
            ("Up" + "hill road marking"),
        ])
        d_hits = find_image_text_hits(ocr_raster(dirty, exe), tolerant=True)
        c_hits = find_image_text_hits(ocr_raster(clean, exe), tolerant=True)
        kinds = {k for k, _ in d_hits}
        if "mark" not in kinds or "name" not in kinds or "home" not in kinds:
            unit_bad.append("dirty raster not fully flagged (got %s)" % sorted(kinds))
        if c_hits:
            unit_bad.append("clean raster flagged: %s" % c_hits[:3])
        # recaption of a 900x560 band must drop the name and show the owner wording
        import recaption
        from PIL import Image, ImageDraw, ImageFont
        im = Image.new("RGBA", (900, 560), (17, 17, 19, 255))
        d = ImageDraw.Draw(im)
        d.text((10, 546), "NOT FOR SHIPPING — awaiting " + ("Ph" + "il's") + " sign-off.",
               fill=(170, 170, 170, 255),
               font=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 9))
        buf = io.BytesIO(); im.save(buf, format="PNG")
        rewritten = recaption.rewrite_png(buf.getvalue())
        recap_path = os.path.join(td, "recap.png")
        open(recap_path, "wb").write(rewritten)
        recap_text = ocr_raster(recap_path, exe)
        if find_image_text_hits(recap_text, tolerant=True):
            unit_bad.append("recaption left a name/mark: %s" % mask_secret(recap_text)[:120])
        if recaption.new_phrase().lower() not in recap_text.lower().replace("’", "'"):
            # tolerate a missing apostrophe in OCR
            folded = recap_text.lower().replace("’", "'").replace("'", "")
            if "awaiting the owners sign-off" not in folded:
                unit_bad.append("recaption missing new wording: %s" % mask_secret(recap_text)[:120])
        meta = png_text_chunks(rewritten)
        if meta:
            unit_bad.append("recaption wrote metadata: %s" % meta[:3])
    if unit_bad:
        say("    image-text unit: FAIL %s" % unit_bad[:3])
        ok = False
    else:
        say("    image-text unit: OK")

    # --- current rasters
    rasters = list_rasters(site)
    skipped = []  # (rel, why)
    ocr_hits = []  # (rel, kind, snippet)
    meta_hits = []
    scanned = 0
    # Official Crown faces are published as SVG (--eps.svg), not rasters, so
    # they are grepped below rather than OCR'd. No Crown EPS raster is tracked
    # today, and nothing is skipped as "hopeless OCR".
    for p in rasters:
        rel = os.path.relpath(p, REPO)
        scanned += 1
        text = ocr_raster(p, exe)
        for kind, snippet in find_image_text_hits(text, tolerant=True):
            ocr_hits.append((rel, kind, snippet))
        for kind, snippet in find_image_text_hits(raster_metadata_text(p), tolerant=False):
            meta_hits.append((rel, kind, snippet))
    say("    image-text OCR: %d raster(s) scanned, %d skipped, %d hit(s) %s" % (
        scanned, len(skipped), len(ocr_hits),
        [(h[0], h[1], h[2][:40]) for h in ocr_hits[:5]]))
    if skipped:
        for rel, why in skipped:
            say("    image-text skip: %s (%s)" % (rel, why))
    else:
        say("    image-text skip: 0 (Crown official faces are published as SVG --eps.svg and grepped, not OCR'd; no hopeless Crown raster is tracked)")
    ok &= not ocr_hits
    say("    image-text metadata: %d raster(s) scanned, %d hit(s) %s" % (
        scanned, len(meta_hits), [(h[0], h[1], h[2][:40]) for h in meta_hits[:5]]))
    ok &= not meta_hits

    # --- SVGs (grep text; no OCR)
    svg_hits = []
    svgs = list_svgs(site)
    for p in svgs:
        rel = os.path.relpath(p, REPO)
        try:
            text = open(p, encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        for kind, snippet in find_image_text_hits(text, tolerant=False):
            svg_hits.append((rel, kind, snippet))
    say("    image-text SVG: %d file(s) grepped, %d hit(s) %s" % (
        len(svgs), len(svg_hits), [(h[0], h[1], h[2][:40]) for h in svg_hits[:5]]))
    ok &= not svg_hits

    # --- historical proof: the same matcher must flag a56e717's dirty images
    if not _commit_is_ancestor(_HIST_COMMIT):
        say("    image-text historical: FAIL commit %s is not an ancestor of HEAD (cannot prove the checker against those images)" % _HIST_COMMIT)
        ok = False
    else:
        missing = []
        shot_mark, look_name = [], []
        with tempfile.TemporaryDirectory() as td:
            for rel in _HIST_SHOTS + _HIST_LOOK:
                blob = _git_show(_HIST_COMMIT, rel)
                if not blob:
                    missing.append(rel)
                    continue
                dest = os.path.join(td, os.path.basename(rel))
                # keep unique names when basenames could clash (they don't here)
                if os.path.exists(dest):
                    dest = os.path.join(td, rel.replace("/", "__"))
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                open(dest, "wb").write(blob)
                hits = find_image_text_hits(ocr_raster(dest, exe), tolerant=True)
                kinds = {k for k, _ in hits}
                if rel in _HIST_SHOTS and "mark" in kinds:
                    shot_mark.append(rel)
                if rel in _HIST_LOOK and "name" in kinds:
                    look_name.append(rel)
        # Required: all 8 screenshots show the mark; the 8 Reviewer-listed
        # look-pack previews (plus lod strip and swatch, which also baked the
        # name) show the owner's name.
        need_shots = set(_HIST_SHOTS)
        need_look = set(_HIST_LOOK[:8])  # the eight listed by Reviewer
        missed_shots = sorted(need_shots - set(shot_mark))
        missed_look = sorted(need_look - set(look_name))
        extra_ok = [r for r in _HIST_LOOK[8:] if r in look_name]
        if missing or missed_shots or missed_look:
            say("    image-text historical: FAIL %s missing=%s missed-shots=%s missed-look=%s" % (
                _HIST_COMMIT, missing[:3], missed_shots, missed_look))
            ok = False
        else:
            say("    image-text historical: %s would have failed (%d/8 screenshots flagged for the mark, %d/8 listed look-pack previews flagged for the name; also %d extra look-pack raster(s) %s) OK" % (
                _HIST_COMMIT, len(shot_mark), len([r for r in look_name if r in need_look]),
                len(extra_ok), extra_ok or "none"))
    return ok


def main():
    site = os.path.join(REPO, sys.argv[sys.argv.index("--site") + 1]) if "--site" in sys.argv else os.path.join(REPO, "site")
    ok = True
    report = []
    def say(x=""):
        print(x); report.append(x)
    sanitise_fail = check_sanitise()
    say("    sanitise unit: %s%s" % ("OK" if not sanitise_fail else "FAIL",
                                      "" if not sanitise_fail else " %s" % sanitise_fail[:3]))
    ok &= not sanitise_fail
    # (a)
    with tempfile.TemporaryDirectory() as td:
        outs = []
        for k in ("a", "b"):
            o = os.path.join(td, k)
            subprocess.run([sys.executable, os.path.join(REPO, "wiki/build.py"), "--out", o], check=True, stdout=subprocess.DEVNULL)
            outs.append(o)
        d = subprocess.run(["diff", "-r", outs[0], outs[1]], capture_output=True, text=True)
        ma, mb = manifest(outs[0]), manifest(outs[1])
        ha, hb = hashlib.sha256(ma.encode()).hexdigest(), hashlib.sha256(mb.encode()).hexdigest()
        same = d.returncode == 0 and ma == mb
        say("(a) twice-regen: diff -r exit %d; manifest sha256 run1 %s run2 %s; files %d -> %s"
            % (d.returncode, ha, hb, ma.count("\n"), "IDENTICAL" if same else "DIFFERENT"))
        ok &= same
        if os.path.isdir(site):
            mc = manifest(site)
            hc = hashlib.sha256(mc.encode()).hexdigest()
            say("    committed %s manifest sha256 %s -> %s" % (os.path.relpath(site, REPO), hc, "IDENTICAL" if mc == ma else "DIFFERENT"))
            ok &= mc == ma
            os.makedirs(os.path.join(REPO, "qa"), exist_ok=True)
            open(os.path.join(REPO, "qa/site.sha256"), "w").write(ma)
    # (b)
    n, bad = link_check(site)
    say("(b) link check: %d internal href/src checked, %d broken" % (n, len(bad)))
    for b in bad[:20]:
        say("    BROKEN %s -> %s (%s)" % b)
    ok &= not bad
    # fonts / privacy
    fontbad = []
    for dp, dn, fn in os.walk(site):
        for f in fn:
            if f.lower().endswith((".ttf", ".otf", ".woff", ".woff2", ".eot")):
                fontbad.append(os.path.relpath(os.path.join(dp, f), site))
            elif f.endswith((".html", ".css", ".svg")) and not os.path.relpath(dp, site).startswith("code"):
                # code/ pages show this checker's own source text, so only font files are checked there
                t = open(os.path.join(dp, f), encoding="utf-8", errors="replace").read()
                if "@font-face" in t or "fonts.googleapis" in t or "fonts.gstatic" in t:
                    fontbad.append(os.path.relpath(os.path.join(dp, f), site))
    say("    fonts: %d font files / @font-face / web-font refs %s" % (len(fontbad), fontbad[:5]))
    ok &= not fontbad
    # r12: every published EPS face carries Crown copyright + OGL v3.0, in the SVG and on its page
    eps_bad, eps_n = [], 0
    for dp, dn, fn in os.walk(site):
        for f in fn:
            fp = os.path.join(dp, f)
            if f.endswith(".svg"):
                b = open(fp, "rb").read()
                if b'data-source="eps"' in b:
                    eps_n += 1
                    if b"<desc>Crown copyright" not in b or b"Open Government Licence v3.0" not in b:
                        eps_bad.append(os.path.relpath(fp, site))
            elif f.endswith(".html") and not os.path.relpath(dp, site).startswith("code"):
                t = open(fp, encoding="utf-8").read()
                if "--eps.svg" in t and not ("Crown copyright" in t and "Open Government Licence v3.0" in t):
                    eps_bad.append(os.path.relpath(fp, site))
    say("    EPS attribution: %d EPS face(s) published, %d without Crown copyright + OGL v3.0 %s" % (eps_n, len(eps_bad), eps_bad[:5]))
    ok &= not eps_bad
    # licence
    lic_ok = os.path.isfile(os.path.join(site, "LICENCE")) and \
        open(os.path.join(site, "LICENCE"), "rb").read() == open(os.path.join(REPO, "LICENCE"), "rb").read() and \
        b"Attribution-NoDerivatives 4.0 International" in open(os.path.join(REPO, "LICENCE"), "rb").read()
    say("    LICENCE: site/LICENCE present and identical to repo LICENCE (CC BY-ND 4.0 legal code): %s" % ("OK" if lic_ok else "FAIL"))
    ok &= lic_ok
    pages, missing = 0, []
    for dp, dn, fn in os.walk(site):
        for f in fn:
            if f.endswith(".html"):
                pages += 1
                t = open(os.path.join(dp, f), encoding="utf-8").read()
                foot = t[t.rfind("<footer>"):] if "<footer>" in t else ""
                if not ("2026 AI-tainment" in foot and "https://creativecommons.org/licenses/by-nd/4.0/" in foot and "CC BY-ND 4.0" in foot):
                    missing.append(os.path.relpath(os.path.join(dp, f), site))
    say("    footer: %d HTML pages, %d without the CC BY-ND 4.0 attribution footer %s" % (pages, len(missing), missing[:5]))
    ok &= not missing and pages > 0
    # no personal name (case-insensitive), in site/ and every tracked file
    pat = re.compile("p" + "hil|rob" + "inson", re.I)
    allow = {}  # word -> justification; none needed so far
    hits = []
    tracked = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True).stdout.split("\n")
    paths = [os.path.join(REPO, f) for f in tracked if f and not f.startswith("site/")]
    for dp, dn, fn in os.walk(site):
        paths += [os.path.join(dp, f) for f in fn]
    for p in sorted(set(paths)):
        if not os.path.isfile(p):
            continue
        rel = os.path.relpath(p, REPO)
        # Vendored third-party sources can contain incidental substrings
        # (e.g. a geometry parameter name); they are pin-hashed separately.
        if "/vendor/" in rel.replace("\\", "/") and not rel.endswith(("LICENSE", "manifest.json")):
            continue
        if pat.search(rel):
            hits.append((pat.sub("***", rel), "path"))
        t = open(p, "rb").read().decode("utf-8", "replace")
        for m in pat.finditer(t):
            w = re.search(r"\w*$", t[:m.start()]).group(0) + m.group(0) + re.match(r"\w*", t[m.end():]).group(0)
            if w.lower() not in allow:
                hits.append((rel, w[:1] + "*" * (len(w) - 1)))  # masked so the report never repeats it
    say("    no-name: %d files scanned (site/ + tracked), %d matches %s; allow-list %s" % (len(set(paths)), len(hits), hits[:5], sorted(allow) or "empty"))
    ok &= not hits
    mark_hits, mark_allow = scan_standalone_mark(site)
    say("    standalone-mark: %d matches %s; allow-list %s" % (
        len(mark_hits), mark_hits[:5], sorted(mark_allow) or "empty"))
    ok &= not mark_hits
    # absolute machine paths (work/scratch/home) in tracked files and site/
    ppat = re.compile(r"(?<![\w.~-])/(?:" + "work" + "space|" + "tm" + "p|" + "ho" + "me" + r")(?:/|\b)")
    phits = []
    for p in sorted(set(paths)):
        if not os.path.isfile(p):
            continue
        b = open(p, "rb").read()
        if b"\0" in b[:8192]:
            continue
        for m in ppat.finditer(b.decode("utf-8", "replace")):
            phits.append((os.path.relpath(p, REPO), m.group(0)))
    say("    abs-paths: %d files scanned (site/ + tracked), %d matches %s; allow-list empty" % (len(set(paths)), len(phits), phits[:5]))
    ok &= not phits
    # 3D viewer: vendored hashes, GLB+poster, no remote resource URLs, metadata scrub
    ok &= check_3d(site, say)
    ok &= check_animation(site, say)
    ok &= check_image_text(site, say)
    # (c)
    src = source_counts()
    gen, _ = site_counts(site)
    say("(c) counts")
    say("    %-34s %8s %8s  %s" % ("item", "source", "wiki", "match"))
    for k in sorted(src):
        m = src[k] == gen.get(k)
        ok &= m
        say("    %-34s %8d %8s  %s" % (k, src[k], gen.get(k), "OK" if m else "MISMATCH"))
    tot_s = sum(src[k] for k in ("signs", "markings", "furniture", "matrix", "artdraft", "furniture3d"))
    tot_g = sum(gen.get(k, 0) for k in ("signs", "markings", "furniture", "matrix", "artdraft", "furniture3d"))
    say("    %-34s %8d %8d  %s" % ("TOTAL item pages", tot_s, tot_g, "OK" if tot_s == tot_g else "MISMATCH"))
    ok &= tot_s == tot_g
    say("RESULT: %s" % ("PASS" if ok else "FAIL"))
    open(os.path.join(REPO, "qa/check-report.txt"), "w").write("\n".join(report) + "\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
