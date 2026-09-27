"""Structured logging for the Agent OS control service.

Standard library only (logging, json, re, pathlib, datetime). The control
plane keeps its zero-install property: adding observability must never add a
runtime dependency.

Output is JSON Lines: one self-describing JSON object per line, so a failure
can be grepped, filtered by level, and read by ``logview.py`` without any
parsing guesswork.

Redaction is a STAGE, not a filter. It runs inside the logging pipeline before
any handler formats or writes the record, and it also rewrites the formatted
traceback. Nothing unredacted reaches a file, the console, or an exception
traceback. This mirrors the rule in docs/hermes-integration-layer.md 2.3.

Logging must never be the reason the service fails: every failure inside
``configure`` degrades to a no-op handler instead of raising.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

__all__ = [
    "configure",
    "get_logger",
    "log_event",
    "redact",
    "register_secret",
    "default_log_dir",
    "is_debug",
    "active_log_file",
]

PACKAGE_LOGGER = "agent_os"
DEFAULT_MAX_BYTES = 10 * 1024 * 1024
DEFAULT_BACKUPS = 5

# Attribute names LogRecord itself owns. Anything else passed through
# ``extra`` is treated as structured field data and emitted as a top-level key.
_STANDARD_ATTRS = frozenset(
    vars(logging.LogRecord("", 0, "", 0, "", None, None)).keys()
) | {"message", "asctime", "taskName"}

# Secrets registered at runtime (the live bearer token, for example).
_LIVE_SECRETS: set[str] = set()
_SECRETS_LOCK = threading.Lock()

# Each entry is (pattern, index_of_the_group_holding_the_secret).
# Index 0 means "the whole match is the secret". The index is explicit because
# the patterns have different group counts; inferring it from the count is how
# the first version of this function crashed on a 3-group pattern.
_REDACTIONS: tuple[tuple["re.Pattern[str]", int], ...] = (
    # GitHub personal access / OAuth / app / refresh / user tokens.
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{16,255}"), 0),
    (re.compile(r"github_pat_[A-Za-z0-9_]{20,255}"), 0),
    # Provider-style secret keys.
    (re.compile(r"sk-[A-Za-z0-9_-]{20,}"), 0),
    # AWS access key id.
    (re.compile(r"AKIA[0-9A-Z]{16}"), 0),
    # Whole PEM private key blocks.
    (
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"
        ),
        0,
    ),
    # Authorization: <value>. Runs BEFORE the bearer rule and swallows the
    # optional auth scheme, so the scheme word ("Bearer") is not itself
    # replaced by the placeholder and the output stays readable.
    (
        re.compile(
            r"""(?i)\b(authorization\s*[:=]\s*)(["']?)([^\s,;"']+(?:\s+[^\s,;"']+)?)(["']?)"""
        ),
        3,
    ),
    # "Bearer <token>" on its own, outside an Authorization header.
    (re.compile(r"(?i)\b(bearer\s+)([A-Za-z0-9._~+/=-]{8,})"), 2),
    # key = value / "key": "value" for credential-shaped key names.
    (
        re.compile(
            r"""(?i)(["']?(?:api[_-]?key|access[_-]?key|secret[_-]?key|client[_-]?secret"""
            r"""|token|password|passwd|credential|private[_-]?key)["']?\s*[:=]\s*)"""
            r"""(["']?)([^\s,;"'}\]]{6,})(["']?)"""
        ),
        3,
    ),
)

_PLACEHOLDER = "[REDACTED]"


def _mask_match(match: "re.Match[str]", secret_group: int) -> str:
    """Rebuild the MATCHED SPAN with ``secret_group`` replaced by the placeholder.

    The return value must cover exactly ``match.span(0)`` and nothing more:
    ``re.sub`` already keeps the text before and after the match, so
    including the leading segment here would duplicate it. That bug produced
    "sent sent bearer [REDACTED] upstream" from "sent bearer <token> upstream".
    """
    if secret_group == 0:
        return _PLACEHOLDER
    pieces: list[str] = []
    cursor = match.start(0)
    for index in range(1, match.re.groups + 1):
        start, end = match.span(index)
        if start < 0:  # optional group did not participate
            continue
        pieces.append(match.string[cursor:start])
        pieces.append(_PLACEHOLDER if index == secret_group else match.group(index))
        cursor = end
    pieces.append(match.string[cursor:match.end(0)])
    return "".join(pieces)


def register_secret(value: Optional[str]) -> None:
    """Register a live secret value so it is masked wherever it appears.

    Used for the bearer token the service is actually running with: the token
    is not a static string in the source, so pattern matching alone cannot
    catch it.
    """
    if not value or not isinstance(value, str):
        return
    if len(value) < 8:  # too short to mask safely without mangling normal text
        return
    with _SECRETS_LOCK:
        _LIVE_SECRETS.add(value)


def redact(text: Any) -> Any:
    """Return ``text`` with every known secret shape masked."""
    if not isinstance(text, str) or not text:
        return text
    out = text
    with _SECRETS_LOCK:
        live = tuple(_LIVE_SECRETS)
    for secret in live:
        if secret in out:
            out = out.replace(secret, _PLACEHOLDER)
    for pattern, secret_group in _REDACTIONS:
        out = pattern.sub(lambda m, _g=secret_group: _mask_match(m, _g), out)
    return out


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: _redact_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact_value(v) for v in value]
    return value


