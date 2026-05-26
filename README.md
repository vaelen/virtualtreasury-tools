# vtextract

> **Proprietary and confidential.** Copyright 2026, Andrew C. Young
> <andrew@vaelen.org>. All rights reserved. This is not open-source software;
> see [LICENSE](LICENSE).

Download resources from [virtualtreasury.ie](https://virtualtreasury.ie) — full
-resolution images, metadata, and transcriptions — into a resumable local
archive. See the design spec in
`docs/superpowers/specs/2026-05-26-virtualtreasury-extractor-design.md`.

## Install

```bash
python -m pip install -e ".[dev]"
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

```bash
vtextract "https://virtualtreasury.ie/search-results?kwList=houston&kwOperList=ALL&\
searchContentDate_begin=1650-01-01&searchContentDate_end=1760-12-31&\
kwSearchFieldList=kwTranscription&resultSorting=relevance" \
  --out ./archive --context-pages 1
```

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
python -m pytest
```

Tests run entirely against committed sample responses in `docs/examples/`; they
never contact the live site or use the real credential.

## License

Proprietary. Copyright 2026, Andrew C. Young <andrew@vaelen.org>. All rights
reserved. No use, copying, modification, or distribution is permitted without
the prior written permission of the copyright holder. See [LICENSE](LICENSE).
