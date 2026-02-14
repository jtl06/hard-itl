from __future__ import annotations

from pathlib import Path
import json


class PlannerAgent:
    def plan_next_baud(self, run_dir: Path, default_baud: int) -> int:
        triage_path = run_dir / "triage.json"
        if not triage_path.exists():
            return default_baud
        triage = json.loads(triage_path.read_text(encoding="utf-8"))
        return int(triage.get("next_baud_rate", default_baud))
