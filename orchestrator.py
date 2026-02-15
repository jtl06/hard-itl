from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from agents import AnalystAgent, PlannerAgent, TriageAgent
from agents.orchestrator_nim import NIMOrchestrator, parse_next_experiments
from runner.flash import FlashError
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


def run_case(
    case_id: str,
    runs: int,
    mode: str,
    live: bool = False,
    uart_tail_lines: int = 8,
    show_agent_fragments: bool = False,
    state_file: str = "",
    live_uart: bool = False,
    trace: bool = False,
    verbose: bool = False,
) -> list[dict[str, Any]]:
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
        build_cmd=str(cfg.get("runner", {}).get("build_cmd", "")),
        build_cwd=str(cfg.get("runner", {}).get("build_cwd", ".")),
        real_elf_path=str(cfg.get("runner", {}).get("real_elf_path", "")),
        real_uf2_path=str(cfg.get("runner", {}).get("real_uf2_path", "")),
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

    state_path = Path(state_file) if state_file else None
    state = _init_state(case_id=case_id, runs=runs, mode=mode)
    if state_path is not None:
        _write_state(state_path, state)

    rows: list[dict[str, Any]] = []
    for run_index in range(1, runs + 1):
        _set_overall(state, status="running", message=f"Running {run_index}/{runs}", current_run=run_index)
        _set_agent(
            state,
            "planner",
            "running",
            "Planning next run parameters",
            _reasoning_summary(state, "planner", "running", "pre-run planning"),
        )
        _set_agent(
            state,
            "coder",
            "running",
            "Preparing instrumentation strategy",
            _reasoning_summary(state, "coder", "running", "preparing instrumentation"),
        )
        _set_agent(
            state,
            "critic",
            "running",
            "Preparing feasibility checks",
            _reasoning_summary(state, "critic", "running", "preparing checks"),
        )
        _set_agent(
            state,
            "summarizer",
            "running",
            "Waiting to merge agent outputs",
            _reasoning_summary(state, "summarizer", "running", "awaiting fan-in"),
        )
        if state_path is not None:
            _write_state(state_path, state)
        if live or verbose:
            print(f"[run {run_index}/{runs}] start case={case_id} params={params}")
        uart_stream: list[str] = []

        def _on_uart_line(line: str) -> None:
            uart_stream.append(line)
            state["latest_uart"] = uart_stream[-uart_tail_lines:]
            if live_uart or verbose:
                print(f"[uart] {line}")
            if state_path is not None:
                _write_state(state_path, state)

        run_result = runner.execute(
            case_id=case_id,
            run_index=run_index,
            params=params,
            mode=mode,
            uart_line_callback=_on_uart_line,
            emulate_timing=(mode == "mock" and (state_path is not None or live_uart or verbose)),
        )
        run_dir = Path(run_result["run_dir"])

        _set_agent(
            state,
            "planner",
            "done",
            "Run params fixed for this iteration",
            _reasoning_summary(state, "planner", "done", "params selected"),
        )
        _set_overall(state, status="running", message=f"Analyzing run {run_index}/{runs}", current_run=run_index)
        _update_latest_uart(state, run_dir=run_dir, tail_lines=uart_tail_lines)
        if state_path is not None:
            _write_state(state_path, state)

        analysis = analyst.analyze(run_dir)
        _set_agent(
            state,
            "coder",
            "running",
            "Drafting instrumentation/fix suggestions",
            _reasoning_summary(state, "coder", "running", "analysis complete"),
        )
        _set_agent(
            state,
            "critic",
            "running",
            "Reviewing risk and feasibility",
            _reasoning_summary(state, "critic", "running", "analysis complete"),
        )
        _set_agent(
            state,
            "summarizer",
            "running",
            "Merging planner/coder/debugger outputs",
            _reasoning_summary(state, "summarizer", "running", "fan-in"),
        )
        if state_path is not None:
            _write_state(state_path, state)

        triage = triage_agent.triage(run_dir, analysis=analysis, params=params)
        nim_summary = _nim_guidance(
            nim_orchestrator,
            case_id,
            run_result,
            analysis,
            triage,
            status_updater=lambda role, s, msg: _nim_status_update(
                state,
                state_path,
                role,
                s,
                msg,
                trace_to_stdout=(trace or verbose),
            ),
        )
        nim_next_experiments = parse_next_experiments(nim_summary)
        state["overall_output"] = nim_summary
        _set_agent(
            state,
            "coder",
            "done",
            "Instrumentation proposal finalized",
            _reasoning_summary(state, "coder", "done", "proposal finalized"),
        )
        _set_agent(
            state,
            "critic",
            "done",
            "Risk review finalized",
            _reasoning_summary(state, "critic", "done", "risk review finalized"),
        )
        _set_agent(
            state,
            "summarizer",
            "done",
            "Merged runbook ready",
            _reasoning_summary(state, "summarizer", "done", "merged output ready"),
        )
        state["history"].append(
            {
                "run": run_index,
                "run_id": run_result["run_id"],
                "status": analysis.pass_fail,
                "uart_rate": params["uart_rate"],
                "buffer_size": params["buffer_size"],
                "error_count": analysis.metrics["error_count"],
                "run_dir": run_result["run_dir"],
            }
        )
        state["last_analysis"] = analysis.metrics
        _update_latest_uart(state, run_dir=run_dir, tail_lines=uart_tail_lines)
        if state_path is not None:
            _write_state(state_path, state)
        if live or verbose:
            _print_live_run_details(
                run_result=run_result,
                run_dir=run_dir,
                analysis=analysis,
                uart_tail_lines=uart_tail_lines,
                nim_orchestrator=nim_orchestrator,
                show_agent_fragments=show_agent_fragments,
            )

        row = {
            "run": run_index,
            "run_id": run_result["run_id"],
            "status": analysis.pass_fail,
            "uart_rate": params["uart_rate"],
            "buffer_size": params["buffer_size"],
            "error_count": analysis.metrics["error_count"],
            "run_dir": run_result["run_dir"],
            "diagnostics": run_result.get("diagnostics", []),
        }
        rows.append(row)
        if analysis.pass_fail != "pass":
            diag_text = "; ".join(run_result.get("diagnostics", [])[-2:])
            _set_overall(
                state,
                status="running",
                message=f"Run {run_index} failed: {diag_text or 'see uart.log'}",
                current_run=run_index,
            )
            if state_path is not None:
                _write_state(state_path, state)

        if analysis.pass_fail != "pass" and nim_next_experiments:
            params = nim_next_experiments[0]
        else:
            params = planner.next_request(params, analysis=analysis, triage=triage)

    _set_overall(state, status="completed", message="Run sequence complete", current_run=runs)
    for role in ("planner", "coder", "critic", "summarizer"):
        if state["agents"][role]["status"] == "running":
            _set_agent(
                state,
                role,
                "done",
                state["agents"][role]["task"],
                state["agents"][role]["fragment"],
            )
    if state_path is not None:
        _write_state(state_path, state)

    return rows


