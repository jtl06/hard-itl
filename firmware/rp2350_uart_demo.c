#include <stdio.h>
#include "pico/stdlib.h"

// RP2350/Pico UART marker demo.
// Continuously emits RUN_START / RUN_END markers expected by the HIL runner
// so capture can succeed even if it begins after device boot.
int main(void) {
    stdio_init_all();
    sleep_ms(1200);

    uint32_t cycle = 0;
    while (true) {
        printf("RUN_START cycle_%lu\n", (unsigned long)cycle);
        printf("INFO boot rp2350_uart_demo cycle=%lu\n", (unsigned long)cycle);
        for (int i = 0; i < 5; ++i) {
            printf("INFO heartbeat %d cycle=%lu\n", i, (unsigned long)cycle);
            sleep_ms(200);
        }
        printf("RUN_END cycle_%lu\n", (unsigned long)cycle);
        cycle++;
        sleep_ms(300);
    }
}
