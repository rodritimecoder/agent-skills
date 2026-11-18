#!/usr/bin/env python3
import datetime
import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple


class PropagationRiskError(Exception):
    def __init__(self, step_idx: int, step_name: str, step_type: str, failure_reason: str):
        super().__init__(f"🛑 [PROPAGATION RISK HALT] Step {step_idx} ('{step_name}', [{step_type}]) failed assertion: {failure_reason}")
        self.step_idx = step_idx
        self.step_name = step_name
        self.step_type = step_type
        self.failure_reason = failure_reason


class StepDef:
    def __init__(self, name: str, step_type: str, handler: Callable[..., Any], validator: Optional[Callable[[Any], Tuple[bool, str]]] = None):
        if step_type not in ("D", "P", "H"):
            raise ValueError(f"Invalid step type '{step_type}'. Must be 'D' (Deterministic), 'P' (Probabilistic), or 'H' (Human)")
        self.name = name
        self.step_type = step_type
        self.handler = handler
        self.validator = validator


class EvalPipeline:
    def __init__(self, ledger_dir: Path):
        self.ledger_dir = Path(ledger_dir)
        self.ledger_dir.mkdir(parents=True, exist_ok=True)
        self.steps: List[StepDef] = []

    def register_step(self, name: str, step_type: str, handler: Callable[..., Any], validator: Optional[Callable[[Any], Tuple[bool, str]]] = None):
        self.steps.append(StepDef(name, step_type, handler, validator))

    def run(self, initial_input: Any) -> Dict[str, Any]:
        current_data = initial_input
        history = []

        for idx, s in enumerate(self.steps, 1):
            artifact_file = self.ledger_dir / f"step_{idx:02d}_{s.name}.json"
            start_time = datetime.datetime.now(datetime.timezone.utc).isoformat()

            # Execute step handler
            output = s.handler(current_data)

            # Validate output before proceeding
            if s.validator:
                valid, reason = s.validator(output)
                if not valid:
                    # Save failed artifact for post-mortem
                    fail_record = {
                        "step_index": idx,
                        "step_name": s.name,
                        "step_type": s.step_type,
                        "status": "failed",
                        "failure_reason": reason,
                        "input": current_data,
                        "output": output,
                        "timestamp": start_time,
                    }
                    artifact_file.write_text(json.dumps(fail_record, indent=2), encoding="utf-8")
                    raise PropagationRiskError(idx, s.name, s.step_type, reason)

            # Record successful intermediate artifact
            record = {
                "step_index": idx,
                "step_name": s.name,
                "step_type": s.step_type,
                "status": "passed",
                "output": output,
                "timestamp": start_time,
            }
            artifact_file.write_text(json.dumps(record, indent=2), encoding="utf-8")
            history.append(record)
            current_data = output

        return {
            "status": "success",
            "total_steps": len(self.steps),
            "final_output": current_data,
            "artifacts_dir": str(self.ledger_dir),
            "step_records": history,
        }