def _nim_guidance(
    nim_orchestrator: NIMOrchestrator | None,
    case_id: str,
    run_result: dict[str, Any],
    analysis: Any,
    triage: Any,
    status_updater: Callable[[str, str, str], None] | None = None,
) -> str:
    if nim_orchestrator is None:
        if status_updater is not None:
            for role in ("planner", "coder", "critic", "summarizer"):
                status_updater(role, "disabled", "NIM orchestration disabled.")
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
        return asyncio.run(nim_orchestrator.run(prompt, status_callback=status_updater))
    except Exception as exc:
        if status_updater is not None:
            status_updater("summarizer", "error", str(exc))
        return nim_orchestrator._fallback_summary(str(exc), prompt)


def _init_state(case_id: str, runs: int, mode: str) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    now_epoch = time.time()
    return {
        "overall": {
            "status": "idle",
            "message": "Waiting to start",
            "case_id": case_id,
            "mode": mode,
            "runs_total": runs,
            "current_run": 0,
            "updated_at": now,
        },
        "agents": {
            "planner": {"status": "idle", "task": "Waiting", "fragment": "", "updated_at": now},
            "coder": {"status": "idle", "task": "Waiting", "fragment": "", "updated_at": now},
            "critic": {"status": "idle", "task": "Waiting", "fragment": "", "updated_at": now},
            "summarizer": {"status": "idle", "task": "Waiting", "fragment": "", "updated_at": now},
        },
        "agent_metrics": {
            "planner": {"active_s": 0.0, "last_status": "idle", "last_change_epoch": now_epoch},
            "coder": {"active_s": 0.0, "last_status": "idle", "last_change_epoch": now_epoch},
            "critic": {"active_s": 0.0, "last_status": "idle", "last_change_epoch": now_epoch},
            "summarizer": {"active_s": 0.0, "last_status": "idle", "last_change_epoch": now_epoch},
        },
        "latest_uart": [],
        "last_analysis": {},
        "overall_output": "",
        "history": [],
    }


