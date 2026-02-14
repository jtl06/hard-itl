# Firmware Placeholder

This baseline does not ship a full RP2350 SDK project.

The runner currently generates placeholder `firmware.elf` and `firmware.uf2`
artifacts per run in `runs/<run_id>/firmware/` so the pipeline can execute
end-to-end in mock mode.

Intended integration point:
- Replace `Runner._build_firmware_artifacts(...)` in `runner/runner.py` with
  real build commands and produced binaries.
