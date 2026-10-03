from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import NoReturn

import pytest

from tidyenv import Env, EnvError, Problem


def make(**values: str) -> Env:
    return Env(environ=values)


def _raise(exc: Exception) -> NoReturn:
    raise exc


def test_reads_each_type() -> None:
    env = make(
        S=" hi ",
        I="1_000",
        F="0.5",
        B="Yes",
        L="a, b,, c",
        N="1,2",
        C="dev",
        P="~/x",
        J='{"a": [1]}',
    )
    assert env.str("S") == "hi"
    assert env.int("I") == 1000
    assert env.float("F") == 0.5
    assert env.bool("B") is True
    assert env.list("L") == ["a", "b", "c"]
    assert env.list("N", of=int) == [1, 2]
    assert env.choice("C", ["dev", "prod"]) == "dev"
    assert env.path("P") == Path("~/x").expanduser()
    assert env.json("J") == {"a": [1]}


@pytest.mark.parametrize("raw", ["0", "false", "NO", "n", "Off"])
def test_false_values(raw: str) -> None:
    assert make(B=raw).bool("B") is False


def test_defaults_apply_when_missing_or_empty() -> None:
    env = make(EMPTY="  ")
    assert env.int("NOPE", default=8000) == 8000
    assert env.str("EMPTY", default=None) is None
    assert env.bool("EMPTY", default=True) is True


