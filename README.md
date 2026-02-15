# Multi-agent HIL debugger (RP2350 + USB CDC UART + local NIM)

Local-only multi-agent HIL pipeline with a strict boundary: only `runner/` may touch hardware (`make`, flashing, serial access).

## Entry points

- `make mock`
- `make real`
- `make demo-live`
- `make gui`
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

Deterministic synthetic flake (baud-hunt mode in `uart_demo`):
- user selects `target_baud`
- agents start from an initial `guess_baud`
- fail until guessed baud matches target
- pass when `guess_baud == target_baud`

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
make mock
```

Live operator view (continuous diagnostics + UART tail + agent fragments):

```bash
make demo-live
```

Equivalent direct command:

```bash
python3 orchestrator.py --case uart_demo --runs 8 --mode mock --live --show-agent-fragments
```

## GUI dashboard

Launch:

```bash
make gui
```

Then open `http://127.0.0.1:8765`.

Dashboard includes:
- 4 agent panels (`planner`, `coder`, `critic`, `summarizer`) with live status + output fragment
- overall status tracker (state, progress, run message)
- overall merged output (summarizer result)
- latest UART tail from current run

Use the Start Run controls in the UI to begin `mock` or `real` runs.
If start fails, the UI now shows process/log tail from `dashboard/orchestrator.log`.

Streaming API:
- `GET /api/stream` (Server-Sent Events)
- `POST /api/run` to start a run (same payload as previous start endpoint)

## Live CLI flags

- `--live-uart`: print UART lines as they are captured, prefixed with `[uart]`
- `--trace`: print live agent reasoning summaries, prefixed with `[planner]`, `[critic]`, `[summarizer]`
- `--verbose`: enables comprehensive live console output

Example:

```bash
python3 orchestrator.py --case uart_demo --runs 8 --mode mock --live-uart --trace --verbose
```

Real mode example:

```bash
PYTHONPATH=. .venv/bin/python orchestrator.py --case uart_demo --runs 8 --mode real --target-baud 76200
```

## Real hardware setup

1. Set `runner.build_cmd`, `runner.real_uf2_path` (and optionally `runner.real_elf_path`) in `config.yaml`.
   - Start from `config.real.example.yaml`.
   - Default build target is `make -C firmware rp2350_uart_demo`.
2. Ensure RP2350 is connected and accessible via `/dev/serial/by-id/*` or `/dev/ttyACM*`.
3. Ensure one flash backend is available:
   - UF2 mount, or
   - `picotool`, or
   - `openocd` with `OPENOCD_CFG`.

Then run:

```bash
make demo-real
```

Notes:
- Real mode now uses Linux/macOS compatible serial config (`stty -F`/`-f`).
- UART capture in real mode reads actual DUT output only; no synthetic `RUN_START/RUN_END` lines are injected.
- Capture stops when `RUN_END <run_id>` (or any `RUN_END ...`) is observed, otherwise on timeout.

## GUI baud-hunt flow

In dashboard (`make gui`), set:
- `Case = uart_demo`
- `Target Baud = <your value, e.g. 76200>`

Then click `Start Run`. The run tracker will show `guess` vs `target` progression.

Additional interactive cases:
- `framing_hunt` (target frame: `8N1`, `7E1`, `8E1`)
- `parity_hunt` (target parity: `none`, `even`, `odd`)
- `signature_check` (target magic hex, semantic `MAGIC/CRC` validation)
