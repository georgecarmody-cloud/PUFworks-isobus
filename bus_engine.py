# PUFworks ISOBUS Bus Engine
# Extracted from PUFVision monolith engine.py (tag v1-monolith-baseline) per BOUNDARY.md Phase 1.
#
# BUS-ONLY: no camera, no OpenCV, no YOLO. Section intent arrives as
# SectionBitmapV1 JSON lines ("VISION_BITMAP:{...}") from PUFworks-vision or a
# bench harness, and is staleness-gated (>300 ms -> sections closed, demote).
#
# The Control Authority ladder, interlocks, watchdogs, sprayer profiles, VT
# handshake, TC announce, recorder, and all TX gating are ported verbatim from
# the monolith ("move first, refactor second").
#
# Wire protocol (stdin -> engine):
#   - ControlCommandV1 line set, legacy colon form (e.g. SET_CONTROL_AUTHORITY:SHADOW)
#   - VISION_BITMAP:{SectionBitmapV1 JSON}  (10-20 Hz fixed rate from vision)
# Engine -> stdout:
#   - TELEMETRY:{TelemetryV1 JSON} at ~10 Hz
#   - CAN_RX:{...} raw frame stream, [ISOBUS_LOG] events

import sys
import json
import time
import threading
import os
from datetime import datetime

try:
    import can
    HAS_CAN = True
except ImportError:
    HAS_CAN = False
    print("Warning: python-can not found. Running without CAN bus support.", flush=True)

try:
    import serial
    HAS_SERIAL = True
except ImportError:
    HAS_SERIAL = False
    print("Warning: pyserial not found. Serial/slcan COM ports will be disabled.", flush=True)

from greenseeker_emitter import GreenSeekerEmitter

# Contract constants (mirror of PUFworks-contracts; keep in sync).
SECTION_BITMAP_STALE_MS = 300
UI_HEARTBEAT_TIMEOUT_S = 3.0
CAN_RX_TIMEOUT_S = 2.0

DEPRECATED_COMMANDS = ("NOZZLE_CMD", "SET_ENGINE_SIDE_SECTIONS", "SET_PRESCRIPTION")


