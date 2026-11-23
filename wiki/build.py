#!/usr/bin/env python3
"""GridForge Street Wiki generator.

    python3 wiki/build.py --out site

Reads the source trees (read-only; paths from flags, GFWIKI_* env vars or
wiki/local_config.json, see wiki/config.py) and writes a static,
relative-link-only site (GitHub Pages ready: index.html at the root, .nojekyll).
Deterministic: sorted iteration, no timestamps, fixed render settings.
"""
from __future__ import annotations
import argparse, html, json, os, posixpath, re, shutil, sys, zipfile

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import config, loaders, render3d, matrix_svg  # noqa: E402

E_ = html.escape
CATS = [
    ("signs", "Signs", "Signage Atlas sign faces (TSRGD 2016; SI 2002 only where 2016 has no diagram), grouped by family."),
    ("markings", "Road markings", "Signage Atlas road markings."),
    ("furniture", "Street furniture (2D)", "Signage Atlas posts, mounts, beacons, poles, gantries and VMS rows (2D elevations)."),
    ("matrix", "Matrix glyphs and pictograms", "Art's LED matrix glyph grids (Spec 019/022 runtime pixel display). Pending sign-off."),
    ("artdraft", "Art drafts (batches 10-12)", "Art's traced faces for plan batches 10-12. Art draft, not yet imported into the Signage Atlas."),
    ("furniture3d", "3D street furniture", "Spec 020 bus stop kit modules and assemblies (rendered headlessly from the GLBs), plus Art's look pack."),
]
CAT_TITLE = {c: t for c, t, _ in CATS}
STATUS = {
    "drawn": ("Drawn", "ok"),
    "adjust": ("ADJUST (Reviewer)", "warn"),
    "placeholder": ("Placeholder", "ph"),
    "unverified": ("Unverified source", "bad"),
    "pending-owner": ("Pending owner decision", "warn"),
    "pending-signoff": ("Pending sign-off", "warn"),
    "art-draft": ("Art draft, not yet imported", "info"),
    "placeholder-3d": ("Reference placeholder (Spec 020, awaiting sign-off)", "info"),
}
CODE_DIRS = ("wiki", "tests")
CODE_TOP = ("README.md", "requirements.txt", "LICENCE")
ATTRIBUTION = ("GridForge Street Wiki \u00a9 2026 AI-tainment (https://github.com/AI-tainment), "
               "licensed under CC BY-ND 4.0 (https://creativecommons.org/licenses/by-nd/4.0/).")
ATTR_HTML = ('GridForge Street Wiki &copy; 2026 AI-tainment (<a href="https://github.com/AI-tainment">https://github.com/AI-tainment</a>), '
             'licensed under <a rel="license" href="https://creativecommons.org/licenses/by-nd/4.0/">CC BY-ND 4.0</a> (https://creativecommons.org/licenses/by-nd/4.0/).')
SCOPE_NOTE = ("The CC BY-ND 4.0 licence covers the owner's own compilation, code and original content only. It does not relicense "
              "third-party parts, which stay under their own terms: OGL v3.0 for TSRGD 2016 / SI 2002 material, ODbL for OpenStreetMap "
              "tag data, and the CC0 or other licences recorded for kit assets.")


# Build-time redaction of the owner's personal name from any text quoted from the
# sources (the source trees are never edited). Character classes keep the name
# itself out of this file.
_N1, _N2 = "[Pp][Hh][Ii][Ll]", "[Rr][Oo][Bb][Ii][Nn][Ss][Oo][Nn]"
REDACT = [
    (re.compile(r"(?:file://)?/" + "home/" + _N1 + r"\S*"), "[local path]"),
    (re.compile(r"(?:qa/)?DECISIONS-FOR-" + _N1 + r"(?:\.md)?"), "the local-only qa decisions note"),
    (re.compile(r"\b" + _N1 + r"\s+" + _N2 + r"\b"), "the owner"),
    (re.compile(r"\b" + _N1 + r"(?:'|&#x27;|\u2019)s\b"), "the owner's"),
    (re.compile(r"\b(?:" + _N1 + "|" + _N2 + r")\b"), "the owner"),
]
TEXT_EXT = (".html", ".svg", ".css", ".js", ".json", ".md", ".txt", ".py", ".war", ".sh")


