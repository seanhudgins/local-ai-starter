#!/usr/bin/env python3
"""Keep private names off GitHub while the working copy stays readable (a git clean/smudge filter).

Real names (machine names, ISP and network names, people) are swapped for placeholders like
`{{alias:pc}}` when a file goes into a commit, and swapped back when it comes out onto disk. GitHub
only ever stores the placeholders; your folders, and any AI working in them, show the real names.

The map of real name -> placeholder lives OUTSIDE every repo, one copy per machine:
    ~/.config/localai/aliases.json      {"terms": {"MYPC": "pc", "ExampleISP": "isp-primary"}}

The source of truth is one 1Password document ("git-alias-map" in "Agent Vault"; set LOCALAI_ALIASES_OP_ITEM
and LOCALAI_ALIASES_OP_VAULT to change it). Each machine's file is a copy pulled with `sync`. Every `op` call
runs as a 1Password service account that can open only that vault (token in the OS credential store,
service "localai-1password"); without the token, op falls back to the desktop app and Touch ID / Windows Hello.

    python3 alias_filter.py install     turn the filter and the repo's hooks on in this clone (once per clone)
    python3 alias_filter.py sync        pull the map from 1Password, then refresh files still showing placeholders;
                                        refuses if 1Password lost keys this machine has (sync --force accepts that)
    python3 alias_filter.py add REAL KEY  pull, add one name, push to 1Password (other machines then run sync)
    python3 alias_filter.py push        merge this machine's map into 1Password (never drops a key there;
                                        push --replace overwrites, for a deliberate removal)
    python3 alias_filter.py check       warn about placeholders on disk the map can't resolve (keys only, no names)
    python3 alias_filter.py clean       stdin -> stdout, real -> placeholder (git runs this)
    python3 alias_filter.py smudge      stdin -> stdout, placeholder -> real (git runs this)
    python3 alias_filter.py guard       pre-commit: block real names in staged text or file names, or a map
                                        missing a key the repo uses (from HEAD and the index, not files on disk)
    python3 alias_filter.py guard-msg FILE  commit-msg: block real names in the commit message or branch name
    python3 alias_filter.py show        list the map (prints real names: for the owner's eyes, not agents or logs)

Names match whole words, ignoring case ("Mypc" and "MYPC" both become {{alias:pc}}; a checkout shows the
map's spelling). UTF-8 and UTF-16 files (with a byte-order mark, as Windows PowerShell 5 writes) are filtered;
other binary files pass through. Every message names keys, never real names.

Standard library only. The same file is copied into each repo (.githooks/alias_filter.py); the
source, with tests, is local-ai's tools/git-alias/.
"""

from __future__ import annotations

import json
import os
import re
import shutil
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
        text = re.sub(_pattern(real), placeholder.replace("\\", r"\\"), text, flags=re.IGNORECASE)
    return text


def names_in(text: str, terms: dict[str, str]) -> list[str]:
    """Keys (never names) of the real names that appear in text, any case."""
    return sorted({k for real, k in terms.items() if re.search(_pattern(real), text, flags=re.IGNORECASE)})


def decode(data: bytes) -> tuple[str, str, bytes] | None:
    """(text, encoding, byte-order mark) for UTF-8 or BOM-marked UTF-16 content; None for anything else (binary)."""
    for bom, enc in ((b"\xff\xfe", "utf-16-le"), (b"\xfe\xff", "utf-16-be")):
        if data.startswith(bom):
            try:
                return data[len(bom) :].decode(enc), enc, bom
            except UnicodeDecodeError:
                return None
    try:
        return data.decode("utf-8"), "utf-8", b""
    except UnicodeDecodeError:
        return None


def smudge(text: str, terms: dict[str, str]) -> str:
    back = {k: real for real, k in terms.items()}
    return re.sub(r"\{\{alias:([a-z0-9-]+)\}\}", lambda m: back.get(m.group(1), m.group(0)), text)


def guard(terms: dict[str, str]) -> list[str]:
    """Real names in staged file names and in the staged (already cleaned) content: what would reach GitHub.
    Reported as "file: {{alias:key}}", never the name itself."""
    files = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"], capture_output=True, text=True, check=True
    ).stdout.splitlines()
    hits = []
    for f in files:
        hits += [f"{f} (file name): {PLACEHOLDER.format(k)}" for k in names_in(f, terms)]
        blob = subprocess.run(["git", "show", f":{f}"], capture_output=True, check=True).stdout
        decoded = decode(blob)
        if decoded is None:
            continue
        hits += [f"{f}: {PLACEHOLDER.format(k)}" for k in names_in(decoded[0], terms)]
    return hits


