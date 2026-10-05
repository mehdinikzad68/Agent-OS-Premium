"""Run the enforcement suite and write results to a file.

Sandbox-friendly: results go to .test-results.txt written directly by
Python (stdout capture through pipes is unreliable in this environment).
"""

import io
import pathlib
import sys
import unittest


def main() -> int:
    here = pathlib.Path(__file__).resolve().parent
    results_path = here / ".test-results.txt"

    loader = unittest.TestLoader()
    suite = loader.discover(str(here / "tests"), top_level_dir=str(here))

    buf = io.StringIO()
    runner = unittest.TextTestRunner(stream=buf, verbosity=2)
    result = runner.run(suite)

    summary = (
        f"ran={result.testsRun} failures={len(result.failures)} "
        f"errors={len(result.errors)} skipped={len(result.skipped)} "
        f"ok={result.wasSuccessful()}"
    )
    if not sys.platform.startswith("linux"):
        # T2: POSIX/WSL-only modules were skipped at import (see tests/*).
        summary += f" [{sys.platform}: POSIX-only modules skipped]"
    results_path.write_text(buf.getvalue() + "\n" + summary + "\n", encoding="utf-8")
    print(summary)  # may be swallowed; the file is authoritative
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
