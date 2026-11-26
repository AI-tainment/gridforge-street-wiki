#!/usr/bin/env python3
"""Acceptance checks for the wiki.

    python3 tests/check.py [--site site]

(a) builds the wiki twice into fresh temp folders; trees must be byte-identical
    (diff -r and a sha256 manifest), and identical to the committed --site;
(b) link check: every internal href/src in every HTML file resolves to a file;
(c) item counts, taken from the sources independently of wiki/loaders.py,
    must equal the generated item pages (printed as a table).
Plus: no font files / @font-face / web-font hosts, no absolute or file: links,
no former-engine mark in site/ or tracked files (see tests/standalone-allow.txt).
Exit code 0 only if every check passes.
"""
import hashlib, json, os, re, subprocess, sys, tempfile, zipfile
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
