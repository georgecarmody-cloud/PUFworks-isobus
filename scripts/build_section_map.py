#!/usr/bin/env python3
"""Build R5-L5 section map from single-toggle recorder sessions."""
import csv
import json
import sys
from pathlib import Path

ORDER = ("R5", "R4", "R3", "R2", "R1", "C", "L1", "L2", "L3", "L4", "L5")


def analyze(sess: Path) -> dict:
    label = json.loads((sess / "session_meta.json").read_text()).get("label", sess.name)
    section = label.split("_")[-1] if "_" in label else "?"
    frames = list(csv.DictReader(open(sess / "frames.csv", newline="", encoding="utf-8")))
    t0 = int(frames[0]["timestamp_ms"]) / 1000.0
    dur = int(frames[-1]["timestamp_ms"]) / 1000.0 - t0

    ff_events = []
    bm_events = []
    seen_ff, seen_bm = set(), set()
    for r in sorted(frames, key=lambda x: int(x["timestamp_ms"])):
        if r["sa_hex"] != "0xE1" or r["pgn_hex"] != "0xEF00":
            continue
        hx = r["data_hex"]
        t = int(r["timestamp_ms"]) / 1000.0 - t0
        if hx.startswith("4F0B06FF") and hx not in seen_ff:
            seen_ff.add(hx)
            b = bytes.fromhex(hx)
            ff_events.append({
                "t": round(t, 2),
                "idx": b[4] if len(b) > 4 else None,
                "hex": hx,
            })
        elif hx.startswith("4F0B0602") and hx not in seen_bm:
            seen_bm.add(hx)
            b = bytes.fromhex(hx)
            bm_events.append({
                "t": round(t, 2),
                "bm6_9": b[6:10].hex().upper() if len(b) >= 10 else hx[12:20],
                "hex": hx,
            })

    # Heuristic: first novel FF after t>1s = OFF toggle; second = ON
    ff_toggle = [e for e in ff_events if e["t"] >= 1.0][:4]
    bm_toggle = [e for e in bm_events if e["t"] >= 1.0][:4]

    return {
        "section": section,
        "label": label,
        "duration_s": round(dur, 1),
        "ff_all": ff_events,
        "bm_all": bm_events,
        "ff_toggle": ff_toggle,
        "bm_toggle": bm_toggle,
    }


def main():
    sessions = [Path(p) for p in sys.argv[1:]]
    if not sessions:
        root = Path(__file__).resolve().parents[1] / "recordings"
        sessions = sorted(root.glob("*_616r_R*")) + sorted(root.glob("*_616r_L*")) + sorted(root.glob("*_616r_C"))

    results = [analyze(s) for s in sessions if (s / "frames.csv").exists()]
    results.sort(key=lambda r: ORDER.index(r["section"]) if r["section"] in ORDER else 99)

    print("SECTION MAP — SRC 0xE1 EF00 4F0B06 (single-toggle captures)")
    print("=" * 88)
    print(f"{'Sec':4s}  {'dur':>5s}  {'OFF idx':>8s}  {'ON idx':>8s}  {'OFF bm[6:10]':>12s}  {'ON bm[6:10]':>12s}")
    print("-" * 88)

    rows = []
    for r in results:
        off_ff = r["ff_toggle"][0]["idx"] if len(r["ff_toggle"]) >= 1 else None
        on_ff = r["ff_toggle"][1]["idx"] if len(r["ff_toggle"]) >= 2 else None
        off_bm = r["bm_toggle"][0]["bm6_9"] if len(r["bm_toggle"]) >= 1 else ""
        on_bm = r["bm_toggle"][1]["bm6_9"] if len(r["bm_toggle"]) >= 2 else ""
        off_ff_s = f"0x{off_ff:02X}" if off_ff is not None else "—"
        on_ff_s = f"0x{on_ff:02X}" if on_ff is not None else "—"
        print(f"{r['section']:4s}  {r['duration_s']:5.1f}  {off_ff_s:>8s}  {on_ff_s:>8s}  {off_bm:>12s}  {on_bm:>12s}")
        rows.append(r)

    print("\nDetail — all novel 4F0B06FF (t>=1s):")
    for r in rows:
        toggles = [e for e in r["ff_all"] if e["t"] >= 1.0]
        if toggles:
            parts = ", ".join(f"+{e['t']}s 0x{e['idx']:02X}" for e in toggles[:6])
            print(f"  {r['section']:4s}: {parts}")


if __name__ == "__main__":
    main()
