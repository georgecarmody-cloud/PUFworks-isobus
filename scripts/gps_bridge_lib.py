"""Reusable 616R GPS bridge — decode ISOBUS position/speed/attitude and emit NMEA or JSON.

Import this module from other programs:

    from gps_bridge_lib import GpsFix, GpsBridge, decode_fef3, nmea_gga

Field sources (X119 tap, StarFire/ATX SA 0x1C):
  PGN 0xFEF3 — lat/lon ~5 Hz
  PGN 0xFEE8 — heading, speed, pitch, altitude (TCM / SPN 517, 583, 580)
  PGN 0xFEE6 — roll (bytes 2-3, JD companion message — likely)
  PGN 0xFFFF — JD proprietary GNSS-quality multiplex; sub-msg 0x51 byte3 =
               satellites used (~5 Hz). SA-gated to 0x1C (DISP 0xF0 also
               emits 0xFFFF with unrelated content). See SPRAY_DECODE.md.
  Any SA     PGN 0xFEF1 — wheel speed fallback

Yaw rate: derived from consecutive FEE8 headings (PGN 61482 not on X119 tap).

GNSS HDOP/PDOP/VDOP are NOT present on this implement tap (see SPRAY_DECODE.md
"GPS / motion" section) — only the satellite count is decodable, so HDOP fields
stay blank rather than fabricated.
"""
from __future__ import annotations

import json
import math
import struct
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone


ATX_SA = 0x1C
PGN_FEF3 = 0xFEF3
PGN_FEE8 = 0xFEE8
PGN_FEE6 = 0xFEE6
PGN_FEF1 = 0xFEF1
PGN_FFFF = 0xFFFF  # JD proprietary multiplex carrying GNSS satellite count (ATX 0x1C)


@dataclass
class GpsFix:
    """Latest GPS + TCM attitude state for export."""

    latitude: float | None = None
    longitude: float | None = None
    speed_kmh: float | None = None
    heading_deg: float | None = None
    pitch_deg: float | None = None
    roll_deg: float | None = None
    yaw_rate_deg_s: float | None = None
    fix_quality: int = 1
    # Satellites-in-use IS published on the 616R X119 implement tap, in the JD
    # proprietary PGN 0xFFFF multiplex from StarFire/ATX 0x1C (sub-msg 0x51,
    # byte 3) — see decode_gnss_sats_ffff() and SPRAY_DECODE.md. HDOP/PDOP/VDOP
    # are NOT on this tap; leave those None = unknown rather than fake them.
    satellites: int | None = None
    altitude_m: float | None = None
    ts_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    source: str = ""

    @property
    def valid(self) -> bool:
        return self.latitude is not None and self.longitude is not None

    def to_json(self) -> str:
        return json.dumps({
            "schema": "GpsFixV2",
            "ts_ms": self.ts_ms,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "speed_kmh": self.speed_kmh,
            "heading_deg": self.heading_deg,
            "pitch_deg": self.pitch_deg,
            "roll_deg": self.roll_deg,
            "yaw_rate_deg_s": self.yaw_rate_deg_s,
            "fix_quality": self.fix_quality,
            "satellites": self.satellites,
            "altitude_m": self.altitude_m,
            "source": self.source,
        }, separators=(",", ":"))


def decode_fef3(
    data_hex: str,
    *,
    big_endian: bool = False,
    mode: str = "jd_atx",
) -> tuple[float | None, float | None]:
    b = bytes.fromhex(data_hex)
    if len(b) < 8:
        return None, None
    fmt = ">ii" if big_endian else "<ii"
    lat_raw, lon_raw = struct.unpack(fmt, b[0:8])
    scale = 1e-7
    if mode == "j1939":
        lat = lat_raw * scale - 210.0
        lon = lon_raw * scale - 210.0
    elif mode == "raw":
        lat = lat_raw * scale
        lon = lon_raw * scale
    else:
        lat = lat_raw * scale - 210.0
        lon = lon_raw * scale
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None, None
    return lat, lon


