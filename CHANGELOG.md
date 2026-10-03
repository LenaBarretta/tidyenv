# Changelog

## 0.2.0 (2026-10-02)

Switching from python-dotenv is now a one-line import change.

- New: `load_dotenv`, `dotenv_values` and `find_dotenv`, with the same arguments and
  results as python-dotenv's. The tests compare them with python-dotenv itself.
- `.env` files are parsed the same way as by python-dotenv 1.2: values spanning
  several lines, `${VAR}` and `${VAR:-default}` expansion (`interpolate=False` turns
  it off), quoted keys, bare `KEY` lines, and the full set of quote escapes.
- Changed: when `env.read_dotenv()` reads several files, the first file to set a
  variable now wins, as with python-dotenv. In 0.1.0 the last one won.
- Changed: `${...}` in `.env` values is now expanded, and `\'` and `\\` are escapes
  inside single quotes.

## 0.1.0 (2026-10-02)

First release: `str`, `int`, `float`, `bool`, `list`, `choice`, `path` and `json`
readers, defaults, `secret=True`, prefixes, `env.collect()` for all-at-once errors,
and built-in `.env` loading with `env.read_dotenv()` and `parse_dotenv()`.
