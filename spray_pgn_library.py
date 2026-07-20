"""
Curated PGN / node filter for sprayer CAN sniffing and library compilation.

Categories align with field analysis goals:
  gps_motion     — speed, position, heading, curvature
  rate_section   — target rate, section bitmap, TC process data, DDI 141/157/158
  flow_pressure  — flow meter, pump, line/tank pressure (PGN + spray-node catch-all)
  boom_height    — BoomTrac / wing height / fold interlocks (BHC node catch-all)
  spray_proprietary — JD/GRC EF00 and other OEM process-data not yet fully decoded

The library is the single source for:
  - bus_engine recorder filter (SET_SNIFF_MODE:spray)
  - bench-ui CAN monitor preset
  - scripts/compile_pgn_catalog.py field observations merge

Export JSON:  library/spray_pgn_library.json  (run export_library_json())
Field decodes: library/SPRAY_DECODE.md  (JD controller names — SRC, MNC, GRC.001, not tractor model)
"""

from __future__ import annotations

import json
import os
from typing import Dict, Iterable, List, Optional, Set, Tuple

# Spray-relevant source addresses — any PGN from these nodes is retained in `spray` mode
# so proprietary IDs (e.g. SR1 0x0CCBF7D4 work messages) are captured before decode.
SPRAY_WATCH_SAS: Set[int] = {
    0x00,   # engine ECU (vehicle speed context)
    0x17, 0xE1,  # SRC / PSSC rate + sections
    0x1C,   # ATX GPS / steering
    0x26, 0xF0,  # display (TC server responses)
    0x68, 0xD4, 0x69, 0xCD,  # MNC / NZC ExactApply
    0x8A,   # BHC boom height
    0x94,   # GWC See & Spray gateway
    0xCC,   # GRC rate controller (Goldacres + some JD paths)
    0xF7,   # JD section-control peer
    0xBA, 0xB9, 0xD5,  # E700 / EF00 peers — identify on Diagnostics
    0xA2,   # VPU family (section indexing context on IB2 bridge)
}

