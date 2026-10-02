from __future__ import annotations

import re

# The value keeps its leading whitespace: `A= # note` is an empty value plus a comment.
_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_.]*)\s*=(.*?)\s*$")
_ESCAPES = {"n": "\n", "r": "\r", "t": "\t", '"': '"', "\\": "\\"}


def parse_dotenv(text: str) -> dict[str, str]:
    """Parse the contents of a ``.env`` file into a dict.

    Supports ``KEY=value``, ``export KEY=value``, ``#`` comments, blank lines,
    'single quotes' (taken literally) and "double quotes" (with ``\\n``, ``\\t``,
    ``\\"`` and ``\\\\`` escapes). Values must fit on one line.
    Raises ``ValueError`` naming the bad line.
    """
    values: dict[str, str] = {}
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = _LINE.match(line)
        if match is None:
            raise ValueError(f"line {lineno}: expected KEY=VALUE")
        key, raw = match.groups()
        try:
            values[key] = _value(raw)
        except ValueError as exc:
            raise ValueError(f"line {lineno}: {exc}") from None
    return values


def _value(raw: str) -> str:
    value = raw.lstrip()
    if value[:1] in ("'", '"'):
        quote = value[0]
        end = _closing_quote(value, quote)
        rest = value[end + 1 :].strip()
        if rest and not rest.startswith("#"):
            raise ValueError(f"unexpected text after closing quote: {rest!r}")
        body = value[1:end]
        if quote == "'":
            return body
        return re.sub(r"\\(.)", lambda m: _ESCAPES.get(m.group(1), m.group(0)), body)
    # Unquoted: an inline comment needs whitespace before the '#'; the space after
    # '=' counts, so `A= # note` is empty while `A=#x` is the literal '#x'.
    return re.split(r"\s+#", raw, maxsplit=1)[0].strip()


def _closing_quote(raw: str, quote: str) -> int:
    i = 1
    while i < len(raw):
        if raw[i] == "\\" and quote == '"':
            i += 2
            continue
        if raw[i] == quote:
            return i
        i += 1
    raise ValueError(f"missing closing {quote}")
