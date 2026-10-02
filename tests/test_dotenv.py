from __future__ import annotations

from pathlib import Path

import pytest

from tidyenv import Env, EnvError, parse_dotenv


def test_parse_dotenv() -> None:
    text = r"""
# comment
PORT=8000
export DEBUG = yes
EMPTY=
COMMENTED= # nothing here
HASH=#literal
QUOTED_AFTER_SPACE=  "x"
URL=http://x/#anchor   # trailing comment
SINGLE='raw \n # kept'
DOUBLE="line\nnext \"quoted\" \\ \q"  # comment
"""
    assert parse_dotenv(text) == {
        "PORT": "8000",
        "DEBUG": "yes",
        "EMPTY": "",
        "COMMENTED": "",
        "HASH": "#literal",
        "QUOTED_AFTER_SPACE": "x",
        "URL": "http://x/#anchor",
        "SINGLE": r"raw \n # kept",
        "DOUBLE": 'line\nnext "quoted" \\ \\q',
    }


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("A=1\nnot a line", "line 2: expected KEY=VALUE"),
        ('A="open', 'line 1: missing closing "'),
        ("A='x' y", "line 1: unexpected text after closing quote: 'y'"),
    ],
)
def test_parse_dotenv_errors(text: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_dotenv(text)


def test_read_dotenv_fills_gaps_but_real_env_wins(tmp_path: Path) -> None:
    file = tmp_path / ".env"
    file.write_text("PORT=1\nHOST=example.com\n")
    env = Env(environ={"PORT": "2"}).read_dotenv(file)
    assert env.int("PORT") == 2
    assert env.str("HOST") == "example.com"


def test_read_dotenv_missing_file(tmp_path: Path) -> None:
    env = Env(environ={})
    assert env.read_dotenv(tmp_path / "nope") is env
    with pytest.raises(EnvError, match="file not found"):
        env.read_dotenv(tmp_path / "nope", required=True)


def test_read_dotenv_bad_file(tmp_path: Path) -> None:
    file = tmp_path / ".env"
    file.write_text("oops\n")
    with pytest.raises(EnvError, match=r"\.env: line 1: expected KEY=VALUE"):
        Env(environ={}).read_dotenv(file)


def test_read_dotenv_default_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("A=1")
    assert Env(environ={}).read_dotenv().int("A") == 1


def test_read_dotenv_later_files_override(tmp_path: Path) -> None:
    (tmp_path / "a.env").write_text("A=1\nB=1\n")
    (tmp_path / "b.env").write_text("B=2\n")
    env = Env(environ={}).read_dotenv(tmp_path / "a.env").read_dotenv(tmp_path / "b.env")
    assert (env.int("A"), env.int("B")) == (1, 2)


def test_read_dotenv_skips_bom(tmp_path: Path) -> None:
    file = tmp_path / ".env"
    file.write_bytes("\ufeffA=1\n".encode())
    assert Env(environ={}).read_dotenv(file).int("A") == 1


def test_read_dotenv_directory(tmp_path: Path) -> None:
    with pytest.raises(EnvError, match="not a file"):
        Env(environ={}).read_dotenv(tmp_path)


def test_read_dotenv_not_utf8(tmp_path: Path) -> None:
    file = tmp_path / ".env"
    file.write_bytes(b"A=\xff\n")
    with pytest.raises(EnvError, match="not valid UTF-8"):
        Env(environ={}).read_dotenv(file)


def test_read_dotenv_unreadable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    file = tmp_path / ".env"
    file.write_text("A=1\n")

    def deny(self: Path, encoding: str | None = None) -> str:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(Path, "read_text", deny)
    with pytest.raises(EnvError, match=r"\.env: Permission denied"):
        Env(environ={}).read_dotenv(file)
