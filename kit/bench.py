#!/usr/bin/env python3
# kit/bench.py -- what ./run executes. Checks the kit's kernels against kernels/SHA256SUMS, asks the
# driver which GPU is device 0, runs every kernel this GPU can load (each in its own process, so a crash
# is a result and not a hang), and writes one receipt JSON under receipts/.
#
# INTERIM host glue (Python). Omega successor: an omc-built `run` that does the same steps, with the
# receipt written by Omega's own JSON and SHA-256 units (omega-mv om/sha256), see DEPENDENCIES.md.
import argparse, datetime, hashlib, json, os, platform, re, subprocess, sys

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KIT, "tools"))
import receipt as R  # noqa: E402


def sh(*cmd):
    try:
        return subprocess.run(cmd, cwd=KIT, capture_output=True, text=True, timeout=60).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def first_line(path, key=None):
    try:
        for line in open(path, errors="replace"):
            if key is None or line.startswith(key):
                return line.strip()
    except OSError:
        pass
    return None


def ck(*args, timeout=600):
    cmd = [sys.executable, os.path.join(KIT, "kit", "ck.py"), *args]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"verdict": "HARNESS_CRASH", "error": "timed out after %d s" % timeout}
    try:
        return json.loads(p.stdout.strip().splitlines()[-1])
    except (IndexError, ValueError):
        stages = re.findall(r"stage=(\S+)", p.stderr)
        return {"verdict": "HARNESS_CRASH",
                "error": "exit %d after stage %s" % (p.returncode, stages[-1] if stages else "none")}


def main():
    ap = argparse.ArgumentParser(prog="./run", description="Run Omega-encoded kernels on this machine's "
                                 "NVIDIA GPU through libcuda and write a receipt.")
    ap.add_argument("--sign-off", help='"Name <email>" (default: git config user.name / user.email)')
    ap.add_argument("--provider", default="self-hosted",
                    help="where the GPU is, e.g. self-hosted (default) or the cloud you rent it from")
    ap.add_argument("--out", default=os.path.join(KIT, "receipts"), help="receipt directory")
    o = ap.parse_args()

    # 1. the kit itself
    sums = R.read_sums(os.path.join(KIT, "kernels", "SHA256SUMS"))
    for name, want in sums.items():
        got = R.sha256_file(os.path.join(KIT, "kernels", name))
        if got != want:
            print("REFUSED: kernels/%s does not match kernels/SHA256SUMS (got %s, want %s)."
                  % (name, got, want))
            print("Run the kit as cloned; rebuild the kernels with kernels/src/build.sh if you changed them.")
            return 3
    commit = sh("git", "rev-parse", "HEAD") or None
    modified = bool(sh("git", "status", "--porcelain", "--", "run", "kit", "kernels", "tools"))
    sign = o.sign_off or ("%s <%s>" % (sh("git", "config", "user.name"), sh("git", "config", "user.email")))
    if not R.SIGNOFF.fullmatch(sign):
        print('REFUSED: no sign-off. Pass --sign-off "Your Name <you@example.com>" or set git config '
              "user.name and user.email.")
        return 4

    # 2. the GPU
    probe = ck("probe", timeout=120)
    if probe.get("verdict") != "PROBED":
        print("NOT_RUN: no usable NVIDIA GPU (%s: %s). No receipt written."
              % (probe.get("verdict"), probe.get("error", "")))
        return 2
    cc = probe["cc"]
    print("GPU 0: %s, compute capability %s, CUDA driver API %d, through %s"
          % (probe["device"], cc, probe["cuda_driver_api"], probe["driver"]))
    smi = sh("nvidia-smi", "--id=0", "--query-gpu=driver_version", "--format=csv,noheader")
    os_name = (first_line("/etc/os-release", "PRETTY_NAME=") or "").split("=", 1)[-1].strip('"') or None
    cpu = first_line("/proc/cpuinfo", "model name")
    machine = {
        "gpu": probe["device"], "cc": cc, "cuda_driver_api": probe["cuda_driver_api"],
        "driver_version": smi or None, "nvrm": first_line("/proc/driver/nvidia/version"),
        "os": os_name, "kernel": platform.release(), "arch": platform.machine(),
        "cpu": cpu.split(":", 1)[1].strip() if cpu else (platform.processor() or None),
    }

    # 3. the kernels this GPU can load
    want = R.expected_cubins(cc, sums)
    results, not_run = [], None
    if not want:
        not_run = ("this kit has no kernel for sm_%s yet: only sm_80/86/89 v7 cubins have passed on "
                   "hardware so far" % cc.replace(".", ""))
        print("NOT_RUN: " + not_run)
    for name in want:
        kind = name.split("_")[0]
        print("  %-22s " % name, end="", flush=True)
        row = ck(os.path.join(KIT, "kernels", name), kind)
        row = R.result_row(name, sums[name], kind, row)
        print(row["verdict"] + ("  %d/%d words checked" % (row["checked"] - row["mismatches"], row["checked"])
                                if row["checked"] else "  " + (row["error"] or ""))
              + ("  %.3f ms, %.1f GB/s" % (row["kernel_ms"], row["gbps"]) if row["gbps"] else ""))
        results.append(row)

    # 4. the receipt
    now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    rec = R.seal({
        "schema": R.SCHEMA, "origin": "kit-run", "path": R.PATH_LABEL, "provider": o.provider,
        "kit": {"repo": R.REPO, "commit": commit, "modified": modified,
                "kernels_sha256sums": R.sha256_file(os.path.join(KIT, "kernels", "SHA256SUMS"))},
        "machine": machine,
        "run": {"utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "driver": probe["driver"],
                "python": platform.python_version()},
        "submitter": {"signed_off_by": sign, "statement": R.STATEMENT},
        "results": results, "not_run": not_run, "evidence": None,
    })
    os.makedirs(o.out, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", probe["device"].lower()).strip("-")[:40]
    fname = os.path.join(o.out, "%s-%s-%s.json" % (now.strftime("%Y%m%dT%H%M%SZ"), slug,
                                                    rec["receipt_sha256"][:8]))
    with open(fname, "w") as f:
        json.dump(rec, f, indent=1, sort_keys=True)
        f.write("\n")
    rel = os.path.relpath(fname, KIT)
    ok = all(r["verdict"] in ("PASS", "NEG_DETECTED") for r in results) and not modified and not not_run
    print("\nreceipt: %s" % rel)
    if modified:
        print("note: the kit has local changes, so the leaderboard will not accept this receipt.")
    print("check it:  python3 tools/validate.py %s" % rel)
    print("submit it: fork https://github.com/%s, then\n"
          "  git checkout -b receipt-%s && git add %s && git commit -s -m 'receipt: %s' && git push\n"
          "  and open a pull request (the commit's Signed-off-by must equal \"%s\")."
          % (R.REPO, rec["receipt_sha256"][:8], rel, probe["device"], sign))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
