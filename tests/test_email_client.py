from datetime import datetime, timedelta, timezone

from backstage_agent.email_client import _is_within_window, _search_query, _subject_matches


def test_search_query_adds_since_date():
    cutoff = datetime(2026, 7, 5, tzinfo=timezone.utc)

    query = _search_query('(FROM "backstage")', cutoff, ["basic filter"])

    assert query == '(FROM "backstage" SUBJECT "basic filter" SINCE "05-Jul-2026")'


def test_is_within_window_filters_old_messages():
    cutoff = datetime.now(timezone.utc) - timedelta(days=1)

    assert _is_within_window(datetime.now(timezone.utc), cutoff)
    assert not _is_within_window(datetime.now(timezone.utc) - timedelta(days=2), cutoff)


def test_subject_matches_all_keywords_case_insensitive():
    assert _subject_matches("1 New Roles Available for basic filter - Jul 5", ["basic filter"])
    assert not _subject_matches("Saved applications reminder", ["basic filter"])
