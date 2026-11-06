#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent / "scripts"))
from harness_core import ProjectsHarness, RuleClashError, EnvelopeHook, RouteChecker, ClashChecker


def main():
    parser = argparse.ArgumentParser(description="Projects Harness CLI — Claude Projects Reverse-Engineered Architecture")
    parser.add_argument("--dir", default=".", help="Workspace directory (default: current directory)")
    parser.add_argument("--json", action="store_true", help="Output in structured JSON format")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # startup
    p_start = subparsers.add_parser("startup", help="Bootstrap fresh session context (recent msgs + job status + memory <= 200 lines)")
    p_start.add_argument("--cap", type=int, default=200, metavar="LIMIT", help="Memory line cap (default: 200)")
    p_start.add_argument("--recent", type=int, default=5, metavar="LIMIT", help="Recent messages count (default: 5)")

    # route
    p_route = subparsers.add_parser("route", help="Deterministic 3-way message router")
    p_route.add_argument("message", help="Inbound message string")
    p_route.add_argument("--active-threads", help="JSON string or file of active threads with keywords")

    # envelope
    p_env = subparsers.add_parser("envelope", help="Build dual-provenance envelope (Coordinator AI Brief + Verbatim Owner Message)")
    p_env.add_argument("--brief", required=True, help="Coordinator's synthetic task brief")
    p_env.add_argument("--owner", required=True, help="Verbatim message from the human owner")

    # memory
    p_mem = subparsers.add_parser("memory", help="Atomic memory management")
    mem_subs = p_mem.add_subparsers(dest="mem_action", required=True)
    p_mem_up = mem_subs.add_parser("update", help="Update a fact in-place with history superseding")
    p_mem_up.add_argument("key", help="Fact key")
    p_mem_up.add_argument("value", help="Fact value")
    p_mem_read = mem_subs.add_parser("read", help="Read active memory facts")
    p_mem_dump = mem_subs.add_parser("dump", help="Dump raw memory lines")
    p_mem_dump.add_argument("--cap", type=int, default=200, metavar="LIMIT", help="Load cap (default: 200)")

    # log
    p_log = subparsers.add_parser("log", help="Message log operations")
    log_subs = p_log.add_subparsers(dest="log_action", required=True)
    p_log_app = log_subs.add_parser("append", help="Append message to log")
    p_log_app.add_argument("--role", default="user", help="Message role")
    p_log_app.add_argument("content", help="Message content")
    p_log_app.add_argument("--thread-id", help="Thread ID")
    p_log_srch = log_subs.add_parser("search", help="Search log messages on-demand")
    p_log_srch.add_argument("query", help="Search query string")
    p_log_srch.add_argument("--limit", type=int, default=10, metavar="LIMIT", help="Max results (default: 10)")

    # queue
    p_queue = subparsers.add_parser("queue", help="Worker queue and concurrency limiter (max 2)")
    queue_subs = p_queue.add_subparsers(dest="queue_action", required=True)
    p_q_enq = queue_subs.add_parser("enqueue", help="Enqueue task")
    p_q_enq.add_argument("task_id", help="Unique task ID")
    p_q_comp = queue_subs.add_parser("complete", help="Complete task (forces report)")
    p_q_comp.add_argument("task_id", help="Unique task ID")
    p_q_comp.add_argument("--report", required=True, help="Report content string or JSON")
    p_q_stat = queue_subs.add_parser("status", help="Show queue status")

    # clash
    p_clash = subparsers.add_parser("clash", help="Check for rule clashes between static instructions and memory writes")
    p_clash.add_argument("--rule-key", required=True, help="Instruction rule key")
    p_clash.add_argument("--rule-val", required=True, help="Instruction static rule value")
    p_clash.add_argument("--proposed-val", required=True, help="Proposed memory update value")

    args = parser.parse_args()
    harness = ProjectsHarness(Path(args.dir))

    if args.command == "startup":
        res = harness.startup(memory_cap=args.cap, recent_limit=args.recent)
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            print(f"🚀 [Startup] Context Bootstrap:")
            print(f"  • Recent Messages: {len(res['recent_messages'])}")
            print(f"  • Active Jobs: {res['jobs_status']['working_count']} working, {res['jobs_status']['queued_count']} queued, {res['jobs_status']['done_count']} done")
            print(f"  • Memory Lines: {res['memory_line_count']} loaded (Capped: {res['memory_was_capped']})")

    elif args.command == "route":
        active_threads = []
        if args.active_threads:
            if Path(args.active_threads).exists():
                active_threads = json.loads(Path(args.active_threads).read_text(encoding="utf-8"))
            else:
                active_threads = json.loads(args.active_threads)
        route_decision, thread_id = RouteChecker.route(args.message, active_threads)
        if args.json:
            print(json.dumps({"route": route_decision, "thread_id": thread_id}))
        else:
            if route_decision == "direct":
                print("🔀 [Route] -> Direct Reply (Answer right here)")
            elif route_decision == "pass_to_thread":
                print(f"🔀 [Route] -> Pass to existing thread [{thread_id}]")
            else:
                print("🔀 [Route] -> Spawn new worker thread")

    elif args.command == "envelope":
        env = EnvelopeHook.wrap(args.brief, args.owner)
        if args.json:
            print(json.dumps(env, indent=2))
        else:
            print(env["formatted"])

    elif args.command == "memory":
        if args.mem_action == "update":
            line = harness.memory.update(args.key, args.value)
            print(f"✓ Memory updated: {line}")
        elif args.mem_action == "read":
            facts = harness.memory.read_facts()
            print(json.dumps(facts, indent=2))
        elif args.mem_action == "dump":
            lines, capped = harness.memory.load(cap=args.cap)
            for idx, l in enumerate(lines, 1):
                print(f"{idx:3d}: {l}")
            if capped:
                print(f"\n⚠️ Truncated at line {args.cap}")

    elif args.command == "log":
        if args.log_action == "append":
            ent = harness.log.append(args.role, args.content, args.thread_id)
            print(f"✓ Log entry appended: {ent['timestamp']}")
        elif args.log_action == "search":
            results = harness.log.search(args.query, limit=args.limit)
            if args.json:
                print(json.dumps(results, indent=2))
            else:
                print(f"🔍 Search results for '{args.query}' ({len(results)} matches):")
                for r in results:
                    print(f"  [{r['timestamp']}] ({r['role']}) {r['content']}")

    elif args.command == "queue":
        if args.queue_action == "enqueue":
            status = harness.queue.enqueue(args.task_id)
            print(f"✓ Task '{args.task_id}' enqueued -> Status: {status.upper()}")
        elif args.queue_action == "complete":
            try:
                rep = json.loads(args.report)
            except Exception:
                rep = {"summary": args.report}
            promoted = harness.queue.complete(args.task_id, rep)
            print(f"✓ Task '{args.task_id}' completed.")
            if promoted:
                print(f"  ⚡ Promoted queued task '{promoted['task_id']}' to WORKING.")
        elif args.queue_action == "status":
            stat = harness.queue.status()
            if args.json:
                print(json.dumps(stat, indent=2))
            else:
                print(f"🚦 Queue Status (Max 2):")
                print(f"  • WORKING ({len(stat['working'])}/2): {[t['task_id'] for t in stat['working']]}")
                print(f"  • QUEUED ({len(stat['queued'])}): {[t['task_id'] for t in stat['queued']]}")
                print(f"  • DONE ({len(stat['done'])}): {[t['task_id'] for t in stat['done']]}")

    elif args.command == "clash":
        instructions = {args.rule_key: args.rule_val}
        err = ClashChecker.check(instructions, args.rule_key, args.proposed_val)
        if err:
            print(f"🚨 [CLASH DETECTED] {err}")
            sys.exit(1)
        else:
            print("✓ No rule clash detected.")


if __name__ == "__main__":
    main()
