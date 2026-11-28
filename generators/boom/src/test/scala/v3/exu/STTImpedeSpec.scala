// [boom-ustt] Module tests for the #8 impede table and the impede gate in the issue slot.

package boom.v3.exu

import chisel3._
import chisel3.util.Valid
import chisel3.simulator.EphemeralSimulator._
import org.scalatest.funspec.AnyFunSpec

import org.chipsalliance.cde.config.Parameters

import boom.v3.common._

/**
 * One IssueSlot with impedeUop on. The release vector, VP, head and stt_block are driven
 * directly; branch masks are 0. Exposes the issued and compaction busy bits and the shadow tag.
 */
class IssueSlotImpedeHarness(implicit p: Parameters) extends Module
{
  val slot = Module(new IssueSlot(numWakeupPorts = 1))
  val io = IO(new Bundle {
    val in_uop     = Input(Valid(new MicroOp))
    val grant      = Input(Bool())
    val stt_block  = Input(Bool())
    val release    = Input(UInt(slot.numImpedeEntries.W))
    val vp         = Input(Valid(UInt(slot.robAddrSz.W)))
    val head       = Input(UInt(slot.robAddrSz.W))
    val valid      = Output(Bool())
    val request    = Output(Bool())
    val request_hp = Output(Bool())
    val iss_busy   = Output(Bool())
    val out_busy   = Output(Bool())
    val iss_yrot   = Output(Valid(UInt(slot.robAddrSz.W)))
  })
  slot.io.in_uop      := io.in_uop
  slot.io.grant       := io.grant
  slot.io.stt_block.get      := io.stt_block
  slot.io.stt_vp.get         := io.vp
  slot.io.stt_head.get       := io.head
  slot.io.impede_release.get := io.release
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
  io.iss_busy   := slot.io.uop.impede_busy.get
  io.out_busy   := slot.io.out_uop.impede_busy.get
  io.iss_yrot   := slot.io.uop.yrot.get
}

/** The impede table with its lanes, VP and branch update driven directly. */
class STTImpedeTableHarness(implicit p: Parameters) extends Module
{
  val table = Module(new STTImpedeTable)
  val io = IO(new Bundle {
    val lanes           = Input(Vec(table.coreWidth, new STTImpedeLane))
    val full            = Output(Vec(table.coreWidth, Bool()))
    val idx             = Output(Vec(table.coreWidth, UInt(table.impedeIdxSz.W)))
    val release         = Output(UInt(table.numImpedeEntries.W))
    val vp              = Input(Valid(UInt(table.robAddrSz.W)))
    val head            = Input(UInt(table.robAddrSz.W))
    val resolve_mask    = Input(UInt(table.maxBrCount.W))
    val mispredict_mask = Input(UInt(table.maxBrCount.W))
    val flush           = Input(Bool())
  })
  table.io.lanes := io.lanes
  io.full        := table.io.full
  io.idx         := table.io.idx
  io.release     := table.io.release
  table.io.vp    := io.vp
  table.io.head  := io.head
  table.io.flush := io.flush
  table.io.brupdate := DontCare
  table.io.brupdate.b1.resolve_mask    := io.resolve_mask
  table.io.brupdate.b1.mispredict_mask := io.mispredict_mask
  table.io.brupdate.b2.mispredict      := false.B
  table.io.brupdate.b2.target_offset   := 0.S(16.W)
}

class STTImpedeSpec extends AnyFunSpec with IssueUnitConstants
{
  val entries = 2
  implicit val p: Parameters = ConservativeSlotParams.withSwitch(new WithSTTImpedeUop(numEntries = entries))

  def setVP(vp: Valid[UInt], head: UInt, v: Option[Int], h: Int = 0): Unit = {
    vp.valid.poke(v.isDefined.B)
    vp.bits.poke(v.getOrElse(0).U)
    head.poke(h.U)
  }

  //-----------------------------------------------------------------------------
  // Issue slot

