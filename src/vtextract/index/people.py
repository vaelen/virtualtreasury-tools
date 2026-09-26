# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# SPDX-License-Identifier: MIT

from __future__ import annotations

from vtextract.index.db import IndexDB
from vtextract.index.models import PersonHit


def people_search(db: IndexDB, name: str) -> list[PersonHit]:
    """Search people by name (canonical + aliases), best match first.

    Each hit carries the page it was found on and the items referencing that page.
    """
    if not name.strip():
        return []
    raw = db.person_fts_search(name)
    pages = sorted({(r["root_id"], r["page_key"]) for r in raw})
    items_by_page: dict[tuple[str, str], list[int]] = {}
    for isadg_id, links in db.items_for_pages(pages).items():
        for root_id, page_key, _role in links:
            items_by_page.setdefault((root_id, page_key), []).append(isadg_id)

    hits: list[PersonHit] = []
    for r in raw:
        page = (r["root_id"], r["page_key"])
        hits.append(PersonHit(
            canonical=r["canonical"],
            root_id=r["root_id"], page_key=r["page_key"],
            items=sorted(items_by_page.get(page, [])), score=r["score"],
        ))
    hits.sort(key=lambda h: h.score)  # bm25: more negative = better
    return hits
