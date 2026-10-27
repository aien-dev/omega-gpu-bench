#!/bin/sh
# kernels/src/oracle.sh -- offline checks of cubins against NVIDIA's own read-only tools, no GPU.
#
#   kernels/src/oracle.sh CUBIN...
#
# Each CUBIN must be named NAME_smSS_vA.cubin (SS 80, 86 or 89; A 7 or 8). For each one:
#   hdr   ELF identification and e_flags. Container v7: EI_OSABI 0x33 (ELFOSABI_CUDA = 51),
#         EI_ABIVERSION 7, e_flags SM | 0x500 | SM << 16 (EF_CUDA_SM*, EF_CUDA_TEXMODE_UNIFIED 0x100,
#         EF_CUDA_64BIT_ADDRESS 0x400, EF_CUDA_VIRTUAL_SM 0xff0000): LLVM's BinaryFormat/ELF.h.
#         Container v8: EI_OSABI 0x41, EI_ABIVERSION 8, e_flags 0x6000000 | SM << 8 | 0x4. LLVM main
#         (930a3d47) names ELFABIVERSION_CUDA_V2 = 8 and EF_CUDA_SM_OFFSET = 8 but not the other bits,
#         and declares ELFOSABI_CUDA_V2 = 41 in decimal; the byte nvcc 13.0 writes is 0x41, and that
#         is the byte the RTX 4090 run RTX_4090-002933 loaded. The v8 values are pinned from those
#         observations, not from a specification.
#   tkinfo  v8 has a .note.nv.tkinfo section, v7 has none. A v8 cubin without it is refused by the
#         driver with CUDA_ERROR_INVALID_IMAGE (RTX_4090-002933 vecadd_sm89_v8dNoTk, RTX_5090-005123).
#   decode  nvdisasm decodes the whole .text without an error.
#   regs  the register count the driver allocates (cuobjdump -res-usage REG) is at least the highest
#         general register the code touches (a .64 operand or a .WIDE/.64 destination counts its
#         pair) plus 3: the 2 Volta+ hardware keeps, plus one because registers count from R0.
#         alu/ctl with REG 16 writing R14/R15 raised CUDA_ERROR_ILLEGAL_INSTRUCTION (715).
#   sb    every scoreboard (0..5) set by an instruction is first waited on at least 2 issue cycles
#         later, counting stall cycles in program order (Mesa NAK calc_instr_deps.rs: `bars[bar] + 2`).
#         alu waiting 1 cycle after LDC.64 R6 read a stale R6 on an RTX 4090.
# Prints one line per check, PASS or FAIL, and exits 0 when all pass, 1 when any fails, 2 when the
# tools are missing (every check NOT_RUN). nvdisasm, cuobjdump (CUDA toolkit) and readelf (binutils)
# are read-only oracles here: they only read cubins this repository built; nothing they print goes
# into a kernel. INTERIM host glue (sh, awk); successor: an Omega cubin reader with the same checks.
set -u
CUDA=${CUDA_HOME:-/usr/local/cuda}
ND=$(command -v nvdisasm || echo "$CUDA/bin/nvdisasm")
CO=$(command -v cuobjdump || echo "$CUDA/bin/cuobjdump")
RE=$(command -v readelf || echo readelf)
for t in "$ND" "$CO" "$RE"; do
  if ! command -v "$t" > /dev/null 2>&1; then
    echo "NOT_RUN: $t not found (needs nvdisasm and cuobjdump from a CUDA toolkit, and readelf)"; exit 2
  fi