  def resetSlot(c: IssueSlotImpedeHarness): Unit = {
    c.io.in_uop.valid.poke(false.B)
    c.io.grant.poke(false.B)
    c.io.stt_block.poke(false.B)
    c.io.release.poke(0.U)
    setVP(c.io.vp, c.io.head, None)
    c.reset.poke(true.B)
    c.clock.step()
    c.reset.poke(false.B)
  }

  /** Write one operand-ready uop. `busy`/`idx` are the impede fields from dispatch and `yrot` the
   *  shadow tag (None = untainted). */
  def insert(c: IssueSlotImpedeHarness, busy: Boolean, idx: Int = 0, yrot: Option[Int] = None,
             transmitter: Boolean = true, isStore: Boolean = false, isBr: Boolean = false): Unit = {
    val u = c.io.in_uop.bits
    u.uopc.poke(if (isStore) uopSTA else if (isBr) uopBEQ else if (transmitter) uopLD else uopADD)
    u.iw_state.poke(if (isStore) s_valid_2 else s_valid_1)
    u.br_mask.poke(0.U)
    u.is_transmitter.get.poke(transmitter.B)
    u.impede_busy.get.poke(busy.B)
    u.impede_idx.get.poke(idx.U)
    u.yrot.get.valid.poke(yrot.isDefined.B)
    u.yrot.get.bits.poke(yrot.getOrElse(0).U)
    u.uses_ldq.poke((transmitter && !isStore && !isBr).B)
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
    u.prs2_busy.poke(false.B)
    u.prs3_busy.poke(false.B)
    u.ppred_busy.poke(false.B)
    u.iw_p1_poisoned.poke(false.B)
    u.iw_p2_poisoned.poke(false.B)
    c.io.in_uop.valid.poke(true.B)
    c.clock.step()
    c.io.in_uop.valid.poke(false.B)
  }

  def expectRequest(c: IssueSlotImpedeHarness, req: Boolean, msg: String): Unit = {
    c.io.valid.expect(true.B, msg)
    c.io.request.expect(req.B, msg)
    if (!req) c.io.request_hp.expect(false.B, msg)
  }

  describe("IssueSlot with impedeUop") {
    it("holds a transmitter until its entry releases, issues in that cycle, and stays released") {
      simulate(new IssueSlotImpedeHarness) { c =>
        resetSlot(c)
        insert(c, busy = true, idx = 1)
        expectRequest(c, false, "entry 1 not released")
        c.io.iss_busy.expect(true.B)
        c.clock.step(3)
        expectRequest(c, false, "still waiting")
        c.io.release.poke(2.U)
        expectRequest(c, true, "entry 1 releases this cycle")
        c.io.iss_busy.expect(false.B, "issued busy bit is the cleared one")
        c.io.out_busy.expect(false.B, "compaction carries the cleared bit")
        c.clock.step()
        c.io.release.poke(0.U)
        expectRequest(c, true, "release is final: the slot cleared its busy bit")
      }
    }

    it("ignores the release of another entry") {
      simulate(new IssueSlotImpedeHarness) { c =>
        resetSlot(c)
        insert(c, busy = true, idx = 0)
        c.io.release.poke(2.U)
        expectRequest(c, false, "entry 1 released, slot waits on entry 0")
        c.clock.step()
        c.io.release.poke(0.U)
        expectRequest(c, false, "still waiting on entry 0")
      }
    }

    it("does not read the shadow tag: a transmitter with no entry issues under an unsafe tag") {
      simulate(new IssueSlotImpedeHarness) { c =>
        resetSlot(c)
        setVP(c.io.vp, c.io.head, Some(2))
        insert(c, busy = false, yrot = Some(4))
        expectRequest(c, true, "no impede entry")
        c.io.iss_yrot.valid.expect(true.B, "shadow tag still held for the assertions")
      }
    }

    it("lets stt_block win over a release in the same cycle") {
      simulate(new IssueSlotImpedeHarness) { c =>
        resetSlot(c)
        insert(c, busy = true, idx = 0)
        c.io.stt_block.poke(true.B)
        c.io.release.poke(1.U)
        expectRequest(c, false, "recovery blocks the released transmitter")
        c.clock.step()
        c.io.release.poke(0.U)
        expectRequest(c, false, "recovery still on")
        c.io.stt_block.poke(false.B)
        expectRequest(c, true, "release was kept while blocked")
      }
    }

    it("holds both halves of a split store on one entry") {
      simulate(new IssueSlotImpedeHarness) { c =>
        resetSlot(c)
        insert(c, busy = true, idx = 0, isStore = true)
        expectRequest(c, false, "STA and STD wait on entry 0")
        c.io.release.poke(1.U)
        expectRequest(c, true, "entry 0 released")
      }
    }

    it("holds a branch on its entry, and lets an untainted branch issue with request_hp") {
      simulate(new IssueSlotImpedeHarness) { c =>
        resetSlot(c)
        insert(c, busy = true, idx = 0, isBr = true)
        expectRequest(c, false, "tainted branch")
        c.io.release.poke(1.U)
        expectRequest(c, true, "released")
        c.io.request_hp.expect(true.B)
      }
      simulate(new IssueSlotImpedeHarness) { c =>
        resetSlot(c)
        insert(c, busy = false, isBr = true)
        expectRequest(c, true, "untainted branch")
        c.io.request_hp.expect(true.B)
      }
    }

    it("does not delay a non-transmitter") {
      simulate(new IssueSlotImpedeHarness) { c =>
        resetSlot(c)
        insert(c, busy = false, transmitter = false, yrot = Some(4))
        c.io.stt_block.poke(true.B)
        expectRequest(c, true, "ALU op")
      }
    }
  }

