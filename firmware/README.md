# Firmware Scaffold

This folder now includes a minimal `Makefile` so the configured build command works:

```bash
make -C firmware all
```

Outputs:
- `firmware/build/firmware.elf`
- `firmware/build/firmware.uf2`

These are placeholder artifacts for pipeline validation. Replace this scaffold with
real RP2350 firmware build logic when your SDK/project is available.
