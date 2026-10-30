# omega-gpu-bench

Run GPU kernels whose machine code was written by Omega on **your own NVIDIA GPU**, check every output
word against a CPU reference, and put your card on the board:
<https://aien-dev.github.io/omega-gpu-bench/>

```sh
git clone https://github.com/aien-dev/omega-gpu-bench && cd omega-gpu-bench && ./run
```

You need Linux, an NVIDIA driver (`libcuda.so.1`), Python 3.8 or newer, and git. No CUDA toolkit, no
compiler, no `pip install`, no root.

## Kernels withdrawn

The six v7 cubins (vecadd and neg for sm_80, sm_86 and sm_89) and the cubin writer that produced them
(`kernels/src/cubin.om`, driven by `kernels/src/build.sh`) were **removed pending clean-room rewrite
(CudaLicenseRisk Q6)**. Until a cubin writer built only from public sources lands, `./run` reports
`NOT_RUN` on every GPU with that reason, touches no GPU and writes no receipt. The removed files remain
in this repository's git history; purging them from history is a separate decision that has not been
made. Their hashes are kept in `kernels/WITHDRAWN.sha256` (see "The seed rows").

## What runs where

| Piece | What it is |
| --- | --- |
| Kernels (`kernels/*.cubin`) | None at present (see "Kernels withdrawn"). The SASS listings `kernels/src/*.cuda.s2` for Omega's `asm2` remain; the cubin writer is to be rewritten from public sources. |
| Path to the GPU | **NVIDIA's own driver library**, libcuda (`cuModuleLoadData`, `cuLaunchKernel`). This kit uses it as an interop oracle for Omega's encoder and cubin writer. It is not CUDA++'s own user-space driver path. |
| Kit (`./run`, `kit/*.py`) | Interim Python glue that loads the cubins through ctypes, checks the output and writes the receipt. Its Omega successor is listed in [DEPENDENCIES.md](DEPENDENCIES.md). |
| Receipts | Self-reported. CI checks everything it can from public inputs (below), but it cannot re-run your GPU. |

When the kit ships kernels, it runs every kernel your card can load: an sm_89 card (RTX 40, L4, L40)
runs the sm_89, sm_86 and sm_80 builds, an sm_86 card (RTX 30, A10, A40) runs sm_86 and sm_80, an sm_80
card (A100, A30) runs sm_80. Other architectures get a receipt that says `not_run`: this kit has no kernel
for them yet.

Each GPU runs two kernels per architecture (this is what the withdrawn kernels did):

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
- it is a kit run of a withdrawn kernel (a hash in `kernels/WITHDRAWN.sha256`), from any kit commit;
- it leaves out a kernel the GPU can load, or lists one it cannot;
- a count is not 2^20 + 7, or a verdict disagrees with its mismatch count;
- any reported reference value differs from the one recomputed from the public seed, or a "wrong"
  value equals the reference;
- a clean run's output hash is not the reference output's hash, or a failing run's is;
- the GB/s does not follow from the kernel time, or the libcuda label is missing;
- it was made with the test fixture driver.

`tools/pr_gate.py` (run from `main`, never from the pull request) also keeps receipts append-only and
checks the sign-off. `tests/run.sh` proves each of these rules can fail: it runs a fixture kit (placeholder
kernel files, not cubins) against a fake driver, tampers with the result fifteen ways, and requires every
tampered receipt to be rejected. It also checks that the shipped kit says `NOT_RUN` and that a run made
with the last kit that shipped the withdrawn kernels is rejected.

## The seed rows

The first three rows on the board are my own runs on GPUs rented from vast through OpenResearch on
2026-10-26, before this kit existed: an RTX 4090, an A100 PCIe 40GB and an RTX 3090. They went through
the same libcuda path with the same cubins (`origin: cloudkernels-import`, allowlisted in
`receipts/imports.sha256`, raw output in `evidence/cloudkernels/`). That harness did not hash the output
or time the kernel, so those rows say "not timed". They are kept unchanged as historical records. The
kernels they hash were withdrawn pending a clean-room rewrite (see "Kernels withdrawn"); the validator
checks imported rows against `kernels/WITHDRAWN.sha256`, and no new run of those kernels is accepted.

## Rebuilding the kernels

NOT_RUN: the cubin writer and its build script were withdrawn (see "Kernels withdrawn"), so there is
nothing to rebuild until the clean-room rewrite lands.

## Tests

```sh
sh tests/run.sh
```

No GPU needed. Licensed under Apache-2.0 with the LLVM exception ([LICENSE](LICENSE), [NOTICE](NOTICE)).

## Human-Directed Agentic Engineering

I follow Human-Directed Agentic Engineering (HDAE) in development: I define goals,
architecture, constraints, acceptance criteria, and stopping points; agents implement,
execute checks, diagnose failures, and revise within those boundaries. I retain
responsibility for reviewing claims, accepting changes, and release decisions.
This development method does not turn a self-reported receipt into hardware qualification.

For the documented method and a systems-software case study, see Gregory M. Kurtzer,
[*Ginux: Building an Independent Kernel That Runs Linux Userspace through
Human-Directed Agentic Engineering* (2026)](https://doi.org/10.5281/zenodo.23682548).
