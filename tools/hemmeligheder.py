# Copied from kodeks (github.com/Piper1128/kodeks, commit 7bb7054, 2026-11-23)
# on 2026-11-23: tools/hemmeligheder.py. Byte for byte, with only this header
# added -- every other byte is the source's. kodeks' tools/tjek_kopier.py
# checks that this file still ends with the source.

#!/usr/bin/env python3
# Secrets in git: gate 1 of the family's analysis gates.
#
#   python tools/hemmeligheder.py --staged      # pre-commit: what this commit adds
#   python tools/hemmeligheder.py --historik    # every commit reachable from any ref
#   python tools/hemmeligheder.py --historik --repo <sti>
#
# It runs gitleaks (>= 8.19, measured on 8.30.1) and reads its JSON report.
# It never prints a secret: gitleaks is called with --redact, and only rule,
# file, line, commit and fingerprint are shown.
#
# Verdict is the exit code, as in the lab:
#   0  gitleaks ran and found nothing
#   1  gitleaks ran and found something
#   2  it could not be decided: gitleaks missing or too old, not a git
#      repository, an exit code gitleaks does not document, or a report that
#      contradicts the exit code. "Could not read" and "found nothing" must
#      never look alike from the call site.
#
# A known, accepted finding is silenced by its fingerprint in .gitleaksignore
# at the repository root (gitleaks reads that file itself). Every line there
# is a decision and should carry a comment saying who made it and why.
#
# This file is the SOURCE. K-010 forbids a project from importing Kodeks, so
# each project carries a copy with a provenance header prepended, and
# tools/tjek_kopier.py fails when a copy no longer ends with these bytes.
# Its drill is lab/experiments/drill_hemmeligheder.py in Kodeks.
#
# What a green run does NOT say: that the repository holds no secrets.
# gitleaks matches patterns; SecretBench measured 88 % recall for it
# (Basak et al. 2023), and a key followed by ")" was reported missed in
# 8.21.2 (Mishra 2026). The drill records what this version does with that
# form.

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

MIN_VERSION = (8, 19, 0)


def version(exe):
    try:
        p = subprocess.run([exe, "version"], capture_output=True, text=True, timeout=60)
    except OSError as e:
        return None, "gitleaks kunne ikke startes: %s" % e
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", p.stdout + p.stderr)
    if p.returncode != 0 or not m:
        return None, "gitleaks version gav ikke et versionsnummer (exit %d)" % p.returncode
    return tuple(int(x) for x in m.groups()), None


def koer(repo, staged, exe):
    """Return (exit code for the caller, findings list, message)."""
    v, fejl = version(exe)
    if v is None:
        return 2, [], fejl
    if v < MIN_VERSION:
        return 2, [], "gitleaks %s er for gammel; kræver mindst %s" % (
            ".".join(map(str, v)), ".".join(map(str, MIN_VERSION)))
    g = subprocess.run(["git", "-C", repo, "rev-parse", "--show-toplevel"],
                       capture_output=True, text=True)
    if g.returncode != 0:
        return 2, [], "ikke et git-repo: %s" % repo
    top = g.stdout.strip()

    fd, rapport = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        cmd = [exe, "git", "--redact", "--no-banner", "--log-level", "error",
               "--exit-code", "1", "-f", "json", "-r", rapport]
        if staged:
            cmd += ["--pre-commit", "--staged"]
        cmd.append(top)
        p = subprocess.run(cmd, capture_output=True, text=True)
        if p.returncode not in (0, 1):
            return 2, [], "gitleaks gav exit %d: %s" % (p.returncode, (p.stderr or p.stdout).strip()[:300])
        try:
            with open(rapport, encoding="utf-8") as f:
                fund = json.load(f)
        except (OSError, ValueError) as e:
            return 2, [], "gitleaks' rapport kunne ikke læses: %s" % e
    finally:
        os.unlink(rapport)

    if not isinstance(fund, list):
        return 2, [], "gitleaks' rapport er ikke en liste"
    if (p.returncode == 1) != bool(fund):
        return 2, fund, "gitleaks' exit %d og %d fund i rapporten modsiger hinanden" % (p.returncode, len(fund))
    return (1 if fund else 0), fund, "gitleaks %s" % ".".join(map(str, v))


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Hemmeligheder i git, via gitleaks. Exit 0 intet, 1 fund, 2 kunne ikke afgøres.")
    hvad = ap.add_mutually_exclusive_group(required=True)
    hvad.add_argument("--staged", action="store_true", help="det, denne commit tilføjer")
    hvad.add_argument("--historik", action="store_true", help="hver commit fra enhver ref")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--gitleaks", default=os.environ.get("GITLEAKS") or shutil.which("gitleaks") or "gitleaks")
    args = ap.parse_args()

    kode, fund, besked = koer(args.repo, args.staged, args.gitleaks)
    hvor = "staged" if args.staged else "historik"
    if kode == 2:
        print("hemmeligheder (%s): KUNNE IKKE AFGØRES — %s" % (hvor, besked), file=sys.stderr)
        print("hemmeligheder: installér gitleaks >= 8.19 (winget install Gitleaks.Gitleaks / github.com/gitleaks/gitleaks/releases)", file=sys.stderr)
        return 2
    for f in fund:
        print("  %s  %s:%s  commit %s  fingerprint %s" % (
            f.get("RuleID"), f.get("File"), f.get("StartLine"),
            (f.get("Commit") or "staged")[:10], f.get("Fingerprint")))
    print("hemmeligheder (%s): %d fund, %s" % (hvor, len(fund), besked))
    if fund:
        print("hemmeligheder: fjern hemmeligheden; er fundet accepteret, så skriv dens fingerprint i .gitleaksignore med en begrundelse.", file=sys.stderr)
    return kode


if __name__ == "__main__":
    sys.exit(main())
