# Copyright 2026, Andrew C. Young <andrew@vaelen.org>
# All rights reserved

from vtextract.tui.screens.transcription import person_surface_forms


PEOPLE = [["John Smith", "Jno. Smith"], ["Patrick Ryan"]]


def test_picks_up_on_page_variant_of_searched_person():
    # Searching "John Smith" should surface this page's "Jno. Smith" variant,
    # returning each form whole (not split into words).
    forms = person_surface_forms("John Smith", PEOPLE)
    assert forms == ["John Smith", "Jno. Smith"]


def test_same_first_name_neighbour_not_highlighted():
    # "John Doe" shares a first name with the query but is a different person;
    # only the searched person's forms should highlight (index search ANDs all
    # query words, so highlighting must too).
    people = [["John Smith", "Jno. Smith"], ["John Doe"]]
    assert person_surface_forms("John Smith", people) == ["John Smith", "Jno. Smith"]


def test_query_word_found_only_in_alias_still_matches():
    # All query words must appear across the person's combined forms, not
    # necessarily within a single form.
    people = [["Thomas Young", "Thos. Young"], ["Thomas Lyster"]]
    assert person_surface_forms("Thos Young", people) == ["Thomas Young", "Thos. Young"]


def test_single_word_query_matches_every_person_bearing_it():
    people = [["John Smith"], ["John Doe"], ["Patrick Ryan"]]
    assert person_surface_forms("John", people) == ["John Smith", "John Doe"]


def test_person_not_on_page_yields_nothing():
    assert person_surface_forms("William Young", PEOPLE) == []


def test_no_query_yields_nothing():
    assert person_surface_forms("", PEOPLE) == []
    assert person_surface_forms(None, PEOPLE) == []
