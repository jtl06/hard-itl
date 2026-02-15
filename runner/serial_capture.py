from __future__ import annotations

import glob
import os
import select
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable


def _iso(ts: datetime) -> str:
    return ts.isoformat(timespec="milliseconds")


def list_serial_candidates(prefer_by_id: bool = True) -> list[str]:
    by_id = sorted(glob.glob("/dev/serial/by-id/*"))
    acm = sorted(glob.glob("/dev/ttyACM*"))
    usb = sorted(glob.glob("/dev/ttyUSB*"))
    other = sorted(glob.glob("/dev/cu.usbmodem*"))

    ordered = []
    if prefer_by_id:
        ordered.extend(by_id)
        ordered.extend(acm)
        ordered.extend(usb)
        ordered.extend(other)
    else:
        ordered.extend(acm)
        ordered.extend(usb)
        ordered.extend(by_id)
        ordered.extend(other)

    seen = set()
    unique = []
    for p in ordered:
        if p not in seen:
            unique.append(p)
            seen.add(p)
    return unique


def autodetect_serial_port(prefer_by_id: bool = True) -> str | None:
    candidates = list_serial_candidates(prefer_by_id=prefer_by_id)
    return candidates[0] if candidates else None


def wait_for_serial_port(
    previous_port: str | None,
    timeout_s: float = 8.0,
    prefer_by_id: bool = True,
) -> str | None:
    deadline = time.monotonic() + timeout_s
    prev = Path(previous_port).resolve().as_posix() if previous_port else None

    while time.monotonic() < deadline:
        candidates = list_serial_candidates(prefer_by_id=prefer_by_id)
        if not candidates:
            time.sleep(0.25)
            continue

        if prev is None:
            return candidates[0]

        for c in candidates:
            try:
                cur = Path(c).resolve().as_posix()
            except Exception:
                cur = c
            if cur != prev:
                return c

        # No new node, but old port may have returned; accept it near timeout.
        if time.monotonic() > deadline - 0.5:
            return candidates[0]
        time.sleep(0.25)

    return None


def capture_uart(
    run_id: str,
    params: dict[str, Any],
    mode: str = "mock",
    serial_port: str = "",
    baud: int = 115200,
    timeout_s: float = 8.0,
    prefer_by_id: bool = True,
    line_callback: Callable[[str], None] | None = None,
    emulate_timing: bool = False,
) -> tuple[list[str], bool, str, str]:
    if mode == "mock":
        lines, passed, note = _simulate_mock_uart(
            run_id,
            params,
            line_callback=line_callback,
            emulate_timing=emulate_timing,
        )
        return lines, passed, note, "mock"

    port = serial_port or autodetect_serial_port(prefer_by_id=prefer_by_id)
    if not port:
        lines = [
            f"{_iso(datetime.now(timezone.utc))} RUN_START {run_id}",
            f"{_iso(datetime.now(timezone.utc))} ERROR SERIAL_AUTODETECT_FAILED no /dev/serial/by-id or /dev/ttyACM* found",
            f"{_iso(datetime.now(timezone.utc))} RUN_END {run_id}",
        ]
        return lines, False, "serial auto-detect failed", ""

    stty = _configure_serial_port(port=port, baud=baud)
    if stty.returncode != 0:
        lines = [
            f"{_iso(datetime.now(timezone.utc))} ERROR SERIAL_CONFIG_FAILED {stty.stderr.strip() or stty.stdout.strip()}",
        ]
        return lines, False, "serial port configuration failed", port

    lines, found_end = _read_until_end_marker(
        port=port,
        run_id=run_id,
        timeout_s=timeout_s,
        line_callback=line_callback,
    )
    passed = not any(" ERROR " in f" {ln} " for ln in lines) and found_end
    note = "real UART capture complete" if found_end else "timeout before RUN_END"
    return lines, passed, note, port


