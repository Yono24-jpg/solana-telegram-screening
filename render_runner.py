"""Continuous alert-only scanner with a lightweight Render health endpoint.

Credentials are read exclusively from environment variables. No wallet signing.
"""
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import bot

INTERVAL = max(15, int(os.getenv("SCAN_INTERVAL_SECONDS", "15")))
last = {"status": "starting", "checked_at": 0}

class Health(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in ("/", "/health"):
            self.send_error(404)
            return
        payload = ('{"service":"solana-screening","status":"%s"}' % last["status"]).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_):
        pass

def scanner():
    while True:
        started = time.monotonic()
        if not os.getenv("TELEGRAM_BOT_TOKEN") or not os.getenv("TELEGRAM_CHAT_ID"):
            last["status"] = "waiting_for_telegram_secrets"
        else:
            try:
                bot.main()
                last["status"] = "scan_completed"
            except Exception as exc:
                # Never print exceptions: HTTP errors may embed bot credentials.
                last["status"] = "scan_failed"
                print("SCAN_FAILED; inspect Telegram destination and API access", flush=True)
        last["checked_at"] = time.time()
        time.sleep(max(1, INTERVAL - (time.monotonic() - started)))

if __name__ == "__main__":
    threading.Thread(target=scanner, daemon=True).start()
    port = int(os.environ.get("PORT", "10000"))
    ThreadingHTTPServer(("0.0.0.0", port), Health).serve_forever()
