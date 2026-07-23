# PUFworks-isobus

```
████  █   █ █████ █   █  ███  ████  █   █  ████   
█░░░█ █░  █░█░░░░░█░  █░█ ░░█ █░░░█ █░ █ ░█ ░░░░  
████░░█░░ █░████░░█░█ █░█░ ░█░████░░███ ░ ░███░░░ 
█░░░░ █░░ █░█░░░░ ██░██░█░░ █░█░░█░ █░░█ ░  ░░█   
█░░░░░ ███ ░█░░░░░█░░ █░░███ ░█░░░█░█░░░█ ████░░  
 ░░     ░░░ ░░░    ░░░ ░░ ░░░ ░░░  ░ ░░  ░ ░░░░ ░ 
  ░      ░░░  ░     ░   ░  ░░░  ░   ░ ░   ░ ░░░░  

                                                                                
                                                                                
                                                                                
                                                                                
                                                                                
                              .=*****=. :@@=                                    
                            .----.-%@@@@@#=@@@= .-                              
                            .:=@@@@@@@@@@@@@@@@@.*@:                            
                       *@@@@@@@@@@@@@@@@@@@@@@@@@=@@:                           
                    *@@*+@@@@@@@@@@@@@@@@@@@@@@@@@@@@                           
                    .=@@@@@@@@%++++++++#%@+%@@%#@@@@@.                          
                   *- #@@@@*+*%@@@@@@@#++++++@@*%@@@@@@*:                       
                    -@@@@++#@%*+++++++%@++++++@#*@@*+*@@@@@@+                   
                   *@@@#++%++*%@@@@@@#++#+++++*%+@%++#@*++*@@*                  
                  +@@@*++++#@@@%+-=%@@@%+++++++%+#+++*++*%%*@#                  
                  @@@*++++@@@.        %@@++++++*++++++*@@@@@@#                  
                 +@@%++++%@*           *@%+++++++++++*@#   .@@.                 
                .%@@+++++@%   =@@#      @@+++++++++++@#     -@#                 
             .=@@@@+.=+++@+ .@@@*  .    =@+++++++++++@.%@:  .@#                 
         -@@@@@@%.   .+++@* =@@@@@@%    +@++++++*%%#+@@@@:+ .@#                 
            -@@:-%.    -+@@.-@@@@@@*    @#+++*@#++++%@@@@@% -@+                 
           :@@#@#    --+##@@:=@@@@%.   @%+++%+++++++++@@@@=:@%                  
          .@@@@@.   .%++++++%@+.    .#@++++++++++++++++@@.+@@@@.                
          .@@@@#    =+++@@#+++++#%%#++++++++++++%%*++++++@@*+#@+                
          .@#*@% .  :+++++#@@%*++++++++++++++++*@@@@%++++++%@@#                 
           : =@@#%.  .=+++++#@@#@@@@%#*++++++++++++++++++++++#@%.               
              +@@@@:    .-+++++%@#. .:=#@@@@@@%#*++++++++++++++@@:              
               :@@@@@-     .*+++++%@@#-   .....=%@@@@@%++++++++%@=              
                 . .@@@@%:. .@%++++++*%@@#:...-=*##*%@@@@@@#+++@@-              
                    #@@%.    :@@@@%*+++++++*%%%%%#*+++#@@@@@@@@@*               
                    :@@@=     +@@@@@@@@@%#**+++++*#@@@*     .%#.                
                     #@@@.     #@@@@@@@@@@@@@@@@@@*:                            
                      %@@%     .%@@@@@@@@@@@@-                                  
                      .@@@#      %@@@@@@@@@@@                                   
                       #@@@=      #@@@@@@@@@@-                                  
                        @@@@.      =@@@@@@@@@*                                  
                         @@@%        %@@@@@@@%                                  
                         .@@@#        .@@@@@@@=                                 
                          -@@@+         :@@@@@%                                 
                           #@@@:          .@@@@=                                
                           .@@@%            +@@@:                               
                            .@@@*            %@@%                               
                             -@@@=           .@@@*                              
```

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

## Spray PGN library (monitor + recorder + CSV export)

Curated filter for **GPS/motion**, **rate/section**, **flow/pressure**, **boom height**,
and **proprietary spray** traffic. Source of truth:

- **`library/SPRAY_DECODE.md`** — human decode ledger (JD controller names: SRC, MNC, GRC.001, …)
- **`library/section_map.json`** — confirmed 11-section SRC `4F0B06` map (R5–L5)
- `spray_pgn_library.py` / `library/spray_pgn_library.json` — machine catalog + recorder filter
- `library/field_observations.json` — merged session stats (`compile_pgn_catalog.py`)
- Recorder: `SET_SNIFF_MODE:spray` (default when profile is `jd_616r`)
- Bench UI: **Spray library only** preset + per-category toggles + **Export CSV**
- Post-session catalog merge: `python scripts/compile_pgn_catalog.py`

Exported `frames.csv` columns match the recorder:

`timestamp_ms, dir, can_id, sa_hex, sa_dec, sa_label, pgn_hex, pgn_dec, pgn_name, category, da_hex, dlc, data_hex`

## 616R field sniff (tomorrow-ready)

**OBSERVE only** — zero CAN TX. Uses `SET_CAN_RX_ONLY:1` to seal all transmit
paths (required when the adapter firmware allows TX, e.g. **CANable 2.0 on COM2**).

Connect to the implement ISOBUS connector (X119, **250 kbps** classic CAN — configure
CANable for 250k classic, not CAN-FD, for this tap).

```powershell
# CANable on COM2 (default) — records + spray PGN filter + RX-only seal
.\scripts\field_sniff_616r.ps1 -Interface COM2 -Label "616r_spray_am" -Record

# Unfiltered discovery capture (larger files — use if roster mode misses traffic)
python bench/field_sniff_616r.py --interface pcan --sniff-mode 616r_full --record --label 616r_full

# After the pass
python scripts/analyze_616r_session.py recordings\<session_id>
```

Bench UI alternative: set profile **jd_616r**, sniff mode **616r** or **616r_full**,
authority **OBSERVE**, start CAN, then **● Start** recorder.

Correlate with image capture: `PUFworks-agronomy` collector writes
`session_epoch_ms.txt` in each `colN_DDMMYY/` folder — match timestamps against
recorder `frames.csv` `timestamp_ms`.

## CAN WiFi hub (full ISOBUS decode)

Stream **full `bus_engine` decode** (TelemetryV1, enriched CAN_RX, logs) over UDP.
**RX-only / OBSERVE** — GPS and monitoring, not section actuation.

```powershell
# Build standalone exe (double-click on laptop)
powershell -ExecutionPolicy Bypass -File scripts\build_isobus_wifi_hub.ps1

# Edit COM port in dist\IsobusWifiHub\isobus_wifi_config.json
dist\IsobusWifiHub\IsobusWifiHub.exe

# Cab tablet / second laptop
dist\IsobusWifiHub\IsobusWifiHub.exe client --gps --status
```

See `docs/CAN_WIFI.md` (hub protocol) and `deploy/pi/README.md` (Pi CAN HAT).

Legacy raw-CAN-only path (GPS without full decode): `scripts/isobus_wifi.py`.

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