def _read_until_end_marker(
    port: str,
    run_id: str,
    timeout_s: float,
    line_callback: Callable[[str], None] | None = None,
) -> tuple[list[str], bool]:
    deadline = time.monotonic() + timeout_s
    fd = os.open(port, os.O_RDONLY | os.O_NONBLOCK)
    buf = b""
    out: list[str] = []
    found_end = False

    try:
        while time.monotonic() < deadline:
            remaining = max(0.0, deadline - time.monotonic())
            ready, _, _ = select.select([fd], [], [], min(0.25, remaining))
            if not ready:
                continue

            try:
                chunk = os.read(fd, 4096)
            except BlockingIOError:
                continue

            if not chunk:
                continue
            buf += chunk

            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                clean = raw.decode("utf-8", errors="replace").strip("\r")
                if not clean:
                    continue
                stamped = f"{_iso(datetime.now(timezone.utc))} {clean}"
                out.append(stamped)
                if line_callback is not None:
                    line_callback(stamped)
                if f"RUN_END {run_id}" in clean or clean.startswith("RUN_END "):
                    found_end = True
                    break
            if found_end:
                break

        if not found_end:
            timeout_line = f"{_iso(datetime.now(timezone.utc))} ERROR TIMEOUT missing RUN_END"
            out.append(timeout_line)
            if line_callback is not None:
                line_callback(timeout_line)
    finally:
        os.close(fd)

    return out, found_end


def _configure_serial_port(port: str, baud: int) -> subprocess.CompletedProcess[str]:
    """Configure serial settings for Linux hosts."""
    return subprocess.run(
        ["stty", "-F", port, str(baud), "raw", "-echo", "-icanon", "min", "0", "time", "1"],
        capture_output=True,
        text=True,
        check=False,
    )


def _simulate_mock_uart(
    run_id: str,
    params: dict[str, Any],
    line_callback: Callable[[str], None] | None = None,
    emulate_timing: bool = False,
) -> tuple[list[str], bool, str]:
    uart_rate = int(params.get("uart_rate", 1000000))
    buffer_size = int(params.get("buffer_size", 16))

    t0 = datetime.now(timezone.utc)
    lines: list[str] = [
        f"{_iso(t0)} RUN_START {run_id}",
        f"{_iso(t0 + timedelta(milliseconds=5))} INFO cfg uart_rate={uart_rate} buffer_size={buffer_size}",
        f"{_iso(t0 + timedelta(milliseconds=12))} INFO handshake tx=HELLO",
    ]

    errors: list[str] = []
    if uart_rate > 230400:
        errors.append("ERROR RATE_TOO_HIGH framing/rx drop")
    if buffer_size < 64:
        errors.append("ERROR BUFFER_UNDERRUN ring overflow")

    if errors:
        for idx, err in enumerate(errors, start=1):
            lines.append(f"{_iso(t0 + timedelta(milliseconds=20 + idx * 8))} {err}")
        lines.append(f"{_iso(t0 + timedelta(milliseconds=45))} INFO test_result FAIL")
        passed = False
        note = "mock failure generated from unstable params"
    else:
        lines.extend(
            [
                f"{_iso(t0 + timedelta(milliseconds=20))} INFO rx HELLO_ACK",
                f"{_iso(t0 + timedelta(milliseconds=30))} INFO test_result PASS",
            ]
        )
        passed = True
        note = "mock pass in stable region"

    lines.append(f"{_iso(t0 + timedelta(milliseconds=52))} RUN_END {run_id}")

    if line_callback is not None:
        prev_ts: datetime | None = None
        for line in lines:
            if emulate_timing:
                ts = _parse_prefix_timestamp(line)
                if ts is not None and prev_ts is not None:
                    dt = (ts - prev_ts).total_seconds()
                    if dt > 0:
                        time.sleep(min(dt, 0.2))
                prev_ts = ts if ts is not None else prev_ts
            line_callback(line)

    return lines, passed, note


def _parse_prefix_timestamp(line: str) -> datetime | None:
    first = line.split(" ", 1)[0]
    try:
        return datetime.fromisoformat(first)
    except ValueError:
        return None
