#!/bin/sh
# kernels/src/build.sh -- rebuild every kernel in kernels/ from source and compare with kernels/SHA256SUMS;
# build the pending images (not in the kit) and compare with kernels/pending/SHA256SUMS; run the
# packer's negative controls.
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
#   alu.s2          integer and float ALU probe (pending: not in the kit)
#   ctl.s2          divergent loop, if/else, warp reduction, atomic (pending: not in the kit)
#   cubin.om        wraps asm2 machine code in a cubin: container v7 (CUDA 12 style) or v8 (CUDA 13)
# cubin.om is the ck/cubin-om version (omega-mv draft #864, 76639738a) plus the scoreboard check
# (exit 7); alu.s2 and ctl.s2 are the same branch's listings with the scoreboard fix. None of them is
# in omega-mv main yet, so cubin.om's sha256 is pinned below until it lands there.
# Exit 0 when the six kit cubins equal kernels/SHA256SUMS, the pending cubins equal
# kernels/pending/SHA256SUMS and every negative control is refused; 1 otherwise. Runs on aarch64 Linux
# only (CI: GitHub's ubuntu-24.04-arm). The script is coordination only; every byte comes from Omega
# tools.
set -eu
MV=${1:?usage: kernels/src/build.sh OMEGA_MV_CHECKOUT [OUT_DIR]}
SRC=$(cd "$(dirname "$0")" && pwd)
KER=$(dirname "$SRC")
OUT=${2:-$(mktemp -d)}
mkdir -p "$OUT/pending" "$OUT/negative"
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
pin "$SRC/cubin.om"           e40ea98d40533512b91297711963743db4d44d83edd014d703fc1f4dcf9dde50

"$MV/seed/out/omc" < "$SRC/cubin.om" > "$OUT/cubin"
chmod +x "$OUT/cubin"
asm() {  # asm LISTING OUT.bin
  cat "$MV/seed/sm80/sm80.tbl" "$1" | "$MV/seed/rung2/asm2.bin" > "$2"
}

# The kit: container v7, API 128, params pppu. REGS 14 (the cubin records 16, as the published kit
# always did; vecadd needs 10).
for k in vecadd neg; do
  asm "$SRC/$k.cuda.s2" "$OUT/$k.bin"
  for sm in 80 86 89; do
    "$OUT/cubin" $sm 7 128 14 $k pppu < "$OUT/$k.bin" > "$OUT/${k}_sm${sm}_v7.cubin"
  done
done
(cd "$OUT" && sha256sum *_v7.cubin) > "$OUT/SHA256SUMS"
if cmp -s "$OUT/SHA256SUMS" "$KER/SHA256SUMS"; then
  echo "PASS: 6 cubins rebuilt from source are byte-identical to kernels/SHA256SUMS"
else
  echo "FAIL: rebuilt cubins differ from kernels/SHA256SUMS"; diff "$KER/SHA256SUMS" "$OUT/SHA256SUMS" || true
  fail=1
fi

# Pending images: every kernel in containers v7 (API 128) and v8 (API 130) for sm_80, sm_86 and
# sm_89. REGS is the highest register a listing names plus 1 (alu R15, ctl R14, vecadd/neg R9 + the
# kit's 14). They wait for a chip run on each architecture before any joins the kit.
asm "$SRC/alu.s2" "$OUT/alu.bin"
asm "$SRC/ctl.s2" "$OUT/ctl.bin"
for k in vecadd:14 neg:14 alu:16 ctl:15; do
  n=${k%:*}; r=${k#*:}
  for sm in 80 86 89; do
    "$OUT/cubin" $sm 7 128 $r $n pppu < "$OUT/$n.bin" > "$OUT/pending/${n}_sm${sm}_v7.cubin"
    "$OUT/cubin" $sm 8 130 $r $n pppu < "$OUT/$n.bin" > "$OUT/pending/${n}_sm${sm}_v8.cubin"
  done
done
(cd "$OUT/pending" && sha256sum *.cubin) > "$OUT/pending/SHA256SUMS"
if cmp -s "$OUT/pending/SHA256SUMS" "$KER/pending/SHA256SUMS"; then
  echo "PASS: 24 pending cubins rebuilt from source are byte-identical to kernels/pending/SHA256SUMS"
else
  echo "FAIL: pending cubins differ from kernels/pending/SHA256SUMS"
  diff "$KER/pending/SHA256SUMS" "$OUT/pending/SHA256SUMS" || true
  fail=1
fi

# Negative controls: the packer must refuse each of these with the named exit code.
refuse() {  # refuse WANT LABEL BIN ARGS...
  want=$1 label=$2 bin=$3; shift 3
  rc=0; "$OUT/cubin" "$@" < "$bin" > "$OUT/negative/out.cubin" || rc=$?
  if [ $rc -eq "$want" ]; then echo "PASS: refused ($label, exit $rc)"; else echo "FAIL: $label gave exit $rc, want $want"; fail=1; fi
}
# alu/ctl as they ran on the RTX 4090: instructions 4 and 10 stall 1 cycle before a wait.
for k in alu ctl; do
  awk '/^;  4 ULDC UR5/ || /^; 10 LDC.64 R6/ { m = 1 } m && /^  c 2 1 / { sub(/^  c 2 1 /, "  c 1 1 "); m = 0 } { print }' \
    "$SRC/$k.s2" > "$OUT/negative/$k.stall1.s2"
  asm "$OUT/negative/$k.stall1.s2" "$OUT/negative/$k.stall1.bin"
  refuse 7 "$k scoreboard waited 1 cycle after it was set" "$OUT/negative/$k.stall1.bin" 89 7 128 16 $k pppu
done
# alu writes R15: REGS 15 leaves it outside the allocation (the original 715 ILLEGAL_INSTRUCTION).
refuse 6 "alu REGS 15 below R15" "$OUT/alu.bin" 89 7 128 15 alu pppu
exit $fail
