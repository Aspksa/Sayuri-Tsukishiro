#!/usr/bin/env python3
"""Project/module versions; Python 3.10+, standard library and Git only."""

import argparse
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys


class VersionError(ValueError):
    pass


def git(root, *args):
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, check=False
    )
    if result.returncode:
        raise VersionError(result.stderr.decode("utf-8", "replace").strip())
    return result.stdout.decode("utf-8")


def resolve_ref(root, ref):
    return git(root, "rev-parse", "--verify", "--end-of-options", ref + "^{commit}").strip()


def read(root, path, ref=None, optional=False):
    if ref:
        if not git(root, "ls-tree", ref, "--", path).strip():
            if optional:
                return None
            raise VersionError(f"Missing {path} at {ref}")
        return git(root, "show", f"{ref}:{path}")
    file = root / path
    if not file.resolve().is_relative_to(root.resolve()):
        raise VersionError(f"Path escapes repository: {path}")
    if file.is_symlink():
        raise VersionError(f"Version metadata must be a regular file: {path}")
    if not file.exists() and optional:
        return None
    return file.read_text(encoding="utf-8")


def parse_version(text):
    value = text.strip()
    if not re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", value):
        raise VersionError(f"Expected MAJOR.MINOR.PATCH, got {value!r}")
    return tuple(map(int, value.split(".")))


def format_version(value):
    return ".".join(map(str, value))


def catalog(root, ref=None, allow_legacy=False):
    project = read(root, "VERSION", ref, optional=allow_legacy)
    config = read(root, "MODULES.json", ref, optional=allow_legacy)
    if project is None and config is None:
        return {}
    if project is None or config is None:
        raise VersionError("VERSION and MODULES.json must both exist")
    data = json.loads(config)
    if data.get("schema_version") != 1 or not isinstance(data.get("modules"), list):
        raise VersionError("Invalid MODULES.json schema")
    result = {"project": {"path": "", "file": "VERSION", "version": parse_version(project)}}
    paths = set()
    for item in data["modules"]:
        name, path = item.get("id", ""), item.get("path", "")
        if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9-]*", name):
            raise VersionError("Invalid module id")
        if name in result:
            raise VersionError(f"Duplicate/reserved module id: {name}")
        if (not isinstance(path, str) or not path or "\\" in path
                or any(p in ("", ".", "..", ".git") for p in path.split("/"))
                or ":" in path or PurePosixPath(path).is_absolute()):
            raise VersionError(f"Invalid module path: {path!r}")
        if path in paths:
            raise VersionError(f"Duplicate module path: {path}")
        paths.add(path)
        version_file = path + "/VERSION"
        result[name] = {"path": path, "file": version_file,
                        "version": parse_version(read(root, version_file, ref))}
    return result


def changed_files(root, base, target=None):
    args = ["diff", "--no-renames", "--name-only", "-z", base]
    if target:
        args.append(target)
    paths = set(git(root, *args, "--").split("\0")) - {""}
    if not target:
        paths.update(set(git(root, "ls-files", "--others", "--exclude-standard", "-z").split("\0")) - {""})
    return paths


def beneath(path, directory):
    return path.startswith(directory + "/")


def required_versions(root, before, after, changed, target=None):
    required = {"project"} if changed else set()
    for name, entry in after.items():
        previous = before.get(name)
        if name != "project" and (
            any(beneath(p, entry["path"]) for p in changed)
            or (previous and previous["path"] != entry["path"])
        ):
            required.add(name)
        if previous and entry["version"] < previous["version"]:
            raise VersionError(f"{name}: version cannot decrease")
    removed = set(before) - set(after)
    if removed:
        if target:
            files = git(root, "ls-tree", "-r", "--name-only", "-z", target).split("\0")
        else:
            files = git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z").split("\0")
            files = [p for p in files if (root / p).exists()]
        for name in removed:
            if any(beneath(p, before[name]["path"]) for p in files):
                raise VersionError(f"{name}: cannot unregister a module while its files remain")
    return required


def compare(root, base, target=None, bump=False, extra=()):
    before = catalog(root, base, allow_legacy=True)
    after = catalog(root, target)
    required = required_versions(root, before, after, changed_files(root, base, target), target)
    for name in extra:
        if name not in after or name == "project":
            raise VersionError(f"Unknown module: {name}")
        required.update(("project", name))
    pending = []
    for name in sorted(required):
        if name in before and after[name]["version"] == before[name]["version"]:
            pending.append(name)
    if pending and not bump:
        raise VersionError("Version increase required: " + ", ".join(pending))
    # Validate everything before writing. Repeating bump against the same base is idempotent.
    for name in pending:
        entry = after[name]
        major, minor, patch = entry["version"]
        entry["version"] = (major, minor, patch + 1)
        (root / entry["file"]).write_text(format_version(entry["version"]) + "\n", encoding="utf-8")
    return after


def report(entries):
    return {name: {"path": item["path"] or ".", "version_file": item["file"],
                   "version": format_version(item["version"])}
            for name, item in entries.items()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("show", help="Read version files; works in a downloaded ZIP without Git")
    bump = sub.add_parser("bump", help="Increase project and changed modules' PATCH once per base")
    bump.add_argument("--base", default="HEAD")
    bump.add_argument("--module", action="append", default=[], help="Also bump an affected dependent module")
    check = sub.add_parser("check", help="Reject changes without a version increase")
    check.add_argument("--base", default="HEAD")
    check.add_argument("--target", help="Commit/ref to check instead of the working tree")
    check.add_argument("--each-commit", action="store_true", help="Check every first-parent commit in base..target")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        if args.command == "show":
            result = catalog(root)
        else:
            base = resolve_ref(root, args.base)
            target = resolve_ref(root, args.target) if getattr(args, "target", None) else None
            if getattr(args, "each_commit", False):
                if not target:
                    raise VersionError("--each-commit requires --target")
                commits = git(root, "rev-list", "--reverse", "--first-parent", f"{base}..{target}").splitlines()
                for commit in commits:
                    parent = resolve_ref(root, commit + "^1")
                    compare(root, parent, commit)
                result = compare(root, base, target)
            else:
                result = compare(root, base, target, args.command == "bump", getattr(args, "module", ()))
        print(json.dumps(report(result), ensure_ascii=False, indent=2))
        return 0
    except (VersionError, OSError, ValueError, TypeError, AttributeError) as exc:
        print(f"Version check failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
