# Multi-agent HIL debugger (RP2350 + USB CDC UART + local NIM)

Local-only multi-agent HIL pipeline with a strict boundary: only `runner/` may touch hardware (`make`, flashing, serial access).

## Entry points

- `make demo`
- `python3 orchestrator.py --case uart_demo --runs 8`

## Truth layer and artifacts

Logic analyzer support was removed. USB CDC UART is the sole truth layer.

Each run bundle is:
- `manifest.json`
- `firmware/firmware.elf`
- `firmware/firmware.uf2`
- `uart.log`
- `analysis.json`
- `triage.md`

## Runner contract

Runner is responsible for:
- flash backend auto-detect (`UF2 -> picotool -> OpenOCD`)
- serial port auto-detect (prefer `/dev/serial/by-id/*`, fallback `/dev/ttyACM*`, `/dev/ttyUSB*`)
- re-enumeration wait after flash
- timestamping captured UART lines
- capture until `RUN_END <run_id>` or timeout

## Metrics in analysis

`analysis.json` includes UART-derived metrics:
- `error_count`
- `missing_start`
- `missing_end`
- `lines_per_sec`
- `max_gap_ms`
- `last_error_code`

## Demo behavior

Deterministic synthetic flake:
- fail when `uart_rate > 230400` or `buffer_size < 64`
- pass when `uart_rate <= 230400` and `buffer_size >= 64`

Planner/agents converge to a passing config in ~6-8 runs.

## NIM orchestration (single endpoint)

- `NIM_CHAT_URL=http://localhost:8000/v1/chat/completions`
- `NIM_MODEL=nvidia/nemotron-nano-9b-v2`

`agents/orchestrator_nim.py` implements exactly 4 async agents:
1. planner
2. coder
3. critic
4. summarizer

Standalone example:

```bash
PYTHONPATH=. .venv/bin/python -m agents.orchestrator_nim --prompt "Suggest next UART experiments"
```

## Concurrency smoke test

Assumes NIM endpoint is already running:

```bash
tools/smoke_concurrency.sh
```

## Setup and run

```bash
make venv
make demo
```

Real mode example:

```bash
PYTHONPATH=. .venv/bin/python orchestrator.py --case uart_demo --runs 8 --mode real
```
