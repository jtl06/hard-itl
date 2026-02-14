# Multi-agent HIL debugger (RP2350 + Saleae + local NIM)

This repository implements a local-only multi-agent HIL pipeline with a strict boundary: only `runner/` touches hardware-facing operations.

## What works now

- End-to-end orchestrator:
  - `python orchestrator.py --case uart_demo --runs 8`
- Convenience target:
  - `make demo`
- Deterministic mock mode (default) so pipeline works without hardware.
- Per-run artifact bundles under `runs/run_<timestamp>_<shortid>/`.

## Assumptions / defaults

- Default mode is `mock`.
- Local LLM endpoint is OpenAI-compatible NIM:
  - `NIM_BASE_URL=http://127.0.0.1:8000/v1`
  - `NIM_MODEL=meta/llama-3.1-8b-instruct`
- If LLM is unavailable, agents use deterministic fallback logic.
- Synthetic failure model:
  - fail when `uart_rate > 230400` or `buffer_size < 64`
  - pass when `uart_rate <= 230400` and `buffer_size >= 64`

## Repo structure

- `orchestrator.py`: coordinates planner -> runner -> analyst -> triage loop.
- `runner/`: only hardware-touching module.
  - `runner.py`: run lifecycle, manifest, firmware placeholders.
  - `flash.py`: UF2/picotool/openocd backends with `method="auto"`.
  - `serial_capture.py`: UART capture + mock UART simulation.
  - `saleae_capture.py`: Saleae export handling (mock export included).
- `agents/`:
  - `planner.py`, `analyst.py`, `triage.py`, `llm_client.py`.
- `schemas/types.py`: data models for requests/results.
- `config.yaml`: runner, Saleae, case defaults.

## Install / run

```bash
make venv
make demo
```

Equivalent direct run:

```bash
PYTHONPATH=. .venv/bin/python orchestrator.py --case uart_demo --runs 8
```

## Output artifacts per run

Each run directory contains:

- `manifest.json` (run_id, case_id, params, git_sha, flash method, serial, Saleae summary)
- `firmware/firmware.elf`, `firmware/firmware.uf2`
- `uart.log` (timestamped lines with `RUN_START`, `ERROR`, `RUN_END`)
- `la/digital.csv`, `la/uart_decoded.csv` (mock or real capture output)
- `analysis.json` (pass_fail, metrics, key_events)
- `triage.md` (hypotheses, evidence references, next experiments, suggested fix)

## Flash backend setup (real mode)

Runner auto-detect order:
1. UF2 mass-storage mount (`RPI-RP2`/`PICO2` style volume)
2. `picotool` if installed
3. `openocd` if installed (`OPENOCD_CFG` required)

If none are available, runner fails fast with actionable diagnostics.

## Saleae automation notes

- This baseline includes mock Saleae exports by default.
- For real capture, extend `runner/saleae_capture.py` with `logic2-automation` integration and ensure Logic 2 automation is enabled (default port `10430`).
- If running headless, use Xvfb when launching Logic 2.

## Wiring notes (for real hardware)

- CH0: `TRIG` high at `RUN_START`, low at `RUN_END`.
- CH1: `ERR` pulse on error.
- UART output should emit:
  - `RUN_START <run_id>`
  - `ERROR <code> <msg>`
  - `RUN_END <run_id>`
