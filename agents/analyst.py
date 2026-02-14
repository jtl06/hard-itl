from __future__ import annotations

from pathlib import Path

from .nim_client import NimClient


class AnalystAgent:
    def __init__(self) -> None:
        self.nim = NimClient()

    def analyze(self, run_dir: Path) -> str:
        uart_log = (run_dir / "uart.log").read_text(encoding="utf-8")
        prompt = (
            "Read this UART log and provide a short root-cause summary and next action.\n\n"
            f"UART LOG:\n{uart_log}"
        )
        llm_summary = self.nim.summarize(prompt)
        if llm_summary:
            summary = llm_summary
        else:
            if "framing error" in uart_log and "timeout" in uart_log:
                summary = "Failure likely due to UART config mismatch; framing error and ACK timeout observed."
            elif "TEST_PASS" in uart_log:
                summary = "UART exchange succeeded; handshake and checksum checks passed."
            else:
                summary = "Run outcome unclear; inspect UART log and test harness parameters."

        summary_path = run_dir / "summary.md"
        summary_path.write_text(f"# Analyst Summary\n\n{summary}\n", encoding="utf-8")
        return summary
