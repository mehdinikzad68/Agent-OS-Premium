"""Read-only tool discovery for one environment.

Design constraints, all of them measured rather than assumed (2026-09-28):

* A probe runs with the SERVER's privileges. A binary that writes a file when
  asked for its version will do so; nothing in discovery can prevent that by
  inspection. The only control available is an allowlist, so the allowlist IS
  the boundary and it is written out explicitly in ALLOWED_PROBES.

* Exec-ability must not be decided from the path. `dsh` resolves on this
  machine to /mnt/c/Users/Mehdi/AppData/Local/hermes/node/dsh - a Windows
  install reached through WSL interop - and it runs fine. A rule that refused
  every /mnt/<drive>/ path would have discarded a working tool. What is
  refused is what demonstrably cannot run.

* The same name can resolve to two different installs in two environments, and
  a version string without provenance is a half-truth. So provenance is
  reported next to the version, never inferred away.

A discovered tool is NOT thereby permitted to run. This module only reports
what is present; registration is a separate, owner-approved step, and
registration alone grants no execution rights.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence

# ---------------------------------------------------------------------------
# The allowlist. This is the whole safety boundary for probing: a name not
# listed here is never executed, whatever else it looks like.
#
# Each entry gives the argv prefix and how to read a version out of the reply.
# `flags` are tried in order; the first that yields a version wins.
# ---------------------------------------------------------------------------
PROBE_TIMEOUT_SECONDS = 8.0
MAX_OUTPUT_BYTES = 8192


# The version token itself. Deliberately strict: a dotted numeric release with
# an optional pre-release suffix, which is what real tools print.
_VERSION_TOKEN = r"v?[0-9]+(?:\.[0-9]+)*(?:[-+][0-9A-Za-z.]+)?"


@dataclass(frozen=True)
class ProbeSpec:
    """How to ask one allowlisted tool for its version.

    `version_pattern` is a regex matched against the START of the tool's first
    output line, with group 1 being the version. A custom pattern is only needed
    for the handful of tools whose banner word differs from their name
    ("git version 2.53.0", "Python 3.14.4"). Everything else is served by the
    default, which accepts the two shapes real tools use:

        "node --version"      ->  v22.23.2
        "writertool 1.0"      ->  writertool 1.0

    What the default must never accept is a version buried in prose - "loaded 3
    plugins" is not version 3. Hence match-from-the-start, in _read_version.
    """

    name: str
    flags: Sequence[str] = ("--version",)
    version_pattern: str = ""
    # Some tools need a subcommand instead of a bare flag.
    argv_prefix: Sequence[str] = ()

    def pattern(self) -> str:
        """The regex actually used. Defaults to this tool's own name."""
        if self.version_pattern:
            return self.version_pattern
        return rf"{re.escape(self.name)}\s+({_VERSION_TOKEN})\s*$|^({_VERSION_TOKEN})\s*$"


ALLOWED_PROBES: Dict[str, ProbeSpec] = {
    spec.name: spec
    for spec in (
        ProbeSpec("python3", version_pattern=r"^Python\s+([0-9][0-9.]*)"),
        ProbeSpec("git", version_pattern=r"^git version\s+([0-9][0-9.]*)"),
        # A bare leading number IS the answer for these three, but only when
        # the line STARTS with it - anchored so trailing prose cannot match.
        ProbeSpec("node", version_pattern=r"^v?([0-9][0-9.]*)\s*$"),
        ProbeSpec("npm", version_pattern=r"^v?([0-9][0-9.]*)\s*$"),
        ProbeSpec("docker", version_pattern=r"^Docker version\s+([0-9][0-9.]*)"),
        ProbeSpec("dsh", version_pattern=r"^v?([0-9][0-9A-Za-z.+-]*)\s*$"),
        ProbeSpec("agy", version_pattern=r"^v?([0-9][0-9A-Za-z.+-]*)\s*$"),
    )
}

# Environments this service has been verified on. Discovery refuses to claim
# knowledge about a platform it has no test evidence for.
SUPPORTED_ENVIRONMENTS = ("wsl",)

# Confidence levels, deliberately coarse. "unknown" is a real, expected result
# and never means "probably fine" - a wrong version looks like knowledge.
CONFIDENCE_EXACT = "exact"        # parsed from the tool's own answer
CONFIDENCE_UNKNOWN = "unknown"    # found, but the version could not be read
CONFIDENCE_NOT_PROBED = "not_probed"  # not on the allowlist; not executed


@dataclass
class DiscoveredTool:
    """One candidate. `version` is Optional on purpose."""

    name: str
    environment: str
    path: Optional[str]
    version: Optional[str] = None
    confidence: str = CONFIDENCE_NOT_PROBED
    # Why a candidate was skipped, or why its version is unknown. Always set
    # when something went wrong, so a caller never has to guess.
    note: str = ""
    # "posix" | "windows_mount" - which filesystem the binary actually lives on.
    provenance: str = "posix"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "environment": self.environment,
            "path": self.path,
            "version": self.version,
            "confidence": self.confidence,
            "note": self.note,
            "provenance": self.provenance,
        }


@dataclass
class DiscoveryResult:
    environment: str
    tools: List[DiscoveredTool] = field(default_factory=list)
    # Candidates that were considered and refused, with the reason. Nothing is
    # dropped silently: a candidate the owner cannot see is indistinguishable
    # from one that does not exist.
    skipped: List[DiscoveredTool] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "environment": self.environment,
            "tools": [t.to_dict() for t in self.tools],
            "skipped": [t.to_dict() for t in self.skipped],
        }


class EnvironmentUnsupported(Exception):
    """Discovery was asked about a platform with no test evidence here.

    Distinct from a bad request so the HTTP layer can refuse with a reason
    rather than returning an empty list that reads like "nothing installed".
    """