# Absolute machine paths never reach the site: each source root becomes a <name>
# placeholder, and any other absolute work/scratch/home path becomes "[local path]".
ABS_PATH = re.compile(r"(?<![\w.~-])/(?:" + "work" + "space|" + "tm" + "p|" + "ho" + "me" + r")(?:/[^\s\"'<>()`,;]*)?")
SOURCE_ROOTS = []  # [(absolute root, placeholder)], longest first; set in main()


EPS_CAPTION = ("Face (SVG): GOV.UK traffic sign image, \u00a9 Crown copyright (Department for Transport), "
               "Open Government Licence v3.0; converted from the EPS")

def redact(text):
    for root, ph in SOURCE_ROOTS:
        text = text.replace(root, ph)
    for rx, rep in REDACT:
        text = rx.sub(rep, text)
    return ABS_PATH.sub("[local path]", text)


def badge(st):
    label, cls = STATUS[st]
    return '<span class="badge %s">%s</span>' % (cls, E_(label))


class Site:
    def __init__(self, out):
        self.out = out
        self.files = {}

    def write(self, rel, data):
        if isinstance(data, bytes) and rel.endswith(TEXT_EXT):
            try:
                data = data.decode("utf-8")
            except UnicodeDecodeError:
                pass
        if isinstance(data, str):
            data = redact(data).encode("utf-8")
        assert rel not in self.files, rel
        self.files[rel] = data

    def link(self, frm, to):
        return posixpath.relpath(to, posixpath.dirname(frm) or ".")

    def page(self, rel, title, body, crumbs=()):
        L = lambda p: self.link(rel, p)
        nav = "".join('<a href="%s">%s</a>' % (L("cat/%s.html" % c), E_(t)) for c, t, _ in CATS)
        cr = " / ".join(['<a href="%s">Home</a>' % L("index.html")] +
                        ['<a href="%s">%s</a>' % (L(p), E_(t)) for p, t in crumbs])
        doc = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{E_(title)} | GridForge Street Wiki</title><link rel="stylesheet" href="{L('assets/wiki.css')}"/></head>
