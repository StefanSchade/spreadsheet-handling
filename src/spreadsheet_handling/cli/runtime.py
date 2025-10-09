from __future__ import annotations
import sys
import traceback
from typing import Optional, Protocol


class MainFunc(Protocol):
    def __call__(self, argv: Optional[list[str]] = None) -> int: ...


def run_cli(main_func: MainFunc) -> None:
    """
    Lightweight CLI wrapper for consistent process exit & error UX.

    - Calls main_func(argv) and exits with its return code.
    - Shows full tracebacks only if '--debug' present OR verbosity >= 2 ('-vv').
    - Otherwise prints a concise 'Error: ...' line.
    """
    argv = sys.argv[1:]
    debug = "--debug" in argv
    # cheap peek: count '-v' occurrences; main() macht die echte Auswertung
    verbosity = sum(1 for a in argv if a == "-v") + (2 if "-vv" in argv else 0)

    try:
        code = main_func(argv)
    except SystemExit:
        # honor explicit sys.exit / SystemExit from inside
        raise
    except Exception as e:
        if debug or verbosity >= 2:
            traceback.print_exc()
        else:
            print(f"Error: {e}", file=sys.stderr)
        raise SystemExit(1)
    else:
        raise SystemExit(code)