def guard_message(message: str, terms: dict[str, str]) -> list[str]:
    """Keys of real names in a commit message (git's comment lines skipped) or the current branch name."""
    text = "\n".join(line for line in message.splitlines() if not line.startswith("#"))
    branch = subprocess.run(["git", "symbolic-ref", "--short", "-q", "HEAD"], capture_output=True, text=True).stdout
    return [f"commit message: {PLACEHOLDER.format(k)}" for k in names_in(text, terms)] + [
        f"branch name: {PLACEHOLDER.format(k)}" for k in names_in(branch, terms)
    ]


def keys_in_repo() -> set[str]:
    """Placeholder keys in the committed (HEAD) and staged content: the keys the map must cover. Read from git,
    not the files on disk, where the smudge filter has already swapped known keys back into names (so a key
    dropped from the map would otherwise go unnoticed until its name was committed in clear)."""
    keys: set[str] = set()
    for where in (["--cached"], ["HEAD"]):
        r = subprocess.run(
            ["git", "grep", "-h", "-o", "-I", "-E", r"\{\{alias:[a-z0-9][a-z0-9-]*\}\}", *where]
            + ["--", ":(attr:filter=alias)"],  # only files the filter swaps back; others show placeholders anyway
            capture_output=True,
            text=True,
        )
        if r.returncode == 0:  # 1 = no match, 128 = no HEAD yet
            keys |= set(PLACEHOLDER_RE.findall(r.stdout))
    return keys


def install() -> None:
    """Point this clone's filter at this script, turn on the repo's hooks, and re-check-out filtered files so
    they show real names."""
    me = Path(__file__).resolve()
    cmd = f'"{sys.executable}" "{me}"'
    for k, v in {
        "filter.alias.clean": f"{cmd} clean",
        "filter.alias.smudge": f"{cmd} smudge",
        "filter.alias.required": "true",  # a failing filter stops git instead of passing text through
    }.items():
        subprocess.run(["git", "config", k, v], check=True)
    top = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True)
    if (Path(top.stdout.strip()) / ".githooks").is_dir():
        # Without this the guard, the commit-message check and gitleaks never run in this clone.
        subprocess.run(["git", "config", "core.hooksPath", ".githooks"], check=True)
        print("hooks on: core.hooksPath = .githooks")
    if not shutil.which("gitleaks"):
        print("WARN  gitleaks not found: the pre-commit hook will block every commit until it's installed.")
    if not load():
        print(
            f"NOTE  no alias map at {map_path()}: files keep their placeholders until you add one (see the docstring)."
        )
    # Re-check-out tracked files so the smudge filter runs on them (the working tree must be clean).
    dirty = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, check=True).stdout
    if dirty.strip():
        print("NOTE  uncommitted changes: commit them, then run `git checkout -- .` to show real names.")
        return
    filtered = _filtered_files()
    for f in filtered:  # only files the filter touches; everything else stays as it is
        Path(f).unlink(missing_ok=True)
    if filtered:
        subprocess.run(["git", "checkout", "--", *filtered], check=True)
    print("alias filter on: commits store placeholders, files on disk show real names.")


# ---- Drift check: placeholders on disk that this machine's map can't (or didn't yet) turn back into names ----

PLACEHOLDER_RE = re.compile(r"\{\{alias:([a-z0-9][a-z0-9-]*)\}\}")


