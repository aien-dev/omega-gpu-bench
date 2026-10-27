# tools/receipt.py -- the receipt format, shared by kit/bench.py (writer), tools/validate.py (checker)
# and tools/board.py (leaderboard). INTERIM host glue (Python); Omega successor: the same rules as an
# omc-built checker using omega-mv's SHA-256 unit (see DEPENDENCIES.md).
import hashlib, json, re

SCHEMA = "omega-gpu-bench/receipt/v1"
REPO = "aien-dev/omega-gpu-bench"
PATH_LABEL = ("NVIDIA libcuda (cuModuleLoadData + cuLaunchKernel): an interop oracle for Omega's "
              "machine-code encoder and cubin writer, not CUDA++'s own user-space driver path")
STATEMENT = "I ran this kit as cloned on the machine described here and did not edit this receipt by hand."
N, SEED, NT = (1 << 20) + 7, 20261026, 1 << 26
SIGNOFF = re.compile(r"[^<>\n]*[^<>\s][^<>\n]* <[^<>@\s]+@[^<>\s]+>")
CUBIN = re.compile(r"(vecadd|neg)_sm(\d)(\d)_v7\.cubin")
ROW_KEYS = ("cubin", "cubin_sha256", "kind", "verdict", "checked", "mismatches", "first_bad",
            "output_sha256", "kernel_ms", "gbps", "timing_n", "error", "timing_error")


def sha256_file(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def parse_sums(text):
    sums = {}
    for line in text.splitlines():
        if line.strip():
            digest, name = line.split(None, 1)
            sums[name.lstrip("*").strip()] = digest
    return sums


def read_sums(path):
    with open(path) as f:
        return parse_sums(f.read())


def canonical(body):
    body = {k: v for k, v in body.items() if k != "receipt_sha256"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def seal(body):
    body["receipt_sha256"] = hashlib.sha256(canonical(body)).hexdigest()
    return body


def expected_cubins(cc, sums):
    """Kernels a GPU of compute capability cc ("8.9") can load: same major, cubin minor <= GPU minor."""
    m = re.fullmatch(r"(\d+)\.(\d+)", cc or "")
    if not m:
        return []
    major, minor = int(m.group(1)), int(m.group(2))
    names = []
    for name in sums:
        c = CUBIN.fullmatch(name)
        if c and int(c.group(2)) == major and int(c.group(3)) <= minor:
            names.append(name)
    return sorted(names)


def result_row(name, digest, kind, ck_out):
    row = {k: ck_out.get(k) for k in ROW_KEYS}
    row.update(cubin=name, kind=kind, cubin_sha256=ck_out.get("cubin_sha256") or digest)
    return row
