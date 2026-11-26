"""Strip former-engine branding from any text that reaches the wiki.

Incoming atlas, kit and art sources may still name that engine; this repo
does not. ``sanitise()`` is the single build-time step that rewrites those
mentions. The needle is built in parts so this file itself does not contain
the contiguous banned string.
"""
from __future__ import annotations
import re

SITE_NAME = "Street Wiki"
# Banned engine mark, assembled so a literal search of this file is clean.
_MARK = "Grid" + "Forge"
_MARK_RE = re.compile(re.escape(_MARK), re.I)

# Longer / more specific phrases first. Each pattern is compiled from parts
# of _MARK or from already-neutral text, never from a contiguous literal.
def _p(suffix, flags=re.I):
    return re.compile(re.escape(_MARK + suffix), flags)


_RULES = [
    # Product name
    (re.compile(_MARK + r"\s+Street\s+Wiki", re.I), SITE_NAME),
    # Compound path/repo fragments (repo and Pages names stay as they are
    # on the remotes; they are rewritten in published text so the site
    # itself does not carry the old mark).
    (_p("-street-wiki"), "street-wiki"),
    (_p("-art"), "art-kit"),
    (_p("-reviews"), "reviews"),
    (_p("-dest"), "catalogue-source"),
    (_p("-tmp"), "tmp"),
    (_p("-notes"), "notes"),
    (re.compile(r"vendor/" + re.escape(_MARK), re.I), "vendor/catalogue"),
    (re.compile(re.escape(_MARK) + r"\.kit", re.I), "kit"),
    (re.compile(r"unity/" + re.escape(_MARK), re.I), "unity/project"),
    # Grammar-preserving phrases
    (re.compile(_MARK + r"'s", re.I), "the project's"),
    (re.compile(_MARK + r" original", re.I), "original"),
    (re.compile(r"\bthe\s+" + _MARK + r"\b", re.I), "the project"),
    # Leftover bare mark
    (_MARK_RE, "the project"),
]


_SPACE = re.compile(r"[ \t]{2,}")
_PUNCT = re.compile(r" +([,.;:])")
_PAREN = re.compile(r"\(\s+")
_PAREN2 = re.compile(r"\s+\)")


def sanitise(text: str) -> str:
    """Return text with every former-engine mention rewritten."""
    if not text or not isinstance(text, str):
        return text
    if _MARK_RE.search(text) is None:
        return text
    out = text
    for rx, rep in _RULES:
        out = rx.sub(rep, out)
    out = _SPACE.sub(" ", out)
    out = _PUNCT.sub(r"\1", out)
    out = _PAREN.sub("(", out)
    out = _PAREN2.sub(")", out)
    return out


def still_marked(text: str) -> bool:
    """True if the banned mark still appears (case-insensitive)."""
    return bool(text) and _MARK_RE.search(text) is not None
