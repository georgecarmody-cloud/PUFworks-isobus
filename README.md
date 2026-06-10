# PUFworks-isobus

Standalone CAN / ISOBUS engine for the PUFworks sprayer stack. Extracted from
the PUFVision monolith (tag `v1-monolith-baseline`) per `BOUNDARY.md` Phase 1.

**Bus-only**: no camera, no OpenCV, no YOLO. Section intent arrives as
`SectionBitmapV1` messages from `PUFworks-vision` (or the bench harness);
everything this repo does is decide what is allowed onto the wire.

Read `SAFETY.md` and `JD_ISOBUS_MAP.md` before changing any TX behaviour.

## Layout

```
bus_engine.py            # ISOBUSController + stdin/stdout line protocol (the engine)
greenseeker_emitter.py   # 616R sanctioned serial rate path (Pathway G) + boom blanking (E)
bench/bench_harness.py   # heartbeat + test-vector driver for virtual-bus smoke tests
JD_ISOBUS_MAP.md         # authoritative ISOBUS architecture & field decisions
requirements.txt
recordings/              # OBSERVE/SHADOW session captures (gitignored)
```

## Quick start (bench, no hardware)

```powershell
pip install -r requirements.txt
python bench/bench_harness.py            # spawns bus_engine on the virtual bus
```

The harness starts the engine, sends `SET_CAN_INTERFACE:virtual` + `START_CAN`,
raises authority to `SHADOW`, sends `UI_HEARTBEAT` at 1 Hz, publishes
`SectionBitmapV1` test vectors at 10 Hz, and prints decoded telemetry.

To drive the engine manually:

```powershell
python bus_engine.py
# then type commands:
START_CAN
SET_CAN_INTERFACE:virtual
SET_CONTROL_AUTHORITY:SHADOW
UI_HEARTBEAT
VISION_BITMAP:{"schema":"SectionBitmapV1","ts_ms":0,"seq":1,"section_count":10,"bitmap":"0x3","source":"manual"}
```

## Wire protocol

- **stdin -> engine**: the `ControlCommandV1` line set (legacy colon form, e.g.
  `SET_CONTROL_AUTHORITY:SHADOW`), plus `VISION_BITMAP:{json}` for the 10-20 Hz
  `SectionBitmapV1` feed. Contracts live in `PUFworks-contracts`.
- **engine -> stdout**: `TELEMETRY:{TelemetryV1 json}` at 10 Hz, `CAN_RX:{json}`
  raw frame stream, `[ISOBUS_LOG]` events.

Commands belonging to vision/agronomy (camera, capture, HSV, prescription) are
rejected by the engine — see `bus_engine.py` tail and BOUNDARY.md §4.5.

## What changed vs the monolith

| Monolith | Here |
|---|---|
| `update_vision_sections()` read `camera.cached_boxes` in-process | `ingest_vision_bitmap()` consumes `SectionBitmapV1`; >300 ms staleness closes all sections and demotes |
| `NOZZLE_CMD`, `SET_ENGINE_SIDE_SECTIONS` | Removed (deprecated; rejected at the parser) |
| `SET_PRESCRIPTION_*` / greenness-driven rate | Deferred — `target_rate_l_ha` stays 0 until `RateCommandV1` exists (BOUNDARY §4.7) |
| MyOps CSV logger | Dropped (vision-derived; recorder covers bus capture) |
| Camera/vision IPC commands | Not ported — rejected with a log line |

Everything else — authority ladder, interlocks, sprayer profiles, GRC EF00
decode, VT handshake, TC announce, recorder, GreenSeeker emitter — is ported
verbatim ("move first, refactor second").
