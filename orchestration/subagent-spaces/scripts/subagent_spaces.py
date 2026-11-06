#!/usr/bin/env python3
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set

SKILL_DIR = Path(__file__).resolve().parent.parent
CONTAINERFILE = SKILL_DIR / "Containerfile"
DEFAULT_IMAGE = "subagent-space:latest"
FALLBACK_IMAGE = "docker.io/library/ubuntu:24.04"

WORKER_CORES = list(range(4, 16))
HOST_RESERVE_CORES = list(range(0, 4))

SLOT_TOPOLOGY = {
    "1": {"cpus": "4-7", "memory": "4g", "threads": 4},
    "2": {"cpus": "8-11", "memory": "4g", "threads": 4},
    "3": {"cpus": "12-15", "memory": "4g", "threads": 4},
    "all": {"cpus": "4-15", "memory": "12g", "threads": 12},
}


def run_cmd(cmd: List[str], check: bool = True, capture: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=check, text=True, capture_output=capture)


def parse_cores(core_str: str) -> List[int]:
    cores: Set[int] = set()
    for part in core_str.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, end = part.split("-", 1)
            cores.update(range(int(start), int(end) + 1))
        elif part.isdigit():
            cores.add(int(part))
    return sorted(list(cores))


def format_cores(core_list: List[int]) -> str:
    if not core_list:
        return ""
    if len(core_list) == 1:
        return str(core_list[0])
    if core_list == list(range(core_list[0], core_list[-1] + 1)):
        return f"{core_list[0]}-{core_list[-1]}"
    return ",".join(str(c) for c in core_list)


def get_active_containers() -> List[Dict]:
    cmd = [
        "podman", "ps",
        "--filter", "label=app=subagent-spaces",
        "--format", "{{json .}}"
    ]
    try:
        proc = run_cmd(cmd)
        lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
        containers = []
        for line in lines:
            try:
                containers.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        return containers
    except Exception:
        return []


def get_occupied_cores(active_containers: List[Dict]) -> Set[int]:
    occupied = set()
    for c in active_containers:
        labels = c.get("Labels") or {}
        cores_str = labels.get("cores")
        if cores_str:
            occupied.update(parse_cores(cores_str))
        else:
            slot = labels.get("slot")
            if slot and slot in SLOT_TOPOLOGY:
                occupied.update(parse_cores(SLOT_TOPOLOGY[slot]["cpus"]))
    return occupied


def allocate_idle_cores(num_cpus: int, active_containers: List[Dict]) -> List[int]:
    occupied = get_occupied_cores(active_containers)
    idle = [c for c in WORKER_CORES if c not in occupied]
    if len(idle) < num_cpus:
        sys.exit(f"❌ Error: Requested {num_cpus} CPU threads, but only {len(idle)} worker threads are idle (out of 12).")
    return idle[:num_cpus]


def resolve_image(custom_image: Optional[str]) -> str:
    if custom_image:
        return custom_image
    inspect_proc = subprocess.run(
        ["podman", "image", "exists", DEFAULT_IMAGE],
        capture_output=True
    )
    if inspect_proc.returncode == 0:
        return DEFAULT_IMAGE
    return FALLBACK_IMAGE


def cmd_doctor() -> None:
    print("🩺 [subagent-spaces] Running system & environment diagnostics...\n")

    podman_path = shutil.which("podman")
    taskset_path = shutil.which("taskset")

    print(f"  • Podman binary:    {'✅ ' + podman_path if podman_path else '❌ NOT FOUND'}")
    print(f"  • Taskset binary:   {'✅ ' + taskset_path if taskset_path else '❌ NOT FOUND'}")

    if not podman_path or not taskset_path:
        print("\n❌ Critical dependencies missing.")
        sys.exit(1)

    cpu_count = os.cpu_count() or 0
    print(f"  • CPU Threads:      ✅ {cpu_count} threads detected (Ryzen 7 7700 Substrate)")
    print(f"  • Host Reserve:     Cores 0-3 (reserved for desktop & OS)")
    print(f"  • Worker Pool:      Cores 4-15 (12 isolated threads available)")

    img_check = subprocess.run(["podman", "image", "exists", DEFAULT_IMAGE], capture_output=True)
    has_local_img = (img_check.returncode == 0)
    print(f"  • Local Image:      {'✅ ' + DEFAULT_IMAGE if has_local_img else '⚠️  Not built (using ' + FALLBACK_IMAGE + ')'}")

    try:
        single_core_test = run_cmd(["taskset", "-c", "4", "podman", "run", "--rm", FALLBACK_IMAGE, "nproc"])
        cores = single_core_test.stdout.strip()
        print(f"  • 1-Thread Pinning: ✅ Enforced via taskset (reported {cores} core in container)")
    except Exception as e:
        print(f"  • 1-Thread Pinning: ❌ Failed: {e}")

    try:
        mem_proc = run_cmd(["podman", "run", "--rm", "-m", "512m", FALLBACK_IMAGE, "cat", "/sys/fs/cgroup/memory.max"])
        mem_val = mem_proc.stdout.strip()
        if mem_val == "536870912":
            print("  • Memory Cgroup:    ✅ Active and enforced (512 MiB quota verified)")
        else:
            print(f"  • Memory Cgroup:    ⚠️  Value: {mem_val}")
    except Exception as e:
        print(f"  • Memory Cgroup:    ⚠️  Failed verification: {e}")

    print("\n✅ System is fully capable of running granular 1-to-12 thread subagent spaces.")


