#!/usr/bin/env python3
"""Detect MNC CB00 prefix cascades and shadow bitmap steps in section-toggle sessions."""
import csv
import json
import sys
from collections import Counter
from pathlib import Path

CASCADE = ("R5", "R4", "R3", "R2", "R1", "C", "L1", "L2", "L3", "L4", "L5")
SECTION_BITS = {
    "R5": 2, "R4": 3, "R3": 4, "R2": 5, "R1": 6, "C": 7,
    "L1": 8, "L2": 9, "L3": 10, "L4": 11, "L5": 12,
}


def decode_sections(val: int) -> str:
    on = [n for n, bit in SECTION_BITS.items() if val & (1 << bit)]
    off = [n for n in CASCADE if n not in on]
    return f"ON={','.join(on) or '-'} OFF={','.join(off) or '-'}"


def main():
    sess = Path(sys.argv[1])
    frames = list(csv.DictReader(open(sess / "frames.csv", newline="", encoding="utf-8")))
    shadow = list(csv.DictReader(open(sess / "shadow_channels.csv", newline="", encoding="utf-8")))
    t0 = int(frames[0]["timestamp_ms"]) / 1000.0
    t0u = float(shadow[0]["timestamp"])
    dur = int(frames[-1]["timestamp_ms"]) / 1000.0 - t0

    print("=" * 72)
    print(sess.name, f"duration={dur:.1f}s")
    print("=" * 72)

    # MNC CB00 prefix transitions (8-char prefix)
    mnc = [
        (int(r["timestamp_ms"]) / 1000.0 - t0, r)
        for r in frames
        if r["sa_hex"] == "0xD4" and r["pgn_hex"] == "0xCB00"
    ]
    last = None
    prefix_events = []
    for t, r in sorted(mnc, key=lambda x: x[0]):
        p = r["data_hex"][:8]
        if p != last:
            prefix_events.append((t, p, r["data_hex"]))
            last = p

    # Filter to interesting prefixes (not pure idle churn): 13xx/93xx/83xx/73xx/53xx/63xx
    interesting = [
        (t, p, hx) for t, p, hx in prefix_events
        if p.startswith("13") or p.startswith("9") or p.startswith("8")
        or p.startswith("7") or p.startswith("6") or p.startswith("5")
    ]
    print(f"\nMNC CB00 prefix transitions: {len(prefix_events)} total, {len(interesting)} interesting")
    print("Interesting prefix timeline (gap > 0.5s or prefix family change):")
    prev_t, prev_p = -999, ""
    shown = 0
    for t, p, hx in interesting:
        if shown < 80 and (t - prev_t >= 0.5 or p[:4] != prev_p[:4]):
            print(f"  +{t:6.1f}s  {p}  {hx[:20]}")
            prev_t, prev_p = t, p
            shown += 1

    # Shadow bitmap stable steps (debounce 0.3s)
    srows = sorted([(float(r["timestamp"]) - t0u, r) for r in shadow], key=lambda x: x[0])
    print("\nShadow host_commanded_bitmap steps (0.5s debounce):")
    last_b, last_t = None, -999
    for t, r in srows:
        b = int(r["host_commanded_bitmap"])
        if b != last_b and t - last_t >= 0.5:
            print(f"  +{t:6.1f}s  0x{b:04X}  {decode_sections(b)}")
            last_b, last_t = t, t

    # SRC EF00 4F0B manual elements
    ef0b = [
        (int(r["timestamp_ms"]) / 1000.0 - t0, r["data_hex"])
        for r in frames
        if r["sa_hex"] == "0xE1" and r["pgn_hex"] == "0xEF00" and r["data_hex"].startswith("4F0B")
    ]
    last_h = None
    print(f"\nSRC EF00 4F0B* changes: {len(ef0b)} frames")
    for t, hx in sorted(ef0b, key=lambda x: x[0]):
        h12 = hx[:12]
        if h12 != last_h:
            print(f"  +{t:6.1f}s  {hx[:24]}")
            last_h = h12

    # Cluster interesting prefix bursts (gap > 8s = separate operator phase)
    if interesting:
        clusters = []
        cluster = [interesting[0]]
        for ev in interesting[1:]:
            if ev[0] - cluster[-1][0] > 8.0:
                clusters.append(cluster)
                cluster = [ev]
            else:
                cluster.append(ev)
        clusters.append(cluster)
        print(f"\nDetected {len(clusters)} MNC prefix burst cluster(s) (>8s gap splits phases):")
        for i, cl in enumerate(clusters, 1):
            print(f"  Phase {i}: +{cl[0][0]:.1f}s - +{cl[-1][0]:.1f}s  ({len(cl)} prefix steps)")
            tops = Counter(p[:4] for _, p, _ in cl)
            print(f"    prefix families: {tops.most_common(8)}")


if __name__ == "__main__":
    main()
