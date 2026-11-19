#!/usr/bin/env python3
"""Capability gate tests for isolate-run: 3 positive cases + 10 negative controls.

A control that unexpectedly succeeds fails the suite — a gate that cannot fail
is not a gate. Skips when Deno is unavailable.

    python3 tests/test_isolate_run.py
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUN = HERE.parent / "scripts" / "isolate_run.py"
DENO = os.environ.get("DENO_BIN") or shutil.which("deno")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class H(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        body = b'{"ok":true,"items":[3,1,2]}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@unittest.skipUnless(DENO and RUN.is_file(), "Deno or isolate_run.py unavailable")
class TestIsolateRun(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="isolate-run-test-")
        cls.root = Path(cls.tmp.name)
        cls.servers = []
        for _ in range(2):
            port = free_port()
            httpd = ThreadingHTTPServer(("127.0.0.1", port), H)
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            cls.servers.append(httpd)
        cls.allowed_port, cls.blocked_port = cls.servers[0].server_port, cls.servers[1].server_port

    @classmethod
    def tearDownClass(cls):
        for httpd in cls.servers:
            httpd.shutdown()
            httpd.server_close()
        cls.tmp.cleanup()

    def js(self, name: str, code: str) -> str:
        path = self.root / f"{name}.js"
        path.write_text(code, encoding="utf-8")
        return str(path)

    def run_iso(self, *args):
        p = subprocess.run([sys.executable, str(RUN), *args],
                           capture_output=True, text=True, timeout=30)
        return p

    def assert_allowed(self, *args):
        p = self.run_iso(*args)
        self.assertEqual(p.returncode, 0, p.stderr[:500])

    def assert_denied(self, *args):
        p = self.run_iso(*args)
        self.assertNotEqual(p.returncode, 0, "permission control unexpectedly succeeded")

    def test_01_pure_compute(self):
        script = self.js("compute", """
const rows=[{n:'b',v:3},{n:'a',v:1},{n:'c',v:2}];
const sorted=rows.sort((x,y)=>x.v-y.v);
const total=rows.reduce((a,r)=>a+r.v,0);
const slug='Hello World'.toLowerCase().replace(/\\s+/g,'-');
const sha=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(slug))
  .then(b=>[...new Uint8Array(b)].slice(0,6).map(x=>x.toString(16).padStart(2,'0')).join(''));
console.log(JSON.stringify({sorted,total,slug,sha}));
""")
        p = self.run_iso("--profile", "pure", "--json", script)
        self.assertEqual(p.returncode, 0, p.stderr[:500])
        self.assertEqual(json.loads(p.stdout)["exit"], 0)
        self.assertIn("hello-world", p.stdout)

    def test_02_scoped_read(self):
        reader = self.js("reader", "console.log((await Deno.readTextFile(Deno.args[0])).trim());")
        self.assert_allowed("--profile", "read", "--allow-path", "/etc/hostname",
                            "--json", reader, "/etc/hostname")

    def test_03_scoped_net(self):
        fetcher = self.js("fetcher", "const r=await fetch(Deno.args[0]); console.log(r.status, (await r.json()).ok);")
        self.assert_allowed("--profile", "net", "--allow-host", f"127.0.0.1:{self.allowed_port}",
                            "--json", fetcher, f"http://127.0.0.1:{self.allowed_port}/data")

    def test_10_deny_read(self):
        reader = self.js("reader", "await Deno.readTextFile(Deno.args[0]);")
        self.assert_denied("--profile", "pure", "--json", reader, "/etc/hostname")

    def test_11_deny_write(self):
        writer = self.js("writer", "await Deno.writeTextFile(Deno.args[0],'pwned');")
        self.assert_denied("--profile", "pure", "--json", writer, str(self.root / "evil.txt"))

    def test_12_deny_env(self):
        envr = self.js("envr", "console.log(Deno.env.get('HOME'));")
        self.assert_denied("--profile", "pure", "--json", envr)

    def test_13_deny_subprocess(self):
        procr = self.js("procr", "new Deno.Command('whoami').outputSync();")
        self.assert_denied("--profile", "pure", "--json", procr)

    def test_14_deny_net(self):
        netr = self.js("netr", "await fetch(Deno.args[0]);")
        self.assert_denied("--profile", "pure", "--json", netr,
                           f"http://127.0.0.1:{self.allowed_port}/")

    def test_15_deny_ffi(self):
        ffir = self.js("ffir", "Deno.dlopen('/lib/x86_64-linux-gnu/libc.so.6',{});")
        self.assert_denied("--profile", "pure", "--json", ffir)

    def test_16_read_scope(self):
        reader = self.js("reader", "await Deno.readTextFile(Deno.args[0]);")
        self.assert_denied("--profile", "read", "--allow-path", "/etc/hostname",
                           "--json", reader, "/etc/passwd")

    def test_17_net_scope(self):
        netr = self.js("netr", "await fetch(Deno.args[0]);")
        self.assert_denied("--profile", "net", "--allow-host", f"127.0.0.1:{self.allowed_port}",
                           "--json", netr, f"http://127.0.0.1:{self.blocked_port}/")

    def test_18_timeout(self):
        loop = self.js("loop", "while(true){}")
        p = self.run_iso("--profile", "pure", "--timeout", "1", "--json", loop)
        self.assertEqual(p.returncode, 124, p.stderr[:300])
        self.assertTrue(json.loads(p.stdout)["timed_out"])

    def test_19_heap_cap(self):
        bomb = self.js("bomb", "let a=[]; while(true){a.push(new Array(1e6).fill('x').join(''));}")
        self.assert_denied("--profile", "pure", "--mem", "32", "--timeout", "8", "--json", bomb)


if __name__ == "__main__":
    unittest.main(verbosity=2)
