#!/usr/bin/env python3
"""Find shadow/host/vision inconsistencies in gatest_a1."""
import csv
import json
from collections import Counter
from pathlib import Path

GRC_BITS = {"L1": 1, "L2": 2, "C": 3, "R2": 4, "R1": 5}


def on_list(mask):
    b = int(mask)
    return [n for n, bit in GRC_BITS.items() if b & (1 << bit)]


def main():
    sess = Path(r"C:\Users\georg\AppData\Local\Programs\react-example\resources\engine\recordings\20260609_174841_gatest_a1")
    meta = json.loads((sess / "session_meta.json").read_text())
    rows = list(csv.DictReader(open(sess / "shadow_channels.csv", newline="", encoding="utf-8")))
    t0 = float(rows[0]["timestamp"])
    print(f"{meta['session_id']}  authority={meta['control_authority']}  duration={meta['duration_s']}s\n")

    # host_commanded vs grc_ef00_section_bitmap
    mism = [(r, int(r["host_commanded_bitmap"]), int(r["grc_ef00_section_bitmap"]))
            for r in rows if r["host_commanded_bitmap"] and r["grc_ef00_section_bitmap"]
            and int(r["host_commanded_bitmap"]) != int(r["grc_ef00_section_bitmap"])]
    print(f"host_commanded != grc_ef00_section_bitmap: {len(mism)}/{len(rows)}")
    if mism:
        print("  samples:", Counter((a, b) for _, a, b in mism).most_common(5))

    # vision vs manual intent expectations
    print(f"\nvision_bitmap histogram: {Counter(r['vision_bitmap'] for r in rows).most_common(8)}")
    print(f"shadow_and_bitmap histogram: {Counter(r['shadow_and_bitmap'] for r in rows).most_common(8)}")

    # AND-gate violations: shadow_and has bits host closed
    bad_and = []
    for r in rows:
        host = int(r["grc_ef00_section_bitmap"])
        shadow = int(r["shadow_and_bitmap"])
        if shadow & ~host:
            bad_and.append(r)
    print(f"\nshadow_and exceeds host mask: {len(bad_and)}/{len(rows)}")

    # master on but all sections off in parser
    master_on_all_off = [r for r in rows if r["grc_master_on"] == "1"
                         and all(r[f"grc_{s}"] == "0" for s in GRC_BITS)]
    print(f"master ON + all grc sections OFF: {len(master_on_all_off)}/{len(rows)}")
    if master_on_all_off:
        t = float(master_on_all_off[0]["timestamp"]) - t0
        print(f"  first at +{t:.1f}s  mask=0x{int(master_on_all_off[0]['grc_ef00_section_bitmap']):04X}")

    # master off but sections show on
    master_off_some_on = [r for r in rows if r["grc_master_on"] == "0"
                          and any(r[f"grc_{s}"] == "1" for s in GRC_BITS)]
    print(f"master OFF + any grc section ON: {len(master_off_some_on)}/{len(rows)}")

    # coarse vs fine mismatch
    coarse_mismatch = []
    for r in rows:
        mask = int(r["grc_ef00_section_bitmap"])
        coarse = int(r["grc_ef00_coarse_bitmap"])
        master = r["grc_master_on"]
        all_on = all(r[f"grc_{s}"] == "1" for s in GRC_BITS)
        any_off = any(r[f"grc_{s}"] == "0" for s in GRC_BITS)
        exp_coarse = None
        if master == "0":
            exp_coarse = 0xFFEE
        elif all_on:
            exp_coarse = 0xFFF6
        elif any_off:
            exp_coarse = 0xFFE6
        if exp_coarse is not None and coarse != exp_coarse:
            coarse_mismatch.append((r, exp_coarse, coarse))
    print(f"coarse bitmap mismatch vs master/sections: {len(coarse_mismatch)}/{len(rows)}")
    if coarse_mismatch:
        print("  samples:", Counter((exp, act) for _, exp, act in coarse_mismatch).most_common(5))

    # per-section columns vs mask bits
    sec_mask_mismatch = 0
    for r in rows:
        mask = int(r["grc_ef00_section_bitmap"])
        for name, bit in GRC_BITS.items():
            col = r[f"grc_{name}"] == "1"
            bit_on = bool(mask & (1 << bit))
            if col != bit_on:
                sec_mask_mismatch += 1
                break
    print(f"grc_L1..R1 columns disagree with section mask bit: {sec_mask_mismatch}/{len(rows)} rows")

    print("\n--- Notable transitions (master / mask / vision) ---")
    prev = None
    for r in rows:
        key = (r["grc_master_on"], r["grc_ef00_section_bitmap"], r["vision_bitmap"], r["shadow_and_bitmap"],
               tuple(r[f"grc_{s}"] for s in GRC_BITS))
        if key != prev:
            t = float(r["timestamp"]) - t0
            print(
                f"+{t:5.1f}s  master={r['grc_master_on']}  "
                f"host=0x{int(r['grc_ef00_section_bitmap']):04X}  "
                f"vision=0x{int(r['vision_bitmap']):04X}  "
                f"shadow=0x{int(r['shadow_and_bitmap']):04X}  "
                f"secs={on_list(r['grc_ef00_section_bitmap'])}"
            )
            prev = key


if __name__ == "__main__":
    main()
