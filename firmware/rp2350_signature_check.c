#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include "pico/stdlib.h"
#include "bootsel_helper.h"

#ifndef TARGET_MAGIC
#define TARGET_MAGIC 0xC0FFEE42u
#endif

// Signature-check demo firmware.
// Emits payload/MAGIC/CRC with RUN_START/RUN_END markers continuously.
// CRC uses the same contract as analyst.py:
//   crc32("payload|0x%08X", TARGET_MAGIC)
static uint32_t crc32_bytes(const uint8_t *data, size_t len) {
    uint32_t crc = 0xFFFFFFFFu;
    for (size_t i = 0; i < len; ++i) {
        crc ^= (uint32_t)data[i];
        for (int j = 0; j < 8; ++j) {
            uint32_t mask = (uint32_t)(-(int)(crc & 1u));
            crc = (crc >> 1) ^ (0xEDB88320u & mask);
        }
    }
    return ~crc;
}

int main(void) {
    stdio_init_all();
    sleep_ms(1200);

    const char *payload = "PING_SEQ_001";
    char msg[96];
    (void)snprintf(msg, sizeof(msg), "%s|0x%08lX", payload, (unsigned long)TARGET_MAGIC);
    uint32_t crc = crc32_bytes((const uint8_t *)msg, strlen(msg));

    uint32_t cycle = 0;
    while (true) {
        bootsel_poll_command();
        printf("RUN_START signature_%lu\n", (unsigned long)cycle);
        printf("INFO demo signature_check cycle=%lu\n", (unsigned long)cycle);
        printf("INFO payload=%s\n", payload);
        printf("MAGIC=0x%08lX\n", (unsigned long)TARGET_MAGIC);
        printf("CRC=0x%08lX\n", (unsigned long)crc);
        printf("RUN_END signature_%lu\n", (unsigned long)cycle);
        cycle++;
        sleep_ms(400);
    }
}