# PGN catalog entries — extend as field sessions confirm new traffic.
PGN_CATALOG: List[dict] = [
    # --- GPS / motion ---
    {"pgn": 0xFEF1, "name": "CCVS Wheel-Based Speed", "category": "gps_motion",
     "status": "confirmed", "notes": "SPN 84 bytes 1-2, 1/256 km/h. Primary speed for latency budget."},
    {"pgn": 0xFEE8, "name": "Navigation / TCM attitude", "category": "gps_motion",
     "status": "confirmed", "notes": "ATX 0x1C: heading b0-1, speed b2-3, pitch b4-5, alt b6-7. Prefer FEF1 speed."},
    {"pgn": 0xFEE6, "name": "ATX companion (roll candidate)", "category": "gps_motion",
     "status": "parked", "notes": "On wire ATX 0x1C ~5 Hz; bytes 2-3 /128 decode DISPROVEN (2026-06-24). Not exported by gps_bridge until re-sniffed."},
    {"pgn": 0xFEF3, "name": "Vehicle Position (GNSS)", "category": "gps_motion",
     "status": "confirmed", "notes": "Lat/lon for geo-tagging; jd_atx lat offset -210."},
    {"pgn": 0xFFFF, "name": "JD GNSS quality multiplex", "category": "gps_motion",
     "status": "confirmed", "notes": "ATX 0x1C only. Sub-msg 0x51: byte3=sats used, byte7=fix quality (hypothesis). SA-gate; ignore DISP 0xF0."},
    {"pgn": 0xFEF5, "name": "Vehicle Direction / Heading", "category": "gps_motion",
     "status": "not_on_ib1", "notes": "Not seen on X119 implement tap; heading from FEE8."},
    {"pgn": 0x1F802, "name": "SOG/COG Rapid Update", "category": "gps_motion",
     "status": "not_on_ib1", "notes": "Not seen on X119; may exist on VB1."},
    {"pgn": 0xF029, "name": "Gyro / Yaw Rate (SSI2)", "category": "gps_motion",
     "status": "not_on_ib1", "notes": "Not on X119; derive yaw from FEE8 heading delta."},
    {"pgn": 0xFECA, "name": "DM1 Active DTCs", "category": "gps_motion",
     "status": "confirmed", "notes": "Diagnostic context when spray faults (pressure, flow)."},
    # --- Rate / section / TC ---
    {"pgn": 0xCB00, "name": "TC Process Data / Section Control", "category": "rate_section",
     "status": "confirmed", "notes": "DDI 141/157/158, section bitmap. Includes SR1 work msgs PF=0xCB."},
    {"pgn": 0x00A0, "name": "PGN 160 Process Data (DDI)", "category": "rate_section",
     "status": "confirmed", "notes": "PF 0xA0. DDI 157 target rate, DDI 158 applied feedback."},
    {"pgn": 0xE000, "name": "TC-GEO Process Data", "category": "rate_section",
     "status": "confirmed", "notes": "DDI 0x004F prescription zones."},
    {"pgn": 0xEF00, "name": "JD/GRC Proprietary Process Data", "category": "spray_proprietary",
     "status": "confirmed", "notes": "GRC rate/master/sections on Goldacres SA 0xCC; probe SRC/GWC on 616R."},
    {"pgn": 0xEA00, "name": "Request PGN", "category": "rate_section",
     "status": "confirmed", "notes": "Address claim / DDOP requests — pairing context only."},
    {"pgn": 0xEE00, "name": "Address Claimed", "category": "rate_section",
     "status": "confirmed", "notes": "Roster discovery for spray nodes."},
    # --- Flow / pressure (standard + node catch-all via SPRAY_WATCH_SAS) ---
    {"pgn": 0xFEEF, "name": "Engine Fluid Level / Pressure", "category": "flow_pressure",
     "status": "likely", "notes": "Auxiliary fluid metrics on some platforms."},
    {"pgn": 0xFE90, "name": "Direct Lamp Status", "category": "flow_pressure",
     "status": "hypothesis", "notes": "Low-pressure / tank warnings may correlate."},
    # --- Boom height ---
    {"pgn": 0xE700, "name": "Proprietary E700 family", "category": "spray_proprietary",
     "status": "likely", "notes": "Dominant from SA 0xBA; identify on Diagnostics Center."},
    {"pgn": 0xFF00, "name": "Proprietary A (BoomTrac candidate)", "category": "boom_height",
     "status": "hypothesis", "notes": "Capture all from BHC 0x8A until PGN confirmed."},
]
_PGN_BY_HEX: Dict[int, dict] = {}
_PGN_BY_PF: Dict[int, dict] = {}  # PF 0xA0 for PGN 160
SPRAY_PGNS: Set[int] = set()
SPRAY_CATEGORIES: Tuple[str, ...] = (
    "gps_motion", "rate_section", "flow_pressure", "boom_height", "spray_proprietary",
)

for entry in PGN_CATALOG:
    pgn = entry["pgn"]
    SPRAY_PGNS.add(pgn)
    _PGN_BY_HEX[pgn] = entry
    pf = (pgn >> 8) & 0xFF if pgn < 0x10000 else (pgn >> 8) & 0xFF
    if pgn == 0x00A0:
        _PGN_BY_PF[0xA0] = entry


def pgn_info(pgn: int, pf: Optional[int] = None) -> dict:
    """Return catalog entry or a generic bucket for unknown PGNs."""
    if pgn in _PGN_BY_HEX:
        return _PGN_BY_HEX[pgn]
    if pf is not None and pf in _PGN_BY_PF:
        return _PGN_BY_PF[pf]
    return {
        "pgn": pgn,
        "name": f"PGN 0x{pgn:04X}",
        "category": "spray_proprietary",
        "status": "unknown",
        "notes": "Observed on wire; add to catalog after decode.",
    }


def frame_in_spray_library(pf: int, sa: int, pgn: int) -> bool:
    """True if this frame belongs in the spray-focused monitor / recorder."""
    if pgn in SPRAY_PGNS:
        return True
    if pf == 0xA0:  # PGN 160 DDI (rate / flow feedback)
        return True
    if pf == 0xCB:   # TC process + SR1-style work messages
        return True
    if sa in SPRAY_WATCH_SAS:
        return True
    return False


def library_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "library", "spray_pgn_library.json")


def export_library_json(path: Optional[str] = None) -> str:
    path = path or library_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {
        "version": 1,
        "description": "Spray-focused CAN PGN catalog for PUFworks sniff/recorder/monitor.",
        "categories": list(SPRAY_CATEGORIES),
        "watch_sas": [f"0x{sa:02X}" for sa in sorted(SPRAY_WATCH_SAS)],
        "entries": PGN_CATALOG,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return path


# Write JSON on first import if missing (keeps bench-ui Vite import in sync).
if not os.path.exists(library_path()):
    export_library_json()
