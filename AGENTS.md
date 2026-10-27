# Instructions for agents

- **Product:** a bring-your-own-GPU bench for Omega-encoded kernels. Honesty is the product: every number
  on the board comes from a receipt that passed `tools/validate.py`. Never add a receipt you did not get
  from `./run` (or an allowlisted import with its raw evidence), never edit a receipt, never weaken the
  validator, `tools/pr_gate.py`, or the negative controls in `tests/run.sh` and the CI rebuild.
- **Labels:** results go through NVIDIA libcuda. Call it an interop oracle, never CUDA++ user space.
  A receipt is self-reported, not hardware qualification. Spell it "Aien"; page and README copy is first
  person singular.
- **Kernels:** only add a cubin together with its source in `kernels/src/`, a `build.sh` rebuild that
  reproduces it byte for byte, and a matching `neg` negative control. The alu/ctl and v8 images are
  fixed in source (README "Known losses") but stay in `kernels/pending/` (hashes only) until a chip run
  on sm_80/86/89 passes; never move them into the kit on host evidence alone. Never remove the
  scoreboard (exit 7) or register (exit 6) refusals from `cubin.om` or `build.sh`.
- **Language:** the kit and tools are interim Python and sh; each has its Omega successor in
  DEPENDENCIES.md. New host programs go there with version, purpose and replacement.
- **Never run `./run` against a shared or production GPU host without its owner's window.** Use
  `OGB_FAKE_DRIVER=tests/fakecuda.py` for development; its receipts are rejected as evidence.
- **Workflow:** changes land by pull request. Run `sh tests/run.sh` before opening one and quote its
  output.
- **Status words:** PROPOSED, IMPLEMENTED, EXERCISED, VERIFIED, QUALIFIED, MERGED, DEPLOYED.
