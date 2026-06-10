"""
GreenSeeker serial emitter for PUFVision.

John Deere Gen 4/5 GreenStar displays expose a sanctioned "GreenSeeker"
prescription rate source over RS232 (COM Port 2 on the GreenStar side, with the
master switch armed in AUX). The display ships a fixed parser, so by speaking
GreenSeeker's serial language we can feed PUFVision's vision-derived target rate
into the 616R as a native prescription -- without touching John Deere's
protected CAN.

--- CONFIRMED FROM HARDWARE / DOCUMENTATION (2026-06) -----------------------
Link layer (Trimble GreenSeeker RT200 Install & Operation Guide, "Data output"):
  * RS-232, 38400 baud, 8 data bits, No parity, 1 stop bit  (38400-8N1).
  * ASCII text, one line per sample.
  * Each line carries the NDVI value and a second user-selected VI value.
  * Selected V.I. default = NDVI; Data Format must be "RT200" for live VRA
    (other formats on the RT200 are simulation-only).
  * Update cadence: 1 Hz = 495 ms, 2 Hz = 245 ms, 5 Hz = 200 ms.

JD display ingest contract (GreenStar COM Port 2 Diagnostics page):
  * Device Type   : "N-Sensing"
  * Manufacturer  : "GreenSeeker"
  * "RC Message"  : required from the GreenSeeker control unit for operation;
                    goes Active when the display is receiving our data.
  * Target Rate Dry / Target Rate Wet : the display ingests a FINISHED target
    rate (dry = granular, wet = liquid), NOT raw NDVI. The NDVI -> rate crop
    algorithm (historically Trimble RT Commander) is therefore OUR job; we emit
    the computed rate as the RC message.
  * "Last Message Received" : staleness watchdog on the display side.

STILL PENDING: the exact byte/field framing of the GreenSeeker "RC Message"
(target-rate sentence) the display parses. The link parameters around it are
confirmed; only the sentence layout needs a real serial capture. When captured,
it drops in as a single GreenSeekerProtocol subclass with no other changes.

This module is Windows-native (pyserial on a COMx port) and has no Linux/Jetson
dependency.
"""

import threading
import time
from dataclasses import dataclass

try:
    import serial  # pyserial
    HAS_SERIAL = True
except ImportError:
    HAS_SERIAL = False


# --- Sample payload -----------------------------------------------------------

@dataclass
class GreenSeekerSample:
    """One emission's worth of data handed to a protocol encoder.

    rate_l_ha is the single PUFVision target rate. rate_wet / rate_dry are the
    two channels the JD COM2 page exposes (liquid / granular); for a liquid-only
    sprayer like Clare Downs, wet == rate_l_ha and dry mirrors it unless a
    separate granular channel is ever wired.
    """
    rate_l_ha: float = 0.0
    rate_wet: float = 0.0
    rate_dry: float = 0.0
    ndvi: float = 0.0
    vi2: float = 0.0          # second user-selected VI (RT200 emits NDVI + VI2)
    speed_kmh: float = 0.0


# --- Pluggable protocol layer -------------------------------------------------

class GreenSeekerProtocol:
    """Base class for a GreenSeeker-compatible serial framing."""

    name = "base"

    def encode(self, sample: GreenSeekerSample) -> bytes:
        raise NotImplementedError


class GenericNdviProtocol(GreenSeekerProtocol):
    """
    Placeholder ASCII frame used until the real RT200 target-rate frame is
    captured. Emits a NMEA-style, comma-delimited, CR/LF-terminated sentence:

        $PUFGS,<ndvi>,<rate_l_ha>*<checksum>\r\n

    The checksum is the XOR of all characters between '$' and '*' (NMEA-0183
    convention), which most ASCII ag parsers tolerate or ignore. Swap this class
    out for the verified GreenSeeker frame once a capture is available.
    """

    name = "generic_ndvi"

    def encode(self, sample: GreenSeekerSample) -> bytes:
        body = f"PUFGS,{sample.ndvi:.2f},{sample.rate_l_ha:.1f}"
        checksum = 0
        for ch in body:
            checksum ^= ord(ch)
        sentence = f"${body}*{checksum:02X}\r\n"
        return sentence.encode("ascii")


class RT200Protocol(GreenSeekerProtocol):
    """
    Trimble GreenSeeker RT200 "Data Format: RT200" line emitter.

    DOCUMENTED (confirmed): the RT200 streams one ASCII line per sample at
    38400-8N1, ~1 Hz (495 ms), each line containing the NDVI value and a second
    user-selected VI value. The precise delimiter set, leading token and any
    embedded GPS/rate fields of the genuine RT200 line are NOT yet captured, so
    the line below is a best-effort reconstruction and MUST be validated against
    a real capture before field use.

    Reconstructed line (placeholder ordering):

        <ndvi>,<vi2>,<rate_wet>,<rate_dry>\r\n

    Once the genuine "RC Message" framing is captured, finalise this method (or
    add a sibling subclass) -- the emitter, IPC and UI need no further change.
    """

    name = "rt200"

    def encode(self, sample: GreenSeekerSample) -> bytes:
        # NOTE: field order/delimiters are unverified. See class docstring.
        line = (
            f"{sample.ndvi:.3f},{sample.vi2:.3f},"
            f"{sample.rate_wet:.1f},{sample.rate_dry:.1f}\r\n"
        )
        return line.encode("ascii")


