# Security

Report vulnerabilities privately through GitHub security advisories on this repository (Security → Report a vulnerability). Do not report them in public issues.

## Threat model

`./run` loads the cubins in `kernels/` into your GPU through NVIDIA's libcuda and runs them:

- It checks every cubin against `kernels/SHA256SUMS` first and refuses to run if one differs.
- It needs no root, installs nothing, and makes no network connection.
- It writes only the receipt under `receipts/` (or `--out`). The receipt names your GPU, driver, OS,
  kernel version and CPU model, and the sign-off you give it. Read it before you submit it.

The receipt gate (`.github/workflows/receipts.yml`) runs with `pull_request_target` and a read-only token.
It runs `tools/` from the base branch and only reads the pull request's files as data; it never executes
code from a pull request.

Receipts are self-reported. The validator catches edits and inconsistent numbers, but nobody can prove
from a JSON file which GPU produced it.
