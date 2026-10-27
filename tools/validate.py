#!/usr/bin/env python3
# tools/validate.py -- check receipts. A receipt is self-reported: nothing here can re-run someone's GPU.
# What it does check, from public inputs alone:
#   * the receipt hash covers every field (an edit after ./run breaks it unless the editor re-seals it,
#     which the rules below then have to survive);
#   * each kernel's sha256 equals kernels/SHA256SUMS at the kit commit the receipt names, and that commit
#     is in this repository's history; the kit was unmodified;
#   * the receipt lists exactly the kernels its GPU's compute capability can load (no dropped failures);
#   * every count is the fixed n = 2^20 + 7, and each verdict agrees with its mismatch count;
#   * every reported reference value in first_bad is recomputed here from the public seed, and every
#     reported GPU value differs from it; a clean run's output hash must equal the reference's hash;
#   * GB/s is recomputed from the kernel time; the libcuda label and the sign-off are present;
#   * imported CloudKernels runs are accepted only if their hash is on receipts/imports.sha256, and their
#     kernels are checked against kernels/WITHDRAWN.sha256 (the cubins they ran, since withdrawn);
#   * a kit run of a withdrawn kernel is rejected, whatever kit commit it names;
#   * receipts made with the test fixture driver are rejected (tests use --allow-fake).
# INTERIM host glue (Python); Omega successor: an omc-built checker, see DEPENDENCIES.md.
import argparse, hashlib, json, os, random, re, subprocess, sys
from array import array

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import receipt as R  # noqa: E402

HEX64, HEX40 = re.compile(r"[0-9a-f]{64}"), re.compile(r"[0-9a-f]{40}")
TOP = {"schema", "origin", "path", "provider", "kit", "machine", "run", "submitter", "results", "not_run",
       "evidence", "receipt_sha256"}
KIT_KEYS = {"repo", "commit", "modified", "kernels_sha256sums"}
MACHINE_KEYS = {"gpu", "cc", "cuda_driver_api", "driver_version", "nvrm", "os", "kernel", "arch", "cpu"}
RUN_KEYS = {"utc", "driver", "python"}
RAN = {"PASS", "WRONG", "NEG_DETECTED", "NEG_MISSED"}
FAILED = {"INIT_FAIL", "LOAD_FAIL", "RUN_FAIL", "HARNESS_CRASH"}
_ref = {}


def reference():
    if not _ref:
        rng = random.Random(R.SEED)
        a = [rng.getrandbits(32) for _ in range(R.N)]
        b = [rng.getrandbits(32) for _ in range(R.N)]
        ref = array("I", ((x + y) & 0xFFFFFFFF for x, y in zip(a, b)))
        if sys.byteorder != "little":
            ref.byteswap()
        _ref["sha"] = hashlib.sha256(ref.tobytes()).hexdigest()
        if sys.byteorder != "little":
            ref.byteswap()
        _ref["ref"] = ref
    return _ref


def git(repo, *args):
    p = subprocess.run(["git", "-C", repo, *args], capture_output=True)
    return p.stdout if p.returncode == 0 else None