def decode_speed_fef1(data_hex: str) -> float | None:
    b = bytes.fromhex(data_hex)
    if len(b) < 3:
        return None
    raw = b[1] | (b[2] << 8)
    if raw == 0xFFFF:
        return None
    return raw / 256.0


def _u16_le(data: bytes, off: int) -> int:
    return data[off] | (data[off + 1] << 8)


def decode_speed_fee8_atx(data_hex: str) -> float | None:
    att = decode_fee8_atx(data_hex)
    return att["speed_kmh"] if att else None


def decode_fee8_atx(data_hex: str) -> dict[str, float] | None:
    """PGN 65256 from StarFire ATX — heading, speed, pitch, altitude."""
    b = bytes.fromhex(data_hex)
    if len(b) < 8:
        return None
    raw_h = _u16_le(b, 0)
    raw_s = _u16_le(b, 2)
    raw_p = _u16_le(b, 4)
    raw_a = _u16_le(b, 6)
    out: dict[str, float] = {}
    if raw_h != 0xFFFF:
        out["heading_deg"] = raw_h / 128.0
    if raw_s != 0xFFFF:
        out["speed_kmh"] = raw_s / 256.0
    if raw_p != 0xFFFF:
        out["pitch_deg"] = raw_p / 128.0 - 210.0
    if raw_a != 0xFFFF:
        out["altitude_m"] = raw_a * 0.125 - 2500.0
    return out or None


def decode_fee6_atx_roll(data_hex: str) -> float | None:
    """Companion ATX message — roll in bytes 2-3 (/128 deg), field-validated."""
    b = bytes.fromhex(data_hex)
    if len(b) < 4:
        return None
    raw = _u16_le(b, 2)
    if raw == 0xFFFF:
        return None
    return raw / 128.0


def decode_gnss_sats_ffff(data_hex: str) -> int | None:
    """Satellites used, from JD proprietary PGN 0xFFFF (StarFire/ATX 0x1C).

    0xFFFF is a multiplexed proprietary container; byte0 selects the sub-message.
    Sub-message 0x51 (signature byte1=0x03, byte2=0x02) carries the GNSS solution
    summary: byte3 = total satellites used; bytes4-6 = per-constellation counts
    (GPS/GLONASS/Galileo), which fall together with byte3 during signal loss —
    confirming they are sat counts, not DOP. Field-validated across 25+ 616R
    captures (range ~25-39 sats). See SPRAY_DECODE.md "GPS / motion" section.

    Caller must SA-gate to 0x1C: DISP 0xF0 also emits 0xFFFF with other content.
    """
    b = bytes.fromhex(data_hex)
    if len(b) < 4 or b[0] != 0x51 or b[1] != 0x03 or b[2] != 0x02:
        return None
    sats = b[3]
    # Guard against fill / implausible values; real StarFire multi-constellation
    # solutions sit well under ~48. 0 / 0xFF mean "no count" -> leave unknown.
    if sats == 0 or sats > 64:
        return None
    return sats


def heading_delta_deg(new_deg: float, prev_deg: float) -> float:
    dh = new_deg - prev_deg
    if dh > 180.0:
        dh -= 360.0
    elif dh < -180.0:
        dh += 360.0
    return dh


def nmea_checksum(body: str) -> str:
    cs = 0
    for ch in body:
        cs ^= ord(ch)
    return f"{cs:02X}"


def _nmea_wrap(talker_payload: str) -> str:
    body = talker_payload[1:]  # strip $
    return f"{talker_payload}*{nmea_checksum(body)}\r\n"


def _lat_nmea(deg: float) -> tuple[str, str]:
    hemi = "N" if deg >= 0 else "S"
    ad = abs(deg)
    d = int(ad)
    m = (ad - d) * 60.0
    return f"{d:02d}{m:07.4f}", hemi


def _lon_nmea(deg: float) -> tuple[str, str]:
    hemi = "E" if deg >= 0 else "W"
    ad = abs(deg)
    d = int(ad)
    m = (ad - d) * 60.0
    return f"{d:03d}{m:07.4f}", hemi


def _utc_hhmmss_ss() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%H%M%S.%f")[:-4]


