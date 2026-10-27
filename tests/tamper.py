#!/usr/bin/env python3
# tests/tamper.py KIT_RECEIPT IMPORT_RECEIPT OUT_DIR -- write tampered copies of two valid receipts.
# Each output file is named <case>.json; tests/run.sh requires tools/validate.py to reject every one of
# them with the reason listed in CASES. All but "noreseal" are re-sealed, so the content rules (not just
# the receipt hash) have to catch them.
import copy, json, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import receipt as R  # noqa: E402


def row(rec, verdict):
    return next(r for r in rec["results"] if r["verdict"] == verdict)


def t_noreseal(r):
    r["machine"]["gpu"] = "NVIDIA H100 80GB HBM3"
    return False


def t_cubin_hash(r):
    r["results"][0]["cubin_sha256"] = "0" * 64


def t_pass_with_mismatches(r):
    row(r, "PASS")["mismatches"] = 5


def t_forged_ref(r):
    row(r, "NEG_DETECTED")["first_bad"][0][2] += 1


def t_dropped_row(r):
    r["results"].remove(row(r, "NEG_DETECTED"))


def t_output_hash(r):
    row(r, "PASS")["output_sha256"] = "ab" * 32


def t_inflated_gbps(r):
    p = row(r, "PASS")
    p["gbps"] = round(p["gbps"] * 2, 3)


def t_label(r):
    r["path"] = "CUDA++ user space"


def t_checked_short(r):
    row(r, "PASS")["checked"] = 1000


def t_unknown_commit(r):
    r["kit"]["commit"] = "f" * 40


def t_modified_kit(r):
    r["kit"]["modified"] = True


def t_neg_not_run_as_detected(r):
    n = row(r, "NEG_DETECTED")
    n.update(checked=None, mismatches=None, first_bad=None, output_sha256=None, error="cuModuleLoadData: 200")


def t_withdrawn_kernel(r):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sums = R.read_sums(os.path.join(root, "kernels", "WITHDRAWN.sha256"))
    p = row(r, "PASS")
    p["cubin_sha256"] = sums[p["cubin"]]


CASES = {  # case: (tamper, which receipt, reason the validator must give)
    "noreseal": (t_noreseal, "kit", "receipt_sha256 does not match"),
    "cubin-hash": (t_cubin_hash, "kit", "differs from kernels/SHA256SUMS"),
    "withdrawn-kernel": (t_withdrawn_kernel, "kit", "kernel withdrawn from this kit"),
    "pass-with-mismatches": (t_pass_with_mismatches, "kit", "contradicts 5 mismatches"),
    "forged-ref": (t_forged_ref, "kit", "recomputed"),
    "dropped-row": (t_dropped_row, "kit", "must run exactly"),
    "output-hash": (t_output_hash, "kit", "differs from the reference output but mismatches = 0"),
    "inflated-gbps": (t_inflated_gbps, "kit", "is not 12 *"),
    "label-removed": (t_label, "kit", "path label"),
    "checked-short": (t_checked_short, "kit", "checked must be"),
    "unknown-commit": (t_unknown_commit, "kit", "is not in"),
    "modified-kit": (t_modified_kit, "kit", "local changes"),
    "neg-not-run-as-detected": (t_neg_not_run_as_detected, "kit", "a kernel that ran has no error"),
    "import-not-allowlisted": (lambda r: r.update(provider="my own 4090"), "import", "imports.sha256"),
    "import-forged-ref": (t_forged_ref, "import", "recomputed"),
}

if __name__ == "__main__":
    src = {"kit": json.load(open(sys.argv[1])), "import": None if sys.argv[2] == "-" else json.load(open(sys.argv[2]))}
    os.makedirs(sys.argv[3], exist_ok=True)
    for case, (fn, which, reason) in CASES.items():
        if src[which] is None:
            continue  # no imported receipt in this checkout
        rec = copy.deepcopy(src[which])
        if fn(rec) is not False:
            R.seal(rec)
        with open(os.path.join(sys.argv[3], case + ".json"), "w") as f:
            json.dump(rec, f, indent=1, sort_keys=True)
        print("%s\t%s" % (case, reason))
