# vtextract

> MIT licensed. Copyright (c) 2026 Andrew C. Young <andrew@vaelen.org>.
> See [LICENSE](LICENSE).

Download resources from [virtualtreasury.ie](https://virtualtreasury.ie) —
metadata and transcriptions by default, optionally with full-resolution images
(`--images`) — into a resumable local archive. See the design spec in
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

[browse]                           # vtbrowse TUI settings
theme         = "textual-dark"     # last theme picked in vtbrowse (Ctrl+P)
```

`[browse].theme` is written automatically: `vtbrowse` remembers the theme you
select from its command palette (Ctrl+P → "Change theme") and restores it on
the next launch.

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

By default this downloads each matching resource's metadata and per-page
transcriptions only — the full-resolution image files dwarf the rest of the
archive on disk and aren't always needed. Add `--images` to also download the
images:

```bash
uv run vtextract search houston --images --context-pages 1
```

Resume is mode-aware: a resource archived without `--images` is treated as
incomplete by a later `--images` run and gets its images backfilled, while a
fully-imaged resource is considered complete by a later metadata-only run and
skipped. Archives created before the flag existed are treated as fully imaged.

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
backfills any missing transcriptions. With `--images`, it also issues a `HEAD`
for every referenced image, comparing the server's `Content-Length` to the file
on disk; mismatched or missing images are re-downloaded and ones whose size
cannot be verified are reported as "unverified". Without `--images`, existing
image files on disk are left untouched. The full-archive `refresh` asks for
confirmation first (use `-y/--yes` to skip); `--refresh` on `search`/`get` does
the same for just those resources, and the same `--images` rule applies.

```bash
# re-fetch metadata + transcriptions for already-archived resources
vtextract search --refresh houston            # scoped to search results
vtextract get --refresh TNA-SP-63-356         # scoped to given resources
vtextract refresh                             # the whole archive (asks to confirm; -y to skip)

# include image verification (HEAD + re-download mismatches)
vtextract refresh --images
```

### Fetching specific resources

When you already know which resources you want, the `get` subcommand takes a
list of reference codes and/or numeric isadgIDs and pulls them directly,
skipping the search query. Everything downstream is identical to `search`
(downloads, dedupe, resume):

```bash
uv run vtextract get "TNA SO 1/14" 474234 --out ./archive --context-pages 1
uv run vtextract get "TNA SO 1/14" --images --out ./archive   # also pull images
```

A reference code may be written with spaces or slashes (`TNA SO 1/14`); each is
normalised to a dash (`TNA-SO-1-14`) before lookup. A purely numeric argument is
treated as an isadgID. A reference code that resolves to nothing is reported and
skipped without aborting the rest of the run.

A resource's IIIF manifest can cover every page in its volume, so `--images`
normally downloads them all. To pull images for just a few pages, pass
`--only-image-pages` a comma-separated list of page keys (the Loris image
filenames); only those pages' images are downloaded, while metadata and
transcriptions are still fetched for the whole resource. This is how `vtbrowse`
backfills images for an exported bundle without dragging down the entire volume:

```bash
uv run vtextract get 474234 --images \
  --only-image-pages IMC_1954_RoD_1_Page_253.jpg,IMC_1954_RoD_1_Page_254.jpg \
  --out ./archive
```

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

## Extracting people (names)

`vtextract names` runs a local-or-remote LLM over the page transcriptions in an
archive to pull out the people mentioned, writing a `<page_key>.names.json`
sidecar next to each `<page_key>.jpg.txt`. Each person is stored as a compact
`[canonical, *surface_forms]` array — the canonical (normalized/expanded) name
first, then the verbatim surface forms seen on that page. With no arguments it
processes the whole archive; pass reference codes and/or isadgIDs to scope the
run to just those resources' pages.

```bash
# extract people from every page transcription in the archive
vtextract names --archive ./archive

# scope to specific resources (reference codes and/or isadgIDs)
vtextract names "TNA SO 1/14" 474234 --archive ./archive
```

The pass is resumable: a page that already has a `.names.json` sidecar is
skipped. A page whose extraction fails *transiently* (network, rate-limit,
auth) leaves no sidecar so a later run retries it; a page that fails
*deterministically* is parked (see [Failed pages](#failed-pages) below). Use
`--force` to re-extract and overwrite existing sidecars. `--model M` overrides
the configured model and `-w/--workers N` the parallelism.

### Correcting the LLM with page notes

To steer extraction on a particular page, write a `<page_key>.notes.md` next to
its `<page_key>.jpg.txt` (e.g. `archive/pages/1234/0007.jpg.notes.md`). It is
free-form Markdown, sent to the LLM alongside the page text as a `NOTES` block
that overrides the default rules for that page: tell it who an ambiguous name
refers to, that a word is not a person, or anything else you know about the
document. Every chunk of a long page carries the same notes.

```markdown
"J. Smith" on this page is James Smith, not John Smith.
"Mrs Kelly" is Bridget Kelly (see page 41).
"Ormond" here is the estate, not a person.
```

Notes travel with the page in a `vtbrowse` bundle export. They are read only
when a page is extracted, so after adding or editing one re-run with `--force`
scoped to that resource:

```bash
vtextract names "TNA SO 1/14" --force --archive ./archive
```

Configure it with a `[names]` table in `~/.vt/vt.toml` (all optional, shown with
their defaults):

```toml
[ask]                            # vtbrowse's `a` (Ask); both default to [names]
model      = "gemini/gemini-2.5-flash"  # a vision-capable model gets the page image
api_base   = ""

[names]
model      = "ollama/llama3.1"   # any LiteLLM model name
api_base   = ""                  # override the model's API base URL (e.g. a local Ollama)
chunk_size = 64000               # transcription chunk size (characters)
overlap    = 512                 # overlap between chunks
workers    = 1                   # parallel pages
dense_threshold   = 5000         # pages longer than this use dense_chunk_size (0 disables)
dense_chunk_size  = 3000         # smaller chunk size for dense/long pages (loop guardrail)
max_output_tokens = 12000        # per-call output-token cap (repetition-loop guardrail)
```

Long, dense pages (name registries, garbled OCR) are what drive the model into
runaway-output loops. **Adaptive chunking** bounds that: a page over
`dense_threshold` characters is split into `dense_chunk_size`-character windows
instead of one large chunk, so each generation is short — lowering the loop
probability and capping the wasted output when one still occurs. Normal-sized
pages are unaffected (a single chunk). Set `dense_threshold = 0` to disable.

`max_output_tokens` bounds the output of each LLM call. Dense, repetitive
transcriptions (e.g. will indexes) can push a model into a repetition loop that
runs to its full output ceiling, producing truncated, unparseable JSON and
burning the maximum tokens per call. The cap turns that runaway into a cheap,
detectable truncation, which the tool then retries once at a higher temperature
to break the loop. The default (12,000) sits well above what real pages produce,
so legitimate extractions are unaffected; lower it to fail loops faster and
cheaper, or raise it if you have pages that genuinely yield more names than fit.

### Failed pages

A page whose extraction fails *deterministically* — the model's output was
truncated at the token cap (a repetition loop) or it never returned valid JSON
even after a retry — is *parked*: a `<page_key>.names.error.json` sidecar is
written next to the transcription recording the error class, attempt count and
the provider message. Parked pages are **skipped** by normal re-runs (so they
don't burn tokens every time) and the run's summary reports how many are parked.

```bash
# list parked pages (page, error class, attempts, date, message) without an LLM
vtextract names --list-failed --archive ./archive

# re-attempt parked pages (e.g. after switching --model or lowering chunk_size)
vtextract names --retry-failed --archive ./archive
```

Both accept the same optional reference-code / isadgID scoping as a normal run.
`--force` also re-attempts parked pages. A successful extraction removes the
page's error sidecar. Transient failures (rate-limit, auth, network,
model-not-found) are **not** parked — they are logged and retried on the next
run, as before.

After extracting, run `vtindex build` to ingest the sidecars into the index,
then search people by canonical name **or** any alias surface form:

```bash
vtindex build --archive ./archive
vtindex people "Houston" --archive ./archive
vtindex people "Houston" --json --archive ./archive
```

Each result reports the volume/page where the person appears and the
items that reference that page. `--json` emits structured output for scripting.

### Benchmarking models (`vtnamebench`)

`vtnamebench bench.toml` runs the exact `vtextract names` extraction over a
folder of `.txt` files for several models and prints a comparison report.

```toml
# bench.toml
input = "~/foo/bar"
models = [
  "anthropic/claude-haiku-4-5",
  "anthropic/claude-sonnet-4-6",
  "openai/gpt-4.1-mini",
  "openai/gpt-4.1",
  "ollama/llama3",
]

# Optional: a custom endpoint per model (e.g. a local Ollama server).
# Models not listed here are routed by their `provider/` prefix.
[api_base]
"ollama/llama3" = "http://localhost:11434"
```

Run with `uv run vtnamebench bench.toml`. For each model it writes
`<input>/models/<model>/<file>.txt.names.json` sidecars and a `times.json`
(filename → seconds), skipping files already processed by that model
(`--force` re-runs). Before processing a model it preflights/warms it (so the
first file is not paying a local model's cold-start load cost, and auth/config
errors surface immediately), and it evicts the previous local (Ollama) model
before loading the next to ease GPU pressure.

It then prints a table comparing the number of names found (counting each
person and each alias) and the per-file timing distribution —
**min, max, median, mean** seconds — plus **ms/byte**, which normalizes for
document length so models are comparable regardless of how long each
transcription happens to be. The report includes any model with prior on-disk
data, even if it was fully skipped this run.

## Browsing the archive interactively

`vtbrowse` is a keyboard-driven TUI (built with [Textual](https://textual.textualize.io/))
that sits on top of an existing archive + its `vtindex` index. After building the
index once (`vtindex build`), you can browse volumes, read transcriptions, search
locally, and curate a **Bundle** of pages you want to keep — without re-running
`vtextract`.

```bash
uv run vtbrowse                        # uses archive from ~/.vt/vt.toml
uv run vtbrowse --archive ./archive    # or point it at a specific archive
```

### Basic flow

The main pane's title shows what it's listing — `Volumes`, the volume title
when viewing its pages, or `Search Results` — and its bottom border shows the
visible row range, e.g. `12-37 of 100`, updating as you scroll.

- **Home** — a list of indexed volumes. Press `Enter` to drill into one.
- **Volume** — pages in order. Press `Enter` to open a page.
- **Page** — metadata on the left, transcription on the right. Press `Space` to
  toggle the page into / out of your Bundle. Press `Enter` in the transcription
  pane to swap between the transcription text and the scanned page image; if no
  image is on disk, a hint is shown to re-run `vtextract` with `--images`.
  Press `n` to open the page's notes (`<page_key>.notes.md`, see
  [page notes](#correcting-the-llm-with-page-notes)) in a Markdown editor
  beside the page; `n` from the page or `Esc` in the editor closes it. The
  notes are saved whenever the editor loses focus or closes, so `P` and `a`
  always see what you typed. Whitespace-only notes delete the file.
  Press `p` to show the people extracted by `vtextract names` in a read-only
  table on the right (below the notes editor if it is open); `p` again or
  `Esc` closes it, and `n` from it toggles the notes editor. If the page has
  no `.names.json` yet, a message says so.
  Press `a` to **ask** the LLM a question about the page: the question is sent
  with everything known about the page (volume data, transcription, your
  notes, the extracted people, and the page image when on disk) and the
  answer appears in a third view that `Enter` cycles to after text and image.
  Follow-up questions see the earlier ones. `w` writes the page's questions
  and answers to a Markdown file. Answers are kept while you page through the
  volume and dropped when you leave the document.
  Press `P` (shift+p) to **re-extract names** for the page with the current
  notes; the index is rebuilt afterwards and an open people table refreshes.
- **`s`** — save the Bundle to `~/.vt/bundle.json` (or the path in config).
- **`x`** — export the Bundle to a folder (transcriptions + metadata
  JSON; optional images).
- **`o`** — open a saved Bundle.

### Searching

- **`f`** — search the local `vtindex` index. Results open as a page list;
  navigate and open pages just like in the volume view.
- **`e`** — run a single-clause `vtextract search` against the live website.
  Newly downloaded resources are automatically indexed afterward. Requires a
  stored credential (`vtextract auth`).

### Other bindings

- **`v`** / **`r`** — jump to the Volumes list / the last search results.
- **`i`** — show the Info dialog for the current volume, page, or item.
- **`b`** — build / rebuild the `vtindex` index in the background.
- **`q`** — exit (confirms first if the Bundle has unsaved changes).
- **`F1` / `?`** — show all key bindings.

### Bundle

A Bundle is a curated list of physical pages (by volume + page key). It persists
as a JSON file so you can save, reopen, and edit it across sessions. Exporting
writes one subfolder per volume, with each page's transcription text, its
`page.json` metadata, and (if the archive has them) the image file. See
`docs/superpowers/specs/2026-05-29-vtbrowse-tui-design.md` for the full Bundle
JSON format and export folder layout.

## Tests

```bash
uv run pytest
```

Tests run entirely against committed sample responses in `docs/examples/`; they
never contact the live site or use the real credential.

## License

MIT. Copyright (c) 2026 Andrew C. Young <andrew@vaelen.org>. See
[LICENSE](LICENSE).
