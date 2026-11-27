package boom.v3.exu

import java.nio.charset.StandardCharsets
import java.nio.file.{Files, Paths}
import chisel3.util.log2Ceil
import circt.stage.ChiselStage

object EmitSTTTaintTable {
  def main(args: Array[String]): Unit = {
    require(args.length == 3, "Usage: PROFILE MODE OUTPUT_DIR")
    val profile = args(0)
    val mode = args(1)
    require(mode == "bypass" || mode == "age")
    val (width, intPregs, fpPregs, robEntries) = profile match {
      case "medium" => (2, 80, 64, 64)
      case "mega" => (4, 128, 128, 128)
      case _ => throw new IllegalArgumentException("Unknown profile: " + profile)
    }
    val pregBits = log2Ceil(intPregs) max log2Ceil(fpPregs)
    val robBits = log2Ceil(robEntries / width) + log2Ceil(width)
    val output = Paths.get(args(2))
    require(!Files.exists(output), "Output directory already exists")
    Files.createDirectories(output)

    val rtl = ChiselStage.emitSystemVerilog(
      new STTTaintTable(
        plWidth = width,
        numIntPregs = intPregs,
        numFpPregs = fpPregs,
        lregSz = 5,
        pregSz = pregBits,
        robAddrSz = robBits,
        ageMatrix = mode == "age",
        debugTables = false
      )
    )
    Files.write(output.resolve("STTTaintTable.sv"),
      rtl.getBytes(StandardCharsets.UTF_8))
    val record = s"profile=$profile mode=$mode width=$width int_pregs=$intPregs fp_pregs=$fpPregs lreg_bits=5 preg_bits=$pregBits rob_bits=$robBits debug_tables=false\n"
    Files.write(output.resolve("parameters.txt"),
      record.getBytes(StandardCharsets.UTF_8))
    println("STT_RTL_GENERATION_COMPLETE: " + output.toAbsolutePath)
  }
}