<body><header><a class="brand" href="{L('index.html')}">GridForge Street Wiki</a>
<nav>{nav}<a href="{L('az.html')}">A-Z / search</a><a href="{L('licences.html')}">Licences</a><a href="{L('code/index.html')}">Code</a></nav></header>
<main><div class="crumbs">{cr}</div>
{body}
</main><footer><p class="attr">{ATTR_HTML} Full text: <a href="{L('LICENCE')}">LICENCE</a>. Third-party parts keep their own licences (<a href="{L('licences.html')}">Licences</a>).</p>Generated by <a href="{L('code/index.html')}">wiki/build.py</a> from local sources. Contains public sector information licensed under the Open Government Licence v3.0. See <a href="{L('licences.html')}">Licences</a>.</footer>
</body></html>
"""
        self.write(rel, doc)

    def flush(self):
        if os.path.exists(self.out):
            shutil.rmtree(self.out)
        for rel in sorted(self.files):
            p = os.path.join(self.out, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "wb") as f:
                f.write(self.files[rel])


def unique_slugs(items):
    seen = {}
    for it in sorted(items, key=lambda x: (x["cat"], x["slug"], x["id"], x.get("sub", ""))):
        k = (it["cat"], it["slug"])
        if k in seen:
            seen[k] += 1
            it["slug"] = "%s-%d" % (it["slug"], seen[k])
        else:
            seen[k] = 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=os.path.join(REPO, "site"))
    for k in config.SOURCES:
        ap.add_argument("--" + k.replace("_", "-"), dest=k, default=None,
                        help="%s (env %s)" % (config.SOURCES[k][1], config.env_name(k)))
    ap.add_argument("--known-status", default=os.path.join(HERE, "known_status.json"))
    a = ap.parse_args(argv)
    paths = config.require(config.resolve({k: getattr(a, k) for k in config.SOURCES}))
    for k, v in paths.items():
        setattr(a, k, v)
    SOURCE_ROOTS[:] = sorted(((v, "<%s>" % k) for k, v in paths.items()), key=lambda t: (-len(t[0]), t[1]))

    known = json.load(open(a.known_status, encoding="utf-8"))
    items = loaders.load_atlas(a.atlas, known)
    names = {i["id"]: i["name"] for i in items if i["cat"] == "signs"}
    items += loaders.load_matrix(a.matrix)
    items += loaders.load_art_drafts(a.art_placeholders, names)
    kitman, kit_items, _ = loaders.load_kit020(a.kit020, a.kit020_dir)
    items += kit_items
    mats, look_item = loaders.load_look(a.look)
    items.append(look_item)
    unique_slugs(items)
    items.sort(key=lambda x: (x["cat"], x["sub"], x["id"], x["slug"]))
    look_pal = {k: v["pbr"]["baseColorFactor"] for k, v in sorted(mats.get("materials", {}).items())
                if isinstance(v, dict) and "pbr" in v and "baseColorFactor" in v["pbr"]}

    s = Site(a.out)
    s.write(".nojekyll", b"")
    s.write("LICENCE", open(os.path.join(REPO, "LICENCE"), "rb").read())
    for f in ("wiki.css", "search.js"):
        s.write("assets/" + f, open(os.path.join(HERE, "static", f), "rb").read())

    zf = zipfile.ZipFile(a.kit020)
    for it in items:
        base = "media/%s/%s" % (it["cat"], it["slug"])
        it["media"] = []
        k = it["preview_kind"]
        if it.get("eps_preview"):
            # r12: EPS face first, with its attribution (the SVG embeds the same notice in <desc>)
            s.write(base + "--eps.svg", open(it["eps_preview"], "rb").read())
            it["media"].append((base + "--eps.svg", EPS_CAPTION))
        if k == "svg" and it["preview"]:
            s.write(base + ".svg", open(it["preview"], "rb").read())
            it["media"].append((base + ".svg", "Procedural face (SVG), the offline fallback" if it.get("eps_preview") else "Face (SVG)"))
        elif k == "war":
            s.write(base + ".svg", matrix_svg.war_to_svg(it["war"][1]))
            it["media"].append((base + ".svg", "Matrix grid (lit pixels)"))
        elif k == "glb":
            glb = zf.read(it["glb"][1])
            kw = dict(az=config.CAM_AZIMUTH, el=config.CAM_ELEVATION,
                      size=(config.PREVIEW_W, config.PREVIEW_H), ss=config.SUPERSAMPLE)
            s.write(base + ".png", render3d.render(glb, **kw))
            it["media"].append((base + ".png", "LOD0, Architect placeholder materials (rendered headlessly from the GLB)"))
            s.write(base + "--look.png", render3d.render(glb, palette=look_pal, **kw))
            it["media"].append((base + "--look.png", "LOD0 in Art's look-pack base colours (NOT FOR SHIPPING, pending sign-off)"))
        elif k == "images":
            for p in it["images"]:
                rel = "%s/%s/%s" % (base, os.path.basename(os.path.dirname(p)), os.path.basename(p))
                s.write(rel, open(p, "rb").read())
                it["media"].append((rel, "Art's existing image: %s/%s (copied, not re-rendered)" % (os.path.basename(os.path.dirname(p)), os.path.basename(p))))
        it["url"] = "items/%s/%s.html" % (it["cat"], it["slug"])

    # ---- item pages
    bycat = {}
    for it in items:
        bycat.setdefault(it["cat"], []).append(it)
    for it in items:
        rel = it["url"]
        L = lambda p: s.link(rel, p)
        subp = "cat/%s--%s.html" % (it["cat"], loaders.slugify(it["sub"])) if it["cat"] == "signs" else None
        media = "".join('<figure><img src="%s" alt="%s"/><figcaption>%s</figcaption></figure>'
                        % (L(p), E_(it["id"]), E_(c)) for p, c in it["media"]) or \
            '<div class="noface">No face: %s</div>' % E_(STATUS[it["status"]][0])
        if it["status"] in ("placeholder", "unverified") and it["media"] and not it.get("eps_preview"):
            media = '<div class="phwarn">PLACEHOLDER: the image is the neutral placeholder, not the sign.</div>' + media
        rows = [("Id", it["id"]), ("Name", it["name"]), ("Category", CAT_TITLE[it["cat"]]), ("Group", it["sub"])]
        rows += it["fields"]
        rows += [("Diagram ref / source page", it["source_ref"]), ("Licence", it["licence"])]
        tbl = "".join("<tr><th>%s</th><td>%s</td></tr>" % (E_(str(k)), E_(str(v))) for k, v in rows)
        extra = ""
        if it.get("materials"):
            mrows = "".join("<tr><td><code>%s</code></td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
                E_(k), E_(str(v.get("display_name", ""))), E_(json.dumps(v.get("pbr", {}).get("baseColorFactor"))), E_(str(v.get("verified", ""))))
                for k, v in sorted(it["materials"].get("materials", {}).items()) if isinstance(v, dict))
            extra = "<h2>Materials (materials.json)</h2><table class='grid'><tr><th>Slot</th><th>Name</th><th>Base colour</th><th>Verified</th></tr>%s</table>" % mrows
        notes = "".join("<li>%s</li>" % E_(n) for n in it["notes"])
        what = "<p>%s</p>" % E_(it["what"]) if it.get("what") else ""
        body = f"""<h1>{E_(it['id'])}: {E_(it['name'])}</h1>
