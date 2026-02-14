from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


class FlashError(RuntimeError):
    pass


class Flasher:
    def __init__(self, mock_mode: bool = True) -> None:
        self.mock_mode = mock_mode

    def flash(self, image_path: Path, method: str = "auto") -> tuple[bool, str, list[str]]:
        diagnostics: list[str] = []
        if self.mock_mode:
            diagnostics.append("mock mode: flash simulated")
            return True, "mock", diagnostics

        if not image_path.exists():
            raise FlashError(f"firmware image not found: {image_path}")

        flash_method = method if method != "auto" else self._autodetect_method(diagnostics)
        if flash_method == "uf2":
            return self._flash_uf2(image_path, diagnostics)
        if flash_method == "picotool":
            return self._flash_picotool(image_path, diagnostics)
        if flash_method == "openocd":
            return self._flash_openocd(image_path, diagnostics)

        diagnostics.append("No flash backend available. Tried UF2, picotool, openocd.")
        raise FlashError("flash auto-detect failed; install picotool/openocd or mount UF2 drive")

    def _autodetect_method(self, diagnostics: list[str]) -> str:
        if self._find_uf2_mount() is not None:
            diagnostics.append("auto-detect: uf2 mass-storage available")
            return "uf2"
        if shutil.which("picotool"):
            diagnostics.append("auto-detect: picotool available")
            return "picotool"
        if shutil.which("openocd"):
            diagnostics.append("auto-detect: openocd available")
            return "openocd"
        return ""

    def _find_uf2_mount(self) -> Path | None:
        roots = [Path("/Volumes"), Path("/media"), Path("/run/media")]
        user = os.getenv("USER", "")
        if user:
            roots.extend([Path(f"/media/{user}"), Path(f"/run/media/{user}")])

        labels = {"RPI-RP2", "RPI_RP2", "PICO2", "RP2350"}
        for root in roots:
            if not root.exists():
                continue
            for child in root.iterdir():
                if child.name.upper() in labels and child.is_dir():
                    return child
        return None

    def _flash_uf2(self, image_path: Path, diagnostics: list[str]) -> tuple[bool, str, list[str]]:
        mount = self._find_uf2_mount()
        if mount is None:
            diagnostics.append("UF2 method selected but no mounted RP2 drive found")
            return False, "uf2", diagnostics
        dest = mount / image_path.name
        shutil.copy2(image_path, dest)
        diagnostics.append(f"copied UF2 image to {dest}")
        return True, "uf2", diagnostics

    def _flash_picotool(self, image_path: Path, diagnostics: list[str]) -> tuple[bool, str, list[str]]:
        cmd = ["picotool", "load", str(image_path), "-f"]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        diagnostics.append(f"picotool rc={proc.returncode}")
        if proc.stdout.strip():
            diagnostics.append(proc.stdout.strip())
        if proc.stderr.strip():
            diagnostics.append(proc.stderr.strip())
        return proc.returncode == 0, "picotool", diagnostics

    def _flash_openocd(self, image_path: Path, diagnostics: list[str]) -> tuple[bool, str, list[str]]:
        cfg = os.getenv("OPENOCD_CFG", "")
        if not cfg:
            diagnostics.append("OPENOCD_CFG not set; cannot run openocd backend")
            return False, "openocd", diagnostics
        cmd = [
            "openocd",
            "-f",
            cfg,
            "-c",
            f"program {image_path} verify reset exit",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        diagnostics.append(f"openocd rc={proc.returncode}")
        if proc.stdout.strip():
            diagnostics.append(proc.stdout.strip())
        if proc.stderr.strip():
            diagnostics.append(proc.stderr.strip())
        return proc.returncode == 0, "openocd", diagnostics
