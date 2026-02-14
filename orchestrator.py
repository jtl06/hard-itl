from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any

from agents import AnalystAgent, PlannerAgent, TriageAgent
from agents.orchestrator_nim import NIMOrchestrator, parse_next_experiments
from runner import Runner, RunnerConfig


def parse_config(path: str = "config.yaml") -> dict[str, Any]:
    data: dict[str, Any] = {}
    section_stack: list[tuple[int, dict[str, Any]]] = [(-1, data)]

    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue

        indent = len(line) - len(line.lstrip(" "))
        key, _, val = line.strip().partition(":")
        val = val.strip()

        while section_stack and indent <= section_stack[-1][0]:
            section_stack.pop()
        current = section_stack[-1][1]

        if not val:
            obj: dict[str, Any] = {}
            current[key] = obj
            section_stack.append((indent, obj))
            continue

        if val.lower() in {"true", "false"}:
            parsed: Any = val.lower() == "true"
        else:
            try:
                parsed = int(val)
            except ValueError:
                try:
                    parsed = float(val)
                except ValueError:
                    parsed = val.strip('"')
        current[key] = parsed

    return data


def run_case(case_id: str, runs: int, mode: str) -> list[dict[str, Any]]:
    cfg = parse_config("config.yaml")
    nim_cfg = cfg.get("nim", {})
    nim_enabled = bool(nim_cfg.get("enabled", True))
    os.environ.setdefault("NIM_CHAT_URL", str(nim_cfg.get("chat_url", "http://localhost:8000/v1/chat/completions")))
    os.environ.setdefault("NIM_MODEL", str(nim_cfg.get("model", "nvidia/nemotron-nano-9b-v2")))

    runner_cfg = RunnerConfig(
        runs_root=str(cfg.get("paths", {}).get("runs_root", "runs")),
        flash_method=str(cfg.get("runner", {}).get("flash_method", "auto")),
        serial_port=str(cfg.get("runner", {}).get("serial_port", "")),
        serial_baud=int(cfg.get("runner", {}).get("serial_baud", 115200)),
        serial_timeout_s=float(cfg.get("runner", {}).get("serial_timeout_s", 8.0)),
        reenumeration_timeout_s=float(cfg.get("runner", {}).get("reenumeration_timeout_s", 8.0)),
        prefer_by_id=bool(cfg.get("runner", {}).get("prefer_by_id", True)),
    )

    runner = Runner(runner_cfg)
    planner = PlannerAgent()
    analyst = AnalystAgent()
    triage_agent = TriageAgent()
    nim_orchestrator = NIMOrchestrator() if nim_enabled else None

    case_cfg = cfg.get("cases", {}).get(case_id, {})
    params = {
        "uart_rate": int(case_cfg.get("initial_uart_rate", 1000000)),
        "buffer_size": int(case_cfg.get("initial_buffer_size", 16)),
    }
    if not case_cfg:
        params = planner.initial_request()

    rows: list[dict[str, Any]] = []
    for run_index in range(1, runs + 1):
        run_result = runner.execute(case_id=case_id, run_index=run_index, params=params, mode=mode)
        run_dir = Path(run_result["run_dir"])

        analysis = analyst.analyze(run_dir)
        triage = triage_agent.triage(run_dir, analysis=analysis, params=params)
        nim_summary = _nim_guidance(nim_orchestrator, case_id, run_result, analysis, triage)
        nim_next_experiments = parse_next_experiments(nim_summary)

        row = {
            "run": run_index,
            "run_id": run_result["run_id"],
            "status": analysis.pass_fail,
            "uart_rate": params["uart_rate"],
            "buffer_size": params["buffer_size"],
            "error_count": analysis.metrics["error_count"],
            "run_dir": run_result["run_dir"],
        }
        rows.append(row)

        if analysis.pass_fail != "pass" and nim_next_experiments:
            params = nim_next_experiments[0]
        else:
            params = planner.next_request(params, analysis=analysis, triage=triage)

    return rows


def _nim_guidance(
    nim_orchestrator: NIMOrchestrator | None,
    case_id: str,
    run_result: dict[str, Any],
    analysis: Any,
    triage: Any,
) -> str:
    if nim_orchestrator is None:
        return "NIM orchestration disabled via config."

    prompt = (
        "Project context: RP2350 DUT with USB CDC UART as the only truth layer; "
        "runner is the only hardware-touching module. "
        f"case={case_id} run_id={run_result['run_id']} status={analysis.pass_fail} run_dir={run_result['run_dir']} "
        "Evidence files: uart.log, analysis.json, triage.md. "
        f"metrics={analysis.metrics} key_events={analysis.key_events} "
        f"triage_next_experiments={triage.next_experiments} triage_fix={triage.suggested_fix}. "
        "Generate next experiments, minimal instrumentation suggestions, risk review, and merged demo guidance."
    )
    try:
        return asyncio.run(nim_orchestrator.run(prompt))
    except Exception as exc:
        return nim_orchestrator._fallback_summary(str(exc), prompt)


def print_summary(rows: list[dict[str, Any]]) -> None:
    print("run | status | uart_rate | buffer_size | errors | run_id")
    print("-" * 72)
    for r in rows:
        print(
            f"{r['run']:>3} | {r['status']:<6} | {r['uart_rate']:<9} | "
            f"{r['buffer_size']:<11} | {r['error_count']:<6} | {r['run_id']}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Multi-agent HIL orchestrator")
    parser.add_argument("--case", default="uart_demo")
    parser.add_argument("--runs", type=int, default=8)
    parser.add_argument("--mode", choices=["mock", "real"], default="mock")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    rows = run_case(case_id=args.case, runs=args.runs, mode=args.mode)
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        print_summary(rows)


if __name__ == "__main__":
    main()
