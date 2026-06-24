#!/usr/bin/env python3
"""Decode SRC 4F0B0602 section bitmap against section_map.json."""
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = ROOT / "library" / "section_map.json"


def load_map():
    return json.loads(MAP_PATH.read_text(encoding="utf-8"))


def bitmap_timeline(sess: Path):
    frames = list(csv.DictReader(open(sess / "frames.csv", newline="", encoding="utf-8")))
    t0 = int(frames[0]["timestamp_ms"]) / 1000.0
    prev = None
    out = []
    for r in sorted(frames, key=lambda x: int(x["timestamp_ms"])):
        if r["sa_hex"] != "0xE1" or r["pgn_hex"] != "0xEF00":
            continue
        hx = r["data_hex"]
        if not hx.startswith("4F0B0602") or hx == prev:
            continue
        prev = hx
        t = int(r["timestamp_ms"]) / 1000.0 - t0
        out.append((t, hx))
    return out


def diff_bytes(base: bytes, cur: bytes) -> list:
    changes = []
    for i in range(min(len(base), len(cur))):
        if base[i] != cur[i]:
            changes.append((i, base[i], cur[i]))
    return changes


KNOWN_COMPOSITE = {
    "4F0B06025555FD3F": ["R5", "R4"],
    "4F0B06025555FF3F": ["R5", "R4", "R3"],
    "4F0B06025555E53F": ["R5_IBS"],
}


def match_sections(map_data: dict, bitmap_hex: str) -> list:
    if bitmap_hex in KNOWN_COMPOSITE:
        return KNOWN_COMPOSITE[bitmap_hex]
    base = bytes.fromhex(map_data["baseline_all_on"]["bitmap"])
    cur = bytes.fromhex(bitmap_hex)
    if cur == base:
        return ["ALL_ON"]
    hits = []
    changes = diff_bytes(base, cur)
    for entry in map_data["sections"]:
        toggle = bytes.fromhex(entry["bitmap_toggle"])
        if cur == toggle:
            hits.append(entry["name"])
            continue
        tchg = diff_bytes(base, toggle)
        if changes == tchg:
            hits.append(entry["name"])
    return hits or [f"UNKNOWN ({' '.join(f'b{i}:{a:02X}->{b:02X}' for i,a,b in changes)})"]


def main():
    sess = Path(sys.argv[1])
    m = load_map()
    tl = bitmap_timeline(sess)
    print(f"{sess.name}  ({len(tl)} 4F0B0602 transitions)")
    print(f"baseline: {m['baseline_all_on']['bitmap']}\n")
    for t, hx in tl:
        names = match_sections(m, hx)
        print(f"  +{t:6.1f}s  {hx}")
        print(f"           -> {', '.join(names)}")


if __name__ == "__main__":
    main()
