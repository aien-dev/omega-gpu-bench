# Dependencies

Everything this repository needs that is not Omega, with its exact version, what it does here, and what
replaces it.

## Build path (CI, `kernels/src/build.sh`)

| Dependency | Pin | What it does | Omega replacement |
| --- | --- | --- | --- |
| aien-dev/omega-mv `seed/out/omc` | commit 7ca3f989, sha256 `2c824805…029f` | compiles `cubin.om` | first-party (Omega's seed compiler) |
| aien-dev/omega-mv `seed/rung2/asm2.bin` | sha256 `6988abe0…69c4` | assembles the `.cuda.s2` listings | first-party |
| aien-dev/omega-mv `seed/sm80/sm80.tbl` | sha256 `c77a731d…670f` | Ampere/Ada encoding table (checked against Mesa NAK in omega-mv PR 836) | first-party |
| `kernels/src/cubin.om` | sha256 `e40ea98d…de50` | cubin writer (ABI 7 and 8 with `.note.nv.tkinfo`, register reserve, exit 6 register and exit 7 scoreboard refusals), vendored from omega-mv branch `ck/cubin-om` (PR 864, 76639738) plus the scoreboard check; PR 864 is on hold for the CudaLicenseRisk Q6 decision | first-party; moves to omega-mv with PR 864 |
| `kernels/src/vecadd.cuda.s2`, `alu.s2`, `ctl.s2` | sha256 `f8cb69e0…504a`, `87dd8cab…0359`, `c82663d3…2a49` | kernel listings (alu and ctl stall 2 after a scoreboard set at instructions 4 and 10) | first-party; move to omega-mv `seed/sm80/` |
| POSIX sh, awk, coreutils, git (GitHub `ubuntu-24.04-arm` image) | runner image | runs the build steps and hashes; awk writes the two 1-cycle negative listings | host tools, coordination only |

## Offline oracle (`kernels/src/oracle.sh`, local only, not in CI)

| Dependency | Version | What it does | Omega replacement |
| --- | --- | --- | --- |
| `kernels/src/oracle.sh` | sha256 `886e4e0c…4e63` | INTERIM sh and awk: header, tkinfo, decode, register and scoreboard checks over any cubin | an Omega cubin reader in omega-mv that decodes the same fields from the bytes; `oracle.sh` stays as its independent cross-check |
| `nvdisasm`, `cuobjdump` (NVIDIA CUDA toolkit) | 13.0 V13.0.88 on the Spark (`evidence/oracle-2026-10-27/oracle.log`) | read-only oracles: decode, register count, control bits; run only on our own cubins and on nvcc builds of our own probe sources, never on extracted NVIDIA binaries | none: they are the independent referee, like Mesa NAK |
| GNU readelf (binutils) | 2.42 | read-only: section list | the Omega cubin reader |

## Run path (`./run` on the developer's machine)

| Dependency | Version | What it does | Omega replacement |
| --- | --- | --- | --- |
| NVIDIA libcuda (`libcuda.so.1`) | whatever driver the developer has; recorded in the receipt | loads and launches the cubins | none intended here: it is the interop oracle. CUDA++'s own user-space path is a separate kit. |
| Python 3.8+ (`kit/bench.py`, `kit/ck.py`) | the developer's | INTERIM glue: ctypes calls into libcuda, CPU reference, receipt JSON | an omc-built `ogb` binary that calls libcuda through Omega's host FFI, writes the same receipt schema, and is checked against the Python kit on the same receipts |
| `nvidia-smi`, `/proc/driver/nvidia/version`, `uname` | the developer's | machine description in the receipt | read by the same omc-built binary |

## CI checks (`tools/`, `tests/`, workflows)

| Dependency | Version | What it does | Omega replacement |
| --- | --- | --- | --- |
| Python 3 (`tools/receipt.py`, `validate.py`, `pr_gate.py`, `board.py`, `import_cloudkernels.py`) | runner's | INTERIM: receipt rules, PR gate, board page | omc-built validator and page generator (the board the way aienos.com pages are rendered from seeded Omega); `import_cloudkernels.py` is one-off and is retired, not ported |
| `tests/run.sh`, `tests/tamper.py`, `tests/fakecuda.py` | runner's sh and Python | INTERIM test driver, tamper cases, fake libcuda fixture | ported with the validator |
| actions/checkout@v4, upload-pages-artifact@v3, deploy-pages@v4 | GitHub | CI plumbing and Pages | none (GitHub is the distribution channel) |
