#!/usr/bin/env python3
"""Summarize SRC 4F0B06 FF/0602 unique payloads per single-section capture."""
import csv
import sys
from pathlib import Path


def summarize(sess: Path) -> dict:
    frames = list(csv.DictReader(open(sess / "frames.csv", newline="", encoding="utf-8")))
    t0 = int(frames[0]["timestamp_ms"]) / 1000.0
    ff = set()
    bm = set()
    ff_first = []
    bm_first = []
    for r in sorted(frames, key=lambda x: int(x["timestamp_ms"])):
        if r["sa_hex"] != "0xE1" or r["pgn_hex"] != "0xEF00":
            continue
        hx = r["data_hex"]
        t = int(r["timestamp_ms"]) / 1000.0 - t0
        if hx.startswith("4F0B06FF"):
            if hx not in ff:
                ff.add(hx)
                ff_first.append((t, hx))
        elif hx.startswith("4F0B0602"):
            if hx not in bm:
                bm.add(hx)
                bm_first.append((t, hx))
    return {
        "session": sess.name,
        "label": __import__("json").loads((sess / "session_meta.json").read_text()).get("label", ""),
        "duration_s": round(int(frames[-1]["timestamp_ms"]) / 1000.0 - t0, 1),
        "ff_unique": len(ff),
        "bm_unique": len(bm),
        "ff_first": ff_first[:6],
        "bm_first": bm_first[:6],
    }


def main():
    sessions = [Path(p) for p in sys.argv[1:]]
    if not sessions:
        root = Path(__file__).resolve().parents[1] / "recordings"
        sessions = sorted(root.glob("*_616r_sec_*"))
    print(f"{'label':24s}  dur   FF  BM  first FF idx@t")
    for sess in sessions:
        if not (sess / "frames.csv").exists():
            continue
        s = summarize(sess)
        label = s["label"] or s["session"]
        ff_line = ""
        if s["ff_first"]:
            t, hx = s["ff_first"][0]
            b = bytes.fromhex(hx)
            idx = b[4] if len(b) > 4 else 0
            ff_line = f"0x{idx:02X}@+{t:.1f}s"
        print(f"{label:24s}  {s['duration_s']:4.1f}  {s['ff_unique']:2d}  {s['bm_unique']:2d}  {ff_line}")
        for t, hx in s["ff_first"][1:4]:
            b = bytes.fromhex(hx)
            print(f"{'':24s}       +{t:4.1f}s 0x{b[4]:02X}  {hx}")


if __name__ == "__main__":
    main()
