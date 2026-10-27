#!/bin/sh
# tests/run.sh -- kit and validator tests, no GPU needed. Run from a clean git checkout:  sh tests/run.sh
# The fixture tests/fakecuda.py stands in for libcuda; its receipts say driver "fake" and the validator
# rejects them unless --allow-fake is given. Every check below is paired with a case that must fail.
# INTERIM host glue (sh); successor: an Omega test driver once omc-built tools replace kit/*.py.
set -u
cd "$(dirname "$0")/.." || exit 1
ROOT=$(pwd)
T=$(mktemp -d)
pass=0 fail=0
ok() { pass=$((pass + 1)); echo "ok    $1"; }
bad() { fail=$((fail + 1)); echo "FAIL  $1"; }
expect() {  # expect NAME WANT_EXIT GOT_EXIT
  if [ "$3" -eq "$2" ]; then ok "$1 (exit $3)"; else bad "$1: exit $3, want $2"; fi
}
SIGN="CI Test <ci@example.invalid>"
FAKE="$ROOT/tests/fakecuda.py"
V="python3 tools/validate.py"

[ -z "$(git status --porcelain)" ] || echo "note: the checkout has local changes; kit runs will say modified=true"

# 1. the receipts in the repository are valid
if ls receipts/*.json > /dev/null 2>&1; then
  $V receipts/*.json > "$T/repo.txt"; expect "repository receipts validate" 0 $?
fi

# 2. a full kit run against the fixture driver (cc 8.9 loads sm_80, sm_86 and sm_89 builds: 6 kernels)
OGB_FAKE_DRIVER=$FAKE ./run --sign-off "$SIGN" --out "$T/ok" > "$T/ok.txt" 2>&1
expect "fake run, all kernels correct" 0 $?
K=$(ls "$T"/ok/*.json 2>/dev/null | head -n 1)
if [ -n "$K" ]; then
  $V --allow-fake "$K" > /dev/null; expect "fake receipt valid with --allow-fake" 0 $?
  $V "$K" > "$T/nofake.txt"; expect "fake receipt rejected without --allow-fake" 1 $?
  grep -q "test fixture driver" "$T/nofake.txt" && ok "reason: fixture driver" || bad "reason: fixture driver"
  n=$(python3 -c "import json,sys;print(len(json.load(open(sys.argv[1]))['results']))" "$K")
  [ "$n" = 6 ] && ok "cc 8.9 ran 6 kernels" || bad "cc 8.9 ran $n kernels, want 6"
else
  bad "fake run wrote no receipt"; cat "$T/ok.txt"
fi

# 3. a GPU that computes wrong answers: exit 1, an honest WRONG receipt that still validates
OGB_FAKE_DRIVER=$FAKE OGB_FAKE_MODE=wrong ./run --sign-off "$SIGN" --out "$T/wrong" > "$T/wrong.txt" 2>&1
expect "fake wrong-answer GPU" 1 $?
W=$(ls "$T"/wrong/*.json 2>/dev/null | head -n 1)
if [ -n "$W" ] && grep -q '"WRONG"' "$W"; then ok "receipt says WRONG"; else bad "receipt says WRONG"; fi
[ -n "$W" ] && { $V --allow-fake "$W" > /dev/null; expect "WRONG receipt validates" 0 $?; }

# 4. a card with no kernel in this kit (cc 9.0): exit 1, receipt with not_run
OGB_FAKE_DRIVER=$FAKE OGB_FAKE_CC=9.0 ./run --sign-off "$SIGN" --out "$T/cc90" > "$T/cc90.txt" 2>&1
expect "cc 9.0 has no kernel" 1 $?
C=$(ls "$T"/cc90/*.json 2>/dev/null | head -n 1)
[ -n "$C" ] && { $V --allow-fake "$C" > /dev/null; expect "not_run receipt validates" 0 $?; }

# 5. no GPU: exit 2 and no receipt
OGB_FAKE_DRIVER=$FAKE OGB_FAKE_MODE=nogpu ./run --sign-off "$SIGN" --out "$T/nogpu" > "$T/nogpu.txt" 2>&1
expect "no GPU" 2 $?
[ -z "$(ls "$T"/nogpu 2>/dev/null)" ] && ok "no receipt without a GPU" || bad "a receipt was written without a GPU"
grep -q "NOT_RUN" "$T/nogpu.txt" && ok "says NOT_RUN" || bad "says NOT_RUN"

# 6. the real driver path on a machine without libcuda (GitHub runners): exit 2, no receipt
if python3 -c "import ctypes;ctypes.CDLL('libcuda.so.1')" 2>/dev/null; then
  echo "skip  real no-driver case: this machine has libcuda (NOT_RUN here, runs in CI)"
else
  ./run --sign-off "$SIGN" --out "$T/real" > "$T/real.txt" 2>&1; expect "real libcuda absent" 2 $?
  [ -z "$(ls "$T"/real 2>/dev/null)" ] && ok "no receipt without libcuda" || bad "receipt without libcuda"
fi

# 7. no sign-off and no git identity: exit 4
mkdir -p "$T/home"
HOME="$T/home" GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 OGB_FAKE_DRIVER=$FAKE \
  ./run --out "$T/nosign" > "$T/nosign.txt" 2>&1
expect "no sign-off" 4 $?

# 8. a changed kernel file: the kit refuses to run (exit 3)
git clone -q "$ROOT" "$T/clone"
printf '\001' | dd of="$T/clone/kernels/vecadd_sm80_v7.cubin" bs=1 seek=300 conv=notrunc 2>/dev/null
OGB_FAKE_DRIVER=$FAKE "$T/clone/run" --sign-off "$SIGN" --out "$T/flip" > "$T/flip.txt" 2>&1
expect "byte-flipped cubin refused" 3 $?

# 9. tampered receipts: every one must be rejected for the stated reason
I=$(ls receipts/*.json 2>/dev/null | head -n 1)
if [ -n "$K" ]; then
  python3 tests/tamper.py "$K" "${I:--}" "$T/tampered" > "$T/cases.tsv"
  while IFS="$(printf '\t')" read -r case reason; do
    $V --allow-fake "$T/tampered/$case.json" > "$T/v.txt"
    if [ $? -eq 1 ] && grep -qF -- "$reason" "$T/v.txt"; then ok "tampered $case rejected: $reason"
    else bad "tampered $case not rejected for: $reason"; cat "$T/v.txt"; fi
  done < "$T/cases.tsv"
fi

# 10. the committed example of a tampered receipt is rejected
$V tests/tampered/*.json > "$T/ex.txt"; expect "tests/tampered examples rejected" 1 $?
grep -q "receipt_sha256 does not match" "$T/ex.txt" && ok "reason: edited after it was written" || bad "tampered example reason"

# 11. the board builds from valid receipts only
python3 tools/board.py "$T/site" > "$T/board.txt"; expect "board builds" 0 $?
grep -q "0 rejected" "$T/board.txt" && ok "board: no rejected receipts in the repo" || bad "board rejected some receipts"

echo "$pass passed, $fail failed"
rm -rf "$T"
[ "$fail" -eq 0 ]
