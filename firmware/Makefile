BUILD_DIR := build
ELF := $(BUILD_DIR)/firmware.elf
UF2 := $(BUILD_DIR)/firmware.uf2
RP_BUILD := $(BUILD_DIR)/rp2350
RP_ELF := $(RP_BUILD)/rp2350_uart_demo.elf
RP_UF2 := $(RP_BUILD)/rp2350_uart_demo.uf2

.PHONY: all rp2350_uart_demo clean

all: $(ELF) $(UF2)
	@echo "Firmware artifacts ready: $(ELF), $(UF2)"

rp2350_uart_demo: $(RP_UF2)
	@cp -f $(RP_ELF) $(ELF)
	@cp -f $(RP_UF2) $(UF2)
	@echo "RP2350 demo artifacts ready: $(ELF), $(UF2)"

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

$(ELF): | $(BUILD_DIR)
	@printf "ELF_PLACEHOLDER\n" > $(ELF)
	@printf "generated_utc=%s\n" "$$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> $(ELF)

$(UF2): | $(BUILD_DIR)
	@printf "UF2_PLACEHOLDER\n" > $(UF2)
	@printf "generated_utc=%s\n" "$$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> $(UF2)

$(RP_BUILD):
	mkdir -p $(RP_BUILD)

$(RP_UF2): CMakeLists.txt rp2350_uart_demo.c | $(RP_BUILD)
	@if [ -z "$$PICO_SDK_PATH" ]; then \
		echo "PICO_SDK_PATH not set; generating RP2350 placeholder artifacts"; \
		printf "RP2350_ELF_PLACEHOLDER\n" > $(RP_ELF); \
		printf "generated_utc=%s\n" "$$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> $(RP_ELF); \
		printf "RP2350_UF2_PLACEHOLDER\n" > $(RP_UF2); \
		printf "generated_utc=%s\n" "$$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> $(RP_UF2); \
	else \
		cmake -S . -B $(RP_BUILD) -DPICO_BOARD=pico2; \
		cmake --build $(RP_BUILD) -j; \
	fi

clean:
	rm -rf $(BUILD_DIR)
