"""Shared evidence helpers (B2, review 2026-10-05).

M4: `detect_test_report` used to be copy-pasted verbatim into both
executors, so a fix to one silently missed the other. Detection order:
framework-specific summary lines first (a casual `echo "1 passed"` does
not look like them), then the original generic markers, so every existing
caller keeps its behaviour.

Honest limit, restated from READINESS.md: this stays a heuristic - a
command that prints a passing-looking line can still produce a report, so
verified state means "claimed and plausible", not proof. Real adapters
must eventually supply structured reports.
"""
from __future__ import annotations

import re

#: Tried before the generic markers: summaries only real runners print.
_FRAMEWORK_PATTERNS = (
    # pytest fences its summary: "== 3 passed in 0.10s ==" /
    # "== 1 failed, 2 passed in 0.05s =="
    re.compile(r"(?m)^=+[^=\n]*\b\d+ (?:passed|failed|skipped|error)\b[^=\n]*=+$"),
    # unittest ends with "OK" (possibly "OK (skipped=2)"). FAILED lines only
    # occur with a non-zero exit code, which the exit check filters anyway.
    re.compile(r"(?m)^OK(?: \(.*\))?$"),
)

#: The original markers, unchanged, as the compatibility fallback.
_GENERIC_MARKERS = (" passed", " ok", "tests passed", "PASSED", "succeeded")


def _snippet(lines, i: int) -> str:
    return "\n".join(lines[max(0, i - 2): i + 3])


def detect_test_report(stdout: str, stderr: str, exit_code: int) -> str:
    """A human-reviewable report, or "" when nothing credible was seen.

    Only exit code 0 can ever yield a report. Framework summaries win over
    generic markers; otherwise the first generic marker found yields a
    snippet around its line - the exact shape callers have always parsed.
    """
    combined = f"{stdout}\n{stderr}"
    if exit_code != 0:
        return ""
    lines = combined.splitlines()
    for pattern in _FRAMEWORK_PATTERNS:
        m = pattern.search(combined)
        if m:
            idx = combined.count("\n", 0, m.start())
            return f"detected framework summary (exit 0)\n{_snippet(lines, idx)}"
    for marker in _GENERIC_MARKERS:
        if marker in combined:
            hits = [i for i, ln in enumerate(lines) if marker in ln]
            if hits:
                return (
                    f"detected test signal '{marker}' (exit 0)\n"
                    f"{_snippet(lines, hits[0])}"
                )
    return ""