class ISOBUSController:
    # Sprayer profile constants — controls CAN behaviour, section command format, and rate pathway
    PROFILE_GOLDACRES_GRC = "goldacres_grc"   # G5 Universal + GRC.001 — Section on/off is primary, rate fixed
    PROFILE_JD_616R = "jd_616r"               # 4600 CommandCenter V2 + ExactApply — TC-GEO rate source primary
    PROFILE_GENERIC = "generic"               # Unknown/generic ISOBUS implement

    def __init__(self, interface='none', bitrate=250000):
        self.interface = interface
        self.bitrate = bitrate
        self.bus = None
        self.is_running = False
        self.can_status = "uninitialized"  # "uninitialized", "connecting", "connected", "error"
        self.can_error_msg = ""
        self.source_address = 0x80  # Default to 0x80 (highly compatible standard ISOBUS Working Set address)
        # Known John Deere source addresses to never claim — colliding with these would knock a
        # genuine controller off the bus. Confirmed from JD See & Spray 616R Service ADVISOR
        # diagnostics (GWC.001 | 0x94 | Implement) plus the documented sprayer controller roster.
        #   0x94 = GWC Gateway Controller (See & Spray)   0x17/0xE1 = SR1/SRC Spray Rate Controller
        #   0x68/0xD4 = MNA/MNC ExactApply nozzles        0xCD/0x69 = MNC Nozzle Central Gateway
        #   0x8A = BH1/BHC Boom Height                     0x1C = ATX AutoTrac GPS
        #   0x26/0xF0 = Gen 4/5 Cab Display / Terminal     0x00 = Engine ECU
        #   0xCC = GRC.001 GreenStar Rate Controller (Goldacres) — in dynamic pool 0x80-0xF7;
        #          we send TO 0xCC as destination but must never claim it as our SA.
        self.jd_reserved_addresses = {
            0x94, 0x17, 0xE1, 0x68, 0xD4, 0xCD, 0x69, 0x8A, 0x1C, 0x26, 0xF0, 0x00, 0xCC,
        }
        # Conforming ISO 11783-5 NAME: Industry Group 2 (Agricultural & Forestry),
        # Device Class 7 (Sensor System, bits 49-55), Device Class Instance 0 (bits 56-59),
        # Function 128/0x80 (Smart Sensor & Rate Provider), Arbitrary-Address-Capable,
        # Manufacturer 1407 (Open-Agriculture), Identity 1234.
        self.name_payload = [0xD2, 0x04, 0xE0, 0xAF, 0x00, 0x80, 0x0E, 0xA0]
        self.address_claimed = False
        self.section_bitmap = 0
        self.speed_kmh = 0.0  # ISOBUS Wheel-based speed (PGN 65265 / FEF1)
        self._fef1_speed_seen = False
        self.is_flushing = False
        self.saved_speed_kmh = 0.0
        self.last_wsm_time = 0.0
        self.listen_thread = None
        self.heartbeat_thread = None
        self.cooperative_mode = True  # Logical AND with John Deere section commands
        self.jd_commanded_sections = 0xFFFF  # Section bits commanded ON by JD display. Default: all ON
        self.jd_headland_active = False

        # --- Sprayer Profile ---
        self.sprayer_profile = self.PROFILE_GENERIC
        self.tc_server_address = 0x06  # Standard ISOBUS TC server SA. JD Gen 4 typically 0x06 or 0x26.
        self.last_tc_client_announce_time = 0.0

        # --- ISOBUS Diagnostics & Liquid Rate Controller Connections ---
        self.isobus_log_path = "isobus_diagnostics.log"
        self.jdrc_address = 0xCC  # Default GRC.001 SA (dynamic auto-learning fallback)
        self.last_rx_time = time.time()
        self.last_vt_rx_time = 0.0
        self.last_ddi158_rx_time = 0.0
        self.is_connected = False

        # --- Goldacres GRC.001 PGN 0xEF00 decode (field-validated gatest_11/12) ---
        self.grc_ef00_rate_l_ha = 0.0
        self.grc_master_on = None
        self.grc_ef00_section_bitmap = 0xFFFE
        self.grc_ef00_coarse_bitmap = 0xFFEE
        self.grc_section_enabled = {name: True for name in ("L1", "L2", "C", "R2", "R1")}
        self.last_grc_ef00_rx_time = 0.0
        self._grc_last_toggle_element = None
        self._grc_last_toggle_time = 0.0
        self.GRC_TOGGLE_DEBOUNCE_S = 2.0
        self.GRC_SECTION_BIT = {"L1": 1, "L2": 2, "C": 3, "R2": 4, "R1": 5}
        self.GRC_ELEMENT_TO_SECTION = {
            0x1F: "L1", 0x2C: "L1",
            0x1E: "L2", 0x2B: "L2",
            0x1C: "C",  0x29: "C",  0x0F: "C",
            0x18: "R2", 0x25: "R2",
            0x10: "R1", 0x1D: "R1", 0x03: "R1",
        }

        # --- Control Authority Ladder & Safety Interlocks ---
        self.AUTHORITY_ORDER = {
            "OBSERVE": 0, "ANNOUNCE": 1, "SHADOW": 2,
            "RATE_ONLY": 3, "SECTION": 4, "FULL": 5,
        }
        self.control_authority = "OBSERVE"
        self.armed = False
        self.speed_interlock = True
        self.min_ground_speed_kmh = 0.5
        self.ui_watchdog_enabled = True
        self.ui_watchdog_timeout = UI_HEARTBEAT_TIMEOUT_S
        self.last_ui_heartbeat = 0.0
        self.rx_watchdog_timeout = CAN_RX_TIMEOUT_S
        self.last_demote_reason = ""
        self.interlock_status = {"speed": True, "rx": True, "ui": True, "vision": True}

        # --- OBSERVE / SHADOW session recorder ---
        self._record_lock = threading.Lock()
        self.record_active = False
        self.record_session_id = ""
        self.record_dir = ""
        self.record_frame_count = 0
        self.record_shadow_count = 0
        self.record_started_at = 0.0
        self.last_shadow_log_time = 0.0
        self.sniffed_grc_ddi141 = None
        self.sniffed_grc_ddi157 = None
        self.recordings_root = os.path.normpath(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "recordings"))

        # --- External vision section feed (SectionBitmapV1, replaces monolith camera coupling) ---
        # Vision publishes at fixed 10-20 Hz even with zero detections; staleness
        # >SECTION_BITMAP_STALE_MS means the vision process is dead -> sections closed.
        self.vision_bitmap = 0
        self.vision_seq = -1
        self.vision_last_rx = 0.0     # local monotonic-ish wall time of last fresh message
        self.vision_seen = False      # has a vision feed ever connected this session
        self.vision_source = ""
        self.num_boom_sections = 10
        # Manual bench test vector (SET_SECTION_BITMAP). Only drives output while
        # no live vision feed has been seen (or after explicit clear).
        self.manual_section_bitmap = None

        self.target_rate_l_ha = 0.0   # Rate setpoint. Stays 0 until RateCommandV1 exists (BOUNDARY 4.7).
        self.greenness_index = 0.0    # Retained for GreenSeeker NDVI provider; fed by future contract.
        self.actual_flow_rate_l_min = 0.0
        self.ddi_157_val = 0
        self.ddi_158_val = 0

        # Count of frames actually put on the wire per TX category (post-gate).
        # Proves what cleared _tx_allowed()/interlocks — the bench asserts that
        # 'section' stays flat in SHADOW and only grows at SECTION+ when ARMed.
        self.tx_counts = {"claim": 0, "presence": 0, "rate": 0, "section": 0}

        try:
            with open(self.isobus_log_path, "a") as f:
                f.write(f"\n--- PUFworks ISOBUS Logging Started {datetime.now()} ---\n")
        except Exception:
            pass

        # --- ISOBUS Virtual Terminal (UT/VT) Handshake & Transport Protocol States ---
        self.vt_address = 0x26
        self.vt_handshake_state = "DISCONNECTED"
        self.last_vt_status_time = 0.0
        self.vt_version = 0
        self.vt_softkeys = 0
        self.vt_colors = 0

        self.tp_tx_active = False
        self.tp_tx_total_bytes = 0
        self.tp_tx_num_packets = 0
        self.tp_tx_next_packet = 1
        self.tp_tx_packets_to_send = 0
        self.tp_tx_pgn = 0x00E600
        self.last_state_transition_time = 0.0

        # Conforming minimal VT Object Pool (ISO 11783-6). Load compiled .iop if present.
        self.object_pool_data = bytearray()
        iop_paths = ['pufworks.iop', 'pufvision.iop', 'assets/pufvision.iop']
        loaded_iop = False
        for p in iop_paths:
            if os.path.exists(p):
                try:
                    with open(p, 'rb') as f:
                        self.object_pool_data = bytearray(f.read())
                    print(f"[ISOBUS] Loaded Object Pool from file: {p} ({len(self.object_pool_data)} bytes)", flush=True)
                    loaded_iop = True
                    break
                except Exception as e:
                    print(f"[ISOBUS] Error reading {p}: {e}", flush=True)

        if not loaded_iop:
            # Fully compliant standard hardcoded Object Pool fallback (WS Master ID = 0x0000)
            self.object_pool_data = bytearray([
                0x00, 0x00, 0x00, 0x07, 0x01, 0x01, 0x01, 0x00, 0x01, 0x02, 0x00,
                0x01, 0x00, 0x01, 0x07, 0x02, 0x00, 0x00, 0x00, 0x01, 0x03, 0x00,
                0x0A, 0x00, 0x0A, 0x00,
                0x02, 0x00, 0x04, 0x07, 0x00, 0x00, 0x00,
                0x03, 0x00, 0x0B, 0x64, 0x00, 0x10, 0x00, 0x07, 0x00, 0x00, 0x16,
                0x50, 0x55, 0x46, 0x56, 0x69, 0x73, 0x69, 0x6F,
                0x6E, 0x20, 0x28, 0x4C, 0x6F, 0x67, 0x69, 0x63,
                0x20, 0x4D, 0x6F, 0x64, 0x65, 0x29,
                0x00, 0x00
            ])
            print(f"[ISOBUS] Initialized compliant fallback Object Pool ({len(self.object_pool_data)} bytes)", flush=True)

        self.active_data_mask_id = 1
        if len(self.object_pool_data) > 7 and self.object_pool_data[2] == 0x00:
            self.active_data_mask_id = self.object_pool_data[6] | (self.object_pool_data[7] << 8)
            print(f"[ISOBUS] Dynamically resolved Active Data Mask ID: {self.active_data_mask_id}", flush=True)

        self.tp_tx_buffer = bytearray()

    # --- Logging --------------------------------------------------------------
    def log_isobus_event(self, message):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        log_line = f"[{timestamp}] {message}"
        print(f"[ISOBUS_LOG] {message}", flush=True)
        try:
            with open(self.isobus_log_path, "a") as f:
                f.write(log_line + "\n")
        except Exception:
            pass

    # --- J1939 helpers ----------------------------------------------------------
    def _msg_j1939_meta(self, arbitration_id):
        pf = (arbitration_id >> 16) & 0xFF
        ps = (arbitration_id >> 8) & 0xFF
        sa = arbitration_id & 0xFF
        if pf < 240:
            pgn = pf << 8
            da = ps
        else:
            pgn = (pf << 8) | ps
            da = 0xFF
        return pf, ps, sa, pgn, da

    # --- Recorder ---------------------------------------------------------------
    def _record_watch_sas(self):
        return {
            self.jdrc_address, self.tc_server_address, 0x06, 0x26, 0xF7,
            self.vt_address, self.source_address,
        }

    def _record_should_capture(self, pf, sa, pgn):
        if pf in (0xA0, 0xCB):
            return True
        if sa in self._record_watch_sas():
            return True
        if pgn in (
            0xCB00, 0xEA00, 0xEE00, 0xFE0D, 0xFEF1, 0xFEE8, 0xFEF3,
            0xFECA, 0xE700, 0xEF00, 65267, 59136,
        ):
            return True
        return False

    def _grc_is_alive(self):
        now = time.time()
        if self.last_grc_ef00_rx_time > 0 and (now - self.last_grc_ef00_rx_time) <= self.rx_watchdog_timeout:
            return True
        if self.last_ddi158_rx_time > 0 and (now - self.last_ddi158_rx_time) <= self.rx_watchdog_timeout:
            return True
        return False

    def _grc_rebuild_section_bitmap(self):
        """Rebuild per-section AND-gate mask and bus-native coarse bitmap."""
        bmp = 0xFFFE  # bit0 unused on live Goldacres bus
        for name, bit in self.GRC_SECTION_BIT.items():
            if self.grc_section_enabled.get(name, True):
                bmp |= (1 << bit)
            else:
                bmp &= ~(1 << bit)
        self.grc_ef00_section_bitmap = bmp & 0xFFFF

        if self.grc_master_on is False:
            self.grc_ef00_coarse_bitmap = 0xFFEE
        elif all(self.grc_section_enabled.get(n, True) for n in self.GRC_SECTION_BIT):
            self.grc_ef00_coarse_bitmap = 0xFFF6
        else:
            self.grc_ef00_coarse_bitmap = 0xFFE6

        if self.sprayer_profile == self.PROFILE_GOLDACRES_GRC and self._grc_is_alive():
            self.jd_commanded_sections = self.grc_ef00_section_bitmap
        self.sniffed_grc_ddi141 = self.grc_ef00_section_bitmap

    def _grc_set_section_enabled(self, name, enabled):
        if name in self.grc_section_enabled:
            self.grc_section_enabled[name] = bool(enabled)

    def _grc_clear_toggle_debounce(self):
        self._grc_last_toggle_element = None
        self._grc_last_toggle_time = 0.0

    def _grc_section_from_element(self, element_id):
        name = self.GRC_ELEMENT_TO_SECTION.get(element_id)
        if name:
            return name
        return self.GRC_ELEMENT_TO_SECTION.get(element_id + 0x0D)

    def _grc_toggle_section_debounced(self, element_id):
        """051XX manual section commands are toggles; GRC repeats each burst ~8x."""
        name = self._grc_section_from_element(element_id)
        if not name:
            return
        now = time.time()
        if (
            element_id == self._grc_last_toggle_element
            and (now - self._grc_last_toggle_time) <= self.GRC_TOGGLE_DEBOUNCE_S
        ):
            return
        self._grc_last_toggle_element = element_id
        self._grc_last_toggle_time = now
        self.grc_section_enabled[name] = not self.grc_section_enabled.get(name, True)

    def _parse_grc_ef00(self, sa, pgn, data):
        """Decode GRC.001 proprietary process data on PGN 0xEF00 (Goldacres)."""
        if pgn != 0xEF00 or sa != self.jdrc_address or len(data) < 4:
            return
        self.last_grc_ef00_rx_time = time.time()
        if self.jdrc_address != sa:
            self.jdrc_address = sa

        now = time.time()

        # Rate feedback: 4F0101 + u16 rate / 10 -> L/ha
        if len(data) >= 5 and data[0] == 0x4F and data[1] == 0x01 and data[2] == 0x01:
            rate_raw = data[3] | (data[4] << 8)
            self.grc_ef00_rate_l_ha = rate_raw / 10.0
            self.ddi_158_val = rate_raw
            self.actual_flow_rate_l_min = self.grc_ef00_rate_l_ha
            self.last_ddi158_rx_time = now

        # Master state: 4F0601FF00 = OFF, 4F0601FF01 = ON
        elif len(data) >= 6 and data[0] == 0x4F and data[1] == 0x06 and data[2] == 0x01:
            if data[3] == 0x00 and data[4] == 0xFF and data[5] == 0x00:
                self.grc_master_on = False
            elif data[3] == 0x01 and data[4] == 0xFF and data[5] == 0x01:
                self.grc_master_on = True

        # Manual timer / accessory exit: 4F0B020200050000 (gatest_12 end-of-session)
        elif len(data) >= 7 and data[0] == 0x4F and data[1] == 0x0B and data[2] == 0x02 \
                and data[3] == 0x02 and data[4] == 0x00 and data[5] == 0x05:
            for name in self.GRC_SECTION_BIT:
                self._grc_set_section_enabled(name, False)
            self._grc_clear_toggle_debounce()

        # Manual-mode all-on reset: 4F0B020201050000
        elif len(data) >= 8 and data[0] == 0x4F and data[1] == 0x0B and data[2] == 0x02 \
                and data[3] == 0x02 and data[4] == 0x01 and data[5] == 0x05 and data[6] == 0x00:
            for name in self.GRC_SECTION_BIT:
                self._grc_set_section_enabled(name, True)
            self._grc_clear_toggle_debounce()

        # Manual-mode per-section toggle: 4F0B02020105XX00
        elif len(data) >= 8 and data[0] == 0x4F and data[1] == 0x0B and data[2] == 0x02 \
                and data[3] == 0x02 and data[4] == 0x01 and data[5] == 0x05:
            self._grc_toggle_section_debounced(data[6])

        # Legacy auto-mode side/num (ga_test5 R2): 4F0B0201020201XX
        elif len(data) >= 8 and data[0] == 0x4F and data[1] == 0x0B and data[2] == 0x02 \
                and data[3] == 0x01 and data[4] in (1, 2) and data[5] in range(1, 16):
            if data[4] == 2 and data[5] == 2:
                self._grc_set_section_enabled("R2", data[7] == 0x02)

        self._grc_rebuild_section_bitmap()

    def _record_update_sniffed_ddi(self, sa, pf, ps, data):
        if len(data) < 6:
            return
        ddi = data[0] | (data[1] << 8)
        val = data[2] | (data[3] << 8) | (data[4] << 16) | (data[5] << 24)
        if pf == 0xA0 and sa == self.jdrc_address:
            if ddi == 0x008D:
                self.sniffed_grc_ddi141 = val & 0xFFFF
            elif ddi == 0x009D:
                self.sniffed_grc_ddi157 = val
        if pf == 0xCB and (sa == self.jdrc_address or ps == self.jdrc_address):
            if ddi == 0x008D:
                self.sniffed_grc_ddi141 = val & 0xFFFF

    def start_record_session(self, label=""):
        if self.record_active:
            self.log_isobus_event("Record session already active — stop it before starting a new one.")
            return False
        if self._authority_level() > self.AUTHORITY_ORDER["SHADOW"]:
            self.log_isobus_event(
                f"Record session refused at authority {self.control_authority} — lower to SHADOW or OBSERVE first."
            )
            return False
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_label = "".join(c if c.isalnum() or c in "-_" else "_" for c in label.strip())[:32]
        self.record_session_id = f"{stamp}_{safe_label}" if safe_label else stamp
        self.record_dir = os.path.join(self.recordings_root, self.record_session_id)
        try:
            os.makedirs(self.record_dir, exist_ok=True)
            with open(os.path.join(self.record_dir, "frames.csv"), "w") as f:
                f.write("timestamp_ms,dir,can_id,sa_hex,sa_dec,pgn_hex,da_hex,dlc,data_hex\n")
            with open(os.path.join(self.record_dir, "shadow_channels.csv"), "w") as f:
                f.write(
                    "timestamp,speed_kmh,host_commanded_bitmap,sniffed_grc_ddi141,"
                    "ddi_158_val,vision_bitmap,shadow_and_bitmap,control_authority,"
                    "grc_alive,record_frame_count,grc_ef00_rate_l_ha,grc_master_on,"
                    "grc_ef00_section_bitmap,grc_ef00_coarse_bitmap,"
                    "grc_L1,grc_L2,grc_C,grc_R2,grc_R1\n"
                )
            meta = {
                "session_id": self.record_session_id,
                "started_at": datetime.now().isoformat(),
                "label": label,
                "sprayer_profile": self.sprayer_profile,
                "control_authority": self.control_authority,
                "jdrc_address": hex(self.jdrc_address),
                "tc_server_address": hex(self.tc_server_address),
                "num_boom_sections": self.num_boom_sections,
                "note": "Tier-1 filtered CAN frames + Tier-2 10Hz shadow channels for Goldacres design capture.",
            }
            with open(os.path.join(self.record_dir, "session_meta.json"), "w") as f:
                json.dump(meta, f, indent=2)
        except Exception as e:
            self.log_isobus_event(f"Record session start failed: {e}")
            return False
        self.record_active = True
        self.record_frame_count = 0
        self.record_shadow_count = 0
        self.record_started_at = time.time()
        self.last_shadow_log_time = 0.0
        self.sniffed_grc_ddi141 = None
        self.sniffed_grc_ddi157 = None
        self.log_isobus_event(f"Record session STARTED: {self.record_session_id} -> {self.record_dir}")
        return True

    def stop_record_session(self):
        if not self.record_active:
            return False
        self.record_active = False
        elapsed = time.time() - self.record_started_at
        try:
            meta_path = os.path.join(self.record_dir, "session_meta.json")
            if os.path.exists(meta_path):
                with open(meta_path, "r") as f:
                    meta = json.load(f)
                meta["stopped_at"] = datetime.now().isoformat()
                meta["duration_s"] = round(elapsed, 1)
                meta["frame_count"] = self.record_frame_count
                meta["shadow_row_count"] = self.record_shadow_count
                meta["control_authority_at_stop"] = self.control_authority
                with open(meta_path, "w") as f:
                    json.dump(meta, f, indent=2)
        except Exception as e:
            self.log_isobus_event(f"Record session meta update failed: {e}")
        self.log_isobus_event(
            f"Record session STOPPED: {self.record_session_id} "
            f"({self.record_frame_count} frames, {self.record_shadow_count} shadow rows, {elapsed:.1f}s)"
        )
        return True

    def record_frame(self, direction, msg):
        if not self.record_active or msg is None:
            return
        pf, ps, sa, pgn, da = self._msg_j1939_meta(msg.arbitration_id)
        if not self._record_should_capture(pf, sa, pgn):
            return
        self._parse_grc_ef00(sa, pgn, msg.data)
        self._record_update_sniffed_ddi(sa, pf, ps, msg.data)
        row = (
            f"{int(time.time() * 1000)},{direction},0x{msg.arbitration_id:08X},"
            f"0x{sa:02X},{sa},0x{pgn:04X},0x{da:02X},{msg.dlc},{msg.data.hex().upper()}\n"
        )
        try:
            with self._record_lock:
                with open(os.path.join(self.record_dir, "frames.csv"), "a") as f:
                    f.write(row)
                self.record_frame_count += 1
        except Exception:
            pass

    def log_record_shadow_row(self, shadow_and_bitmap):
        if not self.record_active:
            return
        now = time.time()
        if self.last_shadow_log_time and (now - self.last_shadow_log_time) < 0.1:
            return
        self.last_shadow_log_time = now
        grc_alive = self._grc_is_alive()
        ddi141 = self.sniffed_grc_ddi141 if self.sniffed_grc_ddi141 is not None else ""
        master = "" if self.grc_master_on is None else (1 if self.grc_master_on else 0)
        sec = self.grc_section_enabled
        row = (
            f"{now:.3f},{self.speed_kmh:.2f},{self.jd_commanded_sections},"
            f"{ddi141},{self.ddi_158_val},{self.section_bitmap},"
            f"{shadow_and_bitmap},{self.control_authority},"
            f"{1 if grc_alive else 0},{self.record_frame_count},"
            f"{self.grc_ef00_rate_l_ha:.1f},{master},{self.grc_ef00_section_bitmap},"
            f"{self.grc_ef00_coarse_bitmap},"
            f"{1 if sec.get('L1', True) else 0},{1 if sec.get('L2', True) else 0},"
            f"{1 if sec.get('C', True) else 0},{1 if sec.get('R2', True) else 0},"
            f"{1 if sec.get('R1', True) else 0}\n"
        )
        try:
            with self._record_lock:
                with open(os.path.join(self.record_dir, "shadow_channels.csv"), "a") as f:
                    f.write(row)
                self.record_shadow_count += 1
        except Exception:
            pass

    # --- Control Authority & Interlock Gating ---------------------------------
    def _authority_level(self):
        return self.AUTHORITY_ORDER.get(self.control_authority, 0)

    def set_manual_section_bitmap(self, bitmap):
        """Bench test vector. Overridden whenever a fresh vision feed is present."""
        self.manual_section_bitmap = int(bitmap) & 0xFFFF
        if self._vision_fresh():
            self.log_isobus_event(
                f"Manual section bitmap {hex(self.manual_section_bitmap)} stored, "
                "but a live vision feed is fresh and takes priority."
            )
        else:
            self.log_isobus_event(f"Manual section bitmap -> {hex(self.manual_section_bitmap)} (bench vector)")
        return True

    def set_control_authority(self, rung):
        rung = str(rung).upper()
        if rung not in self.AUTHORITY_ORDER:
            self.log_isobus_event(f"Rejected unknown control authority '{rung}'")
            return False
        prev = self.control_authority
        self.control_authority = rung
        # Dropping below RATE_ONLY implicitly disarms actuation.
        if self.AUTHORITY_ORDER[rung] < self.AUTHORITY_ORDER["RATE_ONLY"]:
            self.armed = False
        self.log_isobus_event(f"Control authority {prev} -> {rung} (armed={self.armed})")
        if self.record_active and self.AUTHORITY_ORDER[rung] > self.AUTHORITY_ORDER["SHADOW"]:
            self.log_isobus_event("Record session auto-stopped — authority rose above SHADOW.")
            self.stop_record_session()
        return True

    def set_armed(self, armed):
        armed = bool(armed)
        if armed and self._authority_level() < self.AUTHORITY_ORDER["RATE_ONLY"]:
            self.log_isobus_event("ARM refused: raise authority to RATE_ONLY or higher first")
            return False
        self.armed = armed
        self.log_isobus_event(f"{'ARMED' if armed else 'DISARMED'} at authority {self.control_authority}")
        return True

    def _vision_fresh(self):
        """A vision feed is 'fresh' if a SectionBitmapV1 arrived within the staleness window."""
        return self.vision_seen and \
            (time.time() - self.vision_last_rx) * 1000.0 <= SECTION_BITMAP_STALE_MS

    def _interlocks_ok(self):
        """Refresh and return whether actuation interlocks currently permit output."""
        now = time.time()
        speed_ok = (not self.speed_interlock) or (self.speed_kmh >= self.min_ground_speed_kmh)
        rx_ok = (not (HAS_CAN and self.bus is not None)) or \
                (now - self.last_rx_time <= self.rx_watchdog_timeout) or (self.last_rx_time == 0.0)
        ui_ok = (not self.ui_watchdog_enabled) or self.last_ui_heartbeat == 0.0 or \
                (now - self.last_ui_heartbeat <= self.ui_watchdog_timeout)
        # Vision interlock is only meaningful once a feed has been seen this session;
        # pure-bench operation (manual vectors only) is not penalised.
        vision_ok = (not self.vision_seen) or self._vision_fresh()
        self.interlock_status = {"speed": speed_ok, "rx": rx_ok, "ui": ui_ok, "vision": vision_ok}
        return speed_ok and rx_ok and ui_ok and vision_ok

    def _profile_sends_rate(self):
        """Whether the active sprayer profile transmits DDI 157 (PGN 160) rate."""
        return self.sprayer_profile != self.PROFILE_GOLDACRES_GRC

    def _tx_allowed(self, kind):
        """Authority/arm gate for a transmit category.

        kind: 'claim' | 'presence' | 'rate' | 'section'
        Returns True only if the current rung (and arm state, for actuation)
        permits this category. Interlocks are evaluated separately so callers can
        choose to force-safe (send zeros) rather than go silent.
        """
        level = self._authority_level()
        if kind in ("claim", "presence"):
            return level >= self.AUTHORITY_ORDER["ANNOUNCE"]
        if kind == "rate":
            return self._profile_sends_rate() and self.armed and level >= self.AUTHORITY_ORDER["RATE_ONLY"]
        if kind == "section":
            return self.armed and level >= self.AUTHORITY_ORDER["SECTION"]
        return False

    def ui_heartbeat(self):
        self.last_ui_heartbeat = time.time()

    def _service_watchdogs(self):
        """Auto-demote to SHADOW on a genuine fault while armed.

        speed==0 is normal operation (turns, refills) — it force-safes the outputs
        but does NOT demote. Loss of bus comms, the UI control link, or the vision
        feed (real faults) trigger a demote.
        """
        # Refresh interlock_status every tick (pure computation, no TX) so
        # telemetry reports true interlock health even while disarmed/SHADOW.
        self._interlocks_ok()
        if not self.armed:
            return
        fault = [k for k in ("rx", "ui", "vision") if not self.interlock_status.get(k, True)]
        if fault:
            self.last_demote_reason = f"{', '.join(fault)} lost"
            self.log_isobus_event(f"WATCHDOG auto-demote to SHADOW ({self.last_demote_reason})")
            self.armed = False
            self.control_authority = "SHADOW"

    # --- External vision feed ---------------------------------------------------
    def ingest_vision_bitmap(self, msg):
        """Consume a SectionBitmapV1 dict from the vision process (or bench harness)."""
        try:
            if msg.get("schema") != "SectionBitmapV1":
                self.log_isobus_event(f"VISION_BITMAP rejected: schema={msg.get('schema')!r}")
                return False
            section_count = int(msg["section_count"])
            bitmap = int(str(msg["bitmap"]), 16)
            if bitmap >= (1 << section_count):
                self.log_isobus_event(
                    f"VISION_BITMAP rejected: bits above section_count={section_count} in {msg['bitmap']}")
                return False
            seq = int(msg.get("seq", 0))
            if self.vision_seen and seq <= self.vision_seq:
                # Log gaps/repeats but only staleness triggers fail-safe.
                self.log_isobus_event(f"VISION_BITMAP seq regression: {self.vision_seq} -> {seq}")
            self.vision_seq = seq
            self.vision_bitmap = bitmap
            self.vision_source = str(msg.get("source", ""))
            self.vision_last_rx = time.time()
            if not self.vision_seen:
                self.vision_seen = True
                self.num_boom_sections = section_count
                self.log_isobus_event(
                    f"Vision feed connected: source={self.vision_source} sections={section_count}")
            return True
        except (KeyError, ValueError, TypeError) as e:
            self.log_isobus_event(f"VISION_BITMAP parse error: {e}")
            return False

    def update_sections_from_inputs(self):
        """Resolve self.section_bitmap from the external inputs.

        Priority: fresh vision feed > manual bench vector. A stale vision feed
        (publisher death) forces all sections CLOSED — never falls back to the
        manual vector mid-session, and never holds the last bitmap.
        """
        if self.vision_seen:
            self.section_bitmap = self.vision_bitmap if self._vision_fresh() else 0
        elif self.manual_section_bitmap is not None:
            self.section_bitmap = self.manual_section_bitmap

    def vision_weeds_present(self):
        """True if the fresh vision bitmap has any section active. Drives the
        GreenSeeker whole-boom blanking path (616R) — same SectionBitmapV1
        contract, no separate vision->GS channel (BOUNDARY 3.2)."""
        return self._vision_fresh() and self.vision_bitmap != 0

    # --- TX paths (ported verbatim; all gated by _tx_allowed) --------------------
    def send_ddi_157(self):
        if not HAS_CAN or self.bus is None:
            return
        # Goldacres GRC: section-only — Raven fast-close + GRC hold fixed Work Setup rate.
        if not self._profile_sends_rate():
            return
        if not self._tx_allowed("rate"):
            return

        # Interlock: if a safety interlock is tripped, actively command 0 L/ha
        # rather than holding the last rate.
        effective_rate = self.target_rate_l_ha if self._interlocks_ok() else 0.0
        self.ddi_157_val = int(effective_rate * 100)

        arbitration_id = (6 << 26) | (0xA0 << 16) | (self.jdrc_address << 8) | self.source_address
        ddi_bytes = [0x9D, 0x00]
        try:
            val_bytes = list(self.ddi_157_val.to_bytes(4, byteorder='little', signed=True))
            data = ddi_bytes + val_bytes + [0xFF, 0xFF]
            msg = can.Message(arbitration_id=arbitration_id, data=data, is_extended_id=True)
            self.bus.send(msg)
            self.tx_counts["rate"] += 1
            current_time = time.time()
            if not hasattr(self, 'last_ddi157_log_time') or current_time - self.last_ddi157_log_time >= 1.0 \
                    or getattr(self, 'last_logged_ddi157_val', -1) != self.ddi_157_val:
                self.last_ddi157_log_time = current_time
                self.last_logged_ddi157_val = self.ddi_157_val
                self.log_isobus_event(
                    f"TX PGN 160 (DDI 157): Sent Target Rate={self.target_rate_l_ha:.2f} L/ha "
                    f"(raw={self.ddi_157_val}) to JDRC ({hex(self.jdrc_address)})")
        except Exception as e:
            self.log_isobus_event(f"TX PGN 160 Error: failed to send DDI 157 to {hex(self.jdrc_address)}: {e}")

    def update_isobus_name(self, industry_group, func_code, ecu_instance, manuf_code, identity,
                           vehicle_system=7, device_class=0, function_instance=0):
        try:
            # Re-pack standard ISO 11783-5 NAME (8 bytes, little-endian).
            # `vehicle_system` carries the ISO Device Class (bits 49-55, default 7 = Sensor
            # System) and `device_class` carries the Device Class Instance (bits 56-59).
            name_val = 0
            name_val |= (identity & 0x1FFFFF)
            name_val |= ((manuf_code & 0x7FF) << 21)
            name_val |= ((ecu_instance & 0x7) << 32)
            name_val |= ((function_instance & 0x1F) << 35)
            name_val |= ((func_code & 0xFF) << 40)
            name_val |= ((vehicle_system & 0x7F) << 49)
            name_val |= ((device_class & 0x0F) << 56)
            name_val |= ((industry_group & 0x7) << 60)
            name_val |= (1 << 63)

            self.name_payload = list(name_val.to_bytes(8, byteorder='little'))
            print(f"[ISOBUS Name] Recalculated claimed NAME: {[hex(b) for b in self.name_payload]} "
                  f"with IG={industry_group}, Func={func_code}, VS={vehicle_system}, DevClass={device_class}, "
                  f"ECUInst={ecu_instance}, FuncInst={function_instance}, Manuf={manuf_code}, Id={identity}", flush=True)
            self.address_claimed = False
            self.perform_address_claim()
        except Exception as e:
            print(f"[ISOBUS Name] Error updating NAME payload: {e}", flush=True)

    def perform_address_claim(self):
        if not HAS_CAN or self.bus is None:
            self.vt_handshake_state = "CLAIMING_ADDRESS"
            self.last_state_transition_time = time.time()
            return

        # Authority gate: OBSERVE is a pure silent sniffer — never claim/announce.
        if not self._tx_allowed("claim"):
            return

        arbitration_id = (6 << 26) | (0xEEFF << 8) | self.source_address
        msg = can.Message(arbitration_id=arbitration_id, data=self.name_payload, is_extended_id=True)
        try:
            self.bus.send(msg)
            self.tx_counts["claim"] += 1
            self.log_isobus_event(f"TX PGN 60928: Sent Address Claim for SA {hex(self.source_address)}")
            self.address_claimed = True
            self.vt_handshake_state = "CLAIMING_ADDRESS"
            self.last_state_transition_time = time.time()
        except Exception as e:
            self.log_isobus_event(f"CAN TX ERROR (Address Claim): {e}")

    def process_incoming_address_claim(self, arbitration_id, data):
        pf = (arbitration_id >> 16) & 0xFF
        ps = (arbitration_id >> 8) & 0xFF
        if pf < 240:
            pgn = pf << 8
        else:
            pgn = (pf << 8) | ps
        sa = arbitration_id & 0xFF

        if pgn == 0xEE00 and sa == self.source_address:
            incoming_name = int.from_bytes(data, byteorder='little')
            our_name = int.from_bytes(self.name_payload, byteorder='little')

            if incoming_name < our_name:
                self.log_isobus_event(
                    f"ANOMALY: Address Conflict! Lost address {hex(self.source_address)} "
                    f"to higher priority Node ({hex(sa)}).")
                self.address_claimed = False
                # Cycle within the dynamic claim range 0x80-0xF7 (128 addresses), skipping
                # JD-reserved SAs; after 120 attempts send Cannot Claim (SA 0xFE).
                if not hasattr(self, '_address_claim_attempts'):
                    self._address_claim_attempts = 0
                self._address_claim_attempts += 1
                if self._address_claim_attempts >= 120:
                    self.log_isobus_event(
                        "Cannot Claim Address: all 120 dynamic addresses exhausted. "
                        "Broadcasting Cannot Claim (SA 0xFE) per J1939.")
                    cannot_claim_id = (6 << 26) | (0xEEFF << 8) | 0xFE
                    if HAS_CAN and self.bus is not None:
                        try:
                            self.bus.send(can.Message(arbitration_id=cannot_claim_id,
                                                      data=self.name_payload, is_extended_id=True))
                        except Exception:
                            pass
                    self._address_claim_attempts = 0
                    return
                current_offset = self.source_address - 0x80
                for _ in range(120):
                    current_offset = (current_offset + 1) % 120
                    candidate = 0x80 + current_offset
                    if candidate not in self.jd_reserved_addresses:
                        self.source_address = candidate
                        break
                self.log_isobus_event(f"Attempting to claim alternative address: {hex(self.source_address)}")
                self.perform_address_claim()
            else:
                self.log_isobus_event(
                    f"Address contention: Defending our address {hex(self.source_address)} "
                    f"against Node {hex(sa)}.")
                self.perform_address_claim()

    def send_get_vt_version(self):
        if not HAS_CAN or self.bus is None:
            return
        if not self._tx_allowed("presence"):
            return
        arbitration_id = (6 << 26) | (0xE6 << 16) | (self.vt_address << 8) | self.source_address
        data = [0xC0, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF]
        try:
            msg = can.Message(arbitration_id=arbitration_id, data=data, is_extended_id=True)
            self.bus.send(msg)
            print(f"[ISOBUS] Sent 'Get VT Version' (0xC0) Command to VT (SA {hex(self.vt_address)})", flush=True)
            self.vt_handshake_state = "GET_VT_VERSION_SENT"
            self.last_state_transition_time = time.time()
        except Exception as e:
            print(f"CAN TX ERROR (Get VT Version): {e}", flush=True)

    def send_get_vt_capabilities(self):
        if not HAS_CAN or self.bus is None:
            return
        if not self._tx_allowed("presence"):
            return
        arbitration_id = (6 << 26) | (0xE6 << 16) | (self.vt_address << 8) | self.source_address
        data = [0xC1, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF]
        try:
            msg = can.Message(arbitration_id=arbitration_id, data=data, is_extended_id=True)
            self.bus.send(msg)
            print(f"[ISOBUS] Sent 'Get VT Capabilities' (0xC1) Command to VT (SA {hex(self.vt_address)})", flush=True)
            self.vt_handshake_state = "GET_VT_CAPABILITIES_SENT"
            self.last_state_transition_time = time.time()
        except Exception as e:
            print(f"CAN TX ERROR (Get VT Capabilities): {e}", flush=True)

    def initiate_tp_object_pool(self):
        if not HAS_CAN or self.bus is None:
            return
        if not self._tx_allowed("presence"):
            return
        total_size = len(self.object_pool_data)
        num_packets = total_size // 7 + (1 if total_size % 7 != 0 else 0)

        self.tp_tx_total_bytes = total_size
        self.tp_tx_num_packets = num_packets
        self.tp_tx_next_packet = 1
        self.tp_tx_active = True

        arbitration_id = (6 << 26) | (0xEC << 16) | (self.vt_address << 8) | self.source_address
        rts_data = [
            0x10,
            total_size & 0xFF,
            (total_size >> 8) & 0xFF,
            num_packets,
            0xFF,
            0x00, 0xE6, 0x00,
        ]
        try:
            msg = can.Message(arbitration_id=arbitration_id, data=rts_data, is_extended_id=True)
            self.bus.send(msg)
            print(f"[ISOBUS] Sent J1939 TP.RTS for Object Pool upload. Size: {total_size} bytes, "
                  f"{num_packets} packets.", flush=True)
            self.vt_handshake_state = "TP_RTS_SENT"
            self.last_state_transition_time = time.time()
        except Exception as e:
            print(f"CAN TX ERROR (TP RTS Initiate): {e}", flush=True)

    def send_tp_data_packets(self, max_packets_allowed, start_packet_num):
        if not HAS_CAN or self.bus is None:
            return
        arbitration_id = (6 << 26) | (0xEB << 16) | (self.vt_address << 8) | self.source_address
        self.vt_handshake_state = "TP_SENDING_PACKETS"
        self.last_state_transition_time = time.time()

        current_packet = start_packet_num
        packets_sent = 0
        total_size = len(self.object_pool_data)

        while packets_sent < max_packets_allowed and current_packet <= self.tp_tx_num_packets:
            start_offset = (current_packet - 1) * 7
            end_offset = min(start_offset + 7, total_size)
            chunk = self.object_pool_data[start_offset:end_offset]
            packet_bytes = bytearray(chunk)
            while len(packet_bytes) < 7:
                packet_bytes.append(0xFF)
            packet_data = [current_packet] + list(packet_bytes)
            try:
                msg = can.Message(arbitration_id=arbitration_id, data=packet_data, is_extended_id=True)
                self.bus.send(msg)
                print(f"[ISOBUS] Sent TP.DT Packet {current_packet}/{self.tp_tx_num_packets} -> "
                      f"Data: {' '.join(f'{b:02X}' for b in packet_data)}", flush=True)
                time.sleep(0.01)  # Small delay to prevent TX buffer overruns
            except Exception as e:
                print(f"CAN TX ERROR (TP Packet {current_packet}): {e}", flush=True)
                break
            current_packet += 1
            packets_sent += 1

        self.tp_tx_next_packet = current_packet
        if self.tp_tx_next_packet > self.tp_tx_num_packets:
            print("[ISOBUS] All Object Pool packets successfully transmitted! Waiting for VT EOM-ACK...", flush=True)
            self.vt_handshake_state = "TP_EOM_WAIT"
            self.last_state_transition_time = time.time()
        else:
            print(f"[ISOBUS] Sent {packets_sent} packets. Next sequence needed: {self.tp_tx_next_packet}. "
                  "Waiting for next VT CTS...", flush=True)
            self.vt_handshake_state = "TP_RTS_SENT"

    def change_active_mask(self, mask_id=2):
        if not HAS_CAN or self.bus is None:
            return
        arbitration_id = (6 << 26) | (0xE6 << 16) | (self.vt_address << 8) | self.source_address
        data = [0x0A, 0xFF, 0xFF, mask_id & 0xFF, (mask_id >> 8) & 0xFF, 0xFF, 0xFF, 0xFF]
        try:
            msg = can.Message(arbitration_id=arbitration_id, data=data, is_extended_id=True)
            self.bus.send(msg)
            print(f"[ISOBUS] Sent 'Change Active Mask' to ID {mask_id} over VT", flush=True)
        except Exception as e:
            print(f"CAN TX ERROR (Change Active Mask): {e}", flush=True)

    def upload_vt_object_pool(self):
        print(f"[ISOBUS] Connecting to Universal Terminal (UT) at SA {hex(self.vt_address)}...", flush=True)
        self.vt_handshake_state = "CLAIMING_ADDRESS"
        self.last_state_transition_time = time.time()
        print("[ISOBUS] Physical Address Claiming initiated. Handshaking will automatically proceed "
              "on bus registration.", flush=True)

    def autodetect_and_scan(self):
        print("[ISOBUS] Commencing non-blocking Connection Auto-Scan...", flush=True)
        self.can_status = "scanning"
        self.can_error_msg = "Scanning interfaces..."

        candidates = []
        is_linux = sys.platform.startswith('linux')
        if is_linux:
            candidates.append(('can0', 'socketcan', 'can0 (SocketCAN)'))
            candidates.append(('vcan0', 'socketcan', 'vcan0 (SocketCAN)'))

        candidates.append(('PCAN_USBBUS1', 'pcan', 'PCAN USB Interface'))
        candidates.append((0, 'ixxat', 'IXXAT USB Interface'))

        serial_ports = []
        if HAS_SERIAL:
            try:
                import serial.tools.list_ports
                ports = serial.tools.list_ports.comports()
                for p in ports:
                    serial_ports.append(p.device)
            except Exception:
                pass

        if not serial_ports:
            serial_ports = ['COM3', 'COM4', 'COM1', 'COM2', 'COM5', 'COM6', 'COM7', 'COM8']
            if not is_linux:
                serial_ports += ['/dev/ttyUSB0', '/dev/ttyUSB1', '/dev/ttyACM0']

        for port in serial_ports:
            candidates.append((port, 'slcan', f'{port} Serial slcan'))

        for channel, bustype, label in candidates:
            if not self.is_running or self.interface != 'auto':
                break

            self.can_status = "scanning"
            self.can_error_msg = f"Scanning {label}..."
            print(f"[ISOBUS] Auto-Scan probing {label} (channel={channel} bustype={bustype})...", flush=True)

            try:
                test_bus = can.interface.Bus(channel=channel, bustype=bustype, bitrate=self.bitrate)
                start_probe = time.time()
                traffic_detected = False
                while time.time() - start_probe < 0.35:
                    msg = test_bus.recv(timeout=0.1)
                    if msg is not None:
                        traffic_detected = True
                        break

                if traffic_detected:
                    self.bus = test_bus
                    self.can_status = "connected"
                    self.interface = str(channel)
                    self.can_error_msg = f"Auto-Locked: {label} (Traffic Detected)"
                    print(f"[ISOBUS] Auto-Locked onto {label} with active traffic!", flush=True)
                    self.perform_address_claim()
                    self.upload_vt_object_pool()
                    return
                else:
                    print(f"[ISOBUS] No signal on {label}. Moving to next...", flush=True)
                    test_bus.shutdown()
            except Exception as e:
                print(f"[ISOBUS] Failed scanning probe on {label}: {e}", flush=True)
                continue

        if self.is_running and self.interface == 'auto':
            print("[ISOBUS] Auto-scan ended. No active physical CAN bus discovered. Staying disconnected.", flush=True)
            self.can_status = "error"
            self.can_error_msg = "No live physical CAN bus discovered."

    def start(self):
        if self.is_running:
            return
        self.is_running = True
        self.last_wsm_time = 0.0
        self.can_status = "connecting"
        self.can_error_msg = ""

        if HAS_CAN:
            if self.interface in ('none', 'off', ''):
                self.can_status = "disconnected"
                self.can_error_msg = "CAN idle — select an interface in the UI"
                print("[ISOBUS] CAN idle (no interface selected).", flush=True)
            elif self.interface == 'auto':
                self.scan_thread = threading.Thread(target=self.autodetect_and_scan, daemon=True)
                self.scan_thread.start()
            else:
                try:
                    bustype = 'socketcan'
                    channel = self.interface

                    if channel == 'pcan':
                        bustype = 'pcan'
                        channel = 'PCAN_USBBUS1'
                    elif channel == 'virtual':
                        bustype = 'virtual'
                        channel = 'vcan0'
                    elif channel == 'ixxat':
                        bustype = 'ixxat'
                        channel = 0
                    elif isinstance(channel, str) and (channel.upper().startswith('COM')
                                                       or '/dev/tty' in channel or 'COM' in channel.upper()):
                        if not HAS_SERIAL:
                            raise ImportError("The 'pyserial' library is not found. "
                                              "Run 'pip install pyserial' to resolve.")
                        bustype = 'slcan'
                        channel = channel.upper() if channel.upper().startswith('COM') else channel

                    print(f"[ISOBUS] Connecting on channel={channel} bustype={bustype} "
                          f"bitrate={self.bitrate}bps...", flush=True)
                    self.bus = can.interface.Bus(channel=channel, bustype=bustype, bitrate=self.bitrate)
                    print(f"CAN Bus strictly initialized on {channel} at {self.bitrate}bps "
                          f"(bustype: {bustype})", flush=True)
                    self.can_status = "connected"
                    self.can_error_msg = f"Connected to {self.interface} ({bustype})"
                    self.perform_address_claim()
                    self.upload_vt_object_pool()
                except Exception as e:
                    err_str = str(e)
                    print(f"ERROR: Failed to initialize CAN bus ({self.interface}): {err_str}. "
                          "ISOBUS functions disabled.", flush=True)
                    self.can_status = "error"
                    self.can_error_msg = err_str
                    self.bus = None
        else:
            self.can_status = "error"
            self.can_error_msg = "python-can dependency is missing in the Python environment."

        self.listen_thread = threading.Thread(target=self.listen_loop, daemon=True)
        self.listen_thread.start()

        self.heartbeat_thread = threading.Thread(target=self.heartbeat_loop, daemon=True)
        self.heartbeat_thread.start()

    def send_tc_client_announce(self):
        """ISO 11783-10 TC Client Status Announcement at 1 Hz (PGN 0xCB00, DA=0xFF)."""
        if not HAS_CAN or self.bus is None:
            return
        if not self._tx_allowed("presence"):
            return
        arbitration_id = (6 << 26) | (0xCB << 16) | (0xFF << 8) | self.source_address
        tc_capabilities = 0x07  # TC-SC + TC-GEO + TC-BASIC
        data = [0xFF, tc_capabilities, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF]
        try:
            msg = can.Message(arbitration_id=arbitration_id, data=data, is_extended_id=True)
            self.bus.send(msg)
        except Exception as e:
            self.log_isobus_event(f"TX TC Client Announce Error: {e}")

    def send_section_commands(self, out_bitmap):
        """Send section on/off commands using the appropriate method for the active sprayer profile.

        Goldacres GRC: DDI 141 (Section Control State bitmask) direct to GRC.001 at SA 0xCC.
        616R / generic: global broadcast bitmap to DA=0xF7. (616R live pathway is GreenSeeker
        serial + whole-boom blanking — no CAN section injection; see SAFETY.md.)
        """
        if not HAS_CAN or self.bus is None:
            return
        if not self._tx_allowed("section"):
            return

        # Interlock: a tripped interlock forces all sections CLOSED (actively send 0).
        if not self._interlocks_ok():
            out_bitmap = 0

        if self.sprayer_profile == self.PROFILE_GOLDACRES_GRC:
            arb_id = (6 << 26) | (0xCB << 16) | (self.jdrc_address << 8) | self.source_address
            ddi_bytes = [0x8D, 0x00]  # DDI 141 little-endian
            val_bytes = list(out_bitmap.to_bytes(4, byteorder='little', signed=False))
            data = ddi_bytes + val_bytes + [0x00, 0x00]
            try:
                msg = can.Message(arbitration_id=arb_id, data=data, is_extended_id=True)
                self.bus.send(msg)
                self.tx_counts["section"] += 1
            except Exception as e:
                self.log_isobus_event(f"TX DDI 141 (GRC section) Error: {e}")
        else:
            arb_id = (3 << 26) | (0xCB << 16) | (0xF7 << 8) | self.source_address
            b0 = out_bitmap & 0xFF
            b1 = (out_bitmap >> 8) & 0xFF
            data = [b0, b1, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF]
            try:
                msg = can.Message(arbitration_id=arb_id, data=data, is_extended_id=True)
                self.bus.send(msg)
                self.tx_counts["section"] += 1
            except Exception:
                pass

    def listen_loop(self):
        # Background thread listening for ISOBUS feedback (speed, sections, VT packets)
        while self.is_running:
            if HAS_CAN and self.bus is not None:
                try:
                    msg = self.bus.recv(timeout=1.0)
                    if msg:
                        self.last_rx_time = time.time()
                        if not self.is_connected:
                            self.is_connected = True
                            self.log_isobus_event("CAN bus traffic detected: Connection established.")

                        self.process_incoming_address_claim(msg.arbitration_id, msg.data)

                        pf = (msg.arbitration_id >> 16) & 0xFF
                        ps = (msg.arbitration_id >> 8) & 0xFF
                        if pf < 240:
                            pgn = pf << 8
                        else:
                            pgn = (pf << 8) | ps
                        sa = msg.arbitration_id & 0xFF

                        # --- J1939 Request PGN (0xEA00) ---
                        if pgn == 0xEA00 and len(msg.data) >= 3:
                            requested_pgn = msg.data[0] | (msg.data[1] << 8) | (msg.data[2] << 16)
                            if requested_pgn == 0xEE00:
                                self.log_isobus_event(
                                    f"RX PGN 59904 (Request PGN): Address claim requested by Node {hex(sa)}. "
                                    "Re-claiming address.")
                                self.perform_address_claim()

                        # --- ISOBUS Speed Source Decoding ---
                        # PGN 65265 (0xFEF1) CCVS Wheel-Based Vehicle Speed (SPN 84):
                        #   data[1] LSB, data[2] MSB, 1/256 km/h per bit. 0xFFFF = unavailable.
                        elif pgn == 0xFEF1:
                            if len(msg.data) >= 3:
                                raw_speed = msg.data[1] | (msg.data[2] << 8)
                                if raw_speed != 0xFFFF:
                                    self._fef1_speed_seen = True
                                    incoming_speed = raw_speed / 256.0
                                    if self.is_flushing:
                                        self.saved_speed_kmh = incoming_speed
                                    else:
                                        self.speed_kmh = incoming_speed
                        elif pgn == 0xFEE8:
                            # Secondary speed (SPN 517) — only until FEF1 is seen. JD ATX (SA
                            # 0x1C) carries it in bytes 2-3; bytes 1-2 decode phantom ~132 km/h.
                            if not self._fef1_speed_seen and len(msg.data) >= 3:
                                off = 1 if sa == 0x1C else 0
                                raw_speed = msg.data[off] | (msg.data[off + 1] << 8)
                                if raw_speed != 0xFFFF:
                                    incoming_speed = raw_speed / 256.0
                                    if self.is_flushing:
                                        self.saved_speed_kmh = incoming_speed
                                    else:
                                        self.speed_kmh = incoming_speed

                        # --- Goldacres GRC process data (PGN 0xEF00) ---
                        elif pgn == 0xEF00:
                            self._parse_grc_ef00(sa, pgn, msg.data)

                        # --- John Deere Commanded Section State (PF 0xCB) ---
                        # On Goldacres, 0xCB00 from 0xF7 is static; real state is on GRC 0xEF00.
                        elif pf == 0xCB or pgn == 0xCB00 or pgn == 52128:
                            if len(msg.data) >= 2 and self.sprayer_profile != self.PROFILE_GOLDACRES_GRC:
                                self.jd_commanded_sections = msg.data[0] | (msg.data[1] << 8)

                        # --- Process Data (PGN 160 / PF 0xA0) with DDI 158 ---
                        elif pf == 0xA0 and len(msg.data) >= 6:
                            ddi = msg.data[0] | (msg.data[1] << 8)
                            if ddi == 0x009E:
                                if self.jdrc_address != sa:
                                    self.jdrc_address = sa
                                    self.log_isobus_event(f"Discovered Liquid Rate Controller at SA {hex(sa)}")
                                val = msg.data[2] | (msg.data[3] << 8) | (msg.data[4] << 16) | (msg.data[5] << 24)
                                self.ddi_158_val = val
                                self.actual_flow_rate_l_min = val / 100.0
                                self.last_ddi158_rx_time = time.time()
                                self.log_isobus_event(
                                    f"RX PGN 160 (DDI 158): Received Liquid Rate Feedback from {hex(sa)}: "
                                    f"{self.actual_flow_rate_l_min:.2f} L/ha")
                            elif ddi == 0x009D:
                                val = msg.data[2] | (msg.data[3] << 8) | (msg.data[4] << 16) | (msg.data[5] << 24)
                                self.ddi_157_val = val

                        # --- ISOBUS Virtual Terminal (VT to WS) (PGN 0xE700) ---
                        elif pgn == 0xE700:
                            if ps == 0xFF or ps == self.source_address:
                                self.last_vt_rx_time = time.time()
                                self.last_vt_status_time = time.time()
                                if sa != self.source_address and self.vt_address != sa:
                                    self.vt_address = sa
                                    self.log_isobus_event(f"Discovered active Universal Terminal at SA {hex(sa)}")

                                if len(msg.data) >= 2:
                                    ctrl_byte = msg.data[0]
                                    if self.vt_handshake_state == "ADDRESS_CLAIMED" and ps == 0xFF:
                                        self.log_isobus_event(
                                            f"UT Status Broadcast parsed from SA {hex(sa)}. Commencing handshake...")
                                        self.send_get_vt_version()
                                    elif ctrl_byte == 0xC0 and ps == self.source_address:
                                        self.vt_version = msg.data[1]
                                        self.log_isobus_event(
                                            f"Handshake: Received 'Get VT Version' Response! VT version: {self.vt_version}")
                                        self.send_get_vt_capabilities()
                                    elif ctrl_byte == 0xC1 and ps == self.source_address:
                                        self.vt_softkeys = msg.data[1]
                                        self.vt_colors = msg.data[2] if len(msg.data) >= 3 else 256
                                        self.log_isobus_event(
                                            f"Handshake: Received 'Get VT Capabilities' Response. "
                                            f"Softkeys: {self.vt_softkeys}, Colors: {self.vt_colors}")
                                        self.initiate_tp_object_pool()

                        # --- J1939 TP.CM (PGN 0xEC00) from VT to us ---
                        elif pgn == 0xEC00 and sa == self.vt_address and ps == self.source_address:
                            if len(msg.data) >= 8:
                                tp_ctrl = msg.data[0]
                                if tp_ctrl == 0x11:  # TP.CTS
                                    num_pkts = msg.data[1]
                                    start_pkt = msg.data[2]
                                    target_pgn = msg.data[5] | (msg.data[6] << 8) | (msg.data[7] << 16)
                                    if target_pgn == self.tp_tx_pgn:
                                        print(f"[ISOBUS] Handshake: Received TP.CTS for Object Pool. "
                                              f"Sending {num_pkts} packets starting from sequence {start_pkt}", flush=True)
                                        self.send_tp_data_packets(num_pkts, start_pkt)
                                elif tp_ctrl == 0x13:  # TP.EOM-ACK
                                    target_pgn = msg.data[5] | (msg.data[6] << 8) | (msg.data[7] << 16)
                                    if target_pgn == self.tp_tx_pgn:
                                        print("[ISOBUS] Handshake: Received J1939 TP EOM-ACK! Object Pool "
                                              "Transfer successfully completed by VT.", flush=True)
                                        self.vt_handshake_state = "OPERATIONAL"
                                        self.change_active_mask(self.active_data_mask_id)
                                elif tp_ctrl == 0xFF:  # TP.Conn-Abort
                                    abort_reason = msg.data[1]
                                    print(f"[ISOBUS] ERROR: ISOBUS J1939 TP connection aborted by VT! "
                                          f"Reason code: {hex(abort_reason)}. Resetting handshake...", flush=True)
                                    self.vt_handshake_state = "ADDRESS_CLAIMED"
                                    self.last_state_transition_time = time.time()

                        if self.record_active:
                            self.record_frame("RX", msg)

                        data_hex = ' '.join(f'{b:02X}' for b in msg.data)
                        can_data = {
                            "id": hex(msg.arbitration_id),
                            "is_ext": msg.is_extended_id,
                            "dlc": msg.dlc,
                            "data": data_hex,
                            "ts": msg.timestamp
                        }
                        print(f"CAN_RX:{json.dumps(can_data)}", flush=True)
                except Exception:
                    pass
            else:
                time.sleep(0.1)

    def heartbeat_loop(self):
        """ISO 11783 WSM heartbeat (1 Hz), TC announce (1 Hz), section commands (10 Hz),
        VT handshake state machine, watchdogs, and recorder shadow rows."""
        while self.is_running:
            start_time = time.time()
            current_time = time.time()

            # --- Safety watchdogs (run every tick): auto-demote if an interlock trips ---
            self._service_watchdogs()

            # --- Stateful Virtual Terminal Handshake Timeouts & Retries ---
            if HAS_CAN and self.bus is not None:
                if self.vt_handshake_state == "CLAIMING_ADDRESS":
                    if current_time - self.last_state_transition_time >= 0.25:
                        print("[ISOBUS] Address contention period completed safely. Address claimed "
                              "successfully. Waiting for UT Status broadcast to start handshake...", flush=True)
                        self.vt_handshake_state = "ADDRESS_CLAIMED"
                        self.last_state_transition_time = current_time
                elif self.vt_handshake_state == "GET_VT_VERSION_SENT":
                    if current_time - self.last_state_transition_time >= 3.0:
                        print("[ISOBUS] Retry: 'Get VT Version' request timed out. Resending...", flush=True)
                        self.send_get_vt_version()
                elif self.vt_handshake_state == "GET_VT_CAPABILITIES_SENT":
                    if current_time - self.last_state_transition_time >= 3.0:
                        print("[ISOBUS] Retry: 'Get VT Capabilities' request timed out. Resending...", flush=True)
                        self.send_get_vt_capabilities()
                elif self.vt_handshake_state == "TP_RTS_SENT":
                    if current_time - self.last_state_transition_time >= 4.0:
                        print("[ISOBUS] Retry: J1939 TP RTS for Object Pool timed out. Re-initiating...", flush=True)
                        self.initiate_tp_object_pool()

            # --- Standard Broadcasts (WSM Message & TC Heartbeats) ---
            if self.address_claimed:
                # Rate setpoint stays 0 until RateCommandV1 exists (BOUNDARY 4.7); estimated
                # flow on virtual bus retained for bench parity.
                if self.interface == 'virtual' or not HAS_CAN:
                    active_speed = 1.0 if self.is_flushing else max(2.0, self.speed_kmh)
                    self.actual_flow_rate_l_min = (self.target_rate_l_ha * active_speed * 36.6) / 600.0

                # 1 Hz interval tasks (WSM, rate, TC announce)
                if current_time - self.last_wsm_time >= 1.0:
                    self.last_wsm_time = current_time

                    self.send_ddi_157()

                    # Working Set Maintenance (WSM) - PGN 65021 (0xFE0D)
                    wsm_id = (6 << 26) | (0xFE0D << 8) | self.source_address
                    wsm_data = [0x00, 0x05, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF]
                    if HAS_CAN and self.bus is not None and self._tx_allowed("presence"):
                        try:
                            msg = can.Message(arbitration_id=wsm_id, data=wsm_data, is_extended_id=True)
                            self.bus.send(msg)
                            if int(current_time) % 5 == 0:
                                self.log_isobus_event(
                                    f"TX PGN 65021 (WSM): Active, master={hex(self.source_address)}, "
                                    f"target_vt={hex(self.vt_address)}")
                        except Exception as e:
                            self.log_isobus_event(f"TX PGN 65021 Error: Failed to send WSM: {e}")

                    self.send_tc_client_announce()
                    self.last_tc_client_announce_time = current_time
                    if int(current_time) % 10 == 0:
                        self.log_isobus_event(
                            f"TX TC Client Announce: profile={self.sprayer_profile}, "
                            "capabilities=TC-SC+TC-GEO+TC-BASIC")

                # 2. Section command at 10 Hz from external inputs (vision feed / bench vector)
                self.update_sections_from_inputs()
                out_bitmap = self.section_bitmap
                if self.cooperative_mode:
                    out_bitmap &= self.jd_commanded_sections

                if not hasattr(self, 'prev_out_bitmap') or self.prev_out_bitmap != out_bitmap:
                    self.prev_out_bitmap = out_bitmap
                    self.log_isobus_event(
                        f"TX Section Command [{self.sprayer_profile}]: bitmap={bin(out_bitmap)} -> {hex(out_bitmap)}")

                self.send_section_commands(out_bitmap)

            # Tier-2 shadow channel capture at 10 Hz — runs at OBSERVE/ANNOUNCE too
            if self.record_active:
                if not self.address_claimed:
                    self.update_sections_from_inputs()
                out_bitmap = self.section_bitmap
                if self.cooperative_mode:
                    out_bitmap &= self.jd_commanded_sections
                self.log_record_shadow_row(out_bitmap)

            # Watchdog & Graceful Recovery Check (10 Hz)
            if HAS_CAN and self.bus is not None:
                if self.is_connected:
                    if current_time - self.last_rx_time > 5.0:
                        self.is_connected = False
                        self.log_isobus_event("ERROR: Net silence watchdog timeout. Lost communication / disconnected.")
                else:
                    if current_time - getattr(self, 'last_reconnect_attempt', 0) > 10.0:
                        self.last_reconnect_attempt = current_time
                        self.log_isobus_event("Graceful connection recovery: broadcasting Address Claim...")
                        self.perform_address_claim()

            elapsed = time.time() - start_time
            time.sleep(max(0, 0.1 - elapsed))

    def stop(self):
        self.is_running = False
        time.sleep(0.2)  # Allow background threads to exit gracefully
        if HAS_CAN and self.bus is not None:
            try:
                self.bus.shutdown()
            except Exception:
                pass
            self.bus = None