class RedactingFilter(logging.Filter):
    """Mask secrets on the record BEFORE any handler sees it.

    The traceback is formatted here and stored back as already-redacted text,
    so an exception message containing a token cannot leak through the
    standard ``exc_text`` path either.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = redact(record.msg)
            if record.args:
                if isinstance(record.args, dict):
                    record.args = {k: _redact_value(v) for k, v in record.args.items()}
                else:
                    record.args = tuple(_redact_value(a) for a in record.args)
            for key, value in list(vars(record).items()):
                if key not in _STANDARD_ATTRS:
                    record.__dict__[key] = _redact_value(value)
            if record.exc_info:
                record.exc_text = redact(
                    logging.Formatter().formatException(record.exc_info)
                )
                record.exc_info = None
        except Exception:  # noqa: BLE001 - a logger must never break the caller
            record.msg = "[REDACTION FAILED - message withheld]"
            record.args = None
        return True


class JsonLineFormatter(logging.Formatter):
    """One JSON object per line, with a fixed set of mandatory keys."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "pid": record.process,
            "event": getattr(record, "event", None) or str(record.msg),
            "message": record.getMessage(),
        }
        for key, value in vars(record).items():
            if key not in _STANDARD_ATTRS and key not in payload:
                payload[key] = value
        text = record.exc_text or ""
        if text:
            payload["exc"] = text
        return json.dumps(payload, ensure_ascii=False, default=str)


class HumanFormatter(logging.Formatter):
    """Compact one-line console output; the traceback follows on its own lines."""

    def format(self, record: logging.LogRecord) -> str:
        stamp = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
        base = f"{stamp} {record.levelname:<7} {record.name:<18} {record.getMessage()}"
        extras = {
            k: v
            for k, v in vars(record).items()
            if k not in _STANDARD_ATTRS and k != "event" and v is not None
        }
        if extras:
            base += "  " + " ".join(f"{k}={v}" for k, v in extras.items())
        if record.exc_text:
            base += "\n" + record.exc_text
        return base


def is_debug() -> bool:
    return os.environ.get("AGENT_OS_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}


def default_log_dir() -> Path:
    """`<repo>/.logs`, overridable with AGENT_OS_LOG_DIR."""
    override = os.environ.get("AGENT_OS_LOG_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    # .../Agent-OS/control-service/agent_os/logging_setup.py -> .../Agent-OS/.logs
    return Path(__file__).resolve().parents[2] / ".logs"


_ACTIVE_FILE: Optional[Path] = None
_CONFIGURED = False


def active_log_file() -> Optional[Path]:
    """Path of the JSON-lines file currently being written, if any."""
    return _ACTIVE_FILE


def configure(
    level: Optional[int] = None,
    log_dir: Optional[Path] = None,
    console: Optional[bool] = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
    backups: int = DEFAULT_BACKUPS,
    enabled: bool = True,
) -> Optional[Path]:
    """Install the package logger's handlers. Idempotent.

    Returns the active log file path, or ``None`` when logging is disabled or
    the file handler could not be created. Never raises.
    """
    global _ACTIVE_FILE, _CONFIGURED

    logger = logging.getLogger(PACKAGE_LOGGER)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:  # noqa: BLE001
            pass
    logger.propagate = False
    _ACTIVE_FILE = None
    _CONFIGURED = True

    if not enabled:
        logger.addHandler(logging.NullHandler())
        logger.setLevel(logging.CRITICAL + 1)
        return None

    debug = is_debug()
    if level is None:
        level = logging.DEBUG if debug else logging.INFO
    logger.setLevel(level)
    logger.addFilter(RedactingFilter())

    target_dir = Path(log_dir) if log_dir is not None else default_log_dir()
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / f"agent-os-{datetime.now().strftime('%Y%m%d')}.jsonl"
        file_handler = logging.handlers.RotatingFileHandler(
            path, maxBytes=max_bytes, backupCount=backups, encoding="utf-8"
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(JsonLineFormatter())
        file_handler.addFilter(RedactingFilter())
        logger.addHandler(file_handler)
        _ACTIVE_FILE = path
    except Exception:  # noqa: BLE001 - a broken log path must not stop the service
        logger.addHandler(logging.NullHandler())

    if console is True or (console is None and debug):
        stream = logging.StreamHandler()
        stream.setLevel(level)
        stream.setFormatter(HumanFormatter())
        stream.addFilter(RedactingFilter())
        logger.addHandler(stream)

    return _ACTIVE_FILE


def get_logger(name: str) -> logging.Logger:
    """Return a child of the package logger, e.g. ``get_logger("api")``."""
    if name.startswith(PACKAGE_LOGGER):
        return logging.getLogger(name)
    return logging.getLogger(f"{PACKAGE_LOGGER}.{name}")


def log_event(
    logger: logging.Logger,
    level: int,
    name: str,
    *,
    exc_info: bool = False,
    **fields: Any,
) -> None:
    """Emit one structured record.

    ``name`` is the searchable event name (``mission.created``); keyword
    arguments become top-level JSON fields. Names colliding with LogRecord
    attributes are dropped rather than raising.
    """
    extra = {k: v for k, v in fields.items() if k not in _STANDARD_ATTRS}
    extra["event"] = name
    logger.log(level, name, exc_info=exc_info, extra=extra)
