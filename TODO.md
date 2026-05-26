# TODO — follow-ups

Non-blocking items surfaced during code review of the initial implementation.
None affect correctness for the normal happy path; each is a deliberate
improvement to consider.

## Behavior

- [x] **CLI exit code on partial failure.** `cli.run` currently returns `0`
  even when some resources failed (matches the original spec). For scripting,
  return non-zero when `failed > 0` (e.g. `1`) so callers can detect partial
  runs without parsing stderr. See `src/vtextract/cli.py` (`run`).

- [x] **Checksum verification on resume.** Pages absent from `_state.json` are
  re-fetched, but pages already recorded are not re-verified against their
  stored `sha256`. A truncated/corrupt image written before a crash would
  survive a resume. Consider verifying the on-disk file against the recorded
  checksum in `Archive.has_page` (or a dedicated verify path) and re-fetching
  on mismatch. See `src/vtextract/archive.py` (`has_page`, `page_checksum`,
  `store_page`).

## Tests

- [x] **Resume across runs (CLI level).** Add a test that calls `cli.run` twice
  against the same search and asserts the second run skips the already-complete
  resource and issues no item/image requests.

- [x] **Throttle / backoff timing.** Client tests run with `delay=0.0` and a
  no-op `sleep_func`, so the rate-limit and exponential-backoff paths are never
  timed. Add a test that records the `sleep_func` calls and asserts the delay
  fires between requests and backoff grows per retry. See
  `src/vtextract/client.py` (`_throttle`, `_request`).

- [x] **Empty-canvas manifest.** Add a test for a resource whose manifest has
  zero canvases: it should complete with `pages == []` and no image requests.

## Robustness (minor)

- [x] **Friendlier error for non-Loris image URLs.** `schema.loris_filename`
  raises `IndexError` if an image URL lacks `/loris/`. It's caught at the
  resource level (marked failed), but a clearer error message would aid
  debugging if the API ever changes URL shape.

- [x] **Validate CLI numeric args.** `--page-size` accepts values `< 1` and
  `--context-pages` accepts negatives (the latter degrades gracefully to 0).
  Consider rejecting nonsensical values at parse time.