def build_telemetry(ctrl, gs_emitter):
    """TelemetryV1 superset — includes bench-diagnostic extras the schema allows."""
    status = {
        "schema": "TelemetryV1",
        "ts_ms": int(time.time() * 1000),
        "control_authority": ctrl.control_authority,
        "control_armed": ctrl.armed,
        "control_interlocks": dict(ctrl.interlock_status),
        "control_demote_reason": ctrl.last_demote_reason or None,
        "sprayer_profile": ctrl.sprayer_profile,
        "section_bitmap": f"0x{ctrl.section_bitmap:X}",
        "jd_commanded_sections": f"0x{ctrl.jd_commanded_sections:X}",
        "cooperative_mode": ctrl.cooperative_mode,
        "speed_kmh": round(ctrl.speed_kmh, 2),
        "target_rate_l_ha": round(ctrl.target_rate_l_ha, 1),
        "isobus_is_connected": ctrl.is_connected,
        "isobus_jdrc_address": ctrl.jdrc_address,
        "record_session_active": ctrl.record_active,
        "record_session_id": ctrl.record_session_id or None,
        "record_frame_count": ctrl.record_frame_count,
        "record_shadow_count": ctrl.record_shadow_count,
        # Bench diagnostics (additionalProperties allowed by TelemetryV1)
        "can_status": ctrl.can_status,
        "can_interface": ctrl.interface,
        "can_error_msg": ctrl.can_error_msg,
        "isobus_sa": ctrl.source_address,
        "vt_handshake_state": ctrl.vt_handshake_state,
        "vt_version": ctrl.vt_version,
        "vt_softkeys": ctrl.vt_softkeys,
        "vt_colors": ctrl.vt_colors,
        "isobus_vt_address": ctrl.vt_address,
        "isobus_last_rx_time": ctrl.last_rx_time,
        "isobus_last_ddi158_rx_time": ctrl.last_ddi158_rx_time,
        "actual_flow_rate_l_min": round(ctrl.actual_flow_rate_l_min, 1),
        "ddi_157_val": ctrl.ddi_157_val,
        "ddi_158_val": ctrl.ddi_158_val,
        "name_payload": [int(b) for b in ctrl.name_payload],
        "rate_tx_enabled": ctrl._profile_sends_rate(),
        "record_dir": ctrl.record_dir,
        "grc_ef00_rate_l_ha": round(ctrl.grc_ef00_rate_l_ha, 1),
        "grc_master_on": ctrl.grc_master_on,
        "grc_ef00_section_bitmap": ctrl.grc_ef00_section_bitmap,
        "grc_ef00_coarse_bitmap": ctrl.grc_ef00_coarse_bitmap,
        "grc_sections": dict(ctrl.grc_section_enabled),
        "grc_alive": ctrl._grc_is_alive(),
        "tc_server_address": ctrl.tc_server_address,
        "vision_seen": ctrl.vision_seen,
        "vision_fresh": ctrl._vision_fresh(),
        "vision_seq": ctrl.vision_seq,
        "vision_source": ctrl.vision_source,
        "tx_counts": dict(ctrl.tx_counts),
    }
    status.update(gs_emitter.get_status())
    return status