done
echo "oracle: $("$ND" --version | tail -n 1); $("$RE" --version | head -n 1)"
fail=0
say() {  # say CHECK FILE OK DETAIL
  if [ "$3" = 1 ]; then echo "PASS  $1  $2  $4"; else echo "FAIL  $1  $2  $4"; fail=1; fi
}
byte() {  # byte FILE OFFSET COUNT -> little-endian unsigned value
  od -A n -t u1 -j "$2" -N "$3" "$1" | awk '{ for (i = NF; i >= 1; i--) v = v * 256 + $i } END { print v }'
}
for f in "$@"; do
  b=$(basename "$f" .cubin)
  sm=$(echo "$b" | sed -n 's/.*_sm\([0-9][0-9]*\)_v\([78]\)[A-Za-z0-9]*$/\1/p')
  abi=$(echo "$b" | sed -n 's/.*_sm\([0-9][0-9]*\)_v\([78]\)[A-Za-z0-9]*$/\2/p')
  if [ -z "$sm" ] || [ -z "$abi" ]; then echo "FAIL  name  $f  not NAME_smSS_vA.cubin"; fail=1; continue; fi
  osabi=$(byte "$f" 7 1) abiv=$(byte "$f" 8 1) flags=$(byte "$f" 48 4)
  if [ "$abi" = 7 ]; then wo=51 wf=$((sm | 0x500 | sm << 16)); else wo=65 wf=$((0x6000000 | sm << 8 | 4)); fi
  ok=0; [ "$osabi" = "$wo" ] && [ "$abiv" = "$abi" ] && [ "$flags" = "$wf" ] && ok=1
  say hdr "$b" $ok "$(printf 'OSABI 0x%x ABIVERSION %d e_flags 0x%x, want 0x%x %d 0x%x' "$osabi" "$abiv" "$flags" "$wo" "$abi" "$wf")"
  # 2>/dev/null: readelf warns that .text's sh_info holds the register count in its top byte
  n=$("$RE" -S -W "$f" 2>/dev/null | grep -c '\.note\.nv\.tkinfo')
  if [ "$abi" = 8 ]; then ok=0; [ "$n" -ge 1 ] && ok=1; else ok=0; [ "$n" -eq 0 ] && ok=1; fi
  say tkinfo "$b" $ok ".note.nv.tkinfo sections: $n"
  dis=$("$ND" -hex -c "$f" 2>&1); rc=$?
  ok=0; [ $rc -eq 0 ] && ! echo "$dis" | grep -qi 'error' && ok=1
  say decode "$b" $ok "nvdisasm exit $rc"
  reg=$("$CO" -res-usage "$f" 2>/dev/null | sed -n 's/.*REG:\([0-9][0-9]*\).*/\1/p' | head -n 1)
  top=$(echo "$dis" | awk '
    /\/\*[0-9a-f]+\*\// {
      s = $0; sub(/^.*\/\*[0-9a-f]+\*\/[ \t]*/, "", s); sub(/;.*/, "", s)
      sub(/^@!?U?P[0-9T][ \t]+/, "", s)
      op = s; sub(/[ \t].*/, "", op); rest = s; sub(/^[^ \t]+[ \t]*/, "", rest)
      first = 1; t = rest
      while (match(t, /(^|[^A-Z_])R[0-9]+(\.64)?/)) {
        r = substr(t, RSTART, RLENGTH); t = substr(t, RSTART + RLENGTH)
        sub(/^[^R]*R/, "", r); w = (r ~ /\.64$/); sub(/\.64$/, "", r); r = r + 0
        if (first && (op ~ /\.64/ || op ~ /\.WIDE/)) w = 1
        if (op ~ /\.128/ && first) r = r + 3; else if (w) r = r + 1
        if (r > m && r != 255) m = r
        first = 0
      }
    }
    END { print m + 0 }')
  ok=0; [ -n "$reg" ] && [ "$reg" -ge $((top + 3)) ] && ok=1
  say regs "$b" $ok "REG ${reg:-?}, highest register R$top, want at least $((top + 3))"
  sbr=$(echo "$dis" | awk '
    function hex(s,   i, v) { v = 0; for (i = 1; i <= length(s); i++) v = v * 16 + index("0123456789abcdef", substr(s, i, 1)) - 1; return v }
    /\/\*[0-9a-f]+\*\// { pc = $0; sub(/^[^\/]*\/\*/, "", pc); sub(/\*\/.*/, "", pc); want = 1; next }
    want && /^[ \t]*\/\* 0x[0-9a-f]+ \*\// {
      h = $0; sub(/^[ \t]*\/\* 0x/, "", h); sub(/ .*/, "", h)
      c = hex(substr(h, 1, 6)); n++
      P[n] = pc; S[n] = int(c / 2) % 16; WB[n] = int(c / 64) % 8; RB[n] = int(c / 512) % 8; WT[n] = int(c / 4096) % 64
      want = 0
    }
    END {
      min = 99; bad = 0
      for (i = 1; i <= n; i++) for (k = 0; k < 2; k++) {
        bar = k ? RB[i] : WB[i]; if (bar > 5) continue
        acc = 0
        for (j = i + 1; j <= n; j++) {
          acc += S[j - 1]
          if (int(WT[j] / 2 ^ bar) % 2) { if (acc < min) min = acc; if (acc < 2) { bad++; where = where " " P[i] "->" P[j] } ; break }
        }
      }
      printf "%d %d %d%s\n", n, min, bad, where
    }')
  n=${sbr%% *}; r=${sbr#* }; mn=${r%% *}; r=${r#* }; nb=${r%% *}; wh=${r#"$nb"}
  ok=0; [ "$n" -gt 0 ] && [ "$nb" -eq 0 ] && ok=1
  say sb "$b" $ok "$n instructions, shortest set-to-wait $mn cycles, $nb shorter than 2${wh:+:$wh}"
done
exit $fail
