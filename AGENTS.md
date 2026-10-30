# Instructions for agents

- **Product:** a bring-your-own-GPU bench for Omega-encoded kernels. Honesty is the product: every number
  on the board comes from a receipt that passed `tools/validate.py`. Never add a receipt you did not get
  from `./run` (or an allowlisted import with its raw evidence), never edit a receipt, never weaken the
  validator, `tools/pr_gate.py`, or the negative controls in `tests/run.sh`.
- **Labels:** results go through NVIDIA libcuda. Call it an interop oracle, never CUDA++ user space.
  A receipt is self-reported, not hardware qualification. Spell it "Aien"; page and README copy is first
  person singular.
- **Kernels:** the v7 cubins and their writer were withdrawn pending a clean-room rewrite (CudaLicenseRisk
  Q6, README "Kernels withdrawn"); never restore them or anything derived from them. A cubin writer may
  come back only from public sources with recorded provenance, and only with its source in `kernels/src/`,
  a rebuild that reproduces each cubin byte for byte in CI, and a matching `neg` negative control.
  `kernels/WITHDRAWN.sha256` stays: it checks the historical imported receipts. The CloudKernels alu/ctl
  and v8 cubins are excluded on purpose (they fail with CUDA_ERROR_ILLEGAL_INSTRUCTION or crash 12.x drivers).
- **Language:** the kit and tools are interim Python and sh; each has its Omega successor in
  DEPENDENCIES.md. New host programs go there with version, purpose and replacement.
- **Never run `./run` against a shared or production GPU host without its owner's window.** Use
  `OGB_FAKE_DRIVER=tests/fakecuda.py` for development; its receipts are rejected as evidence.
- **Workflow:** changes land by pull request. Run `sh tests/run.sh` before opening one and quote its
  output.
- **Status words:** PROPOSED, IMPLEMENTED, EXERCISED, VERIFIED, QUALIFIED, MERGED, DEPLOYED.
