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

## Rebuild the kernels

```sh
git clone https://github.com/aien-dev/omega-mv ../omega-mv
git -C ../omega-mv fetch origin 7ca3f989cbd62e77de1dd7d23919edd083fd2113 && git -C ../omega-mv checkout FETCH_HEAD
kernels/src/build.sh ../omega-mv     # aarch64 Linux; prints PASS when all six match
```

## Tests

```sh
sh tests/run.sh
```

No GPU needed. Licensed under Apache-2.0 with the LLVM exception ([LICENSE](LICENSE), [NOTICE](NOTICE)).
