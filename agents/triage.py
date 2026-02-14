from __future__ import annotations

import json
from pathlib import Path


class TriageAgent:
    def triage(self, run_dir: Path) -> dict:
        uart_log = (run_dir / "uart.log").read_text(encoding="utf-8")
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        baud = manifest["config"]["baud_rate"]

        if "TEST_PASS" in uart_log:
            result = {
                "status": "pass",
                "root_cause": "none",
                "recommended_change": "none",
                "next_baud_rate": baud,
            }
        elif "framing error" in uart_log or "timeout" in uart_log:
            result = {
                "status": "fail",
                "root_cause": "UART baud mismatch (inferred from framing error + timeout)",
                "recommended_change": "Set baud_rate to 115200 and rerun",
                "next_baud_rate": 115200,
            }
        else:
            result = {
                "status": "fail",
                "root_cause": "unknown",
                "recommended_change": "Collect LA capture and retry",
                "next_baud_rate": baud,
            }

        (run_dir / "triage.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result
