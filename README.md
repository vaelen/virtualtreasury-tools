# vtextract

> **Proprietary and confidential.** Copyright 2026, Andrew C. Young
> <andrew@vaelen.org>. All rights reserved. This is not open-source software;
> see [LICENSE](LICENSE).

Download resources from [virtualtreasury.ie](https://virtualtreasury.ie) — full
-resolution images, metadata, and transcriptions — into a resumable local
archive. See the design spec in
`docs/superpowers/specs/2026-05-26-virtualtreasury-extractor-design.md`.

## Install

Uses [uv](https://docs.astral.sh/uv/). `uv sync` creates the virtualenv,
installs the dependencies from the committed `uv.lock`, and installs the
`vtextract` package itself in editable mode:

```bash
uv sync --extra dev
```

### Install the `vtextract` command

To run `vtextract` directly from any directory — without `uv run` and without
being inside the repo — install it as a uv-managed tool. From the repo root:

```bash
uv tool install --editable .
```

This installs the `vtextract` command into an isolated environment and links it
onto your PATH. `--editable` points that environment at this working tree, so
edits to `src/vtextract/` take effect immediately; you only need to re-run the
command if the dependencies change.

If the command isn't found afterward, ensure uv's bin directory is on your PATH
(then open a new shell):

```bash
uv tool update-shell
```

Verify from a directory outside the repo:

```bash
vtextract --help
```

To remove it later:

```bash
uv tool uninstall vtextract
```

## Credentials

The backend requires an HTTP Basic credential (the same one the public site's
JavaScript sends). Provide it via the environment — it is never stored in the
repo:

```bash
export VT_AUTH="<base64 user:pass token>"
# or
export VT_USERNAME="..." VT_PASSWORD="..."
```

Optional: `VT_BASE_URL`, `VT_DELAY` (seconds between requests, default 0.5),
`VT_MAX_RETRIES`.

## Usage

Searches are built from explicit flags. A simple keyword search:

```bash
uv run vtextract houston --out ./archive --context-pages 1
```

Each **field flag** starts a search clause; the **operand flag** (default
`--all`) sets how its keywords combine; bare words are the keywords. Clauses
combine, and `--start`/`--end` filter by content date (`yyyy-mm-dd`):

```bash
uv run vtextract \
  --title --all memorial houston \
  --transcription --any castle watchmaker \
  --place --exact Dublin \
  --start 1650-01-01 --end 1760-12-31 --newest \
  --out ./archive --context-pages 1
```

- Field flags: `--keyword` (default), `--title`, `--transcription`,
  `--creator`, `--ref`, `--person`, `--place`.
- Operand flags: `--all` (default), `--any`, `--none`, `--exact`.
- Result order: `--relevance` (default), `--newest`, `--oldest`.

`--person`/`--place` rank results by knowledge-graph entity (the last one wins).
See [docs/search-query.md](docs/search-query.md) for exactly how the flags map
onto the backend request. Run `uv run vtextract --help` for the full list.

If you installed the `vtextract` command (see [Install](#install-the-vtextract-command)),
drop the `uv run` prefix and call `vtextract …` directly from anywhere.

Re-running the same (or an overlapping) search resumes: completed resources and
already-downloaded pages are skipped.

## Archive layout

```
archive/
  _state.json
  pages/<volumeId>/<pageFile>.jpg(.txt/.json)   # shared, one copy per physical page
  items/<isadgID>/metadata.json, manifest.json  # resources referencing their pages
```

## Tests

```bash
uv run pytest
```

Tests run entirely against committed sample responses in `docs/examples/`; they
never contact the live site or use the real credential.

## License

Proprietary. Copyright 2026, Andrew C. Young <andrew@vaelen.org>. All rights
reserved. No use, copying, modification, or distribution is permitted without
the prior written permission of the copyright holder. See [LICENSE](LICENSE).