def _filtered_files() -> list[str]:
    """Tracked files that go through the alias filter (per .gitattributes)."""
    tracked = subprocess.run(["git", "ls-files", "-z"], capture_output=True, text=True, check=True).stdout
    files = [f for f in tracked.split("\0") if f]
    if not files:
        return []
    out = subprocess.run(
        ["git", "check-attr", "-z", "filter", "--stdin"],
        input="\0".join(files),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split("\0")
    # -z output is path, attr, value triples
    return [out[i] for i in range(0, len(out) - 2, 3) if out[i + 2] == "alias"]


def check(terms: dict[str, str]) -> tuple[dict[str, list[str]], list[str]]:
    """({missing key: files}, [stale files]). Missing: the map lacks the key, run `sync`. Stale: the map has
    the key but the file was checked out before it did, so a refresh shows the name. Never returns real names."""
    known = set(terms.values())
    missing: dict[str, list[str]] = {}
    stale: list[str] = []
    for f in _filtered_files():
        try:
            text = Path(f).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        keys = set(PLACEHOLDER_RE.findall(text))
        for k in sorted(keys - known):
            missing.setdefault(k, []).append(f)
        if keys & known:
            stale.append(f)
    return missing, stale


def refresh(files: list[str]) -> list[str]:
    """Re-check-out unmodified files so the smudge filter shows real names. Returns files skipped (local edits)."""
    skipped = []
    for f in files:
        if subprocess.run(["git", "diff", "--quiet", "--", f]).returncode != 0:
            skipped.append(f)
            continue
        Path(f).unlink(missing_ok=True)
        subprocess.run(["git", "checkout", "--", f], check=True)
    return skipped


def report(missing: dict[str, list[str]], stale: list[str]) -> str:
    lines = []
    if missing:
        lines.append(f"alias map is missing {len(missing)} key(s) this repo uses: {', '.join(sorted(missing))}.")
        lines.append("  Run: python3 .githooks/alias_filter.py sync   (pulls the map from 1Password)")
    if stale:
        lines.append(f"{len(stale)} file(s) still show placeholders the map can resolve. Run sync to refresh them.")
    return "\n".join(lines)


# ---- 1Password: the shared source of truth ----


def _op_ref() -> list[str]:
    item = os.environ.get("LOCALAI_ALIASES_OP_ITEM", "git-alias-map")
    vault = os.environ.get("LOCALAI_ALIASES_OP_VAULT", "Agent Vault")  # a vault used only for agent tasks
    return [item] + (["--vault", vault] if vault else [])


# Service account: a 1Password identity that can open only the Agent Vault. Its token sits in the OS
# credential store (never a file or env file); with it, op runs as that account, with no Touch ID and no reach
# into any other vault. Without it, op falls back to the desktop-app sign-in (Touch ID / Windows Hello).
TOKEN_SERVICE, TOKEN_ACCOUNT = "localai-1password", "service-account"


def _service_token() -> str | None:
    """The service-account token from macOS Keychain or Windows Credential Manager, else None."""
    if sys.platform == "darwin":
        r = subprocess.run(
            ["security", "find-generic-password", "-s", TOKEN_SERVICE, "-a", TOKEN_ACCOUNT, "-w"],
            capture_output=True,
            text=True,
        )
        return r.stdout.strip() or None if r.returncode == 0 else None
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class CREDENTIAL(ctypes.Structure):
            _fields_ = [
                ("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR),
                ("Comment", wintypes.LPWSTR), ("LastWritten", wintypes.FILETIME),
                ("CredentialBlobSize", wintypes.DWORD), ("CredentialBlob", ctypes.POINTER(ctypes.c_char)),
                ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
                ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR),
            ]  # fmt: skip

        advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        pcred = ctypes.POINTER(CREDENTIAL)()
        if not advapi.CredReadW(TOKEN_SERVICE, 1, 0, ctypes.byref(pcred)):  # 1 = CRED_TYPE_GENERIC
            return None
        try:
            blob = ctypes.string_at(pcred.contents.CredentialBlob, pcred.contents.CredentialBlobSize)
            # cmdkey stores UTF-16; other tools may store UTF-8
            text = blob.decode("utf-16-le") if b"\x00" in blob else blob.decode("utf-8")
            return text.strip() or None
        finally:
            advapi.CredFree(pcred)
    return None


def _op_env() -> dict[str, str]:
    env = dict(os.environ)
    token = _service_token()
    if token:
        env["OP_SERVICE_ACCOUNT_TOKEN"] = token
    return env


def _op(*args: str) -> str:
    """Run the 1Password CLI as the service account if this machine has its token, else via the desktop app."""
    try:
        r = subprocess.run(["op", *args], capture_output=True, text=True, env=_op_env())
    except FileNotFoundError:
        raise SystemExit(
            "1Password CLI (op) not found. Install it, then store the service-account token "
            "(see README: Private names) or turn on Settings > Developer > Integrate with 1Password CLI."
        ) from None
    if r.returncode != 0:
        raise SystemExit(f"op {args[0]} {args[1] if len(args) > 1 else ''} failed: {r.stderr.strip()[:300]}")
    return r.stdout


def _op_exists(ref: list[str]) -> bool:
    try:
        return subprocess.run(["op", "item", "get", *ref], capture_output=True, env=_op_env()).returncode == 0
    except FileNotFoundError:
        return False


def _parse(text: str) -> dict[str, str]:
    """Validate map JSON the same way load() does (unique, simple keys)."""
    terms = json.loads(text).get("terms", {})
    keys = list(terms.values())
    bad = [k for k in keys if not KEY.match(k)]
    if bad or len(set(keys)) != len(keys):
        raise SystemExit(
            f"alias map from 1Password: keys must be unique, lowercase a-z 0-9 '-' (bad: {bad or 'duplicates'})"
        )
    return terms


def _write_map(terms: dict[str, str]) -> None:
    path = map_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"terms": terms}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def pull(force: bool = False) -> dict[str, str]:
    """Fetch the map from 1Password and save it as this machine's copy. Prints key changes, never names.
    Refuses (unless force) when 1Password lacks keys this machine has: dropping a key silently would let its
    name be committed in clear the next time a file using it is edited."""
    remote = _parse(_op("document", "get", *_op_ref()))
    before = set(load().values())
    after = set(remote.values())
    added, removed = sorted(after - before), sorted(before - after)
    if removed and not force:
        raise SystemExit(
            f"1Password's map lacks key(s) this machine has: {', '.join(removed)}. Nothing changed.\n"
            "  If another machine overwrote it by mistake: alias_filter.py push   (merges them back)\n"
            "  If the removal is deliberate:               alias_filter.py sync --force"
        )
    _write_map(remote)
    print(
        f"alias map synced: {len(after)} keys"
        + (f"; added {', '.join(added)}" if added else "")
        + (f"; removed {', '.join(removed)}" if removed else "")
    )
    return remote


