"""Replacements for python-dotenv's ``load_dotenv``, ``dotenv_values`` and
``find_dotenv``: same arguments, same results, so switching is a one-line import change.

Adapted from python-dotenv (https://github.com/theskumar/python-dotenv),
Copyright (c) 2014, Saurabh Kumar (python-dotenv), 2013, Ted Tieken
(django-dotenv-rw), 2013, Jacob Kaplan-Moss (django-dotenv), used under the
BSD-3-Clause license in LICENSES/python-dotenv.txt.
"""

from __future__ import annotations

import io
import logging
import os
import stat
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from typing import IO, Union

from tidyenv._dotenv import parse_bindings, resolve_variables

StrPath = Union[str, "os.PathLike[str]"]

logger = logging.getLogger("tidyenv")

_DISABLED = {"1", "true", "t", "yes", "y"}


def load_dotenv(
    dotenv_path: StrPath | None = None,
    stream: IO[str] | None = None,
    verbose: bool = False,
    override: bool = False,
    interpolate: bool = True,
    encoding: str | None = "utf-8",
) -> bool:
    """Load a ``.env`` file into ``os.environ``, like python-dotenv does.

    Without ``dotenv_path`` and ``stream``, :func:`find_dotenv` looks for ``.env``
    starting next to the calling file. Variables that are already set are kept
    unless ``override=True``, so when you load several files the first one wins.
    Lines that can't be parsed are skipped with a logged warning. Setting
    ``PYTHON_DOTENV_DISABLED=1`` turns loading off. Returns True if the file
    defined any variables.
    """
    if os.environ.get("PYTHON_DOTENV_DISABLED", "").casefold() in _DISABLED:
        logger.debug(".env loading disabled by PYTHON_DOTENV_DISABLED")
        return False
    if dotenv_path is None and stream is None:
        dotenv_path = find_dotenv()
    values = _values(dotenv_path, stream, verbose, interpolate, override, encoding)
    if not values:
        return False
    for key, value in values.items():
        if key in os.environ and not override:
            continue
        if value is not None:
            os.environ[key] = value
    return True


def dotenv_values(
    dotenv_path: StrPath | None = None,
    stream: IO[str] | None = None,
    verbose: bool = False,
    interpolate: bool = True,
    encoding: str | None = "utf-8",
) -> dict[str, str | None]:
    """Return the variables of a ``.env`` file as a dict, like python-dotenv does.

    A bare ``KEY`` line maps to ``None``. Nothing is written to ``os.environ``.
    """
    if dotenv_path is None and stream is None:
        dotenv_path = find_dotenv()
    return _values(dotenv_path, stream, verbose, interpolate, True, encoding)


def find_dotenv(
    filename: str = ".env",
    raise_error_if_not_found: bool = False,
    usecwd: bool = False,
) -> str:
    """Look for ``filename`` in the caller's directory and then in each parent.

    The search starts at the current directory instead when ``usecwd=True``, in a
    REPL or notebook, under a debugger, or in a frozen app. Returns the path, or
    ``""`` if there is no such file.
    """
    if usecwd or _is_interactive() or sys.gettrace() is not None or getattr(sys, "frozen", False):
        path = os.getcwd()
    else:
        frame = sys._getframe()
        while frame.f_code.co_filename == __file__ or not os.path.exists(frame.f_code.co_filename):
            assert frame.f_back is not None
            frame = frame.f_back
        path = os.path.dirname(os.path.abspath(frame.f_code.co_filename))

    for directory in _walk_to_root(path):
        candidate = os.path.join(directory, filename)
        if _is_file_or_fifo(candidate):
            return candidate
    if raise_error_if_not_found:
        raise OSError("File not found")
    return ""


def _values(
    dotenv_path: StrPath | None,
    stream: IO[str] | None,
    verbose: bool,
    interpolate: bool,
    override: bool,
    encoding: str | None,
) -> dict[str, str | None]:
    with _open(dotenv_path, stream, verbose, encoding) as source:
        text = source.read()
    pairs = []
    for binding in parse_bindings(text):
        if binding.error is not None:
            logger.warning(
                "could not parse .env statement at line %s: %s", binding.line, binding.error
            )
        elif binding.key is not None:
            pairs.append((binding.key, binding.value))
    if not interpolate:
        return dict(pairs)
    return resolve_variables(pairs, os.environ, outer_wins=not override)


@contextmanager
def _open(
    dotenv_path: StrPath | None, stream: IO[str] | None, verbose: bool, encoding: str | None
) -> Iterator[IO[str]]:
    if dotenv_path and _is_file_or_fifo(dotenv_path):
        with open(dotenv_path, encoding=encoding) as file:
            yield file
    elif stream is not None:
        yield stream
    else:
        if verbose:
            logger.info("could not find .env file %s", dotenv_path or ".env")
        yield io.StringIO("")


def _is_interactive() -> bool:
    """True in a REPL or a notebook, where there is no calling file to start from."""
    if hasattr(sys, "ps1") or hasattr(sys, "ps2"):
        return True
    main = sys.modules.get("__main__")
    return main is not None and not hasattr(main, "__file__")


def _walk_to_root(path: str) -> Iterator[str]:
    if not os.path.exists(path):
        raise OSError("Starting path not found")
    previous = None
    current = os.path.abspath(path)
    while previous != current:
        yield current
        previous, current = current, os.path.abspath(os.path.join(current, os.path.pardir))


def _is_file_or_fifo(path: StrPath) -> bool:
    """FIFOs count too, so ``.env`` can come from a secrets tool's named pipe."""
    if os.path.isfile(path):
        return True
    try:
        return stat.S_ISFIFO(os.stat(path).st_mode)
    except OSError:
        return False
