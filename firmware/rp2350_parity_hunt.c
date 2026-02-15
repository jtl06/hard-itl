#include <stdio.h>
#include "pico/stdlib.h"

// Parity-hunt demo firmware.
// Emits structured UART lines continuously with RUN_START/RUN_END markers.
int main(void) {
    stdio_init_all();
    sleep_ms(1200);

    uint32_t cycle = 0;
    while (true) {
        printf("RUN_START parity_%lu\n", (unsigned long)cycle);
        printf("INFO demo parity_hunt\n");
        printf("INFO parity_hint even\n");
        printf("INFO pattern 0x00 0xFF 0x7E 0x81\n");
        for (int i = 0; i < 5; ++i) {
            printf("INFO heartbeat %d cycle=%lu\n", i, (unsigned long)cycle);
            sleep_ms(200);
        }
        printf("RUN_END parity_%lu\n", (unsigned long)cycle);
        cycle++;
        sleep_ms(300);
    }
}
