# AgValoniaGPS ↔ PUFworks function map

**AgValonia is not in the active workshop.** Full source on GitHub when needed:

https://github.com/paraquatsundae/AgValoniaGPS

Local UX/docs harvest: `General_files/Information/AgValonia_harvest/`  
Cannibalize notes: `docs/AGVALONIA_CANNIBALIZE.md`

Use this sheet to skip hunting — clone the repo, jump to the path in the AgValonia column.

---

## Capability crosswalk

| Capability | AgValonia (GitHub path / type) | PUFworks / PUF-mobile (live) | Notes |
| :--- | :--- | :--- | :--- |
| GPS UDP `:9999` `$PANDA`/`$PAOGI` | `UdpCommunicationService` → `NmeaParserServiceFast` → `GpsPipelineService` | **PUF-mobile:** `udpgpssource.cpp`, `gpsmodel.cpp` | Tablet listen path |
| CAN → NMEA (616R) | `JdGpsBridgeService` → `External/AGGPS/GPS_bridge/` | **isobus:** `scripts/gps_bridge.py`, `gps_bridge_lib.py`; hub NMEA relay; **PUF-mobile:** `bridge_to_tablet.ps1`, `cangpssource.*` | Canonical decoder = isobus |
| NMEA serial / BT / tablet GNSS | Mostly planned (`Plans/AndroidTablet/`) | **PUF-mobile:** `serialgpssource.*`, `btgpssource.*`, `tabletgpssource.*` | Mobile owns multi-source |
| Map / vehicle | Desktop `MainWindow.axaml` + Skia map | **PUF-mobile:** `FieldView.qml`, `PhoneMapView.qml` | |
| AB / guidance lines | `TrackGuidanceService`, `TrackFilesService`, `ABLineNudge*` | **PUF-mobile:** `AbLinesPage.qml`, `RunLinePopup.qml`, `farmstore` | AgValonia richer AOG tracks |
| Coverage record | `CoverageMapService` (RLE / job bitmap) | **PUF-mobile:** `coverage.cpp`, `CoverageRecorder.qml` (GeoJSON jobs) | |
| Section-on-coverage | `SectionControlService` | Mobile overlap notes in `DEV_NOTES.md` | ≠ vision spot-spray |
| Bus OBSERVE / telemetry | `ProcessImplementBusService`, `ImplementBusPanel` | **isobus:** `bus_engine.py`, **IsobusWifiHub**; **contracts:** `telemetry.v1.json` | |
| Authority / ARM | `MainViewModel.ImplementBusAuthority.cs` | **isobus / actuation:** `_tx_allowed()`, `SAFETY.md` | Boot OBSERVE |
| Section TX Goldacres / 616R | JD Phase 3 planned (not done) | **isobus:** DDI 141; 616R = GS + Pathway E only | Closed platform rules |
| Vision / GoB | `ProcessVisionEngineService`, `VisionBusBridge` | **vision:** `vision_engine.py`; **shell** bitmap bridge; **actuation** | Mobile does not run vision |
| Cab spawn / heartbeat | `PufworksHostService` | **shell:** spawn + `UI_HEARTBEAT` | |
| Gen4 shell / menus | `MainWindow.axaml`, `JDMenuOverlay`, `FloatingPanel` | Softkeys in **PUF-mobile** (`SoftKey.qml`); Electron **shell** | Harvest: `JD_UI_UX.md` |
| GlyphWordButtons | `GlyphButton.axaml`, `Plans/GlyphWordButtons/` | **PUF-mobile:** `SoftKey.qml`, `PageButton.qml` | Harvested locally |
| On-screen keyboard | `NumericKeyboardPanel`, `AlphanumericKeyboardPanel` | **PUF-mobile:** `NumberPad.qml` | |
| Farm / field / jobs | `FieldService`, `JobService`, `FieldJsonService` | **PUF-mobile:** `farmstore.*`, `jobstore.*`, setup pages | |
| ISOXML TaskData | `IsoXmlExporter`, `IsoXmlParserHelpers` | **PUF-mobile:** `taskdata.cpp` | |
| Implement width / offsets | `ToolConfiguration`, `VehicleConfig`, `ConfigurationViewModel` | **PUF-mobile:** `ImplementPage.qml`, `GpsInfoPage.qml` | |
| Direct MCU actuation | — | **actuation:** `actuation_engine.py` | AgValonia never owned this |
| IPC schemas | Consumed via External | **contracts:** `schemas/*.json` | |

---

## AgValonia-only (hunt these on GitHub)

| Topic | Where to look |
| :--- | :--- |
| Autosteer / Stanley | `Shared/.../AutoSteer/`, `AgOpen_Snapshot/` (`StanleyGuidanceService`) |
| YouTurn | `YouTurnGuidanceService`, `YouTurnStateMachine` |
| Tram lines | `TramLineService`, `TramLineOffsetService` |
| Headlands | `HeadlandBuilderService`, `HeadlandDetectionService` |
| Contour mode | `IsContourModeOn`, contour strip types |
| Tool kinematics | `ImplementSweptPath` |
| NTRIP | `NtripClientService`, `NtripProfileService` |
| AgShare cloud | `AgShareDownloaderService`, `AgShareUploaderService` |
| GPS heading fusion / tuning | `GpsHeadingFusionService`, `GpsPipelineService`, `Plans/IMU_HEADING_WIRING_PLAN.md` |
| Coverage bitmap internals | `CoverageMapService` |
| Gen4 overlays | `FloatingPanel`, `JDMenuOverlay`, `LayoutManagerOverlay` |

---

## GitHub folder shortcuts

```
Shared/AgValoniaGPS.Services/     GPS, coverage, section, ISOXML, vision/bus hosts
Shared/AgValoniaGPS.ViewModels/   MainViewModel*, ConfigurationViewModel
Shared/AgValoniaGPS.Views/        Gen4 panels, GlyphButton, keyboards
Platforms/AgValoniaGPS.Desktop/   MainWindow, DI
External/                         old vendored gps_bridge / isobus / vision
Plans/JohnDeereIntegration/       JD phases + JD_UI_UX.md
Plans/GlyphWordButtons/
AgOpen_Snapshot/                  legacy AgOpenGPS.Core archaeology
```

Clone:

```powershell
git clone https://github.com/paraquatsundae/AgValoniaGPS.git C:\Temp\AgValoniaGPS
```

Do **not** re-add to the multi-root workshop unless actively porting a feature.
