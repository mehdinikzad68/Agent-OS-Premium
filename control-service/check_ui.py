"""Structural validation of the single-file UI (no browser available here).

A single-pass scanner tokenizes the inline script the way a JS lexer would
(template literals incl. ${} nesting, strings, comments) and verifies that
(), [] and {} are balanced. Then it checks that every UI element/identifier
the dashboard depends on is present.

Exit 0 = structurally sound.
"""

from __future__ import annotations

import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
PAIRS = {"{": "}", "(": ")", "[": "]"}


def _skip_string(js: str, i: int) -> int:
    """i points at a quote; return index just past the closing quote."""
    quote = js[i]
    i += 1
    n = len(js)
    while i < n:
        if js[i] == "\\":
            i += 2
            continue
        if js[i] == quote:
            return i + 1
        i += 1
    return n


def scan_balanced(js: str) -> str | None:
    """Return an error string, or None when delimiters are balanced."""
    stack: list[str] = []
    i, n = 0, len(js)
    while i < n:
        ch = js[i]
        if ch == "`":  # template literal, with ${ } nesting
            i += 1
            while i < n:
                if js[i] == "\\":
                    i += 2
                    continue
                if js[i] == "`":
                    i += 1
                    break
                if js[i] == "$" and i + 1 < n and js[i + 1] == "{":
                    depth = 1
                    i += 2
                    while i < n and depth > 0:
                        c = js[i]
                        if c == "\\":
                            i += 2
                            continue
                        if c in "\"'`":
                            i = _skip_string(js, i)
                            continue
                        if c == "{":
                            depth += 1
                        elif c == "}":
                            depth -= 1
                        i += 1
                    continue
                i += 1
            continue
        if ch in "\"'":
            i = _skip_string(js, i)
            continue
        if ch == "/" and i + 1 < n and js[i + 1] == "/":
            while i < n and js[i] not in "\r\n":
                i += 1
            continue
        if ch == "/" and i + 1 < n and js[i + 1] == "*":
            end = js.find("*/", i + 2)
            i = n if end < 0 else end + 2
            continue
        if ch in PAIRS:
            stack.append(ch)
        elif ch in PAIRS.values():
            if not stack or PAIRS[stack.pop()] != ch:
                snippet = js[max(0, i - 60): i + 60].replace("\n", " ")
                return f"unbalanced {ch!r} near: …{snippet}…"
        i += 1
    if stack:
        return f"unclosed delimiters remain: {stack}"
    return None


def main() -> int:
    html = (HERE / "agent_os" / "web" / "index.html").read_text(encoding="utf-8")
    m = re.search(r"<script>(.*?)</script>", html, re.S)
    if not m:
        print("FAIL: no inline <script> found")
        return 1
    js = m.group(1)

    err = scan_balanced(js)
    if err:
        print(f"FAIL: {err}")
        return 1

    # Every handler referenced from inline onclick= must exist and be exposed
    # on window (inline handlers resolve against the global scope).
    inline_handlers = set(re.findall(r'onclick="(\w+)\(', js))
    exposed = set(re.findall(r"window\.(\w+)\s*=", js))
    undeclared = {h for h in inline_handlers if h not in exposed}
    if undeclared:
        print(f"FAIL: inline handlers not exposed on window: {sorted(undeclared)}")
        return 1

    required = [
        "job-card", "renderJobDetail", "requestApproval", "escapeHtml",
        "/api/jobs/", "/evidence", "dispatchJob", "reconcileJob", "decide",
        "Authorization", "localStorage",
    ]
    missing = [r for r in required if r not in html]
    if missing:
        print(f"FAIL: UI missing expected identifiers: {missing}")
        return 1

    print(
        f"UI structurally OK ({len(html)} bytes html, {len(js)} bytes script, "
        f"inline handlers: {sorted(inline_handlers) or 'none'})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())