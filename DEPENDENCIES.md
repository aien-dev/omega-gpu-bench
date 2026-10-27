# Dependencies

Everything this repository needs that is not Omega, with its exact version, what it does here, and what
replaces it.

## Build path

None at present. The cubin writer (`kernels/src/cubin.om`), its build script and the CI rebuild job were
removed pending clean-room rewrite (CudaLicenseRisk Q6); see README.md, "Kernels withdrawn". The rewrite
brings its own build-path rows. The kept listings `kernels/src/vecadd.cuda.s2` and `neg.cuda.s2` are input
for Omega's `asm2` (aien-dev/omega-mv `seed/rung2/asm2.bin`, first-party), not run by anything here now.

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