def nmea_gga(fix: GpsFix) -> str | None:
    if not fix.valid:
        return None
    lat, ns = _lat_nmea(fix.latitude)
    lon, ew = _lon_nmea(fix.longitude)
    t = _utc_hhmmss_ss()
    # Satellites come from StarFire PGN 0xFFFF/0x51 (real). HDOP is not on the JD
    # implement bus, so its field stays empty (valid NMEA) -> tablet shows "—"
    # for HDOP rather than a fabricated value.
    sats = f"{fix.satellites:02d}" if fix.satellites is not None else ""
    hdop = ""
    alt = f"{(fix.altitude_m if fix.altitude_m is not None else 0.0):.1f}"
    return _nmea_wrap(
        f"$GPGGA,{t},{lat},{ns},{lon},{ew},{fix.fix_quality},{sats},{hdop},{alt},M,0.0,M,,"
    )


def nmea_panda(fix: GpsFix) -> str | None:
    """AgOpenGPS $PANDA — carries the TCM attitude (roll/pitch/yaw) the plain
    NMEA sentences cannot. Field layout:
    $PANDA,time,lat,N,lon,E,fixQ,sats,hdop,alt,age,speed,heading,roll,pitch,yawrate
    """
    if not fix.valid:
        return None
    lat, ns = _lat_nmea(fix.latitude)
    lon, ew = _lon_nmea(fix.longitude)
    t = _utc_hhmmss_ss()
    sats = f"{fix.satellites:02d}" if fix.satellites is not None else ""
    hdop = ""  # HDOP not on the JD implement bus (see nmea_gga); sats are real
    alt = (fix.altitude_m if fix.altitude_m is not None else 0.0)
    speed = fix.speed_kmh or 0.0
    heading = fix.heading_deg if fix.heading_deg is not None else 0.0
    roll = fix.roll_deg if fix.roll_deg is not None else 0.0
    pitch = fix.pitch_deg if fix.pitch_deg is not None else 0.0
    yaw = fix.yaw_rate_deg_s if fix.yaw_rate_deg_s is not None else 0.0
    return _nmea_wrap(
        f"$PANDA,{t},{lat},{ns},{lon},{ew},{fix.fix_quality},{sats},{hdop},"
        f"{alt:.1f},0.0,{speed:.2f},{heading:.1f},{roll:.2f},{pitch:.2f},{yaw:.2f}"
    )


def nmea_rmc(fix: GpsFix) -> str | None:
    if not fix.valid:
        return None
    lat, ns = _lat_nmea(fix.latitude)
    lon, ew = _lon_nmea(fix.longitude)
    t = _utc_hhmmss_ss()
    spd_kn = (fix.speed_kmh or 0.0) / 1.852
    cog = fix.heading_deg if fix.heading_deg is not None else 0.0
    date = datetime.now(timezone.utc).strftime("%d%m%y")
    return _nmea_wrap(
        f"$GPRMC,{t},A,{lat},{ns},{lon},{ew},{spd_kn:.2f},{cog:.1f},{date},,,A"
    )


def nmea_vtg(fix: GpsFix) -> str | None:
    if not fix.valid:
        return None
    cog = fix.heading_deg if fix.heading_deg is not None else 0.0
    spd_kmh = fix.speed_kmh or 0.0
    spd_kn = spd_kmh / 1.852
    return _nmea_wrap(f"$GPVTG,{cog:.1f},T,,M,{spd_kn:.2f},N,{spd_kmh:.2f},K")