def _write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _set_overall(state: dict[str, Any], status: str, message: str, current_run: int) -> None:
    state["overall"]["status"] = status
    state["overall"]["message"] = message
    state["overall"]["current_run"] = current_run
    state["overall"]["updated_at"] = datetime.now(timezone.utc).isoformat()


def _set_agent(state: dict[str, Any], role: str, status: str, task: str, fragment: str | None = None) -> None:
    _update_agent_metrics(state, role, status)
    frag = fragment if fragment is not None else task
    if len(frag) > 180:
        frag = frag[:177] + "..."
    state["agents"][role]["status"] = status
    state["agents"][role]["task"] = task
    state["agents"][role]["fragment"] = frag
    state["agents"][role]["updated_at"] = datetime.now(timezone.utc).isoformat()


def _update_agent_metrics(state: dict[str, Any], role: str, new_status: str) -> None:
    metrics = state.setdefault("agent_metrics", {})
    entry = metrics.setdefault(
        role,
        {"active_s": 0.0, "last_status": "idle", "last_change_epoch": time.time()},
    )
    now = time.time()
    last_status = entry.get("last_status", "idle")
    last_change = float(entry.get("last_change_epoch", now))
    if last_status == "running":
        entry["active_s"] = float(entry.get("active_s", 0.0)) + max(0.0, now - last_change)
    entry["last_status"] = new_status
    entry["last_change_epoch"] = now


def _nim_status_update(
    state: dict[str, Any],
    state_path: Path | None,
    role: str,
    status: str,
    message: str,
    trace_to_stdout: bool = False,
) -> None:
    reasoning = _reasoning_summary(state=state, role=role, status=status, message=message)
    task_map = {
        "planner": "Planning next experiments",
        "coder": "Drafting instrumentation suggestions",
        "critic": "Reviewing risk and feasibility",
        "summarizer": "Coordinating merged runbook",
    }
    _set_agent(state, role, status, task_map.get(role, role.title()), reasoning)
    if trace_to_stdout and role in {"planner", "critic", "summarizer"}:
        print(f"[{role}] {reasoning}")
    if state_path is not None:
        _write_state(state_path, state)


def _reasoning_summary(state: dict[str, Any], role: str, status: str, message: str) -> str:
    metrics = state.get("last_analysis", {})
    err = metrics.get("error_count", "n/a")
    miss_end = metrics.get("missing_end", "n/a")
    last_code = metrics.get("last_error_code") or "none"
    evidence = f"errors={err}, missing_end={miss_end}, last_error={last_code}"

    hypothesis_map = {
        "planner": "parameter instability likely when UART is too aggressive",
        "coder": "instrumentation gap may hide run boundary or error details",
        "critic": "proposed change may violate runner-only hardware boundaries",
        "summarizer": "best next step is smallest experiment that can confirm root cause",
    }
    next_map = {
        "planner": "propose conservative uart_rate/buffer_size experiment",
        "coder": "suggest minimal logging/marker patch only",
        "critic": "flag feasibility/risk and request safer fallback",
        "summarizer": "merge outputs into operator runbook",
    }
    hyp = hypothesis_map.get(role, "root cause under review")
    nxt = next_map.get(role, "continue analysis")
    if status in {"error", "disabled", "fallback"}:
        hyp = message[:120] if message else hyp
    return f"Evidence: {evidence} | Hypothesis: {hyp} | Next action: {nxt}"


