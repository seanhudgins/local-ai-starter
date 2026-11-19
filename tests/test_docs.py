"""The model registry is well formed and the generated doc tables match it."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_spec = importlib.util.spec_from_file_location("docs_gen", Path(__file__).parent.parent / "ops" / "docs.py")
dg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dg)

REG = json.loads(dg.REGISTRY.read_text(encoding="utf-8"))


def test_registry_is_well_formed():
    tags = [m["tag"] for m in REG["models"]]
    assert len(tags) == len(set(tags))
    for m in REG["models"]:
        assert m["machine"] in REG["machines"], m["tag"]
        assert len(m["country"]) == 2 and m["maker"], m["tag"]  # the model-origin rule needs both
        assert m["status"] in {"active", "testing", "retire-candidate", "retired"}, m["tag"]


def test_generated_tables_are_current():
    assert dg.main(["--check"]) == 0, "run: uv run ops/docs.py"


def test_regenerate_replaces_only_the_block():
    text = "before\n<!-- generated:readme-pc (x) -->\nstale\n<!-- /generated -->\nafter\n"
    out = dg.regenerate(text, REG)
    assert out.startswith("before\n") and out.endswith("<!-- /generated -->\nafter\n")
    assert "stale" not in out and "`gemma4:12b`" in out
