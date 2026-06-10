#!/usr/bin/env python3
"""Deep analysis for gatest_11 session — section transitions + EF00 correlation."""
import csv
import json
import sys
from collections import Counter
from pathlib import Path

GRC_ELEMENT_TO_SECTION = {
    0x1F: "L1", 0x2C: "L1",
    0x1E: "L2", 0x2B: "L2",
    0x1C: "C",  0x29: "C",
    0x18: "R2", 0x25: "R2",
    0x10: "R1", 0x1D: "R1",
}

SECTION_BIT = {"L1": 1, "L2": 2, "C": 3, "R2": 4, "R1": 5}


def bmp_hex(val):
    return f"0x{int(val):04X}"


def on_sections_from_mask(val):
    b = int(val)
    return [n for n, bit in SECTION_BIT.items() if b & (1 << bit)]


def analyze(sess: Path):
    meta = json.loads((sess / "session_meta.json").read_text())
    print("=" * 70)
    print(sess.name, f"duration={meta['duration_s']}s")
    print("=" * 70)

    rows = list(csv.DictReader(open(sess / "shadow_channels.csv", newline="", encoding="utf-8")))
    t0 = float(rows[0]["timestamp"])

    def state_key(r):
        return (
            r["grc_L1"], r["grc_L2"], r["grc_C"], r["grc_R2"], r["grc_R1"],
            r["grc_master_on"], r["grc_ef00_section_bitmap"],
            r["grc_ef00_coarse_bitmap"], r["grc_ef00_rate_l_ha"],
        )

    print("\n--- SHADOW: state transitions ---")
    prev = None
    for r in rows:
        st = state_key(r)
        if st != prev:
            t = float(r["timestamp"]) - t0
            off = [s for s in ("L1", "L2", "C", "R2", "R1") if r[f"grc_{s}"] == "0"]
            on = on_sections_from_mask(r["grc_ef00_section_bitmap"])
            print(
                f"+{t:6.1f}s  master={r['grc_master_on']}  "
                f"mask={bmp_hex(r['grc_ef00_section_bitmap'])}  "
                f"coarse={bmp_hex(r['grc_ef00_coarse_bitmap'])}  "
                f"rate={r['grc_ef00_rate_l_ha']}  "
                f"OFF={off or '—'}  ON={on}"
            )
            prev = st

    print("\n--- SHADOW: mask histogram ---")
    for val, n in Counter(r["grc_ef00_section_bitmap"] for r in rows).most_common():
        print(f"  {bmp_hex(val)}  n={n:4d}  ON={on_sections_from_mask(val)}")

    frames = list(csv.DictReader(open(sess / "frames.csv", newline="", encoding="utf-8")))
    ef = [r for r in frames if r["pgn_hex"] == "0xEF00" and r["sa_hex"] == "0xCC"]
    ft0 = int(ef[0]["timestamp_ms"]) / 1000.0

    print("\n--- EF00: section OFF first occurrence ---")
    seen = {}
    for r in ef:
        hx = r["data_hex"]
        if not (hx.startswith("4F0B02020105") and hx.endswith("00")):
            continue
        if hx == "4F0B020201050000":
            continue
        if hx not in seen:
            elem = int(hx[12:14], 16)
            ff_guess = f"4F0B02FF{hx[12:14]}000000"
            name = GRC_ELEMENT_TO_SECTION.get(elem, "?")
            seen[hx] = (int(r["timestamp_ms"]) / 1000.0 - ft0, elem, name, ff_guess)
    for hx, (t, elem, name, ff) in sorted(seen.items(), key=lambda kv: kv[1][0]):
        n = sum(1 for r in ef if r["data_hex"] == hx)
        print(f"  +{t:6.1f}s  elem=0x{elem:02X}  -> {name:2s}  n={n:3d}  {hx}")

    print("\n--- EF00: unknown element IDs (not in ga_test11 map) ---")
    unknown = Counter()
    for r in ef:
        hx = r["data_hex"]
        if hx.startswith("4F0B02FF") and len(hx) >= 10:
            elem = int(hx[8:10], 16)
            if elem not in GRC_ELEMENT_TO_SECTION:
                unknown[elem] += 1
        if hx.startswith("4F0B02020105") and hx.endswith("00") and hx != "4F0B020201050000":
            elem = int(hx[12:14], 16)
            if elem not in GRC_ELEMENT_TO_SECTION:
                unknown[elem] += 1
    for elem, n in unknown.most_common():
        print(f"  0x{elem:02X}  n={n}")

    print("\n--- MASTER timeline ---")
    prev_m = None
    for r in ef:
        hx = r["data_hex"]
        if not hx.startswith("4F0601"):
            continue
        m = "ON" if hx.endswith("FF01FFFF") else "OFF" if hx.endswith("FF00FFFF") else "?"
        if m != prev_m:
            t = int(r["timestamp_ms"]) / 1000.0 - ft0
            print(f"  +{t:6.1f}s  master {m}  ({hx})")
            prev_m = m


if __name__ == "__main__":
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        r"C:\Users\georg\AppData\Local\Programs\react-example\resources\engine\recordings\20260609_145929_gatest_11"
    )
    analyze(path)
