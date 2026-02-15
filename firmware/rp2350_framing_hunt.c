#include <stdio.h>
#include "pico/stdlib.h"

// Framing-hunt demo firmware.
// Emits structured UART lines continuously with RUN_START/RUN_END markers.
int main(void) {
    stdio_init_all();
    sleep_ms(1200);

    uint32_t cycle = 0;
    while (true) {
        printf("RUN_START framing_%lu\n", (unsigned long)cycle);
        printf("INFO demo framing_hunt\n");
        printf("INFO frame_hint 8N1\n");
        printf("INFO pattern 0x55 0xAA 0x33 0xCC\n");
        for (int i = 0; i < 5; ++i) {
            printf("INFO heartbeat %d cycle=%lu\n", i, (unsigned long)cycle);
            sleep_ms(200);
        }
        printf("RUN_END framing_%lu\n", (unsigned long)cycle);
        cycle++;
        sleep_ms(300);
    }
}
