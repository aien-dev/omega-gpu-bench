# omega-gpu-bench

Run GPU kernels whose machine code was written by Omega on **your own NVIDIA GPU**, check every output
word against a CPU reference, and put your card on the board:
<https://aien-dev.github.io/omega-gpu-bench/>

```sh
git clone https://github.com/aien-dev/omega-gpu-bench && cd omega-gpu-bench && ./run
```

You need Linux, an NVIDIA driver (`libcuda.so.1`), Python 3.8 or newer, and git. No CUDA toolkit, no
compiler, no `pip install`, no root. It takes under a minute and writes one JSON receipt under `receipts/`.

## What runs where

| Piece | What it is |
| --- | --- |
| Kernels (`kernels/*.cubin`) | SASS for sm_80/86/89, assembled by Omega's `asm2` from the hand-written listings in `kernels/src/` and wrapped into a cubin by `kernels/src/cubin.om`, compiled by Omega's seed compiler. CI rebuilds all six from source and checks the bytes. |
| Path to the GPU | **NVIDIA's own driver library**, libcuda (`cuModuleLoadData`, `cuLaunchKernel`). This kit uses it as an interop oracle for Omega's encoder and cubin writer. It is not CUDA++'s own user-space driver path. |
| Kit (`./run`, `kit/*.py`) | Interim Python glue that loads the cubins through ctypes, checks the output and writes the receipt. Its Omega successor is listed in [DEPENDENCIES.md](DEPENDENCIES.md). |
| Receipts | Self-reported. CI checks everything it can from public inputs (below), but it cannot re-run your GPU. |

The kit runs every kernel your card can load: an sm_89 card (RTX 40, L4, L40) runs the sm_89, sm_86 and
sm_80 builds, an sm_86 card (RTX 30, A10, A40) runs sm_86 and sm_80, an sm_80 card (A100, A30) runs sm_80. Other
architectures (Hopper, Blackwell, Turing and older) get a receipt that says `not_run`: this kit has no
kernel for them yet.

Each GPU runs two kernels per architecture:

- **vecadd**: `c[i] = a[i] + b[i]` on 2^20 + 7 32-bit words from a fixed seed; every word is compared.
  Then it is timed on 2^26 words: median of 5 rounds of 20 launches, timed with CUDA events,
  12 bytes moved per word.
- **neg**: the same kernel with one register operand changed. Its output must be wrong
  (`NEG_DETECTED`). If it came out right, the check could not fail, and the run says `NEG_MISSED`.

## Submit your receipt

```sh
python3 tools/validate.py receipts/<your receipt>.json
```

