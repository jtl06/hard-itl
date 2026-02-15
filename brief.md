# EdgeCase (RP2350 + USB CDC UART + DGX Spark NIM)

## Goal
Build a hackathon-ready, multi-agent hardware-in-the-loop (HIL) debugger where:
- DUT is an RP2350 microcontroller connected over USB.
- USB CDC UART is the only truth layer.
- DGX Spark runs everything locally: orchestrator, agents, runner, and the NIM endpoint.

Closed-loop flow:
1) Build firmware with parameters
2) Flash DUT
3) Run test and capture UART stream
4) Agents analyze evidence bundle and hypothesize root cause
5) Planner proposes next experiments
6) Repeat until pass

## Environment / Constraints
- Host: DGX Spark (Ubuntu 24.04)
- Local LLM endpoint (OpenAI-compatible):
  - `NIM_CHAT_URL=http://localhost:8000/v1/chat/completions`
  - `NIM_MODEL=nvidia/nemotron-nano-9b-v2`
- No cloud calls.
- Runner is the ONLY component allowed to:
  - run `make`
  - flash hardware
  - access `/dev/tty*`
- Everything runnable via:
  - `python3 orchestrator.py --case uart_demo --runs 8`
  - `make demo`

## UART Truth Layer Requirements
- UART logs are captured from USB CDC serial:
  - prefer `/dev/serial/by-id/*`
  - fallback `/dev/ttyACM*` (and `/dev/ttyUSB*` when needed)
- UART lines must include:
  - `RUN_START <run_id>`
  - `ERROR <code> <msg>`
  - `RUN_END <run_id>`

## Runner Contract
Runner must:
- auto-detect serial port
- timestamp every captured UART line
- capture until `RUN_END <run_id>` or timeout
- handle serial re-enumeration after flashing
- expose `flash(image_path, method="auto")` returning success/failure + diagnostics

## Flashing Requirements (auto-detect)
Priority:
1) UF2 mass-storage copy (RPI-RP2 / Pico2 style mounted volume)
2) `picotool`
3) optional OpenOCD

Must fail fast with actionable diagnostics if no method works.

## Evidence Bundle (per run)
Store all outputs under:
- `runs/run_<timestamp>_<shortid>/`

Required files:
- `manifest.json`
  - run_id, case_id, params, git_sha, timestamps, flash_method, serial_port
- `firmware/`
  - built ELF + UF2 (if produced)
- `uart.log`
  - timestamped serial capture
- `analysis.json`
  - `pass_fail`
  - UART metrics
  - parsed error events
- `triage.md`
  - hypotheses + evidence references
  - next experiments
  - suggested fix (optional)

## Analysis Metrics
Focus on UART-only metrics:
- `error_count`
- `missing_start`
- `missing_end`
- `lines_per_sec`
- `max_gap_ms`
- `last_error_code`

## Repo Structure
- `runner/`
  - `runner.py`
  - `flash.py`
  - `serial_capture.py`
- `agents/`
  - `llm_client.py`
  - `planner.py`
  - `analyst.py`
  - `triage.py`
  - `orchestrator_nim.py`
- `schemas/types.py`
- `orchestrator.py`
- `config.yaml`
- `README.md`
- `Makefile`

## Agent Behavior
Implement exactly 4 LLM roles against one NIM endpoint:
1) planner
2) coder
3) critic
4) summarizer

Requirements:
- planner/coder/critic run concurrently (`asyncio`)
- summarizer merges outputs to one final answer
- no container lifecycle actions in code
- suggestions must respect runner-only hardware access

Provide:
- `agents/orchestrator_nim.py` using `aiohttp` + `asyncio`
- `tools/smoke_concurrency.sh` using 3 concurrent `curl` requests

## Minimal Demo Scenario
- Include deterministic synthetic flake driven by parameters.
- Planner/agents should find a stable passing config within ~6-8 runs.
- Mock mode must run end-to-end without hardware.

## Deliverables
- `make demo` prints a short summary table
- README documents:
  - dependency install
  - flash backend setup
  - serial auto-detect behavior
  - demo command usage