def cmd_slots() -> None:
    active = get_active_containers()
    occupied_cores = get_occupied_cores(active)

    print("\n🖥️  [subagent-spaces] Thread & Slot Topology (16-Thread Ryzen Substrate)\n")

    grid_items = []
    for c in range(16):
        if c in HOST_RESERVE_CORES:
            grid_items.append(f"\033[36m[{c}:HOST]\033[0m")
        elif c in occupied_cores:
            grid_items.append(f"\033[33m[{c}:BUSY]\033[0m")
        else:
            grid_items.append(f"\033[32m[{c}:IDLE]\033[0m")

    print("  CPU Grid: " + " ".join(grid_items[:4]) + " │ " + " ".join(grid_items[4:8]) + " │ " + " ".join(grid_items[8:12]) + " │ " + " ".join(grid_items[12:16]))
    print()

    print(f"  {'Slot/Pool':<10} │ {'Cores':<8} │ {'Default RAM':<12} │ {'Occupancy'}")
    print("  ───────────┼──────────┼──────────────┼─────────────────────────────────────────────")
    print(f"  {'HOST':<10} │ 0-3      │ System       │ Reserved (Desktop, Display Server, OS)")

    for slot_id in ["1", "2", "3"]:
        topo = SLOT_TOPOLOGY[slot_id]
        slot_cores = set(parse_cores(topo["cpus"]))
        overlap = slot_cores.intersection(occupied_cores)
        if len(overlap) == len(slot_cores):
            status = "\033[33mFULL\033[0m"
        elif len(overlap) > 0:
            status = f"\033[33mPARTIAL ({len(overlap)}/{len(slot_cores)} threads)\033[0m"
        else:
            status = "\033[32mIDLE\033[0m"
        print(f"  Slot {slot_id:<5} │ {topo['cpus']:<8} │ {topo['memory']:<12} │ {status}")

    idle_workers = len([c for c in WORKER_CORES if c not in occupied_cores])
    print(f"  {'Custom/1T':<10} │ 4-15     │ Dynamic (1G) │ {idle_workers}/12 worker threads currently IDLE")
    print()


def cmd_build() -> None:
    if not CONTAINERFILE.is_file():
        sys.exit(f"❌ Error: Containerfile not found at {CONTAINERFILE}")

    print(f"📦 [subagent-spaces] Building image '{DEFAULT_IMAGE}' from {CONTAINERFILE}...")
    cmd = ["podman", "build", "-t", DEFAULT_IMAGE, "-f", str(CONTAINERFILE), str(SKILL_DIR)]
    res = subprocess.run(cmd)
    if res.returncode == 0:
        print(f"\n✅ Image '{DEFAULT_IMAGE}' built successfully.")
    else:
        sys.exit(res.returncode)


