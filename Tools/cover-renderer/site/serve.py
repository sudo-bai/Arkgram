#!/usr/bin/env python3
"""Local static server for the archived rahoo.online app.

Vite uses browser-history routing, so unknown non-file paths fall back to index.html.
"""
from __future__ import annotations

import argparse
import http.server
import os
import socketserver
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def _send_json(self, status: int, payload: dict) -> None:
        import json
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        from urllib.parse import parse_qs, unquote, urlparse

        parsed = urlparse(self.path)
        request_path = parsed.path
        query = parse_qs(parsed.query)

        # Offline compatibility API. The original designer is entirely client-side;
        # these endpoints only cover the site's optional account/private-template features.
        if request_path == "/api/cover-templates":
            self._send_json(200, {"code": 200, "data": []})
            return
        if request_path == "/api/login":
            self._send_json(200, {"code": 503, "msg": "离线版不提供账号登录"})
            return
        if request_path == "/api/assets/get":
            name = (query.get("name") or [""])[0]
            cached = ROOT / "offline-api" / "assets" / unquote(name)
            if cached.is_file():
                self.path = "/" + cached.relative_to(ROOT).as_posix()
                return super().do_GET()
            self._send_json(404, {"msg": "该私有素材未包含在离线存档中"})
            return
        if request_path == "/api/cdn/url":
            self._send_json(200, {"success": False, "msg": "离线版不连接远程 CDN"})
            return

        fs_path = ROOT / request_path.lstrip("/")
        if request_path != "/" and not fs_path.exists() and not request_path.startswith("/assets/"):
            self.path = "/index.html"
        return super().do_GET()

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    url = f"http://127.0.0.1:{args.port}/"
    with Server(("127.0.0.1", args.port), Handler) as httpd:
        print(f"Rahoo 离线版已启动: {url}")
        print("按 Ctrl+C 停止。")
        if not args.no_browser:
            webbrowser.open(url)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n已停止。")


if __name__ == "__main__":
    main()
