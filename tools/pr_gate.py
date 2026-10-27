#!/usr/bin/env python3
# tools/pr_gate.py -- the rules for a pull request that submits receipts. CI runs this file from the
# base branch (workflow receipts.yml, pull_request_target) and treats the pull request as data only:
# nothing from the pull request is executed.
#
#   pr_gate.py --pr PR_CHECKOUT --base BASE_SHA --head HEAD_SHA --assoc AUTHOR_ASSOCIATION
#
# Rules:
#   * receipts are append-only: a pull request may add receipts/*.json, never change or delete one;
#   * a contributor's pull request may change nothing but added receipts (maintainers, i.e. OWNER,
#     MEMBER or COLLABORATOR, may also change the kit, imports.sha256 and evidence/);
#   * every added receipt passes tools/validate.py, using the base branch's validator, the base branch's
#     kernels/SHA256SUMS, and the base branch's import allowlist (a maintainer's own list for theirs);
#   * the commit that adds a kit-run receipt carries "Signed-off-by: <the receipt's signed_off_by>".
# INTERIM host glue (Python); Omega successor: see DEPENDENCIES.md.
import argparse, json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import validate as V  # noqa: E402

MAINTAINER = {"OWNER", "MEMBER", "COLLABORATOR"}
RECEIPT = re.compile(r"receipts/[^/]+\.json")


def git(repo, *a):
    return subprocess.run(["git", "-C", repo, *a], check=True, capture_output=True, text=True).stdout


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pr", required=True)
    ap.add_argument("--base", required=True)
    ap.add_argument("--head", required=True)
    ap.add_argument("--assoc", required=True)
    o = ap.parse_args()
    trusted = os.path.dirname(HERE)
    maint = o.assoc in MAINTAINER
    errs = []
    added = []
    diff = git(o.pr, "diff", "--name-status", "--no-renames", "%s...%s" % (o.base, o.head))
    for line in diff.splitlines():
        status, path = line.split("\t", 1)
        if RECEIPT.fullmatch(path):
            if status == "A":
                added.append(path)
            else:
                errs.append("%s: receipts are append-only (status %s)" % (path, status))
        elif not maint:
            errs.append("%s: a receipt pull request may only add files under receipts/" % path)
    imports = os.path.join(o.pr if maint else trusted, "receipts", "imports.sha256")
    c = V.Checker(o.pr, os.path.join(trusted, "kernels", "SHA256SUMS"), imports, False)
    for path in added:
        try:
            rec = json.loads(git(o.pr, "show", "%s:%s" % (o.head, path)))
        except ValueError as x:
            errs.append("%s: not JSON (%s)" % (path, x))
            continue
        errs += ["%s: %s" % (path, m) for m in c.check(rec)]
        if not isinstance(rec, dict) or rec.get("origin") != "kit-run":
            continue
        who = (rec.get("submitter") or {}).get("signed_off_by")
        shas = git(o.pr, "log", "--format=%H", "--diff-filter=A", "%s..%s" % (o.base, o.head), "--", path).split()
        msgs = [git(o.pr, "log", "-1", "--format=%B", s) for s in shas]
        if not shas or not any(("Signed-off-by: %s" % who) in m.splitlines() for m in msgs):
            errs.append('%s: the commit adding it needs the line "Signed-off-by: %s" (git commit -s)' % (path, who))
        commit = str((rec.get("kit") or {}).get("commit"))
        if not re.fullmatch(r"[0-9a-f]{40}", commit) or subprocess.run(
                ["git", "-C", o.pr, "merge-base", "--is-ancestor", commit, o.base],
                          capture_output=True).returncode != 0:
            errs.append("%s: kit.commit %s is not on the base branch" % (path, commit))
    print("pull request adds %d receipt(s); author association %s" % (len(added), o.assoc))
    for e in errs:
        print("REJECT " + e)
    if not added and not maint:
        print("REJECT: no receipt added")
        return 1
    print("gate: %s" % ("FAIL" if errs else "PASS"))
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
