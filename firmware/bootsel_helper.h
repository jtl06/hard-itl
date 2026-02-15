#ifndef BOOTSEL_HELPER_H
#define BOOTSEL_HELPER_H

#include <stddef.h>
#include <string.h>
#include "pico/bootrom.h"
#include "pico/stdlib.h"

// Poll USB CDC stdin for "BOOTSEL" (or "ENTER_BOOTSEL") command and jump to ROM bootloader.
static inline void bootsel_poll_command(void) {
    static char line[32];
    static size_t used = 0;

    while (true) {
        int ch = getchar_timeout_us(0);
        if (ch == PICO_ERROR_TIMEOUT) {
            return;
        }
        if (ch == '\r' || ch == '\n') {
            line[used] = '\0';
            if (strcmp(line, "BOOTSEL") == 0 || strcmp(line, "ENTER_BOOTSEL") == 0) {
                printf("INFO entering BOOTSEL\n");
                sleep_ms(50);
                reset_usb_boot(0, 0);
            }
            used = 0;
            continue;
        }
        if (used < sizeof(line) - 1) {
            line[used++] = (char)ch;
        } else {
            used = 0;
        }
    }
}

#endif  // BOOTSEL_HELPER_H
