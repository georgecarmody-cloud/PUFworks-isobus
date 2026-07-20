#!/usr/bin/env python3
"""Synthetic-frame unit test for the GNSS fix-quality decode (PGN 0xFFFF/0x51 b7).

Pure decode (no python-can / no hardware). Run:
  python scripts/test_gps_quality_decode.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gps_bridge_lib import (  # noqa: E402
    GpsBridge, GpsFix, decode_gnss_quality_ffff, decode_gnss_sats_ffff,
    gga_quality_from_jd, nmea_gga, nmea_panda, JD_GNSS_QUALITY_TO_GGA,
)
import json  # noqa: E402

fails = []


def check(name, ok, detail=""):
    print(f"[{'ok ' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))
    if not ok:
        fails.append(name)


def frame_0x51(sats, qb7, c=(0x09, 0x05, 0x08)):
    """0x51 summary: [0x51,0x03,0x02, sats, c1,c2,c3, qualByte7]."""
    return bytes([0x51, 0x03, 0x02, sats, c[0], c[1], c[2], qb7]).hex()

# --- Q1 raw byte7 extraction + signature gating ---------------------------- #
q1 = (decode_gnss_quality_ffff(frame_0x51(36, 0x01)) == 0x01
      and decode_gnss_quality_ffff(frame_0x51(30, 0x04)) == 0x04
      and decode_gnss_quality_ffff("520302240905080 1".replace(" ", "")) is None  # not 0x51
      and decode_gnss_quality_ffff("510302") is None)                              # too short
check("Q1 decode byte7 + signature/length gating", q1)

# --- Q2 JD->GGA mapping (hypothesis table) --------------------------------- #
q2 = (gga_quality_from_jd(0x00) == 0 and gga_quality_from_jd(0x01) == 4
      and gga_quality_from_jd(0x02) == 5 and gga_quality_from_jd(0x03) == 2
      and gga_quality_from_jd(0x04) == 1
      and gga_quality_from_jd(0x09) == 1            # unknown -> autonomous fallback
      and gga_quality_from_jd(None) == 1)
check("Q2 JD->GGA mapping + safe fallback", q2,
      f"map={JD_GNSS_QUALITY_TO_GGA}")

# --- Q3 sats still decode from the same frame (no regression) -------------- #
q3 = (decode_gnss_sats_ffff(frame_0x51(36, 0x01)) == 36
      and decode_gnss_sats_ffff(frame_0x51(0, 0x01)) is None)   # 0 sats -> unknown
check("Q3 satellite count unchanged", q3)

# --- Q4 end-to-end through GpsBridge: RTK shows instead of constant 1 ------- #
br = GpsBridge()
# default fix_quality is the old constant until a 0x51 arrives
before = br.fix.fix_quality
# lat/lon first so the fix is "valid"
br.update_from_frame(sa_hex="0x1C", pgn_hex="0xFEF3",
                     data_hex="00000000000000 00".replace(" ", ""))
br.update_from_frame(sa_hex="0x1C", pgn_hex="0xFFFF", data_hex=frame_0x51(33, 0x01))
q4 = (before == 1 and br.fix.fix_quality == 4 and br.fix.gnss_quality_raw == 0x01
      and br.fix.satellites == 33)
check("Q4 bridge sets RTK (4) from byte7=0x01", q4,
      f"before={before} after={br.fix.fix_quality} raw={br.fix.gnss_quality_raw}")

# --- Q5 degraded value flows through (turn -> float) ------------------------ #
br.update_from_frame(sa_hex="0x1C", pgn_hex="0xFFFF", data_hex=frame_0x51(28, 0x02))
q5 = (br.fix.fix_quality == 5 and br.fix.gnss_quality_raw == 0x02)
check("Q5 byte7=0x02 -> RTK float (5)", q5, f"fix={br.fix.fix_quality}")

# --- Q6 SA gating: DISP 0xF0 0xFFFF must NOT touch quality ------------------ #
br2 = GpsBridge()
br2.update_from_frame(sa_hex="0x1C", pgn_hex="0xFEF3", data_hex="0000000000000000")
br2.update_from_frame(sa_hex="0x1C", pgn_hex="0xFFFF", data_hex=frame_0x51(31, 0x01))
q_before = br2.fix.fix_quality
br2.update_from_frame(sa_hex="0xF0", pgn_hex="0xFFFF", data_hex=frame_0x51(10, 0x04))
q6 = (q_before == 4 and br2.fix.fix_quality == 4)   # DISP frame ignored (SA-gated)
check("Q6 SA-gate: DISP 0xF0 0xFFFF ignored", q6, f"stayed={br2.fix.fix_quality}")

# --- Q7 fix_quality flows to JSON + GGA + PANDA ---------------------------- #
fix = GpsFix(latitude=-34.1, longitude=138.7, satellites=33, fix_quality=4,
             gnss_quality_raw=0x01)
j = json.loads(fix.to_json())
gga = nmea_gga(fix).strip().split(",")
panda = nmea_panda(fix).strip().split(",")
q7 = (j["schema"] == "GpsFixV2" and j["fix_quality"] == 4
      and j["gnss_quality_raw"] == 1
      and gga[6] == "4"           # GGA field 6 = fix quality
      and panda[6] == "4")        # PANDA field 6 = fix quality
check("Q7 fix_quality in GpsFixV2 + $GPGGA + $PANDA", q7,
      f"json={j['fix_quality']} gga={gga[6]} panda={panda[6]}")

# --- Q8 custom quality_map override (no code edit) ------------------------- #
br3 = GpsBridge(quality_map={0x01: 5})
br3.update_from_frame(sa_hex="0x1C", pgn_hex="0xFEF3", data_hex="0000000000000000")
br3.update_from_frame(sa_hex="0x1C", pgn_hex="0xFFFF", data_hex=frame_0x51(33, 0x01))
q8 = br3.fix.fix_quality == 5
check("Q8 quality_map override honored", q8, f"fix={br3.fix.fix_quality}")

print()
if fails:
    print(f"[test_gps_quality_decode] FAIL - {fails}")
    sys.exit(1)
print("[test_gps_quality_decode] PASS - byte7 decode, JD->GGA mapping + fallback, "
      "SA gating, sats no-regression, and flow into GpsFixV2/$GPGGA/$PANDA all OK.")
