# [boom-ustt] Full-core STT directed cases (#7). See README.md.
#
# Every case uses the same shape: a branch B whose condition comes from a chain of
# dependent divides (so it stays unresolved for a few hundred cycles), a load R under B
# whose address is untainted (the root), and a transmitter T whose address depends on R.
# Under STT, T is ready as soon as R returns but must wait until B resolves.
# The labels stt_c*_br / _root / _tx mark B, R and T for run.sh.

  .option norvc

  .section .data
  .balign 64
  .globl stt_tbl
stt_tbl:                      # tbl[0]: index for cases 1, 3, 4. tbl[1], tbl[2]: case 2 probe lines
  .dword 5, 3, 0, 0, 0, 0, 0, 0
  .globl stt_arr
stt_arr:                      # arr[i] = 100 + i, so T reads 105
  .dword 100, 101, 102, 103, 104, 105, 106, 107

  .section .bss
  .balign 64
  .globl stt_probe
stt_probe:                    # case 2 probe lines, one per 64 bytes, never touched before the case
  .skip 64 * 16
  .globl stt_trap
stt_trap:                     # saved t1, last mcause, trap count, last mepc
  .skip 32

  .text

# dst := 0 after n dependent divides of 2^63-1 by 1 (no early out).
.macro SLOW n, dst
  li   a5, -1
  srli a5, a5, 1
  li   a6, 1
  mv   \dst, a5
  .rept \n
  div  \dst, \dst, a6
  .endr
  sub  \dst, \dst, a5
.endm

.macro PROLOGUE
  addi sp, sp, -32
  sd   s1, 0(sp)
  sd   s2, 8(sp)
  sd   ra, 16(sp)
  la   s1, stt_tbl
  la   s2, stt_arr
  ld   t0, 0(s1)              # warm the table and array lines, so R returns quickly
  ld   t0, 8(s1)
  ld   t0, 40(s2)
  li   a0, 0
.endm

.macro EPILOGUE
  ld   s1, 0(sp)
  ld   s2, 8(sp)
  ld   ra, 16(sp)
  addi sp, sp, 32
  ret
.endm

#------------------------------------------------------------------------------
# Case 1: B and R in one dispatch group, then a dependent T (the raw dispatch-cycle tag).
# Medium dispatches two uops per cycle; the four copies shift B by 0-3 slots so that at
# least one copy puts B and R in the same ROB row. run.sh reports which copies did.
# Returns 4 * 105.
.macro C1 id, pad
  SLOW 2, a4
  .rept \pad
  nop
  .endr
  .globl stt_c1_br\id
stt_c1_br\id:   bnez a4, 1f
  .globl stt_c1_root\id
stt_c1_root\id: ld   t1, 0(s1)
  slli t1, t1, 3
  add  t1, t1, s2
  .globl stt_c1_tx\id
stt_c1_tx\id:   ld   t2, 0(t1)
  add  a0, a0, t2
1:
.endm

  .globl stt_case1
stt_case1:
  PROLOGUE
  C1 0, 0
  C1 1, 1
  C1 2, 2
  C1 3, 3
  EPILOGUE

#------------------------------------------------------------------------------
# Case 2: B is mispredicted while T waits under it. stt_case2(taken, slot): the driver
# trains B not taken (T runs and reads probe line tbl[2] = 0), then calls it once with B
# taken, so R and T run only on the wrong path, where T would read probe line tbl[1] = 3.
# Returns 1000 + T's value on the fall-through path and 7 when B is taken.
  .globl stt_case2
stt_case2:
  mv   a2, a0                 # taken flag
  mv   a3, a1                 # &tbl[i] for R
  PROLOGUE
  la   s2, stt_probe
  .balign 64
  SLOW 3, a4
  add  a4, a4, a2             # B is taken iff the flag is set
  .globl stt_c2_br
stt_c2_br:      bnez a4, 2f
  .globl stt_c2_root
stt_c2_root:    ld   t1, 0(a3)
  slli t1, t1, 6
  add  t1, t1, s2
  .globl stt_c2_tx
stt_c2_tx:      ld   t2, 0(t1)
  addi a0, t2, 1000
  EPILOGUE
2:
  li   a0, 7
  EPILOGUE

