# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Regenerate the model tables in the docs from router/models.json (one source of truth).

    uv run ops/docs.py            rewrite every generated block
    uv run ops/docs.py --check    exit 1 if any block is out of date (a test runs this)

A generated block sits between `<!-- generated:NAME ... -->` and `<!-- /generated -->`. Edit the
registry, not the block: the next run overwrites hand edits.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "router" / "models.json"
FILES = [ROOT / "README.md", ROOT / "docs" / "setup" / "MAC.md", ROOT / "docs" / "ARCHITECTURE.md"]
BLOCK = re.compile(r"(<!-- generated:([a-z-]+)[^>]*-->\n)(.*?)(<!-- /generated -->)", re.S)


def table(header: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    return "\n".join(lines + ["| " + " | ".join(r) + " |" for r in rows]) + "\n"


def render(name: str, reg: dict) -> str:
    models, machines = reg["models"], reg["machines"]
    on = lambda machine: [m for m in models if m["machine"] == machine and m["status"] != "retired"]  # noqa: E731
    if name in ("readme-mac", "readme-pc"):
        rows = on(name.split("-")[1])
        cells = [[f"`{m['tag']}`", m["use"], "—" if m.get("embedding") else m["speed"]] for m in rows]
        return table(["Model", "For", "Speed"], cells)
    if name == "mac-models":
        return table(
            ["Tag", "Maker", "Size", "First load (sandbox)", "Speed"],
            [
                [f"`{m['tag']}`", f"{m['maker']} ({m['country']})", m["size"], m["first_load"], m["speed"]]
                for m in on("mac")
            ],
        )
    if name == "arch-measured":
        rows = [m for machine in machines for m in on(machine) if not m.get("embedding")]
        return table(
            ["Machine", "Model", "Output speed", "Notes"],
            [[machines[m["machine"]]["label"], f"`{m['tag']}`", m["speed"], m["notes"]] for m in rows],
        )
    raise ValueError(f"unknown generated block {name!r}")


def regenerate(text: str, reg: dict) -> str:
    return BLOCK.sub(lambda m: m.group(1) + render(m.group(2), reg) + m.group(4), text)


def origin(tag: str, reg: dict | None = None) -> str:
    """Country code of a model's maker ("" if it isn't in the registry)."""
    reg = reg or json.loads(REGISTRY.read_text(encoding="utf-8"))
    return next((m["country"] for m in reg["models"] if m["tag"] == tag or m["tag"] == f"{tag}:latest"), "")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--check", action="store_true")
    a = p.parse_args(argv)
    reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
    stale = []
    for f in FILES:
        old = f.read_text(encoding="utf-8")
        new = regenerate(old, reg)
        if new != old:
            stale.append(f.relative_to(ROOT))
            if not a.check:
                f.write_text(new, encoding="utf-8")
    if a.check and stale:
        print(f"Out of date (run: uv run ops/docs.py): {', '.join(map(str, stale))}")
        return 1
    print("updated: " + ", ".join(map(str, stale)) if stale else "model tables up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
