#!/usr/bin/env python3
"""Browser-level regression tests for the microphone path.

Needs geckodriver + Firefox; skips cleanly when either is missing. Three
scenarios, in the order a phone hits them:

  1. boot        the avatar frame and the idle state render
  2. race        the first press raises a permission prompt, so getUserMedia
                 resolves *after* the finger has lifted. Before the fix the
                 release was swallowed and a recorder started with nothing left
                 to stop it — no request, no error, a dead button.
  3. dictation   real speech (synthesised by the companion, played into a
                 captureStream) must type out live, land in the input on
                 release, and only reach the model when send is pressed.

    systemctl --user start companion
    python3 scripts/test_browser.py [url]
"""
from __future__ import annotations

import json
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request

URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:7778/"
PREF = {
    "media.navigator.streams.fake": True,
    "media.navigator.permission.disabled": True,
}
ELEMENT_KEY = "element-6066-11e4-a52e-4f735466cecf"


class Driver:
    def __init__(self, port: int):
        self.base = f"http://127.0.0.1:{port}"
        self.session = None

    def call(self, method, path, payload=None):
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(
            self.base + path, data=data, method=method,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = resp.read()
        return json.loads(body) if body else {}

    def js(self, script):
        return self.call(
            "POST", f"/session/{self.session}/execute/sync",
            {"script": script, "args": []},
        )["value"]

    def js_async(self, script):
        return self.call(
            "POST", f"/session/{self.session}/execute/async",
            {"script": script, "args": []},
        )["value"]

    def click(self, css):
        element = self.call(
            "POST", f"/session/{self.session}/element",
            {"using": "css selector", "value": css},
        )["value"][ELEMENT_KEY]
        self.call("POST", f"/session/{self.session}/element/{element}/click", {})


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def pointer(driver, kind):
    driver.js(
        "document.getElementById('talk').dispatchEvent("
        f"new PointerEvent('{kind}', {{bubbles: true, pointerId: 1}}))"
    )


def main() -> int:
    if not shutil.which("geckodriver") or not shutil.which("firefox"):
        print("skip: geckodriver or firefox is not installed")
        return 0
    try:
        urllib.request.urlopen(URL + "healthz", timeout=3).read()
    except Exception:
        print(f"skip: companion is not serving {URL}")
        return 0

    port = free_port()
    proc = subprocess.Popen(
        ["geckodriver", "--port", str(port)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    driver = Driver(port)
    for _ in range(40):
        try:
            if driver.call("GET", "/status")["value"]["ready"]:
                break
        except Exception:
            time.sleep(0.1)

    driver.session = driver.call("POST", "/session", {
        "capabilities": {"alwaysMatch": {
            "browserName": "firefox",
            "acceptInsecureCerts": True,
            "moz:firefoxOptions": {
                "args": ["-headless", "--width=1100", "--height=800"],
                "prefs": PREF,
            },
        }}
    })["value"]["sessionId"]

    ok = True
    try:
        driver.call("POST", f"/session/{driver.session}/url", {"url": URL})
        time.sleep(1.2)

        # 1 — boot
        state = driver.js("return document.getElementById('state').textContent")
        width = driver.js("return document.getElementById('avatar').naturalWidth")
        print(f"  boot          state={state!r} avatar={width}px")
        ok &= state == "idle" and width == 128

        # 2 — the permission-prompt race
        driver.js("""
            const real = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
            navigator.mediaDevices.getUserMedia = (c) =>
                new Promise((resolve) => setTimeout(() => resolve(real(c)), 900));
        """)
        pointer(driver, "pointerdown")
        time.sleep(0.1)
        pointer(driver, "pointerup")
        time.sleep(1.6)

        after = driver.js("""
            return {
              state: document.getElementById('state').textContent,
              label: document.querySelector('.talk-label').textContent,
              stats: document.getElementById('stats').textContent,
            };
        """)
        print(f"  early release state={after['state']!r} label={after['label']!r}")
        print(f"                stats={after['stats']!r}")
        ok &= after["state"] == "idle"
        ok &= after["label"] == "hold to talk"
        ok &= "hold the button again" in after["stats"]

        # 3 — the meter, on a real getUserMedia stream (the fake device is a tone)
        driver.js("delete navigator.mediaDevices.getUserMedia;")
        driver.click("header")  # trusted gesture: an AudioContext stays suspended without one
        pointer(driver, "pointerdown")
        time.sleep(1.5)
        meter = driver.js("""
            return {
              hidden: document.getElementById('meter').hidden,
              width: document.getElementById('meter').firstElementChild.style.width,
              diag: document.getElementById('diag').textContent,
            };
        """)
        pointer(driver, "pointerup")
        print(f"  meter         hidden={meter['hidden']} width={meter['width']}")
        print(f"                diag={meter['diag']!r}")
        ok &= meter["hidden"] is False
        ok &= float((meter["width"] or "0%").rstrip("%") or 0) > 0
        ok &= bool(meter["diag"].strip())
        time.sleep(2.0)  # let the final ASR pass finish before the next scene

        # 4 — live dictation, with real speech instead of the fake tone
        with urllib.request.urlopen(URL.rstrip("/") + "/api/health", timeout=10) as resp:
            live_enabled = bool(json.loads(resp.read()).get("asr_live", True))
        print(f"  asr mode      {'live streaming' if live_enabled else 'clip only'}")
        driver.js("document.getElementById('text-input').value = '';")
        driver.click("header")  # trusted gesture, so play() is allowed

        fed = driver.js_async("""
            const done = arguments[arguments.length - 1];
            (async () => {
              try {
                const res = await fetch('api/tts', {
                  method: 'POST', headers: {'Content-Type': 'application/json'},
                  body: JSON.stringify({text: 'Hey, I am Orchid.  Ask me anything.'})
                });
                const audio = new Audio(URL.createObjectURL(await res.blob()));
                audio.loop = true;
                await audio.play();
                window.__audio = audio;
                const stream = audio.captureStream ? audio.captureStream()
                                                   : audio.mozCaptureStream();
                navigator.mediaDevices.getUserMedia = async () => stream;
                done({ok: true});
              } catch (err) { done({ok: false, err: String(err && err.message || err)}); }
            })();
        """)
        if not fed.get("ok"):
            print(f"  dictation     skip: cannot feed audio ({fed.get('err')})")
        else:
            seen = []
            pointer(driver, "pointerdown")
            for _ in range(7):
                time.sleep(0.6)
                line = driver.js("return document.getElementById('live').textContent")
                if line and line != "…" and line not in seen:
                    seen.append(line)
            pointer(driver, "pointerup")
            print(f"  live lines    {seen}")
            ok &= len(seen) >= 2 if live_enabled else True  # the line grows while speaking, not once

            final = {}
            for _ in range(30):
                time.sleep(0.4)
                final = driver.js("""
                    return {
                      input: document.getElementById('text-input').value,
                      send: !document.getElementById('send').disabled,
                      live: document.getElementById('live').textContent,
                      state: document.getElementById('state').textContent,
                    };
                """)
                if final["input"] and final["live"] == "":
                    break
            print(f"  after release input={final.get('input','')[:60]!r} send={final.get('send')} live={final.get('live')!r}")
            ok &= bool(final.get("input"))
            ok &= bool(final.get("send"))
            ok &= final.get("live") == ""
            ok &= final.get("state") == "idle"

            driver.js("document.getElementById('send').click()")
            time.sleep(0.6)
            sent = driver.js("var n = document.querySelector('.msg.you'); return n ? n.textContent : ''")
            print(f"  pressed send  bubble={sent[:60]!r}")
            ok &= bool(sent)

        print("  PASS" if ok else "  FAIL")
    finally:
        driver.js("if (window.__audio) window.__audio.pause()")
        driver.call("DELETE", f"/session/{driver.session}")
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=10)

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
