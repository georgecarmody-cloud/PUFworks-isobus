#!/usr/bin/env python3
"""Probe CAN payloads for standard protobuf wire encoding (protobuf hunt helper).

Does NOT need a .proto file — walks wire tags and optionally runs
`protoc --decode_raw` when available.

Usage:
  python scripts/probe_protobuf.py recordings/20260615_095343_616r_spray_live --sa 0xE1 --pgn 0xEF00
  python scripts/probe_protobuf.py recordings/<session> --sa 0xD4 --pgn 0xCB00 --limit 30
  python scripts/probe_protobuf.py recordings/<session> --sa 0xE1 --pgn 0xEF00 --prefix F70400
"""
from __future__ import annotations

import argparse
import csv
import math
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path


def decode_varint(data: bytes, off: int) -> tuple[int, int]:
    result = 0
    shift = 0
    pos = off
    while pos < len(data) and pos < off + 10:
        b = data[pos]
        result |= (b & 0x7F) << shift
        pos += 1
        if not (b & 0x80):
            return result, pos
        shift += 7
    raise ValueError("bad varint")


def shannon_entropy(data: bytes) -> float:
    if not data:
        return 0.0
    counts = Counter(data)
    n = len(data)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def walk_protobuf_tags(data: bytes) -> tuple[list[tuple[int, int, int]], int, str]:
    """Return (tags, bytes_consumed, status)."""
    tags: list[tuple[int, int, int]] = []
    off = 0
    try:
        while off < len(data):
            start = off
            key, off = decode_varint(data, off)
            wire = key & 7
            field = key >> 3
            if field == 0 or field > 2**29 - 1:
                return tags, start, "bad_field"
            if wire not in (0, 1, 2, 5):
                return tags, start, f"bad_wire_{wire}"
            tags.append((start, field, wire))
            if wire == 0:
                _, off = decode_varint(data, off)
            elif wire == 1:
                off += 8
            elif wire == 2:
                length, off = decode_varint(data, off)
                if length < 0 or off + length > len(data):
                    return tags, start, "bad_len"
                off += length
            elif wire == 5:
                off += 4
            if off == start:
                return tags, start, "stall"
        status = "full" if off == len(data) else "partial"
        return tags, off, status
    except ValueError:
        return tags, off, "varint_err"


def protoc_decode_raw(data: bytes) -> str | None:
    protoc = shutil.which("protoc")
    if not protoc:
        return None
    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
        f.write(data)
        path = f.name
    try:
        r = subprocess.run(
            [protoc, "--decode_raw"],
            input=data,
            capture_output=True,
            timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.decode("utf-8", errors="replace").strip()
        return None
    except (subprocess.SubprocessError, OSError):
        return None
    finally:
        Path(path).unlink(missing_ok=True)


def score_payload(data: bytes) -> dict:
    ent = shannon_entropy(data)
    tags, consumed, status = walk_protobuf_tags(data)
    tag_count = len(tags)
    full_parse = status == "full" and tag_count >= 1
    # Heuristic score 0-100
    score = 0.0
    if tag_count >= 2 and status in ("full", "partial"):
        score += 30
    if status == "full":
        score += 40
    if tag_count >= 4:
        score += 15
    if ent < 6.5:  # structured, not random
        score += 15
    if all(t[2] in (0, 2, 5) for t in tags):  # common embedded subset
        score += min(10, tag_count * 2)
    return {
        "len": len(data),
        "entropy": round(ent, 3),
        "tags": tag_count,
        "consumed": consumed,
        "status": status,
        "score": round(min(score, 100), 1),
        "full_parse": full_parse,
        "tag_fields": [t[1] for t in tags[:8]],
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("session", type=Path)
    ap.add_argument("--sa", default="0xE1", help="Source address hex")
    ap.add_argument("--pgn", default="0xEF00", help="PGN hex")
    ap.add_argument("--prefix", default="", help="Filter payloads starting with hex prefix")
    ap.add_argument("--offset", type=int, default=0, help="Skip first N payload bytes before probe")
    ap.add_argument("--limit", type=int, default=25, help="Max unique payloads to print")
    ap.add_argument("--min-score", type=float, default=0, help="Only show score >= this")
    ap.add_argument("--protoc", action="store_true", help="Run protoc --decode_raw on top hit")
    args = ap.parse_args()

    path = args.session / "frames.csv"
    if not path.exists():
        print(f"Missing {path}", file=sys.stderr)
        return 1

    rows = list(csv.DictReader(open(path, newline="", encoding="utf-8")))
    counts: Counter[str] = Counter()
    for r in rows:
        if r["sa_hex"] != args.sa or r["pgn_hex"] != args.pgn:
            continue
        hx = r["data_hex"].upper()
        if args.prefix and not hx.startswith(args.prefix.upper()):
            continue
        counts[hx] += 1

    if not counts:
        print(f"No payloads for sa={args.sa} pgn={args.pgn} prefix={args.prefix!r}")
        return 1

    print(f"Session: {args.session.name}  sa={args.sa} pgn={args.pgn}  unique={len(counts)}  frames={sum(counts.values())}")
    if args.prefix:
        print(f"Prefix filter: {args.prefix.upper()}")
    if args.offset:
        print(f"Byte offset before probe: {args.offset}")
    print()

    ranked: list[tuple[float, str, int, dict]] = []
    for hx, n in counts.items():
        raw = bytes.fromhex(hx)[args.offset:]
        if not raw:
            continue
        meta = score_payload(raw)
        ranked.append((meta["score"], hx, n, meta))

    ranked.sort(key=lambda x: (-x[0], -x[3]["tags"], -x[2]))
    shown = 0
    top_hex = None
    for score, hx, n, meta in ranked:
        if score < args.min_score:
            continue
        if top_hex is None:
            top_hex = hx
        print(
            f"score={meta['score']:5.1f}  frames={n:6d}  len={meta['len']}  "
            f"H={meta['entropy']}  tags={meta['tags']}  {meta['status']:8s}  "
            f"fields={meta['tag_fields']}  {hx[:32]}{'...' if len(hx)>32 else ''}"
        )
        if meta["score"] >= 70 and n < 10:
            print("         ^ low frame count - likely false positive; correlate before trusting")
        shown += 1
        if shown >= args.limit:
            break

    if shown == 0:
        print("No payloads matched filters / min-score.")
        return 0

    print()
    print("Interpretation:")
    print("  score >= 70 + status=full  -> strong protobuf candidate")
    print("  score 40-69                -> maybe nested message or nanopb subset")
    print("  score < 40                 -> likely JD fixed element / bitmap / not protobuf")

    if args.protoc and top_hex:
        raw = bytes.fromhex(top_hex)[args.offset:]
        out = protoc_decode_raw(raw)
        if out:
            print("\nprotoc --decode_raw (top payload):")
            print(out)
        else:
            print("\n(protoc not on PATH or decode_raw failed)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
