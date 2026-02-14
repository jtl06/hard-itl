from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any


def _iso(ts: datetime) -> str:
    return ts.isoformat(timespec="milliseconds")


def capture_uart(
    run_id: str,
    params: dict[str, Any],
    mode: str = "mock",
    serial_port: str = "/dev/ttyACM0",
    baud: int = 115200,
) -> tuple[list[str], bool, str]:
    """Capture UART lines.

    In real mode this function intentionally returns an actionable error stub unless
    platform-specific serial plumbing is added. Hardware touching stays in runner.
    """
    if mode != "mock":
        lines = [
            f"{_iso(datetime.now(timezone.utc))} RUN_START {run_id}",
            f"{_iso(datetime.now(timezone.utc))} ERROR SERIAL_UNAVAILABLE pyserial backend not configured for {serial_port}@{baud}",
            f"{_iso(datetime.now(timezone.utc))} RUN_END {run_id}",
        ]
        return lines, False, "real-mode serial capture backend placeholder"

    return _simulate_mock_uart(run_id, params)


def _simulate_mock_uart(run_id: str, params: dict[str, Any]) -> tuple[list[str], bool, str]:
    # Deterministic synthetic flake model.
    # Stable region: uart_rate <= 230400 and buffer_size >= 64.
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
        errors.append("ERROR BUFFER_UNDERRUN ring buffer overflow")

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
                f"{_iso(t0 + timedelta(milliseconds=28))} INFO throughput_lps 120.0",
                f"{_iso(t0 + timedelta(milliseconds=36))} INFO test_result PASS",
            ]
        )
        passed = True
        note = "mock pass in stable region"

    lines.append(f"{_iso(t0 + timedelta(milliseconds=50))} RUN_END {run_id}")
    return lines, passed, note
