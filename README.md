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
vtextract
```

To remove it later:

```bash
uv tool uninstall vtextract
```

## Configuration

Settings live in a TOML file at `~/.vt/vt.toml`. The shared `archive` location
is at the top level; vtextract's own settings are namespaced under `extract`:

```toml
archive = "~/.vt/archive"          # default; where downloads are stored

[extract.auth]
token = "<base64 user:pass token>"

[extract.http]                     # all optional, shown with their defaults
base_url      = "https://by2022-prod.adaptcentre.ie"
delay         = 0.5                # seconds between requests
max_retries   = 3
```

## Credentials

The backend requires an HTTP Basic credential (the same one the public site's
JavaScript sends). Store it with the `auth` command, which writes it to the
config file (mode `0600`); it is never stored in the repo:

```bash
vtextract auth <username>     # prompts for a password, stores the digest
# or
vtextract auth                # prompts for the base64 token directly
```

## Usage

Searches are built from explicit flags under the `search` subcommand. A simple
keyword search (downloads to the configured `archive` unless `--out` overrides):

```bash
uv run vtextract search houston --context-pages 1
```

Each **field flag** starts a search clause; the **operand flag** (default
`--all`) sets how its keywords combine; bare words are the keywords. Clauses
combine, and `--start`/`--end` filter by content date (`yyyy-mm-dd`):

```bash
uv run vtextract search \
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
onto the backend request. Run `uv run vtextract search --help` for the full
list.

If you installed the `vtextract` command (see [Install](#install-the-vtextract-command)),
drop the `uv run` prefix and call `vtextract …` directly from anywhere.

Re-running the same (or an overlapping) search resumes: completed resources and
already-downloaded pages are skipped.

### Refreshing already-archived resources

`refresh` re-fetches each item's metadata (detail, manifest, `volume.json`) and
issues a `HEAD` for every referenced image, comparing the server's
`Content-Length` to the file on disk. Mismatched or missing images are
re-downloaded; images whose size cannot be verified are reported as
"unverified". The full-archive `refresh` asks for confirmation first (use
`-y/--yes` to skip); `--refresh` on `search`/`get` does the same for just those
resources.

```bash
# re-fetch metadata + verify image sizes for already-archived resources
vtextract search --refresh houston            # scoped to search results
vtextract get --refresh TNA-SP-63-356         # scoped to given resources
vtextract refresh                             # the whole archive (asks to confirm; -y to skip)
```

### Fetching specific resources

When you already know which resources you want, the `get` subcommand takes a
list of reference codes and/or numeric isadgIDs and pulls them directly,
skipping the search query. Everything downstream is identical to `search`
(downloads, dedupe, resume):

```bash
uv run vtextract get "TNA SO 1/14" 474234 --out ./archive --context-pages 1
```

A reference code may be written with spaces or slashes (`TNA SO 1/14`); each is
normalised to a dash (`TNA-SO-1-14`) before lookup. A purely numeric argument is
treated as an isadgID. A reference code that resolves to nothing is reported and
skipped without aborting the rest of the run.

### Progress output

Both commands report progress on **stderr**. `search` first prints how many
matches it found (`get` how many resources you asked for), then a line before
and after each resource, and `skipping …` for anything already in the archive:

```
Found 42 matches.
fetching 474234...
done 474234
skipping 474235, already archived
fetching 474236...
done 474236
finished: 2 archived, 0 failed
```

In an interactive terminal these lines scroll above two live progress bars — an
overall bar across all resources and a per-resource bar that advances as each
page is downloaded. When output is piped or redirected the bars are suppressed
automatically and only the plain lines above are written, so logs stay clean.
Status output is on stderr, leaving stdout free.

## Archive layout

```
archive/
  _state.json
  pages/<volumeId>/<pageFile>.jpg(.txt/.json)   # shared, one copy per physical page
  items/<isadgID>/metadata.json, manifest.json  # resources referencing their pages
```

## Searching the archive

`vtindex` builds a local SQLite/FTS5 index over an archive so you can search it
without re-reading every file. The index lives at `<archive>/index/`.

```bash
# build (or incrementally refresh) the index after a download
vtindex build --archive ./archive

# keyword search (title + description + transcription by default)
vtindex search "houston" --archive ./archive

# restrict fields, add a time frame and a volume, get JSON for scripting
vtindex search "deed" --in title,transcription \
  --from 1700 --to 1760 --date-type content --volume 208925 \
  --archive ./archive --json

# discover volume ids/labels, or inspect the index
vtindex volumes --archive ./archive
vtindex stats   --archive ./archive

# show a page's previous / current / next neighbours in its volume
vtindex page <root_id>/<page_key> --archive ./archive [--json]
```

The archive dir defaults to the `archive` setting in `~/.vt/vt.toml` (the same
config `vtextract` uses; override the file with `--config` or the dir with
`--archive`). Exit codes follow the
grep convention: `0` = at least one match, `1` = no matches, `2` = error (e.g.
the index has not been built yet). Re-running `vtindex build` is incremental —
it only reads files whose size/mtime changed since the last build.

- `vtindex page <root_id>/<page_key>` — show a page's previous / current / next
  neighbours in its volume, with resolved file paths (`--json` for structured
  output). Page ordering comes from the volume's `volume.json`, which is written
  during extraction with `--context-pages >= 1`; re-extract an existing archive
  to populate ordering for older volumes.

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