  //-----------------------------------------------------------------------------
  // Impede table

  def resetTable(c: STTImpedeTableHarness): Unit = {
    c.io.lanes.foreach { l =>
      l.need.poke(false.B); l.fire.poke(false.B)
      l.yrot.valid.poke(false.B); l.yrot.bits.poke(0.U)
      l.br_mask.poke(0.U); l.rob_idx.poke(0.U)
    }
    c.io.resolve_mask.poke(0.U)
    c.io.mispredict_mask.poke(0.U)
    c.io.flush.poke(false.B)
    setVP(c.io.vp, c.io.head, None)
    c.reset.poke(true.B)
    c.clock.step()
    c.reset.poke(false.B)
  }

  /** Allocate one entry on lane 0 for a transmitter at `rob` with root `yrot`; returns its index. */
  def alloc(c: STTImpedeTableHarness, yrot: Int, rob: Int, brMask: Int = 0): Int = {
    val l = c.io.lanes(0)
    l.need.poke(true.B); l.fire.poke(true.B)
    l.yrot.valid.poke(true.B); l.yrot.bits.poke(yrot.U)
    l.br_mask.poke(brMask.U); l.rob_idx.poke(rob.U)
    c.io.full(0).expect(false.B, "a free entry")
    val i = c.io.idx(0).peek().litValue.toInt
    c.clock.step()
    l.need.poke(false.B); l.fire.poke(false.B)
    i
  }

