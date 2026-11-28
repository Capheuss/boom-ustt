# STT full-core directed cases (#7)

Short bare-metal programs for `MediumBoomV3STTConfig`. They exercise the cases that the
attacks don't reliably reach. Each case has the same shape:
- **B** is a branch whose condition comes from a chain of dependent divides, so it stays
  unresolved for a few hundred cycles.
- **R** is a load under B whose address is untainted. It is the root.
- **T** is a transmitter whose address depends on R.

Under STT, T is ready as soon as R returns, but it must wait until B resolves.

| Case | What it covers |
| --- | --- |
| `1` | B and R in one dispatch group (one ROB row), followed by T. This is the raw dispatch-cycle tag. Four copies shift B by 0 to 3 slots, so at least one of them puts B and R in the same row. |
| `2` | B mispredicted while T waits under it. The driver trains B not taken 8 times, reads 256 KB of DRAM to evict the D-cache, then calls the case once with B taken. R and T then run only on the wrong path, where T would read probe line 3. |
| `3a` | Exception while T waits: a misaligned store X, older than B (mcause 6). |
| `3b` | Exception while T waits: a misaligned load X, older than B (mcause 4). |
| `4` | Branch-tag reuse: after T come 40 short loop branches. They resolve at once and free their tags (Medium has 12), so tags get reused while B is still unresolved. |
| `5` | A held tag outlives its root. U is an ALU op tainted by R that also waits on three divides. B resolves and R retires while U and T are still queued, so their stored tags must already be clear. This is the case the tag-lifetime assertion (`STTAssertLive`) is built for: with the issue-slot or LDQ clearing disabled, it fires here. |

In case 3, X's address comes from a divide, so X faults late, after B, R and T have
dispatched. The handler skips X, and B, R and T run again. An illegal instruction or an
`ecall` can't produce this case on BOOM:
- the ROB stops taking new instructions as soon as an exception is recorded, and a
  decode-time exception is recorded at dispatch;
- `ecall` is serializing.

So with either one, no younger transmitter can be in flight.

## Run

```bash
./tests/stt-directed/run.sh MediumBoomV3STTConfig 1     # or 2, 3a, 3b, 4, 5
```

`run.sh` builds `case<N>.riscv` and runs the simulator with `+stt_trace=1`. With that flag,
the issue queues print one line for each cycle a ready transmitter is held by the STT gate,
and one line when a transmitter issues. Without the flag nothing is printed, and the
regressions don't pass it.

The script then reads the trace at the PCs of the labels `stt_c*_br`, `_root` and `_tx` in
`cases.S`, and prints one line:

```
STT_DIRECTED case=1 config=MediumBoomV3STTConfig result=PASS simrc=0 assertions=0 ...
```

PASS requires all of the following:
- the program's own result check passes;
- the simulator exits with status 0 (any assertion stops it);
- no `[boom-ustt]` or "Assertion failed" line appears;
- the trace evidence for the case:

| Case | Trace evidence |
| --- | --- |
| `1` | In every copy, T issues only after B, or is squashed without issuing. In a warm pass, B and R share a ROB row and T is held. |
| `2` | In each training call, T is held and then issues. In the mispredicted call, T is held and never issues. After the eviction, an untouched reference line misses, and the probe line misses too. |
| `3a`, `3b` | In two warm passes, T is held when X flushes it. Then it is held again after the handler, and issues. |
| `4` | In both warm passes: T is held, then issues after B. More than 12 loop branches resolve while T is held, and a tag is reused. B's own tag is never reallocated. |
| `5` | In both warm passes, T issues more than 100 cycles after B, so U and T stayed queued after R retired. |

The first pass of cases 1, 3, 4 and 5 runs with cold caches and predictors, so it is reported
but not judged.

Logs and the symbol table go to `logs/stt-directed/case<N>-<CONFIG>.{log,syms}`.
