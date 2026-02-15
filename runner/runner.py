from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from runner.flash import FlashError, Flasher
from runner.serial_capture import capture_uart, wait_for_serial_port


@dataclass
class RunnerConfig:
    runs_root: str = "runs"
    flash_method: str = "auto"
    serial_port: str = ""
    serial_baud: int = 115200
    serial_timeout_s: float = 8.0
    reenumeration_timeout_s: float = 8.0
    prefer_by_id: bool = True
    build_cmd: str = ""
    build_cwd: str = "."
    real_elf_path: str = ""
    real_uf2_path: str = ""


class Runner:
    """Hardware boundary: all build/flash/serial interactions are centralized here."""

    def __init__(self, config: RunnerConfig | None = None) -> None:
        self.config = config or RunnerConfig()
        self.runs_root = Path(self.config.runs_root)
        self.runs_root.mkdir(parents=True, exist_ok=True)

    def flash(self, image_path: Path, method: str = "auto", mode: str = "mock") -> tuple[bool, str, list[str]]:
        flasher = Flasher(mock_mode=(mode == "mock"))
        return flasher.flash(image_path=image_path, method=method)

    def execute(
        self,
        case_id: str,
        run_index: int,
        params: dict[str, Any],
        mode: str = "mock",
        uart_line_callback: Callable[[str], None] | None = None,
        emulate_timing: bool = False,
    ) -> dict[str, Any]:
        run_id = self._new_run_id()
        run_dir = self.runs_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        fw_dir = run_dir / "firmware"
        fw_dir.mkdir(parents=True, exist_ok=True)
        elf_path, uf2_path = self._build_firmware_artifacts(
            fw_dir=fw_dir,
            case_id=case_id,
            params=params,
            mode=mode,
        )

        diagnostics: list[str] = []
        try:
            flash_ok, flash_method, flash_diag = self.flash(uf2_path, method=self.config.flash_method, mode=mode)
            diagnostics.extend(flash_diag)
        except FlashError as exc:
            flash_ok = False
            flash_method = "none"
            diagnostics.append(str(exc))

        serial_port = self.config.serial_port
        if mode != "mock":
            serial_port = wait_for_serial_port(
                previous_port=serial_port or None,
                timeout_s=self.config.reenumeration_timeout_s,
                prefer_by_id=self.config.prefer_by_id,
            ) or ""
            diagnostics.append(
                f"serial re-enumeration selected port={serial_port or 'none'} within {self.config.reenumeration_timeout_s}s"
            )

        capture_baud = int(params.get("guess_baud", self.config.serial_baud))
        uart_lines, uart_pass, capture_note, detected_port = capture_uart(
            run_id=run_id,
            params=params,
            mode=mode,
            serial_port=serial_port,
            baud=capture_baud,
            timeout_s=self.config.serial_timeout_s,
            prefer_by_id=self.config.prefer_by_id,
            line_callback=uart_line_callback,
            emulate_timing=emulate_timing,
        )
        diagnostics.append(capture_note)

        uart_path = run_dir / "uart.log"
        uart_path.write_text("\n".join(uart_lines) + "\n", encoding="utf-8")

        resolved_port = detected_port or serial_port or self.config.serial_port or "auto"
        status = "pass" if flash_ok and uart_pass else "fail"
        manifest = {
            "run_id": run_id,
            "case_id": case_id,
            "run_index": run_index,
            "params": params,
            "git_sha": self._git_sha(),
            "timestamps": {"created_utc": datetime.now(timezone.utc).isoformat()},
            "flash_method": flash_method,
            "serial_port": resolved_port,
            "status": status,
            "artifacts": {
                "firmware_elf": str(elf_path),
                "firmware_uf2": str(uf2_path),
                "uart_log": str(uart_path),
                "analysis": str(run_dir / "analysis.json"),
                "triage": str(run_dir / "triage.md"),
            },
            "diagnostics": diagnostics,
        }
        (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        return {
            "run_id": run_id,
            "run_dir": str(run_dir),
            "status": status,
            "params": params,
            "flash_method": flash_method,
            "serial_port": resolved_port,
            "diagnostics": diagnostics,
        }

    def _build_firmware_artifacts(
        self,
        fw_dir: Path,
        case_id: str,
        params: dict[str, Any],
        mode: str,
    ) -> tuple[Path, Path]:
        elf = fw_dir / "firmware.elf"
        uf2 = fw_dir / "firmware.uf2"
        if mode == "real":
            if self.config.build_cmd:
                build_cmd = self.config.build_cmd
                try:
                    build_cmd = build_cmd.format(case_id=case_id)
                except KeyError:
                    # Keep literal command when unrelated braces are present.
                    build_cmd = self.config.build_cmd
                build_env = dict(os.environ)
                if case_id == "signature_check" and "target_magic" in params:
                    try:
                        build_env["TARGET_MAGIC_HEX"] = hex(int(params["target_magic"]))
                    except (TypeError, ValueError):
                        pass
                proc = subprocess.run(
                    build_cmd,
                    cwd=self.config.build_cwd,
                    capture_output=True,
                    text=True,
                    shell=True,
                    env=build_env,
                    check=False,
                )
                if proc.returncode != 0:
                    stdout_tail = proc.stdout.strip()[-1200:]
                    stderr_tail = proc.stderr.strip()[-1200:]
                    msg = (
                        "build command failed. "
                        f"cmd='{build_cmd}' rc={proc.returncode} "
                        f"stdout_tail='{stdout_tail}' stderr_tail='{stderr_tail}'"
                    )
                    raise FlashError(msg)

            if not self.config.real_uf2_path:
                raise FlashError(
                    "real mode requires runner.real_uf2_path in config.yaml (path to built firmware UF2)"
                )

            src_uf2 = Path(self.config.real_uf2_path)
            if not src_uf2.exists():
                raise FlashError(f"UF2 artifact not found: {src_uf2}")
            if self._is_placeholder_artifact(src_uf2):
                raise FlashError(
                    f"UF2 artifact looks like a placeholder: {src_uf2}. "
                    "Refusing to flash in real mode. Set PICO_SDK_PATH and rebuild firmware."
                )

            uf2.write_bytes(src_uf2.read_bytes())

            if self.config.real_elf_path:
                src_elf = Path(self.config.real_elf_path)
                if src_elf.exists():
                    elf.write_bytes(src_elf.read_bytes())
                else:
                    elf.write_text(
                        f"ELF_MISSING {src_elf}\n",
                        encoding="utf-8",
                    )
            else:
                elf.write_text("ELF_PATH_NOT_CONFIGURED\n", encoding="utf-8")
            return elf, uf2

        meta = json.dumps({"case_id": case_id, "params": params}, indent=2)
        elf.write_text(f"ELF_PLACEHOLDER\n{meta}\n", encoding="utf-8")
        uf2.write_text(f"UF2_PLACEHOLDER\n{meta}\n", encoding="utf-8")
        return elf, uf2

    @staticmethod
    def _is_placeholder_artifact(path: Path) -> bool:
        try:
            data = path.read_bytes()
        except OSError:
            return False
        return b"PLACEHOLDER" in data[:4096]

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
