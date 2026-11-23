"""Read every source tree (read-only) into plain item dicts.

Each item: cat, sub, id, slug, name, status, status_note, preview (source path or
None), preview_kind, fields [(label, value)], source_ref, licence, notes [str].
Nothing here writes to a source tree (no imports from the sources, so no
__pycache__ is created there).
"""
from __future__ import annotations
import ast, json, os, re, zipfile

OGL = "OGL-3.0"
OGL_ATTR = "Contains public sector information licensed under the Open Government Licence v3.0."

def slugify(s: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("_")
    return s or "item"

def _json(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)

def _read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()

def md_table_rows(text: str):
    """Rows of every markdown table as lists of stripped cells (header/rule rows dropped)."""
    out, header = [], None
    for line in text.splitlines():
        t = line.strip()
        if not t.startswith("|"):
            header = None
            continue
        cells = [c.strip() for c in t.strip("|").split("|")]
        if all(re.fullmatch(r":?-{3,}:?", c) for c in cells if c):
            continue
        if header is None:
            header = cells
            continue
        out.append(dict(zip(header, cells)))
    return out

# ---------------------------------------------------------------- atlas
def traced_sources(atlas):
    """traced.SOURCE dict parsed with ast (the module is not imported)."""
    src = _read(os.path.join(atlas, "tools/atlas/traced.py"))
    tree = ast.parse(src)
    for node in tree.body:
        tgt = getattr(node, "target", None) or (node.targets[0] if isinstance(node, ast.Assign) else None)
        if isinstance(tgt, ast.Name) and tgt.id == "SOURCE":
            return ast.literal_eval(node.value)
    return {}

def decisions_ids(atlas):
    qa = os.path.join(atlas, "qa")
    names = sorted(f for f in os.listdir(qa) if f.startswith("DECISIONS-") and f.endswith(".md"))
    text = "".join(_read(os.path.join(qa, f)) for f in names)
    return sorted(set(re.findall(r"^## ([0-9A-Z][0-9A-Za-z.]*) \(", text, re.M)))

def unverified_ids(atlas):
    """Face ids named in the 'Title' column of qa/UNVERIFIED-SOURCES.md rows whose 'Needed for' is a face."""
    ids = {}
    for r in md_table_rows(_read(os.path.join(atlas, "qa/UNVERIFIED-SOURCES.md"))):
        if "Face" not in r.get("Needed for", ""):
            continue
        for i in re.findall(r"\b(\d{3,4}(?:\.\d+)?[A-Z]?)\b", r.get("Title", "")):
            ids[i] = "UNVERIFIED-SOURCES #%s: %s" % (r.get("#", "?"), r.get("Where I looked", ""))
    return ids

def sign_source(row, traced, refs, si16):
    i = row["id"]
    keys = sorted(k for k in traced if k == i or k.startswith(i + "/"))
    if keys:
        return " | ".join(traced[k] for k in keys)
    if i in refs:
        r = refs[i]
        return "SI %s, %s" % (r.get("si", "?"), r.get("where", ""))
    d = si16.get(row.get("diagram") or i)
    if d:
        return "SI 2016/362 %s %s (caption from the SI XML; page not recorded in the atlas)" % (
            d.get("schedule", "").title(), d.get("part", "").title())
    if row.get("status") == "2002-legacy":
        return "SI 2002/3113 (2002-legacy row; page not recorded in the atlas)"
    return "not recorded"

def load_atlas(atlas, known):
    uk = os.path.join(atlas, "countries/uk")
    faces = os.path.join(atlas, "site/faces/uk")
    manifest = _json(os.path.join(faces, "manifest.json"))["faces"]
    traced = traced_sources(atlas)
    refs = _json(os.path.join(uk, "sources/diagram_refs.json"))["refs"]
    si16 = _json(os.path.join(uk, "sources/si2016_diagrams.json"))["diagrams"]
    dec = set(decisions_ids(atlas))
    unv = unverified_ids(atlas)
    # EPS-first (atlas countries/uk/face_sources.json). r12: the owner ruled EPS-derived faces may be
    # republished with attribution (Crown copyright, OGL v3.0). When the atlas has built its local EPS cache
    # (site/faces-eps/, gitignored there), the page shows the EPS face first, then the atlas's procedural face
    # (the offline fallback), then the placeholder. Each EPS SVG embeds the notice; tests/check.py checks it.
    fs_path = os.path.join(uk, "face_sources.json")
    face_src = _json(fs_path)["faces"] if os.path.exists(fs_path) else {}
    adjust = known.get("adjust", {})
    items = []
    for kind, fname in (("signs", "signs.json"), ("markings", "markings.json"), ("furniture", "furniture.json")):
        rows = _json(os.path.join(uk, fname))
        for row in sorted(rows, key=lambda r: r["id"]):
            i = row["id"]
            m = manifest.get("%s/%s" % (kind, i))
            preview = os.path.join(faces, m["path"]) if m else None
            notes = []
            eps_preview = None
            eps_example = False
            if kind == "signs":
                drawn = bool(row.get("glyph"))
                if i in dec:
                    status, note = "pending-owner", "Face held for the owner's decision (local-only qa decisions note in the atlas). Current face shown."
                elif drawn and i in adjust:
                    status, note = "adjust", adjust[i]
                elif drawn:
                    status, note = "drawn", "Drawn from the cited SI diagram (Reviewer-graded OK or awaiting grade)."
                elif i in unv:
                    status, note = "unverified", "Placeholder: no verified source diagram. " + unv[i]
                else:
                    status, note = "placeholder", "Placeholder face: not drawn yet. The neutral placeholder is shown, not the sign."
                src = sign_source(row, traced, refs, si16)
                sub = row.get("family", "Other")
                fields = [("Diagram", row.get("diagram")), ("Row status", row.get("status")),
                          ("Renumbered to", row.get("renumbered_to")),
                          ("SI caption", row.get("si_caption")), ("SI ref", row.get("si_ref")),
                          ("Family", sub), ("Chapter", row.get("chapter")), ("Mount", row.get("mount")),
                          ("Colours", ", ".join(row.get("colours") or [])),
                          ("Dimensions (m)", _dims(row.get("dimensions_m"))),
                          ("OSM tag", row.get("osm"))]
                fsrc = face_src.get(i)
                if fsrc:
                    label = {"eps": "GOV.UK EPS (Crown copyright, OGL v3.0), converted locally by the atlas",
                             "procedural": "procedural (atlas tools/atlas)",
                             "placeholder": "placeholder"}.get(fsrc["source"], fsrc["source"])
                    if fsrc.get("example"):
                        label = ("GOV.UK EPS example layout (Crown copyright, OGL v3.0) "
                                 "- to be generated per site")
                    fields.append(("Face source", label))
                    if fsrc["source"] == "eps":
                        ep = os.path.join(atlas, "site/faces-eps/uk/signs", i.replace("/", "_") + ".svg")
                        # No EPS cache (clean checkout) or GFWIKI_EPS=off: no EPS link and no Crown notice for
                        # this face; the procedural face (then the placeholder) is shown instead.
                        if os.environ.get("GFWIKI_EPS", "auto") != "off" and os.path.exists(ep):
                            eps_preview = ep
                            if fsrc.get("example"):
                                eps_example = True
                                note = "Example layout (official GOV.UK image) - to be generated per site."
                                notes.append("Example layout (official GOV.UK image) - to be generated per site.")
                                notes.append("Face: GOV.UK traffic sign image, \u00a9 Crown copyright (Department for Transport), "
                                             "used under the Open Government Licence v3.0 "
                                             "(https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/); "
                                             "converted from the EPS by the atlas. This is an example layout; a generated "
                                             "face will replace it per site. The atlas's own placeholder is shown after it "
                                             "as the offline fallback.")
                            else:
                                notes.append("Face: GOV.UK traffic sign image, \u00a9 Crown copyright (Department for Transport), "
                                             "used under the Open Government Licence v3.0 "
                                             "(https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/); "
                                             "converted from the EPS by the atlas. The atlas's own procedural face is shown "
                                             "after it as the offline fallback.")
                        else:
                            notes.append("The atlas takes this face from the GOV.UK EPS artwork, which is not built on "
                                         "this machine; the preview is the atlas's own procedural face (the offline fallback)"
                                         + (", superseded by the EPS." if fsrc.get("superseded") else "."))
                            if fsrc.get("example"):
                                eps_example = True
                                note = "Example layout (official GOV.UK image) - to be generated per site."
                                notes.append("Example layout (official GOV.UK image) - to be generated per site.")
                    elif fsrc.get("why_not_eps") and fsrc.get("eps"):
                        notes.append("Not EPS-sourced: " + "; ".join(fsrc["why_not_eps"]) + ".")
                lic = OGL
            elif kind == "markings":
                status = "placeholder" if row.get("placeholder") or row.get("renderer") == "placeholder" else "drawn"
                note = "Marking drawn from its TSRGD schedule / TSM figures." if status == "drawn" else "Placeholder."
                src = row.get("schedule") or "not recorded"
                if "TSM" in src:
                    notes.append("Cites the Traffic Signs Manual, which is Crown copyright and not OGL (see Licences).")
                sub = "Markings"
                fields = [("Diagram", row.get("diagram")), ("Row status", row.get("status")),
                          ("Renderer", row.get("renderer")), ("Pair", row.get("pair")),
                          ("Dimensions (m)", _dims(row.get("dimensions_m")))]
                lic = OGL
            else:
                ph = bool(row.get("placeholder")) or row.get("renderer") == "placeholder"
                status = "placeholder" if ph else "drawn"
                note = ("Placeholder: no figures until sourced. To do: " + row.get("todo", "")) if ph else \
                    "Drawn 2D elevation from the figures in countries/uk/furniture.json."
                src = "; ".join(sorted(set(str(v) for v in (row.get("source") or {}).values()))) or row.get("spec") or "not recorded"
                if row.get("sources_needed"):
                    notes.append("Sources needed: " + _s(row.get("sources_needed")))
                sub = row.get("section", "posts-and-mounts")
                fields = [("Spec", row.get("spec")), ("Renderer", row.get("renderer")),
                          ("Section", row.get("section")), ("Dimensions (m)", _dims(row.get("dimensions_m")))]
                lic = "Project data; figures cite their sources (see Licences)"
            items.append(dict(cat=kind, sub=sub, id=i, slug=slugify(i), name=row.get("name") or i,
                              what=row.get("what"), status=status, status_note=note,
                              preview=preview, preview_kind="svg" if preview else None, eps_preview=eps_preview,
                              eps_example=eps_example,
                              fields=[(k, v) for k, v in fields if v not in (None, "", [])],
                              source_ref=src, licence=lic, notes=notes))
    return items

def _s(v):
    return ", ".join(map(str, v)) if isinstance(v, list) else str(v)

def _dims(d):
    if not d:
        return None
    return ", ".join("%s %s" % (k, d[k]) for k in sorted(d))

# ---------------------------------------------------------------- matrix
def parse_war(path):
    text = _read(path)
    lines = [l for l in text.splitlines() if not l.startswith("#")]
    body = "\n".join(lines)
    dec = json.JSONDecoder()
    j = body.index("{")
    header, end = dec.raw_decode(body, j)
    rows = [l for l in body[end:].splitlines() if l.strip()]
    h = int(header.get("h", len(rows)))
    return header, rows[:h]

def load_matrix(root):
    items = []
    for dp, dn, fn in os.walk(root):
        dn.sort()
        for f in sorted(fn):
            if not f.endswith(".war"):
                continue
            p = os.path.join(dp, f)
            rel = os.path.relpath(p, root)
            hdr, rows = parse_war(p)
            setname = os.path.dirname(rel)
            gid = hdr.get("id") or f[:-4]
            src = hdr.get("source")
            ref = hdr.get("tsrgd_ref")
            fields = [("File", rel), ("Set", setname), ("Grid", "%s x %s" % (hdr.get("w"), hdr.get("h"))),
                      ("Profile", hdr.get("profile")), ("Char", hdr.get("char")),
                      ("TSRGD ref", ref), ("Variant", hdr.get("variant")),
                      ("Baseline / advance", "%s / %s" % (hdr.get("baseline"), hdr.get("advance"))),
                      ("Built", src), ("Snap", hdr.get("snap")), ("Verified flag", hdr.get("verified"))]
            items.append(dict(cat="matrix", sub=setname, id=gid, slug=slugify(rel[:-4]),
                              name="%s (%s)" % (gid, setname), what=hdr.get("note"),
                              status="pending-signoff",
                              status_note="Spec 019/022 matrix display glyph by Art: pending sign-off. Pixel placement unverified (TSRGD gives proportions, not a pixel map).",
                              preview=None, preview_kind="war", war=(hdr, rows),
                              fields=[(k, v) for k, v in fields if v not in (None, "", "None / None")],
                              source_ref=("SI 2016/362 diagram %s" % ref) if ref else "original (hand-drawn font / helper); no SI diagram",
                              licence=OGL if ref else "Art original (licence not yet recorded; OGL v3.0 attribution carried in the kit README)",
                              notes=[]))
    return items

# ---------------------------------------------------------------- Art drafts b10-12
def load_art_drafts(root, atlas_names):
    items = []
    man = md_table_rows(_read(os.path.join(root, "MANIFEST.md")))
    unv = md_table_rows(_read(os.path.join(root, "UNVERIFIED.md")))
    reasons = {r.get("Id"): r for r in unv if r.get("Id")}
    for r in man:
        i = r.get("Face id")
        if not i:
            continue
        if r.get("Verified") == "Y":
            f = r.get("File", "").strip("`")
            p = os.path.join(root, f)
            items.append(dict(cat="artdraft", sub="Batches 10-12", id=i, slug=slugify(i),
                              name=atlas_names.get(i, i), what=None,
                              status="art-draft", status_note="Art draft, not yet imported into the Signage Atlas. Source located by Art (MANIFEST.md, verified Y); Build has not reviewed or imported it.",
                              preview=p if os.path.exists(p) else None, preview_kind="svg",
                              fields=[("Diagram", r.get("Diagram")), ("Source SI", r.get("Source SI")),
                                      ("Art file", f)],
                              source_ref="%s diagram %s, %s" % (r.get("Source SI"), r.get("Diagram"), r.get("Page (printed / PDF)")),
                              licence=OGL, notes=[]))
        else:
            u = reasons.get(i, {})
            items.append(dict(cat="artdraft", sub="Batches 10-12", id=i, slug=slugify(i),
                              name=atlas_names.get(i, i), what=None, status="unverified",
                              status_note="Art found no locatable diagram (UNVERIFIED.md); stays a labelled placeholder. Nothing invented.",
                              preview=None, preview_kind=None,
                              fields=[("Batch", u.get("Batch"))], source_ref="none located: " + u.get("Reason", "not recorded"),
                              licence="n/a (no face)", notes=[]))
    return sorted(items, key=lambda x: x["id"])

# ---------------------------------------------------------------- 3D kit 020
def load_kit020(gfkit, kit_dir):
    z = zipfile.ZipFile(gfkit)
    man = json.loads(z.read("kit.manifest.json"))
    tri = {}
    tp = os.path.join(kit_dir, "tri_report.json")
    if os.path.exists(tp):
        tri = _json(tp)
    items = []
    for slot in sorted(man["slots"]):
        s = man["slots"][slot]
        short = slot.split("bus_stop/", 1)[1]
        items.append(dict(cat="furniture3d", sub="Spec 020 bus stop kit (gf.module.bus_stop_ref v%s)" % man.get("pack_version"),
                          id=short, slug=slugify(short), name="Bus stop %s" % short.replace("/", " / ").replace("_", " "),
                          what=man.get("edition"), status="placeholder-3d",
                          status_note="Architect reference placeholder geometry (not final art). Bus-stop furniture category awaits the owner's sign-off.",
                          preview=None, preview_kind="glb", glb=(gfkit, s["lods"]["lod0"]),
                          lods=s["lods"], slot=slot,
                          fields=[("Slot", slot), ("Pack", "%s v%s" % (man["pack_id"], man["pack_version"])),
                                  ("LODs", ", ".join("%s: %s" % (k, os.path.basename(v)) for k, v in sorted(s["lods"].items())))],
                          source_ref="gf.module.bus_stop_ref.gfkit (Spec 020 r3-final); flag face: TSRGD 2016 diagram 970" if "flag" in short
                          else "gf.module.bus_stop_ref.gfkit (Spec 020 r3-final)",
                          licence="%s (%s)" % (man["licence"]["spdx"], man["licence"].get("credit", "")),
                          notes=[]))
    return man, items, tri

def load_look(look_dir):
    mats = _json(os.path.join(look_dir, "materials.json"))
    imgs = []
    for sub in ("previews", "swatches"):
        d = os.path.join(look_dir, sub)
        if os.path.isdir(d):
            imgs += [os.path.join(d, f) for f in sorted(os.listdir(d)) if f.endswith(".png")]
    item = dict(cat="furniture3d", sub="Art look pack (Spec 020)", id="look-pack", slug="look-pack",
                name="Bus stop look pack (materials and textures)", what="Art's materials, procedural textures and previews on Architect's modules.",
                status="pending-signoff", status_note="NOT FOR SHIPPING: awaiting the owner's sign-off (LOOK.md).",
                preview=None, preview_kind="images", images=imgs, materials=mats,
                fields=[("Spec", mats.get("spec")), ("Bind", mats.get("bind_by")),
                        ("Colourways", ", ".join(mats.get("frame_colourways", [])))],
                source_ref="Art look pack, kit/street_furniture/bus_stop/look/ (LOOK.md, PROVENANCE.md). Previews are Art's existing images (copied, not re-rendered).",
                licence="Original procedural (intended CC0 once signed off, PROVENANCE.md); flag face 970: original construction + OGL v3.0",
                notes=[])
    return mats, item
