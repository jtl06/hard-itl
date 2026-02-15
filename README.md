# EdgeCase (Multi-Agent LLM HIL on DGX Spark + NVIDIA NIM)

Local-first multi-agent hardware-in-the-loop debugger.  
Only `runner/` touches hardware (`build`, `flash`, `/dev/tty*`).

## Mission and purpose

EdgeCase demonstrates an LLM-driven hardware debugging loop designed for live demos and iterative bring-up:
- use real UART evidence from the DUT as the single source of truth
- run planner/coder/debugger/coordinator/validator roles against that evidence
- converge quickly on a stable, passing configuration

The goal is to make hardware debugging observable, repeatable, and explainable, not just ad-hoc trial-and-error.

## Architecture block diagram

```text
                         ┌───────────────────────────────────────────┐
                         │            NVIDIA NIM (local)              │
                         │  http://localhost:8000/v1/chat/completions │
                         └───────────────▲───────────────────────────┘
                                         │ LLM calls
                                         │
┌──────────────────────────────┐   ┌─────┴─────────────────────────────┐
│ Dashboard (make gui)          │   │ orchestrator.py (CLI)             │
│ http://127.0.0.1:8765         │   │ - run loop per case               │
│ - Planner/Coder/Debugger/...  │◄──┤ - emits SSE updates               │
│ - Verifier panel + charts     │SSE│ - reads/writes run artifacts      │
└───────────────▲──────────────┘   └─────┬─────────────────────────────┘
                │ user selects case/target│
                │                         │ invokes
                │                         ▼
                │               ┌─────────────────────────┐
                │               │ Agents (fan-out/converge)│
                │               │ Planner / Coder / Debugger│
                │               │ Coordinator / Verifier    │
                │               └───────────┬──────────────┘
                │                           │ propose params
                │                           ▼
                │               ┌─────────────────────────┐
                │               │ runner/ (ONLY hardware)  │
                │               │ - Build (ELF/UF2)         │
                │               │ - Flash (picotool/OpenOCD │
                │               │   /UF2)                   │
                │               │ - UART capture (/dev/tty*)│
                │               │ - Mock mode (synthetic)   │
                │               └───────────┬──────────────┘
                │                           │ produces
                ▼                           ▼
        ┌────────────────────────────────────────────────────┐
        │ Run Evidence Bundle (unchanged contract)            │
        │ runs/run_x/                                         │
        │  manifest.json  firmware.elf  firmware.uf2          │
        │  uart.log  analysis.json  triage.md                 │
        └────────────────────────────────────────────────────┘
```

Real mode path: Runner -> Flash -> RP2350 -> UART -> uart.log  
Mock/demo path: Runner -> synthetic uart.log + outcomes

## Primary use cases

- Interactive demos: show live agent reasoning summaries and UART logs in one dashboard.
- Rapid bring-up: validate that firmware boots, emits expected markers, and ends runs cleanly.
- Regression checks: replay the same case across multiple runs and compare artifacts.
- Safe automation: keep all hardware-touching actions isolated in `runner/`.

## Platform focus: DGX Spark + NIM

Primary deployment target is DGX Spark on `Ubuntu 24.04 (ARM64)`:
- NIM inference runs locally via Docker (`make nim-start`).
- Orchestrator, agents, dashboard, build, flash, and UART capture run on the same host.
- Hardware target (RP2350 in this repo) is connected over USB CDC (`/dev/serial/by-id/*` preferred).

For real runs, set:
- Docker/NGC access for NIM (`NGC_API_KEY`) for local Nemotron inference
- target-specific build toolchain (RP2350 example uses `PICO_SDK_PATH` + `arm-none-eabi-gcc`)

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

For `uart_demo`, allowed model-selectable baud candidates are configurable via:
- `cases.uart_demo.baud_options_csv`

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
- `--trace`: stream short agent reasoning summaries (`[planner]`, `[coder]`, `[critic]`, `[summarizer]`, `[verifier]`)
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
- Agent Load / Time chart + Verifier panel (right side)

Top controls:
- `Case`, `Runs`, `Mode` (`mock`/`real`)
- `Agent Mode` (`sequential` tag-team or `parallel`)
- `NIM Model` (`Nemotron Nano 9B` or `Nemotron 30B`)
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
- flash backend settings (`runner.flash_method`, optional `runner.openocd_cfg` when using OpenOCD)

Default config uses:
- `build_cmd: make -C firmware REQUIRE_PICO_SDK=1 rp2350_{case_id}`
- `real_uf2_path: firmware/build/firmware.uf2`
- `flash_method: picotool`
- `auto_bootsel: true` (runner sends `BOOTSEL` command over USB CDC before flashing)

If `runner.real_uf2_path` is missing, orchestrator exits with configuration error.
If the UF2 appears to be a placeholder artifact, real mode aborts before flashing.

Run real mode:

```bash
make real
```

OpenOCD-only setup:

```bash
sudo apt-get update
sudo apt-get install -y openocd
```

If your board/probe needs a different config, set `runner.openocd_cfg` in `config.yaml`.
You can also provide multiple cfg files separated by `;`:
- `openocd_cfg: interface/cmsis-dap.cfg;target/rp2350.cfg`

Notes:
- Install build dependencies on Ubuntu:
  - `sudo apt-get update`
  - `sudo apt-get install -y build-essential cmake ninja-build gcc-arm-none-eabi`
- Serial setup in code currently uses Linux-style `stty -F ...`.
- In real mode, UART data is actual DUT output; synthetic markers are not injected.
- If firmware never prints `RUN_END`, run fails with `ERROR TIMEOUT missing RUN_END`.
- Firmware targets now support firmware-assisted BOOTSEL:
  - runner sends `BOOTSEL` / `ENTER_BOOTSEL` over serial
  - firmware jumps to ROM bootloader via `reset_usb_boot(...)`

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

## Multi-agent NIM orchestration

Environment defaults used by agents:
- `NIM_CHAT_URL=http://localhost:8000/v1/chat/completions`
- `NIM_MODEL=nvidia/nemotron-nano-9b-v2`
- `NIM_EXECUTION_MODE=sequential` (`sequential` or `parallel`)

Agent roles in this repo:
- `planner`: chooses next experiment sequence
- `coder`: proposes minimal instrumentation/fix changes
- `critic` (UI label: Debugger): validates feasibility and risk
- `verifier` (UI label: Validator): scores evidence quality and confidence
- `summarizer` (UI label: Coordinator): merges final runbook output

Config option:
- `nim.execution_mode` in `config.yaml` / `config.real.example.yaml`
- `nim.coordinator_rework_rounds` (sequential mode only; coordinator can send coder back for refinement)
- `nim.peer_message_rounds` (agent-to-agent follow-up rounds before coordinator merge)
- per-run override via CLI `--nim-mode` or dashboard `Agent Mode` selector

NIM-first behavior:
- when NIM is enabled, the initial guess experiment is model-selected before run 1
- if model output is invalid/unavailable, planner fallback is used

Peer message format (inside agent outputs):
- `@coder: tighten instrumentation for missing RUN_END`
- `CALL critic: validate risk of this patch`

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
