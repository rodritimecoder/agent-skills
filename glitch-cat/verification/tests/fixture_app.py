#!/usr/bin/env python3
"""Fixture app for the verification gate: one mobile cut-off button, one silent
checkout failure, one healthy page, and a two-story Storybook index."""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BUGGY = """<!doctype html><html><head><title>Checkout</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  body { font-family: sans-serif; margin: 0; padding: 16px; width: 390px; }
  #pay { position: absolute; left: 320px; top: 120px; width: 300px; height: 48px; }
</style></head><body>
<h1>Cart</h1><p>1 item</p>
<button id="pay">Place order</button>
<script>
document.getElementById('pay').addEventListener('click', async () => {
  const r = await fetch('/api/checkout', {method: 'POST'});
  console.error('checkout returned ' + r.status);
});
</script></body></html>"""

FIXED = """<!doctype html><html><head><title>Checkout</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  body { font-family: sans-serif; margin: 0; padding: 16px; box-sizing: border-box; }
  #pay { display: block; width: 100%; height: 48px; margin-top: 24px; box-sizing: border-box; }
</style></head><body>
<h1>Cart</h1><p>1 item</p>
<button id="pay">Place order</button>
<script>
document.getElementById('pay').addEventListener('click', async () => {
  const r = await fetch('/api/checkout', {method: 'POST'});
  const box = document.createElement('h2');
  box.style.textTransform = 'uppercase';
  box.textContent = r.ok ? 'Order confirmed' : 'Order failed';
  document.body.appendChild(box);
});
</script></body></html>"""

OCCLUDED = """<!doctype html><html><head><title>Occluded</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>body { margin: 0; }</style></head><body>
<button id="pay" style="position:absolute; top:40px; left:10px; width:200px; height:44px;">Place order</button>
<div id="overlay" style="position:absolute; top:0; left:0; width:100%; height:200px; background:rgba(0,0,0,.2)"></div>
</body></html>"""

WIDE = """<!doctype html><html><head><title>Wide</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>body { margin: 0; } .hud { min-width: 900px; height: 60px; background: #333; }</style>
</head><body><div class="hud">desktop-only hud</div></body></html>"""

STORY = """<!doctype html><html><head><title>story</title></head><body>
<div id="root">Cart item</div>
<script>
if (new URLSearchParams(location.search).get('id') === 'cart-item--broken') {
  console.error('story failed to mount');
}
</script></body></html>"""

STORY_INDEX = {
    "v": 3,
    "entries": {
        "cart-item--default": {"id": "cart-item--default", "title": "Cart/Item", "name": "Default", "type": "story"},
        "cart-item--broken": {"id": "cart-item--broken", "title": "Cart/Item", "name": "Broken", "type": "story"},
        "cart-item--docs": {"id": "cart-item--docs", "title": "Cart/Item", "name": "Docs", "type": "docs"},
    },
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code: int, body: str, content_type: str = "text/html") -> None:
        payload = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/buggy":
            return self._send(200, BUGGY)
        if path == "/fixed":
            return self._send(200, FIXED)
        if path == "/wide":
            return self._send(200, WIDE)
        if path == "/occluded":
            return self._send(200, OCCLUDED)
        if path == "/index.json":
            return self._send(200, json.dumps(STORY_INDEX), "application/json")
        if path == "/iframe.html":
            return self._send(200, STORY)
        return self._send(404, "not found")

    def do_POST(self):
        if self.path.split("?")[0] == "/api/checkout":
            broken = "bug" in (self.headers.get("Referer") or "")
            return self._send(500 if broken else 200, json.dumps({"ok": not broken}), "application/json")
        return self._send(404, "not found")


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8901
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"fixture on http://127.0.0.1:{port}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
