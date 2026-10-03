"""The ``.env`` parser. It follows python-dotenv's grammar so files mean the same thing.

The grammar is python-dotenv's (https://github.com/theskumar/python-dotenv), used
under the BSD-3-Clause license in LICENSES/python-dotenv.txt.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from typing import NamedTuple

_SINGLE_QUOTE_ESCAPES = {"\\": "\\", "'": "'"}
_DOUBLE_QUOTE_ESCAPES = {
    "\\": "\\",
    "'": "'",
    '"': '"',
    "a": "\a",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "v": "\v",
}


class Binding(NamedTuple):
    """One statement of a ``.env`` file."""

    key: str | None  # None for a comment
    value: str | None  # None for a bare `KEY` line without `=`
    line: int
    error: str | None  # why the statement could not be parsed


class _ParseError(Exception):
    pass


def parse_dotenv(text: str) -> dict[str, str]:
    """Parse the contents of a ``.env`` file into a dict.

    The syntax is python-dotenv's: ``KEY=value``, ``export KEY=value``, ``#``
    comments, 'single quotes' (only ``\\'`` and ``\\\\`` escapes), "double quotes"
    (``\\n``, ``\\t``, ``\\"`` and friends), quoted values spanning several lines,
    and bare ``KEY`` lines, which set nothing. ``${VAR}`` is left as it is here.
    Raises ``ValueError`` naming the bad line.
    """
    values = dict(parse_pairs(text))
    return {key: value for key, value in values.items() if value is not None}


def parse_pairs(text: str) -> list[tuple[str, str | None]]:
    """Return every ``(key, value)`` in file order; raise ``ValueError`` on a bad line."""
    pairs = []
    for binding in parse_bindings(text):
        if binding.error is not None:
            raise ValueError(f"line {binding.line}: {binding.error}")
        if binding.key is not None:
            pairs.append((binding.key, binding.value))
    return pairs


def parse_bindings(text: str) -> Iterator[Binding]:
    """Yield every statement, including the ones that failed to parse."""
    scanner = _Scanner(text)
    while True:
        binding = scanner.statement()
        if binding is None:
            return
        yield binding


def resolve_variables(
    pairs: list[tuple[str, str | None]], outer: Mapping[str, str], *, outer_wins: bool
) -> dict[str, str | None]:
    """Expand ``${VAR}`` and ``${VAR:-default}`` in values, in file order.

    A reference sees the values defined above it in the file and ``outer``
    (usually the environment); ``outer_wins`` picks which one takes priority.
    """
    resolved: dict[str, str | None] = {}
    first, second = (outer, resolved) if outer_wins else (resolved, outer)
    for key, value in pairs:
        resolved[key] = None if value is None else _expand(value, first, second)
    return resolved


def _expand(value: str, first: Mapping[str, str | None], second: Mapping[str, str | None]) -> str:
    parts = []
    i = 0
    while (start := value.find("${", i)) != -1:
        reference = _reference_at(value, start)
        if reference is None:  # not a complete ${...}: keep the text as it is
            parts.append(value[i : start + 1])
            i = start + 1
            continue
        name, default, end = reference
        if name in first:
            found = first[name]
        elif name in second:
            found = second[name]
        else:
            found = default
        parts.append(value[i:start])
        parts.append(found or "")
        i = end
    parts.append(value[i:])
    return "".join(parts)


def _reference_at(value: str, start: int) -> tuple[str, str | None, int] | None:
    """Parse ``${NAME}`` or ``${NAME:-default}`` at ``start``: (name, default, end)."""
    i = start + 2
    while i < len(value) and value[i] not in "}:":
        i += 1
    name = value[start + 2 : i]
    if value[i : i + 1] == "}":
        return name, None, i + 1
    if value.startswith(":-", i):
        close = value.find("}", i + 2)
        if close != -1:
            return name, value[i + 2 : close], close + 1
    return None


def _is_inline_space(char: str) -> bool:
    return char.isspace() and char not in "\r\n"


class _Scanner:
    """Reads statements one at a time; mirrors python-dotenv's grammar step by step."""

    def __init__(self, text: str) -> None:
        self.text = text[1:] if text.startswith("﻿") else text
        self.pos = 0
        self.line = 1

    def statement(self) -> Binding | None:
        self._advance(self._skip(self.pos, str.isspace))
        if self.pos == len(self.text):
            return None
        line = self.line
        try:
            key, value = self._binding()
        except _ParseError as exc:
            self._advance(self._rest_of_line())
            return Binding(None, None, line, str(exc))
        return Binding(key, value, line, None)

    def _binding(self) -> tuple[str | None, str | None]:
        self._export()
        key = self._key()
        self._advance(self._skip(self.pos, _is_inline_space))
        value = None
        quoted = False
        if self._peek() == "=":
            after_space = self._skip(self.pos + 1, _is_inline_space)
            spaced = after_space > self.pos + 1
            self._advance(after_space)
            if spaced and self._peek() == "#":
                value = ""  # `KEY= # note`: empty value, then a comment
            else:
                quoted = self._peek() in ("'", '"')
                value = self._value()
        self._comment()
        self._end_of_line(quoted)
        return key, value

    # -- steps: each one advances only when it succeeds ------------------

    def _export(self) -> None:
        if self.text.startswith("export", self.pos):
            end = self._skip(self.pos + 6, _is_inline_space)
            if end > self.pos + 6:
                self._advance(end)

    def _key(self) -> str | None:
        char = self._peek()
        if char == "#":
            return None
        if char == "'":
            close = self.text.find("'", self.pos + 1)
            if close <= self.pos + 1:
                raise _ParseError("expected KEY=VALUE")
            key = self.text[self.pos + 1 : close]
            self._advance(close + 1)
            return key
        end = self._skip(self.pos, lambda c: c not in "=#" and not c.isspace())
        if end == self.pos:
            raise _ParseError("expected KEY=VALUE")
        key = self.text[self.pos : end]
        self._advance(end)
        return key

    def _value(self) -> str:
        char = self._peek()
        if char == "'":
            return self._quoted("'", _SINGLE_QUOTE_ESCAPES)
        if char == '"':
            return self._quoted('"', _DOUBLE_QUOTE_ESCAPES)
        end = self._line_end(self.pos)
        value = _strip_inline_comment(self.text[self.pos : end]).rstrip()
        self._advance(end)
        return value

    def _quoted(self, quote: str, escapes: dict[str, str]) -> str:
        i = self.pos + 1
        while i < len(self.text):
            char = self.text[i]
            if char == "\\":
                if i + 1 == len(self.text):
                    break
                i += 2
            elif char == quote:
                body = self.text[self.pos + 1 : i]
                self._advance(i + 1)
                return _unescape(body, escapes)
            else:
                i += 1
        raise _ParseError(f"missing closing {quote}")

    def _comment(self) -> None:
        start = self._skip(self.pos, _is_inline_space)
        if self.text[start : start + 1] == "#":
            self._advance(self._line_end(start))

    def _end_of_line(self, quoted: bool) -> None:
        i = self._skip(self.pos, _is_inline_space)
        if self.text.startswith("\r\n", i):
            i += 2
        elif self.text[i : i + 1] in ("\r", "\n"):
            i += 1
        elif i < len(self.text):
            if quoted:
                rest = self.text[i : self._line_end(i)].strip()
                raise _ParseError(f"unexpected text after closing quote: {rest!r}")
            raise _ParseError("expected KEY=VALUE")
        self._advance(i)

    def _rest_of_line(self) -> int:
        # Like python-dotenv, a lone "\r" counts as the line break here.
        end = self._line_end(self.pos)
        return end + 1 if end < len(self.text) else end

    # -- helpers ---------------------------------------------------------

    def _peek(self) -> str:
        return self.text[self.pos : self.pos + 1]

    def _skip(self, i: int, wanted: Callable[[str], bool]) -> int:
        while i < len(self.text) and wanted(self.text[i]):
            i += 1
        return i

    def _line_end(self, i: int) -> int:
        return self._skip(i, lambda c: c not in "\r\n")

    def _advance(self, end: int) -> None:
        for i in range(self.pos, end):
            char = self.text[i]
            # "\r\n" is one line break, even when it is consumed in two steps.
            if char == "\r" or (char == "\n" and (i == 0 or self.text[i - 1] != "\r")):
                self.line += 1
        self.pos = end


def _strip_inline_comment(value: str) -> str:
    """Cut an unquoted value at the first ``#`` that has whitespace before it."""
    for i in range(1, len(value)):
        if value[i] == "#" and value[i - 1].isspace():
            start = i - 1
            while start > 0 and value[start - 1].isspace():
                start -= 1
            return value[:start]
    return value


def _unescape(body: str, escapes: dict[str, str]) -> str:
    parts = []
    i = 0
    while i < len(body):
        if body[i] == "\\" and body[i + 1 : i + 2] in escapes:
            parts.append(escapes[body[i + 1]])
            i += 2
        else:
            parts.append(body[i])
            i += 1
    return "".join(parts)
