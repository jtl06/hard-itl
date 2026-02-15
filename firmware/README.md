# Firmware Scaffold

This folder includes:

- `rp2350_uart_demo.c`: a concrete RP2350 UART marker example emitting
  `RUN_START` / `RUN_END`.
- `CMakeLists.txt`: Pico SDK target for `rp2350_uart_demo`.
- `Makefile`: wrapper targets.

```bash
make -C firmware all
```

Outputs:
- `firmware/build/firmware.elf`
- `firmware/build/firmware.uf2`

For RP2350 demo target:

```bash
make -C firmware rp2350_uart_demo
```

If `PICO_SDK_PATH` is set, this builds with Pico SDK and copies:
- `build/rp2350/rp2350_uart_demo.elf` -> `build/firmware.elf`
- `build/rp2350/rp2350_uart_demo.uf2` -> `build/firmware.uf2`

If `PICO_SDK_PATH` is missing, it falls back to placeholder artifacts so the
software pipeline can still execute.