def nmea_bundle(fix: GpsFix) -> bytes:
    # $PANDA last so its full attitude payload wins if a consumer parses all four.
    parts = [nmea_gga(fix), nmea_rmc(fix), nmea_vtg(fix), nmea_panda(fix)]
    return "".join(p for p in parts if p).encode("ascii")


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r1, r2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(r2)
    x = math.cos(r1) * math.sin(r2) - math.sin(r1) * math.cos(r2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


class GpsBridge:
    """Stateful decoder: CAN frames / recorder rows -> GpsFix updates."""

    def __init__(self, latlon_mode: str = "jd_atx", big_endian: bool = False):
        self.latlon_mode = latlon_mode
        self.big_endian = big_endian
        self.fix = GpsFix()
        self._prev_lat: float | None = None
        self._prev_lon: float | None = None
        self._prev_heading_deg: float | None = None
        self._prev_heading_ts_ms: int | None = None
        self._fef1_speed_seen = False

    def _apply_fee8(self, data_hex: str, ts: int) -> bool:
        att = decode_fee8_atx(data_hex)
        if not att:
            return False
        changed = False
        if "heading_deg" in att:
            hdg = att["heading_deg"]
            if self._prev_heading_deg is not None and self._prev_heading_ts_ms is not None:
                dt_s = (ts - self._prev_heading_ts_ms) / 1000.0
                if 0.0 < dt_s < 2.0:
                    self.fix.yaw_rate_deg_s = heading_delta_deg(hdg, self._prev_heading_deg) / dt_s
            self._prev_heading_deg = hdg
            self._prev_heading_ts_ms = ts
            self.fix.heading_deg = hdg
            changed = True
        if "pitch_deg" in att:
            self.fix.pitch_deg = att["pitch_deg"]
            changed = True
        if "altitude_m" in att:
            self.fix.altitude_m = att["altitude_m"]
            changed = True
        # FEE8 speed is often phantom on a stationary machine; prefer FEF1 when seen.
        if "speed_kmh" in att and not self._fef1_speed_seen:
            self.fix.speed_kmh = att["speed_kmh"]
            changed = True
        if changed:
            self.fix.source = self.fix.source or "atx_fee8"
        return changed

    def update_from_frame(
        self,
        *,
        sa_hex: str,
        pgn_hex: str,
        data_hex: str,
        timestamp_ms: int | None = None,
    ) -> GpsFix | None:
        sa = int(sa_hex, 16) if sa_hex.lower().startswith("0x") else int(sa_hex)
        pgn = int(pgn_hex, 16) if pgn_hex.lower().startswith("0x") else int(pgn_hex)
        changed = False
        ts = timestamp_ms if timestamp_ms is not None else int(time.time() * 1000)

        if sa == ATX_SA and pgn == PGN_FEF3:
            lat, lon = decode_fef3(data_hex, big_endian=self.big_endian, mode=self.latlon_mode)
            if lat is not None:
                if self.fix.heading_deg is None and self._prev_lat is not None and self._prev_lon is not None:
                    dist = abs(lat - self._prev_lat) + abs(lon - self._prev_lon)
                    if dist > 1e-7:
                        self.fix.heading_deg = bearing_deg(self._prev_lat, self._prev_lon, lat, lon)
                self._prev_lat, self._prev_lon = lat, lon
                self.fix.latitude = lat
                self.fix.longitude = lon
                self.fix.source = "atx_fef3"
                changed = True
        elif sa == ATX_SA and pgn == PGN_FEE8:
            changed = self._apply_fee8(data_hex, ts)
        elif sa == ATX_SA and pgn == PGN_FEE6:
            roll = decode_fee6_atx_roll(data_hex)
            if roll is not None:
                self.fix.roll_deg = roll
                self.fix.source = self.fix.source or "atx_fee6"
                changed = True
        elif sa == ATX_SA and pgn == PGN_FFFF:
            sats = decode_gnss_sats_ffff(data_hex)
            if sats is not None:
                self.fix.satellites = sats
                self.fix.source = self.fix.source or "atx_ffff"
                changed = True
        elif pgn == PGN_FEF1:
            spd = decode_speed_fef1(data_hex)
            if spd is not None:
                self._fef1_speed_seen = True
                self.fix.speed_kmh = spd
                changed = True

        if changed:
            self.fix.ts_ms = ts
            return self.fix
        return None

    def update_from_can_id(self, can_id: int, data: bytes, timestamp_ms: int | None = None) -> GpsFix | None:
        pgn = (can_id >> 8) & 0x3FFFF
        sa = can_id & 0xFF
        return self.update_from_frame(
            sa_hex=f"0x{sa:02X}",
            pgn_hex=f"0x{pgn:04X}" if pgn <= 0xFFFF else f"0x{pgn:X}",
            data_hex=data.hex(),
            timestamp_ms=timestamp_ms,
        )
