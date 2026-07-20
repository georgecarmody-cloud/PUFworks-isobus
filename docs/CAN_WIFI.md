# CAN WiFi — ISOBUS decode over UDP

## Primary: IsobusWifiHub (full bus_engine decode)

**Entry:** `scripts/isobus_wifi_gui.py` → **`dist\IsobusWifiHub\IsobusWifiHub.exe`**

Double-click the exe on the cab laptop (CANable on COM). Native Windows GUI:

1. Set **COM**, **Phone IP**, confirm NMEA relay
2. Press **START**
3. Tablet: GPS → UDP `9999` → Listen

Config: `isobus_wifi_config.json` beside the exe (OBSERVE / RX-only).

Headless (Pi / scripts): `IsobusWifiHub.exe --console` or `python scripts/isobus_wifi_hub.py hub`

Streams over UDP `:5578`:
- **telemetry** — TelemetryV1 (GWC/SRC/MNC/ATX liveness, speed, sections, GRC decode)
- **can_rx** — enriched with PGN name / category / SA label
- **log** — ISOBUS_LOG lines

Optional NMEA relay to tablet/AgIO on UDP `:9999` (same sentences as `gps_bridge`).

Build: `powershell -File scripts\build_isobus_wifi_hub.ps1`

---

## GPS-only path (no hub GUI)

When you only need StarFire → tablet NMEA and not full bus telemetry:

| Tool | Path |
| :--- | :--- |
| Standalone exe | `dist\gps_bridge.exe` / `PUF-mobile\dist\run_gps_bridge.bat` |
| Source | `scripts/gps_bridge.py` + `gps_bridge_lib.py` |
| Rebuild | `scripts\build_gps_bridge_exe.ps1` |

Prefer **IsobusWifiHub** when you want one cab app (GPS + bus status). Prefer **gps_bridge.exe** for a minimal laptop→tablet link.

---

## Legacy: raw CAN gateway (no bus_engine)

Lightweight **RX-only** raw frames. Entry: `scripts/isobus_wifi.py`  
Still used on **Pi** (`deploy/pi`). On Windows laptops this is **superseded** by IsobusWifiHub.

---

## Script inventory (keep / discard)

Decide before deleting. Recommendations:

| Item | Role | Decision |
| :--- | :--- | :--- |
| `isobus_wifi_gui.py` + hub modules | Operator GUI + orchestrator | **KEEP** |
| `build_isobus_wifi_hub.ps1` → `dist\IsobusWifiHub\` | Cab laptop app | **KEEP** |
| `gps_bridge.py` / `gps_bridge_lib.py` / `build_gps_bridge_exe.ps1` | Minimal NMEA bridge | **KEEP** |
| `PUF-mobile\bridge_to_tablet.ps1` / `run_bridge.bat` | Tablet launchers | **KEEP** |
| `PUF-mobile\bt_bridge.ps1` / `bt_gps_host.py` | Bluetooth NMEA alt | **KEEP** if BT still needed |
| `isobus_wifi.py` + `can_wifi_lib.py` | Pi raw gateway | **KEEP** (Pi) |
| ~~`build_can_wifi.ps1`~~ / ~~`isobus_wifi.spec`~~ | Windows lightweight exe build | **DISCARDED** (2026-07-19) |
| ~~`dist\isobus_wifi\`~~ | Old lightweight onedir build | **DISCARDED** (2026-07-19) — hub replaced it |
| Duplicate launchers that only wrap Python when exe exists | Convenience | **KEEP** one per path (hub bat optional) |

Do **not** discard `gps_bridge*` — tablet path (PUF-mobile) still uses it. Hub embeds the same decoder for NMEA relay.

---

## Wire protocol

**Port:** `5578` (default)  
**Transport:** UDP (multicast `239.255.42.1` or unicast)

CAN frame:

```json
{"schema":"CanWifiFrameV1","ts_ms":1718000000123,"id":"0x18FEF31C","ext":true,"dlc":8,"data":"AA BB CC DD EE FF 00 00"}
```

Heartbeat (1 Hz):

```json
{"schema":"CanWifiHeartbeatV1","ts_ms":1718000000123}
```

Client `--relay` emits bus_engine-compatible lines:

```
CAN_RX:{"id":"0x18FEF31C","is_ext":true,"dlc":8,"data":"...","ts":1718000000.123}
```

---

## Safety scope

- Gateway **never transmits** on CAN — read-only `bus.recv()` loop / OBSERVE.
- Intended for **GPS / bus monitoring / recorder feed** — same class as
  `SET_CAN_RX_ONLY:1` + `gps_bridge.py`.
- **Not** for section actuation or spray-critical control (WiFi latency/jitter).
- Full ISOBUS engine (`bus_engine.py`) remains required for Goldacres section TX
  with authority ladder.

---

## Pi deployment

See `deploy/pi/README.md` — SocketCAN `can0`, systemd unit, isolated HAT.

---

## Tablet / NMEA clients

Hub and `gps_bridge` send NMEA to UDP `:9999` for **PUF-mobile** (and any AgIO-compatible listener).

AgValoniaGPS is reference-only (not in the workshop). See `docs/AGVALONIA_FUNCTION_MAP.md` and GitHub https://github.com/paraquatsundae/AgValoniaGPS if you need the old Avalonia ingest notes.

---

## Related

| Path | Role |
| :-- | :-- |
| `scripts/gps_bridge.py` | Direct USB CAN → NMEA (no WiFi hub UI) |
| `bench/field_sniff_616r.py` | Full bus_engine recorder |
| `deploy/pi/can_wifi_gateway.json` | Pi config template |
| `PUFworks-site` | Fox Rockett visual language reference |
