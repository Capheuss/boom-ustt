CROSS ?= riscv64-unknown-elf-

# Bare-metal M-mode (htif_nano.specs), same flags as tests/spectre, plus the atexit
# workaround from tests/CMakeLists.txt that printf-using tests need.
CFLAGS ?= -march=rv64imafd -mabi=lp64d -mcmodel=medany -std=gnu99 -O2 \
          -Wall -Wextra -specs=htif_nano.specs

CASES   = 1 2 3a 3b 4 5
TARGETS = $(CASES:%=case%.riscv)

all: $(TARGETS)

case%.riscv: main.c cases.S ../atexit-workaround.c
	$(CROSS)gcc $(CFLAGS) -DCASE=CASE_$* -Wl,--wrap=atexit -o $@ main.c cases.S ../atexit-workaround.c

clean:
	rm -f $(TARGETS)

.PHONY: all clean
