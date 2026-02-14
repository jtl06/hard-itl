from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

from schemas.types import AnalysisResult


class AnalystAgent:
    def analyze(self, run_dir: Path) -> AnalysisResult:
        uart_path = run_dir / "uart.log"
        lines = [ln.strip() for ln in uart_path.read_text(encoding="utf-8").splitlines() if ln.strip()]

        key_events = []
        ts_values: list[datetime] = []
        error_count = 0
        has_end = False

        for idx, line in enumerate(lines):
            parts = line.split(" ", 2)
            if len(parts) < 2:
                continue
            timestamp = self._parse_ts(parts[0])
            if timestamp is not None:
                ts_values.append(timestamp)
            event = parts[1]
            msg = parts[2] if len(parts) > 2 else ""

            if event == "ERROR":
                error_count += 1
                code = msg.split(" ", 1)[0] if msg else "UNKNOWN"
                key_events.append({"index": idx, "timestamp": parts[0], "code": code, "message": msg})
            if event == "RUN_END":
                has_end = True

        throughput = self._extract_throughput(lines)
        max_gap_ms = self._max_gap_ms(ts_values)
        pass_fail = "pass" if error_count == 0 and has_end else "fail"

        la_uart_path = run_dir / "la" / "uart_decoded.csv"
        la_rows = self._count_csv_rows(la_uart_path) if la_uart_path.exists() else 0

        metrics = {
            "error_count": error_count,
            "missing_end": not has_end,
            "throughput_lps": throughput,
            "max_gap_ms": max_gap_ms,
            "uart_line_count": len(lines),
            "la_uart_rows": la_rows,
        }

        result = AnalysisResult(pass_fail=pass_fail, metrics=metrics, key_events=key_events)
        (run_dir / "analysis.json").write_text(json.dumps({
            "pass_fail": result.pass_fail,
            "metrics": result.metrics,
            "key_events": result.key_events,
        }, indent=2), encoding="utf-8")
        return result

    @staticmethod
    def _parse_ts(text: str) -> datetime | None:
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            return None

    @staticmethod
    def _extract_throughput(lines: list[str]) -> float:
        for line in lines:
            if "throughput_lps" in line:
                try:
                    return float(line.rsplit(" ", 1)[-1])
                except ValueError:
                    return 0.0
        return 0.0

    @staticmethod
    def _max_gap_ms(ts_values: list[datetime]) -> float:
        if len(ts_values) < 2:
            return 0.0
        max_gap = 0.0
        for i in range(1, len(ts_values)):
            gap = (ts_values[i] - ts_values[i - 1]).total_seconds() * 1000.0
            if gap > max_gap:
                max_gap = gap
        return round(max_gap, 3)

    @staticmethod
    def _count_csv_rows(path: Path) -> int:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        return max(0, len(rows) - 1)
