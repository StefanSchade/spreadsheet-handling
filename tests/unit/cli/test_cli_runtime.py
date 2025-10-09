import io
import sys
import pytest
from spreadsheet_handling.cli.runtime import run_cli

# ---------------------------------------------------------------------
# Fake mains for exercising the wrapper
# ---------------------------------------------------------------------
def main_ok(argv=None) -> int:
    """simulates sucessful run of main"""
    return 0

def main_fail(argv=None) -> int:
    """simulates regular failurie code of main"""
    return 5

def main_exception(argv=None) -> int:
    """simulates uncaught exception in main"""
    raise ValueError("kaputt")

# ---------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------
def test_run_cli_ok(monkeypatch, capsys):
    """main() sucessful -> exit code 0, no error message"""
    with pytest.raises(SystemExit) as e:
        run_cli(main_ok)
    assert e.value.code == 0
    out, err = capsys.readouterr()
    assert out == ""
    assert err == ""


def test_run_cli_fail(monkeypatch, capsys):
    """main() returns 5 -> exit code 5"""
    with pytest.raises(SystemExit) as e:
        run_cli(main_fail)
    assert e.value.code == 5
    out, err = capsys.readouterr()
    assert "Error" not in err


def test_run_cli_exception_short(monkeypatch, capsys):
    """Exception without --debug or -vv -> short error message"""
    argv = ["prog"]
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as e:
        run_cli(main_exception)
    assert e.value.code == 1
    out, err = capsys.readouterr()
    assert "Error: kaputt" in err
    assert "Traceback" not in err


def test_run_cli_exception_debug(monkeypatch, capsys):
    """Exception with --debug -> full Traceback"""
    argv = ["prog", "--debug"]
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as e:
        run_cli(main_exception)
    assert e.value.code == 1
    out, err = capsys.readouterr()
    assert "Traceback" in err
    assert "ValueError: kaputt" in err


def test_run_cli_exception_verbose(monkeypatch, capsys):
    """Exception wit -vv -> full Traceback"""
    argv = ["prog", "-v", "-v"]
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as e:
        run_cli(main_exception)
    assert e.value.code == 1
    out, err = capsys.readouterr()
    assert "Traceback" in err
