/* Stand-in for valgrind's header: with -DCALLGRIND_RUN=1, CoreMark's riscv64-baremetal start_time/stop_time call these, so mcycle/minstret cover the timed region like riscv-tests' setStats. */
void setStats(int enable);
#define CALLGRIND_START_INSTRUMENTATION setStats(1);
#define CALLGRIND_STOP_INSTRUMENTATION setStats(0);
