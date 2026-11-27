//------------------------------------------------------------------------------
// [boom-ustt] Shared STT helpers: transmitter classification and YRoT safety
// against the visibility point (VP). Contract: project-docs/spec-interface.md.
//------------------------------------------------------------------------------

package boom.v3.common

import chisel3._
import chisel3.util._

import boom.v3.util.IsOlder

/**
 * The STT transmitter set (spec section 3). Classify the decoded instruction,
 * never a rewritten issue opcode, so split stores keep the original flag.
 */
object STTIsTransmitter
{
  def apply(uop: MicroOp): Bool = uop.uses_ldq || (uop.uses_stq && !uop.is_fence) || uop.is_br || uop.is_jalr
}

/**
 * A tag is safe when it is invalid, there is no unresolved branch, or its root
 * is strictly older than the VP. Equality is unsafe.
 */
object STTIsSafe
{
  def apply(yrot: Valid[UInt], vp: Valid[UInt], head: UInt): Bool =
    !yrot.valid || !vp.valid || IsOlder(yrot.bits, vp.bits, head)
}

/**
 * Conservative stand-in permission (#6, spec section 6): a transmitter may issue
 * only outside recovery and with no unresolved older branch in its updated mask.
 */
object STTConservativeOk
{
  def apply(is_transmitter: Bool, stt_block: Bool, updated_br_mask: UInt): Bool =
    !is_transmitter || (!stt_block && !updated_br_mask.orR)
}

/**
 * Simulation checks on an issue-queue output for the conservative stand-in. The transmitter test is
 * recomputed from the uop, so it does not trust the stored flag the gate uses.
 */
object STTAssertConservativeIssue
{
  def apply(valid: Bool, uop: MicroOp, updated_br_mask: UInt, stt_block: Bool, queue: String): Unit = {
    assert(!valid || uop.is_transmitter.get === STTIsTransmitter(uop),
      s"[boom-ustt] $queue issue: is_transmitter lost or changed before issue")
    assert(!(valid && STTIsTransmitter(uop) && (updated_br_mask.orR || stt_block)),
      s"[boom-ustt] $queue issue: conservative transmitter issued under an unresolved branch or during recovery")
  }
}

/** An invalid tag with a zero payload. */
object STTUntainted
{
  def apply(robAddrSz: Int): Valid[UInt] = {
    val t = Wire(Valid(UInt(robAddrSz.W)))
    t.valid := false.B
    t.bits  := 0.U
    t
  }
}

/** Drop a tag that has become safe, so a released transmitter stays released. */
object STTClearSafe
{
  def apply(yrot: Valid[UInt], vp: Valid[UInt], head: UInt): Valid[UInt] = {
    val t = Wire(Valid(UInt(yrot.bits.getWidth.W)))
    t.valid := yrot.valid && !STTIsSafe(yrot, vp, head)
    t.bits  := Mux(t.valid, yrot.bits, 0.U)
    t
  }
}

/** The younger of two tags in circular ROB order; invalid tags contribute nothing. */
object STTYoungest
{
  def apply(a: Valid[UInt], b: Valid[UInt], head: UInt): Valid[UInt] = {
    val take_b = b.valid && (!a.valid || IsOlder(a.bits, b.bits, head))
    Mux(take_b, b, a)
  }
}

/**
 * STT issue permission (spec section 6). `yrot` is the slot's tag after this cycle's
 * clearing, so a valid tag means the root is not yet older than the VP.
 */
object STTIssueOk
{
  def apply(is_transmitter: Bool, stt_block: Bool, cleared_yrot: Valid[UInt]): Bool =
    !is_transmitter || (!stt_block && !cleared_yrot.valid)
}

/**
 * Checks an STT issue port. An issue slot sends out the tag it cleared that cycle, so a
 * transmitter that passed the gate leaves with an invalid tag. The transmitter test is
 * recomputed from the uop rather than taken from the flag the gate used.
 */
object STTAssertIssue
{
  def apply(valid: Bool, uop: MicroOp, stt_block: Bool, queue: String): Unit = {
    assert(!valid || uop.is_transmitter.get === STTIsTransmitter(uop),
      s"[boom-ustt] $queue issue: is_transmitter lost or changed before issue")
    assert(!(valid && STTIsTransmitter(uop) && (uop.yrot.get.valid || stt_block)),
      s"[boom-ustt] $queue issue: STT transmitter issued with an unsafe YRoT or during recovery")
  }
}

/**
 * Tag lifetime (spec section 5) for a tag held by a live instruction `holder`. A YRoT names a
 * strictly older root, so a valid held tag must lie in [head, holder): the root is still in the ROB
 * window, which ends at the tail, and has not been retired with its index reused. A retired root sits
 * before the head and a reused index sits after the holder, so both fail the age check. The check is
 * on the stored tag; a dispatch-cycle tag is checked from the cycle after it is written.
 */
object STTAssertLive
{
  def apply(valid: Bool, yrot: Valid[UInt], holder: UInt, head: UInt, what: String): Unit =
    assert(!(valid && yrot.valid && !IsOlder(yrot.bits, holder, head)),
      s"[boom-ustt] $what holds a YRoT that is not a live root older than it")
}

/** Checks one LSU or branch side effect: a transmitter fires only with a safe tag. */
object STTAssertSafe
{
  def apply(fire: Bool, yrot: Valid[UInt], vp: Valid[UInt], head: UInt, what: String): Unit =
    assert(!(fire && !STTIsSafe(yrot, vp, head)), s"[boom-ustt] $what fired with an unsafe YRoT")
}
