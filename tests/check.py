#!/usr/bin/env python3
"""Acceptance checks for the wiki.

    python3 tests/check.py [--site site]

(a) builds the wiki twice into fresh temp folders; trees must be byte-identical
    (diff -r and a sha256 manifest), and identical to the committed --site;
(b) link check: every internal href/src in every HTML file resolves to a file;
(c) item counts, taken from the sources independently of wiki/loaders.py,
    must equal the generated item pages (printed as a table).
Plus: no font files / @font-face / web-font hosts, no absolute or file: links.
Exit code 0 only if every check passes.
"""
import hashlib, json, os, re, subprocess, sys, tempfile, zipfile
from html.parser import HTMLParser
from urllib.parse import urlsplit, unquote

sys.dont_write_bytecode = True
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "wiki"))
import config  # paths only
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


def main():
    site = os.path.join(REPO, sys.argv[sys.argv.index("--site") + 1]) if "--site" in sys.argv else os.path.join(REPO, "site")
    ok = True
    report = []
    def say(x=""):
        print(x); report.append(x)
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
        if pat.search(rel):
            hits.append((pat.sub("***", rel), "path"))
        t = open(p, "rb").read().decode("utf-8", "replace")
        for m in pat.finditer(t):
            w = re.search(r"\w*$", t[:m.start()]).group(0) + m.group(0) + re.match(r"\w*", t[m.end():]).group(0)
            if w.lower() not in allow:
                hits.append((rel, w[:1] + "*" * (len(w) - 1)))  # masked so the report never repeats it
    say("    no-name: %d files scanned (site/ + tracked), %d matches %s; allow-list %s" % (len(set(paths)), len(hits), hits[:5], sorted(allow) or "empty"))
    ok &= not hits
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
