#!/usr/bin/env python3
"""Deep analysis: FEF1 speed, EF00/shadow correlation, toggle interleaving."""
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

SESS = Path(
    r"C:\Users\georg\AppData\Local\Programs\react-example\resources\engine\recordings\20260609_174841_gatest_a1"
)
GRC_BITS = {"L1": 1, "L2": 2, "C": 3, "R2": 4, "R1": 5}
ELEMENT = {0x1F: "L1", 0x1E: "L2", 0x1C: "C", 0x18: "R2", 0x10: "R1"}


def on_list(mask):
    return [n for n, bit in GRC_BITS.items() if int(mask) & (1 << bit)]


def main():
    meta = json.loads((SESS / "session_meta.json").read_text())
    frames = list(csv.DictReader(open(SESS / "frames.csv", newline="", encoding="utf-8")))
    shadow = list(csv.DictReader(open(SESS / "shadow_channels.csv", newline="", encoding="utf-8")))
    t0_ms = int(frames[0]["timestamp_ms"])
    t0 = float(shadow[0]["timestamp"])

    print("=== FEF1 / FEE8 speed decode ===")
    for pgn, label in (("0xFEF1", "FEF1"), ("0xFEE8", "FEE8")):
        spd = [r for r in frames if r["pgn_hex"] == pgn]
        if not spd:
            print(f"{label}: no frames")
            continue
        vals = []
        for r in spd:
            b = bytes.fromhex(r["data_hex"])
            if pgn == "0xFEF1" and len(b) >= 3:
                raw = b[1] | (b[2] << 8)
            elif len(b) >= 2:
                raw = b[0] | (b[1] << 8)
            else:
                continue
            vals.append((raw, raw / 256.0, r["data_hex"]))
        print(f"{label}: n={len(spd)} unique_raw={len(set(v[0] for v in vals))}")
        print(f"  top raw:", Counter(v[0] for v in vals).most_common(5))
        print(f"  sample hex:", Counter(v[2] for v in vals).most_common(3))

    shadow_speed = Counter(r["speed_kmh"] for r in shadow)
    print(f"shadow speed_kmh: {shadow_speed.most_common(5)}")

    print("\n=== Shadow mask dwell time ===")
    dwell = defaultdict(float)
    prev_t = None
    prev_mask = None
    for r in shadow:
        t = float(r["timestamp"])
        mask = int(r["grc_ef00_section_bitmap"])
        if prev_t is not None:
            dwell[mask] += t - prev_t
        prev_t, prev_mask = t, mask
    total = sum(dwell.values())
    for mask, sec in sorted(dwell.items(), key=lambda x: -x[1]):
        pct = 100 * sec / total
        secs = on_list(mask) or []
        print(f"  0x{mask:04X} {str(secs):20s} {sec:5.1f}s ({pct:4.1f}%)")

    print("\n=== EF00 section cmds near shadow transitions (+11s to +18s) ===")
    ef = [r for r in frames if r["pgn_hex"] == "0xEF00" and r["sa_hex"] == "0xCC"]
    t0_ef = int(ef[0]["timestamp_ms"]) / 1000.0
    for r in ef:
        t = int(r["timestamp_ms"]) / 1000.0 - t0_ef
        if t < 11 or t > 18:
            continue
        hx = r["data_hex"]
        if hx.startswith("4F0B0202") or hx.startswith("4F0601"):
            tag = ""
            if hx == "4F0B020201050000":
                tag = " ALL-ON-RESET"
            elif hx == "4F0B020200050000":
                tag = " ALL-OFF-IDLE"
            elif hx.startswith("4F0B02020105") and len(hx) >= 16:
                el = int(hx[12:14], 16)
                tag = f" TOGGLE {ELEMENT.get(el, f'0x{el:02X}')}"
            elif hx.startswith("4F0601"):
                tag = " MASTER-OFF" if "FF00" in hx else " MASTER-ON"
            print(f"  +{t:5.2f}s {hx}{tag}")

    print("\n=== 050000 vs 051XX interleaving (all manual cmds) ===")
    bursts = []
    for r in ef:
        hx = r["data_hex"]
        if not hx.startswith("4F0B0202"):
            continue
        t = int(r["timestamp_ms"]) / 1000.0 - t0_ef
        bursts.append((t, hx))

    # Group by 50ms windows
    win = defaultdict(list)
    for t, hx in bursts:
        win[int(t * 20)].append(hx)  # 50ms buckets

    mixed = 0
    for bucket in sorted(win):
        hs = set(win[bucket])
        has_reset = "4F0B020201050000" in hs
        has_toggle = any(h.startswith("4F0B02020105") and h != "4F0B020201050000" for h in hs)
        has_idle = "4F0B020200050000" in hs
        if has_reset and has_toggle:
            mixed += 1
            t = bucket / 20.0
            print(f"  +{t:5.1f}s bucket: reset+toggle {[h for h in win[bucket] if '0500' in h[:14]]}")
        if has_idle and has_toggle:
            mixed += 1
            t = bucket / 20.0
            print(f"  +{t:5.1f}s bucket: idle+toggle")
    print(f"  mixed buckets (reset/toggle or idle/toggle): {mixed}")

    print("\n=== +25.2s master-ON all-off anomaly ===")
    for r in shadow:
        t = float(r["timestamp"]) - t0
        if 25.0 <= t <= 25.5:
            print(
                f"  +{t:.2f}s master={r['grc_master_on']} mask=0x{int(r['grc_ef00_section_bitmap']):04X} "
                f"secs={on_list(r['grc_ef00_section_bitmap'])}"
            )
    for r in ef:
        t = int(r["timestamp_ms"]) / 1000.0 - t0_ef
        if 25.0 <= t <= 25.5:
            hx = r["data_hex"]
            if hx.startswith("4F0601") or hx.startswith("4F0B0202"):
                print(f"  EF00 +{t:.3f}s {hx}")

    print("\n=== +29-36s R1/L1 oscillation EF00 cmds ===")
    prev_mask = None
    for r in shadow:
        t = float(r["timestamp"]) - t0
        if t < 29 or t > 37:
            continue
        mask = int(r["grc_ef00_section_bitmap"])
        if mask != prev_mask:
            print(f"  shadow +{t:.1f}s 0x{mask:04X} {on_list(mask)}")
            prev_mask = mask

    toggles_29 = []
    for r in ef:
        t = int(r["timestamp_ms"]) / 1000.0 - t0_ef
        if 29 <= t <= 37:
            hx = r["data_hex"]
            if hx.startswith("4F0B02020105") and hx != "4F0B020201050000":
                el = int(hx[12:14], 16)
                toggles_29.append((t, ELEMENT.get(el, f"0x{el:02X}"), hx))
    print(f"  toggle cmds in window: {len(toggles_29)}")
    for t, el, hx in toggles_29[:20]:
        print(f"    +{t:.2f}s {el} {hx}")
    resets = [t for t, hx in [(int(r["timestamp_ms"]) / 1000.0 - t0_ef, r["data_hex"]) for r in ef]
              if 29 <= t <= 37 and hx == "4F0B020201050000"]
    print(f"  all-on resets in window: {len(resets)}")


if __name__ == "__main__":
    main()
