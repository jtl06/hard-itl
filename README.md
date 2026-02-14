# Multi-Agent HIL Debugger (Pi UART)

Implements a local, no-cloud multi-agent flow for UART HIL debugging using run artifact bundles.

## What this delivers

- `runner/`: executes tests (mock or real over SSH) and captures UART logs.
- `agents/`: `planner`, `analyst`, `triage` consume each run bundle.
- `runs/run_x/`: evidence bundles with `manifest.json`, `uart.log`, `summary.md`, `triage.json`.
- `make demo`: deterministic flow `fail -> diagnose -> tweak param -> pass`.

## Constraints mapping

- Runner is the only hardware-touching module: SSH and UART capture exist only in `runner/runner.py`.
- No cloud dependencies: LLM calls target local NIM endpoint (`NIM_BASE_URL`), with deterministic local fallback when unavailable.
- Everything runnable from one command: `make demo`.

## Quick start (venv)

```bash
make demo
```

This creates `.venv`, installs deps, runs demo, and writes artifacts under `runs/`.

## Optional: use real Pi SSH run

```bash
.venv/bin/python -m runner.cli \
  --run-id run_003 \
  --baud-rate 115200 \
  --mode real \
  --ssh-host <PI_HOST> \
  --ssh-user pi \
  --remote-cmd "python3 /opt/hil/run_uart_test.py"
```

## Local NIM endpoint config

Defaults:
- `NIM_BASE_URL=http://localhost:8000/v1`
- `NIM_MODEL=meta/llama-3.1-8b-instruct`

If your DGX host differs:

```bash
export DGX_HOST=<DGX_HOST>
export NIM_BASE_URL=http://$DGX_HOST:8000/v1
```

## Evidence bundle format

Each `runs/run_x/` directory contains:
- `manifest.json`
- `uart.log`
- `summary.md`
- `triage.json`

Stretch support scaffold:
- `la_uart.csv` can be dropped into run folders later for LA ingestion enhancements.
