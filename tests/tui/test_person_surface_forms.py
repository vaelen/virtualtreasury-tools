# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from vtextract.tui.screens.transcription import person_surface_forms


PEOPLE = [["John Smith", "Jno. Smith"], ["Patrick Ryan"]]


def test_picks_up_on_page_variant_of_searched_person():
    # Searching "John Smith" should surface this page's "Jno. Smith" variant,
    # returning each form whole (not split into words).
    forms = person_surface_forms("John Smith", PEOPLE)
    assert forms == ["John Smith", "Jno. Smith"]


def test_person_not_on_page_yields_nothing():
    assert person_surface_forms("William Young", PEOPLE) == []


def test_no_query_yields_nothing():
    assert person_surface_forms("", PEOPLE) == []
    assert person_surface_forms(None, PEOPLE) == []
