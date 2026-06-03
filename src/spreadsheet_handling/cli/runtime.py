from __future__ import annotations
import sys
import traceback
from typing import Optional, Protocol


class MainFunc(Protocol):
    def __call__(self, argv: Optional[list[str]] = None) -> int: ...


def _count_verbose(argv: list[str]) -> int:
    """Cheap-peek verbosity count before argparse runs.

    Mirrors argparse ``action="count"`` semantics for the common patterns
    the runner exposes via ``-v`` / ``--verbose``: every ``--verbose``
    counts as 1, and every short token of the form ``-v``, ``-vv``,
    ``-vvv``, ... contributes ``len(token) - 1``. Combinations are
    additive, so ``--verbose --verbose``, ``-v -v``, ``-vv`` and ``-vvv``
    all yield a verbosity that crosses the traceback threshold.
    """
    count = 0
    for token in argv:
        if token == "--verbose":
            count += 1
        elif len(token) > 1 and token.startswith("-") and set(token[1:]) == {"v"}:
            count += len(token) - 1
    return count


def run_cli(main_func: MainFunc) -> None:
    """
    Lightweight CLI wrapper for consistent process exit & error UX.

    - Calls main_func(argv) and exits with its return code.
    - Shows full tracebacks only if '--debug' present OR verbosity >= 2
      (any combination of '-v' / '--verbose' that argparse would count
      as >= 2, e.g. '-vv', '-v -v', '--verbose --verbose').
    - Otherwise prints a concise 'Error: ...' line for exceptions or
      'Interrupted by user.' for Ctrl+C.
    """
    argv = sys.argv[1:]
    debug = "--debug" in argv
    verbosity = _count_verbose(argv)

    try:
        code = main_func(argv)
    except SystemExit:
        # honor explicit sys.exit / SystemExit from inside
        raise
    except KeyboardInterrupt:
        # KeyboardInterrupt is a BaseException, not Exception, so it must be
        # caught separately. Exit code 130 follows the POSIX SIGINT
        # convention (128 + signal number 2); as an integer literal it is
        # portable across platforms and does not depend on the signal module.
        if debug or verbosity >= 2:
            traceback.print_exc()
        else:
            print("Interrupted by user.", file=sys.stderr)
        raise SystemExit(130)
    except Exception as e:
        if debug or verbosity >= 2:
            traceback.print_exc()
        else:
            print(f"Error: {e}", file=sys.stderr)
        raise SystemExit(1)
    else:
        raise SystemExit(code)
