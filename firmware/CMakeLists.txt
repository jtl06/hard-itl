cmake_minimum_required(VERSION 3.13)

include(pico_sdk_import.cmake)
project(rp2350_uart_demo C CXX ASM)

pico_sdk_init()
set(TARGET_MAGIC_HEX "0xC0FFEE42" CACHE STRING "MAGIC value used by rp2350_signature_check")

add_executable(rp2350_uart_demo
    rp2350_uart_demo.c
)

target_link_libraries(rp2350_uart_demo pico_stdlib)
pico_enable_stdio_usb(rp2350_uart_demo 1)
pico_enable_stdio_uart(rp2350_uart_demo 0)

pico_add_extra_outputs(rp2350_uart_demo)

add_executable(rp2350_framing_hunt
    rp2350_framing_hunt.c
)
target_link_libraries(rp2350_framing_hunt pico_stdlib)
pico_enable_stdio_usb(rp2350_framing_hunt 1)
pico_enable_stdio_uart(rp2350_framing_hunt 0)
pico_add_extra_outputs(rp2350_framing_hunt)

add_executable(rp2350_parity_hunt
    rp2350_parity_hunt.c
)
target_link_libraries(rp2350_parity_hunt pico_stdlib)
pico_enable_stdio_usb(rp2350_parity_hunt 1)
pico_enable_stdio_uart(rp2350_parity_hunt 0)
pico_add_extra_outputs(rp2350_parity_hunt)

add_executable(rp2350_signature_check
    rp2350_signature_check.c
)
target_compile_definitions(rp2350_signature_check PRIVATE TARGET_MAGIC=${TARGET_MAGIC_HEX})
target_link_libraries(rp2350_signature_check pico_stdlib)
pico_enable_stdio_usb(rp2350_signature_check 1)
pico_enable_stdio_uart(rp2350_signature_check 0)
pico_add_extra_outputs(rp2350_signature_check)
