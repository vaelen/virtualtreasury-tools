# How a search is constructed

`vtextract` builds searches from explicit CLI flags. This document explains how
those flags map onto the request the [virtualtreasury.ie](https://virtualtreasury.ie)
backend expects, and how that relates to the `/search-results` URL you see in
the browser.

## URL vs. request body

The public site is an Angular SPA. When you search, the address bar shows a
`/search-results?...` URL whose query string carries the search parameters, e.g.

```
/search-results?kwList=memorial%20houston&kwList=castle&kwOperList=ALL&kwOperList=ANY
                &kwSearchFieldList=title&kwSearchFieldList=kwTranscription&...
```

But the actual data request the SPA makes is a **`POST`** to
`/IR_REST_V2/webapi/doc_search` with a **JSON body** (`Content-Type:
application/json`). The repeated query-string keys (`kwList` appears once per
clause) become **JSON arrays** in that body. `vtextract` builds this body
directly; it never parses a URL.

## The request body

A search with several clauses produces a body like this (captured from the
live site):

```json
{
  "indexDBName": "beyond_2022",
  "totalElementsInt": 100,
  "pageNumberInt": 0,
  "kwList": ["keyword search", "title search", "transcription search", "creator search",
             "reference code search", "person search", "place search", "second title search"],
  "kwOperList": ["ALL", "EXACT", "ANY", "NONE", "ALL", "ALL", "EXACT", "ANY"],
  "kwSearchFieldList": ["all", "title", "kwTranscription", "creator",
                        "referenceCode", "kg_label", "kg_label", "title"],
  "neOperList": [],
  "neComboSetList": [],
  "searchDocumentRepositoryNameList": [],
  "searchLinkTypeList": [],
  "searchThematicCollectionList": [],
  "searchSourceFormatList": [],
  "searchSourceGradeList": [],
  "searchContentDate_begin": "1200-01-01",
  "searchContentDate_end": "1870-12-31",
  "boostItemsWithKGEntityType": "Place",
  "resultSorting": "relevance"
}
```

### The three parallel arrays

`kwList`, `kwOperList`, and `kwSearchFieldList` are **parallel arrays**: index
`i` of each describes one search clause — its keywords, its boolean operand, and
the field it searches. They always have the same length (one entry per clause),
even for a single-clause search. Note a field may repeat (`title` appears twice
above): each `--field` flag on the command line is its own clause.

| Array | Meaning | Source |
|---|---|---|
| `kwList[i]` | the clause's keywords, joined by spaces | positional keywords |
| `kwOperList[i]` | `ALL` / `ANY` / `NONE` / `EXACT` | operand flag |
| `kwSearchFieldList[i]` | which field to search | field flag |

### Scalar fields

- `searchContentDate_begin` / `searchContentDate_end` — `yyyy-mm-dd` date range
  (`--start` / `--end`). Sent only when given; not validated by the tool.
- `boostItemsWithKGEntityType` — `"Person"` or `"Place"`. Ranks results by
  knowledge-graph entity type. Appears at most once; the **last** `--person`/
  `--place` flag wins. Omitted when neither is used.
- `resultSorting` — `"relevance"` (default), `"ascending"` (oldest content date
  first), or `"descending"` (newest first). Set by `--relevance` / `--oldest` /
  `--newest`.
- `indexDBName` — always `"beyond_2022"` (from config).
- `pageNumberInt` / `totalElementsInt` — pagination, managed by the tool.

### Always-empty scaffolding

The site always sends these as empty arrays; `vtextract` mirrors that:
`neOperList`, `neComboSetList`, `searchDocumentRepositoryNameList`,
`searchLinkTypeList`, `searchThematicCollectionList`, `searchSourceFormatList`,
`searchSourceGradeList`.

`searchDocumentRepositoryNameList` *would* let you filter by holding repository,
but its valid values are not known, so there is **no CLI flag** for it — it is
always sent empty.

## Flag → field mapping

| CLI flag | `kwSearchFieldList` value | Notes |
|---|---|---|
| `--keyword` | `all` | default when no field flag precedes the keywords |
| `--title` | `title` | |
| `--transcription` | `kwTranscription` | |
| `--creator` | `creator` | |
| `--ref` | `referenceCode` | |
| `--person` | `kg_label` | also sets `boostItemsWithKGEntityType = "Person"` |
| `--place` | `kg_label` | also sets `boostItemsWithKGEntityType = "Place"` |

| CLI flag | `kwOperList` value |
|---|---|
| `--all` | `ALL` (default) |
| `--any` | `ANY` |
| `--none` | `NONE` |
| `--exact` | `EXACT` |

## How the command line is parsed

Flags and keywords are read left to right. A **field flag** starts a new clause
and resets the operand to `--all`. An **operand flag** sets the operand for the
current clause. Bare words are keywords appended to the current clause. So:

```
vtextract --title --all memorial houston --transcription --any castle watchmaker \
          --place --exact Dublin --out ./archive
```

produces three clauses:

1. `title` / `ALL` / `"memorial houston"`
2. `kwTranscription` / `ANY` / `"castle watchmaker"`
3. `kg_label` / `EXACT` / `"Dublin"` (and `boostItemsWithKGEntityType = "Place"`)

If keywords appear with no preceding field flag, the field defaults to `all`
(`--keyword`). A literal keyword beginning with `-` is not supported (it is
treated as an unknown option).