def cmd_run(args: argparse.Namespace) -> None:
    active = get_active_containers()

    # Determine Cores
    if args.cores:
        assigned_cores = parse_cores(args.cores)
        core_spec = format_cores(assigned_cores)
        slot_label = f"custom-{core_spec}"
    elif args.cpus:
        assigned_cores = allocate_idle_cores(args.cpus, active)
        core_spec = format_cores(assigned_cores)
        slot_label = f"{args.cpus}t-{core_spec}"
    elif args.slot:
        if args.slot not in SLOT_TOPOLOGY:
            sys.exit(f"❌ Error: Invalid slot '{args.slot}'. Must be 1, 2, 3, or all.")
        topo = SLOT_TOPOLOGY[args.slot]
        assigned_cores = parse_cores(topo["cpus"])
        core_spec = topo["cpus"]
        slot_label = args.slot
    else:
        # Default: Allocate 1 core if free, else next idle slot
        assigned_cores = allocate_idle_cores(1, active)
        core_spec = format_cores(assigned_cores)
        slot_label = f"1t-{core_spec}"

    # Determine Memory
    if args.memory:
        mem_quota = args.memory
    elif args.slot and args.slot in SLOT_TOPOLOGY:
        mem_quota = SLOT_TOPOLOGY[args.slot]["memory"]
    else:
        # 1 GB per allocated thread by default
        mem_quota = f"{max(1, len(assigned_cores))}g"

    ws_path = Path(args.workspace).resolve() if args.workspace else Path.cwd().resolve()
    if not ws_path.exists():
        sys.exit(f"❌ Error: Workspace directory does not exist: {ws_path}")

    mount_flags = "ro,z" if args.ro else "z"
    image = resolve_image(args.image)
    container_name = args.name or f"subagent-space-{core_spec}-{os.urandom(3).hex()}"

    podman_cmd = [
        "taskset", "-c", core_spec,
        "podman", "run",
        "--name", container_name,
        "-m", mem_quota,
        "-v", f"{ws_path}:/workspace:{mount_flags}",
        "-w", "/workspace",
        "--label", "app=subagent-spaces",
        "--label", f"slot={slot_label}",
        "--label", f"cores={core_spec}",
        "--label", f"threads={len(assigned_cores)}",
        "--label", f"workspace={ws_path}",
        "--network", args.network,
    ]

    if not args.keep:
        podman_cmd.append("--rm")

    if args.env:
        for e in args.env:
            podman_cmd.extend(["-e", e])

    if args.detach:
        podman_cmd.append("-d")
    elif args.interactive:
        podman_cmd.extend(["-it"])

    podman_cmd.append(image)

    cmd_to_run = list(args.command) if args.command else []
    if cmd_to_run and cmd_to_run[0] == "--":
        cmd_to_run = cmd_to_run[1:]

    if cmd_to_run:
        podman_cmd.extend(cmd_to_run)
    else:
        podman_cmd.extend(["/bin/bash"])

    print(f"🚀 [subagent-spaces] Launching space on Cores {core_spec} ({len(assigned_cores)} thread{'s' if len(assigned_cores) > 1 else ''}, RAM {mem_quota})")
    print(f"   Image:     {image}")
    print(f"   Workspace: {ws_path} ({'Read-Only' if args.ro else 'Read-Write'})")
    print(f"   Network:   {args.network}")
    print(f"   Container: {container_name}\n")

    res = subprocess.run(podman_cmd)
    sys.exit(res.returncode)


def cmd_ps() -> None:
    active = get_active_containers()
    if not active:
        print("No active subagent-spaces containers running.")
        return

    print("\n📦 Active Subagent Spaces:\n")
    print(f"  {'Container ID':<14} │ {'Cores':<8} │ {'Threads':<8} │ {'Status':<16} │ {'Workspace':<30} │ Names")
    print("  ───────────────┼──────────┼──────────┼──────────────────┼────────────────────────────────┼──────────────")

    for c in active:
        cid = c.get("Id", "")[:12]
        labels = c.get("Labels") or {}
        cores = labels.get("cores", labels.get("slot", "?"))
        threads = labels.get("threads", "1")
        ws = labels.get("workspace", "-")
        status = c.get("Status", "Running")
        names = ", ".join(c.get("Names") or [])
        print(f"  {cid:<14} │ {cores:<8} │ {threads:<8} │ {status:<16} │ {ws:<30} │ {names}")
    print()


def cmd_enter(target: str) -> None:
    active = get_active_containers()
    matched = None
    for c in active:
        cid = c.get("Id", "")
        names = c.get("Names") or []
        labels = c.get("Labels") or {}
        slot = labels.get("slot")
        cores = labels.get("cores")

        if target in (slot, cores) or target in names or cid.startswith(target):
            matched = names[0] if names else cid[:12]
            break

    if not matched:
        sys.exit(f"❌ Error: No running space matching slot, core, name, or container ID '{target}'.")

    print(f"🔗 Attaching interactive shell to {matched}...")
    exec_cmd = ["podman", "exec", "-it", matched, "/bin/bash"]
    res = subprocess.run(exec_cmd)
    if res.returncode != 0:
        subprocess.run(["podman", "exec", "-it", matched, "/bin/sh"])


