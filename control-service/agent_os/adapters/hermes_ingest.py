# Agent OS — Human-Supervised Agent Operating System
# Copyright (c) 2026 Mehdi Nikzad Semeskandi
# SPDX-License-Identifier: Apache-2.0
# Author: Mehdi Nikzad Semeskandi

"""Event ingestion from a real Hermes profile. Observation only.

What this module is allowed to claim, and what it must never claim:

* It READS a Hermes state.db and reports tool calls that Hermes already
  recorded. It creates nothing, executes nothing and blocks nothing. Every
  event it emits describes something that already happened.
* Because the source records tool RESULTS, ingest can say what occurred. It
  can never say it prevented anything. Interception is Phase 5's job and this
  module must not be worded as if it did that work.

Every constraint below was measured against the real database on 2026-09-28,
not assumed from the schema:

* 3,479 tool rows across 22 distinct tool names, and TWO of them have
  tool_name IS NULL. They are ingested as name=unknown with a reason, not
  dropped - a missing field is a fact about the row, and dropping the row
  would hide real activity.
* 20 rows have a timestamp that moves BACKWARDS relative to id. Ordering by
  time would therefore produce a wrong timeline, so ordering is by id, which
  is the primary key and therefore monotonic. Nothing rewrites a timestamp.
* git_repo_root is NULL on some sessions. It is reported as unknown and is
  never inferred from cwd or from a path that resembles a repository.
* Message CONTENT is never selected. The redaction boundary is structural: the
  query does not name the column, so no future edit to the mapper can leak it.

The source is opened mode=ro. Hermes keeps writing while we read, and ingest
must degrade rather than block the thing it observes, so a lock or a vanished
file raises SourceUnavailable - which the caller must render as an explicit
disconnected state and never as an empty timeline.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

UNKNOWN = "unknown"

# The only columns an event is built from. `content` is deliberately absent.
_SELECT = (
    "SELECT m.id, m.session_id, m.tool_name, m.tool_call_id, m.timestamp, "
    "       s.source, s.model, s.git_repo_root "
    "FROM messages m JOIN sessions s ON s.id = m.session_id "
    "WHERE m.role = 'tool' AND m.id > ? ORDER BY m.id ASC"
)


class SourceUnavailable(Exception):
    """The source could not be read.

    Distinct from "the source is readable and has no new rows". A UI that
    conflates the two will show an empty timeline during a Hermes restart and
    call it a quiet period.
    """


@dataclass(frozen=True)
class IngestEvent:
    """One real tool call, reduced to what is safe to show and to correlate.

    Every field is either a value the row carried or UNKNOWN with a note. No
    field is derived from a sibling field, so an event can never report a repo
    it never saw or a tool it never heard named.
    """
    row_id: int
    session_id: str
    tool_name: str
    tool_call_id: str
    timestamp: float
    source: str
    model: str
    repo_root: str
    notes: tuple = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "row_id": self.row_id,
            "session_id": self.session_id,
            "tool_name": self.tool_name,
            "tool_call_id": self.tool_call_id,
            "timestamp": self.timestamp,
            "source": self.source,
            "model": self.model,
            "repo_root": self.repo_root,
            "notes": list(self.notes),
        }

    @property
    def attributable(self) -> bool:
        """Can this event be attributed to a named tool?"""
        return self.tool_name != UNKNOWN


def _text(value) -> tuple:
    """A text column becomes a value, or UNKNOWN plus the reason.

    A None is never carried forward as a string, and a placeholder is never
    substituted that could be mistaken for a measurement.
    """
    if value is None:
        return UNKNOWN, ("field is null",)
    text = str(value).strip()
    if not text:
        return UNKNOWN, ("field is empty",)
    return text, ()


def row_to_event(row) -> IngestEvent:
    """Map one database row to one event.

    A row with no tool name is still an event; the absence is recorded. A row
    is dropped only when it carries no id, because without an id it can be
    neither correlated nor deduplicated.
    """
    row_id, session_id, tool_name, tool_call_id, ts, source, model, repo = row
    if row_id is None:
        raise ValueError("row without an id cannot be correlated")

    notes = []
    name, n = _text(tool_name)
    notes += list(n)
    call, n = _text(tool_call_id)
    notes += list(n)
    sess, n = _text(session_id)
    notes += list(n)
    src, n = _text(source)
    notes += list(n)
    mdl, n = _text(model)
    notes += list(n)
    repo_s, n = _text(repo)
    notes += list(n)

    if isinstance(ts, (int, float)) and not isinstance(ts, bool) and ts > 0:
        stamp = float(ts)
    else:
        stamp = 0.0
        notes.append("timestamp is unusable, so this event cannot be placed")

    if name == UNKNOWN:
        notes.append("tool name unknown, so this event is not attributable")

    return IngestEvent(
        row_id=int(row_id),
        session_id=sess,
        tool_name=name,
        tool_call_id=call,
        timestamp=stamp,
        source=src,
        model=mdl,
        repo_root=repo_s,
        notes=tuple(notes),
    )


class StateReader:
    """Incremental reader over one Hermes state.db."""

    def __init__(self, path: str, busy_timeout_ms: int = 1500):
        self.path = path
        self.busy_timeout_ms = busy_timeout_ms

    def _connect(self) -> sqlite3.Connection:
        """Open the source read-only, on a filesystem that may not support locks.

        Measured 2026-09-28: this profile lives on a Windows drive reached
        from WSL at /mnt/c, and SQLite there raises `disk I/O error` on a plain
        read-only open - the locking SQLite attempts is not available on that
        mount. `immutable=1` tells SQLite the file cannot change under it, which
        is the honest description when the reader only ever looks, and it makes
        the read work.

        The trade-off is explicit rather than hidden: an immutable read can
        return a stale page if the writer commits while the read is in flight.
        That is acceptable here because a cursor on the primary key means a
        missed row is picked up on the next pass, and it is NOT acceptable for
        anything that must see the newest committed state - which is why this
        lives in the adapter and nowhere near the service's own store.
        """
        last_error = None
        for query in (f"file:{self.path}?mode=ro&immutable=1",
                      f"file:{self.path}?mode=ro"):
            try:
                con = sqlite3.connect(
                    query, uri=True, timeout=self.busy_timeout_ms / 1000.0)
                # touch it once, so a mount that cannot serve a read fails here
                # rather than mid-query
                con.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone()
                return con
            except sqlite3.Error as e:
                last_error = e
                try:
                    con.close()
                except (NameError, sqlite3.Error):
                    pass
        raise SourceUnavailable(f"cannot open the source: {last_error}")

    def probe(self) -> dict:
        """Readable right now, and how far does it reach?

        This is what separates "nothing happened" from "cannot see". A source
        that cannot be opened is a state the UI must be able to state.
        """
        con = self._connect()
        try:
            tables = {r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            missing = {"messages", "sessions"} - tables
            if missing:
                raise SourceUnavailable(
                    f"source is missing {sorted(missing)}; it is not a Hermes "
                    f"state database")
            max_id = con.execute(
                "SELECT MAX(id) FROM messages WHERE role='tool'").fetchone()[0]
            total = con.execute(
                "SELECT COUNT(*) FROM messages WHERE role='tool'").fetchone()[0]
            return {"readable": True, "max_row_id": int(max_id or 0),
                    "tool_rows": int(total)}
        except sqlite3.Error as e:
            raise SourceUnavailable(f"source is not usable: {e}") from e
        finally:
            con.close()

    def read_since(self, cursor: int = 0, limit: int = 500):
        """Return (events, new_cursor) for tool rows with id > cursor.

        The cursor advances only to the id of the last row actually converted,
        so a failure part way through leaves the unread rows to be picked up
        on the next pass instead of skipping them.
        """
        con = self._connect()
        try:
            try:
                rows = con.execute(_SELECT, (cursor,)).fetchmany(limit)
            except sqlite3.Error as e:
                raise SourceUnavailable(f"cannot read the source: {e}") from e
        finally:
            con.close()

        events = []
        new_cursor = cursor
        for row in rows:
            try:
                ev = row_to_event(row)
            except ValueError:
                continue
            events.append(ev)
            new_cursor = max(new_cursor, ev.row_id)
        return events, new_cursor


def default_profile_db(profile: str = "my-personal-assistant") -> str:
    """Where this runtime should look for a Hermes profile.

    A path is a default, not a claim: the caller must still probe it and handle
    SourceUnavailable. Two forms are needed because the host is Windows and the
    service runs in WSL:

      - inside WSL, the Windows drive is mounted at /mnt/<drive>, and the plain
        Windows form does not open there
      - on Windows, LOCALAPPDATA gives the real location

    Measured: with the Windows form from WSL, SQLite raised `disk I/O error`;
    with the /mnt/c form it read 3,544 tool rows.
    """
    import glob
    import os
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return os.path.join(local, "hermes", "profiles", profile, "state.db")
    # WSL: /mnt/c/... derived from the Windows profile path when available
    home = os.environ.get("USERPROFILE")
    if home and len(home) > 1 and home[1] == ":":
        drive = home[0].lower()
        rest = home[2:].replace("\\", "/")
        return f"/mnt/{drive}{rest}/AppData/Local/hermes/profiles/{profile}/state.db"
    # Measured 2026-09-28: inside WSL neither LOCALAPPDATA nor USERPROFILE is
    # exported, so a path built from them silently fell back to ~/.hermes and
    # pointed at nothing at all. Look for a mounted Windows profile instead,
    # and return it only if the file is really there - a default that names a
    # file which does not exist is worse than no default.
    pattern = f"/mnt/*/Users/*/AppData/Local/hermes/profiles/{profile}/state.db"
    for candidate in sorted(glob.glob(pattern)):
        if os.path.isfile(candidate):
            return candidate
    return os.path.join("~", ".hermes", "profiles", profile, "state.db")


# ---------------------------------------------------------------------------
# M1 (B2, review 2026-10-05): the ingest route accepted ANY local path, a
# token-gated arbitrary-read primitive. Sources must resolve under an allowed
# root: $AGENT_OS_INGEST_ROOTS (os.pathsep separated) plus the Hermes profile
# locations default_profile_db() could name. Deny by default; fail closed.
# ---------------------------------------------------------------------------

INGEST_ROOTS_ENV = "AGENT_OS_INGEST_ROOTS"


def allowed_source_roots() -> list:
    """Every directory an ingest source may resolve inside."""
    import glob as _glob
    import os as _os
    from pathlib import Path as _Path

    roots = []
    raw = _os.environ.get(INGEST_ROOTS_ENV, "")
    for part in raw.split(_os.pathsep):
        if part.strip():
            roots.append(_Path(part.strip()).expanduser())
    # The built-in defaults mirror default_profile_db(): every location that
    # function could ever have chosen, extended to the profiles ROOT so any
    # profile under it stays allowed.
    home = _Path(_os.path.expanduser("~"))
    roots.append(home / ".hermes" / "profiles")
    userprofile = _os.environ.get("USERPROFILE")
    if userprofile:
        roots.append(
            _Path(userprofile) / "AppData" / "Local" / "hermes" / "profiles"
        )
    for found in _glob.glob("/mnt/*/Users/*/AppData/Local/hermes/profiles"):
        roots.append(_Path(found))
    return roots


def assert_source_allowed(source: str):
    """Raise PermissionError when `source` resolves outside every allowed root.

    Resolution (not the literal string) decides, so `..` segments and a
    symlink planted inside an allowed root cannot widen it.
    """
    import os as _os
    from pathlib import Path as _Path

    p = _Path(source).expanduser()
    try:
        resolved = p.resolve()
    except OSError:
        resolved = p.absolute()
    for root in allowed_source_roots():
        try:
            rr = root.resolve()
        except OSError:
            rr = root.absolute()
        if resolved == rr or rr in resolved.parents:
            return p
    allowed = _os.pathsep.join(str(r) for r in allowed_source_roots())
    raise PermissionError(
        f"ingest source outside the allowed roots: {resolved} "
        f"(set {INGEST_ROOTS_ENV} to extend; allowed: {allowed})"
    )
