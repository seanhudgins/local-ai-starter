# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Check every locked Python dependency against the public vulnerability database (pip-audit).

    uv run ops/audit.py                 audit both lockfiles (CI runs this)
    uv run ops/audit.py --accept-all    record today's findings as accepted (after a person reviews them)

Pinning makes installs reproducible, but it also freezes known holes, so CI re-checks the pins on
every push. A finding fails the check unless it's listed in the lockfile's accepted-vulns.json with
a reason and a review date; an expired acceptance fails too, so nothing stays accepted by default.
The project's own lockfile has no acceptance file: its dependencies must stay clean.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PIP_AUDIT = "pip-audit==2.10.1"
LOCKS = {  # project folder -> acceptance file (None = must be clean)
    ROOT: None,
    ROOT / "services" / "open-webui": ROOT / "services" / "open-webui" / "accepted-vulns.json",
}
REVIEW_DAYS = 30


def findings(project: Path) -> dict[str, dict]:
    """{vuln id: {package, version, fix}} for one uv project's locked dependencies."""
    req = subprocess.run(
        ["uv", "export", "--quiet", "--frozen", "--no-hashes", "--no-emit-project"],
        cwd=project,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write(req)
    out = subprocess.run(
        ["uvx", "--quiet", PIP_AUDIT, "--disable-pip", "--no-deps", "-r", f.name, "-f", "json"],
        capture_output=True,
        text=True,
    )
    Path(f.name).unlink()
    if not out.stdout.strip():
        raise RuntimeError(f"pip-audit gave no output: {out.stderr.strip()[-300:]}")
    return parse(json.loads(out.stdout))


def parse(report: dict) -> dict[str, dict]:
    found = {}
    for dep in report.get("dependencies", []):
        for v in dep.get("vulns", []):
            found[v["id"]] = {"package": dep["name"], "version": dep["version"], "fix": v.get("fix_versions", [])}
    return found


def problems(found: dict[str, dict], accepted: dict[str, dict], today: date) -> list[str]:
    """What fails the check: findings nobody accepted, and acceptances past their review date."""
    out = []
    for vid, f in sorted(found.items()):
        a = accepted.get(vid)
        if a is None:
            fix = f", fixed in {f['fix'][-1]}" if f["fix"] else ", no fix yet"
            out.append(f"NEW      {vid}: {f['package']} {f['version']}{fix}")
        elif date.fromisoformat(a["review_by"]) < today:
            out.append(f"EXPIRED  {vid}: {f['package']} accepted until {a['review_by']} ({a['reason']})")
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--accept-all", action="store_true", help="accept current findings for REVIEW_DAYS")
    p.add_argument("--reason", default="reviewed: tailnet-only, single user; waiting for upstream to unpin")
    a = p.parse_args(argv)
    today, bad = date.today(), 0
    for project, accept_file in LOCKS.items():
        found = findings(project)
        accepted = json.loads(accept_file.read_text(encoding="utf-8")) if accept_file and accept_file.is_file() else {}
        if a.accept_all and accept_file:
            until = (today + timedelta(days=REVIEW_DAYS)).isoformat()
            accepted = {vid: {**f, "reason": a.reason, "review_by": until} for vid, f in sorted(found.items())}
            accept_file.write_text(json.dumps(accepted, indent=2) + "\n", encoding="utf-8")
            print(f"{project.relative_to(ROOT) or '.'}: {len(found)} findings accepted until {until}")
            continue
        issues = problems(found, accepted, today)
        name = str(project.relative_to(ROOT)) if project != ROOT else "project"
        print(f"{name}: {len(found)} known vulnerabilities, {len(found) - len(issues)} reviewed and accepted")
        for line in issues:
            print("  " + line)
        bad += len(issues)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
