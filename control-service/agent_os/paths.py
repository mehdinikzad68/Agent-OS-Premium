# Agent OS — Human-Supervised Agent Operating System
# Copyright (c) 2026 Mehdi Nikzad Semeskandi
# SPDX-License-Identifier: Apache-2.0
# Author: Mehdi Nikzad Semeskandi

"""Pure path logic for project registration.

Contains no filesystem access on purpose: existence, symlink and permission
checks belong to the caller in the HTTP layer, so this module stays fully
unit-testable and its behaviour is auditable by reading it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

REASON_OK = "ok"
REASON_NOT_ABSOLUTE = "not_absolute"
REASON_TRAVERSAL = "traversal"
REASON_OUTSIDE_SCOPE = "outside_scope"
REASON_WINDOWS_UNSUPPORTED = "windows_unsupported"


def canonicalize(path: str) -> str:
    """Normalise a POSIX path lexically.

    Collapses repeated slashes, resolves "." and "..", strips a trailing
    slash. Never touches the filesystem and never follows a symlink, so the
    result is a string claim, not an observation.

    Raises ValueError when the path is not absolute.
    """
    p = PurePosixPath(path)
    if not p.is_absolute():
        raise ValueError(f"path is not absolute: {path!r}")
    parts: list[str] = []
    for part in p.parts:
        # POSIX leaves a leading "//" implementation-defined, and pathlib keeps
        # it as a single ("//",) part, so it must be treated as the root too -
        # otherwise canonicalize("//") returns "///".
        if part.strip("/") == "" or part == ".":
            continue
        if part == "..":
            if parts:
                parts.pop()
            continue
        parts.append(part)
    return "/" + "/".join(parts)


def is_within(scope: str, candidate: str) -> bool:
    """True when candidate is scope itself or lies below it.

    Must not be fooled by a sibling that merely shares a prefix:
    scope "/a/b" does not contain "/a/bc".
    """
    scope_parts = PurePosixPath(canonicalize(scope)).parts
    candidate_parts = PurePosixPath(canonicalize(candidate)).parts
    return candidate_parts[: len(scope_parts)] == scope_parts


@dataclass(frozen=True)
class Check:
    ok: bool
    reason: str
    canonical: str


def _has_raw_traversal(raw: str) -> bool:
    return any(segment == ".." for segment in raw.split("/"))


def check_project_root(raw: str, scope: str, environment: str) -> Check:
    """Decide whether a user-typed path may be registered.

    Only the "wsl" environment is supported in this step; the field exists so
    a later step can add another without a schema change.

    Order of checks: environment, absoluteness, traversal, scope. Existence
    cannot be checked here - that is the caller's job - so REASON_OK means
    "well-formed and in scope", not "this directory exists".
    """
    if environment != "wsl":
        return Check(ok=False, reason=REASON_WINDOWS_UNSUPPORTED, canonical="")
    if not PurePosixPath(raw).is_absolute():
        return Check(ok=False, reason=REASON_NOT_ABSOLUTE, canonical="")
    if _has_raw_traversal(raw):
        return Check(ok=False, reason=REASON_TRAVERSAL, canonical="")
    canonical = canonicalize(raw)
    if not is_within(scope, canonical):
        return Check(ok=False, reason=REASON_OUTSIDE_SCOPE, canonical=canonical)
    return Check(ok=True, reason=REASON_OK, canonical=canonical)