# Registry so the UI/IPC can select a protocol by name.
PROTOCOLS = {
    GenericNdviProtocol.name: GenericNdviProtocol,
    RT200Protocol.name: RT200Protocol,
}


# --- Emitter ------------------------------------------------------------------

class GreenSeekerEmitter:
    """
    Background 1 Hz emitter that pushes the current target rate out a COM port
    using the selected GreenSeeker protocol.

    Providers are callables so the emitter stays decoupled from the engine:
      - rate_provider()  -> float  target application rate (L/ha)
      - ndvi_provider()  -> float  greenness / NDVI proxy (0..1), optional
      - speed_provider() -> float  ground speed km/h, optional (safety interlock)
    """

    def __init__(self, rate_provider, ndvi_provider=None, speed_provider=None,
                 detection_provider=None, logger=None):
        self._rate_provider = rate_provider
        self._ndvi_provider = ndvi_provider or (lambda: 0.0)
        self._speed_provider = speed_provider or (lambda: None)
        # detection_provider() -> bool: True if the boom currently sees a weed
        # anywhere across its width. Defaults to always-True so that enabling
        # blanking without a provider fails SAFE (keeps spraying, never blanks).
        self._detection_provider = detection_provider or (lambda: True)
        self._log = logger or (lambda msg: print(f"[GREENSEEKER] {msg}", flush=True))

        # Config (thread-safe via _lock)
        self._lock = threading.Lock()
        self.enabled = False
        self.port = "COM3"
        self.baud = 38400           # confirmed GreenSeeker RT200 link rate
        self.protocol_name = GenericNdviProtocol.name
        self.rate_hz = 1.0          # GreenSeeker streams target rate at ~1 Hz (495 ms)
        self.min_rate = 0.0
        self.max_rate = 300.0
        self.zero_when_stopped = True  # interlock: no movement -> rate 0

        # --- Pathway E: whole-boom blanking ("section via rate") ---
        # When the boom sees clean ground, drive the serial rate to blank_rate
        # (0) so the JD display applies nothing; when a weed is seen, emit the
        # normal target rate. A trailing hold prevents chatter and gives spray
        # overlap. This is the only fail-safe "section-like" control available
        # on the 616R through the sanctioned serial path: it can only ever
        # SUBTRACT application over clean ground, never add it.
        self.boom_blanking = False
        self.blank_rate = 0.0          # L/ha applied when blanked (clean ground)
        self.blank_hold_s = 0.7        # keep spraying this long after last detection

        # Runtime state
        self._serial = None
        self._thread = None
        self._running = False
        self._link_state = "closed"  # closed | open | error
        self._last_error = ""
        self._last_frame = ""
        self._last_rate = 0.0
        self._last_tx_time = 0.0
        self._last_detect_time = 0.0
        self._blank_state = "off"    # off | spraying | blanked

    # -- lifecycle --
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        self._close_port()

    # -- config setters --
    def set_enabled(self, enabled: bool):
        with self._lock:
            self.enabled = bool(enabled)
        if not enabled:
            self._close_port()
        self._log(f"emitter {'enabled' if enabled else 'disabled'}")

    def set_port(self, port: str):
        with self._lock:
            changed = port != self.port
            self.port = port
        if changed:
            self._close_port()  # reopen on next cycle with new port
        self._log(f"port set to {port}")

    def set_baud(self, baud: int):
        with self._lock:
            changed = baud != self.baud
            self.baud = int(baud)
        if changed:
            self._close_port()
        self._log(f"baud set to {baud}")

    def set_protocol(self, name: str):
        with self._lock:
            if name in PROTOCOLS:
                self.protocol_name = name
                self._log(f"protocol set to {name}")
            else:
                self._log(f"unknown protocol '{name}' (have: {list(PROTOCOLS)})")

    def set_rate_limits(self, min_rate=None, max_rate=None):
        with self._lock:
            if min_rate is not None:
                self.min_rate = float(min_rate)
            if max_rate is not None:
                self.max_rate = float(max_rate)

    def set_boom_blanking(self, enabled: bool):
        with self._lock:
            self.boom_blanking = bool(enabled)
        self._log(f"boom blanking {'ON (rate->0 over clean ground)' if enabled else 'OFF'}")

    def set_blank_params(self, blank_rate=None, hold_s=None):
        with self._lock:
            if blank_rate is not None:
                self.blank_rate = max(0.0, float(blank_rate))
            if hold_s is not None:
                self.blank_hold_s = max(0.0, float(hold_s))
        self._log(f"blank params: rate={self.blank_rate} L/ha, hold={self.blank_hold_s}s")

    # -- status for telemetry --
    def get_status(self) -> dict:
        with self._lock:
            return {
                "gs_enabled": self.enabled,
                "gs_port": self.port,
                "gs_baud": self.baud,
                "gs_protocol": self.protocol_name,
                "gs_link_state": self._link_state,
                "gs_last_error": self._last_error,
                "gs_last_frame": self._last_frame,
                "gs_last_rate": round(self._last_rate, 1),
                "gs_last_tx_age": round(time.time() - self._last_tx_time, 2)
                                  if self._last_tx_time else None,
                "gs_serial_available": HAS_SERIAL,
                "gs_boom_blanking": self.boom_blanking,
                "gs_blank_rate": round(self.blank_rate, 1),
                "gs_blank_hold_s": round(self.blank_hold_s, 2),
                "gs_blank_state": self._blank_state,
            }

    # -- internals --
    def _close_port(self):
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:
                pass
        self._serial = None
        self._link_state = "closed"

    def _open_port(self) -> bool:
        if not HAS_SERIAL:
            self._link_state = "error"
            self._last_error = "pyserial not installed"
            return False
        try:
            with self._lock:
                port, baud = self.port, self.baud
            self._serial = serial.Serial(
                port=port,
                baudrate=baud,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0,
                write_timeout=0.5,
            )
            self._link_state = "open"
            self._last_error = ""
            self._log(f"opened {port} @ {baud}-8N1")
            return True
        except Exception as e:
            self._serial = None
            self._link_state = "error"
            self._last_error = str(e)
            self._log(f"failed to open port: {e}")
            return False

    def _build_sample(self) -> GreenSeekerSample:
        try:
            rate = float(self._rate_provider())
        except Exception:
            rate = 0.0

        with self._lock:
            lo, hi = self.min_rate, self.max_rate
            blanking = self.boom_blanking
            blank_rate = self.blank_rate
            hold_s = self.blank_hold_s

        # Pathway E: whole-boom blanking. If clean ground (no detection within
        # the trailing hold window), force the blank rate; otherwise spray the
        # target rate. Decided BEFORE the speed interlock/clamp below.
        blanked = False
        if blanking:
            try:
                detected = bool(self._detection_provider())
            except Exception:
                detected = True  # provider failure -> fail safe (keep spraying)
            now = time.time()
            if detected:
                self._last_detect_time = now
            spraying = (now - self._last_detect_time) <= hold_s
            if not spraying:
                rate = blank_rate
                blanked = True
            self._blank_state = "blanked" if blanked else "spraying"
        else:
            self._blank_state = "off"

        # Safety interlock: no ground speed -> no rate.
        try:
            spd = self._speed_provider()
            spd = float(spd) if spd is not None else 0.0
        except Exception:
            spd = 0.0
        if self.zero_when_stopped and spd <= 0.0:
            rate = 0.0

        # Clamp. When blanked, allow the floor to drop to 0 (don't re-apply the
        # min-rate floor over clean ground); otherwise honour the configured min.
        if blanked:
            rate = max(0.0, min(hi, rate))
        else:
            rate = max(lo, min(hi, rate))

        try:
            ndvi = float(self._ndvi_provider())
        except Exception:
            ndvi = 0.0

        # Liquid sprayer (Clare Downs): the single PUFVision rate is the "wet"
        # channel; dry mirrors it until a separate granular channel is wired.
        return GreenSeekerSample(
            rate_l_ha=rate,
            rate_wet=rate,
            rate_dry=rate,
            ndvi=ndvi,
            vi2=ndvi,
            speed_kmh=spd,
        )

    def _loop(self):
        while self._running:
            with self._lock:
                enabled = self.enabled
                hz = self.rate_hz if self.rate_hz > 0 else 1.0
                proto_cls = PROTOCOLS.get(self.protocol_name, GenericNdviProtocol)
            period = 1.0 / hz

            if not enabled:
                time.sleep(period)
                continue

            if self._serial is None:
                if not self._open_port():
                    time.sleep(1.0)  # back off before retrying a bad port
                    continue

            try:
                sample = self._build_sample()
                frame = proto_cls().encode(sample)
                self._serial.write(frame)
                self._last_frame = frame.decode("ascii", errors="replace").strip()
                self._last_rate = sample.rate_l_ha
                self._last_tx_time = time.time()
                self._link_state = "open"
            except Exception as e:
                self._last_error = str(e)
                self._link_state = "error"
                self._log(f"write error: {e}")
                self._close_port()
                time.sleep(0.5)

            time.sleep(period)
