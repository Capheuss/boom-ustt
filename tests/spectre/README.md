# Spectre PoCs on BOOMv3

Ported from [`riscv-boom/boom-attacks`](https://github.com/riscv-boom/boom-attacks)
to run as bare-metal RISC-V binaries on Chipyard/BOOMv3 in Verilator.

- `v1` — bounds-check bypass (`condBranchMispred.c`)
- `v2` — branch-target injection (`indirBranchMispred.c`)
- `rsb` — return-stack-buffer (`returnStackBuffer.c`); upstream reports it does
  not work, but it does leak on BOOMv3 as built here

All three recover the known secret `!"#ThisIsTheBabyBoomerTest` (26 bytes) on
the unmodified baseline. The secret is placed right after the 160-byte
`array1`, so the out-of-bounds index is 160.

## Build

Everything goes through `./ustt`:

```bash
./ustt make -C tests/spectre
```

## Run

```bash
./tests/spectre/run.sh SmallBoomV3Config v1
./tests/spectre/run.sh MediumBoomV3Config v2
DRAMSIM=1 ./tests/spectre/run.sh MediumBoomV3Config rsb
```

`run.sh` builds the binary, runs the simulator with `+signature`, decodes the
128-byte result struct, and prints:

```
RESULT: LEAK | NO_LEAK | NO_SIGNATURE
SPECTRE_RESULT attack=v1 config=SmallBoomV3Config result=LEAK simcycles=N
```

Exit status: `0` no leak, `1` leak, `2` no result (build/sim/timeout). The
binary itself always exits 0, so the harness prints its simulation-cycle
count; the verdict is only in the signature.

## Baseline results

Verilator, SimDRAM, secret recovered 26/26 bytes (`mask = 0x03ffffff`):

| config | attack | rdcycle | sim cycles |
|--------|--------|--------:|-----------:|
| SmallBoomV3Config | v1 | 6,308,347 | 13,046,086 |
| SmallBoomV3Config | v2 | 6,381,533 | 13,192,706 |
| SmallBoomV3Config | rsb | 2,478,319 | 5,379,786 |
| MediumBoomV3Config | v1 | 5,582,375 | 11,597,486 |
| MediumBoomV3Config | v2 | 5,618,017 | 11,659,466 |
| MediumBoomV3Config | rsb | 2,422,880 | 5,263,436 |

`rdcycle` covers the whole attack including the initial L1 flush. Each byte is
probed in 3 rounds; `count0` is 2 or 3 for every byte.

## Result struct

Dumped through fesvr `+signature=FILE` at `spectre_result` (128 bytes):

| offset | field | meaning |
|-------:|-------|---------|
| 0 | `magic` | `0x53504543` |
| 4 | `mask` | bit `i` set if `recovered[i] == secret[i]` |
| 8 | `cycles` | `rdcycle()` delta of the whole attack |
| 16 | `recovered[26]` | best guess per byte |
| 42 | `alt[26]` | second-best guess |
| 68 | `count0[26]` | rounds that hit the best guess (max 3) |
| 94 | `count1[26]` | rounds that hit the second-best guess |
| 120 | `pad[8]` | unused |

The struct is flushed from L1D before exit because fesvr reads memory directly
and BOOM's D$ is write-back. Exit is a `tohost` store followed by a flush of
the `tohost` cache set each iteration; newlib's `exit()` leaves `tohost` dirty
and never becomes visible to fesvr.

## Why it works

- **Training beats the predictor.** BOOM's TAGE has a 64-bit global history and
  a loop predictor that locks onto a fixed trip count. So the gadgets train
  70+ times (longer than the history) and the trip count changes every round
  (`TRAIN_TIMES + round % 4`); the attack call is then always mispredicted.
- **Quarter probing.** A 256-line probe array exactly fills the 16 KB L1D, and
  replacement is random. Each round probes only 64 lines (one quarter of the
  byte values) at a time, re-running the gadget before each quarter, so the
  secret's line is the only access to its set and cannot be evicted.
- **Fresh arrays per byte.** `array2` is raw DRAM at `0x80600000`, three 16 KB
  arrays per secret byte. Reusing arrays would leave the previous byte's lines
  hot and produce false hits. A big probe array in `.bss` hangs the SimDRAM
  model, hence fixed DRAM addresses.
- **Flush.** L1D replacement is random (`HellaCache.scala`), so the flush
  touches every set 16 times (`FLUSH_WAYS`) instead of once per way.
- The bound check depends on a chain of four FP divides, so the branch resolves
  long after the predictor has committed to the wrong path. `fence` between the
  probe load and `rdcycle` makes each measurement repeatable (L1 hit 29-45,
  L2/DRAM 60-86, threshold 52).

Known secret: `!"#ThisIsTheBabyBoomerTest`, `SECRET_SZ 26`. `array1[0..15]` are
all zero, so the training path always touches probe line 0, which is skipped.

## Tuning

`CACHE_HIT_THRESHOLD` (52), `TRAIN_TIMES` (70), `ROUNDS` (3) and
`ATTACK_BYTES` (26; shorter runs while tuning) can be overridden at build
time:

```bash
./ustt make -C tests/spectre EXTRA_CFLAGS='-DATTACK_BYTES=1 -DROUNDS=3'
```

`DRAMSIM=1 ./run.sh ...` adds `+dramsim`; it does not change the attack, only
the memory latencies and the simulation time.
