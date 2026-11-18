#!/usr/bin/env python3
import datetime
import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional


class OrchestraConductor:
    def __init__(self, workspace_dir: Path):
        self.workspace = Path(workspace_dir)
        self.orchestra_dir = self.workspace / ".orchestra"
        self.sessions_file = self.orchestra_dir / "sessions.json"
        self.lock_file = self.orchestra_dir / "sessions.lock"
        self.orchestra_dir.mkdir(parents=True, exist_ok=True)

    def _read_sessions(self) -> Dict[str, Any]:
        if not self.sessions_file.exists():
            return {
                "plan": None,
                "approval": None,
                "active_sessions": [],
                "completed_sessions": [],
                "events": [],
            }
        data = json.loads(self.sessions_file.read_text(encoding="utf-8"))
        data.setdefault("plan", None)
        data.setdefault("approval", None)
        data.setdefault("active_sessions", [])
        data.setdefault("completed_sessions", [])
        data.setdefault("events", [])
        return data

    def _write_sessions(self, data: Dict[str, Any]):
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.orchestra_dir,
                prefix="sessions.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                temporary_file.write(json.dumps(data, indent=2))
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_path, self.sessions_file)
        finally:
            if temporary_path and temporary_path.exists():
                temporary_path.unlink()

    @contextmanager
    def _sessions_lock(self) -> Iterator[None]:
        with self.lock_file.open("a+b") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    @contextmanager
    def _edit_sessions(self) -> Iterator[Dict[str, Any]]:
        with self._sessions_lock():
            data = self._read_sessions()
            yield data
            self._write_sessions(data)

    @staticmethod
    def _required_text(name: str, value: Optional[str]) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must not be empty")
        return value.strip()

    @staticmethod
    def _timestamp() -> str:
        return datetime.datetime.now(datetime.timezone.utc).isoformat()

    def _record_event(self, data: Dict[str, Any], event_type: str, **details: Any) -> Dict[str, Any]:
        event = {
            "sequence": max((item["sequence"] for item in data["events"]), default=0) + 1,
            "type": event_type,
            "timestamp": self._timestamp(),
            **details,
        }
        data["events"].append(event)
        return event

    def draft_plan(
        self,
        audience: str,
        great: str,
        made: str,
        moves: str,
        feel: str,
        references: Optional[List[str]] = None,
        references_unnecessary: Optional[str] = None,
        readiness_cue: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._edit_sessions() as data:
            if data["approval"] is not None:
                raise ValueError("An approved plan cannot be changed")
            if data["active_sessions"] or data["completed_sessions"]:
                raise ValueError("A plan cannot be drafted after worker dispatch")

            normalized_references = [self._required_text("reference", reference) for reference in references or []]
            reason = references_unnecessary.strip() if references_unnecessary else None
            if bool(normalized_references) == bool(reason):
                raise ValueError("Provide one or more --reference values or --references-unnecessary, but not both")

            plan = {
                "audience": self._required_text("audience", audience),
                "great": self._required_text("great", great),
                "made": self._required_text("made", made),
                "moves": self._required_text("moves", moves),
                "feel": self._required_text("feel", feel),
                "references": normalized_references,
                "references_unnecessary": reason,
                "readiness_cue": readiness_cue.strip() if readiness_cue and readiness_cue.strip() else None,
                "drafted_at": self._timestamp(),
            }
            data["plan"] = plan
            self._record_event(data, "plan_drafted", plan=plan)
        return plan

    def approve_plan(self, approver: str) -> Dict[str, Any]:
        with self._edit_sessions() as data:
            if data["plan"] is None:
                raise ValueError("Draft a plan before approving it")
            if data["approval"] is not None:
                raise ValueError("The plan is already approved")

            approval = {
                "approver": self._required_text("approver", approver),
                "approved_at": self._timestamp(),
            }
            data["approval"] = approval
            self._record_event(data, "plan_approved", approver=approval["approver"])
        return approval

    def register_child_session(
        self,
        session_id: str,
        task: str,
        role: str,
        scope: str,
        terminal_tag: str = "term_01",
    ) -> Dict[str, Any]:
        with self._edit_sessions() as data:
            if data["approval"] is None:
                raise ValueError("Worker dispatch is blocked until a human approves the plan")
            session_id = self._required_text("session_id", session_id)
            if any(s["session_id"] == session_id for s in data["active_sessions"] + data["completed_sessions"]):
                raise ValueError(f"Session '{session_id}' is already registered")
            session_entry = {
                "session_id": session_id,
                "task": self._required_text("task", task),
                "role": self._required_text("role", role),
                "scope": self._required_text("scope", scope),
                "terminal_tag": self._required_text("terminal_tag", terminal_tag),
                "status": "running",
                "started_at": self._timestamp(),
            }
            data["active_sessions"].append(session_entry)
            self._record_event(
                data,
                "worker_registered",
                session_id=session_id,
                role=session_entry["role"],
                scope=session_entry["scope"],
            )
        return session_entry

    def record_worker_signal(
        self,
        session_id: str,
        message: Optional[str] = None,
        worker_status: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._edit_sessions() as data:
            matched = next((s for s in data["active_sessions"] if s["session_id"] == session_id), None)
            if not matched:
                raise ValueError(f"Session '{session_id}' not found in active sessions")
            if not message and not worker_status:
                raise ValueError("A worker signal needs --message, --status, or both")

            normalized_message = self._required_text("message", message) if message else None
            normalized_status = self._required_text("status", worker_status) if worker_status else None
            if normalized_status:
                matched["worker_status"] = normalized_status
            event = self._record_event(
                data,
                "worker_signal",
                to="conductor",
                session_id=session_id,
                role=matched["role"],
                message=normalized_message,
                worker_status=normalized_status,
            )
        return event

    def record_worker_comparison(
        self,
        session_id: str,
        prompt: str,
        before: str,
        after: str,
        assessment: str,
    ) -> Dict[str, Any]:
        with self._edit_sessions() as data:
            matched = next((s for s in data["active_sessions"] if s["session_id"] == session_id), None)
            if not matched:
                raise ValueError(f"Session '{session_id}' not found in active sessions")
            event = self._record_event(
                data,
                "worker_comparison",
                to="conductor",
                session_id=session_id,
                role=matched["role"],
                prompt=self._required_text("prompt", prompt),
                before=self._required_text("before", before),
                after=self._required_text("after", after),
                assessment=self._required_text("assessment", assessment),
            )
        return event

    def mark_session_complete(self, session_id: str, summary: str = "Finished", evidence: str = None) -> Dict[str, Any]:
        with self._edit_sessions() as data:
            matched = next((s for s in data["active_sessions"] if s["session_id"] == session_id), None)
            if not matched:
                raise ValueError(f"Session '{session_id}' not found in active sessions")

            evidence_path = Path(evidence).expanduser().resolve() if evidence else None
            if evidence_path and not evidence_path.is_file():
                raise FileNotFoundError(f"Evidence '{evidence_path}' does not exist; a completion claim needs proof")

            data["active_sessions"].remove(matched)
            matched["status"] = "completed"
            matched["summary"] = summary
            matched["evidence"] = str(evidence_path) if evidence_path else None
            matched["verified"] = bool(evidence_path)
            matched["completed_at"] = self._timestamp()
            data["completed_sessions"].append(matched)
            self._record_event(data, "worker_completed", session_id=session_id, verified=matched["verified"])
        return matched

    def trigger_completion_alert(self, message: str = "All orchestra subagents have completed their tasks.") -> Dict[str, Any]:
        # Audible terminal bell and optional audio synthesis
        bell_emitted = False
        try:
            print("\a", end="", flush=True)
            bell_emitted = True
        except Exception:
            pass

        return {
            "alert_message": message,
            "bell_emitted": bell_emitted,
            "timestamp": self._timestamp(),
        }

    def status(self) -> Dict[str, Any]:
        data = self._read_sessions()
        return {
            "plan": data["plan"],
            "approval": data["approval"],
            "dispatch_approved": data["approval"] is not None,
            "active_count": len(data["active_sessions"]),
            "completed_count": len(data["completed_sessions"]),
            "verified_count": sum(1 for s in data["completed_sessions"] if s.get("verified")),
            "active_sessions": data["active_sessions"],
            "completed_sessions": data["completed_sessions"],
            "events": data["events"],
        }
