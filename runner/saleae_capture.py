from __future__ import annotations

from pathlib import Path
from typing import Any


def capture_saleae(run_dir: Path, mode: str, trigger_channel: int, uart_lines: list[str]) -> dict[str, Any]:
    la_dir = run_dir / "la"
    la_dir.mkdir(parents=True, exist_ok=True)

    if mode == "mock":
        digital_csv = la_dir / "digital.csv"
        uart_csv = la_dir / "uart_decoded.csv"

        digital_csv.write_text(
            "time_s,channel,state\n"
            "0.000000,0,1\n"
            "0.000050,1,1\n"
            "0.000080,1,0\n"
            "0.000200,0,0\n",
            encoding="utf-8",
        )

        rows = ["time_s,analyzer,data"]
        t = 0.0
        for line in uart_lines:
            if "INFO" in line or "ERROR" in line:
                rows.append(f"{t:.6f},uart,{line.split(' ', 2)[-1]}")
                t += 0.00004
        uart_csv.write_text("\n".join(rows) + "\n", encoding="utf-8")

        return {
            "status": "mock",
            "trigger_channel": trigger_channel,
            "digital_csv": str(digital_csv),
            "uart_decoded_csv": str(uart_csv),
        }

    return {
        "status": "not_captured",
        "trigger_channel": trigger_channel,
        "reason": "Logic2 automation not configured in this baseline. Use mock mode or extend runner/saleae_capture.py.",
    }
