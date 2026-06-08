"""Smoke tests for PROMPTLINT. Standard library only, no network.

Run with: python -m unittest tests.test_smoke  (from the project root)
"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from promptlint import (  # noqa: E402
    TOOL_NAME,
    TOOL_VERSION,
    parse_prompt,
    lint_prompt,
    version_prompt,
    run_tests,
    SEVERITY_ERROR,
)
from promptlint.cli import main  # noqa: E402


SAMPLE = (
    "---\n"
    "model: claude-sonnet\n"
    "version: 1.0.0\n"
    "vars:\n"
    "  name: Alex\n"
    "---\n"
    "Hello {{name}}, welcome aboard.\n"
)


class ParseTest(unittest.TestCase):
    def test_front_matter_and_body(self):
        doc = parse_prompt(SAMPLE, "x.prompt")
        self.assertEqual(doc.meta["model"], "claude-sonnet")
        self.assertEqual(doc.declared_vars["name"], "Alex")
        self.assertIn("{{name}}", doc.body)
        self.assertEqual(doc.used_vars, ["name"])

    def test_no_front_matter(self):
        doc = parse_prompt("just a body {{x}}", "y.prompt")
        self.assertEqual(doc.meta, {})
        self.assertEqual(doc.used_vars, ["x"])


class LintTest(unittest.TestCase):
    def test_clean_prompt_has_no_errors(self):
        doc = parse_prompt(SAMPLE)
        issues = lint_prompt(doc)
        errors = [i for i in issues if i.severity == SEVERITY_ERROR]
        self.assertEqual(errors, [])

    def test_undeclared_var_is_error(self):
        doc = parse_prompt("---\nmodel: m\n---\nHi {{ghost}}")
        issues = lint_prompt(doc)
        codes = {i.code for i in issues if i.severity == SEVERITY_ERROR}
        self.assertIn("PL010", codes)

    def test_empty_body_is_error(self):
        doc = parse_prompt("---\nmodel: m\n---\n   ")
        codes = {i.code for i in lint_prompt(doc)}
        self.assertIn("PL001", codes)

    def test_single_brace_warning(self):
        doc = parse_prompt("---\nmodel: m\nvars:\n  t: x\n---\nUse {t} please")
        codes = {i.code for i in lint_prompt(doc)}
        self.assertIn("PL012", codes)


class VersionTest(unittest.TestCase):
    def test_hash_is_deterministic_and_drifts(self):
        a = version_prompt(parse_prompt(SAMPLE))
        b = version_prompt(parse_prompt(SAMPLE))
        self.assertEqual(a["hash"], b["hash"])
        self.assertTrue(a["hash"].startswith("sha256:"))
        changed = version_prompt(parse_prompt(SAMPLE.replace("welcome", "WELCOME")))
        self.assertNotEqual(a["hash"], changed["hash"])


class RunTestsTest(unittest.TestCase):
    def test_assertions_pass_and_fail(self):
        doc = parse_prompt(SAMPLE)
        cases = [
            {"name": "ok", "vars": {"name": "Jo"},
             "assert": [{"name": "has", "kind": "contains", "value": "Jo"}]},
            {"name": "bad",
             "assert": [{"name": "nope", "kind": "contains", "value": "zzz"}]},
        ]
        results = run_tests(doc, cases)
        self.assertTrue(results[0]["passed"])
        self.assertFalse(results[1]["passed"])

    def test_vars_resolved_assertion(self):
        doc = parse_prompt("---\nmodel: m\n---\nHi {{who}}")
        results = run_tests(doc, [
            {"name": "unresolved",
             "assert": [{"kind": "vars_resolved"}]},
        ])
        self.assertFalse(results[0]["passed"])


class CliTest(unittest.TestCase):
    def _write(self, text, suffix=".prompt"):
        fd, path = tempfile.mkstemp(suffix=suffix)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        self.addCleanup(lambda: os.remove(path))
        return path

    def test_version_flag(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            with self.assertRaises(SystemExit) as cm:
                main(["--version"])
        self.assertEqual(cm.exception.code, 0)
        self.assertIn(TOOL_VERSION, buf.getvalue())

    def test_lint_json_clean_exit_zero(self):
        path = self._write(SAMPLE)
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["--format", "json", "lint", path])
        self.assertEqual(rc, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["tool"], TOOL_NAME)
        self.assertTrue(payload["ok"])

    def test_lint_error_exit_nonzero(self):
        path = self._write("---\nmodel: m\n---\nHi {{ghost}}")
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["--format", "json", "lint", path])
        self.assertEqual(rc, 1)
        self.assertFalse(json.loads(buf.getvalue())["ok"])

    def test_check_gate_pass(self):
        ppath = self._write(SAMPLE)
        tpath = self._write(json.dumps({"tests": [
            {"name": "c", "vars": {"name": "Jo"},
             "assert": [{"kind": "contains", "value": "Jo"}]},
        ]}), suffix=".json")
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["--format", "json", "check", ppath, "--tests", tpath])
        self.assertEqual(rc, 0)
        self.assertTrue(json.loads(buf.getvalue())["ok"])

    def test_check_gate_fail_on_test(self):
        ppath = self._write(SAMPLE)
        tpath = self._write(json.dumps({"tests": [
            {"name": "c",
             "assert": [{"kind": "contains", "value": "absent"}]},
        ]}), suffix=".json")
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["--format", "json", "check", ppath, "--tests", tpath])
        self.assertEqual(rc, 1)
        self.assertFalse(json.loads(buf.getvalue())["ok"])

    def test_missing_file_exit_two(self):
        rc = main(["--format", "json", "lint", "/no/such/file.prompt"])
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
