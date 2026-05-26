# Config file + `auth` command — design

Date: 2026-05-27

## Goal

Replace the `VT_*` environment-variable configuration with a TOML config file
at `~/.vt/vt.toml`, and add a `vtextract auth` command that stores the basic
auth credential into that file. The CLI gains explicit subcommands
(`search`, `auth`); running `vtextract` with no subcommand prints help and
exits non-zero.

The config file is intended to be **shared with other utilities** that use the
same archive. Therefore the archive location lives at the top level, and all
vtextract-specific settings are namespaced under an `extract` table.

## Config file: `~/.vt/vt.toml`

```toml
# vtextract configuration
archive = "~/.vt/archive"          # shared across utilities; top-level on purpose

[extract.auth]
token = "dXNlcjpwYXNz"             # base64 of "user:pass"; sent as "Authorization: Basic <token>"

[extract.http]
base_url      = "https://by2022-prod.adaptcentre.ie"
user_agent    = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:151.0) Gecko/20100101 Firefox/151.0"
index_db_name = "beyond_2022"
delay         = 0.5
max_retries   = 3
```

- Only `[extract.auth].token` has no default. The `[extract.http]` table and
  every key in it are optional and rarely edited. `archive` defaults to
  `~/.vt/archive`.
- `~` is expanded on load (both `archive` and the config path itself).
- The file is written mode `0600` (it holds a credential); `~/.vt/` is created
  mode `0700`.
- All `VT_*` environment variables are **removed**. There is no env fallback.

## Module changes

### `config.py`

- `Config` dataclass:
  - `auth_header: str | None` (was `str`) — `None` when no token is configured.
  - new `archive: Path` field (defaults to `~/.vt/archive`, `~`-expanded).
  - keeps `base_url`, `user_agent`, `index_db_name`, `delay`, `max_retries`.
- `load_config(path: Path | None = None) -> Config`:
  - default path `~/.vt/vt.toml`.
  - reads with stdlib `tomllib` (`rb` mode). Missing file → all defaults,
    `auth_header=None`.
  - maps `[extract.auth].token` → `auth_header = "Basic <token>"` (or `None`),
    `[extract.http].*` → the http fields, top-level `archive` → `Config.archive`.
  - no longer accepts an `env` dict; no `VT_*` handling remains.
- `default_config_path() -> Path` → `~/.vt/vt.toml` (`~`-expanded).
- `make_token(username: str, password: str) -> str` — pure base64 of
  `f"{username}:{password}"` (factored out of the old inline code).
- `set_token(path: Path, token: str) -> None` — read-merge-write: load the
  existing TOML (if any) into a dict, set `data["extract"]["auth"]["token"]`,
  write the whole dict back. Preserves `archive` and `[extract.http]` so
  running `auth` never clobbers other settings.
- `write_config(path: Path, data: dict) -> None` — hand-rolled TOML emitter:
  - emits top-level scalar keys first, then `[extract.auth]` / `[extract.http]`
    tables (nested-table headers written as `[extract.auth]`).
  - value types: `str` (quoted, with `"`/`\` escaped), `int`, `float`.
  - `mkdir(parents=True, exist_ok=True)` on the parent (`0700`), then write,
    then `chmod(0600)`.

No third-party dependency is added; `httpx` remains the only runtime dep.

### `cli.py` — subcommands

- Two subcommands:
  - **`vtextract search <criteria...> [--out PATH] [--config PATH]
    [--start/--end] [--relevance/--newest/--oldest] [--context-pages]
    [--page-size]`**
    - the existing `split_and_group` walker runs on the tokens after `search`.
    - `--out` is now **optional**; defaults to `config.archive`.
    - `--config` overrides the config path (default `~/.vt/vt.toml`).
    - if `config.auth_header is None`, exit non-zero with:
      `No credentials configured. Run \`vtextract auth\`.`
  - **`vtextract auth [username] [--config PATH]`**
    - no username → `getpass.getpass("Basic auth token (base64): ")`, store
      verbatim.
    - with username → `getpass.getpass("Password: ")`, compute
      `make_token(username, password)`, store the token. The password is never
      written to disk or echoed.
    - on success, print the path written (never the token).
- **No subcommand / unknown first token** → print help, exit non-zero. No
  implicit default to `search`.
- Implementation note: detect the subcommand by peeking `argv[0]` before
  handing the remainder to the appropriate parser/walker (argparse subparsers
  do not compose with the custom criteria walker, so dispatch is manual).
- `_make_transport()` test seam unchanged. Prompts go through `getpass.getpass`
  so tests can monkeypatch them.

## Testing

- `test_config.py` rewritten to use fixture TOML written into `tmp_path`
  instead of env dicts:
  - defaults when file is absent (`auth_header is None`, default `archive`,
    default http settings).
  - token present → `auth_header == "Basic <token>"`.
  - `[extract.http]` overrides applied.
  - `set_token` merges: writing a token preserves an existing `archive` and
    `[extract.http]` values; round-trips through `load_config`.
- `test_cli.py`:
  - update existing search tests to prefix `search`.
  - `auth` with direct token (monkeypatched `getpass`, `--config tmp`) writes
    `[extract.auth].token`.
  - `auth <username>` computes the digest and stores it; password not stored.
  - `search` with no configured credentials exits non-zero with the guidance
    message.
- All tests remain offline, using `httpx.MockTransport` + committed fixtures
  for the network path and `tmp_path` for config files.

## Docs

- `README.md`: replace env-var usage with `vtextract auth` + `vtextract search`.
- `CLAUDE.md`: update the "credentials come only from the environment" guidance
  and the example invocation to the `search` subcommand and config file.
- `docs/search-query.md`: update example invocations to `vtextract search ...`.

## Out of scope

- No migration shim from the old `VT_*` env vars (clean break, as agreed).
- No backward-compatible bare `vtextract <keywords>` form.
- No config keys for the other utilities that will share the file; only the
  shared top-level `archive` and the `extract` namespace are defined here.
