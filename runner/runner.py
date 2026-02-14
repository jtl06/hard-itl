from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from runner.flash import Flasher, FlashError
from runner.serial_capture import capture_uart
from runner.saleae_capture import capture_saleae


@dataclass
class RunnerConfig:
    runs_root: str = "runs"
    flash_method: str = "auto"
    serial_port: str = "/dev/ttyACM0"
    serial_baud: int = 115200
    trigger_channel: int = 0


class Runner:
    """Hardware boundary: all build/flash/serial/LA interactions are centralized here."""

    def __init__(self, config: RunnerConfig | None = None) -> None:
        self.config = config or RunnerConfig()
        self.runs_root = Path(self.config.runs_root)
        self.runs_root.mkdir(parents=True, exist_ok=True)

    def flash(self, image_path: Path, method: str = "auto", mode: str = "mock") -> tuple[bool, str, list[str]]:
        flasher = Flasher(mock_mode=(mode == "mock"))
        return flasher.flash(image_path=image_path, method=method)

    def execute(self, case_id: str, run_index: int, params: dict[str, Any], mode: str = "mock") -> dict[str, Any]:
        run_id = self._new_run_id()
        run_dir = self.runs_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        fw_dir = run_dir / "firmware"
        fw_dir.mkdir(parents=True, exist_ok=True)
        elf_path, uf2_path = self._build_firmware_artifacts(fw_dir, case_id=case_id, params=params)

        diagnostics: list[str] = []
        try:
            flash_ok, flash_method, flash_diag = self.flash(uf2_path, method=self.config.flash_method, mode=mode)
            diagnostics.extend(flash_diag)
        except FlashError as exc:
            flash_ok = False
            flash_method = "none"
            diagnostics.append(str(exc))

        uart_lines, uart_pass, capture_note = capture_uart(
            run_id=run_id,
            params=params,
            mode=mode,
            serial_port=self.config.serial_port,
            baud=self.config.serial_baud,
        )
        diagnostics.append(capture_note)

        uart_path = run_dir / "uart.log"
        uart_path.write_text("\n".join(uart_lines) + "\n", encoding="utf-8")

        saleae_summary = capture_saleae(
            run_dir=run_dir,
            mode=mode,
            trigger_channel=self.config.trigger_channel,
            uart_lines=uart_lines,
        )

        status = "pass" if flash_ok and uart_pass else "fail"
        manifest = {
            "run_id": run_id,
            "case_id": case_id,
            "run_index": run_index,
            "params": params,
            "git_sha": self._git_sha(),
            "timestamps": {"created_utc": datetime.now(timezone.utc).isoformat()},
            "flash_method": flash_method,
            "serial_port": self.config.serial_port,
            "saleae_config_summary": saleae_summary,
            "status": status,
            "artifacts": {
                "firmware_elf": str(elf_path),
                "firmware_uf2": str(uf2_path),
                "uart_log": str(uart_path),
                "la_dir": str(run_dir / "la"),
                "analysis": str(run_dir / "analysis.json"),
                "triage": str(run_dir / "triage.md"),
            },
        }
        (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        return {
            "run_id": run_id,
            "run_dir": str(run_dir),
            "status": status,
            "params": params,
            "flash_method": flash_method,
            "diagnostics": diagnostics,
        }

    def _build_firmware_artifacts(self, fw_dir: Path, case_id: str, params: dict[str, Any]) -> tuple[Path, Path]:
        elf = fw_dir / "firmware.elf"
        uf2 = fw_dir / "firmware.uf2"
        meta = json.dumps({"case_id": case_id, "params": params}, indent=2)
        elf.write_text(f"ELF_PLACEHOLDER\n{meta}\n", encoding="utf-8")
        uf2.write_text(f"UF2_PLACEHOLDER\n{meta}\n", encoding="utf-8")
        return elf, uf2

    @staticmethod
    def _new_run_id() -> str:
        now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        short = uuid4().hex[:6]
        return f"run_{now}_{short}"

    @staticmethod
    def _git_sha() -> str:
        proc = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            return "unknown"
        return proc.stdout.strip() or "unknown"
