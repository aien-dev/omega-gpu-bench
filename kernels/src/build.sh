#!/bin/sh
# kernels/src/build.sh -- rebuild every kernel in kernels/ from source and compare with kernels/SHA256SUMS.
#
#   kernels/src/build.sh OMEGA_MV_CHECKOUT [OUT_DIR]
#
# OMEGA_MV_CHECKOUT is a clone of github.com/aien-dev/omega-mv at commit 7ca3f989 (branch
# seed/sm80-ampere). It supplies the three pinned Omega tools, each checked by sha256 before use:
#   seed/out/omc       Omega's seed compiler (aarch64 Linux); compiles cubin.om
#   seed/rung2/asm2.bin  Omega's table-driven SASS assembler (rung 2)
#   seed/sm80/sm80.tbl   the Ampere/Ada instruction table, checked against Mesa NAK's encoder
# The kernel sources and the cubin writer are in this directory:
#   vecadd.cuda.s2  c[i] = a[i] + b[i], hand-written for asm2 with the CUDA kernel-parameter ABI
#   neg.cuda.s2     the same with one operand changed (R4 for R5): the run's negative control
#   cubin.om        wraps asm2 machine code in a cubin (CUDA 12 style container, "v7")
# vecadd.cuda.s2 and cubin.om are copies of files in the CudaArch lane's omega-mv worktree that are not
# yet committed to omega-mv; their sha256 are pinned below until they land there.
# Exit 0 when all six rebuilt cubins equal kernels/SHA256SUMS, 1 otherwise. Runs on aarch64 Linux only
# (CI: GitHub's ubuntu-24.04-arm). The script is coordination only; every byte comes from Omega tools.
set -eu
MV=${1:?usage: kernels/src/build.sh OMEGA_MV_CHECKOUT [OUT_DIR]}
SRC=$(cd "$(dirname "$0")" && pwd)
KER=$(dirname "$SRC")
OUT=${2:-$(mktemp -d)}
mkdir -p "$OUT"
fail=0
pin() {  # pin FILE SHA256
  got=$(sha256sum "$1" | cut -d' ' -f1)
  if [ "$got" = "$2" ]; then echo "pin ok   $1"; else echo "PIN FAIL $1: $got, want $2"; exit 1; fi
}
[ "$(git -C "$MV" rev-parse HEAD)" = 7ca3f989cbd62e77de1dd7d23919edd083fd2113 ] \
  || { echo "omega-mv checkout is not at 7ca3f989"; exit 1; }
pin "$MV/seed/out/omc"       2c82480596bbdc50cda9626866209ef662d5834f278f839ff4ce0250c495029f
pin "$MV/seed/rung2/asm2.bin" 6988abe072fac3cdef2240d5ad13a3ecd8fb576fa09112d344b9e7c2315969c4
pin "$MV/seed/sm80/sm80.tbl"  c77a731d07498fbd16410a2be385adfacb0fe0e3b11000cf3126bf882115670f
pin "$SRC/cubin.om"           8f2c7f5d56410233f162479b300c91fb30b19183bf4f89400efa5d00255289e9

"$MV/seed/out/omc" < "$SRC/cubin.om" > "$OUT/cubin"
chmod +x "$OUT/cubin"
for k in vecadd neg; do
  cat "$MV/seed/sm80/sm80.tbl" "$SRC/$k.cuda.s2" | "$MV/seed/rung2/asm2.bin" > "$OUT/$k.bin"
  for sm in 80 86 89; do
    # cubin SM ABI API REGS NAME SIG: container v7 (CUDA 12 style), API 128, 16 registers, params pppu
    "$OUT/cubin" $sm 7 128 16 $k pppu < "$OUT/$k.bin" > "$OUT/${k}_sm${sm}_v7.cubin"
  done
done
(cd "$OUT" && sha256sum *_v7.cubin) > "$OUT/SHA256SUMS"
if cmp -s "$OUT/SHA256SUMS" "$KER/SHA256SUMS"; then
  echo "PASS: 6 cubins rebuilt from source are byte-identical to kernels/SHA256SUMS"
else
  echo "FAIL: rebuilt cubins differ from kernels/SHA256SUMS"; diff "$KER/SHA256SUMS" "$OUT/SHA256SUMS" || true
  fail=1
fi
exit $fail