<p>{badge(it['status'])} <span class="note">{E_(it['status_note'])}</span></p>{what}
<div class="media">{media}</div>
<table class="kv">{tbl}</table>{('<ul class="notes">%s</ul>' % notes) if notes else ''}{extra}"""
        crumbs = [("cat/%s.html" % it["cat"], CAT_TITLE[it["cat"]])]
        if subp:
            crumbs.append((subp, it["sub"]))
        s.page(rel, "%s %s" % (it["id"], it["name"]), body, crumbs)

    def item_grid(frm, its):
        cells = []
        for it in its:
            img = it["media"][0][0] if it["media"] else None
            th = '<img loading="lazy" src="%s" alt=""/>' % s.link(frm, img) if img else '<div class="noimg">no face</div>'
            cells.append('<a class="card st-%s" href="%s">%s<span class="cid">%s</span><span class="cn">%s</span>%s</a>'
                         % (it["status"], s.link(frm, it["url"]), th, E_(it["id"]), E_(it["name"]), badge(it["status"])))
        note = ('<p class="attrib">Faces marked from GOV.UK: traffic sign images \u00a9 Crown copyright (Department for '
                'Transport), Open Government Licence v3.0; converted from the EPS.</p>'
                if any(it.get("eps_preview") for it in its) else "")
        return '<div class="cards">%s</div>%s' % ("".join(cells), note)

    def status_counts(its):
        c = {}
        for it in its:
            c[it["status"]] = c.get(it["status"], 0) + 1
        return ", ".join("%s %d" % (STATUS[k][0], c[k]) for k in sorted(c))

    # ---- category pages
    for cat, title, desc in CATS:
        rel = "cat/%s.html" % cat
        its = bycat.get(cat, [])
        subs = {}
        for it in its:
            subs.setdefault(it["sub"], []).append(it)
        if cat == "signs":
            lst = "".join('<li><a href="%s">%s</a> (%d: %s)</li>' % (
                s.link(rel, "cat/signs--%s.html" % loaders.slugify(k)), E_(k), len(v), E_(status_counts(v))) for k, v in sorted(subs.items()))
            body = "<h1>%s</h1><p>%s</p><p>%d items: %s</p><h2>Families</h2><ul>%s</ul>" % (E_(title), E_(desc), len(its), E_(status_counts(its)), lst)
            s.page(rel, title, body)
            for k, v in sorted(subs.items()):
                srel = "cat/signs--%s.html" % loaders.slugify(k)
                s.page(srel, "Signs: " + k, "<h1>Signs: %s</h1><p>%d items: %s</p>%s" % (E_(k), len(v), E_(status_counts(v)), item_grid(srel, v)),
                       [(rel, title)])
        else:
            parts = "".join("<h2>%s</h2><p>%d items: %s</p>%s" % (E_(k), len(v), E_(status_counts(v)), item_grid(rel, v)) for k, v in sorted(subs.items()))
            body = "<h1>%s</h1><p>%s</p><p>%d items: %s</p>%s" % (E_(title), E_(desc), len(its), E_(status_counts(its)), parts)
            s.page(rel, title, body)

    # ---- home
    rows = "".join('<tr><td><a href="cat/%s.html">%s</a></td><td>%d</td><td>%s</td></tr>' % (c, E_(t), len(bycat.get(c, [])), E_(status_counts(bycat.get(c, []))))
                   for c, t, _ in CATS)
    legend = "".join("<li>%s</li>" % badge(k) for k in STATUS)
    home = f"""<h1>GridForge Street Wiki</h1>
