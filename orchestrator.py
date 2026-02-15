from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
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
        elif re.fullmatch(r"[+-]?\d+", val):
            parsed = int(val)
        elif re.fullmatch(r"[+-]?(?:\d+\.\d*|\d*\.\d+)", val):
            parsed = float(val)
        else:
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
    target_baud: int = 0,
    target_frame: str = "",
    target_parity: str = "",
    target_magic: str = "",
    nim_mode: str = "",
) -> list[dict[str, Any]]:
    cfg = parse_config("config.yaml")
    nim_cfg = cfg.get("nim", {})
    nim_enabled = bool(nim_cfg.get("enabled", True))
    os.environ.setdefault("NIM_CHAT_URL", str(nim_cfg.get("chat_url", "http://localhost:8000/v1/chat/completions")))
    os.environ.setdefault("NIM_MODEL", str(nim_cfg.get("model", "nvidia/nemotron-nano-9b-v2")))
    selected_nim_mode = nim_mode or str(nim_cfg.get("execution_mode", "sequential"))
    os.environ["NIM_EXECUTION_MODE"] = selected_nim_mode
    os.environ["NIM_COORDINATOR_REWORK_ROUNDS"] = str(int(nim_cfg.get("coordinator_rework_rounds", 1)))
    os.environ["NIM_PEER_MESSAGE_ROUNDS"] = str(int(nim_cfg.get("peer_message_rounds", 1)))

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
        openocd_cfg=str(cfg.get("runner", {}).get("openocd_cfg", "")),
        auto_bootsel=bool(cfg.get("runner", {}).get("auto_bootsel", True)),
    )

    runner = Runner(runner_cfg)
    planner = PlannerAgent()
    analyst = AnalystAgent()
    triage_agent = TriageAgent()
    nim_orchestrator = NIMOrchestrator() if nim_enabled else None

    case_cfg = cfg.get("cases", {}).get(case_id, {})
    hidden_eval_context: dict[str, Any] = {}
    params = {
        "uart_rate": int(case_cfg.get("initial_uart_rate", 1000000)),
        "buffer_size": int(case_cfg.get("initial_buffer_size", 16)),
    }
    if case_id == "uart_demo":
        default_target_baud = int(case_cfg.get("target_baud", 115200))
        selected_target = target_baud if target_baud > 0 else default_target_baud
        params = {
            "guess_baud": int(case_cfg.get("initial_guess_baud", 57600)),
            "baud_probe_idx": 0,
            "last_baud_direction": "unknown",
            "last_baud_guess": int(case_cfg.get("initial_guess_baud", 57600)),
        }
        hidden_eval_context["target_baud"] = selected_target
    elif case_id == "framing_hunt":
        selected_target_frame = target_frame or str(case_cfg.get("target_frame", "8N1"))
        params = {
            "guess_frame": str(case_cfg.get("initial_guess_frame", "7E1")),
            "target_frame": selected_target_frame,
        }
    elif case_id == "parity_hunt":
        selected_target_parity = target_parity or str(case_cfg.get("target_parity", "even"))
        params = {
            "guess_parity": str(case_cfg.get("initial_guess_parity", "none")),
            "target_parity": selected_target_parity,
        }
    elif case_id == "signature_check":
        default_target_magic = int(case_cfg.get("target_magic", 0xC0FFEE42))
        if target_magic:
            parsed_target_magic = int(target_magic, 0)
        else:
            parsed_target_magic = default_target_magic
        params = {
            "guess_magic": int(case_cfg.get("initial_guess_magic", 0x0BADF00D)),
            "target_magic": parsed_target_magic,
        }
    if not case_cfg:
        params = planner.initial_request()

    state_path = Path(state_file) if state_file else None
    state = _init_state(case_id=case_id, runs=runs, mode=mode)
    if state_path is not None:
        _write_state(state_path, state)

    rows: list[dict[str, Any]] = []
    solved = False
    solved_run = 0
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
            "idle",
            "Waiting for UART evidence",
            _reasoning_summary(state, "coder", "idle", "waiting for evidence"),
        )
        _set_agent(
            state,
            "critic",
            "idle",
            "Waiting for UART evidence",
            _reasoning_summary(state, "critic", "idle", "waiting for evidence"),
        )
        _set_agent(
            state,
            "summarizer",
            "idle",
            "Waiting for fan-in",
            _reasoning_summary(state, "summarizer", "idle", "awaiting fan-in"),
        )
        _set_agent(
            state,
            "verifier",
            "idle",
            "Waiting for merged proposal",
            _reasoning_summary(state, "verifier", "idle", "awaiting merged proposal"),
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
            eval_context={
                **hidden_eval_context,
                "baud_hint_mode": "unknown" if run_index <= 2 else "directional",
            } if case_id == "uart_demo" else None,
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
            "idle",
            "Waiting for coder/debugger outputs",
            _reasoning_summary(state, "summarizer", "idle", "awaiting coder/debugger completion"),
        )
        _set_agent(
            state,
            "verifier",
            "idle",
            "Waiting for merged proposal",
            _reasoning_summary(state, "verifier", "idle", "awaiting merged proposal"),
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
        _set_agent(
            state,
            "verifier",
            "done",
            "Confidence verdict ready",
            _reasoning_summary(state, "verifier", "done", "verdict published"),
        )
        state["history"].append(
            {
                "run": run_index,
                "run_id": run_result["run_id"],
                "status": analysis.pass_fail,
                "guess_key": _guess_key(params) or "",
                "target_key": _target_key_for_guess(_guess_key(params) or "") or "",
                "guess_value": _guess_value(params),
                "target_value": _target_value(params),
                "uart_rate": int(params.get("uart_rate", 0)) if "uart_rate" in params else 0,
                "buffer_size": int(params.get("buffer_size", 0)) if "buffer_size" in params else 0,
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
            "guess_key": _guess_key(params) or "",
            "target_key": _target_key_for_guess(_guess_key(params) or "") or "",
            "guess_value": _guess_value(params),
            "target_value": _target_value(params),
            "uart_rate": int(params.get("uart_rate", 0)) if "uart_rate" in params else 0,
            "buffer_size": int(params.get("buffer_size", 0)) if "buffer_size" in params else 0,
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

        if analysis.pass_fail == "pass":
            solved = True
            solved_run = run_index
            _set_overall(
                state,
                status="completed",
                message=f"successful: converged at run {run_index}",
                current_run=run_index,
            )
            if state_path is not None:
                _write_state(state_path, state)
            if live or verbose:
                print(f"[result] successful at run {run_index}; stopping early")
            break

        if analysis.pass_fail != "pass" and nim_next_experiments:
            guess_key = _guess_key(params)
            if guess_key:
                match = [x for x in nim_next_experiments if guess_key in x]
                if match:
                    chosen = dict(match[0])
                    target_key = _target_key_for_guess(guess_key)
                    if target_key and target_key not in chosen and target_key in params:
                        chosen[target_key] = params[target_key]
                    params = chosen
                else:
                    params = planner.next_request(params, analysis=analysis, triage=triage)
            else:
                params = nim_next_experiments[0]
        else:
            params = planner.next_request(params, analysis=analysis, triage=triage)

    final_run = solved_run if solved else len(rows)
    final_msg = f"successful: converged at run {solved_run}" if solved else "Run sequence complete"
    _set_overall(state, status="completed", message=final_msg, current_run=final_run)
    for role in ("planner", "coder", "critic", "summarizer", "verifier"):
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
            for role in ("planner", "coder", "critic", "summarizer", "verifier"):
                status_updater(role, "disabled", "NIM orchestration disabled.")
        return "NIM orchestration disabled via config."

    prompt = (
        "Project context: RP2350 DUT with USB CDC UART as the only truth layer; "
        "runner is the only hardware-touching module. "
        f"case={case_id} run_id={run_result['run_id']} status={analysis.pass_fail} run_dir={run_result['run_dir']} "
        "Evidence files: uart.log, analysis.json, triage.md. "
        f"metrics={analysis.metrics} key_events={analysis.key_events} "
        f"triage_next_experiments={triage.next_experiments} triage_fix={triage.suggested_fix}. "
        "Generate next experiments, minimal instrumentation suggestions, risk review, verifier confidence, and merged demo guidance."
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
            "verifier": {"status": "idle", "task": "Waiting", "fragment": "", "updated_at": now},
        },
        "agent_metrics": {
            "planner": {"active_s": 0.0, "last_status": "idle", "last_change_epoch": now_epoch},
            "coder": {"active_s": 0.0, "last_status": "idle", "last_change_epoch": now_epoch},
            "critic": {"active_s": 0.0, "last_status": "idle", "last_change_epoch": now_epoch},
            "summarizer": {"active_s": 0.0, "last_status": "idle", "last_change_epoch": now_epoch},
            "verifier": {"active_s": 0.0, "last_status": "idle", "last_change_epoch": now_epoch},
        },
        "latest_uart": [],
        "agent_calls": [],
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
    # Keep a bit more model text visible in the dashboard before truncating.
    if len(frag) > 255:
        frag = frag[:252] + "..."
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
    if message.startswith("Peer call "):
        calls = state.setdefault("agent_calls", [])
        calls.append(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} {message}")
        if len(calls) > 40:
            del calls[:-40]
    reasoning = _reasoning_summary(state=state, role=role, status=status, message=message)
    task_map = {
        "planner": "Planning next experiments",
        "coder": "Drafting instrumentation suggestions",
        "critic": "Reviewing risk and feasibility",
        "summarizer": "Coordinating merged runbook",
        "verifier": "Scoring confidence from evidence",
    }
    _set_agent(state, role, status, task_map.get(role, role.title()), reasoning)
    if trace_to_stdout and role in {"planner", "critic", "summarizer", "verifier"}:
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
        "verifier": "evidence quality may be insufficient for high-confidence acceptance",
    }
    next_map = {
        "planner": "propose conservative uart_rate/buffer_size experiment",
        "coder": "suggest minimal logging/marker patch only",
        "critic": "flag feasibility/risk and request safer fallback",
        "summarizer": "merge outputs into operator runbook",
        "verifier": "publish confidence and explicit acceptance criteria",
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
            if len(frag) > 215:
                frag = frag[:212] + "..."
            print(f"    {item.role}: {frag}")


def print_summary(rows: list[dict[str, Any]]) -> None:
    guess_mode = any(str(r.get("guess_key", "")) != "" for r in rows)
    if guess_mode:
        print("run | status | guess | target | errors | run_id")
        print("-" * 76)
        for r in rows:
            print(
                f"{r['run']:>3} | {r['status']:<6} | {str(r.get('guess_value','')):<10} | "
                f"{str(r.get('target_value','')):<11} | {r['error_count']:<6} | {r['run_id']}"
            )
        if rows and rows[-1]["status"] == "pass":
            print("successful")
        return
    print("run | status | uart_rate | buffer_size | errors | run_id")
    print("-" * 72)
    for r in rows:
        print(
            f"{r['run']:>3} | {r['status']:<6} | {r['uart_rate']:<9} | "
            f"{r['buffer_size']:<11} | {r['error_count']:<6} | {r['run_id']}"
        )
    if rows and rows[-1]["status"] == "pass":
        print("successful")


def _guess_key(params: dict[str, Any]) -> str | None:
    for k in ("guess_baud", "guess_frame", "guess_parity", "guess_magic"):
        if k in params:
            return k
    return None


def _target_key_for_guess(guess_key: str) -> str | None:
    mapping = {
        "guess_baud": "target_baud",
        "guess_frame": "target_frame",
        "guess_parity": "target_parity",
        "guess_magic": "target_magic",
    }
    return mapping.get(guess_key)


def _guess_value(params: dict[str, Any]) -> Any:
    g = _guess_key(params)
    return params.get(g, "") if g else ""


def _target_value(params: dict[str, Any]) -> Any:
    g = _guess_key(params)
    if not g:
        return ""
    t = _target_key_for_guess(g)
    if not t:
        return ""
    if t not in params and g == "guess_baud":
        return "unknown"
    return params.get(t, "")


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
        help="Print short planner/coder/critic/verifier response fragments in live mode",
    )
    parser.add_argument("--state-file", default="", help="Write live dashboard state JSON to this path")
    parser.add_argument("--live-uart", action="store_true", help="Print UART lines live as they are captured")
    parser.add_argument("--trace", action="store_true", help="Print live agent reasoning summaries")
    parser.add_argument("--verbose", action="store_true", help="Enable all live CLI output")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--target-baud", type=int, default=0, help="Target baud for uart_demo baud-hunt mode")
    parser.add_argument("--target-frame", default="", help="Target frame (e.g. 8N1) for framing_hunt")
    parser.add_argument("--target-parity", default="", help="Target parity (none/even/odd) for parity_hunt")
    parser.add_argument("--target-magic", default="", help="Target magic hex (e.g. 0xC0FFEE42) for signature_check")
    parser.add_argument("--nim-mode", choices=["sequential", "parallel"], default="", help="Agent execution mode")
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
            target_baud=args.target_baud,
            target_frame=args.target_frame,
            target_parity=args.target_parity,
            target_magic=args.target_magic,
            nim_mode=args.nim_mode,
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
        if "real_uf2_path" in str(exc) or "build command failed" in str(exc):
            print("Check runner.build_cmd, runner.real_uf2_path, and PICO_SDK_PATH for --mode real.")
        raise SystemExit(2)
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        print_summary(rows)


if __name__ == "__main__":
    main()