def _parse_int(text):
    text = text.strip()
    return int(text, 16) if text.lower().startswith("0x") else int(text)


def main():
    print("PUFworks ISOBUS Bus Engine started. Bus-only sidecar (no camera).", flush=True)

    ctrl = ISOBUSController()

    # GreenSeeker serial emitter (616R sanctioned pathway). Detection provider is the
    # fresh vision bitmap — same SectionBitmapV1 contract as CAN sections.
    gs_emitter = GreenSeekerEmitter(
        rate_provider=lambda: ctrl.target_rate_l_ha,
        ndvi_provider=lambda: ctrl.greenness_index,
        speed_provider=lambda: ctrl.speed_kmh,
        detection_provider=lambda: ctrl.vision_weeds_present(),
        logger=lambda msg: ctrl.log_isobus_event(f"GreenSeeker: {msg}"),
    )
    gs_emitter.start()

    def telemetry_loop():
        while True:
            try:
                print(f"TELEMETRY:{json.dumps(build_telemetry(ctrl, gs_emitter))}", flush=True)
            except Exception as e:
                print(f"ERROR: telemetry_loop: {e}", flush=True)
            time.sleep(0.1)  # 10 Hz

    threading.Thread(target=telemetry_loop, daemon=True).start()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        # --- SectionBitmapV1 ingest (vision feed / bench harness) ---
        if line.startswith('VISION_BITMAP:'):
            try:
                ctrl.ingest_vision_bitmap(json.loads(line[len('VISION_BITMAP:'):]))
            except json.JSONDecodeError as e:
                ctrl.log_isobus_event(f"VISION_BITMAP invalid JSON: {e}")
            continue  # high-rate path: skip the command echo below

        # UI_HEARTBEAT arrives at 1 Hz from the UI host — echoing it floods the log.
        if line != 'UI_HEARTBEAT':
            print(f"Bus engine received command: {line}", flush=True)

        if line == 'STOP_CAN':
            ctrl.stop()
            print("CAN stopped.", flush=True)
        elif line == 'START_CAN':
            ctrl.start()
            print("CAN started.", flush=True)
        elif line.startswith('SET_CAN_INTERFACE:'):
            parts = line.split(':')
            if len(parts) == 2:
                new_iface = parts[1]
                print(f"[ISOBUS] Setting CAN interface to {new_iface} and restarting...", flush=True)
                ctrl.stop()
                ctrl.interface = new_iface
                ctrl.start()
        elif line.startswith('SET_COOPERATIVE_MODE:'):
            parts = line.split(':')
            if len(parts) == 2:
                try:
                    ctrl.cooperative_mode = bool(int(parts[1]))
                    print(f"Cooperative Mode updated: {ctrl.cooperative_mode}", flush=True)
                except ValueError:
                    pass
        elif line.startswith('SET_CAN_ADDRESS:'):
            parts = line.split(':')
            if len(parts) == 2:
                try:
                    new_addr = _parse_int(parts[1])
                    if 1 <= new_addr <= 254:
                        print(f"[ISOBUS] Relocating SA from {hex(ctrl.source_address)} to {hex(new_addr)}...", flush=True)
                        ctrl.stop()
                        ctrl.source_address = new_addr
                        ctrl.address_claimed = False
                        ctrl.start()
                except Exception as e:
                    print(f"Error updating J1939 CAN Address: {e}", flush=True)
        elif line == 'RECLAIM_ADDRESS':
            print("[ISOBUS] Manual address reclaim triggered via command.", flush=True)
            ctrl.log_isobus_event("Manual J1939 address reclaim triggered by user.")
            ctrl.address_claimed = False
            ctrl.perform_address_claim()
        elif line.startswith('SET_SPRAYER_PROFILE:'):
            parts = line.split(':')
            if len(parts) == 2:
                profile = parts[1].strip().lower()
                valid_profiles = [ISOBUSController.PROFILE_GOLDACRES_GRC,
                                  ISOBUSController.PROFILE_JD_616R,
                                  ISOBUSController.PROFILE_GENERIC]
                if profile in valid_profiles:
                    ctrl.sprayer_profile = profile
                    print(f"[ISOBUS] Sprayer profile set to: {profile}", flush=True)
                    ctrl.log_isobus_event(f"Sprayer profile changed to: {profile}")
                    if profile == ISOBUSController.PROFILE_GOLDACRES_GRC:
                        ctrl.log_isobus_event(
                            "Goldacres: DDI 157 rate TX suppressed — GRC holds Work Setup rate; "
                            "DDI 141 sections only.")
                else:
                    print(f"[ISOBUS] Unknown sprayer profile '{profile}'. Valid: {valid_profiles}", flush=True)
        elif line.startswith('SET_TC_SERVER_ADDRESS:'):
            parts = line.split(':')
            if len(parts) == 2:
                try:
                    ctrl.tc_server_address = _parse_int(parts[1])
                    print(f"[ISOBUS] TC Server SA set to: {hex(ctrl.tc_server_address)}", flush=True)
                except Exception as e:
                    print(f"Error setting TC server address: {e}", flush=True)
        elif line.startswith('SET_GS_EMITTER:'):
            parts = line.split(':')
            if len(parts) == 2:
                try:
                    gs_emitter.set_enabled(bool(int(parts[1])))
                except ValueError:
                    pass
        elif line.startswith('SET_GS_COM_PORT:'):
            parts = line.split(':', 1)
            if len(parts) == 2 and parts[1].strip():
                gs_emitter.set_port(parts[1].strip())
        elif line.startswith('SET_GS_BAUD:'):
            parts = line.split(':')
            if len(parts) == 2:
                try:
                    gs_emitter.set_baud(int(parts[1]))
                except ValueError:
                    pass
        elif line.startswith('SET_GS_PROTOCOL:'):
            parts = line.split(':', 1)
            if len(parts) == 2 and parts[1].strip():
                gs_emitter.set_protocol(parts[1].strip())
        elif line.startswith('SET_GS_BLANKING:'):
            parts = line.split(':')
            if len(parts) == 2:
                try:
                    gs_emitter.set_boom_blanking(bool(int(parts[1])))
                except ValueError:
                    pass
        elif line.startswith('SET_GS_BLANK_HOLD:'):
            parts = line.split(':')
            if len(parts) == 2:
                try:
                    gs_emitter.set_blank_params(hold_s=float(parts[1]))
                except ValueError:
                    pass
        elif line.startswith('SET_GS_BLANK_RATE:'):
            parts = line.split(':')
            if len(parts) == 2:
                try:
                    gs_emitter.set_blank_params(blank_rate=float(parts[1]))
                except ValueError:
                    pass
        elif line.startswith('SIMULATE_DDI158:'):
            parts = line.split(':')
            if len(parts) == 2:
                try:
                    sim_val = int(parts[1])
                    ctrl.ddi_158_val = sim_val
                    ctrl.actual_flow_rate_l_min = sim_val / 100.0
                    ctrl.last_ddi158_rx_time = time.time()
                    ctrl.log_isobus_event(
                        f"DDI 158 diagnostic injection: {ctrl.actual_flow_rate_l_min:.2f} L/ha")
                except Exception as e:
                    print(f"Error simulating DDI 158 feedback: {e}", flush=True)
        elif line.startswith('SIMULATE_GRC_EF00:'):
            # Bench-only: feed a hex payload through the GRC EF00 decoder as if it
            # arrived from the GRC. Also bumps last_rx_time so the rx interlock
            # treats the (virtual) bus as alive. REFUSED on any non-virtual bus so
            # field state can never be faked on a real wire.
            if ctrl.interface != 'virtual':
                ctrl.log_isobus_event("SIMULATE_GRC_EF00 refused: only allowed on the virtual bench bus.")
            else:
                parts = line.split(':', 1)
                try:
                    data = bytes.fromhex(parts[1].strip().replace(' ', ''))
                    ctrl.last_rx_time = time.time()
                    ctrl._parse_grc_ef00(ctrl.jdrc_address, 0xEF00, data)
                    ctrl.log_isobus_event(f"GRC EF00 bench injection: {data.hex().upper()}")
                except Exception as e:
                    print(f"Error simulating GRC EF00: {e}", flush=True)
        elif line.startswith('SIMULATE_SPEED:'):
            # Bench-only: set ground speed for the speed interlock / flow estimate.
            if ctrl.interface != 'virtual':
                ctrl.log_isobus_event("SIMULATE_SPEED refused: only allowed on the virtual bench bus.")
            else:
                parts = line.split(':')
                if len(parts) == 2:
                    try:
                        ctrl.speed_kmh = float(parts[1])
                        ctrl.log_isobus_event(f"Bench speed injection: {ctrl.speed_kmh:.1f} km/h")
                    except ValueError:
                        pass
        elif line.startswith('TEST_BOOM_SECTIONS:'):
            parts = line.split(':')
            if len(parts) == 2:
                try:
                    state = int(parts[1])
                    if state:
                        ctrl.manual_section_bitmap = 0xFFFF
                        if not ctrl.is_flushing:
                            ctrl.is_flushing = True
                            ctrl.saved_speed_kmh = ctrl.speed_kmh
                            ctrl.speed_kmh = 1.0  # Enforce 1 km/h max for diagnostic flush
                    else:
                        ctrl.manual_section_bitmap = 0x0000
                        if ctrl.is_flushing:
                            ctrl.is_flushing = False
                            ctrl.speed_kmh = ctrl.saved_speed_kmh
                    print(f"Boom Section Overridden: {'ON' if state else 'OFF'} "
                          f"(Bitmap: {hex(ctrl.manual_section_bitmap)}) "
                          f"(Forced speed 1.0km/h: {ctrl.is_flushing})", flush=True)
                except ValueError:
                    pass
        elif line == 'STOP_RECORD_SESSION':
            ctrl.stop_record_session()
        elif line.startswith('START_RECORD_SESSION'):
            label = line.split(':', 1)[1].strip() if ':' in line else ""
            ctrl.start_record_session(label)
        elif line.startswith('SET_SECTION_BITMAP:'):
            parts = line.split(':')
            if len(parts) == 2:
                try:
                    ctrl.set_manual_section_bitmap(_parse_int(parts[1]))
                except ValueError:
                    print(f"Invalid SET_SECTION_BITMAP value: {parts[1]}", flush=True)
        elif line.startswith('SET_CONTROL_AUTHORITY:'):
            parts = line.split(':')
            if len(parts) == 2:
                ok = ctrl.set_control_authority(parts[1].strip())
                # Raising authority to ANNOUNCE+ should (re)claim our address.
                if ok and ctrl._authority_level() >= ctrl.AUTHORITY_ORDER["ANNOUNCE"] \
                        and not ctrl.address_claimed:
                    ctrl.perform_address_claim()
        elif line.startswith('ARM'):
            ctrl.set_armed(True)
        elif line.startswith('DISARM'):
            ctrl.set_armed(False)
        elif line.startswith('UI_HEARTBEAT'):
            ctrl.ui_heartbeat()
        elif line.startswith('SET_SPEED_INTERLOCK:'):
            parts = line.split(':')
            if len(parts) == 2:
                try:
                    ctrl.speed_interlock = bool(int(parts[1]))
                    print(f"Speed interlock set to {ctrl.speed_interlock}", flush=True)
                except ValueError:
                    pass
        elif line.startswith('SET_ISO_NAME:'):
            # FORMAT: SET_ISO_NAME:ig:func:ecu:manuf:identity[:vehicle_system[:device_class[:func_instance]]]
            parts = line.split(':')
            if len(parts) >= 6:
                try:
                    ig = int(parts[1])
                    func = int(parts[2])
                    ecu = int(parts[3])
                    manuf = int(parts[4])
                    ident = int(parts[5])
                    vs = 7
                    device_class = 0
                    func_instance = 0
                    if len(parts) >= 7:
                        vs = int(parts[6])
                    else:
                        # Auto-infer Device Class: spray rate controllers use 4, sensors use 7
                        vs = 4 if func == 0x82 or func == 130 else 7
                    if len(parts) >= 8:
                        device_class = int(parts[7])
                    if len(parts) >= 9:
                        func_instance = int(parts[8])
                    ctrl.update_isobus_name(ig, func, ecu, manuf, ident, vs, device_class, func_instance)
                except ValueError:
                    print(f"Invalid SET_ISO_NAME values: {line}", flush=True)
        elif any(line.startswith(dep) for dep in DEPRECATED_COMMANDS):
            ctrl.log_isobus_event(
                f"REJECTED deprecated/deferred command: {line.split(':')[0]} (see BOUNDARY.md 4.5/4.7)")
        else:
            ctrl.log_isobus_event(f"REJECTED out-of-scope command: {line.split(':')[0]} "
                                  "(vision/agronomy concern — not a bus command)")


if __name__ == '__main__':
    main()
