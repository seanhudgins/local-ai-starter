"""Rule checks for eval items (evals/sets/*.jsonl). Pure Python, no model calls.

An item's `checks` list is applied to a model's reply; each check returns a CheckResult. Judgment
items also have a `grader` rubric, scored separately by a grader model. Check types:

    exact_label        reply is exactly `expected` (case, quotes and trailing punctuation ignored)
    must_contain       every regex in `patterns` is found (case-insensitive)
    must_not_contain   no regex in `patterns` is found (case-insensitive)
    json_schema        reply is JSON matching the item's `output_schema` (a small JSON Schema subset)
    field_equals       JSON field == `expected`; options: `casefold`, `unordered` (lists)
    field_range        JSON number field within `min` / `max`
    field_matches      JSON field (text, or list joined) matches regex `pattern` (case-insensitive)
    field_not_matches  ... does not match
    max_words          reply has at most `max` words
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any


@dataclass
class CheckResult:
    check: str
    ok: bool
    detail: str = ""


# ---------- reply parsing ----------


def parse_json(reply: str) -> Any:
    """JSON from a reply, tolerating a ```json fence or text around one object."""
    text = reply.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except ValueError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


def normalize_label(reply: str) -> str:
    """'card_fraud' from replies like ' "Card_Fraud". ' or '**card_fraud**'."""
    return re.sub(r"^[\s`'\"*]+|[\s`'\"*.!]+$", "", reply).lower()


# ---------- a small JSON Schema subset ----------

_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
    "null": type(None),
}


def _type_ok(value: Any, expected: str) -> bool:
    if expected in ("number", "integer"):
        if isinstance(value, bool) or not isinstance(value, int | float):
            return False
        return expected == "number" or float(value).is_integer()
    return isinstance(value, _TYPES[expected])


def schema_errors(value: Any, schema: dict, path: str = "$") -> list[str]:
    """Errors for the subset used here: type, enum, required, properties, items, min/max, maxLength, pattern."""
    errors: list[str] = []
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_type_ok(value, t) for t in types):
            return [f"{path}: expected {'/'.join(types)}, got {type(value).__name__}"]
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} not in {schema['enum']}")
    if isinstance(value, dict):
        errors += [f"{path}: missing {k!r}" for k in schema.get("required", []) if k not in value]
        for key, sub in schema.get("properties", {}).items():
            if key in value:
                errors += schema_errors(value[key], sub, f"{path}.{key}")
    if isinstance(value, list) and "items" in schema:
        for i, v in enumerate(value):
            errors += schema_errors(v, schema["items"], f"{path}[{i}]")
    if isinstance(value, int | float) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: {value} < {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: {value} > {schema['maximum']}")
    if isinstance(value, str):
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{path}: longer than {schema['maxLength']} characters")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{path}: doesn't match {schema['pattern']}")
    return errors


# ---------- checks ----------


def _equal(actual: Any, expected: Any, check: dict) -> bool:
    if check.get("casefold") and isinstance(actual, str) and isinstance(expected, str):
        return actual.strip().casefold() == expected.casefold()
    if check.get("unordered") and isinstance(actual, list) and isinstance(expected, list):
        return sorted(map(str, actual)) == sorted(map(str, expected))
    if isinstance(expected, float | int) and not isinstance(expected, bool) and isinstance(actual, int | float):
        return not isinstance(actual, bool) and abs(actual - expected) < 0.005
    return actual == expected


def _as_text(value: Any) -> str:
    return " ".join(map(str, value)) if isinstance(value, list) else str(value)


def run_check(check: dict, reply: str, item: dict) -> CheckResult:
    kind = check["type"]
    try:
        if kind == "exact_label":
            got = normalize_label(reply)
            return CheckResult(kind, got == check["expected"], f"got {got!r}, want {check['expected']!r}")
        if kind in ("must_contain", "must_not_contain"):
            found = [p for p in check["patterns"] if re.search(p, reply, re.I)]
            if kind == "must_contain":
                missing = [p for p in check["patterns"] if p not in found]
                return CheckResult(kind, not missing, f"missing {missing}" if missing else "")
            return CheckResult(kind, not found, f"found {found}" if found else "")
        if kind == "max_words":
            n = len(reply.split())
            return CheckResult(kind, n <= check["max"], f"{n} words (max {check['max']})")

        data = parse_json(reply)
        if kind == "json_schema":
            errors = schema_errors(data, item["output_schema"])
            return CheckResult(kind, not errors, "; ".join(errors[:3]))
        field = check["field"]
        if not isinstance(data, dict) or field not in data:
            return CheckResult(kind, False, f"no field {field!r}")
        value = data[field]
        if kind == "field_equals":
            return CheckResult(kind, _equal(value, check["expected"], check), f"{field}={value!r}")
        if kind == "field_range":
            ok = isinstance(value, int | float) and not isinstance(value, bool)
            ok = ok and value >= check.get("min", float("-inf")) and value <= check.get("max", float("inf"))
            return CheckResult(kind, ok, f"{field}={value!r}")
        if kind in ("field_matches", "field_not_matches"):
            hit = bool(re.search(check["pattern"], _as_text(value), re.I))
            return CheckResult(kind, hit == (kind == "field_matches"), f"{field}={value!r}")
    except (ValueError, KeyError, TypeError) as e:
        return CheckResult(kind, False, f"can't check: {e}")
    return CheckResult(kind, False, f"unknown check type {kind!r}")


# Look-alike characters models often emit (non-breaking hyphen, en/em dash, minus, non-breaking space).
_LOOKALIKES = str.maketrans(
    {
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
        "\u00a0": " ",
        "\u202f": " ",
        "\u2009": " ",
    }
)


def normalize(reply: str) -> str:
    """Map look-alike dashes and spaces to plain ones, so a check doesn't depend on which dash a model typed."""
    return reply.translate(_LOOKALIKES)


def run_checks(item: dict, reply: str) -> list[CheckResult]:
    reply = normalize(reply)
    return [run_check(c, reply, item) for c in item["checks"]]


def reference_reply(item: dict) -> str:
    """The item's reference answer as a model would send it (JSON answers serialized)."""
    ref = item["reference"]
    return ref if isinstance(ref, str) else json.dumps(ref)
