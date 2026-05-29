# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from __future__ import annotations

from vtextract.index.db import IndexDB
from vtextract.index.models import SearchQuery, SearchResult


def search(db: IndexDB, q: SearchQuery) -> list[SearchResult]:
    """Run a SearchQuery and return ordered SearchResults."""
    candidate_ids: set[int] | None = None
    scores: dict[int, float] = {}
    matched_fields: dict[int, set[str]] = {}
    matched_pages: dict[int, list[tuple[str, str, str]]] = {}

    if q.text:
        candidate_ids = set()
        # title/description
        for isadg_id, score in db.item_fts_search(q.text, q.fields).items():
            candidate_ids.add(isadg_id)
            _record_score(scores, isadg_id, score)
            # which of title/description we searched
            for f in q.fields:
                if f in ("title", "description"):
                    matched_fields.setdefault(isadg_id, set()).add(f)
        # transcription
        if "transcription" in q.fields:
            page_hits = db.transcription_fts_search(q.text)
            best_page_score = {(r, p): s for r, p, s in page_hits}
            pages = list(best_page_score)
            for isadg_id, pgs in db.items_for_pages(pages).items():
                candidate_ids.add(isadg_id)
                matched_fields.setdefault(isadg_id, set()).add("transcription")
                matched_pages.setdefault(isadg_id, []).extend(pgs)
                for rt, pk, _role in pgs:
                    _record_score(scores, isadg_id, best_page_score[(rt, pk)])

    rows = db.filter_items(
        candidate_ids,
        date_type=q.date_type,
        date_from=q.date_from,
        date_to=q.date_to,
        volume=q.volume,
    )

    results: list[SearchResult] = []
    for row in rows:
        isadg_id = row["isadg_id"]
        results.append(
            SearchResult(
                isadg_id=isadg_id,
                title=row["title"],
                reference_code=row["reference_code"],
                repository=row["repository"],
                content_date=_fmt_date(row["content_begin"], row["content_end"]),
                created_date=_fmt_date(row["created_begin"], row["created_end"]),
                matched_fields=sorted(matched_fields.get(isadg_id, set())),
                matched_pages=matched_pages.get(isadg_id, []),
                score=scores.get(isadg_id, 0.0),
                path=row["path"],
                estimated_date=_fmt_date(row["estimated_begin"], row["estimated_end"]),
                estimated_source=row["estimated_source"],
            )
        )

    if q.text:
        # best (most negative) bm25 first; ties keep filter order (date asc)
        results.sort(key=lambda r: r.score)
    start = max(q.offset, 0)
    # limit <= 0 means "no upper bound" (return everything from the offset on).
    if q.limit <= 0:
        return results[start:]
    return results[start : start + q.limit]


def _record_score(scores: dict[int, float], isadg_id: int, score: float) -> None:
    # bm25 is more-negative = better; keep the best (minimum).
    if isadg_id not in scores or score < scores[isadg_id]:
        scores[isadg_id] = score


def _fmt_date(begin: str | None, end: str | None) -> str | None:
    if not begin and not end:
        return None
    if begin == end:
        return begin
    return f"{begin}/{end}"
