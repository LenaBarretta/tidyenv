"""tidyenv's load_dotenv / dotenv_values / find_dotenv must match python-dotenv's exactly."""

from __future__ import annotations

import io
import os
import random
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

import tidyenv

dotenv = pytest.importorskip("dotenv")  # python-dotenv; installed for Python 3.10+

ENVIRON = {"A": "from-env", "EMPTY": ""}

EXAMPLES = [
    "",
    "A=1\nB=2",
    "export A=1",
    "A = 1 # comment\n# full line comment\n\n",
    "A= # empty\nB=#literal\nC=x#y\nD=x #y",
    "A='single \\' quote \\\\ \\n'",
    'A="double \\" \\n \\t \\a \\q"',
    'KEY="line one\nline two"\nNEXT=1',
    "A='x' trailing\nB=2",
    'A="unclosed\nB=2',
    "'quoted key'=1\n'=2",
    "BARE\nBARE2 # comment\nA=1\nA",
    "=nokey\nexport\nexport =1\nexportA=1",
    "A=1\r\nB=2\rC=3",
    "\ufeffA=1",
    "B=${A}\nC=${MISSING:-default}\nD=${B}${B}\nE=$A ${A\nF=${:-x}${}",
    "A=from-file\nB=${A}",
    "EMPTY=x\nB=${EMPTY:-d}",
    "A=1\nA=2\nB=${A}",
    "BARE\nB=${BARE:-d}",
]

TOKENS = [
    *("A", "B", "b.c", "export", "export ", " ", "  ", "\t", "=", "=", "#", " #"),
    *("'", '"', "\\", "\n", "\n", "\r\n", "\r", "$", "{", "}", ":-", ":"),
    *("${A}", "${B:-x}", "${C}", "${A:-}", "x", "y z", "\\n", "\\'", '\\"', "\\\\"),
    *("\x0b", "\x0c", "\u2028", "\x1c", "é", "\ufeff"),
]


def generated(count: int) -> Iterator[str]:
    """Random .env-ish texts built from the characters that matter to the grammar."""
    rng = random.Random(2026)
    for _ in range(count):
        yield "".join(rng.choice(TOKENS) for _ in range(rng.randint(1, 30)))


@pytest.fixture(autouse=True)
def fake_environ(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "environ", dict(ENVIRON))


def load_with(
    load: Callable[..., bool], texts: list[str], override: bool
) -> tuple[list[bool], dict[str, str]]:
    """Load ``texts`` in order into a fresh fake environment; return results and env."""
    os.environ.clear()
    os.environ.update(ENVIRON)
    results = [load(stream=io.StringIO(text), override=override) for text in texts]
    return results, dict(os.environ)


def check_same(text: str) -> None:
    for interpolate in (True, False):
        expected = dotenv.dotenv_values(stream=io.StringIO(text), interpolate=interpolate)
        actual = tidyenv.dotenv_values(stream=io.StringIO(text), interpolate=interpolate)
        assert actual == expected, (text, interpolate)
    for override in (False, True):
        expected_load = load_with(dotenv.load_dotenv, [text], override)
        assert load_with(tidyenv.load_dotenv, [text], override) == expected_load, (text, override)


@pytest.mark.parametrize("text", EXAMPLES)
def test_examples_match_python_dotenv(text: str) -> None:
    check_same(text)


def test_generated_files_match_python_dotenv() -> None:
    for text in generated(3000):
        check_same(text)


@pytest.mark.parametrize("override", [False, True])
def test_several_files_match_python_dotenv(override: bool) -> None:
    texts = ["A=first\nB=first\nC=${B}", "B=second\nC=${B}\nD=second", "E=${D}"]
    expected = load_with(dotenv.load_dotenv, texts, override)
    assert load_with(tidyenv.load_dotenv, texts, override) == expected


def test_find_dotenv_matches_python_dotenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".env").write_text("A=1")
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)
    assert tidyenv.find_dotenv(usecwd=True) == dotenv.find_dotenv(usecwd=True)
    assert tidyenv.find_dotenv("missing.env", usecwd=True) == ""
    assert dotenv.find_dotenv("missing.env", usecwd=True) == ""
