# EdgeCase Brief (DGX Spark + NVIDIA NIM + Multi-Agent HIL)

## Goal
Build a hackathon-ready, LLM-driven hardware-in-the-loop debugger where:
- DGX Spark runs the full stack locally.
- NVIDIA NIM (Nemotron) provides one shared OpenAI-compatible endpoint.
- Multi-agent orchestration drives iterative debug decisions from UART evidence.
- `runner/` is the only module allowed to touch hardware.

This is a **multi-agent systems demo first**, with RP2350 as the current reference target.

## Core Story
Closed-loop debug cycle:
1) Build firmware and flash target
2) Capture UART truth stream
3) Analyze run artifacts
4) Planner/Coder/Debugger/Validator reason over evidence
5) Coordinator emits next experiments and operator guidance
6) Repeat until pass, then stop with a success message

## Environment / Platform
- Host: DGX Spark (`Ubuntu 24.04`, `ARM64`)
- Local endpoint:
  - `NIM_CHAT_URL=http://localhost:8000/v1/chat/completions`
  - `NIM_MODEL=nvidia/nemotron-nano-9b-v2`
- No required cloud inference path.
- Dashboard + orchestrator + agents + runner all execute on same host.

## Architecture Constraints
- `runner/` is the only hardware-touching boundary:
  - build commands
  - flash commands
  - `/dev/tty*` access
- USB CDC UART is the only truth layer.
- No logic analyzer dependency in current flow.

## Runner Contract
Runner must:
- auto-detect serial port (`/dev/serial/by-id/*` preferred)
- handle re-enumeration after flash
- timestamp captured UART lines
- stop capture on `RUN_END` or timeout
- emit actionable diagnostics on failure

Flash strategy (auto-detect, fast failure):
1) UF2 mass-storage copy
2) `picotool`
3) optional OpenOCD

## Artifact Contract (per run)
Each run directory under `runs/run_<timestamp>_<id>/` must include:
- `manifest.json`
- `firmware/firmware.elf`
- `firmware/firmware.uf2`
- `uart.log`
- `analysis.json`
- `triage.md`

No extra bundle files.

## Agent Model
Five roles over one NIM endpoint:
1) Planner
2) Coder
3) Critic (UI: Debugger)
4) Verifier (UI: Validator)
5) Summarizer (UI: Coordinator)

Behavior requirements:
- No hidden chain-of-thought exposure.
- Stream short reasoning summaries only:
  - `Evidence -> Hypothesis -> Next action`
- Stream live UART lines to CLI/dashboard.
- Prefer dependency-driven scheduling over cosmetic parallelism.

## Dashboard Requirements
- Live SSE stream (`GET /api/stream`)
- Start runs via `POST /api/run`
- Show:
  - Planner, Coder, Debugger, Coordinator, Validator panes
  - overall output
  - latest UART
  - run tracker
  - agent load/time chart

## Demo/Real Modes
- `demo` (mock): full pipeline without hardware
- `real`: build/flash/capture against connected hardware

Commands that must work:
- `make demo`
- `python3 orchestrator.py --case uart_demo --runs 8`

## Current Demo Cases
- `uart_demo` (baud hunt, blind-first strategy)
- `framing_hunt`
- `parity_hunt`
- `signature_check`

## Success Criteria
- Pipeline runs end-to-end in demo mode with clear agent activity.
- Real mode gives actionable diagnostics when toolchain/flash/UART fail.
- Agents converge on passing configuration within reasonable run count.
- README reflects actual behavior and DGX Spark + NIM deployment.
