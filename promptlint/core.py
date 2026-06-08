"""PROMPTLINT engine: parse, lint, version, and test prompts as code.

A prompt file is a small text document with an optional front-matter header
fenced by lines of '---'. The header holds key: value metadata (notably
`model:` and `vars:`). The body is the prompt template, which may reference
variables with {{name}} placeholders.

Nothing here hits the network: 'tests' are deterministic local assertions over
the rendered prompt text (contains / not_contains / max_chars / regex /
vars_resolved), so promptlint can sit in a CI gate as a fast, hermetic check.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"

_VAR_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")
# Bare single-brace placeholders are a common authoring mistake.
_SINGLE_BRACE_RE = re.compile(r"(?<!\{)\{\s*[a-zA-Z_][a-zA-Z0-9_]*\s*\}(?!\})")
_TODO_RE = re.compile(r"\b(TODO|FIXME|XXX|TBD)\b")
_TRAILING_WS_RE = re.compile(r"[ \t]+$", re.MULTILINE)


@dataclass
class Rule:
    code: str
    message: str
    severity: str = SEVERITY_WARNING


@dataclass
class LintIssue:
    code: str
    severity: str
    message: str
    line: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AssertResult:
    name: str
    kind: str
    passed: bool
    detail: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PromptDoc:
    path: str
    meta: Dict[str, Any] = field(default_factory=dict)
    body: str = ""
    raw: str = ""

    @property
    def declared_vars(self) -> Dict[str, str]:
        v = self.meta.get("vars", {})
        return v if isinstance(v, dict) else {}

    @property
    def used_vars(self) -> List[str]:
        seen: List[str] = []
        for m in _VAR_RE.finditer(self.body):
            name = m.group(1)
            if name not in seen:
                seen.append(name)
        return seen


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if value == "":
        return ""
    if (value[0], value[-1]) in (("\"", "\""), ("'", "'")) and len(value) >= 2:
        return value[1:-1]
    low = value.lower()
    if low in ("true", "false"):
        return low == "true"
    if low in ("null", "none", "~"):
        return None
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


def _parse_header(header: str) -> Dict[str, Any]:
    """Tiny YAML-ish parser: top-level `key: value` plus one nested level for
    `vars:` defined with two-space-indented `name: value` lines."""
    meta: Dict[str, Any] = {}
    current_block: Optional[str] = None
    for line in header.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent == 0:
            if ":" not in line:
                continue
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip()
            if val == "":
                meta[key] = {}
                current_block = key
            else:
                meta[key] = _parse_scalar(val)
                current_block = None
        else:
            if current_block is None or not isinstance(meta.get(current_block), dict):
                continue
            if ":" not in line:
                continue
            key, _, val = line.strip().partition(":")
            meta[current_block][key.strip()] = _parse_scalar(val)
    return meta


def parse_prompt(text: str, path: str = "<string>") -> PromptDoc:
    """Split optional front matter from the prompt body."""
    raw = text
    body = text
    meta: Dict[str, Any] = {}
    stripped = text.lstrip("﻿")
    if stripped.startswith("---"):
        lines = stripped.splitlines()
        # find closing fence after line 0
        close = None
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                close = i
                break
        if close is not None:
            header = "\n".join(lines[1:close])
            body = "\n".join(lines[close + 1:])
            meta = _parse_header(header)
    return PromptDoc(path=path, meta=meta, body=body, raw=raw)


def render_prompt(doc: PromptDoc, overrides: Optional[Dict[str, Any]] = None) -> Tuple[str, List[str]]:
    """Substitute {{vars}} from declared defaults + overrides.
    Returns (rendered_text, unresolved_var_names)."""
    values: Dict[str, Any] = {}
    for k, v in doc.declared_vars.items():
        values[k] = v
    if overrides:
        values.update(overrides)
    unresolved: List[str] = []

    def repl(m: "re.Match[str]") -> str:
        name = m.group(1)
        if name in values and values[name] is not None:
            return str(values[name])
        if name not in unresolved:
            unresolved.append(name)
        return m.group(0)

    rendered = _VAR_RE.sub(repl, doc.body)
    return rendered, unresolved


def lint_prompt(doc: PromptDoc) -> List[LintIssue]:
    """Run the static rule set over a parsed prompt."""
    issues: List[LintIssue] = []
    body = doc.body

    if body.strip() == "":
        issues.append(LintIssue("PL001", SEVERITY_ERROR, "Prompt body is empty", 1))

    if "model" not in doc.meta or not doc.meta.get("model"):
        issues.append(LintIssue("PL002", SEVERITY_WARNING,
                                "No `model:` declared in front matter", 1))

    # Variables used in body but not declared in front matter.
    declared = set(doc.declared_vars.keys())
    for name in doc.used_vars:
        if name not in declared:
            line = _line_of(body, "{{" + name)
            issues.append(LintIssue("PL010", SEVERITY_ERROR,
                                    f"Variable '{name}' used but not declared in vars:", line))

    # Declared but unused variables.
    used = set(doc.used_vars)
    for name in declared:
        if name not in used:
            issues.append(LintIssue("PL011", SEVERITY_WARNING,
                                    f"Variable '{name}' declared but never used", 1))

    # Single-brace placeholders (likely meant to be {{...}}).
    for m in _SINGLE_BRACE_RE.finditer(body):
        line = _line_of(body, m.group(0))
        issues.append(LintIssue("PL012", SEVERITY_WARNING,
                                f"Single-brace placeholder '{m.group(0)}' "
                                f"- did you mean '{{{m.group(0)}}}'?", line))

    # Unfinished work markers.
    for m in _TODO_RE.finditer(body):
        line = _line_of(body, m.group(0))
        issues.append(LintIssue("PL020", SEVERITY_WARNING,
                                f"Unresolved marker '{m.group(0)}' in prompt body", line))

    # Trailing whitespace.
    tw = list(_TRAILING_WS_RE.finditer(body))
    if tw:
        line = body[:tw[0].start()].count("\n") + 1
        issues.append(LintIssue("PL030", SEVERITY_WARNING,
                                f"Trailing whitespace on {len(tw)} line(s)", line))

    # Very long prompts are a smell worth flagging.
    if len(body) > 8000:
        issues.append(LintIssue("PL031", SEVERITY_WARNING,
                                f"Prompt body is large ({len(body)} chars)", 1))

    issues.sort(key=lambda i: (i.line, i.code))
    return issues


def _line_of(text: str, needle: str) -> int:
    idx = text.find(needle)
    if idx < 0:
        return 1
    return text[:idx].count("\n") + 1


def version_prompt(doc: PromptDoc) -> Dict[str, Any]:
    """Compute a deterministic content hash + declared version for drift detection."""
    norm = doc.body.strip().replace("\r\n", "\n")
    digest = hashlib.sha256(norm.encode("utf-8")).hexdigest()
    return {
        "path": doc.path,
        "declared_version": doc.meta.get("version", "0.0.0"),
        "model": doc.meta.get("model"),
        "hash": "sha256:" + digest,
        "short": digest[:12],
        "body_chars": len(doc.body),
        "vars": sorted(doc.declared_vars.keys()),
    }


def _run_assertion(name: str, spec: Dict[str, Any], rendered: str,
                   unresolved: List[str]) -> AssertResult:
    kind = spec.get("kind", "")
    if kind == "contains":
        needle = str(spec.get("value", ""))
        ok = needle in rendered
        return AssertResult(name, kind, ok,
                            "" if ok else f"expected to contain {needle!r}")
    if kind == "not_contains":
        needle = str(spec.get("value", ""))
        ok = needle not in rendered
        return AssertResult(name, kind, ok,
                            "" if ok else f"should not contain {needle!r}")
    if kind == "regex":
        pat = str(spec.get("value", ""))
        ok = re.search(pat, rendered) is not None
        return AssertResult(name, kind, ok,
                            "" if ok else f"no match for /{pat}/")
    if kind == "max_chars":
        limit = int(spec.get("value", 0))
        ok = len(rendered) <= limit
        return AssertResult(name, kind, ok,
                            "" if ok else f"{len(rendered)} > {limit} chars")
    if kind == "min_chars":
        limit = int(spec.get("value", 0))
        ok = len(rendered) >= limit
        return AssertResult(name, kind, ok,
                            "" if ok else f"{len(rendered)} < {limit} chars")
    if kind == "vars_resolved":
        ok = len(unresolved) == 0
        return AssertResult(name, kind, ok,
                            "" if ok else f"unresolved: {', '.join(unresolved)}")
    return AssertResult(name, kind or "unknown", False, f"unknown assertion kind {kind!r}")


def run_tests(doc: PromptDoc, cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Execute deterministic test cases against the rendered prompt.

    Each case: {name, vars: {...}, assert: [{name, kind, value}, ...]}.
    Returns one result dict per case with its assertion outcomes.
    """
    results: List[Dict[str, Any]] = []
    for i, case in enumerate(cases):
        cname = case.get("name", f"case-{i + 1}")
        overrides = case.get("vars", {}) or {}
        rendered, unresolved = render_prompt(doc, overrides)
        asserts = case.get("assert", []) or []
        ar: List[AssertResult] = []
        for j, spec in enumerate(asserts):
            aname = spec.get("name", f"{spec.get('kind', 'assert')}-{j + 1}")
            ar.append(_run_assertion(aname, spec, rendered, unresolved))
        passed = all(a.passed for a in ar) if ar else True
        results.append({
            "name": cname,
            "passed": passed,
            "rendered_chars": len(rendered),
            "unresolved_vars": unresolved,
            "assertions": [a.to_dict() for a in ar],
        })
    return results
