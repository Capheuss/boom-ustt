// [boom-ustt] Module tests for the baseline STT issue gate and per-cycle tag clearing (#7).

package boom.v3.exu

import chisel3._
import chisel3.util.Valid
import chisel3.simulator.EphemeralSimulator._
import org.scalatest.funspec.AnyFunSpec

import org.chipsalliance.cde.config.Parameters

import boom.v3.common._

/**
 * One IssueSlot with the STT ports driven directly: VP, ROB head and stt_block. All branch
 * masks are 0, so only the STT gate can hold a uop. Exposes the issued and compaction tags.
 */
class IssueSlotSTTHarness(implicit p: Parameters) extends Module
{
  val slot = Module(new IssueSlot(numWakeupPorts = 1))
  val io = IO(new Bundle {
    val in_uop     = Input(Valid(new MicroOp))
    val grant      = Input(Bool())
    val stt_block  = Input(Bool())
    val vp         = Input(Valid(UInt(slot.robAddrSz.W)))
    val head       = Input(UInt(slot.robAddrSz.W))
    val valid      = Output(Bool())
    val request    = Output(Bool())
    val request_hp = Output(Bool())
    val iss_yrot   = Output(Valid(UInt(slot.robAddrSz.W)))
    val out_yrot   = Output(Valid(UInt(slot.robAddrSz.W)))
  })
  slot.io.in_uop      := io.in_uop
  slot.io.grant       := io.grant
  slot.io.stt_block.get := io.stt_block
  slot.io.stt_vp.get    := io.vp
  slot.io.stt_head.get  := io.head
  slot.io.kill        := false.B
  slot.io.clear       := false.B
  slot.io.ldspec_miss := false.B
  slot.io.brupdate    := DontCare
  slot.io.brupdate.b1.resolve_mask    := 0.U
  slot.io.brupdate.b1.mispredict_mask := 0.U
  slot.io.brupdate.b2.mispredict      := false.B
  slot.io.brupdate.b2.target_offset   := 0.S(16.W)
  slot.io.wakeup_ports.foreach(_.valid := false.B)
  slot.io.wakeup_ports.foreach(_.bits := DontCare)
  slot.io.pred_wakeup_port.valid := false.B
  slot.io.pred_wakeup_port.bits  := DontCare
  slot.io.spec_ld_wakeup.foreach(_.valid := false.B)
  slot.io.spec_ld_wakeup.foreach(_.bits := DontCare)
  io.valid      := slot.io.valid
  io.request    := slot.io.request
  io.request_hp := slot.io.request_hp
  io.iss_yrot   := slot.io.uop.yrot.get
  io.out_yrot   := slot.io.out_uop.yrot.get
}

class IssueSlotSTTSpec extends AnyFunSpec with IssueUnitConstants
{
  implicit val p: Parameters = ConservativeSlotParams.withSwitch(new WithSTT)

  def dut = new IssueSlotSTTHarness

  /** VP: None means no unresolved branch. */
  def setVP(c: IssueSlotSTTHarness, vp: Option[Int], head: Int = 0): Unit = {
    c.io.vp.valid.poke(vp.isDefined.B)
    c.io.vp.bits.poke(vp.getOrElse(0).U)
    c.io.head.poke(head.U)
  }

  def reset(c: IssueSlotSTTHarness): Unit = {
    c.io.in_uop.valid.poke(false.B)
    c.io.grant.poke(false.B)
    c.io.stt_block.poke(false.B)
    setVP(c, None)
    c.reset.poke(true.B)
    c.clock.step()
    c.reset.poke(false.B)
  }

  /** Write one operand-ready uop with input tag `yrot` (None = untainted). The VP/head poked
   *  beforehand are the ones seen in the write (dispatch) cycle. */
  def insert(c: IssueSlotSTTHarness, yrot: Option[Int], transmitter: Boolean, isLoad: Boolean = false,
             isBr: Boolean = false, isStore: Boolean = false, dataBusy: Boolean = false): Unit = {
    val u = c.io.in_uop.bits
    u.uopc.poke(if (isStore) uopSTA else if (isLoad) uopLD else if (isBr) uopBEQ else uopADD)
    u.iw_state.poke(if (isStore) s_valid_2 else s_valid_1)
    u.br_mask.poke(0.U)
    u.is_transmitter.get.poke(transmitter.B)
    u.yrot.get.valid.poke(yrot.isDefined.B)
    u.yrot.get.bits.poke(yrot.getOrElse(0).U)
    u.uses_ldq.poke(isLoad.B)
    u.uses_stq.poke(isStore.B)
    u.is_br.poke(isBr.B)
    u.is_jal.poke(false.B)
    u.is_jalr.poke(false.B)
    u.prs1.poke(1.U)
    u.prs2.poke(2.U)
    u.prs3.poke(3.U)
    u.ppred.poke(0.U)
    u.lrs1_rtype.poke(RT_FIX)
    u.lrs2_rtype.poke(if (isStore) RT_FIX else RT_X)
    u.prs1_busy.poke(false.B)
    u.prs2_busy.poke(dataBusy.B)
    u.prs3_busy.poke(false.B)
    u.ppred_busy.poke(false.B)
    u.iw_p1_poisoned.poke(false.B)
    u.iw_p2_poisoned.poke(false.B)
    c.io.in_uop.valid.poke(true.B)
    c.clock.step()
    c.io.in_uop.valid.poke(false.B)
  }

