#!/usr/bin/env python3
"""Batch analysis for paddock validation sessions."""
import csv
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAP = json.loads((ROOT / "library" / "section_map.json").read_text())


def sess_info(path: Path):
    frames = list(csv.DictReader(open(path / "frames.csv", newline="", encoding="utf-8")))
    shadow = list(csv.DictReader(open(path / "shadow_channels.csv", newline="", encoding="utf-8")))
    meta = json.loads((path / "session_meta.json").read_text())
    t0 = int(frames[0]["timestamp_ms"]) / 1000.0
    dur = int(frames[-1]["timestamp_ms"]) / 1000.0 - t0
    t0u = float(shadow[0]["timestamp"])
    return frames, shadow, meta, t0, dur, t0u


def ff_timeline(frames, t0):
    prev = None
    out = []
    for r in sorted(frames, key=lambda x: int(x["timestamp_ms"])):
        if r["sa_hex"] != "0xE1" or not r["data_hex"].startswith("4F0B06FF"):
            continue
        hx = r["data_hex"]
        if hx == prev:
            continue
        prev = hx
        b = bytes.fromhex(hx)
        out.append((int(r["timestamp_ms"]) / 1000.0 - t0, b[4] if len(b) > 4 else 0, hx))
    return out


def bm_timeline(frames, t0):
    prev = None
    out = []
    for r in sorted(frames, key=lambda x: int(x["timestamp_ms"])):
        if r["sa_hex"] != "0xE1" or not r["data_hex"].startswith("4F0B0602"):
            continue
        hx = r["data_hex"]
        if hx == prev:
            continue
        prev = hx
        out.append((int(r["timestamp_ms"]) / 1000.0 - t0, hx))
    return out


def speed_window(frames, t0, lo, hi):
    pts = []
    for r in frames:
        if r["pgn_hex"] != "0xFEF1":
            continue
        t = int(r["timestamp_ms"]) / 1000.0 - t0
        if not (lo <= t <= hi):
            continue
        b = bytes.fromhex(r["data_hex"])
        if len(b) < 3:
            continue
        raw = b[1] | (b[2] << 8)
        if raw != 0xFFFF:
            pts.append(raw / 256.0)
    if not pts:
        return None
    return min(pts), sum(pts) / len(pts), max(pts)


def mnc_prefix_window(frames, t0, lo, hi):
    sub = [
        r for r in frames
        if r["sa_hex"] == "0xD4" and r["pgn_hex"] == "0xCB00"
        and lo <= int(r["timestamp_ms"]) / 1000.0 - t0 <= hi
    ]
    return Counter(r["data_hex"][:8] for r in sub).most_common(8)


def analyze(path: Path):
    frames, shadow, meta, t0, dur, t0u = sess_info(path)
    label = meta.get("label", path.name)
    print("=" * 72)
    print(f"{label}  ({dur:.1f}s, {len(frames)} frames)")
    print("=" * 72)

    print("\n4F0B0602 bitmap timeline:")
    for t, hx in bm_timeline(frames, t0):
        mark = "ALL_ON" if hx == MAP["baseline_all_on"]["bitmap"] else hx
        print(f"  +{t:5.1f}s  {mark}")

    print("\n4F0B06FF timeline:")
    for t, idx, hx in ff_timeline(frames, t0):
        print(f"  +{t:5.1f}s  0x{idx:02X}  {hx}")

    sp = speed_window(frames, t0, 0, dur)
    if sp:
        print(f"\nSpeed whole session: {sp[0]:.1f}–{sp[1]:.1f}–{sp[2]:.1f} km/h")

    # headland-ish: speed dip
    for lo, hi, name in [(0, dur, "full"), (0, 60, "first60s"), (60, dur, "after60s"), (120, dur, "after120s")]:
        if hi <= lo:
            continue
        spw = speed_window(frames, t0, lo, hi)
        if spw:
            print(f"  speed {name} (+{lo}-{hi}s): {spw[0]:.1f}–{spw[2]:.1f} km/h")

    mnc = mnc_prefix_window(frames, t0, 0, dur)
    if mnc:
        print(f"\nMNC CB00 top prefixes (full session): {mnc[:6]}")


def main():
    for p in sys.argv[1:]:
        analyze(Path(p))
        print()


if __name__ == "__main__":
    main()
