<p align="center">
  <img src="https://raw.githubusercontent.com/LenaBarretta/tidyenv/main/docs/logo.png" alt="tidyenv logo" width="160">
</p>

# tidyenv

[![PyPI](https://img.shields.io/pypi/v/tidyenv)](https://pypi.org/project/tidyenv/)
[![Python](https://img.shields.io/pypi/pyversions/tidyenv)](https://pypi.org/project/tidyenv/)
[![CI](https://github.com/LenaBarretta/tidyenv/actions/workflows/ci.yml/badge.svg)](https://github.com/LenaBarretta/tidyenv/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**Typed environment variables with friendly errors.** Built-in `.env` support. Zero dependencies.

```python
from tidyenv import env

PORT = env.int("PORT", default=8000)
DEBUG = env.bool("DEBUG", default=False)
HOSTS = env.list("ALLOWED_HOSTS", default=["localhost"])
DATABASE_URL = env.str("DATABASE_URL")
```

Each line converts the type, applies the default, and if something is wrong, says exactly what:

```text
tidyenv.EnvError: 1 environment problem:
  - PORT: expected an integer (got 'eighty')
```

## Why

| | Plain `os.environ` | tidyenv |
| --- | --- | --- |
| Number with a default | `int(os.environ.get("PORT", "8000"))` | `env.int("PORT", default=8000)` |
| Bad number | `ValueError: invalid literal for int() with base 10: 'eighty'` (which variable?) | `PORT: expected an integer (got 'eighty')` |
| Missing variable | `KeyError: 'DB_URL'` | `DB_URL: is not set` |
| Empty value `DB_URL=` | silently `""` | treated as not set |
| Boolean | `os.environ.get("DEBUG", "").lower() in ("1", "true", "yes")`, and a typo like `ture` silently means `False` | `env.bool("DEBUG", default=False)`, and `ture` is an error |
| List | `[h.strip() for h in os.environ.get("HOSTS", "").split(",") if h.strip()]` | `env.list("HOSTS")` |
| List of numbers | the same, plus `int()` on every item | `env.list("PORTS", of=int)` |
| One of several values | `if mode not in ("dev", "prod"): raise ...` | `env.choice("MODE", ["dev", "prod"])` |
| Secrets in errors | the value ends up in your logs | `secret=True` shows `***` |
| `.env` file | `pip install python-dotenv` + `load_dotenv()` | the same `load_dotenv()`, built in |
| Types for mypy / IDE | `str \| None`, cast it yourself | `env.int` returns `int` |
| Several broken variables | crash, fix, redeploy, crash on the next one | `env.collect()` lists them all at once |

One line per variable, and every error names the variable and says what is wrong with it.

## Install

```bash
pip install tidyenv
```

Python 3.9+.

## Usage

| Reader | Example value | Returns |
| --- | --- | --- |
| `env.str(name)` | `hello` | `str` (stripped) |
| `env.int(name)` | `8000`, `1_000` | `int` |
| `env.float(name)` | `0.25` | `float` (`nan` and `inf` are rejected) |
| `env.bool(name)` | `true/false`, `yes/no`, `on/off`, `1/0`, any case | `bool` |
| `env.list(name, sep=",", of=str)` | `a, b, c` | `list` (use `of=int` to convert items; `int`, `float` and `bool` follow the rules above) |
| `env.choice(name, choices)` | `prod` | `str` that must be in `choices` |
| `env.path(name, must_exist=False)` | `~/data` | `pathlib.Path` with `~` expanded |
| `env.json(name)` | `{"a": 1}` | parsed JSON |

Every reader takes an optional `default`. Without one, a missing or empty variable is
an error. With one, the default is returned instead, and type checkers know the result
is `int | <type of default>`.

### `.env` files

**Coming from python-dotenv?** Change the import, nothing else:

```python
from tidyenv import load_dotenv  # was: from dotenv import load_dotenv

load_dotenv()
```

`load_dotenv`, `dotenv_values` and `find_dotenv` take the same arguments and give the
same results as python-dotenv 1.2's:

- the same file syntax: `export`, comments, quotes, values spanning several lines,
  `${VAR}` and `${VAR:-default}`;
- `.env` is looked up starting next to the calling file, then in its parents;
- values go into `os.environ`, and variables that are already set are kept unless
  `override=True`, so the first file you load wins;
- `PYTHON_DOTENV_DISABLED=1` turns loading off.

The test suite checks this against python-dotenv itself on thousands of generated
files. Not included: `set_key`, `unset_key`, `get_key` and the `dotenv` command.

Then read the values with types. `env` reads `os.environ`, so it sees them:

```python
from tidyenv import env, load_dotenv

load_dotenv()
PORT = env.int("PORT", default=8000)
```

**Without touching `os.environ`.** `env.read_dotenv()` follows the same rules but keeps
the values inside `env`, and a line it can't parse is an error naming the file and line
(python-dotenv only logs a warning):

```python
env.read_dotenv()  # ./.env in the current directory, if it exists
env.read_dotenv("config/dev.env", required=True)
```

Need just the parser? `tidyenv.parse_dotenv(text)` returns a `dict` (without `${VAR}`
expansion).

### All errors at once (optional)

By default the first bad variable raises `EnvError`. If you'd rather see every
problem in one go, wrap your reads in `env.collect()`:

```python
with env.collect():
    PORT = env.int("PORT", default=8000)
    DATABASE_URL = env.str("DATABASE_URL")
    API_KEY = env.str("API_KEY", secret=True)
```

```text
tidyenv.EnvError: 3 environment problems:
  - PORT: expected an integer (got 'eighty')
  - DATABASE_URL: is not set
  - API_KEY: is not set
```

Failed reads return `None` inside the block, so only use the values after it exits.

### More

**Secrets.** Pass `secret=True` and the raw value is shown as `***` in error messages,
including errors about single `env.list` items.

**Prefixes and custom sources.** Build your own reader:

```python
from tidyenv import Env

env = Env(prefix="MYAPP_")  # reads MYAPP_PORT for env.int("PORT")
test_env = Env(environ={"PORT": "1"})  # any mapping, handy in tests
```

**Handling errors.** `EnvError.problems` is a list of `Problem(name, message)`, so you
can print them your own way.

## License

MIT. The `.env` support is adapted from
[python-dotenv](https://github.com/theskumar/python-dotenv) (BSD-3-Clause, see
[LICENSES/python-dotenv.txt](LICENSES/python-dotenv.txt)); thanks to its authors.
tidyenv is not affiliated with or endorsed by the python-dotenv project.
