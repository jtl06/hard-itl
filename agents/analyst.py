from __future__ import annotations

import json
import re
import zlib
from datetime import datetime
from pathlib import Path

from schemas.types import AnalysisResult


class AnalystAgent:
    def analyze(self, run_dir: Path) -> AnalysisResult:
        uart_path = run_dir / "uart.log"
        lines = [ln.strip() for ln in uart_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        params = manifest.get("params", {})

        key_events: list[dict[str, str | int]] = []
        ts_values: list[datetime] = []
        error_count = 0
        has_start = False
        has_end = False
        last_error_code = ""
        baud_direction = "unknown"

        for idx, line in enumerate(lines):
            parts = line.split(" ", 2)
            if len(parts) < 2:
                continue

            timestamp = self._parse_ts(parts[0])
            if timestamp is not None:
                ts_values.append(timestamp)

            event = parts[1]
            msg = parts[2] if len(parts) > 2 else ""

            if event == "RUN_START":
                has_start = True
            if event == "RUN_END":
                has_end = True
            if event == "ERROR":
                error_count += 1
                code = msg.split(" ", 1)[0] if msg else "UNKNOWN"
                last_error_code = code
                key_events.append({"index": idx, "timestamp": parts[0], "code": code, "message": msg})
            if event == "INFO" and (msg.startswith("BAUD_GUIDE ") or msg.startswith("BAUD_HINT ")):
                hint = msg.split(" ", 1)[1].strip().lower()
                if hint in {"higher", "lower", "unknown"}:
                    baud_direction = hint

        max_gap_ms = self._max_gap_ms(ts_values)
        lines_per_sec = self._lines_per_sec(lines_count=len(lines), ts_values=ts_values)
        signature_valid = self._validate_signature(lines, params)
        signature_required = "target_magic" in params
        pass_fail = "pass" if has_start and has_end and error_count == 0 else "fail"
        if signature_required and not signature_valid:
            pass_fail = "fail"

        metrics = {
            "error_count": error_count,
            "missing_start": not has_start,
            "missing_end": not has_end,
            "lines_per_sec": lines_per_sec,
            "max_gap_ms": max_gap_ms,
            "last_error_code": last_error_code,
            "uart_line_count": len(lines),
            "signature_valid": signature_valid,
            "baud_direction": baud_direction,
        }

        result = AnalysisResult(pass_fail=pass_fail, metrics=metrics, key_events=key_events)
        (run_dir / "analysis.json").write_text(
            json.dumps(
                {
                    "pass_fail": result.pass_fail,
                    "metrics": result.metrics,
                    "key_events": result.key_events,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return result

    @staticmethod
    def _parse_ts(text: str) -> datetime | None:
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            return None

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
    def _lines_per_sec(lines_count: int, ts_values: list[datetime]) -> float:
        if len(ts_values) < 2:
            return float(lines_count)
        dur_s = (ts_values[-1] - ts_values[0]).total_seconds()
        if dur_s <= 0:
            return float(lines_count)
        return round(lines_count / dur_s, 3)

    @staticmethod
    def _validate_signature(lines: list[str], params: dict) -> bool:
        if "target_magic" not in params:
            return True

        payload = None
        magic = None
        crc = None
        for line in lines:
            if "payload=" in line:
                payload = line.split("payload=", 1)[-1].strip()
            m_magic = re.search(r"MAGIC=0x([0-9A-Fa-f]{8})", line)
            if m_magic:
                magic = int(m_magic.group(1), 16)
            m_crc = re.search(r"CRC=0x([0-9A-Fa-f]{8})", line)
            if m_crc:
                crc = int(m_crc.group(1), 16)

        if payload is None or magic is None or crc is None:
            return False

        target_magic = int(params.get("target_magic", 0))
        expected_crc = zlib.crc32(f"{payload}|0x{target_magic:08X}".encode()) & 0xFFFFFFFF
        return magic == target_magic and crc == expected_crc
