"""load_dotenv / dotenv_values / find_dotenv on their own (test_compat.py compares them
with python-dotenv, which isn't available on every Python we support)."""

from __future__ import annotations

import io
import logging
import os
import sys
import types
from pathlib import Path

import pytest

from tidyenv import dotenv_values, find_dotenv, load_dotenv


@pytest.fixture(autouse=True)
def fake_environ(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    environ = {"EXISTING": "real"}
    monkeypatch.setattr(os, "environ", environ)
    return environ


@pytest.fixture
def from_cwd(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make find_dotenv start at the current directory, as it does in a REPL."""
    monkeypatch.setattr(sys, "ps1", ">>> ", raising=False)


def test_load_dotenv_sets_missing_variables_only(
    tmp_path: Path, fake_environ: dict[str, str]
) -> None:
    file = tmp_path / ".env"
    file.write_text("EXISTING=file\nNEW=file\nBARE\n")
    assert load_dotenv(file) is True
    assert (fake_environ["EXISTING"], fake_environ["NEW"]) == ("real", "file")
    assert "BARE" not in fake_environ


def test_load_dotenv_override(fake_environ: dict[str, str]) -> None:
    assert load_dotenv(stream=io.StringIO("EXISTING=file"), override=True) is True
    assert fake_environ["EXISTING"] == "file"


def test_load_dotenv_first_file_wins(fake_environ: dict[str, str]) -> None:
    load_dotenv(stream=io.StringIO("A=first"))
    load_dotenv(stream=io.StringIO("A=second\nB=${A}"))
    assert (fake_environ["A"], fake_environ["B"]) == ("first", "first")


def test_load_dotenv_empty_or_missing_returns_false(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    assert load_dotenv(stream=io.StringIO("# only a comment\n")) is False
    with caplog.at_level(logging.INFO, logger="tidyenv"):
        assert load_dotenv(tmp_path / "missing.env", verbose=True) is False
    assert "could not find .env file" in caplog.text


def test_load_dotenv_prefers_an_existing_path_over_the_stream(tmp_path: Path) -> None:
    file = tmp_path / ".env"
    file.write_text("A=file")
    assert dotenv_values(file, stream=io.StringIO("A=stream")) == {"A": "file"}
    assert dotenv_values(tmp_path / "missing", stream=io.StringIO("A=stream")) == {"A": "stream"}


def test_load_dotenv_encoding(tmp_path: Path) -> None:
    file = tmp_path / ".env"
    file.write_bytes("A=é".encode("latin-1"))
    assert dotenv_values(file, encoding="latin-1") == {"A": "é"}


def test_load_dotenv_skips_bad_lines_with_a_warning(
    fake_environ: dict[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="tidyenv"):
        load_dotenv(stream=io.StringIO("A=1\nnot a line\nB=2"))
    assert (fake_environ["A"], fake_environ["B"]) == ("1", "2")
    assert "line 2: expected KEY=VALUE" in caplog.text


@pytest.mark.parametrize("value", ["1", "true", "YES", "y", "t"])
def test_load_dotenv_can_be_disabled(fake_environ: dict[str, str], value: str) -> None:
    fake_environ["PYTHON_DOTENV_DISABLED"] = value
    assert load_dotenv(stream=io.StringIO("A=1")) is False
    assert "A" not in fake_environ


@pytest.mark.usefixtures("from_cwd")
def test_load_dotenv_finds_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_environ: dict[str, str]
) -> None:
    (tmp_path / ".env").write_text("A=1")
    nested = tmp_path / "sub"
    nested.mkdir()
    monkeypatch.chdir(nested)
    assert load_dotenv() is True
    assert dotenv_values() == {"A": "1"}
    assert fake_environ["A"] == "1"


def test_dotenv_values(fake_environ: dict[str, str]) -> None:
    text = "EXISTING=file\nA=${EXISTING}\nB=${NOPE:-d}\nBARE\nC=${BARE:-d}"
    assert dotenv_values(stream=io.StringIO(text)) == {
        "EXISTING": "file",
        "A": "file",  # the file's own values beat the environment here
        "B": "d",
        "BARE": None,
        "C": "",
    }
    assert dotenv_values(stream=io.StringIO("A=${EXISTING}"), interpolate=False) == {
        "A": "${EXISTING}"
    }
    assert fake_environ["EXISTING"] == "real"
    assert "A" not in fake_environ


@pytest.mark.usefixtures("from_cwd")
def test_find_dotenv_walks_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "app.env").write_text("")
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)
    assert find_dotenv("app.env") == str(tmp_path / "app.env")
    assert find_dotenv("tidyenv-missing.env") == ""
    with pytest.raises(OSError, match="File not found"):
        find_dotenv("tidyenv-missing.env", raise_error_if_not_found=True)


def test_find_dotenv_starts_next_to_the_calling_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "gettrace", lambda: None)  # coverage counts as a debugger
    caller = tmp_path / "pkg" / "settings.py"
    caller.parent.mkdir()
    caller.write_text("")
    (tmp_path / "app.env").write_text("")
    namespace: dict[str, object] = {"find_dotenv": find_dotenv}
    exec(compile("found = find_dotenv('app.env')", str(caller), "exec"), namespace)
    assert namespace["found"] == str(tmp_path / "app.env")


@pytest.mark.parametrize("setup", ["usecwd", "ps2", "notebook", "frozen", "debugger"])
def test_find_dotenv_uses_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, setup: str) -> None:
    (tmp_path / "app.env").write_text("")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "gettrace", lambda: None)
    if setup == "ps2":
        monkeypatch.setattr(sys, "ps2", "... ", raising=False)
    elif setup == "notebook":
        monkeypatch.setitem(sys.modules, "__main__", types.ModuleType("__main__"))
    elif setup == "frozen":
        monkeypatch.setattr(sys, "frozen", True, raising=False)
    elif setup == "debugger":
        monkeypatch.setattr(sys, "gettrace", lambda: print)
    assert find_dotenv("app.env", usecwd=setup == "usecwd") == str(tmp_path / "app.env")


def test_find_dotenv_without_main_module(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "gettrace", lambda: None)
    monkeypatch.delitem(sys.modules, "__main__")
    assert find_dotenv("tidyenv-missing.env") == ""


def test_find_dotenv_missing_start(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "getcwd", lambda: "/tidyenv/does/not/exist")
    with pytest.raises(OSError, match="Starting path not found"):
        find_dotenv(usecwd=True)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="needs named pipes")
def test_find_dotenv_accepts_a_named_pipe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    os.mkfifo(tmp_path / ".env")
    monkeypatch.chdir(tmp_path)
    assert find_dotenv(usecwd=True) == str(tmp_path / ".env")