<p>Every UK sign face, road marking, matrix glyph and piece of street furniture in the GridForge sources, one page each, regenerated by one command from the source trees. Placeholders and unverified items are labelled as such and never shown as drawn.</p>
<form class="search" action="az.html" method="get"><input name="q" placeholder="Search id or name (e.g. 670, bus stop, 6031)"/><button>Search</button></form>
<table class="grid"><tr><th>Category</th><th>Items</th><th>Status</th></tr>{rows}<tr><th>Total</th><th>{len(items)}</th><th></th></tr></table>
<h2>Status labels</h2><ul class="legend">{legend}</ul>
<h2>Not included</h2><ul>
<li>Third-party asset kits elsewhere in the gridforge-art tree (Kenney, KayKit, Quaternius, cartoon-city): not street-furniture sources for this wiki and under their own licences.</li>
<li>Spec 020 <code>_old/</code> (r1 files kept for diffing) and LOD1/LOD2 renders (LOD file names are listed on each 3D page).</li>
<li>The SI PDFs in the atlas <code>refs/</code>, and the atlas' own interactive app (it loads web fonts); only its generated face SVGs are used.</li>
<li>No Transport typeface, no web fonts, no location or personal data.</li></ul>"""
    s.page("index.html", "Home", home)

    # ---- A-Z / search
    idx = sorted(((it["id"], it["name"], CAT_TITLE[it["cat"]], STATUS[it["status"]][0], it["url"]) for it in items), key=lambda r: (r[0].lower(), r[2], r[4]))
    groups = {}
    for r in idx:
        ch = r[0][:1].upper()
        groups.setdefault(ch if ch.isalnum() else "#", []).append(r)
    jump = " ".join('<a href="#g-%s">%s</a>' % (E_(g), E_(g)) for g in sorted(groups))
    secs = "".join('<h2 id="g-%s">%s</h2><ul class="az">%s</ul>' % (E_(g), E_(g), "".join(
        '<li data-k="%s"><a href="%s">%s</a> %s <span class="muted">(%s; %s)</span></li>' % (
            E_((r[0] + " " + r[1] + " " + r[2]).lower()), r[4], E_(r[0]), E_(r[1]), E_(r[2]), E_(r[3])) for r in rs)) for g, rs in sorted(groups.items()))
    s.page("az.html", "A-Z and search", '<h1>A-Z index and search</h1><input id="q" class="q" placeholder="Filter by id, name or category"/><p class="jump">%s</p>%s<script src="assets/search.js"></script>' % (jump, secs))

    # ---- licences
    lic_atlas = open(os.path.join(a.atlas, "LICENCE.md"), encoding="utf-8").read()
    kit_lic = zf.read("LICENSE").decode("utf-8")
    licp = f"""<h1>Licences and attribution</h1>
