# Firmware Scaffold

This folder includes:

- `rp2350_uart_demo.c`: baud-hunt demo marker stream.
- `rp2350_framing_hunt.c`: framing-hunt demo marker stream.
- `rp2350_parity_hunt.c`: parity-hunt demo marker stream.
- `rp2350_signature_check.c`: signature demo emitting `payload`, `MAGIC`, `CRC`.
- `CMakeLists.txt`: Pico SDK targets for all RP2350 demo cases.
- `Makefile`: wrapper targets.

```bash
make -C firmware all
```

Outputs:
- `firmware/build/firmware.elf`
- `firmware/build/firmware.uf2`

For RP2350 demo targets:

```bash
make -C firmware rp2350_uart_demo
make -C firmware rp2350_framing_hunt
make -C firmware rp2350_parity_hunt
make -C firmware rp2350_signature_check
```

If `PICO_SDK_PATH` is set, this builds with Pico SDK and copies:
- `build/rp2350/<target>.elf` -> `build/firmware.elf`
- `build/rp2350/<target>.uf2` -> `build/firmware.uf2`

If `PICO_SDK_PATH` is missing, it falls back to placeholder artifacts so the
software pipeline can still execute.

For signature check target magic override:

```bash
make -C firmware rp2350_signature_check TARGET_MAGIC_HEX=0xC0FFEE42
```

For real hardware runs, enforce a real SDK build (no placeholders):

```bash
make -C firmware REQUIRE_PICO_SDK=1 rp2350_uart_demo
```

If your SDK/board differs, you can override board selection:

```bash
make -C firmware REQUIRE_PICO_SDK=1 PICO_BOARD=pico2 rp2350_uart_demo
```
