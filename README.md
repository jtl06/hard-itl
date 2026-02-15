# Multi-agent HIL debugger (RP2350 + USB CDC UART + local NIM)

Local-only multi-agent HIL pipeline. Only `runner/` touches hardware (`build`, `flash`, `/dev/tty*`).

## Quick start

```bash
make venv
make mock
```

Default demo command:

```bash
python3 orchestrator.py --case uart_demo --runs 8
```

## Make targets

- `make mock` / `make demo`: mock run (`uart_demo`, 8 runs)
- `make real`: real hardware run (`demo-real`)
- `make demo-live`: mock run with live run diagnostics
- `make demo-real`: real run with live run diagnostics
- `make gui`: start dashboard on `http://127.0.0.1:8765`
- `make nim-start`: start local Nemotron Nano 9B NIM container
- `make nim-stop`: stop/remove local NIM container
- `make nim-smoke`: basic concurrent curl smoke test against NIM

## Truth layer and run artifacts

Logic analyzer support is removed. USB CDC UART is the only truth layer.

Per-run bundle (`runs/run_*`):
- `manifest.json`
- `firmware/firmware.elf`
- `firmware/firmware.uf2`
- `uart.log`
- `analysis.json`
- `triage.md`

## Runner contract

Runner responsibilities:
- flash backend auto-detect (`UF2 -> picotool -> OpenOCD`)
- serial auto-detect (prefer `/dev/serial/by-id/*`, fallback `/dev/ttyACM*`, `/dev/ttyUSB*`, `/dev/cu.usbmodem*`)
- serial re-enumeration handling after flash
- timestamp each UART line
- capture until `RUN_END <run_id>` (or any `RUN_END ...`) or timeout

## Cases

- `uart_demo`: baud guess hunt (`guess_baud` vs `target_baud`)
- `framing_hunt`: frame guess hunt (`guess_frame` vs `target_frame`)
- `parity_hunt`: parity guess hunt (`guess_parity` vs `target_parity`)
- `signature_check`: signature semantic check (`guess_magic` vs `target_magic`)

You can override targets from CLI:

```bash
python3 orchestrator.py --case uart_demo --runs 8 --target-baud 76200
python3 orchestrator.py --case framing_hunt --runs 8 --target-frame 8E1
python3 orchestrator.py --case parity_hunt --runs 8 --target-parity odd
python3 orchestrator.py --case signature_check --runs 8 --target-magic 0xC0FFEE42
```

## Analysis metrics

`analysis.json` includes:
- `error_count`
- `missing_start`
- `missing_end`
- `lines_per_sec`
- `max_gap_ms`
- `last_error_code`
- `uart_line_count`
- `signature_valid`

## Live CLI flags

- `--live`: per-run diagnostics + UART tail
- `--live-uart`: stream UART lines as captured (`[uart] ...`)
- `--trace`: stream short agent reasoning summaries (`[planner]`, `[coder]`, `[critic]`, `[summarizer]`)
- `--verbose`: enables all live CLI output
- `--show-agent-fragments`: print short role output fragments in live mode
- `--state-file <path>`: write live state JSON for dashboard

Example:

```bash
python3 orchestrator.py --case uart_demo --runs 8 --mode mock --live-uart --trace --verbose
```

## Dashboard

Run:

```bash
make gui
```

Open `http://127.0.0.1:8765`.

UI sections:
- Planner, Coder, Debugger, Coordinator panels
- Overall Output
- Latest UART
- Run Tracker
- Agent Load / Time chart (right side)

Top controls:
- `Case`, `Runs`, `Mode` (`mock`/`real`)
- one case-specific target input shown at a time:
  - baud, frame, parity, or magic

API:
- `GET /api/stream` (SSE live state/process stream)
- `GET /api/state`
- `GET /api/process`
- `POST /api/run` (also accepts `/api/start`)

## Real hardware mode

Real mode requires valid firmware build outputs configured in `config.yaml`:
- `runner.build_cmd`
- `runner.real_uf2_path`
- optional `runner.real_elf_path`

Default config uses:
- `build_cmd: make -C firmware REQUIRE_PICO_SDK=1 rp2350_{case_id}`
- `real_uf2_path: firmware/build/firmware.uf2`

If `runner.real_uf2_path` is missing, orchestrator exits with configuration error.
If the UF2 appears to be a placeholder artifact, real mode aborts before flashing.

Run real mode:

```bash
make real
```

Notes:
- Serial setup in code currently uses Linux-style `stty -F ...`.
- In real mode, UART data is actual DUT output; synthetic markers are not injected.
- If firmware never prints `RUN_END`, run fails with `ERROR TIMEOUT missing RUN_END`.

## Firmware targets

`firmware/` contains one target per demo case:

```bash
make -C firmware rp2350_uart_demo
make -C firmware rp2350_framing_hunt
make -C firmware rp2350_parity_hunt
make -C firmware rp2350_signature_check
```

- With `PICO_SDK_PATH` set: builds real RP2350 artifacts.
- Without `PICO_SDK_PATH`: generates placeholder artifacts so software pipeline can still run.
- For `signature_check`, runner passes `TARGET_MAGIC_HEX` from selected target magic in real mode.

## NIM orchestration

Environment defaults used by agents:
- `NIM_CHAT_URL=http://localhost:8000/v1/chat/completions`
- `NIM_MODEL=nvidia/nemotron-nano-9b-v2`

Start local NIM (Docker + NVIDIA GPU):

```bash
export NGC_API_KEY=nvapi-...
make nim-start
```

Stop:

```bash
make nim-stop
```

NIM start script supports:
- `NIM_IMAGE`
- `NIM_CONTAINER_NAME`
- `NIM_PORT`
- `NIM_CACHE_DIR`
- `NIM_DETACH=1`
- `NIM_PLATFORM`

Default image used by `make nim-start`:
- `nvcr.io/nim/nvidia/nvidia-nemotron-nano-9b-v2-dgx-spark:1.0.0-variant`

DGX Spark (`Ubuntu 24.04`, `ARM64`) notes:
- script auto-detects ARM64 and defaults `NIM_PLATFORM=linux/arm64`
- for headless, use detached mode:
  - `NIM_DETACH=1 make nim-start`
- if using a different image tag:
  - `NIM_IMAGE=<your_image> NIM_PLATFORM=linux/arm64 make nim-start`

Standalone role-orchestrator example:

```bash
PYTHONPATH=. .venv/bin/python -m agents.orchestrator_nim --prompt "Suggest next UART experiments"
```

Concurrency smoke test (expects NIM already running):

```bash
tools/smoke_concurrency.sh
```
