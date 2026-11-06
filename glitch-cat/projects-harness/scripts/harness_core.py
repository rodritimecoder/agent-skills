#!/usr/bin/env python3
import datetime
import fcntl
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class ProjectsHarnessError(Exception):
    pass


class RuleClashError(ProjectsHarnessError):
    def __init__(self, key: str, instruction_rule: str, proposed_value: str):
        super().__init__(f"Rule clash detected for '{key}': static rule='{instruction_rule}' vs memory='{proposed_value}'")
        self.key = key
        self.instruction_rule = instruction_rule
        self.proposed_value = proposed_value


class LogManager:
    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)
        self.log_file = self.base_dir / "messages.jsonl"
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def append(self, role: str, content: str, thread_id: Optional[str] = None) -> Dict[str, Any]:
        entry = {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "role": role,
            "content": content,
            "thread_id": thread_id,
        }
        with open(self.log_file, "a", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                f.write(json.dumps(entry) + "\n")
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
        return entry

    def get_recent(self, limit: int = 5) -> List[Dict[str, Any]]:
        if not self.log_file.exists():
            return []
        lines = self.log_file.read_text(encoding="utf-8").strip().splitlines()
        selected = lines[-limit:] if len(lines) >= limit else lines
        return [json.loads(line) for line in selected if line.strip()]

    def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        if not self.log_file.exists():
            return []
        pattern = re.compile(re.escape(query), re.IGNORECASE)
        results = []
        with open(self.log_file, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                record = json.loads(line)
                if pattern.search(record.get("content", "")):
                    results.append(record)
                    if len(results) >= limit:
                        break
        return results


class MemoryWriter:
    def __init__(self, base_dir: Path, memory_file_name: str = "memory.txt"):
        self.base_dir = Path(base_dir)
        self.memory_file = self.base_dir / memory_file_name
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def update(self, key: str, value: str) -> str:
        clean_key = key.strip()
        clean_val = value.strip()
        lock_file = self.base_dir / ".memory.lock"
        with open(lock_file, "w", encoding="utf-8") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            try:
                lines = []
                if self.memory_file.exists():
                    lines = self.memory_file.read_text(encoding="utf-8").splitlines()

                updated = False
                new_lines = []
                prefix = f"{clean_key}:"

                for line in lines:
                    if line.startswith(prefix):
                        old_history = line[len(prefix):].strip()
                        new_line = f"{clean_key}: {clean_val} <- {old_history}"
                        new_lines.append(new_line)
                        updated = True
                    else:
                        new_lines.append(line)

                if not updated:
                    new_lines.append(f"{clean_key}: {clean_val}")

                temp_file = self.memory_file.with_suffix(".tmp")
                temp_file.write_text("\n".join(new_lines) + ("\n" if new_lines else ""), encoding="utf-8")
                temp_file.replace(self.memory_file)
                return next(line for line in new_lines if line.startswith(prefix))
            finally:
                fcntl.flock(lf, fcntl.LOCK_UN)

    def load(self, cap: int = 200) -> Tuple[List[str], bool]:
        if not self.memory_file.exists():
            return [], False
        lines = [line for line in self.memory_file.read_text(encoding="utf-8").splitlines() if line.strip()]
        was_capped = len(lines) > cap
        return lines[:cap], was_capped

    def read_facts(self) -> Dict[str, str]:
        lines, _ = self.load(cap=100000)
        facts = {}
        for line in lines:
            if ":" in line:
                k, v = line.split(":", 1)
                active_val = v.split("<-")[0].strip()
                facts[k.strip()] = active_val
        return facts


class EnvelopeHook:
    @staticmethod
    def wrap(ai_brief: str, owner_message: str) -> Dict[str, str]:
        if not ai_brief or not ai_brief.strip():
            raise ProjectsHarnessError("Coordinator AI brief cannot be empty")
        if not owner_message or not owner_message.strip():
            raise ProjectsHarnessError("Owner message cannot be empty")
        envelope = {
            "coordinator_brief": ai_brief.strip(),
            "coordinator_label": "AI-GENERATED",
            "owner_message": owner_message.strip(),
            "owner_label": "FROM OWNER (VERBATIM)",
            "formatted": (
                "--- [COORDINATOR BRIEF (AI-GENERATED)] ---\n"
                f"{ai_brief.strip()}\n\n"
                "--- [OWNER MESSAGE (FROM OWNER - VERBATIM)] ---\n"
                f"{owner_message.strip()}"
            ),
        }
        return envelope


class RouteChecker:
    @staticmethod
    def route(message: str, active_threads: Optional[List[Dict[str, Any]]] = None) -> Tuple[str, Optional[str]]:
        msg = message.strip()
        threads = active_threads or []

        # Check existing threads matching keywords
        for t in threads:
            tid = t.get("thread_id")
            keywords = t.get("keywords", [])
            for kw in keywords:
                if re.search(r"\b" + re.escape(kw) + r"\b", msg, re.IGNORECASE):
                    return "pass_to_thread", tid

        # Check for direct answer patterns (questions, greetings, status queries)
        direct_patterns = [
            r"^(hi|hello|hey|status|where are we|what is up|summary)\b",
            r"\?$",
            r"^(how|what|why|who|when)\b",
        ]
        if any(re.search(pat, msg, re.IGNORECASE) for pat in direct_patterns) and not re.search(r"\b(build|create|refactor|test|fix|run|worker|agent)\b", msg, re.IGNORECASE):
            return "direct", None

        # Work instruction triggers a new thread
        return "new_thread", None


class ClashChecker:
    @staticmethod
    def check(instructions: Dict[str, str], key: str, proposed_value: str) -> Optional[RuleClashError]:
        clean_key = key.strip()
        clean_val = proposed_value.strip().lower()
        if clean_key in instructions:
            static_rule = instructions[clean_key].strip()
            if static_rule.lower() != clean_val:
                return RuleClashError(clean_key, static_rule, proposed_value.strip())
        return None


class QueueLimiter:
    def __init__(self, base_dir: Path, max_concurrency: int = 2):
        self.base_dir = Path(base_dir)
        self.state_file = self.base_dir / "task_queue.json"
        self.max_concurrency = max_concurrency
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _read_state(self) -> Dict[str, Any]:
        if not self.state_file.exists():
            return {"working": [], "queued": [], "done": []}
        return json.loads(self.state_file.read_text(encoding="utf-8"))

    def _write_state(self, state: Dict[str, Any]):
        lock_file = self.base_dir / ".queue.lock"
        with open(lock_file, "w", encoding="utf-8") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            try:
                temp_file = self.state_file.with_suffix(".tmp")
                temp_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
                temp_file.replace(self.state_file)
            finally:
                fcntl.flock(lf, fcntl.LOCK_UN)

    def enqueue(self, task_id: str, payload: Optional[Dict[str, Any]] = None) -> str:
        state = self._read_state()
        task = {"task_id": task_id, "payload": payload or {}, "queued_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
        if len(state["working"]) < self.max_concurrency:
            state["working"].append(task)
            status = "working"
        else:
            state["queued"].append(task)
            status = "queued"
        self._write_state(state)
        return status

    def complete(self, task_id: str, report: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        if report is None:
            raise ProjectsHarnessError("Completion requires a forced report payload")
        state = self._read_state()
        item = next((t for t in state["working"] if t["task_id"] == task_id), None)
        if not item:
            raise ProjectsHarnessError(f"Task '{task_id}' is not in working state")
        state["working"].remove(item)
        item["report"] = report
        item["completed_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        state["done"].append(item)

        promoted = None
        if state["queued"] and len(state["working"]) < self.max_concurrency:
            promoted = state["queued"].pop(0)
            state["working"].append(promoted)

        self._write_state(state)
        return promoted

    def status(self) -> Dict[str, Any]:
        return self._read_state()


class ProjectsHarness:
    def __init__(self, workspace_dir: Path, max_concurrency: int = 2):
        self.workspace = Path(workspace_dir)
        self.storage_dir = self.workspace / ".projects"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.log = LogManager(self.storage_dir)
        self.memory = MemoryWriter(self.storage_dir)
        self.envelope = EnvelopeHook()
        self.router = RouteChecker()
        self.clash = ClashChecker()
        self.queue = QueueLimiter(self.storage_dir, max_concurrency=max_concurrency)

    def startup(self, memory_cap: int = 200, recent_limit: int = 5) -> Dict[str, Any]:
        recent_msgs = self.log.get_recent(limit=recent_limit)
        q_status = self.queue.status()
        mem_lines, was_capped = self.memory.load(cap=memory_cap)
        return {
            "recent_messages": recent_msgs,
            "jobs_status": {
                "working_count": len(q_status["working"]),
                "queued_count": len(q_status["queued"]),
                "done_count": len(q_status["done"]),
                "working_tasks": [t["task_id"] for t in q_status["working"]],
            },
            "memory": mem_lines,
            "memory_was_capped": was_capped,
            "memory_line_count": len(mem_lines),
        }
