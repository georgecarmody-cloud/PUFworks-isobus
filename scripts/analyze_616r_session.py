#!/usr/bin/env python3
"""Post-process a PUFworks-isobus recorder session from a 616R field sniff."""
import csv
import json
import sys
from pathlib import Path

# Allow running from repo root or scripts/
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sniff_616r import print_616r_report, summarize_frames  # noqa: E402


def load_session(sess: Path):
    meta = json.loads((sess / "session_meta.json").read_text(encoding="utf-8"))
    frames = list(csv.DictReader(open(sess / "frames.csv", newline="", encoding="utf-8")))
    shadow = []
    shadow_path = sess / "shadow_channels.csv"
    if shadow_path.exists():
        shadow = list(csv.DictReader(open(shadow_path, newline="", encoding="utf-8")))
    return meta, frames, shadow


def ef00_payload_digest(frames, sa_filter=None):
    from collections import Counter
    ef = [r for r in frames if r.get("pgn_hex") == "0xEF00"]
    if sa_filter:
        hx = f"0x{sa_filter:02X}"
        ef = [r for r in ef if r.get("sa_hex", "").lower() == hx.lower()]
    print(f"\nEF00 payload digest (n={len(ef)}):")
    prefixes = Counter()
    for r in ef:
        data = r.get("data_hex", "")
        if len(data) >= 8:
            prefixes[data[:8]] += 1
        elif data:
            prefixes[data[: min(8, len(data))]] += 1
    for pref, n in prefixes.most_common(15):
        print(f"  n={n:5d}  {pref}…")


def cb00_section_timeline(frames):
    from collections import Counter
    cb = [r for r in frames if r.get("pgn_hex") == "0xCB00" and len(r.get("data_hex", "")) >= 4]
    if not cb:
        return
    print(f"\nCB00 section bitmap samples (n={len(cb)}):")
    vals = Counter()
    for r in cb:
        try:
            b = bytes.fromhex(r["data_hex"])
            vals[f"0x{b[0]:02X}{b[1]:02X}"] += 1
        except ValueError:
            pass
    for v, n in vals.most_common(8):
        print(f"  {v}  n={n}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/analyze_616r_session.py <recordings/session_dir>")
        sys.exit(1)
    sess = Path(sys.argv[1])
    if not (sess / "session_meta.json").exists():
        print(f"Not a recorder session: {sess}")
        sys.exit(1)

    meta, frames, shadow = load_session(sess)
    summary = summarize_frames(frames)
    print_616r_report(sess.name, meta, summary, shadow)

    # Extra digests useful on first integrated 616R capture
    for sa in (0x94, 0x17, 0xCC, 0x68):
        ef00_payload_digest(frames, sa_filter=sa)
    cb00_section_timeline(frames)

    # Write machine-readable summary alongside session
    out = sess / "sniff_616r_summary.json"
    payload = {"meta": meta, "summary": summary}
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