#------------------------------------------------------------------------------
# Case 3: an exception is taken while T waits. X is a misaligned access older than B, so
# B, R and T dispatch behind it. X's address comes from one divide, so X faults late: the
# ROB stops dispatch only once an exception is recorded, and BOOM records decode-time
# exceptions (illegal instruction) at dispatch and serializes ecall, so neither can have a
# younger transmitter waiting. B waits on three more divides, so T is held when X flushes.
# The handler skips X, then B, R and T run again and T issues once B resolves. Returns 105.
.macro C3 name, xinst
  .globl stt_\name
stt_\name:
  PROLOGUE
  .balign 64
  li   a5, -1
  srli a5, a5, 1
  li   a6, 1
  div  a3, a5, a6
  sub  a3, a3, a5
  add  a3, a3, s1             # &tbl, known only after the divide
  .globl stt_\name\()_x
stt_\name\()_x: \xinst
  mv   a4, a5
  div  a4, a4, a6
  div  a4, a4, a6
  div  a4, a4, a6
  sub  a4, a4, a5
  .globl stt_\name\()_br
stt_\name\()_br:   bnez a4, 3f
  .globl stt_\name\()_root
stt_\name\()_root: ld   t1, 0(s1)
  slli t1, t1, 3
  add  t1, t1, s2
  .globl stt_\name\()_tx
stt_\name\()_tx:   ld   t2, 0(t1)
  add  a0, a0, t2
3:
  EPILOGUE
.endm

  C3 c3a, "sd zero, 1(a3)"    # misaligned store (mcause 6)
  C3 c3b, "ld t0, 1(a3)"      # misaligned load (mcause 4)

#------------------------------------------------------------------------------
# Case 4: branch-tag reuse while T is held. After T come 40 short loop branches that
# resolve at once and free their tags; Medium has 12, so tags are reused while B is
# still unresolved. Returns 105.
  .globl stt_case4
stt_case4:
  PROLOGUE
  .balign 64
  SLOW 3, a4
  .globl stt_c4_br
stt_c4_br:      bnez a4, 4f
  .globl stt_c4_root
stt_c4_root:    ld   t1, 0(s1)
  slli t1, t1, 3
  add  t1, t1, s2
  .globl stt_c4_tx
stt_c4_tx:      ld   t2, 0(t1)
  li   t3, 40
5:
  addi t3, t3, -1
  .globl stt_c4_loop
stt_c4_loop:    bnez t3, 5b
  add  a0, a0, t2
4:
  EPILOGUE

#------------------------------------------------------------------------------
# Case 5: a held tag outlives its root. U is an ALU op tainted by R that also waits on
# three divides that start after B's one. B resolves and R retires while U and T are still
# queued, so their stored tags must already be clear: the tag-lifetime assertion checks the
# issue queue and LDQ copies against the ROB head. Returns 105.
  .globl stt_case5
stt_case5:
  PROLOGUE
  .balign 64
  li   a5, -1
  srli a5, a5, 1
  li   a6, 1
  mv   a4, a5
  div  a4, a4, a6
  sub  a4, a4, a5
  .globl stt_c5_br
stt_c5_br:      bnez a4, 6f
  .globl stt_c5_root
stt_c5_root:    ld   t1, 0(s1)
  mv   a7, a5
  div  a7, a7, a6
  div  a7, a7, a6
  div  a7, a7, a6
  sub  a7, a7, a5
  .globl stt_c5_u
stt_c5_u:       add  t4, t1, a7
  slli t4, t4, 3
  add  t4, t4, s2
  .globl stt_c5_tx
stt_c5_tx:      ld   t2, 0(t4)
  add  a0, a0, t2
6:
  EPILOGUE

#------------------------------------------------------------------------------
# Load latency of one address, in cycles. CSR reads are serializing on BOOM, so the
# second rdcycle waits for the load.
  .globl stt_time_load
stt_time_load:
  fence
  rdcycle t0
  ld   t1, 0(a0)
  rdcycle t2
  sub  a0, t2, t0
  ret

# M-mode trap handler for case 3: record the cause, skip the 4-byte faulting instruction.
  .balign 4
  .globl stt_trap_handler
stt_trap_handler:
  csrw mscratch, t0
  la   t0, stt_trap
  sd   t1, 0(t0)
  csrr t1, mcause
  sd   t1, 8(t0)
  ld   t1, 16(t0)
  addi t1, t1, 1
  sd   t1, 16(t0)
  csrr t1, mepc
  sd   t1, 24(t0)
  addi t1, t1, 4
  csrw mepc, t1
  ld   t1, 0(t0)
  csrr t0, mscratch
  mret
