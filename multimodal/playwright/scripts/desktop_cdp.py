#!/usr/bin/env python3
"""Headed Chromium with a CDP port, visible on the user's desktop.

The headless shell owns :9222 on this machine, so automation always ran in a
window nobody could see. This helper owns a second, headed Chromium profile
whose debug port is separate from the automation shell.

Commands:
  doctor          report which browser owns each port and whether it is visible
  clone-profile   copy the Flatpak Chromium profile while its browser is closed
  launch          start the headed agent browser and wait for its CDP endpoint
  stop            stop only the agent browser (matched by its profile path)
"""
import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_PORT = 9224
PROFILE = os.path.expanduser("~/.local/share/chromium-agent")
CURRENT_PROFILE = os.path.expanduser("~/.var/app/org.chromium.Chromium/config/chromium")
FLATPAK_APP = "org.chromium.Chromium"
AUTOMATION_PORT = 9222
COPY_IGNORES = {
    "Cache",
    "CacheStorage",
    "Code Cache",
    "GPUCache",
    "ShaderCache",
    "GrShaderCache",
    "DawnCache",
    "Media Cache",
    "Crash Reports",
    "BrowserMetrics",
    "SingletonCookie",
    "SingletonLock",
    "SingletonSocket",
    "DevToolsActivePort",
}


def cdp_version(port, timeout=1.0):
    url = f"http://127.0.0.1:{port}/json/version"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return json.load(response)
    except (urllib.error.URLError, ValueError, TimeoutError):
        return None


def cdp_targets(port, timeout=1.0):
    url = f"http://127.0.0.1:{port}/json/list"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return json.load(response)
    except (urllib.error.URLError, ValueError, TimeoutError):
        return []


def chromium_processes():
    found = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/cmdline", "rb") as handle:
                raw = handle.read()
        except OSError:
            continue
        fields = [part.decode("utf-8", "replace") for part in raw.split(b"\0") if part]
        if not fields:
            continue
        joined = " ".join(fields)
        if "chrom" not in joined.lower():
            continue
        found.append((int(entry), joined))
    return found


def process_kind(joined):
    if "chrome_crashpad_handler" in joined:
        return "helper"
    if "--type=" in joined:
        return "child"
    if "chrome-headless-shell" in joined:
        return "headless"
    if joined.startswith(("/app/chromium/chrome", "/app/bin/chromium", "/opt/", "/usr/bin/chrom")):
        return "desktop"
    return "other"


def browser_processes():
    return [
        (pid, joined)
        for pid, joined in chromium_processes()
        if process_kind(joined) in ("headless", "desktop")
    ]


def flag_value(joined, name):
    marker = f"--{name}="
    index = joined.find(marker)
    if index < 0:
        return None
    rest = joined[index + len(marker):]
    return rest.split(" ", 1)[0].strip('"') or None


def debug_port_of(joined):
    return flag_value(joined, "remote-debugging-port")


def profile_of(joined):
    return flag_value(joined, "user-data-dir")


def owned_pids():
    wanted = os.path.realpath(PROFILE)
    pids = []
    for pid, joined in browser_processes():
        current = profile_of(joined)
        if current and os.path.realpath(current) == wanted:
            pids.append(pid)
    return pids


def cmd_doctor(args):
    version = cdp_version(args.port)
    print(f"agent port   : {args.port} -> " + ("open" if version else "closed"))
    if version:
        print(f"  browser    : {version.get('Browser', 'unknown')}")
        targets = [t for t in cdp_targets(args.port) if t.get("type") == "page"]
        print(f"  pages      : {len(targets)}")
        for target in targets[:5]:
            print(f"    - {target.get('title') or '(untitled)'} :: {target.get('url')}")

    automation = cdp_version(AUTOMATION_PORT)
    if automation:
        print(f"automation   : {AUTOMATION_PORT} -> {automation.get('Browser', 'unknown')} (hidden)")

    desktop = []
    headless = []
    for pid, joined in browser_processes():
        target = (pid, debug_port_of(joined), profile_of(joined))
        if process_kind(joined) == "desktop":
            desktop.append(target)
        else:
            headless.append(target)

    for pid, port, profile in headless:
        if str(port) == str(AUTOMATION_PORT):
            continue
        print(f"headless     : pid {pid} cdp :{port or 'none'} (not visible)")

    if not desktop:
        print("desktop      : no visible Chromium browser process found")
    for pid, port, profile in desktop:
        where = profile or "(default profile)"
        state = f"cdp :{port}" if port else "no cdp port"
        print(f"desktop      : pid {pid} {state} {where}")

    print(f"agent profile: {PROFILE} " + ("(running)" if owned_pids() else "(stopped)"))
    return 0


