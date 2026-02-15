BUILD_DIR := build
ELF := $(BUILD_DIR)/firmware.elf
UF2 := $(BUILD_DIR)/firmware.uf2

.PHONY: all clean

all: $(ELF) $(UF2)
	@echo "Firmware artifacts ready: $(ELF), $(UF2)"

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

$(ELF): | $(BUILD_DIR)
	@printf "ELF_PLACEHOLDER\n" > $(ELF)
	@printf "generated_utc=%s\n" "$$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> $(ELF)

$(UF2): | $(BUILD_DIR)
	@printf "UF2_PLACEHOLDER\n" > $(UF2)
	@printf "generated_utc=%s\n" "$$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> $(UF2)

clean:
	rm -rf $(BUILD_DIR)
