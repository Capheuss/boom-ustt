#!/usr/bin/env bash
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo"
output="$repo/logs/d3-rename-sweep-01"
if [[ -e "$output" ]]; then
    echo "Output already exists: $output" >&2
    exit 1
fi
mkdir -p "$output"
printf 'config\tstage\tstatus\n' > "$output/status.tsv"

while read -r config decode phy rob; do
    work="$output/$config"
    source_dir="$repo/reference/uSTT/rtl/src"
    if [[ "$config" == small ]]; then
        source_dir="$repo/logs/d3-small-og-init-src-01"
    fi
    echo "Starting rename-only $config: decode=$decode phy=$phy"

    if [[ "$config" == medium ]]; then
        if ! grep -Fq 'PASS: 100/100 reference test cases.' \
            logs/d3-rename-medium-xsim.log; then
            printf '%s\txsim\tFAIL\n' "$config" >> "$output/status.tsv"
            continue
        fi
        printf '%s\txsim\tPASS-reused\n' "$config" >> "$output/status.tsv"
    else
        if ./ustt python3 scripts/ustt-rtl/prepare-test.py \
            --top rename --decode "$decode" --phy "$phy" \
            --output "$work-test" > "$work-prepare.log" 2>&1; then
            printf '%s\tprepare\tPASS\n' "$config" >> "$output/status.tsv"
        else
            printf '%s\tprepare\tFAIL\n' "$config" >> "$output/status.tsv"
            continue
        fi
        if env USTT_RTL_SRC="$source_dir" ./ustt --vivado bash \
            scripts/ustt-rtl/run-xsim.sh "$work-test" > "$work-xsim.log" 2>&1; then
            printf '%s\txsim\tPASS\n' "$config" >> "$output/status.tsv"
        else
            printf '%s\txsim\tFAIL\n' "$config" >> "$output/status.tsv"
            continue
        fi
    fi

    if /usr/bin/time -v ./ustt --vivado vivado \
        -mode batch -nojournal -log "$work-vivado.log" \
        -source scripts/ustt-rtl/synth.tcl \
        -tclargs rename "$decode" "$phy" "$rob" "$source_dir" "$work-synth" \
        > "$work-synth.log" 2>&1; then
        printf '%s\tsynthesis\tPASS\n' "$config" >> "$output/status.tsv"
    else
        printf '%s\tsynthesis\tFAIL\n' "$config" >> "$output/status.tsv"
    fi
done <<'CONFIGS'
small 1 52 32
medium 2 80 64
large 3 100 96
mega 4 128 128
giga 5 128 130
reference-8wide 8 380 512
CONFIGS

echo "Rename sweep finished. Inspect status.tsv and timing reports."