def cmd_launch(args):
    if cdp_version(args.port):
        print(f"already running on :{args.port}")
        return 0

    flatpak = shutil.which("flatpak")
    if not flatpak:
        print("flatpak not found; cannot start the headed agent browser", file=sys.stderr)
        return 1

    os.makedirs(PROFILE, exist_ok=True)
    command = [
        flatpak,
        "run",
        FLATPAK_APP,
        f"--remote-debugging-port={args.port}",
        "--remote-allow-origins=*",
        f"--user-data-dir={PROFILE}",
        "--no-first-run",
        "--no-default-browser-check",
        "--start-maximized",
        args.url or "about:blank",
    ]
    subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    deadline = time.time() + 30
    while time.time() < deadline:
        version = cdp_version(args.port)
        if version:
            print(f"headed Chromium ready on :{args.port}")
            print(f"  browser : {version.get('Browser', 'unknown')}")
            print(f"  profile : {PROFILE}")
            return 0
        time.sleep(0.5)

    print("timed out waiting for the CDP endpoint", file=sys.stderr)
    return 1


def copy_current_profile(source, destination):
    source = Path(source).expanduser().resolve()
    destination = Path(destination).expanduser().resolve()
    if not source.is_dir():
        raise ValueError(f"Chromium profile not found: {source}")
    if source == destination or source in destination.parents:
        raise ValueError("destination must be outside the current Chromium profile")
    if destination.exists() and any(destination.iterdir()):
        raise ValueError(f"destination is not empty: {destination}")
    active_default = [
        (pid, joined)
        for pid, joined in browser_processes()
        if process_kind(joined) == "desktop"
        and (
            profile_of(joined) is None
            or Path(profile_of(joined)).expanduser().resolve() == source
        )
    ]
    if active_default:
        pids = ", ".join(str(pid) for pid, _ in active_default)
        raise ValueError(f"close the current Chromium completely before copying its profile (running browser PID(s): {pids})")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".chromium-profile-copy-", dir=destination.parent) as staging_parent:
        staging = Path(staging_parent) / "profile"
        shutil.copytree(source, staging, ignore=shutil.ignore_patterns(*COPY_IGNORES))
        if destination.exists():
            destination.rmdir()
        shutil.move(str(staging), str(destination))


def cmd_clone_profile(args):
    try:
        copy_current_profile(args.source, args.destination)
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(f"Copied Chromium profile to {args.destination}")
    print("The original profile was not modified. The clone contains private browser data.")
    return 0


def cmd_stop(args):
    pids = owned_pids()
    if not pids:
        print("agent browser is not running")
        return 0
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            continue
    print(f"stopped {len(pids)} agent browser process(es)")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Headed Chromium CDP helper")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="report browser and port state")
    doctor.set_defaults(func=cmd_doctor)

    launch = sub.add_parser("launch", help="start the headed agent browser")
    launch.add_argument("url", nargs="?", default=None)
    launch.set_defaults(func=cmd_launch)

    clone = sub.add_parser("clone-profile", help="copy the current Flatpak Chromium profile after Chromium is closed")
    clone.add_argument("--source", default=CURRENT_PROFILE)
    clone.add_argument("--destination", default=PROFILE)
    clone.set_defaults(func=cmd_clone_profile)

    stop = sub.add_parser("stop", help="stop the headed agent browser")
    stop.set_defaults(func=cmd_stop)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