def test_str_allow_empty(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("FROM_FILE=\n")
    env = make(EMPTY="", BLANK="  ", SET=" x ").read_dotenv(tmp_path / ".env")
    assert env.str("EMPTY", allow_empty=True) == ""
    assert env.str("BLANK", allow_empty=True) == ""
    assert env.str("FROM_FILE", allow_empty=True) == ""
    assert env.str("SET", allow_empty=True) == "x"
    assert env.str("NOPE", default=None, allow_empty=True) is None
    with pytest.raises(EnvError, match="NOPE: is not set"):
        env.str("NOPE", allow_empty=True)
    with pytest.raises(EnvError) as info:
        env.str("EMPTY")  # without allow_empty, empty still counts as missing
    assert info.value.problems == [
        Problem("EMPTY", "is empty (pass allow_empty=True if an empty value is valid)")
    ]
    with pytest.raises(EnvError) as info:
        env.int("EMPTY")
    assert info.value.problems == [Problem("EMPTY", "is empty")]


def test_missing_raises_immediately() -> None:
    with pytest.raises(EnvError) as info:
        make().str("TOKEN")
    assert info.value.problems == [Problem("TOKEN", "is not set")]
    assert str(info.value) == "1 environment problem:\n  - TOKEN: is not set"


@pytest.mark.parametrize(
    ("method", "raw", "message"),
    [
        ("int", "abc", "expected an integer"),
        ("float", "abc", "expected a number"),
        ("bool", "maybe", "expected true/false, yes/no, on/off or 1/0"),
        ("json", "{", "invalid JSON"),
    ],
)
def test_invalid_values_explain_themselves(method: str, raw: str, message: str) -> None:
    with pytest.raises(EnvError, match=message) as info:
        getattr(make(X=raw), method)("X")
    assert f"(got {raw!r})" in str(info.value)


def test_choice_lists_options() -> None:
    with pytest.raises(EnvError, match="expected one of dev, prod"):
        make(C="qa").choice("C", ["dev", "prod"])


@pytest.mark.parametrize("raw", ["prod", "PROD", "Prod"])
def test_choice_ignores_case_and_returns_the_listed_spelling(raw: str) -> None:
    assert make(C=raw).choice("C", ["dev", "prod"]) == "prod"


def test_choice_needs_an_exact_match_when_choices_differ_only_in_case() -> None:
    env = make(EXACT="A", OTHER="b")
    assert env.choice("EXACT", ["a", "A", "b"]) == "A"
    assert env.choice("OTHER", ["a", "A", "B"]) == "B"
    with pytest.raises(EnvError, match="expected one of ß, SS"):
        make(C="ss").choice("C", ["ß", "SS"])  # matches both when case is ignored


def test_path_must_exist(tmp_path: Path) -> None:
    env = make(OK=str(tmp_path), BAD=str(tmp_path / "missing"))
    assert env.path("OK", must_exist=True) == tmp_path
    with pytest.raises(EnvError, match="path does not exist"):
        env.path("BAD", must_exist=True)


def test_list_item_conversion_errors_are_friendly() -> None:
    with pytest.raises(EnvError) as info:
        make(PORTS="80,,x").list("PORTS", of=int)
    assert info.value.problems == [
        Problem("PORTS", "item 2 ('x'): expected an integer (got '80,,x')")
    ]


def test_list_uses_reader_rules_for_builtin_types() -> None:
    env = make(FLAGS="yes, off", RATES="0.5, 1")
    assert env.list("FLAGS", of=bool) == [True, False]
    assert env.list("RATES", of=float) == [0.5, 1.0]


def test_list_custom_converter_errors() -> None:
    def lookup(item: str) -> int:
        return {"a": 1}[item]

    with pytest.raises(EnvError, match=r"item 2 \('b'\): KeyError: 'b'"):
        make(L="a,b").list("L", of=lookup)
    with pytest.raises(EnvError, match=r"item 1 \('x'\): bad x"):
        make(L="x").list("L", of=lambda item: _raise(ValueError(f"bad {item}")))


@pytest.mark.parametrize(
    "of",
    # int() itself puts the value into its message, which must not leak.
    [int, lambda item: int(item)],
    ids=["builtin", "custom"],
)
def test_list_secret_items_are_hidden(of: Callable[[str], object]) -> None:
    with pytest.raises(EnvError) as info:
        make(KEYS="1,hunter2").list("KEYS", of=of, secret=True)
    message = str(info.value)
    assert "hunter2" not in message
    assert "KEYS: item 2: " in message
    assert message.endswith("(got ***)")


def test_list_types() -> None:
    env = make(P="1,2")
    ports: list[int] = env.list("P", of=int)
    hosts: list[str] | None = env.list("H", default=None)
    assert ports == [1, 2]
    assert hosts is None


@pytest.mark.parametrize("raw", ["__5", "1__0", "_1", "1_"])
def test_int_rejects_misplaced_underscores(raw: str) -> None:
    with pytest.raises(EnvError, match="expected an integer"):
        make(I=raw).int("I")


@pytest.mark.parametrize("raw", ["nan", "inf", "-Infinity"])
def test_float_rejects_non_finite(raw: str) -> None:
    with pytest.raises(EnvError, match="expected a finite number"):
        make(F=raw).float("F")


def test_secret_values_are_hidden() -> None:
    with pytest.raises(EnvError) as info:
        make(KEY="hunter2").int("KEY", secret=True)
    assert "hunter2" not in str(info.value)
    assert "(got ***)" in str(info.value)


def test_collect_reports_every_problem_at_once() -> None:
    env = make(PORT="eighty", DEBUG="true")
    with pytest.raises(EnvError) as info, env.collect():
        port = env.int("PORT")
        debug = env.bool("DEBUG")
        env.str("DATABASE_URL")
        assert port is None
        assert debug is True
    assert [p.name for p in info.value.problems] == ["PORT", "DATABASE_URL"]
    assert str(info.value).startswith("2 environment problems:")


def test_collect_passes_when_everything_is_fine() -> None:
    env = make(A="1")
    with env.collect():
        a = env.int("A")
    assert a == 1
    with pytest.raises(EnvError):
        env.int("B")  # back to raising right away


def test_collect_is_isolated_per_thread() -> None:
    env = make()
    inside, finished = threading.Event(), threading.Event()
    result: dict[str, str] = {}

    def collecting() -> None:
        with env.collect():
            inside.set()
            finished.wait(5)

    def reading() -> None:
        inside.wait(5)
        try:
            env.str("OTHER")
        except EnvError as exc:
            result["error"] = str(exc)
        finally:
            finished.set()

    threads = [threading.Thread(target=collecting), threading.Thread(target=reading)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert "OTHER: is not set" in result["error"]


def test_nested_collect_raises_inner_problems_only() -> None:
    env = make()
    with pytest.raises(EnvError) as outer, env.collect():
        env.str("A")
        with pytest.raises(EnvError) as inner, env.collect():
            env.str("B")
        env.str("C")
    assert [p.name for p in inner.value.problems] == ["B"]
    assert [p.name for p in outer.value.problems] == ["A", "C"]


def test_prefix() -> None:
    env = Env(environ={"APP_PORT": "1"}, prefix="APP_")
    assert env.int("PORT") == 1
    with pytest.raises(EnvError, match="APP_HOST: is not set"):
        env.str("HOST")


def test_default_env_reads_os_environ(monkeypatch: pytest.MonkeyPatch) -> None:
    from tidyenv import env

    monkeypatch.setenv("TIDYENV_TEST", "42")
    assert env.int("TIDYENV_TEST") == 42
