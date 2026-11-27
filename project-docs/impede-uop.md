# #8 [B3] Impede micro-op for BOOM: design note

Status: for review. Implementation starts after this note is approved and merged (#8's first Done-when box).

Builds on:
- #7: the baseline STT delay, the LSU audit, the tag-lifetime assertion and `tests/stt-directed`, all in PR #60, not yet merged into dev;
- spec-interface.md sections 5 and 6.

The gem5 paths below are relative to `reference/uSTT/gem5/src` (the `reference/uSTT` submodule).

## 1. What µSTT's impede uop does, in gem5

Reference: `reference/uSTT/gem5/src`, tagged `[Boru, STT]`.

- **Cracking** (`arch/arm/isa/templates/mem64stt.isa`, `arch/arm/isa/insts/ldr64stt.isa`, `arch/arm/isa/insts/str64stt.isa`, `arch/arm/isa/templates/branch64stt.isa`): a load, store or branch is decoded into two micro-ops.
  - `MicroImpedeUop` is `Ureg0 = base`.
  - The transmitter then uses `Ureg0` as its base register, so it depends on the impede uop through an ordinary register.
- **Tag** (`cpu/o3/rename.cc`):
  - The impede uop is renamed first with `yrot = UINT64_MAX` (no tag yet).
  - When the transmitter is renamed, the impede uop's `yrot` is overwritten with the transmitter's YRoT (`lastImpedeUop->yrot = inst->yrot`).
  - The impede uop's destination taint is computed from its own sources, so `Ureg0` stays tainted.
- **Wait** (`cpu/o3/inst_queue.cc`): when the impede uop is selected, it is parked if it has no tag yet or `yrot > VP`.
  - Parked impede uops leave the ready list.
  - Transmitters themselves have no STT check when `impedeUop` is on.
- **Release** (`cpu/o3/iew.cc`, `releaseDelayedImpedeUop`): each cycle, `lastVP` steps forward toward the current VP, at most writeback-width steps.
  - Every parked impede uop whose `yrot` equals the step is released.
  - Release is therefore an **equality match on a broadcast**, not a per-entry age compare, and its rate is bounded.
- The impede uop then executes like a move and wakes the transmitter through normal register wakeup.

In this snapshot the cracking is switched off: `arch/arm/isa/insts/insts.isa` includes `ldr64.isa`, `str64.isa` and `branch64.isa`, with the `*stt.isa` variants commented out. `IMPEDE_UOP_*` are 0 (`arch/arm/insts/macromem.hh`, `arch/arm/insts/branch64.hh`) and `impedeUop` defaults to False (`cpu/o3/BaseO3CPU.py`). The mechanism is clear from the code, but we have no gem5 numbers for it.

## 2. What has to change in BOOM

In #7, every issue slot in every queue holds a YRoT and clears it each cycle with `STTClearSafe`. That is one circular age compare per slot against the VP, plus the tag register.
- That is 48 slots on Medium (12 mem + 20 int + 16 FP) and 24 on Small. Non-transmitter slots carry the logic too, because the slot module is shared.
- The gate is `STTIssueOk`, which uses the same compare.

Spec section 6 requires #8 to "explain how it removes per-entry age comparators, including those used only for tag cleanup". It also says "moving the same comparator from request logic to cleanup logic does not establish the intended area reduction." So the issue slots must stop holding a YRoT at all, not just stop using it in the request.

## 3. Options

| Option | How the transmitter waits | Cost | Per-slot STT logic left |
| --- | --- | --- | --- |
| (a) Extra uop at dispatch (gem5 style) | Crack in decode into impede + transmitter. The impede uop writes a new physical register that the transmitter reads. | One more decode slot, ROB entry, IQ entry and physical register per transmitter, plus an ALU pass (latency). BOOM has no cracking, so this touches the fetch buffer, decode, rename, ROB, commit trace and Spike cosim. The taint is not known at decode, so every transmitter must be cracked, tainted or not. | All slots of the queue the impede uops go to still need the release logic. |
| (b) Ordinary IQ slot reserved at dispatch | A second slot in the same queue holds the tag and wakes the transmitter. | One more IQ slot per tainted transmitter. | **All slots**, because any slot can hold an impede entry. This moves the comparator rather than removing it. |
| **(c) Impede table** (recommended) | A small, separate table allocated at dispatch only for transmitters whose YRoT is valid. The transmitter waits on a one-bit "impeded" operand that the table releases. | N entries of tag + compare (N = 8 on Medium), dispatch allocation like the LDQ, and a stall when the table is full. | One busy bit, a log2(N)-bit index and an N:1 mux per slot. **No tag and no age compare.** |

Option (c) is a refinement of (b): the reserved entry goes in a dedicated structure, not in the issue queue. That is what makes the per-slot logic go away. It keeps µSTT's idea, which is to take the wait out of the IQ and have it end by an ordinary wakeup, without (a)'s cracking cost.

## 4. Recommended design: impede table

All of this sits behind `impedeUop` (the parameter already exists and requires `enableSTT`). Every new line is marked `// [boom-ustt]`.

### 4.1 Structure

`STTImpedeTable` in `exu/`, with `numImpedeEntries` entries. Proposed defaults: Small 4, Medium 8, to be swept in #11. Each entry holds:
- `valid`;
- `yrot`: the transmitter's YRoT;
- `br_mask`: the transmitter's branch mask, for kill.

### 4.2 Dispatch

- A dispatching transmitter with `yrot.valid` (the same taint-table output #7 uses, including same-group roots) allocates one entry.
- The uop is written to its issue queue(s) with `impede_busy = 1` and `impede_idx = entry`.
- A transmitter with an invalid YRoT allocates nothing and gets `impede_busy = 0`.
- Allocation works like LDQ/STQ allocation: a priority-encoded free list across `coreWidth` lanes. A lane that cannot get an entry is a new dispatch hazard, and the lanes behind it wait, the same as when the LDQ is full.
- A split store (STA in the mem IQ, STD in the FP IQ for FP stores) uses **one** entry. Both copies carry the same `impede_idx`.

### 4.3 Release

- Each cycle, every valid entry computes `release(i) = valid(i) && STTIsSafe(yrot(i), vp, head)`. These are the only STT age comparators left on the issue side: N of them, instead of one per slot.
- The N-bit `release` vector is broadcast to every issue queue.
- A released entry frees at that edge. A safe tag never becomes unsafe (#7 audit, fact 2), so a release is final and nothing needs to be cleaned up afterwards. That covers spec section 5's lifetime rule for this structure.
- The release is combinational, like #7's gate. A slot can request in the same cycle its entry releases, so the issue timing matches #7.
- Entries are killed with `IsKilledByBranch` on their `br_mask` and cleared on flush. A killed entry's transmitter is killed by the same branch, so no live slot can wait on a freed index.

### 4.4 Issue slot

- New per-slot state: `impede_busy` (1 bit) and `impede_idx` (log2 N bits).
- Each cycle, `impede_busy` is cleared when `release(impede_idx)` is set.
- The cleared value is what goes out on `io.out_uop` (compaction) and `io.uop` (issue). This is the same hold-and-transfer rule #7 uses for tags.
- The STT part of the request becomes `!is_transmitter || (!stt_block && !impede_busy_now)`, where `impede_busy_now = impede_busy && !release(impede_idx)`.
  - `stt_block` stays, because it is one global bit.
  - `request_hp` still derives from the gated request.
- With `impedeUop` on, the slot holds no YRoT and runs no `STTClearSafe`. This is #8's second Done-when box ("per-entry delay logic removed from the issue queue").
- `s_valid_2` stores: one `impede_busy` gates both halves, as `is_transmitter` does now.

### 4.5 Branches and `jalr`

Branches and `jalr` are transmitters and go through the same path in the int IQ. A tainted branch waits until its root is older than the VP. Progress is #7's argument:
- The oldest unresolved branch is the VP itself.
- Its root, if it has one, is older than it, so that root is already older than the VP and the branch's entry releases.
- When that branch resolves, the VP moves to the next unresolved branch, and the same holds for it.
- Recovery (`stt_block`) is a bounded pulse.

### 4.6 LSU paths that skip the issue queue

The #7 audit carries over unchanged:
- Every LSU access still enters through an issue slot, now gated by the impede release.
- A release happens only when `isSafe(yrot)` holds.
- Safety is monotonic.
- So every TLB retry, nack replay, store commit and forward comes from an entry whose tag was already safe.

The LSU keeps #7's LDQ/STQ tags and the fire-point assertions. Those tags feed only assertions, which Chisel emits inside `ifndef SYNTHESIS`. A synthesis run should therefore drop them, in #7 as well. D should confirm this in #13 (see 6.2).

### 4.7 Checks

The assertions don't depend on the new mechanism, so they check it rather than repeat it:
- **#7's checks stay:** issue-port, branch-resolution, LSU fire-point and tag-lifetime. #8's third box requires "#7's assertion never fires".
  - With `impedeUop` on, the issue slots keep a **simulation-only shadow** of #7's YRoT and its clearing, used only by those assertions.
  - The shadow is the same code #7 has. It has no fanout to `io.request`, so synthesis removes it (see 6.2).
- **New checks:**
  - A transmitter never issues with `impede_busy_now` set.
  - A tainted transmitter never dispatches without an entry.
  - A released entry's tag is safe (true by construction; checked anyway).
  - Every valid entry's tag passes the same lifetime check as #7's (`STTAssertLive` against the transmitter's ROB index, so the entry also stores that index, in simulation only).
  - No two live slots wait on the same index unless they are the two halves of one store.
- **Mutation tests:**
  - Release ignoring the VP must fire the issue-port assertion.
  - Never releasing must trip the existing deadlock timeouts.

### 4.8 Configs

Per spec-interface.md section 7:
- `WithSTTImpedeUop` (enables STT and `impedeUop`);
- `SmallBoomV3STTImpedeConfig`, `MediumBoomV3STTImpedeConfig`, `MediumBoomV3STTImpedeCosimConfig`.

The `require(!impedeUop, ...)` in `parameters.scala` comes out. USTT (Age Matrix + impede) stays with #5.

## 5. Differences from gem5, on purpose

| gem5 | This design | Why |
| --- | --- | --- |
| Cracks every transmitter at decode | Allocates only for transmitters with a valid YRoT at dispatch | BOOM has no cracking, and the taint is only known at dispatch. Untainted transmitters cost nothing. |
| Impede uop is a real move through an ALU and a register | No uop: a table entry and a one-bit operand | No extra ROB entry, physical register, dispatch slot or ALU latency. The commit trace and cosim are unchanged. |
| Release by stepping `lastVP`, at most writeback-width per cycle | Every entry compares against the VP each cycle (N comparators) | All released entries go in one cycle, so there is no release lag behind the VP. N is small. |
| Impede uops sit in the unified IQ | Separate N-entry table | Keeps the release logic out of the issue slots. |

## 6. Costs, risks and what to measure

### 6.1 Logic on Medium

|  | #7 STT | #8 impede |
| --- | --- | --- |
| Per issue slot (×48) | 7-bit tag register + `IsOlder` (three 6-bit compares) + clear mux | 1 + 3 bits + an 8:1 mux |
| Central | none | 8 entries × (7-bit tag + 12-bit `br_mask` + valid) + 8 `IsOlder` + allocation |

D measures the actual numbers in #13/#16.

### 6.2 Risks and checks

- **The simulation-only shadow tags must not survive synthesis.** Check the synthesized netlist (#13) for the shadow registers. If they do survive, add a switch that drops them for area runs. That would be a spec change, so it needs review.
- **Dispatch stall when the table is full.** This is the main performance risk. #11 sweeps `numImpedeEntries` (4/8/16) and reports stall cycles. Sharing one entry between transmitters with the same root would cut the pressure; it is left as a follow-up unless the sweep shows a need.
- **Timing.** The release path is VP → 8 comparators → 8-bit vector → per-slot mux → request. #7's path is VP → per-slot compare → request. One more mux level; check in #13.

## 7. Verification (#8's Done-when boxes)

Every item below gets a command, a log path, the config and the commit on #8.

1. **Design note merged:** this document.
2. **Per-entry delay logic removed:** the generated `IssueSlot` for `MediumBoomV3STTImpedeConfig` has no YRoT compare feeding the request, checked in the Verilog. A module test covers the new slot gating: release, kill, compaction carrying the cleared bit, both store halves, and `stt_block` winning over a release.
3. **#7's assertions never fire, and every attack fails:** `scripts/ustt-regress.sh` on the Small and Medium impede configs, plus `tests/stt-directed/` cases 1–5 on Medium. The trace has to be extended to show impede releases.
4. **riscv-tests and benchmarks pass on Small and Medium, no timeouts:** the same regression, plus Spike cosim on the Medium cosim config.
5. **Switches off match `baseline-v0`:** `scripts/rtl/switches-off.sh SmallBoomV3Config MediumBoomV3Config`, and the regression's verilog-diff stage.

Each step also has a mutation run that shows its check is live: release ignoring the VP, and the table never releasing.

## 8. Questions for the reviewer

1. Is option (c), a dedicated table instead of a cracked uop, acceptable as "the impede uop" for the report? It keeps the mechanism (wait outside the IQ, release by wakeup) but not gem5's encoding.
2. Is the simulation-only shadow tag in the issue slots acceptable for keeping #7's assertions, provided #13 confirms synthesis removes it?
3. Default `numImpedeEntries`: 4 on Small and 8 on Medium, or sized from #11 first?
4. Should sharing one entry per root be in scope for #8, or a follow-up?

## 9. Plan after approval

| Step | Files | Estimate |
| --- | --- | --- |
| Table + dispatch allocation and hazard | `exu/stt-impede-table.scala` (new), `exu/core.scala` (shared) | 0.5 day |
| Slot and queue changes, compaction, store halves, FP store data | `issue-slot.scala`, `issue-unit.scala`, `fp-pipeline.scala` | 0.5 day |
| Mixin and configs, remove the `require` | `parameters.scala`, `config-mixins.scala`, `BoomConfigs.scala` (shared) | 1 hour |
| Module tests, assertions, mutation runs | `src/test/scala/v3/exu/` | 0.5 day |
| Regressions and directed cases on Small and Medium | none | about 2 hours of machine time, overlapped |

The shared files (`core.scala`, `parameters.scala`, config files) need a teammate review, as in #7.
