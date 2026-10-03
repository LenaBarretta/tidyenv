"""Typed environment variables with friendly errors and built-in .env support."""

from tidyenv._compat import dotenv_values, find_dotenv, load_dotenv
from tidyenv._dotenv import parse_dotenv
from tidyenv._env import Env, EnvError, Problem

__all__ = [
    "Env",
    "EnvError",
    "Problem",
    "dotenv_values",
    "env",
    "find_dotenv",
    "load_dotenv",
    "parse_dotenv",
]
__version__ = "0.2.0"

# Show errors as tidyenv.EnvError, not tidyenv._env.EnvError.
for _cls in (Env, EnvError, Problem):
    _cls.__module__ = __name__

env = Env()
