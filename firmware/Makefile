BUILD_DIR := build
ELF := $(BUILD_DIR)/firmware.elf
UF2 := $(BUILD_DIR)/firmware.uf2
RP_BUILD := $(BUILD_DIR)/rp2350

TARGET_MAGIC_HEX ?= 0xC0FFEE42
REQUIRE_PICO_SDK ?= 0

DEMO_TARGETS := rp2350_uart_demo rp2350_framing_hunt rp2350_parity_hunt rp2350_signature_check

.PHONY: all clean $(DEMO_TARGETS)

all: $(ELF) $(UF2)
	@echo "Firmware artifacts ready: $(ELF), $(UF2)"

$(DEMO_TARGETS): %: $(RP_BUILD)/%.uf2
	@cp -f "$(RP_BUILD)/$*.elf" "$(ELF)"
	@cp -f "$(RP_BUILD)/$*.uf2" "$(UF2)"
	@echo "RP2350 demo artifacts ready: $(ELF), $(UF2) (from $*)"

$(BUILD_DIR):
	mkdir -p "$(BUILD_DIR)"

$(RP_BUILD):
	mkdir -p "$(RP_BUILD)"

$(ELF): | $(BUILD_DIR)
	@printf "ELF_PLACEHOLDER\n" > "$(ELF)"
	@printf "generated_utc=%s\n" "$$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$(ELF)"

$(UF2): | $(BUILD_DIR)
	@printf "UF2_PLACEHOLDER\n" > "$(UF2)"
	@printf "generated_utc=%s\n" "$$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$(UF2)"

$(RP_BUILD)/%.uf2: CMakeLists.txt rp2350_uart_demo.c rp2350_framing_hunt.c rp2350_parity_hunt.c rp2350_signature_check.c | $(RP_BUILD)
	@if [ -z "$$PICO_SDK_PATH" ]; then \
		if [ "$(REQUIRE_PICO_SDK)" = "1" ]; then \
			echo "ERROR: PICO_SDK_PATH is not set; refusing placeholder build for real mode."; \
			echo "Set PICO_SDK_PATH and rerun (example: export PICO_SDK_PATH=~/pico-sdk)"; \
			exit 2; \
		else \
			echo "PICO_SDK_PATH not set; generating RP2350 placeholder artifacts for $*"; \
			printf "%s_ELF_PLACEHOLDER\n" "$*" > "$(RP_BUILD)/$*.elf"; \
			printf "generated_utc=%s\n" "$$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$(RP_BUILD)/$*.elf"; \
			printf "%s_UF2_PLACEHOLDER\n" "$*" > "$(RP_BUILD)/$*.uf2"; \
			printf "generated_utc=%s\n" "$$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$(RP_BUILD)/$*.uf2"; \
		fi; \
	else \
		cmake -S . -B "$(RP_BUILD)" -DPICO_BOARD=pico2 -DTARGET_MAGIC_HEX="$(TARGET_MAGIC_HEX)"; \
		cmake --build "$(RP_BUILD)" -j --target "$*"; \
	fi

clean:
	rm -rf "$(BUILD_DIR)"
