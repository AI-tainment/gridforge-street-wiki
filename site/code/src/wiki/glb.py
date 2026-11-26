"""Read and write GLB files, scrubbing string metadata.

The kit GLBs are already glTF 2.0. This module does not convert other
formats; it rewrites the JSON chunk so generator, copyright and names
cannot carry a former engine mark or a personal home path. The BIN
chunk is left byte-identical. Output is deterministic.
"""
from __future__ import annotations
import json, struct

GLB_MAGIC = b"glTF"
JSON_CHUNK = b"JSON"
BIN_CHUNK = b"BIN\x00"


def _pad4(data: bytes, pad: bytes) -> bytes:
    n = (4 - (len(data) % 4)) % 4
    return data + pad * n


def parse_glb(data: bytes):
    if len(data) < 20 or data[:4] != GLB_MAGIC:
        raise ValueError("not a GLB file")
    _magic, version, length = struct.unpack_from("<4sII", data, 0)
    if version != 2:
        raise ValueError("unsupported GLB version %s" % version)
    off = 12
    chunks = {}
    while off + 8 <= len(data):
        clen, ctype = struct.unpack_from("<I4s", data, off)
        off += 8
        chunks[ctype] = data[off:off + clen]
        off += clen
    if JSON_CHUNK not in chunks:
        raise ValueError("GLB has no JSON chunk")
    return json.loads(chunks[JSON_CHUNK]), chunks.get(BIN_CHUNK, b"")


def write_glb(doc: dict, bin_chunk: bytes) -> bytes:
    raw = json.dumps(doc, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    js = _pad4(raw, b" ")
    bn = _pad4(bin_chunk, b"\x00") if bin_chunk else b""
    parts = [js]
    length = 12 + 8 + len(js)
    out_chunks = [(len(js), JSON_CHUNK, js)]
    if bin_chunk is not None:
        # Always keep a BIN chunk if the document has buffers, even if empty.
        out_chunks.append((len(bn), BIN_CHUNK, bn))
        length += 8 + len(bn)
    header = struct.pack("<4sII", GLB_MAGIC, 2, length)
    body = b"".join(struct.pack("<I4s", clen, ctype) + blob for clen, ctype, blob in out_chunks)
    return header + body


def _walk(obj, fn):
    if isinstance(obj, str):
        return fn(obj)
    if isinstance(obj, list):
        return [_walk(x, fn) for x in obj]
    if isinstance(obj, dict):
        return {k: _walk(v, fn) for k, v in obj.items()}
    return obj


def scrub_glb(data: bytes, transform) -> bytes:
    """Return a GLB whose JSON strings have been passed through transform."""
    doc, binary = parse_glb(data)
    doc = _walk(doc, transform)
    return write_glb(doc, binary)
