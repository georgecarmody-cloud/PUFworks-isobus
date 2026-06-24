#!/usr/bin/env python3
"""Correlate operator timestamps with CAN signals in a recorder session."""
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


def t0_of(frames):
    return int(frames[0]["timestamp_ms"]) / 1000.0


def speed_series(frames, t0):
    out = []
    for r in frames:
        if r["pgn_hex"] != "0xFEF1":
            continue
        b = bytes.fromhex(r["data_hex"])
        if len(b) < 3:
            continue
        raw = b[1] | (b[2] << 8)
        if raw == 0xFFFF:
            continue
        t = int(r["timestamp_ms"]) / 1000.0 - t0
        out.append((t, raw / 256.0))
    return out


def speed_at(speeds, t, window=2.0):
    pts = [s for ts, s in speeds if abs(ts - t) <= window]
    if not pts:
        return None
    return min(pts), sum(pts) / len(pts), max(pts)


def cb00_prefix_counts(frames, t0, lo, hi, sa_hex=None):
    c = Counter()
    for r in frames:
        if r["pgn_hex"] != "0xCB00":
            continue
        if sa_hex and r["sa_hex"] != sa_hex:
            continue
        t = int(r["timestamp_ms"]) / 1000.0 - t0
        if not (lo <= t <= hi):
            continue
        hx = r["data_hex"]
        c[hx[:8]] += 1
    return c


def ef00_prefix_changes(frames, t0, lo, hi, sa_hex="0xE1"):
    prev = {}
    changes = []
    for r in frames:
        if r["sa_hex"] != sa_hex or r["pgn_hex"] != "0xEF00":
            continue
        t = int(r["timestamp_ms"]) / 1000.0 - t0
        if not (lo <= t <= hi):
            continue
        hx = r["data_hex"]
        pre = hx[:6]
        if prev.get(pre) == hx:
            continue
        prev[pre] = hx
        changes.append((t, pre, hx))
    return changes


def bhc_activity(frames, t0, lo, hi):
    rows = []
    for r in frames:
        if r["sa_hex"] != "0x8A":
            continue
        t = int(r["timestamp_ms"]) / 1000.0 - t0
        if not (lo <= t <= hi):
            continue
        rows.append((t, r["pgn_hex"], r["data_hex"][:16]))
    return rows


def unique_cb00_payloads(frames, t0, lo, hi, sa_hex, limit=12):
    seen = []
    seen_set = set()
    for r in frames:
        if r["pgn_hex"] != "0xCB00" or r["sa_hex"] != sa_hex:
            continue
        t = int(r["timestamp_ms"]) / 1000.0 - t0
        if not (lo <= t <= hi):
            continue
        hx = r["data_hex"]
        if hx in seen_set:
            continue
        seen_set.add(hx)
        seen.append((t, hx))
        if len(seen) >= limit:
            break
    return seen


def main():
    sess = Path(sys.argv[1])
    meta = json.loads((sess / "session_meta.json").read_text(encoding="utf-8"))
    frames = list(csv.DictReader(open(sess / "frames.csv", newline="", encoding="utf-8")))
    t0 = t0_of(frames)
    dur = int(frames[-1]["timestamp_ms"]) / 1000.0 - t0
    speeds = speed_series(frames, t0)

    print("=" * 72)
    print(sess.name)
    print(f"frames={len(frames)}  duration={dur:.1f}s  sniff={meta.get('sniff_mode')}")
    print("=" * 72)

    windows = [
        ("111s manual sections R5-R3 off then all on + slow", 105, 120),
        ("191-201s speed increase", 186, 206),
        ("221-231s centre raise + auto height return", 216, 236),
        ("350-380s headland ASC off/on sequence", 345, 385),
    ]

    for label, lo, hi in windows:
        print(f"\n### {label}  (+{lo}-{hi}s)")
        sp = speed_at(speeds, (lo + hi) / 2)
        if sp:
            print(f"  Speed FEF1 (±2s mid): min={sp[0]:.1f} avg={sp[1]:.1f} max={sp[2]:.1f} km/h")

        mnc_pre = cb00_prefix_counts(frames, t0, lo, hi, "0xD4").most_common(6)
        f7_pre = cb00_prefix_counts(frames, t0, lo, hi, "0xF7").most_common(4)
        print(f"  MNC CB00 prefix top: {mnc_pre}")
        print(f"  JD_SEC CB00 prefix top: {f7_pre}")

        ef = ef00_prefix_changes(frames, t0, lo, hi)
        if ef:
            print("  SRC EF00 changes:")
            for t, pre, hx in ef[:10]:
                extra = ""
                if hx.startswith("4F0101") and len(hx) >= 10:
                    raw = int.from_bytes(bytes.fromhex(hx)[3:5], "little")
                    extra = f" -> {raw/10:.1f} L/ha"
                elif hx.startswith("F43401") and len(hx) >= 10:
                    b = bytes.fromhex(hx)
                    be = (b[3] << 8) | b[4]
                    extra = f" -> {be/4.096:.0f} kPa" if be >= 256 else " -> rate mode"
                print(f"    +{t:6.1f}s {pre}…{extra}")

        bhc = bhc_activity(frames, t0, lo, hi)
        if bhc:
            pgns = Counter(p for _, p, _ in bhc)
            print(f"  BHC frames: {len(bhc)}  PGNs: {dict(pgns)}")
            for t, pgn, hx in bhc[:5]:
                print(f"    +{t:6.1f}s {pgn} {hx}")

        new_mnc = unique_cb00_payloads(frames, t0, lo, hi, "0xD4", 8)
        if new_mnc:
            print("  MNC CB00 new payloads (sample):")
            for t, hx in new_mnc:
                print(f"    +{t:5.1f}s {hx[:24]}…")


if __name__ == "__main__":
    main()