def _provenance(path: str) -> str:
    """Which filesystem the binary lives on.

    Reported, never used to refuse: a Windows install reached through WSL
    interop genuinely runs, so a path-based refusal would be wrong.
    """
    m = re.match(r"^/mnt/([a-zA-Z])(/|$)", path)
    return "windows_mount" if m else "posix"


def _read_version(text: str, spec: "ProbeSpec") -> Optional[str]:
    """Pull a version out of the first line, or return None.

    Deliberately conservative in two ways, both enforced here rather than
    left to the caller's pattern: only the first non-empty line is considered,
    and the pattern must match from the start of it. A failure yields None
    rather than a guess.
    """
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # match, not search: a version belongs at the START of the line the
        # tool printed. Without this, a pattern like ([0-9][0-9.]*) would read
        # "loaded 3 plugins" as version 3 - and the caller cannot be trusted to
        # supply an anchored pattern, because the next one added might not be.
        m = re.match(spec.pattern(), line)
        if m:
            found = next((g for g in m.groups() if g), None) if m.groups() else m.group(0)
            if found:
                # "v22.23.2" is how node prints it; "22.23.2" is what a version
                # field should hold, so the decorative prefix is dropped here
                # rather than left for every consumer to strip.
                return found[1:] if found[:1] in ("v", "V") else found
        # A non-empty first line that does not match is a real answer we could
        # not read. Stop rather than scanning further for a convenient number.
        return None
    return None


def _run(argv: Sequence[str], cwd: Optional[str] = None) -> tuple:
    """Run a probe with a hard timeout and a bounded capture.

    Returns (rc, stdout_text, note). Never raises: a failing probe is a result,
    not an error, and discovery must survive any single bad candidate.
    """
    try:
        r = subprocess.run(
            list(argv),
            capture_output=True,
            timeout=PROBE_TIMEOUT_SECONDS,
            cwd=cwd,
            text=True,
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        return None, "", f"probe timed out after {PROBE_TIMEOUT_SECONDS:g}s"
    except (OSError, ValueError) as e:
        return None, "", f"probe could not run: {type(e).__name__}"

    out = (r.stdout or "")[:MAX_OUTPUT_BYTES]
    if not out.strip():
        out = (r.stderr or "")[:MAX_OUTPUT_BYTES]
    return r.returncode, out, ""


def probe_tool(name: str, environment: str) -> DiscoveredTool:
    """Probe one named tool. Never raises, never guesses a version."""
    spec = ALLOWED_PROBES.get(name)
    path = shutil.which(name)

    if spec is None:
        # Not allowlisted. `which` is a filesystem lookup, not an execution, so
        # this is safe to report - but the binary is NOT run.
        return DiscoveredTool(
            name=name, environment=environment, path=path,
            confidence=CONFIDENCE_NOT_PROBED,
            note="not on the probe allowlist; not executed",
            provenance=_provenance(path) if path else "posix",
        )

    if path is None:
        return DiscoveredTool(
            name=name, environment=environment, path=None,
            confidence=CONFIDENCE_NOT_PROBED, note="not found on PATH",
        )

    provenance = _provenance(path)
    last_note = ""
    for flag in spec.flags:
        argv = list(spec.argv_prefix) + [path, flag]
        rc, out, note = _run(argv)
        if note:
            last_note = note
            continue
        if rc not in (0, None):
            last_note = f"exited {rc} for '{flag}'"
            continue
        version = _read_version(out, spec)
        if version:
            return DiscoveredTool(
                name=name, environment=environment, path=path,
                version=version, confidence=CONFIDENCE_EXACT,
                provenance=provenance,
                note=("version read from a Windows install reached through WSL"
                      if provenance == "windows_mount" else ""),
            )
        last_note = f"could not read a version from '{flag}' output"

    # Found and executed, but the version is not knowable. This is the honest
    # outcome and it stays a first-class result.
    return DiscoveredTool(
        name=name, environment=environment, path=path, version=None,
        confidence=CONFIDENCE_UNKNOWN, note=last_note or "no version available",
        provenance=provenance,
    )


def discover(names: Sequence[str], environment: str) -> DiscoveryResult:
    """Probe a set of candidate names in one environment.

    Read-only by construction: the only side effect is executing allowlisted
    binaries with a version flag. Nothing is installed, written, or registered.
    """
    if environment not in SUPPORTED_ENVIRONMENTS:
        raise EnvironmentUnsupported(
            f"environment {environment!r} has no test evidence in this service; "
            f"supported: {', '.join(SUPPORTED_ENVIRONMENTS)}"
        )

    result = DiscoveryResult(environment=environment)
    seen = set()
    for raw in names:
        name = (raw or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        tool = probe_tool(name, environment)
        if tool.confidence == CONFIDENCE_NOT_PROBED and tool.path is None:
            # Never even present: not worth listing as a refusal.
            continue
        if tool.confidence == CONFIDENCE_NOT_PROBED:
            result.skipped.append(tool)
        else:
            result.tools.append(tool)
    return result


def search_path(environment: str) -> List[str]:
    """Names on PATH that look like agent tooling, for a UI-driven search.

    A directory listing, not an execution, so nothing here runs anything. The
    allowlist filter is applied by the caller via probe_tool.
    """
    if environment not in SUPPORTED_ENVIRONMENTS:
        raise EnvironmentUnsupported(
            f"environment {environment!r} has no test evidence in this service")
    names = set()
    for d in os.environ.get("PATH", "").split(os.pathsep):
        if not d:
            continue
        try:
            entries = os.listdir(d)
        except OSError:
            # An unreadable or stale PATH entry is normal, not an error.
            continue
        for e in entries:
            if e in ALLOWED_PROBES:
                names.add(e)
    return sorted(names)
