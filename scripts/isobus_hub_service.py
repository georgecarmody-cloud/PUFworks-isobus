"""Background ISOBUS WiFi hub — start/stop from native GUI or CLI."""

from __future__ import annotations

import subprocess
import threading
import time
from typing import Callable

from isobus_wifi_hub import (
    HubRuntime,
    _log,
    enrich_can_rx,
    send_engine,
    setup_engine,
    spawn_engine,
    start_phone_web,
)


class HubService:
    """Runs bus_engine + UDP stream; exposes live state to a native UI."""

    def __init__(
        self,
        cfg: dict,
        *,
        enable_web: bool = False,
        on_log: Callable[[str], None] | None = None,
    ) -> None:
        self._cfg = dict(cfg)
        self._enable_web = enable_web
        self._on_log = on_log or _log
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.live = None
        self.runtime: HubRuntime | None = None
        self._proc = None
        self._web_server = None
        self._running = False

    @property
    def cfg(self) -> dict:
        if self.runtime is not None:
            return dict(self.runtime.cfg)
        return dict(self._cfg)

    @property
    def running(self) -> bool:
        return self._running

    def log(self, msg: str) -> None:
        self._on_log(msg)

    def start(self, cfg: dict | None = None) -> tuple[bool, str]:
        with self._lock:
            if self._running or (self._thread is not None and self._thread.is_alive()):
                return False, "Hub already running"
            if cfg is not None:
                self._cfg = dict(cfg)
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, daemon=True, name="hub-run")
            self._thread.start()
            return True, "Starting hub…"

    def stop(self, *, wait: bool = False, timeout: float = 3.0) -> None:
        """Signal hub to stop. Default is non-blocking so the Tk UI never freezes."""
        self._stop.set()
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                send_engine(proc, "STOP_CAN")
            except OSError:
                pass
            # Kick the stdout reader off its blocking readline.
            try:
                if proc.stdout:
                    proc.stdout.close()
            except OSError:
                pass
            try:
                if proc.stdin:
                    proc.stdin.close()
            except OSError:
                pass
            # Hard stop if the child ignores stdin close (common with busy CAN threads).
            try:
                proc.terminate()
            except OSError:
                pass

        if wait and self._thread is not None:
            self._thread.join(timeout=timeout)
            if self._thread.is_alive() and proc is not None and proc.poll() is None:
                try:
                    proc.kill()
                except OSError:
                    pass
                self._thread.join(timeout=1.0)
            self._thread = None

    def snapshot(self) -> dict:
        if self.live is None:
            return {}
        return self.live.snapshot()

    def apply_can(self) -> tuple[bool, str]:
        if self.runtime is None:
            return False, "Hub not running"
        ok, msg = self.runtime.apply_can()
        if ok:
            self.log(msg)
        return ok, msg

    def apply_network(self) -> tuple[bool, str]:
        if self.runtime is None:
            return False, "Hub not running"
        ok, msg = self.runtime.apply_network()
        if ok:
            self.log(msg)
        return ok, msg

    def apply_record_filter(self) -> tuple[bool, str]:
        if self.runtime is None:
            return False, "Hub not running"
        ok, msg = self.runtime.apply_record_filter()
        if ok:
            self.log(msg)
        return ok, msg

    def start_record(self, label: str = "") -> tuple[bool, str]:
        if self.runtime is None:
            return False, "Start the hub first"
        ok, msg = self.runtime.start_record(label)
        self.log(msg if ok else f"Error: {msg}")
        return ok, msg

    def stop_record(self) -> tuple[bool, str]:
        if self.runtime is None:
            return False, "Hub not running"
        ok, msg = self.runtime.stop_record()
        self.log(msg if ok else f"Error: {msg}")
        return ok, msg

    def merge_config(self, patch: dict) -> None:
        self._cfg.update(patch)
        if self.runtime is not None:
            self.runtime.merge_config(patch)

    def _shutdown_proc(self, proc: subprocess.Popen) -> None:
        if proc.poll() is not None:
            return
        try:
            send_engine(proc, "STOP_CAN")
        except OSError:
            pass
        time.sleep(0.15)
        try:
            if proc.stdin:
                proc.stdin.close()
        except OSError:
            pass
        try:
            if proc.stdout:
                proc.stdout.close()
        except OSError:
            pass
        try:
            proc.wait(timeout=1.5)
        except subprocess.TimeoutExpired:
            try:
                proc.terminate()
            except OSError:
                pass
            try:
                proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                except OSError:
                    pass
                try:
                    proc.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    pass

    def _run(self) -> None:
        import json

        from isobus_wifi_state import HubLiveState  # noqa: WPS433
        from isobus_wifi_stream import encode_heartbeat, encode_line  # noqa: WPS433

        live = HubLiveState()
        proc = spawn_engine()
        cfg = dict(self._cfg)
        runtime = HubRuntime(cfg, live, proc)
        self.live = live
        self.runtime = runtime
        self._proc = proc
        self._running = True

        web_cfg = dict(cfg)
        if not self._enable_web:
            web_cfg["web_enabled"] = False
        self._web_server = start_phone_web(
            web_cfg, live, runtime.make_callbacks() if self._enable_web else None
        )

        self.log(
            f"CAN {cfg.get('can_interface', 'COM2')} @ {cfg.get('can_bitrate', 250000)}"
        )
        stop = self._stop
        last_can_rx = 0.0

        def heartbeat_loop() -> None:
            while not stop.is_set():
                try:
                    runtime.publisher.send(encode_heartbeat())
                    send_engine(proc, "UI_HEARTBEAT")
                except OSError:
                    break
                stop.wait(1.0)

        def engine_reader() -> None:
            nonlocal last_can_rx
            try:
                stdout = proc.stdout
                if stdout is None:
                    return
                for raw in stdout:
                    if stop.is_set():
                        break
                    line = raw.rstrip("\n")
                    if line.startswith("TELEMETRY:"):
                        try:
                            payload = json.loads(line[len("TELEMETRY:"):])
                            runtime.publisher.send(encode_line("telemetry", payload))
                            live.push_telemetry(payload)
                        except Exception:
                            pass
                    elif line.startswith("CAN_RX:"):
                        try:
                            frame = json.loads(line[len("CAN_RX:"):])
                            enriched = enrich_can_rx(frame)
                            runtime.handle_can_rx(frame, enriched, runtime.publisher.send)
                            if runtime.stream_can_rx:
                                now = time.time()
                                interval = runtime.can_rx_interval
                                if not interval or (now - last_can_rx) >= interval:
                                    runtime.publisher.send(encode_line("can_rx", enriched))
                                    live.push_frame(enriched)
                                    last_can_rx = now
                        except Exception:
                            pass
                    elif line.startswith("[ISOBUS_LOG]") or line.startswith("[ISOBUS]"):
                        try:
                            runtime.publisher.send(encode_line("log", line))
                            live.push_log(line)
                            self.log(line)
                        except Exception:
                            pass
            except (OSError, ValueError):
                # stdout closed during stop — expected
                pass

        threading.Thread(target=heartbeat_loop, daemon=True, name="hub-heartbeat").start()
        threading.Thread(target=engine_reader, daemon=True, name="hub-engine-reader").start()
        try:
            setup_engine(proc, runtime.cfg)
        except OSError as exc:
            self.log(f"ERROR: failed to configure bus_engine: {exc}")
            stop.set()

        if not stop.is_set():
            mode = runtime.cfg.get("nmea_latlon_mode", "jd_atx")
            if bool(runtime.cfg.get("nmea_relay", True)) and runtime.cfg.get("unicast_client"):
                self.log(
                    f"NMEA → {runtime.cfg.get('unicast_client')}:"
                    f"{runtime.cfg.get('nmea_udp_port', 9999)}  "
                    f"latlon={mode}  (tablet: GPS → UDP listen)"
                )
            else:
                self.log("WARNING: Phone IP empty — NMEA relay disabled until set")
            self.log(f"Hub running (FEF3 decode={mode})")

        try:
            while not stop.is_set() and proc.poll() is None:
                time.sleep(0.15)
            if not stop.is_set() and proc.poll() is not None:
                self.log(
                    f"ERROR: bus_engine exited (code {proc.returncode}) — WiFi stream stopped"
                )
        finally:
            stop.set()
            self._shutdown_proc(proc)
            try:
                runtime.publisher.close()
            except Exception:
                pass
            if runtime._nmea_sock:
                try:
                    runtime._nmea_sock.close()
                except OSError:
                    pass
            if self._web_server is not None:
                try:
                    self._web_server.shutdown()
                except Exception:
                    pass
            self._running = False
            self.live = None
            self.runtime = None
            self._proc = None
            self._web_server = None
            self.log("Hub stopped")
