from __future__ import annotations

import json
from pathlib import Path

from agents import AnalystAgent, PlannerAgent, TriageAgent
from runner import Runner, RunConfig


def print_run_result(run_dir: Path) -> None:
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    triage = json.loads((run_dir / "triage.json").read_text(encoding="utf-8"))
    print(f"{manifest['run_id']}: status={manifest['status']}, baud={manifest['config']['baud_rate']}")
    print(f"  triage: {triage['root_cause']}")


def main() -> None:
    print("=== Demo: fail -> diagnose -> tweak param -> pass ===")

    runner = Runner("runs")
    analyst = AnalystAgent()
    triage = TriageAgent()
    planner = PlannerAgent()

    run1 = runner.execute(RunConfig(run_id="run_001", baud_rate=9600, mode="mock"))
    analyst.analyze(run1)
    triage.triage(run1)
    print_run_result(run1)

    next_baud = planner.plan_next_baud(run1, default_baud=9600)
    run2 = runner.execute(RunConfig(run_id="run_002", baud_rate=next_baud, mode="mock"))
    analyst.analyze(run2)
    triage.triage(run2)
    print_run_result(run2)

    print("Artifacts written to runs/run_001 and runs/run_002")


if __name__ == "__main__":
    main()