  def expectRequest(c: IssueSlotSTTHarness, req: Boolean, msg: String): Unit = {
    c.io.valid.expect(true.B, msg)
    c.io.request.expect(req.B, msg)
    if (!req) c.io.request_hp.expect(false.B, msg)
  }

  describe("IssueSlot with enableSTT") {
    it("holds a load whose root follows the VP and releases it in the cycle the VP passes the root") {
      simulate(dut) { c =>
        reset(c)
        setVP(c, Some(2))
        insert(c, yrot = Some(4), transmitter = true, isLoad = true)
        expectRequest(c, false, "root 4 follows branch 2")
        c.io.iss_yrot.valid.expect(true.B, "held tag still valid")
        setVP(c, Some(6))
        expectRequest(c, true, "VP advanced past root 4")
        c.io.iss_yrot.valid.expect(false.B, "issued tag is the cleared one")
      }
    }

    it("treats equality with the VP as unsafe") {
      simulate(dut) { c =>
        reset(c)
        setVP(c, Some(2))
        insert(c, yrot = Some(2), transmitter = true, isLoad = true)
        expectRequest(c, false, "yrot == VP")
      }
    }

    it("issues with no unresolved branch, and issues an untainted load under a branch") {
      simulate(dut) { c =>
        reset(c)
        insert(c, yrot = Some(4), transmitter = true, isLoad = true)
        expectRequest(c, true, "VP invalid")
      }
      simulate(dut) { c =>
        reset(c)
        setVP(c, Some(2))
        insert(c, yrot = None, transmitter = true, isLoad = true)
        expectRequest(c, true, "untainted address under branch 2")
      }
    }

    it("orders tags across the ROB wrap using the head") {
      simulate(dut) { c =>
        reset(c)
        setVP(c, Some(2), head = 28)
        insert(c, yrot = Some(30), transmitter = true, isLoad = true)
        expectRequest(c, true, "root 30 precedes the wrapped branch 2")
      }
      simulate(dut) { c =>
        reset(c)
        setVP(c, Some(2), head = 28)
        insert(c, yrot = Some(4), transmitter = true, isLoad = true)
        expectRequest(c, false, "root 4 follows the wrapped branch 2")
      }
    }

    it("clears the held tag once safe, so a reused ROB index cannot re-block it") {
      simulate(dut) { c =>
        reset(c)
        setVP(c, Some(6))
        insert(c, yrot = Some(4), transmitter = true, isLoad = true)
        expectRequest(c, true, "root 4 older than branch 6")
        c.clock.step()
        // Root 4 retired and index 4 now names an instruction younger than the new branch 2.
        setVP(c, Some(2), head = 30)
        expectRequest(c, true, "cleared tag stays released")
        c.io.iss_yrot.valid.expect(false.B, "held tag was cleared")
      }
    }

    it("keeps a dispatch-cycle tag raw when an older same-group branch is not in the VP yet") {
      simulate(dut) { c =>
        reset(c)
        setVP(c, None)       // the dispatch-cycle VP does not see the same-group branch
        insert(c, yrot = Some(4), transmitter = true, isLoad = true)
        setVP(c, Some(2))    // next cycle the branch is in the ROB
        expectRequest(c, false, "same-group branch 2 is older than root 4")
      }
    }

    it("does not delay a non-transmitter with an unsafe tag") {
      simulate(dut) { c =>
        reset(c)
        setVP(c, Some(2))
        insert(c, yrot = Some(4), transmitter = false)
        expectRequest(c, true, "ALU op propagates taint, does not wait")
      }
    }

    it("blocks a safe transmitter while stt_block is high") {
      simulate(dut) { c =>
        reset(c)
        insert(c, yrot = None, transmitter = true, isLoad = true)
        c.io.stt_block.poke(true.B)
        expectRequest(c, false, "stt_block")
        c.io.stt_block.poke(false.B)
        expectRequest(c, true, "stt_block released")
      }
    }

    it("holds a tainted branch, and lets an untainted branch issue with request_hp") {
      simulate(dut) { c =>
        reset(c)
        setVP(c, Some(2))
        insert(c, yrot = Some(4), transmitter = true, isBr = true)
        expectRequest(c, false, "tainted branch")
      }
      simulate(dut) { c =>
        reset(c)
        setVP(c, Some(2), head = 28)
        insert(c, yrot = Some(30), transmitter = true, isBr = true)
        expectRequest(c, true, "branch with older root")
        c.io.request_hp.expect(true.B, "branch is high priority")
      }
    }

    it("holds both halves of a split store with an unsafe tag") {
      simulate(dut) { c =>
        reset(c)
        setVP(c, Some(2))
        insert(c, yrot = Some(4), transmitter = true, isStore = true)
        expectRequest(c, false, "STA+STD")
        setVP(c, Some(6))
        expectRequest(c, true, "VP passed root 4")
      }
      simulate(dut) { c =>
        reset(c)
        setVP(c, Some(2))
        insert(c, yrot = Some(4), transmitter = true, isStore = true, dataBusy = true)
        expectRequest(c, false, "STA half")
      }
    }

    it("keeps a released tag cleared across more than two ROB wraps (spec section 8: tag lifetime)") {
      simulate(dut) { c =>
        reset(c)
        setVP(c, Some(6))
        insert(c, yrot = Some(4), transmitter = true, isLoad = true)
        expectRequest(c, true, "root 4 older than branch 6")
        c.clock.step()
        // Three full wraps. Each cycle the VP sits just after the head, so index 4 names an
        // instruction younger than the VP in every cycle but one; a stale tag would block.
        for (h <- 0 until 3 * 32) {
          setVP(c, Some((h + 1) % 32), head = h % 32)
          expectRequest(c, true, s"wrap step $h")
          c.io.iss_yrot.valid.expect(false.B, s"tag stays cleared at step $h")
          c.clock.step()
        }
      }
    }

    it("keeps an unsafe tag held while the head wraps, until the VP passes the root") {
      simulate(dut) { c =>
        reset(c)
        setVP(c, Some(2), head = 28)
        insert(c, yrot = Some(4), transmitter = true, isLoad = true)
        for (h <- Seq(29, 30, 31, 0, 1)) {
          setVP(c, Some(2), head = h)
          expectRequest(c, false, s"head $h, root 4 still follows branch 2")
          c.clock.step()
        }
        setVP(c, Some(6), head = 1)
        expectRequest(c, true, "branch 2 resolved; root 4 older than branch 6")
      }
    }

    it("lets stt_block win over a release in the same cycle (spec section 8: recovery)") {
      simulate(dut) { c =>
        reset(c)
        setVP(c, Some(2))
        insert(c, yrot = Some(4), transmitter = true, isLoad = true)
        setVP(c, Some(6))                // the VP passes the root...
        c.io.stt_block.poke(true.B)      // ...in a mispredict cycle
        expectRequest(c, false, "kill wins over release")
        c.io.stt_block.poke(false.B)
        expectRequest(c, true, "released once recovery ends")
      }
    }

    it("sends the cleared tag on compaction") {
      simulate(dut) { c =>
        reset(c)
        setVP(c, Some(2))
        insert(c, yrot = Some(4), transmitter = true, isLoad = true)
        c.io.out_yrot.valid.expect(true.B, "unsafe tag moves with the uop")
        c.io.out_yrot.bits.expect(4.U)
        setVP(c, Some(6))
        c.io.out_yrot.valid.expect(false.B, "safe tag is cleared on the move")
      }
    }
  }
}

class IssueSlotSTTSwitchSpec extends AnyFunSpec
{
  def ports(mixin: Parameters): (Boolean, Boolean) = {
    implicit val p: Parameters = ConservativeSlotParams.withSwitch(mixin)
    var res = (true, true)
    circt.stage.ChiselStage.emitCHIRRTL(new Module {
      val slot = Module(new IssueSlot(numWakeupPorts = 1))
      res = (slot.io.stt_vp.isDefined, slot.io.stt_head.isDefined)
      slot.io := DontCare
    })
    res
  }

  it("IssueSlot has VP/head ports only with enableSTT") {
    assert(ports(new WithSTT) == ((true, true)))
    assert(ports(new WithConservativeSTT) == ((false, false)))
    assert(ports(Parameters.empty) == ((false, false)))
  }
}