def merge(remote: dict[str, str], local: dict[str, str]) -> dict[str, str]:
    """remote plus local's extra names. A name mapped to two keys, or a key used for two names, stops (keys only)."""
    out = dict(remote)
    owner = {k: real for real, k in remote.items()}
    for real, k in local.items():
        if real in out and out[real] != k:
            here, there = PLACEHOLDER.format(k), PLACEHOLDER.format(out[real])
            raise SystemExit(f"map conflict: one name is {here} here and {there} in 1Password")
        if k in owner and owner[k] != real:
            raise SystemExit(f"map conflict: key {k!r} stands for different names here and in 1Password")
        out[real], owner[k] = k, real
    return out


def push(terms: dict[str, str] | None = None, replace: bool = False) -> None:
    """Merge a map into 1Password (or overwrite it, with replace), creating the document the first time."""
    terms = load() if terms is None else terms
    if not terms:
        raise SystemExit(f"no alias map at {map_path()} to push")
    ref = _op_ref()
    exists = _op_exists(ref)
    if exists and not replace:
        terms = merge(_parse(_op("document", "get", *ref)), terms)
    _write_map(terms)
    path = str(map_path())
    if exists:
        _op("document", "edit", ref[0], path, *ref[1:])
    else:
        _op("document", "create", path, "--title", ref[0], *ref[1:])
    print(f"alias map pushed to 1Password ({len(terms)} keys). Other machines: run `alias_filter.py sync`.")


def add(real: str, key: str) -> None:
    """Pull first so another machine's additions aren't overwritten, then add one name and push."""
    if not KEY.match(key):
        raise SystemExit(f"key {key!r}: use lowercase a-z, 0-9 and '-'")
    terms = pull()
    if real in terms:
        raise SystemExit(f"that name is already mapped to {{{{alias:{terms[real]}}}}}")
    if key in terms.values():
        raise SystemExit(f"key {key!r} is already used; pick another")
    terms[real] = key
    push(terms)


def _in_filtered_repo() -> bool:
    r = subprocess.run(["git", "config", "--get", "filter.alias.smudge"], capture_output=True, text=True)
    return r.returncode == 0 and bool(r.stdout.strip())


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "check":  # post-checkout / post-merge hooks: warn only, never block
        msg = report(*check(load()))
        if msg:
            print(msg, file=sys.stderr)
        return 0
    if cmd == "sync":
        terms = pull(force="--force" in argv[2:])
        if _in_filtered_repo():
            _, stale = check(terms)
            skipped = refresh(stale)
            if stale:
                print(f"refreshed {len(stale) - len(skipped)} file(s) to show real names.")
            if skipped:
                print("not refreshed (local edits; commit, then `git checkout -- <file>`): " + ", ".join(skipped))
        return 0
    if cmd == "add" and len(argv) == 4:
        add(argv[2], argv[3])
        return 0
    if cmd == "push":
        push(replace="--replace" in argv[2:])
        return 0
    if cmd in ("clean", "smudge"):
        data = sys.stdin.buffer.read()
        decoded = decode(data)
        if decoded is None:
            sys.stdout.buffer.write(data)  # binary files pass through untouched
            return 0
        text, enc, bom = decoded
        terms = load()
        out = clean(text, terms) if cmd == "clean" else smudge(text, terms)
        sys.stdout.buffer.write(bom + out.encode(enc))
        return 0
    if cmd == "guard-msg" and len(argv) == 3:
        terms = load()
        hits = guard_message(Path(argv[2]).read_text(encoding="utf-8", errors="replace"), terms) if terms else []
        if hits:
            print("alias guard: private names in " + "; ".join(hits) + ". Reword using the key.", file=sys.stderr)
            return 1
        return 0
    if cmd == "guard":
        terms = load()
        if not terms:
            print(
                f"alias guard: no map at {map_path()}; can't check for private names. Commit blocked.", file=sys.stderr
            )
            return 1
        missing, _ = check(terms)
        for k in sorted(keys_in_repo() - set(terms.values())):  # e.g. a key dropped from the map
            missing.setdefault(k, ["(committed or staged content)"])
        if missing:  # a stale map means the guard below can't see every private name
            print("alias guard: " + report(missing, []) + "\nCommit blocked until the map is current.", file=sys.stderr)
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