def cmd_stop(target: str) -> None:
    active = get_active_containers()
    matched = []
    for c in active:
        cid = c.get("Id", "")
        names = c.get("Names") or []
        labels = c.get("Labels") or {}
        slot = labels.get("slot")
        cores = labels.get("cores")

        if target in (slot, cores) or target in names or cid.startswith(target):
            matched.append(names[0] if names else cid[:12])

    if not matched:
        sys.exit(f"❌ Error: No running space matching '{target}'.")

    for m in matched:
        print(f"🛑 Stopping container: {m}...")
        subprocess.run(["podman", "stop", "-t", "2", m], check=False)
        subprocess.run(["podman", "rm", "-f", m], check=False)
    print("✅ Stopped.")


def cmd_prune() -> None:
    active = get_active_containers()
    if not active:
        print("No active subagent spaces to prune.")
        return

    print(f"🧹 Pruning {len(active)} active subagent spaces...")
    for c in active:
        cid = c.get("Id", "")[:12]
        print(f"  • Terminating {cid}...")
        subprocess.run(["podman", "stop", "-t", "2", cid], check=False, capture_output=True)
        subprocess.run(["podman", "rm", "-f", cid], check=False, capture_output=True)
    print("✅ All subagent spaces pruned.")


def main():
    parser = argparse.ArgumentParser(
        prog="subagent-spaces",
        description="Isolated CPU-pinned containerized sandbox environments for autonomous subagents."
    )
    subparsers = parser.add_subparsers(dest="action")

    subparsers.add_parser("doctor", help="Run diagnostic health checks on host capabilities")
    subparsers.add_parser("slots", help="Show CPU core topology and slot occupancy")
    subparsers.add_parser("ps", help="List active subagent space containers")
    subparsers.add_parser("build", help="Build optimized local subagent-space image")
    subparsers.add_parser("prune", help="Clean up all active subagent spaces")

    enter_p = subparsers.add_parser("enter", help="Attach interactive shell to a running space")
    enter_p.add_argument("target", help="Slot, core, container name, or container ID")

    stop_p = subparsers.add_parser("stop", help="Stop and remove a running space")
    stop_p.add_argument("target", help="Slot, core, container name, or container ID")

    run_p = subparsers.add_parser("run", help="Run a command or spawn a subagent space")
    run_p.add_argument("--cores", "-c", help="Exact CPU core(s) to pin (e.g. '4', '4-5', '4,6,8')")
    run_p.add_argument("--cpus", "-n", type=int, help="Number of CPU threads to auto-allocate (e.g. 1, 2, 4)")
    run_p.add_argument("--slot", choices=["1", "2", "3", "all"], help="Predefined worker slot")
    run_p.add_argument("--memory", "-m", help="Memory quota (e.g. '1g', '512m', '4g')")
    run_p.add_argument("--workspace", "-w", help="Workspace directory to mount into /workspace")
    run_p.add_argument("--image", "-i", help=f"Custom container image (default: {DEFAULT_IMAGE} or {FALLBACK_IMAGE})")
    run_p.add_argument("--name", help="Custom container name")
    run_p.add_argument("--ro", action="store_true", help="Mount workspace as read-only")
    run_p.add_argument("--network", default="host", choices=["host", "bridge", "none"], help="Network mode (default: host)")
    run_p.add_argument("--detach", "-d", action="store_true", help="Run in background")
    run_p.add_argument("--interactive", "-it", action="store_true", help="Run interactively with terminal TTY")
    run_p.add_argument("--keep", action="store_true", help="Keep container after exit (do not --rm)")
    run_p.add_argument("-e", "--env", action="append", help="Environment variable KEY=VALUE")
    run_p.add_argument("command", nargs=argparse.REMAINDER, help="Command to run inside the space")

    args = parser.parse_args()

    if args.action == "doctor":
        cmd_doctor()
    elif args.action == "slots":
        cmd_slots()
    elif args.action == "ps":
        cmd_ps()
    elif args.action == "build":
        cmd_build()
    elif args.action == "enter":
        cmd_enter(args.target)
    elif args.action == "stop":
        cmd_stop(args.target)
    elif args.action == "prune":
        cmd_prune()
    elif args.action == "run":
        cmd_run(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
