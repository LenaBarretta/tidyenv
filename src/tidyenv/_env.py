from __future__ import annotations

import json as _json
import math
import os
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar, overload

from tidyenv._dotenv import parse_pairs, resolve_variables

T = TypeVar("T")
U = TypeVar("U")

# Env has methods named str/int/list/...; these aliases keep the builtins reachable.
_str = str
_int = int
_float = float
_bool = bool
_list = list

_MISSING: Any = object()
_TRUE = {"1", "true", "yes", "y", "on"}
_FALSE = {"0", "false", "no", "n", "off"}


@dataclass(frozen=True)
class Problem:
    """One thing that is wrong with the environment."""

    name: str
    message: str

    def __str__(self) -> str:
        return f"{self.name}: {self.message}"


class EnvError(Exception):
    """Raised when one or more environment variables are missing or invalid."""

    def __init__(self, problems: Sequence[Problem]) -> None:
        self.problems = list(problems)
        lines = "\n".join(f"  - {p}" for p in self.problems)
        noun = "problem" if len(self.problems) == 1 else "problems"
        super().__init__(f"{len(self.problems)} environment {noun}:\n{lines}")


class Env:
    """Reads typed values from the environment.

    Each reader raises :class:`EnvError` right away, unless it runs inside
    :meth:`collect`, which gathers every problem and raises once at the end.
    """

    def __init__(self, environ: Mapping[_str, _str] | None = None, prefix: _str = "") -> None:
        self._environ = environ
        self.prefix = prefix
        self._dotenv: dict[_str, _str] = {}
        # Per thread / async task, so a collect() in one never swallows another's errors.
        self._pending: ContextVar[_list[Problem] | None] = ContextVar(
            "tidyenv_pending", default=None
        )

    @property
    def environ(self) -> Mapping[_str, _str]:
        return os.environ if self._environ is None else self._environ

    def read_dotenv(
        self,
        path: _str | os.PathLike[_str] = ".env",
        *,
        required: _bool = False,
        interpolate: _bool = True,
    ) -> Env:
        """Use values from a ``.env`` file for variables the environment doesn't set.

        The rules are python-dotenv's ``load_dotenv``: real environment variables
        always win, and when several files are read the first one to set a
        variable wins. ``${VAR}`` and ``${VAR:-default}`` are expanded unless
        ``interpolate=False``. Unlike ``load_dotenv``, nothing is written to
        ``os.environ`` and a line that can't be parsed is an error.
        A missing file is skipped unless ``required=True``.
        Returns ``self``, so ``env = Env().read_dotenv()`` works.
        """
        file = Path(path)
        if not file.exists():
            if required:
                raise EnvError([Problem(_str(file), "file not found")])
            return self
        if not file.is_file():
            raise EnvError([Problem(_str(file), "not a file")])
        try:
            # utf-8-sig drops the BOM that some Windows editors add.
            text = file.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            raise EnvError([Problem(_str(file), "not valid UTF-8")]) from None
        except OSError as exc:
            raise EnvError([Problem(_str(file), exc.strerror or _str(exc))]) from None
        try:
            pairs = parse_pairs(text)
        except ValueError as exc:
            raise EnvError([Problem(_str(file), _str(exc))]) from None
        if interpolate:
            # References see earlier files too, and the environment beats both.
            outer = {**self._dotenv, **self.environ}
            values = resolve_variables(pairs, outer, outer_wins=True)
        else:
            values = dict(pairs)
        for key, value in values.items():
            if value is not None:
                self._dotenv.setdefault(key, value)
        return self

    @contextmanager
    def collect(self) -> Iterator[Env]:
        """Gather problems from every read inside the block, then raise them together.

        Failed reads return ``None`` inside the block, so don't use those
        values until the block has exited cleanly.
        """
        token = self._pending.set([])
        try:
            yield self
            problems = self._pending.get()
        finally:
            self._pending.reset(token)
        if problems:
            raise EnvError(problems)

    # -- readers ---------------------------------------------------------
    # Each reader returns its type, or the type of `default` when one is given.

    @overload
    def str(self, name: _str, *, secret: _bool = ..., allow_empty: _bool = ...) -> _str: ...
    @overload
    def str(
        self, name: _str, default: T, *, secret: _bool = ..., allow_empty: _bool = ...
    ) -> _str | T: ...
    def str(
        self,
        name: _str,
        default: Any = _MISSING,
        *,
        secret: _bool = False,
        allow_empty: _bool = False,
    ) -> Any:
        """Read a string. Values are stripped.

        An empty value counts as missing, unless ``allow_empty=True``: then a
        variable that is set but empty gives ``""`` (one that isn't set at all
        is still missing).
        """
        return self._read(name, default, lambda raw: raw, secret=secret, allow_empty=allow_empty)

    @overload
    def int(self, name: _str, *, secret: _bool = ...) -> _int: ...
    @overload
    def int(self, name: _str, default: T, *, secret: _bool = ...) -> _int | T: ...
    def int(self, name: _str, default: Any = _MISSING, *, secret: _bool = False) -> Any:
        """Read an integer, e.g. ``8000`` or ``1_000``."""
        return self._read(name, default, _parse_int, secret=secret)

    @overload
    def float(self, name: _str, *, secret: _bool = ...) -> _float: ...
    @overload
    def float(self, name: _str, default: T, *, secret: _bool = ...) -> _float | T: ...
    def float(self, name: _str, default: Any = _MISSING, *, secret: _bool = False) -> Any:
        """Read a number, e.g. ``0.25``."""
        return self._read(name, default, _parse_float, secret=secret)

    @overload
    def bool(self, name: _str) -> _bool: ...
    @overload
    def bool(self, name: _str, default: T) -> _bool | T: ...
    def bool(self, name: _str, default: Any = _MISSING) -> Any:
        """Read a boolean: 1/true/yes/y/on or 0/false/no/n/off, in any case."""
        return self._read(name, default, _parse_bool)

    @overload
    def list(self, name: _str, *, sep: _str = ..., secret: _bool = ...) -> _list[_str]: ...
    @overload
    def list(
        self, name: _str, default: T, *, sep: _str = ..., secret: _bool = ...
    ) -> _list[_str] | T: ...
    @overload
    def list(
        self, name: _str, *, sep: _str = ..., of: Callable[[_str], U], secret: _bool = ...
    ) -> _list[U]: ...
    @overload
    def list(
        self,
        name: _str,
        default: T,
        *,
        sep: _str = ...,
        of: Callable[[_str], U],
        secret: _bool = ...,
    ) -> _list[U] | T: ...
    def list(
        self,
        name: _str,
        default: Any = _MISSING,
        *,
        sep: _str = ",",
        of: Callable[[_str], Any] = _str,
        secret: _bool = False,
    ) -> Any:
        """Read a separated list, e.g. ``a, b, c``. Items are stripped; blanks dropped.

        ``of`` converts each item, e.g. ``of=int``. ``int``, ``float`` and ``bool``
        use the same rules as the matching readers, so ``of=bool`` understands ``no``.
        """
        known = of in _ITEM_PARSERS
        convert = _ITEM_PARSERS.get(of, of)

        def parse(raw: _str) -> _list[Any]:
            items = [item.strip() for item in raw.split(sep)]
            values = []
            for number, item in enumerate((item for item in items if item), start=1):
                try:
                    values.append(convert(item))
                except Exception as exc:
                    label = f"item {number}" if secret else f"item {number} ({item!r})"
                    raise ValueError(f"{label}: {_item_error(exc, known, secret)}") from None
            return values

        return self._read(name, default, parse, secret=secret)

    @overload
    def choice(self, name: _str, choices: Sequence[_str]) -> _str: ...
    @overload
    def choice(self, name: _str, choices: Sequence[_str], default: T) -> _str | T: ...
    def choice(self, name: _str, choices: Sequence[_str], default: Any = _MISSING) -> Any:
        """Read a string that must be one of ``choices``, in any case.

        Returns the choice as written in ``choices``, so ``PROD`` gives ``"prod"``.
        Choices that differ only in case (``"a"``, ``"A"``) need an exact match.
        """

        def parse(raw: _str) -> _str:
            if raw in choices:
                return raw
            matches = [choice for choice in choices if choice.casefold() == raw.casefold()]
            if len(matches) != 1:
                raise ValueError(f"expected one of {', '.join(choices)}")
            return matches[0]

        return self._read(name, default, parse)

    @overload
    def path(self, name: _str, *, must_exist: _bool = ...) -> Path: ...
    @overload
    def path(self, name: _str, default: T, *, must_exist: _bool = ...) -> Path | T: ...
    def path(self, name: _str, default: Any = _MISSING, *, must_exist: _bool = False) -> Any:
        """Read a filesystem path, with ``~`` expanded."""

        def parse(raw: _str) -> Path:
            p = Path(raw).expanduser()
            if must_exist and not p.exists():
                raise ValueError("path does not exist")
            return p

        return self._read(name, default, parse)

    def json(self, name: _str, default: Any = _MISSING, *, secret: _bool = False) -> Any:
        """Read a JSON value, e.g. ``{"a": 1}``."""
        return self._read(name, default, _parse_json, secret=secret)

    # -- internals -------------------------------------------------------

    def _read(
        self,
        name: _str,
        default: Any,
        parse: Callable[[_str], Any],
        *,
        secret: _bool = False,
        allow_empty: _bool | None = None,
    ) -> Any:
        """``allow_empty`` is None for readers that have no such option."""
        key = self.prefix + name
        raw = self.environ.get(key)
        if raw is None:
            raw = self._dotenv.get(key)
        if allow_empty and raw is not None and raw.strip() == "":
            return ""
        if raw is None or raw.strip() == "":
            if default is not _MISSING:
                return default
            if raw is None:
                return self._fail(key, "is not set")
            hint = (
                "" if allow_empty is None else " (pass allow_empty=True if an empty value is valid)"
            )
            return self._fail(key, "is empty" + hint)
        try:
            return parse(raw.strip())
        except (ValueError, TypeError) as exc:
            shown = "***" if secret else repr(raw)
            return self._fail(key, f"{exc} (got {shown})")

    def _fail(self, key: _str, message: _str) -> None:
        problem = Problem(key, message)
        pending = self._pending.get()
        if pending is None:
            raise EnvError([problem])
        pending.append(problem)
        return None


