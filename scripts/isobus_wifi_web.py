"""HTTP server for ISOBUS WiFi dashboard + admin configuration UI."""

from __future__ import annotations

import json
import mimetypes
import socket
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from isobus_wifi_state import HubLiveState


def lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


def list_com_ports() -> list[str]:
    try:
        from serial.tools import list_ports  # noqa: WPS433

        return sorted(p.device for p in list_ports.comports())
    except Exception:
        return []


@dataclass
class HubCallbacks:
    """Runtime hooks from isobus_wifi_hub into the web admin API."""

    load_config: Callable[[], dict]
    save_config: Callable[[dict], tuple[bool, str]]
    apply_can: Callable[[], tuple[bool, str]]
    restart_can: Callable[[], tuple[bool, str]]
    apply_network: Callable[[], tuple[bool, str]] = field(
        default=lambda: (True, "Network unchanged")
    )


def make_handler(
    state: HubLiveState,
    static_dir: Path,
    hub_info: dict,
    callbacks: HubCallbacks | None,
):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # noqa: A003 — stdlib name
            return

        def _cors(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")

        def _send_json(self, obj: dict, code: int = 200) -> None:
            body = json.dumps(obj, separators=(",", ":")).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self._cors()
            self.end_headers()
            self.wfile.write(body)

        def _send_file(self, path: Path) -> None:
            if not path.is_file():
                self.send_error(404)
                return
            data = path.read_bytes()
            ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(data)

        def _read_json_body(self) -> dict:
            length = int(self.headers.get("Content-Length", 0))
            if length <= 0:
                return {}
            raw = self.rfile.read(length)
            return json.loads(raw.decode("utf-8"))

        def do_OPTIONS(self) -> None:  # noqa: N802
            self.send_response(204)
            self._cors()
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                self._send_file(static_dir / "index.html")
                return
            if path in ("/admin", "/admin.html"):
                self._send_file(static_dir / "admin.html")
                return
            if path.startswith("/static/"):
                rel = path[len("/static/") :]
                target = (static_dir / rel).resolve()
                if not str(target).startswith(str(static_dir.resolve())):
                    self.send_error(403)
                    return
                self._send_file(target)
                return
            if path == "/api/snapshot":
                snap = state.snapshot()
                snap["hub"] = hub_info
                self._send_json(snap)
                return
            if path == "/api/info":
                self._send_json({"hub": hub_info, "lan_ip": hub_info.get("lan_ip")})
                return
            if path == "/api/config":
                cfg = callbacks.load_config() if callbacks else {}
                self._send_json(
                    {
                        "config": cfg,
                        "com_ports": list_com_ports(),
                        "lan_ip": hub_info.get("lan_ip"),
                        "config_path": hub_info.get("config_path", ""),
                    }
                )
                return
            self.send_error(404)

        def do_POST(self) -> None:  # noqa: N802
            if callbacks is None:
                self._send_json({"ok": False, "error": "Admin API unavailable"}, 503)
                return
            path = self.path.split("?", 1)[0]
            try:
                body = self._read_json_body()
            except json.JSONDecodeError:
                self._send_json({"ok": False, "error": "Invalid JSON"}, 400)
                return

            if path == "/api/config":
                patch = body.get("config", body)
                ok, msg = callbacks.save_config(patch)
                self._send_json({"ok": ok, "message": msg, "config": callbacks.load_config()})
                return
            if path == "/api/can/apply":
                ok, msg = callbacks.apply_can()
                self._send_json({"ok": ok, "message": msg})
                return
            if path == "/api/can/restart":
                ok, msg = callbacks.restart_can()
                self._send_json({"ok": ok, "message": msg})
                return
            if path == "/api/network/apply":
                ok, msg = callbacks.apply_network()
                self._send_json({"ok": ok, "message": msg})
                return
            self.send_error(404)

    return Handler


class PhoneWebServer:
    def __init__(
        self,
        state: HubLiveState,
        static_dir: Path,
        host: str,
        port: int,
        hub_info: dict,
        callbacks: HubCallbacks | None = None,
    ) -> None:
        self.state = state
        self.host = host
        self.port = port
        self._hub_info = dict(hub_info)
        self._hub_info["lan_ip"] = lan_ip()
        self._hub_info["web_port"] = port
        handler = make_handler(state, static_dir, self._hub_info, callbacks)
        self._httpd = ThreadingHTTPServer((host, port), handler)

    @property
    def lan_ip(self) -> str:
        return self._hub_info["lan_ip"]

    @property
    def url(self) -> str:
        return f"http://{self.lan_ip}:{self.port}/"

    @property
    def admin_url(self) -> str:
        return f"http://{self.lan_ip}:{self.port}/admin"

    def update_hub_info(self, patch: dict) -> None:
        self._hub_info.update(patch)

    def start_background(self) -> None:
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()

    def shutdown(self) -> None:
        self._httpd.shutdown()
