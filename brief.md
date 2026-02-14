# Multi-agent HIL debugger (RP2350 + Saleae LA + DGX Spark NIM)

## Goal
Build a hackathon-ready, multi-agent hardware-in-the-loop (HIL) debugger where:
- DUT is an RP2350 microcontroller connected over USB.
- A Saleae Logic analyzer is the "truth layer" (captures digital + UART decode).
- DGX Spark runs everything locally: orchestrator, agents, runner, and the NIM/Nemotron LLM endpoint.

The system runs closed-loop experiments:
1) Build firmware with parameters
2) Flash DUT
3) Run test, capture UART + LA trace
4) Agents analyze evidence bundle, hypothesize root cause
5) Planner proposes next experiments
6) Repeat until pass

## Environment / Constraints
- Host: DGX Spark running Ubuntu 24.04
- Local LLM: NIM/Nemotron OpenAI-compatible endpoint at:
  - NIM_BASE_URL = http://127.0.0.1:8000/v1
  - Model name via NIM_MODEL env var
- No cloud calls. All LLM calls MUST go to NIM_BASE_URL.
- Runner is the ONLY component allowed to:
  - run `make`
  - flash hardware
  - access /dev/tty* or Saleae automation API
- Everything should be runnable via:
  - `python orchestrator.py --case uart_demo --runs 8`
  - and a convenience `make demo`

## Hardware & Signals
- DUT: RP2350 board via USB (CDC serial output + flashing)
- LA: Saleae Logic device plugged into DGX via USB
- Use GPIO markers from firmware to LA:
  - CH0: TRIG (goes high at RUN_START, low at RUN_END)
  - CH1: ERR  (pulse on error)
- UART stream is emitted by DUT:
  - Prefer: USB CDC (captured as /dev/ttyACM*), and also decoded by Saleae UART analyzer if configured.
  - UART log lines MUST include markers:
    - "RUN_START <run_id>"
    - "ERROR <code> <msg>"
    - "RUN_END <run_id>"

## Flashing Requirements (auto-detect)
Implement a flashing backend that auto-detects which method is available on the host.
Priority order:
1) UF2 mass-storage copy (BOOTSEL drive): if a mounted volume with RPI-RP2 / Pico2 style label exists, copy firmware.uf2.
2) picotool: if `picotool` is installed, use it to load/convert.
3) OpenOCD: optional backend (note upstream OpenOCD may not support RP2350 in older releases; allow using raspberrypi/openocd fork or a newer build). If configured, use it for SWD flash.

The runner must expose:
- flash(image_path, method="auto") -> success/failure + diagnostics
- and must fail fast with actionable error text if no method works.

## Saleae Capture Requirements
Use Saleae Logic 2 Automation API via the `logic2-automation` Python package.
- Assume Logic 2 is running with automation enabled (default port 10430), OR start it with automation flags.
- Capture must trigger on TRIG rising edge.
- Export per run:
  - digital.csv (digital transitions)
  - uart_decoded.csv (decoded UART analyzer export) if analyzer exists
- Store exports inside the run artifact bundle.

If headless is needed, support running Logic 2 under Xvfb (document in README).

## Evidence Bundle (per run)
All outputs for each run must be stored under:
  runs/run_<timestamp>_<shortid>/

Files:
- manifest.json:
  - run_id, case_id, params, git_sha (if available), timestamps, flash_method, serial_port, saleae_config_summary
- firmware/:
  - built ELF + UF2 (if produced)
- uart.log:
  - captured serial with timestamps
- la/:
  - capture file reference (if available)
  - digital.csv
  - uart_decoded.csv (optional)
- analysis.json:
  - pass_fail
  - metrics (error_count, missing_end, throughput lines/s, max_gap_ms, etc.)
  - key_events (parsed ERROR lines with indices/timestamps)
- triage.md:
  - hypotheses + why (must cite evidence files/metrics)
  - next_experiments (concrete param sets)
  - suggested_fix (optional)

