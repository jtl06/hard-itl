from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class RunConfig:
    run_id: str
    baud_rate: int
    ssh_host: str = ""
    ssh_user: str = "pi"
    remote_cmd: str = "python3 /opt/hil/run_uart_test.py"
    mode: str = "mock"


class Runner:
    """Only module allowed to touch hardware (SSH / UART capture path)."""

    def __init__(self, runs_dir: str = "runs") -> None:
        self.runs_dir = Path(runs_dir)
        self.runs_dir.mkdir(parents=True, exist_ok=True)

    def execute(self, cfg: RunConfig) -> Path:
        run_dir = self.runs_dir / cfg.run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        uart_log = self._capture_uart(cfg)
        uart_path = run_dir / "uart.log"
        uart_path.write_text(uart_log, encoding="utf-8")

        status = "pass" if "TEST_PASS" in uart_log else "fail"
        manifest = {
            "run_id": cfg.run_id,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "artifacts": ["manifest.json", "uart.log", "summary.md", "triage.json"],
            "config": asdict(cfg),
        }
        (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return run_dir

    def _capture_uart(self, cfg: RunConfig) -> str:
        if cfg.mode == "mock":
            return self._mock_uart(cfg.baud_rate)
        if not cfg.ssh_host:
            raise ValueError("ssh_host is required for real mode")

        ssh_target = f"{cfg.ssh_user}@{cfg.ssh_host}"
        cmd = ["ssh", ssh_target, cfg.remote_cmd]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            return (
                "[runner] SSH command failed\n"
                f"return_code={proc.returncode}\n"
                f"stderr={proc.stderr.strip()}\n"
                "TEST_FAIL\n"
            )
        return proc.stdout

    @staticmethod
    def _mock_uart(baud_rate: int) -> str:
        expected = 115200
        lines = [
            "[boot] DUT initialized",
            f"[cfg] baud_rate={baud_rate}",
            "[test] sending handshake",
        ]
        if baud_rate == expected:
            lines += ["[uart] RX OK: HELLO_ACK", "[assert] checksum=OK", "TEST_PASS"]
        else:
            lines += ["[uart] RX ERR: framing error", "[assert] timeout waiting for ACK", "TEST_FAIL"]
        return "\n".join(lines) + "\n"
