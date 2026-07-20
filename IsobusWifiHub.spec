# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['scripts\\isobus_wifi_gui.py'],
    pathex=[],
    binaries=[],
    datas=[('record_filter_lib.py', '.'), ('bus_engine.py', '.'), ('greenseeker_emitter.py', '.'), ('sniff_616r.py', '.'), ('spray_pgn_library.py', '.'), ('contract_import.py', '.'), ('library', 'library'), ('C:\\Projects\\PUFworks-contracts\\python\\pufworks_contracts', 'pufworks_contracts')],
    hiddenimports=['can', 'can.interface', 'can.interfaces.slcan', 'can.interfaces.pcan', 'can.interfaces.socketcan', 'can.interfaces.virtual', 'serial', 'serial.tools.list_ports', 'bus_engine', 'greenseeker_emitter', 'sniff_616r', 'spray_pgn_library', 'contract_import', 'pufworks_contracts', 'isobus_wifi_hub', 'isobus_hub_service', 'isobus_wifi_web', 'isobus_wifi_state', 'isobus_wifi_stream', 'can_wifi_lib', 'gps_bridge_lib', 'record_filter_lib', 'isobus_record_filter_ui'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='IsobusWifiHub',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='IsobusWifiHub',
)