class Checker:
    def __init__(self, repo, sums_path, imports_path, allow_fake):
        self.repo, self.allow_fake = repo, allow_fake
        self.sums_text = open(sums_path).read()
        withdrawn = os.path.join(os.path.dirname(sums_path), "WITHDRAWN.sha256")
        self.withdrawn_text = open(withdrawn).read() if os.path.exists(withdrawn) else ""
        self.withdrawn = set(R.parse_sums(self.withdrawn_text).values())
        self.imports = set()
        if os.path.exists(imports_path):
            self.imports = {l.split()[0] for l in open(imports_path) if l.strip() and not l.startswith("#")}
        self.is_git = git(repo, "rev-parse", "--git-dir") is not None

    def sums_at(self, commit, errs):
        if commit is None or not self.is_git:
            return self.sums_text
        if git(self.repo, "cat-file", "-e", commit + "^{commit}") is None:
            errs.append("kit.commit %s is not in %s's history" % (commit, R.REPO))
            return self.sums_text
        text = git(self.repo, "show", commit + ":kernels/SHA256SUMS")
        if text is None:
            errs.append("kit.commit %s has no kernels/SHA256SUMS" % commit)
            return self.sums_text
        return text.decode()

    def check(self, rec):
        errs = []
        e = errs.append
        if not isinstance(rec, dict):
            return ["not a JSON object"]
        if set(rec) != TOP:
            return ["top-level keys differ: missing %s, extra %s" % (sorted(TOP - set(rec)), sorted(set(rec) - TOP))]
        if rec["schema"] != R.SCHEMA:
            e("schema is not %s" % R.SCHEMA)
        if rec["receipt_sha256"] != hashlib.sha256(R.canonical(rec)).hexdigest():
            e("receipt_sha256 does not match the receipt's contents (edited after it was written)")
        if rec["path"] != R.PATH_LABEL:
            e("the libcuda path label is missing or changed")
        if not isinstance(rec["provider"], str) or not rec["provider"].strip():
            e("provider is empty")
        origin = rec["origin"]
        if origin not in ("kit-run", "cloudkernels-import"):
            return errs + ["origin must be kit-run or cloudkernels-import"]
        kit, mach, run, sub = rec["kit"], rec["machine"], rec["run"], rec["submitter"]
        if not (isinstance(kit, dict) and set(kit) == KIT_KEYS):
            return errs + ["kit must have exactly %s" % sorted(KIT_KEYS)]
        if not (isinstance(mach, dict) and set(mach) == MACHINE_KEYS):
            return errs + ["machine must have exactly %s" % sorted(MACHINE_KEYS)]
        if not (isinstance(run, dict) and set(run) == RUN_KEYS):
            return errs + ["run must have exactly %s" % sorted(RUN_KEYS)]
        if not (isinstance(sub, dict) and set(sub) == {"signed_off_by", "statement"}):
            return errs + ["submitter must have exactly signed_off_by and statement"]
        if not (isinstance(sub["signed_off_by"], str) and R.SIGNOFF.fullmatch(sub["signed_off_by"])):
            e('submitter.signed_off_by must be "Name <email>"')
        if not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", str(run["utc"])):
            e("run.utc must be YYYY-MM-DDTHH:MM:SSZ")
        if run["driver"] == "fake" and not self.allow_fake:
            e("made with the test fixture driver (tests/fakecuda.py), not a GPU")
        elif run["driver"] not in ("libcuda", "fake"):
            e("run.driver must be libcuda")
        if not (isinstance(mach["gpu"], str) and mach["gpu"]):
            e("machine.gpu is empty")
        if not isinstance(mach["cuda_driver_api"], int) or mach["cuda_driver_api"] <= 0:
            e("machine.cuda_driver_api must be a positive integer")
        if not re.fullmatch(r"\d+\.\d+", str(mach["cc"])):
            return errs + ["machine.cc must look like 8.9"]

        if origin == "kit-run":
            if kit["repo"] != R.REPO:
                e("kit.repo must be %s" % R.REPO)
            if not (isinstance(kit["commit"], str) and HEX40.fullmatch(kit["commit"])):
                e("kit.commit must be a 40-hex commit (run the kit from a git clone)")
            if kit["modified"] is not False:
                e("the kit had local changes when it ran")
            if sub["statement"] != R.STATEMENT:
                e("submitter.statement is missing or changed")
            if rec["evidence"] is not None:
                e("evidence is only for imported runs")
            sums_text = self.sums_at(kit["commit"] if HEX40.fullmatch(str(kit["commit"])) else None, errs)
            if kit["kernels_sha256sums"] != hashlib.sha256(sums_text.encode()).hexdigest():
                e("kit.kernels_sha256sums is not the hash of kernels/SHA256SUMS at kit.commit")
        else:
            if rec["receipt_sha256"] not in self.imports:
                e("imported run is not listed in receipts/imports.sha256")
            ev = rec["evidence"]
            if not (isinstance(ev, dict) and isinstance(ev.get("source"), str) and isinstance(ev.get("files"), list)
                    and ev["files"] and all(isinstance(f, dict) and HEX64.fullmatch(str(f.get("sha256")))
                                            for f in ev["files"])):
                e("imported run needs evidence.source and evidence.files [{path, sha256}]")
            sums_text = self.withdrawn_text
        sums = R.parse_sums(sums_text)

        rows = rec["results"]
        if not isinstance(rows, list):
            return errs + ["results must be a list"]
        want = R.expected_cubins(mach["cc"], sums)
        names = [r.get("cubin") for r in rows if isinstance(r, dict)]
        if len(names) != len(rows) or len(set(names)) != len(names):
            e("results must be distinct objects")
        if origin == "kit-run" and sorted(names) != want:
            e("results list %s but a cc %s GPU must run exactly %s" % (sorted(names), mach["cc"], want))
        if origin != "kit-run" and (not rows or not set(names) <= set(want)):
            e("imported results must be kit kernels this GPU can load")
        if (rec["not_run"] is None) != bool(want):
            e("not_run must be set exactly when this kit has no kernel for the GPU")
        for r in rows:
            if isinstance(r, dict):
                self.check_row(r, sums, origin, e)
                if origin == "kit-run" and r.get("cubin_sha256") in self.withdrawn:
                    e("%s: kernel withdrawn from this kit: %s" % (r.get("cubin"), R.WITHDRAWN))
        return errs

    def check_row(self, r, sums, origin, e):
        name = r.get("cubin")
        if set(r) != set(R.ROW_KEYS):
            e("%s: row keys must be exactly %s" % (name, list(R.ROW_KEYS)))
            return
        m = R.CUBIN.fullmatch(str(name))
        if not m or name not in sums:
            e("%s: not a kernel of this kit" % name)
            return
        if r["cubin_sha256"] != sums[name]:
            e("%s: cubin_sha256 differs from kernels/SHA256SUMS" % name)
        if r["kind"] != m.group(1):
            e("%s: kind must be %s" % (name, m.group(1)))
        v, kind = r["verdict"], m.group(1)
        timing = (r["kernel_ms"], r["gbps"], r["timing_n"])
        if v in FAILED:
            if not (isinstance(r["error"], str) and r["error"]):
                e("%s: %s needs the error text" % (name, v))
            if any(r[k] is not None for k in ("checked", "mismatches", "first_bad", "output_sha256")) or \
                    any(t is not None for t in timing):
                e("%s: %s cannot carry results" % (name, v))
            return
        if v not in RAN:
            e("%s: unknown verdict %r" % (name, v))
            return
        if (kind == "vecadd") != (v in ("PASS", "WRONG")):
            e("%s: verdict %s does not belong to a %s kernel" % (name, v, kind))
        if r["error"] is not None:
            e("%s: a kernel that ran has no error" % name)
        if r["checked"] != R.N:
            e("%s: checked must be %d" % (name, R.N))
        mm = r["mismatches"]
        if not (isinstance(mm, int) and not isinstance(mm, bool) and 0 <= mm <= R.N):
            e("%s: mismatches must be an integer 0..%d" % (name, R.N))
            return
        if (mm == 0) != (v in ("PASS", "NEG_MISSED")):
            e("%s: verdict %s contradicts %d mismatches" % (name, v, mm))
        fb = r["first_bad"]
        if not (isinstance(fb, list) and len(fb) == min(3, mm)):
            e("%s: first_bad must list the first min(3, mismatches) words" % name)
        else:
            ref = reference()["ref"]
            last = -1
            for t in fb:
                if not (isinstance(t, list) and len(t) == 3 and all(isinstance(x, int) for x in t)
                        and last < t[0] < R.N):
                    e("%s: bad first_bad entry %r" % (name, t))
                    break
                last = t[0]
                if t[2] != ref[t[0]]:
                    e("%s: first_bad reference at %d is %d, recomputed %d" % (name, t[0], t[2], ref[t[0]]))
                if t[1] == t[2]:
                    e("%s: first_bad at %d is not a mismatch" % (name, t[0]))
        osha = r["output_sha256"]
        if origin == "kit-run":
            if not (isinstance(osha, str) and HEX64.fullmatch(osha)):
                e("%s: output_sha256 is required" % name)
            elif (osha == reference()["sha"]) != (mm == 0):
                e("%s: output_sha256 %s the reference output but mismatches = %d"
                  % (name, "equals" if osha == reference()["sha"] else "differs from", mm))
        elif osha is not None:
            e("%s: imported runs have no output_sha256" % name)
        if origin == "kit-run" and v == "PASS":
            if r["timing_error"] is not None:
                if any(t is not None for t in timing):
                    e("%s: timing_error and a timing together" % name)
            else:
                kms, gbps, nt = timing
                if nt != R.NT or not isinstance(kms, (int, float)) or kms <= 0 or not isinstance(gbps, (int, float)):
                    e("%s: PASS needs timing_n = %d, kernel_ms > 0 and gbps (or timing_error)" % (name, R.NT))
                elif abs(gbps - round(12 * R.NT / (kms * 1e6), 3)) > 0.0015:
                    e("%s: gbps %s is not 12 * %d bytes / %s ms" % (name, gbps, R.NT, kms))
        elif any(t is not None for t in timing) or r["timing_error"] is not None:
            e("%s: only a kit-run PASS carries timing" % name)


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ap = argparse.ArgumentParser(description="Validate omega-gpu-bench receipts.")
    ap.add_argument("files", nargs="+")
    ap.add_argument("--repo", default=root, help="git checkout used to resolve kit.commit")
    ap.add_argument("--sums", default=os.path.join(root, "kernels", "SHA256SUMS"))
    ap.add_argument("--imports", default=os.path.join(root, "receipts", "imports.sha256"))
    ap.add_argument("--allow-fake", action="store_true", help="tests only: accept the fixture driver")
    o = ap.parse_args()
    c = Checker(o.repo, o.sums, o.imports, o.allow_fake)
    bad = 0
    for path in o.files:
        try:
            errs = c.check(json.load(open(path)))
        except (OSError, ValueError) as x:
            errs = ["unreadable: %s" % x]
        if errs:
            bad += 1
            print("REJECT %s" % path)
            for msg in errs:
                print("  - " + msg)
        else:
            print("VALID  %s" % path)
    print("%d valid, %d rejected" % (len(o.files) - bad, bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
