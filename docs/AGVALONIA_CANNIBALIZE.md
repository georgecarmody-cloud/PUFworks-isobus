# AgValoniaGPS — cannibalization map

AgValoniaGPS is **not** the product path for Clare Downs / PUFworks field work.
**Removed from the local workshop workspace (2026-07-19).** Source remains on GitHub.

| | |
| :--- | :--- |
| GitHub | https://github.com/paraquatsundae/AgValoniaGPS |
| Local harvest | `General_files/Information/AgValonia_harvest/` |
| Function map | [`AGVALONIA_FUNCTION_MAP.md`](AGVALONIA_FUNCTION_MAP.md) |

## Worth keeping (already harvested or live elsewhere)

| Asset | Status |
| :-- | :-- |
| GPS bridge + lib | **Live** in `PUFworks-isobus/scripts/` — not the AgValonia External copy |
| GlyphWordButtons / JD_UI_UX / Gen4 PDF | **Harvested** under `General_files/Information/AgValonia_harvest/` |
| Implement Bus panel pattern | **Replaced** by IsobusWifiHub + `bench-ui` |
| UDP `:9999` / `$PANDA` | **Live** in PUF-mobile + gps_bridge / hub NMEA |

## Low value — skip unless hunting on GitHub

Full Avalonia app, Perspectives, native C# CAN, vendored duplicate isobus tree, NTRIP/AgShare unless you adopt that ecosystem.

## Recommended stack

```
616R CAN → CANable (laptop)
         → IsobusWifiHub.exe  (or gps_bridge.exe)
         → WiFi UDP NMEA → PUF-mobile :9999
         → PUFworks-vision + isobus/actuation (spray)
```

## Action

- **Do not** invest in AgValonia Phase 3–5.
- **Do** use the function map when porting GPS/UI ideas from GitHub.
- **Do not** run `sync_external_isobus.ps1` for AgValonia — obsolete.
