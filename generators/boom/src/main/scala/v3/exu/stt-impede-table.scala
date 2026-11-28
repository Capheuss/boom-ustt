//------------------------------------------------------------------------------
// [boom-ustt] #8 impede table (project-docs/impede-uop.md section 4).
//
// A transmitter whose YRoT is valid at dispatch gets one entry here. Its issue
// slot holds only a busy bit and the entry index; the entry holds the tag and is
// the only place its age is compared against the VP. Once the tag is safe the
// entry broadcasts a release bit and frees itself. A safe tag never becomes
// unsafe again, so a release is final.
//------------------------------------------------------------------------------

package boom.v3.exu

import chisel3._
import chisel3.util._

import org.chipsalliance.cde.config.Parameters

import boom.v3.common._
import boom.v3.util._

class STTImpedeLane(implicit p: Parameters) extends BoomBundle
{
  val need    = Bool() // a valid, tainted transmitter that enters an issue queue
  val fire    = Bool() // the lane dispatches this cycle
  val yrot    = Valid(UInt(robAddrSz.W))
  val br_mask = UInt(maxBrCount.W)
  val rob_idx = UInt(robAddrSz.W)
}

class STTImpedeTable(implicit p: Parameters) extends BoomModule
{
  val io = IO(new Bundle {
    val lanes    = Input(Vec(coreWidth, new STTImpedeLane))
    // Lane w needs an entry and none is left after the older lanes take theirs.
    val full     = Output(Vec(coreWidth, Bool()))
    // The entry lane w gets when it needs one and fires.
    val idx      = Output(Vec(coreWidth, UInt(impedeIdxSz.W)))
    // Bit i: entry i's tag is safe this cycle. Its waiters may issue now.
    val release  = Output(UInt(numImpedeEntries.W))

    val vp       = Input(Valid(UInt(robAddrSz.W)))
    val head     = Input(UInt(robAddrSz.W))
    val brupdate = Input(new BrUpdateInfo)
    val flush    = Input(Bool()) // same cycle as the issue-queue kill
  })

  class Entry extends Bundle {
    val yrot    = UInt(robAddrSz.W)
    val br_mask = UInt(maxBrCount.W)
    val rob_idx = UInt(robAddrSz.W) // the transmitter; for the lifetime check only
  }

  val valid   = RegInit(VecInit(Seq.fill(numImpedeEntries)(false.B)))
  val entries = Reg(Vec(numImpedeEntries, new Entry))

  // Release: N age compares against the VP, instead of one per issue slot. An entry
  // is valid from the cycle after dispatch, when an older branch in the same dispatch
  // group is already part of the VP.
  val release = VecInit((0 until numImpedeEntries).map { i =>
    val tag = Wire(Valid(UInt(robAddrSz.W)))
    tag.valid := true.B
    tag.bits  := entries(i).yrot
    valid(i) && STTIsSafe(tag, io.vp, io.head)
  })
  io.release := release.asUInt

  // Allocation: lane w takes the lowest entry left free by the older lanes. A lane
  // that cannot get one is a dispatch hazard, so it and the lanes behind it wait.
  val free = valid.map(!_)
  var avail = VecInit(free).asUInt
  for (w <- 0 until coreWidth) {
    val lane = io.lanes(w)
    val pick = PriorityEncoderOH(avail)
    io.full(w) := lane.need && !avail.orR
    io.idx(w)  := OHToUInt(pick)
    avail = avail & ~Mux(lane.need, pick, 0.U)
  }

  for (i <- 0 until numImpedeEntries) {
    val killed = IsKilledByBranch(io.brupdate, entries(i).br_mask)
    when (valid(i)) {
      entries(i).br_mask := GetNewBrMask(io.brupdate, entries(i).br_mask)
    }
    when (release(i) || killed) {
      valid(i) := false.B
    }
  }

  for (w <- 0 until coreWidth) {
    val lane = io.lanes(w)
    when (lane.need && lane.fire) {
      val i = io.idx(w)
      valid(i)           := true.B
      entries(i).yrot    := lane.yrot.bits
      entries(i).br_mask := GetNewBrMask(io.brupdate, lane.br_mask)
      entries(i).rob_idx := lane.rob_idx
    }
  }

  when (io.flush) {
    valid.foreach(_ := false.B)
  }

  //-------------------------------------------------------------
  // Checks

  for (w <- 0 until coreWidth) {
    val lane = io.lanes(w)
    assert(!(lane.need && !lane.yrot.valid), "[boom-ustt] impede table: entry requested for an untainted uop")
    assert(!(lane.need && lane.fire && io.full(w)), "[boom-ustt] impede table: lane dispatched without an entry")
    for (v <- 0 until w) {
      assert(!(lane.need && lane.fire && io.lanes(v).need && io.lanes(v).fire && io.idx(w) === io.idx(v)),
        "[boom-ustt] impede table: two lanes allocated the same entry")
    }
  }
  for (i <- 0 until numImpedeEntries) {
    val tag = Wire(Valid(UInt(robAddrSz.W)))
    tag.valid := valid(i)
    tag.bits  := entries(i).yrot
    STTAssertLive(valid(i), tag, entries(i).rob_idx, io.head, s"impede table entry $i")
  }

  // Trace, with the same switch as the issue queues (+stt_trace=1).
  val stt_trace = freechips.rocketchip.util.PlusArg("stt_trace", width = 1,
    docstring = "Print STT hold and issue events from the issue queues")
  val stt_cycle = RegInit(0.U(64.W))
  stt_cycle := stt_cycle + 1.U
  for (w <- 0 until coreWidth) {
    val lane = io.lanes(w)
    when (stt_trace(0) && lane.need && lane.fire) {
      printf("[stt-trace] cycle=%d impede alloc idx=%d rob=%d yrot=%d\n",
        stt_cycle, io.idx(w), lane.rob_idx, lane.yrot.bits)
    }
  }
  for (i <- 0 until numImpedeEntries) {
    when (stt_trace(0) && release(i)) {
      printf("[stt-trace] cycle=%d impede release idx=%d rob=%d yrot=%d vp=%d:%d\n",
        stt_cycle, i.U, entries(i).rob_idx, entries(i).yrot, io.vp.valid, io.vp.bits)
    }
  }
}