  describe("STTImpedeTable") {
    it("releases an entry once the VP passes its root, never in the allocation cycle, then frees it") {
      simulate(new STTImpedeTableHarness) { c =>
        resetTable(c)
        // No unresolved branch: the tag is safe, but the entry is not valid until the next cycle.
        c.io.release.expect(0.U, "nothing allocated yet")
        val l = c.io.lanes(0)
        l.need.poke(true.B); l.fire.poke(true.B)
        l.yrot.valid.poke(true.B); l.yrot.bits.poke(3.U); l.rob_idx.poke(5.U)
        c.io.release.expect(0.U, "no release in the allocation cycle")
        val i = c.io.idx(0).peek().litValue.toInt
        setVP(c.io.vp, c.io.head, Some(3))
        c.clock.step()
        l.need.poke(false.B); l.fire.poke(false.B)
        c.io.release.expect(0.U, "root 3 equals the VP: unsafe")
        setVP(c.io.vp, c.io.head, Some(4))
        c.io.release.expect((BigInt(1) << i).U, "VP passed root 3")
        c.clock.step()
        c.io.release.expect(0.U, "a released entry is freed")
      }
    }

    it("reports full when every entry is taken, and frees an entry for reuse after its release") {
      simulate(new STTImpedeTableHarness) { c =>
        resetTable(c)
        setVP(c.io.vp, c.io.head, Some(1))
        val a = alloc(c, yrot = 2, rob = 6)
        val b = alloc(c, yrot = 3, rob = 7)
        assert(a != b, "two live entries share an index")
        c.io.lanes(0).need.poke(true.B)
        c.io.full(0).expect(true.B, s"all $entries entries are held")
        c.io.lanes(0).need.poke(false.B)
        c.io.full(0).expect(false.B, "no request, no hazard")
        setVP(c.io.vp, c.io.head, Some(3))
        c.io.release.expect((BigInt(1) << a).U, "only root 2 is older than the VP")
        c.clock.step()
        setVP(c.io.vp, c.io.head, Some(1))
        c.io.lanes(0).need.poke(true.B)
        c.io.full(0).expect(false.B, "entry freed")
        c.io.idx(0).expect(a.U, "the freed entry is reused")
      }
    }

    it("kills an entry with its branch and clears every entry on flush") {
      simulate(new STTImpedeTableHarness) { c =>
        resetTable(c)
        setVP(c.io.vp, c.io.head, Some(1))
        alloc(c, yrot = 2, rob = 6, brMask = 1)
        alloc(c, yrot = 3, rob = 7, brMask = 2)
        c.io.mispredict_mask.poke(1.U)
        c.clock.step()
        c.io.mispredict_mask.poke(0.U)
        c.io.lanes(0).need.poke(true.B)
        c.io.full(0).expect(false.B, "the killed entry is free")
        c.io.lanes(0).need.poke(false.B)
        alloc(c, yrot = 4, rob = 8)
        c.io.lanes(0).need.poke(true.B)
        c.io.full(0).expect(true.B, "full again")
        c.io.lanes(0).need.poke(false.B)
        c.io.flush.poke(true.B)
        c.clock.step()
        c.io.flush.poke(false.B)
        setVP(c.io.vp, c.io.head, None)
        c.io.release.expect(0.U, "flushed entries do not release")
        c.io.lanes(0).need.poke(true.B)
        c.io.full(0).expect(false.B, "flush freed every entry")
      }
    }

    it("keeps a resolved branch bit from killing an entry") {
      simulate(new STTImpedeTableHarness) { c =>
        resetTable(c)
        setVP(c.io.vp, c.io.head, Some(1))
        val a = alloc(c, yrot = 2, rob = 6, brMask = 1)
        c.io.resolve_mask.poke(1.U)
        c.clock.step()
        c.io.resolve_mask.poke(0.U)
        c.io.mispredict_mask.poke(1.U) // a new branch reusing tag 0
        c.clock.step()
        c.io.mispredict_mask.poke(0.U)
        setVP(c.io.vp, c.io.head, Some(3))
        c.io.release.expect((BigInt(1) << a).U, "entry survived the reused tag")
      }
    }
  }

  it("IssueSlot has an impede release port only with impedeUop") {
    def ports(mixin: Parameters): Boolean = {
      implicit val p: Parameters = ConservativeSlotParams.withSwitch(mixin)
      var has = false
      circt.stage.ChiselStage.emitCHIRRTL(new Module {
        val s = Module(new IssueSlot(numWakeupPorts = 1))
        has = s.io.impede_release.isDefined
        s.io := DontCare
      })
      has
    }
    assert(ports(new WithSTTImpedeUop(numEntries = 2)))
    assert(!ports(new WithSTT))
    assert(!ports(Parameters.empty))
  }
}
