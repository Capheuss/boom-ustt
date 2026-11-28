// [boom-ustt] Driver for the full-core STT directed cases (#7). Build one binary per
// case with -DCASE=<1|2|3a|3b|4>; see README.md. Exit status 0 means the architectural
// result check passed. Whether T waited is read from the +stt_trace output by run.sh.

#include <stdint.h>
#include <stdio.h>

extern uint64_t stt_case1(void), stt_c3a(void), stt_c3b(void), stt_case4(void), stt_case5(void);
extern uint64_t stt_case2(uint64_t taken, volatile uint64_t *index);
extern volatile uint64_t stt_tbl[8];
extern uint64_t stt_time_load(volatile void *addr);
extern void stt_trap_handler(void);
extern volatile uint64_t stt_trap[4];
extern volatile uint8_t stt_probe[];

#define CASE_1  1
#define CASE_2  2
#define CASE_3a 3
#define CASE_3b 4
#define CASE_4  5
#define CASE_5  6

// The first pass runs with cold caches and predictors; run.sh judges the later ones.
#define PASSES 3
#define TRAIN  8

// The C runtime zeroes .bss at startup, which leaves the probe lines cached, so case 2
// first reads 256 KiB (16 times the Medium L1 D-cache, whose replacement is random) of
// DRAM above the program image. It is not part of the ELF, because the loader writes
// .bss over the slow serial link. run.sh checks that a never-touched line then misses.
#define EVICT_BASE  0x80100000UL
#define EVICT_BYTES (256 * 1024)

__attribute__((unused)) static void evict_dcache(void)
{
  volatile uint64_t *buf = (volatile uint64_t *)EVICT_BASE;
  for (unsigned i = 0; i < EVICT_BYTES / 8; i += 8)
    (void)buf[i];
}

static int check(const char *what, uint64_t got, uint64_t want)
{
  printf("STT_CHECK %s got=%lu want=%lu %s\n", what, (unsigned long)got, (unsigned long)want,
         got == want ? "ok" : "MISMATCH");
  return got != want;
}

__attribute__((unused)) static int run_trap_case(uint64_t (*fn)(void), uint64_t cause)
{
  int fail = 0;
  asm volatile("csrw mtvec, %0" :: "r"(stt_trap_handler));
  for (int pass = 0; pass < PASSES; pass++) {
    uint64_t before = stt_trap[2];
    fail |= check("result", fn(), 105);
    fail |= check("traps", stt_trap[2] - before, 1);
    fail |= check("mcause", stt_trap[1], cause);
  }
  return fail;
}

int main(void)
{
  int fail = 0;
#if CASE == CASE_1
  for (int pass = 0; pass < PASSES; pass++)
    fail |= check("result", stt_case1(), 4 * 105);
#elif CASE == CASE_2
  for (int i = 0; i < TRAIN; i++)
    fail |= check("train", stt_case2(0, &stt_tbl[2]), 1000);
  evict_dcache();
  fail |= check("result", stt_case2(1, &stt_tbl[1]), 7);
  // Latency of the line the wrong-path T would have touched, then a line nothing touched
  // (a miss) and the first line again (now a hit), for comparison.
  uint64_t probe = stt_time_load(&stt_probe[3 * 64]);
  uint64_t cold  = stt_time_load(&stt_probe[9 * 64]);
  uint64_t hot   = stt_time_load(&stt_probe[3 * 64]);
  printf("STT_PROBE probe=%lu cold=%lu hot=%lu\n", (unsigned long)probe, (unsigned long)cold,
         (unsigned long)hot);
#elif CASE == CASE_3a
  fail |= run_trap_case(stt_c3a, 6);
#elif CASE == CASE_3b
  fail |= run_trap_case(stt_c3b, 4);
#elif CASE == CASE_4
  for (int pass = 0; pass < PASSES; pass++)
    fail |= check("result", stt_case4(), 105);
#elif CASE == CASE_5
  for (int pass = 0; pass < PASSES; pass++)
    fail |= check("result", stt_case5(), 105);
#else
#error "unknown CASE"
#endif
  printf("STT_CASE result=%s\n", fail ? "FAIL" : "PASS");
  return fail;
}
