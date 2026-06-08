"""PROMPTLINT command line interface.

Subcommands:
  lint     Run static rules over a prompt file.
  version  Print a deterministic content hash for drift detection.
  test     Run deterministic test cases from a JSON spec.
  check    CI gate: lint + tests together; exits non-zero on any failure.

Global flags: --version, --format {table,json}.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Optional

from . import TOOL_NAME, TOOL_VERSION
from .core import (
    parse_prompt,
    lint_prompt,
    version_prompt,
    run_tests,
    SEVERITY_ERROR,
)


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _emit(payload: Dict[str, Any], fmt: str, table_lines: List[str]) -> None:
    if fmt == "json":
        print(json.dumps(payload, indent=2))
    else:
        for line in table_lines:
            print(line)


def _cmd_lint(args: argparse.Namespace) -> int:
    doc = parse_prompt(_read(args.file), args.file)
    issues = lint_prompt(doc)
    errors = [i for i in issues if i.severity == SEVERITY_ERROR]
    payload = {
        "tool": TOOL_NAME,
        "command": "lint",
        "file": args.file,
        "ok": len(errors) == 0,
        "error_count": len(errors),
        "warning_count": len(issues) - len(errors),
        "issues": [i.to_dict() for i in issues],
    }
    lines = [f"lint {args.file}"]
    if not issues:
        lines.append("  clean - no issues")
    for i in issues:
        lines.append(f"  {i.severity:7} {i.code}  L{i.line:<4} {i.message}")
    lines.append(f"  => {len(errors)} error(s), {len(issues) - len(errors)} warning(s)")
    _emit(payload, args.format, lines)
    return 1 if errors else 0


def _cmd_version(args: argparse.Namespace) -> int:
    doc = parse_prompt(_read(args.file), args.file)
    info = version_prompt(doc)
    payload = {"tool": TOOL_NAME, "command": "version", "ok": True, **info}
    lines = [
        f"version {args.file}",
        f"  declared : {info['declared_version']}",
        f"  model    : {info['model']}",
        f"  hash     : {info['hash']}",
        f"  short    : {info['short']}",
        f"  vars     : {', '.join(info['vars']) or '(none)'}",
    ]
    _emit(payload, args.format, lines)
    return 0


def _load_cases(args: argparse.Namespace) -> List[Dict[str, Any]]:
    if args.tests:
        data = json.loads(_read(args.tests))
        if isinstance(data, dict):
            return data.get("tests", [])
        if isinstance(data, list):
            return data
        return []
    return []


def _cmd_test(args: argparse.Namespace) -> int:
    doc = parse_prompt(_read(args.file), args.file)
    cases = _load_cases(args)
    results = run_tests(doc, cases)
    passed = sum(1 for r in results if r["passed"])
    ok = passed == len(results)
    payload = {
        "tool": TOOL_NAME,
        "command": "test",
        "file": args.file,
        "ok": ok,
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "results": results,
    }
    lines = [f"test {args.file}"]
    for r in results:
        mark = "PASS" if r["passed"] else "FAIL"
        lines.append(f"  [{mark}] {r['name']} ({r['rendered_chars']} chars)")
        for a in r["assertions"]:
            amark = "ok" if a["passed"] else "x"
            extra = f" - {a['detail']}" if a["detail"] else ""
            lines.append(f"      ({amark}) {a['name']} [{a['kind']}]{extra}")
    lines.append(f"  => {passed}/{len(results)} case(s) passed")
    _emit(payload, args.format, lines)
    return 0 if ok else 1


def _cmd_check(args: argparse.Namespace) -> int:
    """CI gate: lint (errors fail) + tests (failures fail)."""
    doc = parse_prompt(_read(args.file), args.file)
    issues = lint_prompt(doc)
    errors = [i for i in issues if i.severity == SEVERITY_ERROR]
    cases = _load_cases(args)
    results = run_tests(doc, cases)
    passed = sum(1 for r in results if r["passed"])
    test_ok = passed == len(results)
    ok = (not errors) and test_ok
    payload = {
        "tool": TOOL_NAME,
        "command": "check",
        "file": args.file,
        "ok": ok,
        "lint": {
            "error_count": len(errors),
            "warning_count": len(issues) - len(errors),
            "issues": [i.to_dict() for i in issues],
        },
        "tests": {
            "total": len(results),
            "passed": passed,
            "failed": len(results) - passed,
            "results": results,
        },
    }
    lines = [f"check {args.file}"]
    lines.append(f"  lint : {len(errors)} error(s), {len(issues) - len(errors)} warning(s)")
    for i in issues:
        lines.append(f"    {i.severity:7} {i.code}  L{i.line:<4} {i.message}")
    lines.append(f"  test : {passed}/{len(results)} passed")
    for r in results:
        if not r["passed"]:
            lines.append(f"    FAIL {r['name']}")
    lines.append(f"  => GATE {'PASS' if ok else 'FAIL'}")
    _emit(payload, args.format, lines)
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=TOOL_NAME,
        description="Lint, version, and test prompts as code with a CI gate.",
    )
    p.add_argument("--version", action="version",
                   version=f"{TOOL_NAME} {TOOL_VERSION}")
    p.add_argument("--format", choices=["table", "json"], default="table",
                   help="output format (default: table)")
    sub = p.add_subparsers(dest="command", required=True)

    pl = sub.add_parser("lint", help="run static rules over a prompt file")
    pl.add_argument("file")
    pl.set_defaults(func=_cmd_lint)

    pv = sub.add_parser("version", help="print a content hash for drift detection")
    pv.add_argument("file")
    pv.set_defaults(func=_cmd_version)

    pt = sub.add_parser("test", help="run deterministic test cases")
    pt.add_argument("file")
    pt.add_argument("--tests", help="path to a JSON test spec", required=True)
    pt.set_defaults(func=_cmd_test)

    pc = sub.add_parser("check", help="CI gate: lint + tests together")
    pc.add_argument("file")
    pc.add_argument("--tests", help="path to a JSON test spec")
    pc.set_defaults(func=_cmd_check)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except FileNotFoundError as e:
        print(json.dumps({"tool": TOOL_NAME, "ok": False,
                          "error": f"file not found: {e.filename}"})
              if args.format == "json" else f"error: file not found: {e.filename}",
              file=sys.stderr)
        return 2
    except (ValueError, json.JSONDecodeError) as e:
        print(json.dumps({"tool": TOOL_NAME, "ok": False, "error": str(e)})
              if args.format == "json" else f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
