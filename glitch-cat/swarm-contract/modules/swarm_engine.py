#!/usr/bin/env python3
import datetime
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class SwarmBudgetExceededError(Exception):
    pass


class ScorecardValidationError(Exception):
    pass


class SwarmContract:
    def __init__(self, workspace_dir: Path):
        self.workspace = Path(workspace_dir)
        self.swarm_dir = self.workspace / ".swarm"
        self.manifest_file = self.swarm_dir / "manifest.json"
        self.scorecards_file = self.swarm_dir / "scorecards.jsonl"
        self.swarm_dir.mkdir(parents=True, exist_ok=True)

    def init_swarm(self, goal: str, max_budget_usd: float = 5.0, max_tokens: int = 500000, required_schema: Optional[List[str]] = None) -> Dict[str, Any]:
        manifest = {
            "goal": goal.strip(),
            "max_budget_usd": float(max_budget_usd),
            "max_tokens": int(max_tokens),
            "current_spend_usd": 0.0,
            "current_tokens": 0,
            "required_fields": required_schema or ["worker_id", "target", "status", "findings"],
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "status": "active"
        }
        self.manifest_file.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return manifest

    def get_manifest(self) -> Dict[str, Any]:
        if not self.manifest_file.exists():
            raise FileNotFoundError("Swarm manifest not initialized. Run 'init' first.")
        return json.loads(self.manifest_file.read_text(encoding="utf-8"))

    def check_budget_availability(self, estimated_tokens: int = 10000, estimated_usd: float = 0.05) -> bool:
        man = self.get_manifest()
        if man["current_spend_usd"] + estimated_usd > man["max_budget_usd"]:
            return False
        if man["current_tokens"] + estimated_tokens > man["max_tokens"]:
            return False
        return True

    def record_scorecard(self, scorecard: Dict[str, Any], tokens_used: int = 0, cost_usd: float = 0.0) -> Dict[str, Any]:
        man = self.get_manifest()

        # Hard budget ceiling check
        new_spend = man["current_spend_usd"] + cost_usd
        new_tokens = man["current_tokens"] + tokens_used

        if new_spend > man["max_budget_usd"] or new_tokens > man["max_tokens"]:
            man["status"] = "budget_exhausted"
            self.manifest_file.write_text(json.dumps(man, indent=2), encoding="utf-8")
            raise SwarmBudgetExceededError(
                f"Hard budget exceeded! Spend: ${new_spend:.4f}/${man['max_budget_usd']:.2f}, Tokens: {new_tokens}/{man['max_tokens']}"
            )

        # Validate scorecard schema
        for req in man["required_fields"]:
            if req not in scorecard or scorecard[req] is None or str(scorecard[req]).strip() == "":
                raise ScorecardValidationError(f"Scorecard missing required field: '{req}'")

        entry = {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "tokens_used": tokens_used,
            "cost_usd": cost_usd,
            "scorecard": scorecard,
        }

        with open(self.scorecards_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

        # Update manifest
        man["current_spend_usd"] = round(new_spend, 6)
        man["current_tokens"] = new_tokens
        self.manifest_file.write_text(json.dumps(man, indent=2), encoding="utf-8")
        return entry

    def summary(self) -> Dict[str, Any]:
        man = self.get_manifest()
        scorecards = []
        if self.scorecards_file.exists():
            for line in self.scorecards_file.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    scorecards.append(json.loads(line))

        return {
            "goal": man["goal"],
            "status": man["status"],
            "budget": {
                "max_usd": man["max_budget_usd"],
                "spent_usd": man["current_spend_usd"],
                "remaining_usd": round(man["max_budget_usd"] - man["current_spend_usd"], 4),
                "max_tokens": man["max_tokens"],
                "tokens_used": man["current_tokens"],
                "tokens_remaining": man["max_tokens"] - man["current_tokens"],
            },
            "total_scorecards": len(scorecards),
            "scorecards": scorecards,
        }
