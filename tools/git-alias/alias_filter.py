#!/usr/bin/env python3
"""Keep private names off GitHub while the working copy stays readable (a git clean/smudge filter).

Real names (machine names, ISP and network names, people) are swapped for placeholders like
`{{alias:pc}}` when a file goes into a commit, and swapped back when it comes out onto disk. GitHub
only ever stores the placeholders; your folders, and any AI working in them, show the real names.

The map of real name -> placeholder lives OUTSIDE every repo, one copy per machine:
    ~/.config/localai/aliases.json      {"terms": {"MYPC": "pc", "ExampleISP": "isp-primary"}}

    python3 alias_filter.py install     turn the filter on in this clone (once per clone)
    python3 alias_filter.py clean       stdin -> stdout, real -> placeholder (git runs this)
    python3 alias_filter.py smudge      stdin -> stdout, placeholder -> real (git runs this)
    python3 alias_filter.py guard       pre-commit: block staged text that still holds a real name
    python3 alias_filter.py show        list the map

Standard library only. The same file is copied into each repo (.githooks/alias_filter.py); the
source, with tests, is local-ai's tools/git-alias/.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path


def map_path() -> Path:
    """Where this machine's map lives (read each time, so LOCALAI_ALIASES can point elsewhere)."""
    return Path(os.environ.get("LOCALAI_ALIASES") or Path.home() / ".config" / "localai" / "aliases.json")


PLACEHOLDER = "{{{{alias:{}}}}}"  # -> {{alias:pc}}
KEY = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def load(path: Path | None = None) -> dict[str, str]:
    """{real name: placeholder key}; empty if this machine has no map."""
    path = path or map_path()
    if not path.is_file():
        return {}
    terms = json.loads(path.read_text(encoding="utf-8")).get("terms", {})
    keys = list(terms.values())
    bad = [k for k in keys if not KEY.match(k)]
    if bad or len(set(keys)) != len(keys):
        raise SystemExit(f"alias map {path}: keys must be unique, lowercase a-z 0-9 '-' (bad: {bad or 'duplicates'})")
    return terms


def _pattern(term: str) -> str:
    """Whole-word match where the term starts/ends with a letter or digit ("Ann" not in "Annual")."""
    left = r"(?<![A-Za-z0-9])" if term[0].isalnum() else ""
    right = r"(?![A-Za-z0-9])" if term[-1].isalnum() else ""
    return left + re.escape(term) + right


def clean(text: str, terms: dict[str, str]) -> str:
    for real in sorted(terms, key=len, reverse=True):  # longest first: "HomeNet-IoT" before "HomeNet"
        placeholder = PLACEHOLDER.format(terms[real])
        text = re.sub(_pattern(real), placeholder.replace("\\", r"\\"), text)
    return text


def smudge(text: str, terms: dict[str, str]) -> str:
    back = {k: real for real, k in terms.items()}
    return re.sub(r"\{\{alias:([a-z0-9-]+)\}\}", lambda m: back.get(m.group(1), m.group(0)), text)


def guard(terms: dict[str, str]) -> list[str]:
    """Real names in the staged (already cleaned) content of text files: what would reach GitHub."""
    files = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"], capture_output=True, text=True, check=True
    ).stdout.splitlines()
    hits = []
    for f in files:
        blob = subprocess.run(["git", "show", f":{f}"], capture_output=True, check=True).stdout
        try:
            text = blob.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for real in terms:
            if re.search(_pattern(real), text):
                hits.append(f"{f}: {real}")
    return hits


def install() -> None:
    """Point this clone's filter at this script and re-check-out files so they show real names."""
    me = Path(__file__).resolve()
    cmd = f'"{sys.executable}" "{me}"'
    for k, v in {
        "filter.alias.clean": f"{cmd} clean",
        "filter.alias.smudge": f"{cmd} smudge",
        "filter.alias.required": "true",  # a failing filter stops git instead of passing text through
    }.items():
        subprocess.run(["git", "config", k, v], check=True)
    if not load():
        print(
            f"NOTE  no alias map at {map_path()}: files keep their placeholders until you add one (see the docstring)."
        )
    # Re-check-out tracked files so the smudge filter runs on them (the working tree must be clean).
    dirty = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, check=True).stdout
    if dirty.strip():
        print("NOTE  uncommitted changes: commit them, then run `git checkout -- .` to show real names.")
        return
    tracked = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True).stdout.splitlines()
    for f in tracked:
        Path(f).unlink(missing_ok=True)
    subprocess.run(["git", "checkout", "--", "."], check=True)
    print("alias filter on: commits store placeholders, files on disk show real names.")


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd in ("clean", "smudge"):
        data = sys.stdin.buffer.read()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            sys.stdout.buffer.write(data)  # binary files pass through untouched
            return 0
        terms = load()
        out = clean(text, terms) if cmd == "clean" else smudge(text, terms)
        sys.stdout.buffer.write(out.encode("utf-8"))
        return 0
    if cmd == "guard":
        terms = load()
        if not terms:
            print(
                f"alias guard: no map at {map_path()}; can't check for private names. Commit blocked.", file=sys.stderr
            )
            return 1
        hits = guard(terms)
        if hits:
            print(
                "alias guard: private names would reach GitHub. Is the filter on? (alias_filter.py install)",
                file=sys.stderr,
            )
            print("\n".join("  " + h for h in hits), file=sys.stderr)
            return 1
        return 0
    if cmd == "install":
        install()
        return 0
    if cmd == "show":
        for real, k in sorted(load().items(), key=lambda x: x[1]):
            print(f"{PLACEHOLDER.format(k):28s} {real}")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
