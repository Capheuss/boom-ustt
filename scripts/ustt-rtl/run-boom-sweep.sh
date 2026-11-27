#!/usr/bin/env bash
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo"

output="$repo/logs/d3-boom-sweep-01"
if [[ -e "$output" ]]; then
    echo "Output already exists: $output" >&2
    exit 1
fi
mkdir -p "$output"
printf 'config\tvariant\tstage\tstatus\n' > "$output/status.tsv"

while read -r config decode phy rob; do
    for variant in og age; do
        top="stt_$variant"
        if [[ "$variant" == og ]]; then
            source_dir="$repo/logs/d3-reference-copies-01/og-bounded"
        else
            source_dir="$repo/logs/d3-reference-copies-01/age-width"
        fi
        name="$config-$variant"
        work="$output/$name"
        echo "Starting $name: decode=$decode phy=$phy rob=$rob"

        if ./ustt python3 scripts/ustt-rtl/prepare-test.py \
            --top "$top" --decode "$decode" --phy "$phy" --rob "$rob" \
            --output "$work-test" > "$work-prepare.log" 2>&1; then
            printf '%s\t%s\tprepare\tPASS\n' "$config" "$variant" >> "$output/status.tsv"
        else
            printf '%s\t%s\tprepare\tFAIL\n' "$config" "$variant" >> "$output/status.tsv"
            continue
        fi

        if env USTT_RTL_SRC="$source_dir" ./ustt --vivado bash \
            scripts/ustt-rtl/run-xsim.sh "$work-test" > "$work-xsim.log" 2>&1; then
            printf '%s\t%s\txsim\tPASS\n' "$config" "$variant" >> "$output/status.tsv"
        else
            printf '%s\t%s\txsim\tFAIL\n' "$config" "$variant" >> "$output/status.tsv"
            continue
        fi

        if /usr/bin/time -v ./ustt --vivado vivado \
            -mode batch -nojournal -log "$work-vivado.log" \
            -source scripts/ustt-rtl/synth.tcl \
            -tclargs "$top" "$decode" "$phy" "$rob" "$source_dir" "$work-synth" \
            > "$work-synth.log" 2>&1; then
            printf '%s\t%s\tsynthesis\tPASS\n' "$config" "$variant" >> "$output/status.tsv"
        else
            printf '%s\t%s\tsynthesis\tFAIL\n' "$config" "$variant" >> "$output/status.tsv"
        fi
    done
done <<'CONFIGS'
small 1 52 32
large 3 100 96
mega 4 128 128
giga 5 128 130
CONFIGS

echo "Sweep finished. Inspect $output/status.tsv and all generated reports."
