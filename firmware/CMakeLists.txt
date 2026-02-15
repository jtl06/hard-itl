cmake_minimum_required(VERSION 3.13)

include(pico_sdk_import.cmake)
project(rp2350_uart_demo C CXX ASM)

pico_sdk_init()

add_executable(rp2350_uart_demo
    rp2350_uart_demo.c
)

target_link_libraries(rp2350_uart_demo pico_stdlib)
pico_enable_stdio_usb(rp2350_uart_demo 1)
pico_enable_stdio_uart(rp2350_uart_demo 0)

pico_add_extra_outputs(rp2350_uart_demo)
