"""
keep_alive.py — سيرفر HTTP بسيط لتلبية شرط Render (Web Service يجب أن يستمع لمنفذ)
ويُستخدم أيضاً مع UptimeRobot لمنع نوم الخطة المجانية.
"""

import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("البوت يعمل ✅".encode("utf-8"))

    def log_message(self, format, *args):
        pass  # تعطيل سجلات الطلبات لتقليل الضجيج


def start() -> None:
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
