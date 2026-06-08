"""PROMPTLINT - Lint, version, and test prompts as code with a CI gate.

prompt-as-code, in the spirit of promptfoo. Standard library only, zero install.
"""
from .core import (
    Rule,
    LintIssue,
    AssertResult,
    PromptDoc,
    parse_prompt,
    lint_prompt,
    version_prompt,
    run_tests,
    SEVERITY_ERROR,
    SEVERITY_WARNING,
)

TOOL_NAME = "promptlint"
TOOL_VERSION = "1.0.0"

__all__ = [
    "Rule",
    "LintIssue",
    "AssertResult",
    "PromptDoc",
    "parse_prompt",
    "lint_prompt",
    "version_prompt",
    "run_tests",
    "SEVERITY_ERROR",
    "SEVERITY_WARNING",
    "TOOL_NAME",
    "TOOL_VERSION",
]
