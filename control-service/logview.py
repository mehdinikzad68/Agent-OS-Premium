"""Read and filter the Agent OS JSON-lines log.

Standard library only. Reads the newest file in the log directory by default.

Examples:
    python3 logview.py --tail 40
    python3 logview.py --level warning
    python3 logview.py --since 15m --grep dispatch
    python3 logview.py --event job.completed_unverified --full
    python3 logview.py --follow
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Iterator, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent_os.logging_setup import default_log_dir  # noqa: E402

LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
_COLORS = {
    "DEBUG": "\033[36m",
    "INFO": "\033[32m",
    "WARNING": "\033[33m",
    "ERROR": "\033[31m",
    "CRITICAL": "\033[1;31m",
}
_RESET = "\033[0m"
_DUR = re.compile(r"^(\d+)([smhd])$")


def _duration_to_seconds(text: str) -> Optional[float]:
    m = _DUR.match(text.strip())
    if not m:
        return None
    n = int(m.group(1))
    return n * {"s": 1, "m": 60, "h": 3600, "d": 86400}[m.group(2)]


def _iso_to_epoch(ts: str) -> Optional[float]:
    from datetime import datetime

    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except Exception:  # noqa: BLE001
        return None


def latest_file(log_dir: Path) -> Optional[Path]:
    if not log_dir.is_dir():
        return None
    files = sorted(log_dir.glob("agent-os-*.jsonl"), key=lambda p: p.stat().st_mtime)
    if not files:
        return None
    # Rotated files are agent-os-YYYYMMDD.jsonl.N - include the newest of those
    rotated = sorted(log_dir.glob("agent-os-*.jsonl.*"), key=lambda p: p.stat().st_mtime)
    if rotated and rotated[-1].stat().st_mtime > files[-1].stat().st_mtime:
        return rotated[-1]
    return files[-1]


def read_records(path: Path) -> Iterator[dict]:
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                yield {"level": "UNPARSED", "message": line, "event": "?"}
                continue
            if isinstance(record, dict):
                yield record


def _matches(rec: dict, args) -> bool:
    level = (rec.get("level") or "").upper()
    if args.level and level != args.level.upper():
        return False
    if args.min_level and LEVELS.index(level) < LEVELS.index(args.min_level.upper()):
        return False
    if args.event and args.event not in (rec.get("event") or ""):
        return False
    if args.grep and args.grep.lower() not in json.dumps(rec, ensure_ascii=False).lower():
        return False
    if args.since:
        seconds = _duration_to_seconds(args.since)
        ts = _iso_to_epoch(rec.get("ts") or "")
        if seconds is not None and ts is not None and ts < time.time() - seconds:
            return False
    return True


def render(rec: dict, color: bool, full: bool) -> str:
    level = (rec.get("level") or "?").upper()
    stamp = (rec.get("ts") or "")[:23]
    event = rec.get("event") or "?"
    fields = {
        k: v
        for k, v in rec.items()
        if k
        not in {"ts", "level", "logger", "pid", "event", "message", "exc"}
    }
    def fmt(value: Any) -> str:
        text = str(value)
        return f'"{text}"' if (" " in text or not text) else text

    parts = " ".join(f"{k}={fmt(v)}" for k, v in fields.items())
    # log_event() uses the event name as the message too, so printing both
    # columns would show it twice on every line.
    message = rec.get("message", "")
    tail = "" if message == event else f"  {message}"
    line = f"{stamp} {level:<8} {event:<28}{tail}"
    if parts:
        line += "  | " + parts
    if color and level in _COLORS:
        line = f"{_COLORS[level]}{line}{_RESET}"
    if full and rec.get("exc"):
        line += "\n" + rec["exc"]
    return line


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="View the Agent OS structured log.")
    parser.add_argument("--file", help="log file to read (default: newest in the log dir)")
    parser.add_argument("--dir", help="log directory (default: AGENT_OS_LOG_DIR or <repo>/.logs)")
    parser.add_argument("--level", choices=LEVELS, help="exact level match")
    parser.add_argument("--min-level", choices=LEVELS, help="this level and above")
    parser.add_argument("--event", help="substring match on the event name")
    parser.add_argument("--grep", help="substring match anywhere in the record")
    parser.add_argument("--since", help="only records newer than e.g. 15m, 2h, 1d")
    parser.add_argument("--tail", type=int, default=0, help="show only the last N matches")
    parser.add_argument("--follow", action="store_true", help="stream new lines (Ctrl-C to stop)")
    parser.add_argument("--full", action="store_true", help="include full tracebacks")
    parser.add_argument("--no-color", action="store_true")
    args = parser.parse_args(argv)

    log_dir = Path(args.dir) if args.dir else default_log_dir()
    path = Path(args.file) if args.file else latest_file(log_dir)
    if path is None or not path.exists():
        print(f"no log file found in {log_dir}", file=sys.stderr)
        print("hint: start the service first, or pass --file <path>", file=sys.stderr)
        return 2

    color = sys.stdout.isatty() and not args.no_color and os.environ.get("NO_COLOR") is None

    def emit(records) -> None:
        matched = [r for r in records if _matches(r, args)]
        if args.tail > 0:
            matched = matched[-args.tail :]
        for rec in matched:
            print(render(rec, color, args.full))

    emit(read_records(path))
    if not args.follow:
        return 0

    print(f"-- following {path.name} (Ctrl-C to stop) --", file=sys.stderr)
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            fh.seek(0, os.SEEK_END)
            while True:
                line = fh.readline()
                if not line:
                    time.sleep(0.4)
                    continue
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(rec, dict) and _matches(rec, args):
                    print(render(rec, color, args.full))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
