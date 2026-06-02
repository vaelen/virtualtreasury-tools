# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

from vtextract.index.db import IndexDB
from vtextract.index.models import PersonHit
from vtextract.names.models import meets_threshold


def people_search(db: IndexDB, name: str, *, confidence: str | None) -> list[PersonHit]:
    """Search people by name (canonical + aliases), best match first.

    ``confidence`` filters by the person's entry-level confidence at query time.
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
        if not meets_threshold(r["confidence"], confidence):
            continue
        page = (r["root_id"], r["page_key"])
        hits.append(PersonHit(
            canonical=r["canonical"], confidence=r["confidence"],
            root_id=r["root_id"], page_key=r["page_key"],
            items=sorted(items_by_page.get(page, [])), score=r["score"],
        ))
    hits.sort(key=lambda h: h.score)  # bm25: more negative = better
    return hits