def _parse_int(raw: str) -> int:
    try:
        return int(raw)  # int() already accepts 1_000 but rejects 1__0 and _1
    except ValueError:
        raise ValueError("expected an integer") from None


def _parse_float(raw: str) -> float:
    try:
        value = float(raw)
    except ValueError:
        raise ValueError("expected a number") from None
    if not math.isfinite(value):
        raise ValueError("expected a finite number")
    return value


def _parse_bool(raw: str) -> bool:
    value = raw.lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise ValueError("expected true/false, yes/no, on/off or 1/0")


def _parse_json(raw: str) -> Any:
    try:
        return _json.loads(raw)
    except _json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc.msg}") from None


def _parse_str(raw: str) -> str:
    return raw


# Converters for env.list(of=...) that get the readers' rules and friendly messages.
_ITEM_PARSERS: dict[Callable[[str], Any], Callable[[str], Any]] = {
    str: _parse_str,
    int: _parse_int,
    float: _parse_float,
    bool: _parse_bool,
}


def _item_error(exc: Exception, known: bool, secret: bool) -> str:
    """Describe why ``of`` rejected a list item without leaking a secret value."""
    if known:
        return str(exc)  # our own messages never contain the value
    if secret:
        return "invalid value"
    if isinstance(exc, (ValueError, TypeError)):
        return str(exc)
    return f"{type(exc).__name__}: {exc}"
