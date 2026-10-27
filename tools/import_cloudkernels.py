#!/usr/bin/env python3
# tools/import_cloudkernels.py -- turn one CloudKernels rental run (aien-dev's own 2026-10-26 runs on
# rented GPUs, made before this kit existed) into a receipt with origin "cloudkernels-import".
#
#   import_cloudkernels.py RUN_DIR SPEND_LOG PROVIDER
#
# Only rows for kernels this kit ships are imported (vecadd/neg v7); the alu/ctl rows in the same run
# failed with CUDA_ERROR_ILLEGAL_INSTRUCTION and stay visible in the copied results.jsonl. The copied
# evidence goes to evidence/cloudkernels/<run>/: results.jsonl, driver-version.txt, nvidia-smi.txt and
# rental.txt (the run's CREATE/READY/DELETE lines from spend.log without the sandbox id). Those runs did
# not hash their output buffer or time the kernel, so output_sha256 and timing are null. The cubin hashes
# are this kit's SHA256SUMS: the run predates hashing in the receipt, and the files it loaded were last
# written before the run started (vecadd 22:37Z, neg 22:46Z; the runs began 23:13Z or later).
# The import is recorded in receipts/imports.sha256, which is the validator's allowlist for this origin.
# INTERIM host glue (Python), one-off; no Omega successor needed once kit runs replace imports.
import json, os, re, shutil, sys

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KIT, "tools"))
import receipt as R  # noqa: E402

run_dir, spend_log, provider = sys.argv[1], sys.argv[2], sys.argv[3]
run = os.path.basename(run_dir.rstrip("/"))
res = os.path.join(run_dir, "res")
sums = R.read_sums(os.path.join(KIT, "kernels", "SHA256SUMS"))
dest = os.path.join(KIT, "evidence", "cloudkernels", run)
os.makedirs(dest, exist_ok=True)
for f in ("results.jsonl", "driver-version.txt", "nvidia-smi.txt"):
    shutil.copyfile(os.path.join(res, f), os.path.join(dest, f))
with open(os.path.join(dest, "rental.txt"), "w") as out:
    for line in open(spend_log):
        if "\t" + run + "\t" in line and re.search(r"\t(CREATE|READY|DELETE)\t", line):
            out.write(re.sub(r"\tid=\S+", "", line.strip()) + "\n")

rows, mach = [], None
for line in open(os.path.join(res, "results.jsonl")):
    j = json.loads(line)
    name = os.path.basename(j["cubin"])
    mach = mach or j
    if name not in sums:
        continue
    j.pop("launch_s", None)  # wall clock around one launch, 0.1 ms timer resolution: not a timing
    j["first_bad"] = [list(t) for t in j.get("first_bad", [])]
    rows.append(R.result_row(name, sums[name], j["kind"], j))
rows.sort(key=lambda r: r["cubin"])

nvrm = open(os.path.join(res, "driver-version.txt")).readline().strip()
drv = re.search(r"\s(\d+\.\d+(?:\.\d+)?)\s", nvrm)
host = open(os.path.join(res, "host.txt")).read().splitlines()
os_name = next((l.split("=", 1)[1].strip('"') for l in host if l.startswith("PRETTY_NAME=")), None)
uname = next((l for l in host if l.startswith("Linux ")), "").split()
cpu = next((l.split(":", 1)[1].strip() for l in open(os.path.join(res, "cpuinfo.txt"))
            if l.startswith("model name")), None)
rec = R.seal({
    "schema": R.SCHEMA, "origin": "cloudkernels-import", "path": R.PATH_LABEL, "provider": provider,
    "kit": {"repo": None, "commit": None, "modified": False, "kernels_sha256sums": None},
    "machine": {"gpu": mach["device"], "cc": mach["cc"], "cuda_driver_api": mach["cuda_driver_api"],
                "driver_version": drv.group(1) if drv else None, "nvrm": nvrm, "os": os_name,
                "kernel": uname[2] if len(uname) > 2 else None, "arch": uname[-2] if uname else None,
                "cpu": cpu},
    "run": {"utc": host[0].strip(), "driver": "libcuda", "python": None},
    "submitter": {"signed_off_by": "Aien agents, CloudKernels import <aien@aienos.com>",
                  "statement": "Imported from aien-dev's own CloudKernels run %s; not run with this kit." % run},
    "results": rows, "not_run": None,
    "evidence": {
        "source": "CloudKernels rental run %s (aien-dev, 2026-10-26), harness ck.py, through NVIDIA libcuda" % run,
        "files": [{"path": "evidence/cloudkernels/%s/%s" % (run, f), "sha256": R.sha256_file(os.path.join(dest, f))}
                  for f in sorted(os.listdir(dest))],
        "note": "Kit kernels only; alu/ctl rows of the same run are in results.jsonl. No output hash or "
                "kernel timing was recorded by that harness.",
    },
})
slug = re.sub(r"[^a-z0-9]+", "-", mach["device"].lower()).strip("-")
fname = os.path.join(KIT, "receipts", "%s-%s-%s.json" % (rec["run"]["utc"].replace("-", "").replace(":", ""),
                                                         slug, rec["receipt_sha256"][:8]))
with open(fname, "w") as f:
    json.dump(rec, f, indent=1, sort_keys=True)
    f.write("\n")
with open(os.path.join(KIT, "receipts", "imports.sha256"), "a") as f:
    f.write("%s  %s\n" % (rec["receipt_sha256"], os.path.basename(fname)))
print(fname)
