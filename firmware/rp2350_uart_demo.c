#include <stdio.h>
#include "pico/stdlib.h"
#include "bootsel_helper.h"

// RP2350/Pico UART marker demo.
// Emits RUN_START / RUN_END markers expected by the HIL runner.
int main(void) {
    stdio_init_all();
    sleep_ms(1200);

    const char *run_id = "firmware_boot";
    printf("RUN_START %s\n", run_id);
    printf("INFO boot rp2350_uart_demo\n");

    for (int i = 0; i < 5; ++i) {
        bootsel_poll_command();
        printf("INFO heartbeat %d\n", i);
        sleep_ms(300);
    }

    printf("RUN_END %s\n", run_id);

    while (true) {
        bootsel_poll_command();
        printf("INFO idle\n");
        sleep_ms(1000);
    }
}
