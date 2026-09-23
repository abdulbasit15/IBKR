"""Local web server that serves the app and saves tags back to Excel.

`python -m journal serve` builds the app in server mode and hosts it so you can
edit Setups / Mistakes / Custom Tags per trade in the browser; each save writes
straight into the workbook (serialized with a lock; a backup is taken each time).
Pure standard library — no Flask.
"""
from __future__ import annotations

import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import config, excel_io, webapp

_lock = threading.Lock()


def _wb_mtime():
    try:
        return config.WORKBOOK.stat().st_mtime
    except OSError:
        return 0.0


def _rebuild(state):
    """Rebuild the served HTML from the current workbook (caches keep it fast)."""
    out = webapp.build_app(config.WORKBOOK, state["ai"], out=state["path"],
                           server=True)
    state["html"] = out.read_bytes()
    state["mtime"] = _wb_mtime()


def _make_handler(state: dict):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code, body, ctype="application/json"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?")[0]
            if path in ("/", "/index.html", "/TradeJournal.html"):
                # If the workbook changed on disk (e.g. you edited Tag Options
                # in Excel), rebuild so a browser refresh shows the update.
                if _wb_mtime() > state.get("mtime", 0):
                    with _lock:
                        try:
                            _rebuild(state)
                        except Exception:
                            pass
                self._send(200, state["html"], "text/html; charset=utf-8")
            else:
                self._send(404, b'{"error":"not found"}')

        def do_POST(self):
            if self.path not in ("/api/save-tags", "/api/save-rules"):
                self._send(404, b'{"error":"not found"}')
                return
            try:
                n = int(self.headers.get("Content-Length", 0))
                data = json.loads(self.rfile.read(n) or b"{}")
            except Exception:
                self._send(400, b'{"ok":false,"error":"bad request"}')
                return
            try:
                with _lock:
                    if self.path == "/api/save-rules":
                        excel_io.write_rules(data.get("hard", []),
                                             data.get("other", []))
                        _rebuild(state)
                        self._send(200, b'{"ok": true}')
                        return
                    from . import tags as _t
                    ident = {k: data.get(k) for k in
                             ("date", "time", "asset", "direction", "entry")}
                    values = {k: data.get(k, "") for k in _t.FIELD_KEYS if k in data}
                    ok = excel_io.update_tags(
                        ident, values, screenshot=data.get("screenshot"))
                    if ok:
                        _rebuild(state)   # so refresh / other clients see it too
                msg = {"ok": ok} if ok else {"ok": False, "error": "trade not found"}
                self._send(200, json.dumps(msg).encode())
            except PermissionError:
                self._send(200, json.dumps(
                    {"ok": False,
                     "error": "Workbook is open in Excel — close it and retry."}).encode())
            except Exception as e:
                self._send(200, json.dumps({"ok": False, "error": str(e)}).encode())

        def log_message(self, *a):
            pass
    return Handler


def serve(ai_text: str = "", host: str = "127.0.0.1", port: int = 8899,
          open_browser: bool = True) -> None:
    out = config.REPORTS_DIR / "TradeJournal.serve.html"
    webapp.build_app(config.WORKBOOK, ai_text, out=out, server=True)
    state = {"html": out.read_bytes(), "ai": ai_text, "path": out,
             "mtime": _wb_mtime()}

    httpd = None
    for p in range(port, port + 10):
        try:
            httpd = ThreadingHTTPServer((host, p), _make_handler(state))
            port = p
            break
        except OSError:
            continue
    if httpd is None:
        raise SystemExit("Could not bind a port in range.")

    url = f"http://{host}:{port}/"
    print(f"\n  Trade Journal is live at {url}")
    print("  Edit Setups / Mistakes / Custom Tags on any trade — saves to Excel.")
    print("  Keep the Excel workbook CLOSED while tagging.")
    print("  Press Ctrl+C to stop.\n")
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        httpd.shutdown()