## Repo Structure to Create
hil-multi-agent/
  firmware/                  # placeholder (do not invent a full SDK, but provide an example interface)
  runner/
    runner.py                # safe boundary (build/flash/capture)
    flash.py                 # UF2/picotool/openocd backends
    serial_capture.py        # /dev/tty capture with timestamps
    saleae_capture.py        # automation capture + exports
  agents/
    llm_client.py            # calls NIM_BASE_URL using OpenAI-compatible API
    planner.py
    analyst.py
    triage.py
  schemas/
    types.py                 # RunRequest/RunResult/AnalysisResult/TriageResult
  orchestrator.py
  config.yaml                # ports, baud, trigger channel, paths
  README.md
  Makefile

## Agent Behavior (multi-agent)
Implement 3-4 agents (can be simple but must be distinct):
- Planner: proposes next RunRequest(s) given last analysis + triage
- Analyst: parses uart.log (+ optional la/uart_decoded.csv) and computes metrics/features
- Triage: produces hypotheses + a minimal next-experiment list + suggested fix
- Optional Patch agent: proposes code/config changes, but MUST NOT apply them automatically (only suggests)

Agents may call the LLM endpoint, but MUST be robust to LLM failure (fallback rules).

## Minimal Demo Scenario (must work)
Provide a deterministic "synthetic flake" in firmware interface assumptions:
- The case can fail when a parameter is too aggressive (e.g., uart_rate or buffer_size too small).
- Planner should find a stable passing configuration within ~6-8 runs.

Even if firmware isn't fully implemented, create a mock mode in runner that simulates logs so the pipeline can be tested end-to-end.

## Deliverables
- `make demo` runs orchestrator for a handful of runs and prints a short summary table
- README includes:
  - installing python deps
  - enabling Saleae automation
  - flashing method setup (UF2/picotool/openocd) and how runner auto-detects
  - how to wire TRIG/ERR
  - how to run the demo

  ## LLM Orchestration (Nemotron Nano 9B v2 via ONE NIM endpoint)

We will run a single multi-agent orchestrator that calls ONE NVIDIA NIM endpoint (OpenAI-compatible).
Constraints:
- Do NOT start multiple containers.
- All agents MUST call the same endpoint:
  - base_url: http://localhost:8000/v1/chat/completions
- model id: nvidia/nemotron-nano-9b-v2
- Implement exactly 4 agents, each with a distinct system prompt:
  1) planner
  2) coder
  3) critic
  4) summarizer
- Fan-out: planner/coder/critic run concurrently on the same user prompt (asyncio).
- Converge: summarizer merges their outputs into a single final answer.
- Provide:
  (1) a Python file (e.g., `agents/orchestrator_nim.py`) using `aiohttp` + `asyncio`
      - It must incorporate our project context (RP2350 DUT, Saleae LA truth layer, Runner-only hardware access, evidence bundles).
      - It MUST print ONLY the final summarized answer (no intermediate agent outputs).
  (2) a bash concurrency smoke test (e.g., `tools/smoke_concurrency.sh`) using `curl`
      - It should launch 3 concurrent requests (planner/coder/critic style) to verify parallel request handling.
      - It should not start/stop the NIM container; it assumes the endpoint is already running.

Integration points:
- The orchestrator is used by `orchestrator.py` to generate:
  - next experiments (planner)
  - minimal patch/instrumentation suggestions (coder)
  - feasibility/risk review (critic)
  - final merged run plan and demo script guidance (summarizer)
- All agent suggestions must respect: Runner is the ONLY module allowed to touch hardware (make/flash/serial/Saleae).
- Agents should reference evidence bundle outputs (uart.log, la/digital.csv, la/uart_decoded.csv, analysis.json) when making recommendations.

- The code MUST NOT attempt to start NIM or any containers; it only calls the existing local endpoint.