<div class="licbox"><p><strong>{ATTR_HTML}</strong></p><p>Full legal code: <a href="LICENCE">LICENCE</a> (verbatim CC BY-ND 4.0 legal code). You may use and share the wiki unmodified, with credit; no derivatives.</p>
<p><strong>Scope:</strong> {E_(SCOPE_NOTE)}</p></div>
<h1>Third-party notices (each applies to its own parts)</h1>
<h2>TSRGD 2016 / SI 2002 material: OGL v3.0</h2>
<p>Contains public sector information licensed under the Open Government Licence v3.0 (<a href="https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/">OGL v3.0</a>). Sign, marking and matrix faces are redrawn identification silhouettes derived from The Traffic Signs Regulations and General Directions 2016 (SI 2016/362) and, only where 2016 has no diagram, SI 2002/3113 (legislation.gov.uk). Page convention: "printed pN" is the page number printed on the SI page; tsrgd2016.pdf PDF p = printed + 1; refs/si2016.pdf and refs/si2002.pdf PDF p = printed.</p>
<h2>Traffic Signs Manual: not OGL</h2><p>Marking rows that cite TSM figures quote them as citations only; TSM is Crown copyright under a non-commercial notice (see the atlas LICENCE below).</p>
<h2>OpenStreetMap: ODbL</h2><p>The atlas records "OpenStreetMap contributors, ODbL" for OSM-derived material. This wiki shows only OSM tag values (e.g. <code>traffic_sign=GB:670</code>) as cross-references; it contains no OSM geodata. Where OSM data is used: &copy; OpenStreetMap contributors, ODbL 1.0.</p>
<h2>Spec 020 bus stop kit: {E_(kitman['licence']['spdx'])}</h2><pre>{E_(kit_lic)}</pre>
<h2>Art look pack</h2><p>Original procedural textures (PROVENANCE.md); intended CC0 once signed off. NOT FOR SHIPPING until then. Flag face 970: original construction from SI proportions plus OGL v3.0.</p>
<h2>Art matrix glyphs</h2><p>OGL v3.0 attribution as recorded in the kit README (traced from SI 2016/362 Sch 15). Pending sign-off; pixel placement unverified.</p>
<h2>Typeface</h2><p>No Transport typeface or any font file is embedded. Legends are Schedule 17 stand-in strokes.</p>
<h2>Wiki compilation, generator code and original content</h2><p>CC BY-ND 4.0, as above (owner's choice, 19 Nov 2026). This does not change the licences of the third-party parts listed on this page.</p>
<h2>Signage Atlas LICENCE.md (verbatim)</h2><pre>{E_(lic_atlas)}</pre>"""
    s.page("licences.html", "Licences", licp)

    # ---- code section
    code_files = []
    for d in CODE_DIRS:
        for dp, dn, fn in os.walk(os.path.join(REPO, d)):
            dn[:] = sorted(x for x in dn if x != "__pycache__")
            for f in sorted(fn):
                if not f.endswith((".pyc",)) and f != "local_config.json":
                    code_files.append(os.path.relpath(os.path.join(dp, f), REPO))
    code_files += [f for f in CODE_TOP if os.path.exists(os.path.join(REPO, f))]
    code_files.sort()
    lis = []
    for f in code_files:
        data = open(os.path.join(REPO, f), "rb").read()
        s.write("code/src/" + f, data)
        prel = "code/view/%s.html" % f
        s.page(prel, f, '<h1><code>%s</code></h1><p><a href="%s">raw file</a></p><pre class="src">%s</pre>' % (
            E_(f), s.link(prel, "code/src/" + f), E_(data.decode("utf-8", "replace"))),
            [("code/index.html", "Code")])
        lis.append('<li><a href="view/%s.html">%s</a> (%d bytes)</li>' % (f, E_(f), len(data)))
    s.page("code/index.html", "Code", """<h1>Generator code</h1>
<p>The whole wiki is regenerated from the sources by one command:</p><pre>python3 wiki/build.py --out site</pre>
<p>Source paths come from flags (<code>--atlas</code>, <code>--matrix</code>, <code>--art-placeholders</code>, <code>--kit020</code>, <code>--kit020-dir</code>, <code>--look</code>), <code>GFWIKI_*</code> environment variables or a gitignored <code>wiki/local_config.json</code> (see <code>wiki/local_config.json.example</code>). Checks: <code>python3 tests/check.py</code> (twice-regen byte identity, link check, item counts).</p>
<ul>%s</ul>""" % "".join(lis))

    s.flush()
    print("wrote %d files, %d item pages to %s" % (len(s.files), len(items), a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