def _update_latest_uart(state: dict[str, Any], run_dir: Path, tail_lines: int) -> None:
    uart_path = run_dir / "uart.log"
    if not uart_path.exists():
        state["latest_uart"] = []
        return
    lines = [ln.rstrip("\n") for ln in uart_path.read_text(encoding="utf-8").splitlines()]
    state["latest_uart"] = lines[-tail_lines:]


def _print_live_run_details(
    run_result: dict[str, Any],
    run_dir: Path,
    analysis: Any,
    uart_tail_lines: int,
    nim_orchestrator: NIMOrchestrator | None,
    show_agent_fragments: bool,
) -> None:
    print(f"  run_id={run_result['run_id']} status={analysis.pass_fail} flash={run_result['flash_method']}")
    for note in run_result.get("diagnostics", []):
        print(f"  diag: {note}")

    uart_path = run_dir / "uart.log"
    if uart_path.exists():
        lines = [ln.rstrip("\n") for ln in uart_path.read_text(encoding="utf-8").splitlines()]
        print(f"  uart.log tail ({min(uart_tail_lines, len(lines))} lines):")
        for ln in lines[-uart_tail_lines:]:
            print(f"    {ln}")
    else:
        print("  uart.log not found")

    metrics = analysis.metrics
    print(
        "  analysis:"
        f" errors={metrics.get('error_count')}"
        f" missing_start={metrics.get('missing_start')}"
        f" missing_end={metrics.get('missing_end')}"
        f" lps={metrics.get('lines_per_sec')}"
        f" max_gap_ms={metrics.get('max_gap_ms')}"
        f" last_error={metrics.get('last_error_code') or 'none'}"
    )

    if show_agent_fragments and nim_orchestrator is not None and nim_orchestrator.last_fanout:
        print("  agent fragments:")
        for item in nim_orchestrator.last_fanout:
            frag = " ".join(item.text.split())
            if len(frag) > 180:
                frag = frag[:177] + "..."
            print(f"    {item.role}: {frag}")


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
    parser.add_argument("--live", action="store_true", help="Print per-run diagnostics and UART log tail")
    parser.add_argument("--uart-tail-lines", type=int, default=8, help="Number of UART lines to print in live mode")
    parser.add_argument(
        "--show-agent-fragments",
        action="store_true",
        help="Print short planner/coder/critic response fragments in live mode",
    )
    parser.add_argument("--state-file", default="", help="Write live dashboard state JSON to this path")
    parser.add_argument("--live-uart", action="store_true", help="Print UART lines live as they are captured")
    parser.add_argument("--trace", action="store_true", help="Print live agent reasoning summaries")
    parser.add_argument("--verbose", action="store_true", help="Enable all live CLI output")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        rows = run_case(
            case_id=args.case,
            runs=args.runs,
            mode=args.mode,
            live=args.live,
            uart_tail_lines=args.uart_tail_lines,
            show_agent_fragments=args.show_agent_fragments,
            state_file=args.state_file,
            live_uart=args.live_uart,
            trace=args.trace,
            verbose=args.verbose,
        )
    except FlashError as exc:
        if args.state_file:
            fail_state = _init_state(case_id=args.case, runs=args.runs, mode=args.mode)
            _set_overall(
                fail_state,
                status="failed",
                message=f"Runner configuration error: {exc}",
                current_run=fail_state["overall"]["current_run"],
            )
            _write_state(Path(args.state_file), fail_state)
        print(f"Runner configuration error: {exc}")
        print("Set runner.build_cmd and runner.real_uf2_path in config.yaml before using --mode real.")
        raise SystemExit(2)
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        print_summary(rows)


if __name__ == "__main__":
    main()