Then fork this repository, commit the receipt with `git commit -s` (the `Signed-off-by` line must equal the
receipt's `signed_off_by`), push, and open a pull request. `./run` prints the exact commands.
`--sign-off "Name <email>"` sets the name; the default is your git identity. `--provider` says where the
GPU is (default `self-hosted`; e.g. `--provider "vast"` for a rented card).

## What CI checks

`tools/validate.py` rejects a receipt when:

- it was edited after `./run` wrote it (the `receipt_sha256` covers every field);
- a kernel hash differs from `kernels/SHA256SUMS` at the kit commit named in the receipt, that commit is
  not on `main`, or the kit had local changes;
- it leaves out a kernel the GPU can load, or lists one it cannot;
- a count is not 2^20 + 7, or a verdict disagrees with its mismatch count;
- any reported reference value differs from the one recomputed from the public seed, or a "wrong"
  value equals the reference;
- a clean run's output hash is not the reference output's hash, or a failing run's is;
- the GB/s does not follow from the kernel time, or the libcuda label is missing;
- it was made with the test fixture driver.

`tools/pr_gate.py` (run from `main`, never from the pull request) also keeps receipts append-only and
checks the sign-off. `tests/run.sh` proves each of these rules can fail: it runs the kit against a fake
driver, tampers with the result fourteen ways, and requires every tampered receipt to be rejected.

## The seed rows

The first three rows on the board are my own runs on GPUs rented from vast through OpenResearch on
2026-10-26, before this kit existed: an RTX 4090, an A100 PCIe 40GB and an RTX 3090. They went through
the same libcuda path with the same cubins (`origin: cloudkernels-import`, allowlisted in
`receipts/imports.sha256`, raw output in `evidence/cloudkernels/`). That harness did not hash the output
or time the kernel, so those rows say "not timed".

## Known losses: what failed on the seed rows, and why

The seed rentals ran 8 images per architecture (alu, ctl, vecadd, neg × ABI 7 and 8). Only vecadd v7
passed and neg v7 failed the way it should. These are my losses and their causes; nothing below has been
re-run on an sm_80/86/89 chip yet.

| Class | Rows (of 22 failing) | What the driver said | Root cause | Evidence |
| --- | --- | --- | --- | --- |
| A | alu, ctl, vecadd v8 on every card (9) | `cuModuleLoadData: 200 CUDA_ERROR_INVALID_IMAGE` | an ABI 8 cubin needs a `.note.nv.tkinfo` section; cubin.om wrote none | the same vecadd v8 with tkinfo loads and passes, without it (`v8dNoTk`, `v8old`) LOAD_FAIL 200 on RTX_4090-002933 (driver 615.71.09) |
| B | alu, ctl v7 on every card, sm_80 builds on the 4090 and 3090 too (10) | `cuCtxSynchronize: 715 CUDA_ERROR_ILLEGAL_INSTRUCTION` | the cubin recorded 16 registers while alu writes R15 and ctl R14; Volta and later reserve 2 more, so the kernel ran past its allocation | on RTX_4090-002933 the same alu machine code with 16 registers (`alu_sm89_v7old`) RUN_FAIL 715 and with 18 (`alu_sm89_v7`) ran to completion (then hit D); ctl v7 with 17 PASS |
| C | neg v8 on every card (3) | `NEG_DETECTED` with error `200` | not a pass: the old harness called a load failure a detected negative. `kit/ck.py` classifies it as LOAD_FAIL | the `error` field of those rows |
| D | alu after the B fix (only on later 4090 rentals) | WRONG (33 to 289 words, always in the float output) or 700/716/717 | instructions 4 (ULDC UR5) and 10 (LDC.64 R6) set a scoreboard and stalled 1 cycle; the wait at the next instruction ran before the scoreboard was armed, so IMAD.WIDE at instruction 14 could read R6 before LDC wrote it. Mesa NAK arms a scoreboard 2 cycles after issue (`calc_instr_deps.rs`, `bars[bar] + 2`, Mesa 02f13375) | alu v7 WRONG 129 and v8 WRONG 225 on RTX_4090-002933; the same bytes WRONG 33 on RTX_4090-005123 and 257 on RTX_4090-010516, PASS once on RTX_4090-004535 (a race); a wait at instruction 12, 13 or 14 PASS, at 16 or later WRONG (RTX_4090-005123) |

Rows: A100_PCIE_40GB-231428 (driver 570.211.01), RTX_3090-231552 (580.159.03) and RTX_4090-231340
(580.65.06) in `evidence/cloudkernels/`. The later 4090 runs are in the CloudKernels lane's run logs
(`~/handoffs/CloudKernels/runs/<tag>/res/results.jsonl` on the Spark), not in this repository. ctl v7
carries the same 1-cycle schedule as alu and passed anyway; I count that as luck, not evidence.
`launch_s` in those logs is one launch's wall time for a correctness run, not a throughput figure.

Fixes (IMPLEMENTED, EXERCISED on the host only):

- `kernels/src/cubin.om` writes `.note.nv.tkinfo` for ABI 8 (A), records REGS + 2 and refuses a REGS
  below the highest register with exit 6 (B), and refuses with exit 7 any instruction that sets a
  scoreboard with stall 0, or with stall 1 when the next instruction waits on it or stalls 0 (D).
- `kernels/src/alu.s2` and `ctl.s2` stall 2 at instructions 4 and 10.
- `build.sh` rebuilds 24 pending images (alu, ctl, vecadd, neg × sm_80/86/89 × ABI 7/8) and checks them
  against `kernels/pending/SHA256SUMS`, then requires three refusals: alu and ctl with the old 1-cycle
  stall (exit 7; the alu machine code it would have produced equals the bytes that went WRONG on
  RTX_4090-005123 and -010516) and alu with REGS 15 (exit 6).

The pending images stay out of the kit until they run on a chip. That re-run is NOT_RUN. The command,
for whoever holds the rental budget (CloudKernels lane, OpenResearch account):

```sh
kernels/src/build.sh ../omega-mv /tmp/ogb
mkdir -p ~/handoffs/CloudKernels/payload-gbf/cub
cp /tmp/ogb/pending/*.cubin ~/handoffs/CloudKernels/payload-gbf/cub/
cp ~/handoffs/CloudKernels/payload-r7/run.sh ~/handoffs/CloudKernels/payload-r7/ck.py ~/handoffs/CloudKernels/payload-gbf/
cd ~/handoffs/CloudKernels
CK_PAYLOAD=payload-gbf python3 box.py gpu RTX_4090 20 vast
CK_PAYLOAD=payload-gbf python3 box.py gpu A100_PCIE_40GB 20 vast
CK_PAYLOAD=payload-gbf python3 box.py gpu RTX_3090 20 vast
```

Pass means: every alu, ctl and vecadd image PASS and every neg image NEG_DETECTED with no error, on each
card, repeated at least 10 times for alu (the D race passed once by chance on RTX_4090-004535).

## Offline oracle

`kernels/src/oracle.sh` checks cubins with NVIDIA's disassembler tools as read-only oracles: header
(OSABI, ABI version, e_flags), `.note.nv.tkinfo` for ABI 8, `nvdisasm` decode, `cuobjdump -res-usage`
registers ≥ highest register + 3, and a set-to-wait distance of at least 2 cycles for every scoreboard.
It needs a CUDA toolkit, so CI does not run it (NOT_RUN there); I ran it on the Spark with CUDA 13.0
V13.0.88 (`evidence/oracle-2026-10-27/oracle.log`):

- the 6 kit cubins and 24 pending images: 150 of 150 checks PASS;
- positive control, nvcc 13.0 builds of three probe kernels for sm_80/86/89: 45 of 45 PASS;
- negative control, the 27 images that ran on the rentals: every image that failed on a chip fails here
  in its class (A: tkinfo; B: regs; D: sb), and the 6 vecadd and neg v7 images that behaved on the chip
  pass. ctl also fails `sb`, the latent hazard above.

The v8 header rule (OSABI 0x41, e_flags `0x6000000 | SM << 8 | 4`) comes from what nvcc 13.0 writes and
the driver loads, not from a specification. LLVM main (930a3d47) names `ELFOSABI_CUDA_V2 = 41`, decimal;
I have not checked whether that is a typo or a different value.

## Rebuild the kernels

```sh
git clone https://github.com/aien-dev/omega-mv ../omega-mv
git -C ../omega-mv fetch origin 7ca3f989cbd62e77de1dd7d23919edd083fd2113 && git -C ../omega-mv checkout FETCH_HEAD
kernels/src/build.sh ../omega-mv     # aarch64 Linux; prints PASS for the six kit cubins, the 24 pending images and three refusals
```

## Tests

```sh
sh tests/run.sh
```

No GPU needed. Licensed under Apache-2.0 with the LLVM exception ([LICENSE](LICENSE), [NOTICE](NOTICE)).
